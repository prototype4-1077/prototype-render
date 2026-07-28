"""Prepare/finalize a surgical scene revision using cached scene masters.

Approved scene masters are hash-locked and kept. Rejected scene masters and their
visual source artifacts are removed so the normal resumable builder regenerates
only those scenes. Narration text/timing and the approved delivery audio are
fingerprint-locked throughout.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from editorial_timeline import narration_fingerprint
import locked_audio
from revision_cache import validate_manifest

REVISION_DECISIONS = {"revise", "revision", "needs_revision"}
APPROVAL_DECISIONS = {"approved", "approve"}
RUNTIME_KEYS = {
    "clip",
    "clip_fingerprint",
    "stock_id",
    "pexels_id",
    "stock_frame_url",
    "stock_frame_url_checked",
    "source_url",
    "motion_verified",
    "motion_evidence",
    "motion_compiled",
    "motion_source",
    "hero_generated",
    "hero_raw_signature",
    "enhanced_source_image",
    "still_reference_signature",
    "pure_generated_still",
    "still_enhancement_steps",
    "still_reference_generation_model",
    "still_enhancement_version",
    "still_enhanced",
}


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _feedback_path(build_dir: Path) -> Path:
    for name in ("scene-feedback.request.json", "scene-review-feedback.json"):
        path = build_dir / name
        if path.exists():
            return path
    raise SystemExit("no scene feedback file found")


def _decisions(build_dir: Path, scene_count: int) -> tuple[list[int], list[int], dict[int, str]]:
    feedback = _load(_feedback_path(build_dir))
    items = feedback.get("scenes") or []
    if len(items) != scene_count:
        raise SystemExit(f"feedback has {len(items)} scenes; script has {scene_count}")
    revised: list[int] = []
    approved: list[int] = []
    comments: dict[int, str] = {}
    seen: set[int] = set()
    for item in items:
        index = int(item.get("scene_index"))
        if index in seen or index < 0 or index >= scene_count:
            raise SystemExit(f"invalid or duplicate scene index: {index}")
        seen.add(index)
        decision = str(item.get("decision") or "").lower()
        comments[index] = str(item.get("comments") or "")
        if decision in REVISION_DECISIONS:
            revised.append(index)
        elif decision in APPROVAL_DECISIONS:
            approved.append(index)
        else:
            raise SystemExit(f"scene {index + 1} is not fully reviewed")
    if not revised:
        raise SystemExit("selective revision requires at least one rejected scene")
    return sorted(approved), sorted(revised), comments


def _segment_paths(build_dir: Path, scene_index: int) -> list[Path]:
    return [
        build_dir / f"youtube_seg_{scene_index:02d}.mp4",
        build_dir / f"seg_{scene_index:02d}.mp4",
    ]


def _visual_artifacts(build_dir: Path, scene_index: int) -> list[Path]:
    patterns = (
        f"clip_{scene_index:02d}.mp4",
        f"hero_{scene_index:02d}*",
        f"stock_ref_{scene_index:02d}*",
        f"reference_{scene_index:02d}*",
        f"source_{scene_index:02d}*",
        f"enhanced_{scene_index:02d}*",
    )
    found: dict[str, Path] = {}
    for pattern in patterns:
        for path in build_dir.glob(pattern):
            if path.is_file():
                found[str(path)] = path
    return list(found.values())


def prepare(build_dir: str | Path) -> dict[str, Any]:
    build_dir = Path(build_dir).resolve()
    cache_report = validate_manifest(build_dir)
    if not cache_report["passed"]:
        raise SystemExit("revision cache failed validation: " + json.dumps(cache_report["failures"]))
    audio_report = locked_audio.verify(build_dir)
    if not audio_report["passed"]:
        raise SystemExit("approved delivery audio is not safely locked")
    script_path = build_dir / "script.json"
    script = _load(script_path)
    scenes = script.get("scenes") or []
    approved, revised, comments = _decisions(build_dir, len(scenes))
    baseline: dict[str, dict[str, str | None]] = {"approved": {}, "revised": {}}
    for index in approved:
        for path in _segment_paths(build_dir, index):
            if path.exists():
                baseline["approved"][path.name] = _sha256(path)
    for index in revised:
        for path in _segment_paths(build_dir, index):
            if path.exists():
                baseline["revised"][path.name] = _sha256(path)
        for path in _segment_paths(build_dir, index) + _visual_artifacts(build_dir, index):
            path.unlink(missing_ok=True)
        for key in RUNTIME_KEYS:
            scenes[index].pop(key, None)
        scenes[index]["revision_note"] = comments.get(index, "")

    for pattern in (
        "final*.mp4",
        "video_noaudio.mp4",
        "youtube_video_noaudio.mp4",
        "alts_sheet.jpg",
        "scene-review.html",
        "scene-review.json",
        "editorial.otio",
        "editorial_manifest.json",
        "editorial-verification.json",
        "export-verification*.json",
        "detected-scenes*.csv",
    ):
        for path in build_dir.glob(pattern):
            path.unlink(missing_ok=True)

    _write(script_path, script)
    manifest = {
        "schema_version": 2,
        "slug": script.get("slug") or build_dir.name,
        "prepared_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "approved_scenes": approved,
        "revised_scenes": revised,
        "narration_fingerprint": narration_fingerprint(script),
        "locked_audio_sha256": audio_report.get("locked_audio_sha256"),
        "baseline_segment_hashes": baseline,
        "status": "prepared",
    }
    _write(build_dir / "selective-revision.json", manifest)
    return manifest


def finalize(build_dir: str | Path) -> dict[str, Any]:
    build_dir = Path(build_dir).resolve()
    manifest_path = build_dir / "selective-revision.json"
    manifest = _load(manifest_path)
    script = _load(build_dir / "script.json")
    failures: list[dict[str, Any]] = []
    current_narration = narration_fingerprint(script)
    if current_narration != manifest.get("narration_fingerprint"):
        failures.append({"code": "narration_changed"})
    audio_report = locked_audio.verify(build_dir)
    if not audio_report["passed"]:
        failures.extend(audio_report["failures"])
    elif audio_report.get("locked_audio_sha256") != manifest.get("locked_audio_sha256"):
        failures.append({"code": "approved_delivery_audio_changed"})

    approved_hashes = (manifest.get("baseline_segment_hashes") or {}).get("approved") or {}
    for name, expected_hash in approved_hashes.items():
        path = build_dir / name
        actual = _sha256(path)
        if actual != expected_hash:
            failures.append(
                {
                    "code": "approved_segment_changed",
                    "path": name,
                    "expected": expected_hash,
                    "actual": actual,
                }
            )

    revised_hashes = (manifest.get("baseline_segment_hashes") or {}).get("revised") or {}
    changed_revised: list[str] = []
    for index in manifest.get("revised_scenes") or []:
        candidates = [path for path in _segment_paths(build_dir, int(index)) if path.exists()]
        if not candidates:
            failures.append({"code": "missing_revised_segment", "scene_index": index})
            continue
        for path in candidates:
            current = _sha256(path)
            old = revised_hashes.get(path.name)
            if old and current == old:
                failures.append(
                    {
                        "code": "revised_segment_unchanged",
                        "scene_index": index,
                        "path": path.name,
                    }
                )
            else:
                changed_revised.append(path.name)

    finals = [path.name for path in sorted(build_dir.glob("final*.mp4")) if path.stat().st_size > 100_000]
    if not finals:
        failures.append({"code": "missing_final_output"})
    result = {
        "schema_version": 2,
        "slug": script.get("slug") or build_dir.name,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "passed": not failures,
        "approved_scenes_preserved": len(manifest.get("approved_scenes") or []),
        "approved_delivery_audio_preserved": not any(
            failure.get("code") in {
                "missing_locked_audio",
                "missing_locked_audio_manifest",
                "locked_audio_hash_mismatch",
                "approved_delivery_audio_changed",
            }
            for failure in failures
        ),
        "locked_audio_sha256": audio_report.get("locked_audio_sha256"),
        "revised_scenes": manifest.get("revised_scenes") or [],
        "changed_revised_segments": sorted(changed_revised),
        "final_outputs": finals,
        "failures": failures,
    }
    _write(build_dir / "selective-revision-result.json", result)
    manifest["status"] = "completed" if result["passed"] else "failed"
    manifest["finished_at"] = result["finished_at"]
    _write(manifest_path, manifest)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "finalize"))
    parser.add_argument("build_dir")
    args = parser.parse_args(argv)
    report = prepare(args.build_dir) if args.command == "prepare" else finalize(args.build_dir)
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
