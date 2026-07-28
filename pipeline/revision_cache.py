"""Build and validate the reusable scene-master cache for selective revisions."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import locked_audio

CACHE_VERSION = 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def _cache_files(build_dir: Path) -> list[Path]:
    patterns = (
        "clip_*.mp4",
        "seg_*.mp4",
        "youtube_seg_*.mp4",
        "*.mp3",
        "*.wav",
        "*.m4a",
        "*.png",
        "*.jpg",
        "*.jpeg",
        "*.webp",
        "*.npy",
        "words.json",
        "voiceover-manifest.json",
        "music_variants.json",
        "alts.json",
        "motion_report.json",
        "still_reference_report.json",
        "visual_symbol_report.json",
        "editorial.otio",
        "editorial_manifest.json",
        "editorial-verification.json",
        "locked-audio-manifest.json",
    )
    found: dict[str, Path] = {}
    for pattern in patterns:
        for path in build_dir.glob(pattern):
            if path.is_file() and not path.name.startswith("final"):
                found[path.name] = path
    return [found[name] for name in sorted(found)]


def build_manifest(build_dir: str | Path, *, run_id: str | None = None) -> dict[str, Any]:
    build_dir = Path(build_dir).resolve()
    script = _load(build_dir / "script.json")
    scenes = script.get("scenes") or []
    if not scenes:
        raise SystemExit("script has no scenes")
    locked_report = locked_audio.verify(build_dir)
    if not locked_report["passed"]:
        raise SystemExit("revision cache requires exact locked delivery audio")
    expected_prefixes: list[str] = []
    if (build_dir / "youtube_seg_00.mp4").exists():
        expected_prefixes.append("youtube_seg_")
    if (build_dir / "seg_00.mp4").exists():
        expected_prefixes.append("seg_")
    missing: list[str] = []
    for prefix in expected_prefixes:
        for index in range(len(scenes)):
            path = build_dir / f"{prefix}{index:02d}.mp4"
            if not path.exists() or path.stat().st_size < 100_000:
                missing.append(path.name)
    if missing:
        raise SystemExit("revision cache is missing scene masters: " + ", ".join(missing))
    files = []
    total_bytes = 0
    for path in _cache_files(build_dir):
        size = path.stat().st_size
        total_bytes += size
        files.append({"path": path.name, "size_bytes": size, "sha256": _sha256(path)})
    durations = [round(float(scene.get("duration") or 0.0), 3) for scene in scenes]
    manifest = {
        "schema_version": CACHE_VERSION,
        "slug": script.get("slug") or build_dir.name,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_run_id": run_id,
        "scene_count": len(scenes),
        "scene_durations": durations,
        "segment_prefixes": expected_prefixes,
        "locked_audio_sha256": locked_report.get("locked_audio_sha256"),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
    }
    (build_dir / "revision-cache-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_manifest(build_dir: str | Path) -> dict[str, Any]:
    build_dir = Path(build_dir).resolve()
    manifest = _load(build_dir / "revision-cache-manifest.json")
    script = _load(build_dir / "script.json")
    failures: list[dict[str, Any]] = []
    scenes = script.get("scenes") or []
    if int(manifest.get("schema_version") or 0) != CACHE_VERSION:
        failures.append({"code": "unsupported_cache_version"})
    if int(manifest.get("scene_count") or -1) != len(scenes):
        failures.append(
            {
                "code": "scene_count_mismatch",
                "cache": manifest.get("scene_count"),
                "script": len(scenes),
            }
        )
    expected_durations = [round(float(scene.get("duration") or 0.0), 3) for scene in scenes]
    if manifest.get("scene_durations") != expected_durations:
        failures.append(
            {
                "code": "scene_duration_mismatch",
                "cache": manifest.get("scene_durations"),
                "script": expected_durations,
            }
        )
    locked_report = locked_audio.verify(build_dir)
    if not locked_report["passed"]:
        failures.extend(locked_report["failures"])
    elif manifest.get("locked_audio_sha256") != locked_report.get("locked_audio_sha256"):
        failures.append({"code": "cache_locked_audio_mismatch"})
    for item in manifest.get("files") or []:
        path = build_dir / str(item.get("path") or "")
        if not path.exists():
            failures.append({"code": "missing_cache_file", "path": path.name})
            continue
        if int(item.get("size_bytes") or -1) != path.stat().st_size:
            failures.append({"code": "cache_size_mismatch", "path": path.name})
            continue
        if item.get("sha256") != _sha256(path):
            failures.append({"code": "cache_hash_mismatch", "path": path.name})
    report = {
        "schema_version": 1,
        "slug": script.get("slug") or build_dir.name,
        "passed": not failures,
        "locked_audio_sha256": locked_report.get("locked_audio_sha256"),
        "failures": failures,
    }
    (build_dir / "revision-cache-verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate"))
    parser.add_argument("build_dir")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if args.command == "build":
        report = build_manifest(args.build_dir, run_id=args.run_id)
        print(json.dumps(report, indent=2))
        return 0
    report = validate_manifest(args.build_dir)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
