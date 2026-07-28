"""Compare the exported video against the planned scene timeline with PySceneDetect."""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Iterable


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return payload


def _load_optional(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _probe(path: Path) -> dict[str, float]:
    command = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,duration",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    format_duration = float((payload.get("format") or {}).get("duration") or 0.0)
    video_duration = 0.0
    audio_duration = 0.0
    for stream in payload.get("streams") or []:
        duration = float(stream.get("duration") or 0.0)
        if stream.get("codec_type") == "video":
            video_duration = max(video_duration, duration)
        elif stream.get("codec_type") == "audio":
            audio_duration = max(audio_duration, duration)
    return {
        "duration": format_duration,
        "video_duration": video_duration,
        "audio_duration": audio_duration,
    }


def planned_boundaries(durations: Iterable[float]) -> list[float]:
    values = [float(value) for value in durations]
    total = 0.0
    boundaries: list[float] = []
    for duration in values[:-1]:
        total += duration
        boundaries.append(round(total, 6))
    return boundaries


def match_boundaries(
    planned: list[float], detected: list[float], *, tolerance: float
) -> tuple[list[dict[str, float | None]], list[float]]:
    unused = list(detected)
    matches: list[dict[str, float | None]] = []
    for expected in planned:
        if not unused:
            matches.append({"planned": expected, "detected": None, "delta": None})
            continue
        nearest = min(unused, key=lambda value: abs(value - expected))
        delta = nearest - expected
        if abs(delta) <= tolerance:
            matches.append(
                {
                    "planned": round(expected, 3),
                    "detected": round(nearest, 3),
                    "delta": round(delta, 3),
                }
            )
            unused.remove(nearest)
        else:
            matches.append({"planned": round(expected, 3), "detected": None, "delta": None})
    return matches, [round(value, 3) for value in unused]


def _detect(path: Path, *, threshold: float, min_scene_seconds: float) -> list[tuple[float, float]]:
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(str(path))
    frame_rate = float(video.frame_rate or 30.0)
    manager = SceneManager()
    manager.add_detector(
        ContentDetector(
            threshold=float(threshold),
            min_scene_len=max(int(round(min_scene_seconds * frame_rate)), 1),
        )
    )
    manager.detect_scenes(video=video, show_progress=False)
    return [
        (float(start.get_seconds()), float(end.get_seconds()))
        for start, end in manager.get_scene_list(start_in_scene=True)
    ]


def _extract_frames(build_dir: Path, video: Path, durations: list[float], canvas: str) -> list[str]:
    frame_dir = build_dir / "verification_frames" / canvas
    frame_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    start = 0.0
    for index, duration in enumerate(durations):
        timestamp = start + max(duration * 0.5, 0.05)
        target = frame_dir / f"scene_{index + 1:02d}.jpg"
        result = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-ss", f"{timestamp:.3f}",
                "-i", str(video), "-frames:v", "1", "-q:v", "2", str(target),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and target.exists():
            outputs.append(str(target.relative_to(build_dir)))
        start += duration
    return outputs


def _planned_edit(
    build_dir: Path, video: Path, scenes: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]], list[int]]:
    stem = video.stem.lower()
    if "short" in stem:
        canvas = "short"
        short_report = _load_optional(build_dir / "motion_report_short.json")
        indexes = [int(value) for value in short_report.get("selected_indexes") or []]
        if not indexes:
            raise SystemExit("short export requires motion_report_short.json selected_indexes")
        if any(index < 0 or index >= len(scenes) for index in indexes):
            raise SystemExit("short export contains invalid selected scene indexes")
        return canvas, [scenes[index] for index in indexes], indexes
    canvas = "youtube" if "youtube" in stem else "portrait"
    return canvas, scenes, list(range(len(scenes)))


