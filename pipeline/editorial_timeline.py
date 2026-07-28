"""Create and validate the canonical OpenTimelineIO edit for a rendered build.

The OTIO timeline is the durable editorial truth. It references scene masters,
voiceover, score, and the exact approved delivery mix externally while carrying
scene approval/revision metadata. It deliberately does not embed media.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

FPS = 30.0
NAMESPACE = "prototype_video"


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def narration_fingerprint(script: dict[str, Any]) -> str:
    payload = {
        "slug": script.get("slug"),
        "title": script.get("title"),
        "scenes": [
            {
                "text": scene.get("text", ""),
                "start": round(float(scene.get("start") or 0.0), 3),
                "duration": round(float(scene.get("duration") or 0.0), 3),
            }
            for scene in script.get("scenes") or []
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _scene_statuses(build_dir: Path, scene_count: int) -> tuple[set[int], set[int]]:
    selective = _load_json(build_dir / "selective-revision.json", {}) or {}
    approved = {int(value) for value in selective.get("approved_scenes") or []}
    revised = {int(value) for value in selective.get("revised_scenes") or []}
    if not approved and not revised:
        approved = set(range(scene_count))
    return approved, revised


def _canvas_specs(build_dir: Path, scene_count: int) -> list[tuple[str, str, str]]:
    specs: list[tuple[str, str, str]] = []
    if scene_count and (build_dir / "youtube_seg_00.mp4").exists():
        specs.append(("youtube", "youtube_seg_", "final_youtube.mp4"))
    if scene_count and (build_dir / "seg_00.mp4").exists():
        specs.append(("portrait", "seg_", "final.mp4"))
    return specs


def _rational_time(otio: Any, seconds: float):
    frames = max(int(round(float(seconds) * FPS)), 1)
    return otio.opentime.RationalTime(frames, FPS)


def _time_range(otio: Any, seconds: float):
    return otio.opentime.TimeRange(
        start_time=otio.opentime.RationalTime(0, FPS),
        duration=_rational_time(otio, seconds),
    )


def _selected_score(build_dir: Path) -> str | None:
    payload = _load_json(build_dir / "music_variants.json", {}) or {}
    variants = payload.get("variants") or payload.get("entries") or []
    selected = payload.get("selected")
    if isinstance(selected, dict) and selected.get("file"):
        return str(selected["file"])
    for item in variants:
        if item.get("selected") and item.get("file"):
            return str(item["file"])
    if variants and variants[0].get("file"):
        return str(variants[0]["file"])
    return None


def _audio_specs(build_dir: Path) -> list[tuple[str, str | None, str]]:
    return [
        ("Locked Delivery Mix", "locked_delivery_audio.m4a", "delivery_mix"),
        ("Voiceover", "vo.mp3", "voiceover"),
        ("Selected Score", _selected_score(build_dir), "music"),
    ]


def build_timeline(build_dir: str | Path) -> dict[str, Any]:
    import opentimelineio as otio

    build_dir = Path(build_dir).resolve()
    script_path = build_dir / "script.json"
    script = _load_json(script_path)
    if not isinstance(script, dict):
        raise SystemExit(f"invalid or missing script: {script_path}")
    scenes = script.get("scenes") or []
    if not scenes:
        raise SystemExit("script has no scenes")
    if any(scene.get("duration") is None for scene in scenes):
        raise SystemExit("all scenes need resolved durations before writing OTIO")

    approved, revised = _scene_statuses(build_dir, len(scenes))
    timeline = otio.schema.Timeline(name=str(script.get("title") or build_dir.name))
    timeline.metadata[NAMESPACE] = {
        "schema_version": 1,
        "slug": script.get("slug") or build_dir.name,
        "title": script.get("title"),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "narration_fingerprint": narration_fingerprint(script),
        "scene_count": len(scenes),
        "approved_scenes": sorted(approved),
        "revised_scenes": sorted(revised),
        "revision_number": int(script.get("scene_feedback_revision_count") or 0),
        "locked_delivery_audio_sha256": _sha256(build_dir / "locked_delivery_audio.m4a"),
    }

    manifest_tracks: list[dict[str, Any]] = []
    for canvas, prefix, final_name in _canvas_specs(build_dir, len(scenes)):
        track = otio.schema.Track(
            name=f"{canvas.title()} Scene Masters",
            kind=otio.schema.TrackKind.Video,
        )
        manifest_clips: list[dict[str, Any]] = []
        for index, scene in enumerate(scenes):
            segment = build_dir / f"{prefix}{index:02d}.mp4"
            duration = float(scene["duration"])
            status = "revised" if index in revised else "approved"
            scene_id = str(scene.get("scene_id") or f"scene-{index + 1:02d}")
            reference = otio.schema.ExternalReference(
                target_url=segment.as_uri(),
                available_range=_time_range(otio, duration),
            )
            clip = otio.schema.Clip(
                name=scene_id,
                media_reference=reference,
                source_range=_time_range(otio, duration),
            )
            clip.metadata[NAMESPACE] = {
                "scene_index": index,
                "scene_number": index + 1,
                "scene_id": scene_id,
                "canvas": canvas,
                "status": status,
                "text_sha256": hashlib.sha256(
                    str(scene.get("text") or "").encode("utf-8")
                ).hexdigest(),
                "visual_function": scene.get("visual_function"),
                "symbol_family": scene.get("symbol_family"),
                "revision_note": scene.get("revision_note"),
                "segment_sha256": _sha256(segment),
            }
            track.append(clip)
            manifest_clips.append(
                {
                    "scene_index": index,
                    "scene_id": scene_id,
                    "duration": duration,
                    "status": status,
                    "path": segment.name,
                    "sha256": _sha256(segment),
                }
            )
        timeline.tracks.append(track)
        final_path = build_dir / final_name
        manifest_tracks.append(
            {
                "canvas": canvas,
                "segment_prefix": prefix,
                "final": final_name,
                "final_sha256": _sha256(final_path),
                "clips": manifest_clips,
            }
        )

    total_duration = sum(float(scene["duration"]) for scene in scenes)
    manifest_audio: list[dict[str, Any]] = []
    for name, filename, role in _audio_specs(build_dir):
        if not filename:
            continue
        media_path = build_dir / filename
        if not media_path.exists():
            continue
        track = otio.schema.Track(name=name, kind=otio.schema.TrackKind.Audio)
        clip = otio.schema.Clip(
            name=name,
            media_reference=otio.schema.ExternalReference(target_url=media_path.as_uri()),
            source_range=_time_range(otio, total_duration),
        )
        clip.metadata[NAMESPACE] = {
            "role": role,
            "sha256": _sha256(media_path),
            "locked": role == "delivery_mix",
        }
        track.append(clip)
        timeline.tracks.append(track)
        manifest_audio.append(
            {
                "name": name,
                "role": role,
                "path": media_path.name,
                "sha256": _sha256(media_path),
                "locked": role == "delivery_mix",
            }
        )

    otio_path = build_dir / "editorial.otio"
    otio.adapters.write_to_file(timeline, str(otio_path))
    manifest = {
        "schema_version": 1,
        "slug": script.get("slug") or build_dir.name,
        "title": script.get("title"),
        "created_at": timeline.metadata[NAMESPACE]["created_at"],
        "narration_fingerprint": narration_fingerprint(script),
        "scene_count": len(scenes),
        "total_duration": round(total_duration, 3),
        "approved_scenes": sorted(approved),
        "revised_scenes": sorted(revised),
        "tracks": manifest_tracks,
        "audio_tracks": manifest_audio,
        "locked_delivery_audio_sha256": _sha256(build_dir / "locked_delivery_audio.m4a"),
        "otio_file": otio_path.name,
        "otio_sha256": _sha256(otio_path),
    }
    (build_dir / "editorial_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_timeline(build_dir: str | Path) -> dict[str, Any]:
    import opentimelineio as otio

    build_dir = Path(build_dir).resolve()
    script = _load_json(build_dir / "script.json")
    if not isinstance(script, dict):
        raise SystemExit("missing script.json")
    timeline_path = build_dir / "editorial.otio"
    timeline = otio.adapters.read_from_file(str(timeline_path))
    expected = len(script.get("scenes") or [])
    failures: list[dict[str, Any]] = []
    video_tracks = [
        track for track in timeline.tracks
        if getattr(track, "kind", None) == otio.schema.TrackKind.Video
    ]
    audio_tracks = [
        track for track in timeline.tracks
        if getattr(track, "kind", None) == otio.schema.TrackKind.Audio
    ]
    if not video_tracks:
        failures.append({"code": "missing_video_track", "message": "OTIO has no video track"})
    expected_total = sum(float(scene.get("duration") or 0.0) for scene in script.get("scenes") or [])
    for track in video_tracks:
        clips = list(track)
        if len(clips) != expected:
            failures.append(
                {
                    "code": "scene_count_mismatch",
                    "track": track.name,
                    "expected": expected,
                    "actual": len(clips),
                }
            )
        actual_total = sum(float(clip.duration().to_seconds()) for clip in clips)
        if abs(actual_total - expected_total) > max(1.0 / FPS, 0.05):
            failures.append(
                {
                    "code": "timeline_duration_mismatch",
                    "track": track.name,
                    "expected": round(expected_total, 3),
                    "actual": round(actual_total, 3),
                }
            )
        for clip in clips:
            target = getattr(getattr(clip, "media_reference", None), "target_url", "")
            if target.startswith("file://"):
                from urllib.parse import unquote, urlparse
                media = Path(unquote(urlparse(target).path))
                if not media.exists():
                    failures.append(
                        {
                            "code": "missing_media_reference",
                            "track": track.name,
                            "clip": clip.name,
                            "target_url": target,
                        }
                    )
    locked = build_dir / "locked_delivery_audio.m4a"
    if locked.exists() and not any(track.name == "Locked Delivery Mix" for track in audio_tracks):
        failures.append({"code": "missing_locked_delivery_audio_track"})
    report = {
        "schema_version": 1,
        "slug": script.get("slug") or build_dir.name,
        "passed": not failures,
        "expected_scene_count": expected,
        "video_track_count": len(video_tracks),
        "audio_track_count": len(audio_tracks),
        "narration_fingerprint": narration_fingerprint(script),
        "locked_delivery_audio_sha256": _sha256(locked),
        "failures": failures,
    }
    (build_dir / "editorial-verification.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("build_dir")
    args = parser.parse_args(argv)
    if args.command == "build":
        report = build_timeline(args.build_dir)
        print(json.dumps(report, indent=2))
        return 0
    report = verify_timeline(args.build_dir)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