def verify_export(
    build_dir: str | Path,
    video_name: str,
    *,
    threshold: float = 27.0,
    tolerance: float = 0.85,
    extract_frames: bool = False,
) -> dict[str, Any]:
    build_dir = Path(build_dir).resolve()
    script = _load(build_dir / "script.json")
    all_scenes = script.get("scenes") or []
    video = build_dir / video_name
    if not video.exists():
        raise SystemExit(f"missing export: {video}")
    canvas, scenes, scene_indexes = _planned_edit(build_dir, video, all_scenes)
    durations = [float(scene.get("duration") or 0.0) for scene in scenes]
    if not durations or any(value <= 0 for value in durations):
        raise SystemExit("all planned export scenes need positive durations")
    probe = _probe(video)
    expected_total = sum(durations)
    detected_ranges = _detect(video, threshold=threshold, min_scene_seconds=0.25)
    detected_cuts = [end for _, end in detected_ranges[:-1]]
    planned = planned_boundaries(durations)
    matches, unmatched_detected = match_boundaries(planned, detected_cuts, tolerance=tolerance)
    matched_count = sum(item["detected"] is not None for item in matches)
    detected_durations = [end - start for start, end in detected_ranges]
    micro_scenes = [
        {"index": index, "duration": round(duration, 3)}
        for index, duration in enumerate(detected_durations)
        if duration < 0.35
    ]
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    duration_delta = probe["duration"] - expected_total
    if abs(duration_delta) > max(0.75, expected_total * 0.005):
        failures.append(
            {
                "code": "export_duration_mismatch",
                "expected": round(expected_total, 3),
                "actual": round(probe["duration"], 3),
                "delta": round(duration_delta, 3),
            }
        )
    if probe["audio_duration"] and probe["video_duration"]:
        av_delta = probe["audio_duration"] - probe["video_duration"]
        if abs(av_delta) > 0.5:
            failures.append({"code": "audio_video_duration_mismatch", "delta": round(av_delta, 3)})
    if micro_scenes:
        failures.append({"code": "micro_scenes", "scenes": micro_scenes})
    expected_cuts = max(len(scenes) - 1, 0)
    if len(detected_cuts) > max(expected_cuts + 3, int(math.ceil(expected_cuts * 1.6))):
        failures.append(
            {
                "code": "excessive_detected_cuts",
                "expected_planned_cuts": expected_cuts,
                "detected_cuts": len(detected_cuts),
            }
        )
    match_ratio = matched_count / max(len(planned), 1)
    if planned and match_ratio < 0.35:
        warnings.append(
            {
                "code": "low_boundary_match",
                "matched": matched_count,
                "planned": len(planned),
                "ratio": round(match_ratio, 3),
                "note": "Continuous motion or gentle fades can be valid; inspect representative frames.",
            }
        )
    if unmatched_detected:
        warnings.append(
            {
                "code": "unplanned_detected_cuts",
                "count": len(unmatched_detected),
                "times": unmatched_detected[:30],
            }
        )
    frames = _extract_frames(build_dir, video, durations, canvas) if extract_frames else []
    report = {
        "schema_version": 2,
        "slug": script.get("slug") or build_dir.name,
        "canvas": canvas,
        "video": video.name,
        "passed": not failures,
        "expected_scene_count": len(scenes),
        "expected_scene_indexes": scene_indexes,
        "expected_duration": round(expected_total, 3),
        "probe": {key: round(value, 3) for key, value in probe.items()},
        "detector": {
            "name": "PySceneDetect ContentDetector",
            "threshold": threshold,
            "boundary_tolerance_seconds": tolerance,
            "detected_scene_count": len(detected_ranges),
            "detected_ranges": [
                {"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)}
                for start, end in detected_ranges
            ],
            "boundary_matches": matches,
            "matched_boundary_ratio": round(match_ratio, 3),
        },
        "representative_frames": frames,
        "failures": failures,
        "warnings": warnings,
    }
    report_path = build_dir / f"export-verification-{canvas}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    csv_path = build_dir / f"detected-scenes-{canvas}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("scene", "start", "end", "duration"))
        writer.writeheader()
        for index, (start, end) in enumerate(detected_ranges, 1):
            writer.writerow(
                {
                    "scene": index,
                    "start": f"{start:.3f}",
                    "end": f"{end:.3f}",
                    "duration": f"{end - start:.3f}",
                }
            )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir")
    parser.add_argument("video", nargs="?", default="final_youtube.mp4")
    parser.add_argument("--threshold", type=float, default=27.0)
    parser.add_argument("--tolerance", type=float, default=0.85)
    parser.add_argument("--frames", action="store_true")
    args = parser.parse_args(argv)
    report = verify_export(
        args.build_dir,
        args.video,
        threshold=args.threshold,
        tolerance=args.tolerance,
        extract_frames=args.frames,
    )
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
