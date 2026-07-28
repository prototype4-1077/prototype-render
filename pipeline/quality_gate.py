"""Independent technical quality firewall for finished videos.

The Governor may optimize latency and recovery policy, but this module owns the
non-negotiable acceptance floor.  A run cannot be marked DONE unless required
outputs are structurally valid, decodable, correctly oriented, and synchronized
with the script closely enough to be safe for delivery.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

from governor import atomic_write_json, load_json, utc_now
import render_policy


MIN_FILE_BYTES = 100_000
MIN_DIMENSION = 1080  # deliverable floor: nothing below the 1080 canvas ships
CURATION_MIN_DIMENSION = 880  # editorial curation reels use a 1600x880 canvas


def parse_ratio(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        if "/" in value:
            numerator, denominator = value.split("/", 1)
            denominator_value = float(denominator)
            return float(numerator) / denominator_value if denominator_value else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def expected_script_duration(script: Mapping[str, Any]) -> float | None:
    scenes = script.get("scenes") or []
    if not scenes:
        return None
    ends: list[float] = []
    durations: list[float] = []
    for scene in scenes:
        try:
            duration = float(scene.get("duration"))
        except (TypeError, ValueError):
            continue
        if duration <= 0:
            continue
        durations.append(duration)
        try:
            start = float(scene.get("start"))
        except (TypeError, ValueError):
            start = None
        if start is not None:
            ends.append(start + duration)
    if ends:
        return max(ends)
    return sum(durations) if durations else None


def probe_media(path: Path, timeout_s: float = 30) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-print_format", "json", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError:
        return {"ok": False, "error": "ffprobe is not installed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"ffprobe timed out after {timeout_s:.0f}s"}
    if result.returncode != 0:
        return {"ok": False, "error": (result.stderr or result.stdout)[-800:]}
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        return {"ok": False, "error": f"invalid ffprobe JSON: {exc}"}
    payload["ok"] = True
    return payload


def _float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def summarize_probe(payload: Mapping[str, Any]) -> dict[str, Any]:
    streams = payload.get("streams") or []
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    video = video_streams[0] if video_streams else {}
    audio = audio_streams[0] if audio_streams else {}
    format_info = payload.get("format") or {}
    duration = _float(format_info.get("duration"))
    if duration is None:
        duration = _float(video.get("duration"))
    return {
        "duration_s": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": parse_ratio(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "has_video": bool(video_streams),
        "has_audio": bool(audio_streams),
        "video_duration_s": _float(video.get("duration")),
        "audio_duration_s": _float(audio.get("duration")),
        "format_name": format_info.get("format_name"),
        "bit_rate": _float(format_info.get("bit_rate")),
    }


def deep_decode_scan(path: Path, *, duration_s: float, has_audio: bool) -> dict[str, Any]:
    """Decode the whole deliverable and collect high-signal anomaly markers."""
    video_filters = "blackdetect=d=2.0:pix_th=0.10:pic_th=0.98,freezedetect=n=-60dB:d=6"
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-v", "info", "-xerror",
        "-i", str(path), "-vf", video_filters,
    ]
    if has_audio:
        command += ["-af", "silencedetect=n=-55dB:d=5"]
    command += ["-f", "null", "-"]
    timeout_s = min(1500.0, max(120.0, duration_s * 3.0 + 60.0))
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg is not installed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"full decode timed out after {timeout_s:.0f}s"}
    log = (result.stderr or "") + "\n" + (result.stdout or "")
    black = [float(value) for value in re.findall(r"black_duration:([0-9.]+)", log)]
    freezes = [float(value) for value in re.findall(r"freeze_duration:\s*([0-9.]+)", log)]
    silence = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", log)]
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "error": None if result.returncode == 0 else log[-1200:],
        "black_intervals": len(black),
        "black_total_s": round(sum(black), 3),
        "black_longest_s": round(max(black, default=0.0), 3),
        "freeze_intervals": len(freezes),
        "freeze_total_s": round(sum(freezes), 3),
        "freeze_longest_s": round(max(freezes, default=0.0), 3),
        "silence_intervals": len(silence),
        "silence_total_s": round(sum(silence), 3),
        "silence_longest_s": round(max(silence, default=0.0), 3),
    }


def _issue(code: str, target: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "target": target, "message": message, **details}


def check_output(
    path: Path,
    *,
    target_name: str,
    orientation: str | None,
    require_audio: bool,
    expected_duration_s: float | None,
    deep: bool,
    min_dimension: int = MIN_DIMENSION,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "failures": failures,
        "warnings": warnings,
    }
    if not path.exists():
        failures.append(_issue("missing_output", target_name, f"Required output does not exist: {path}"))
        return result
    try:
        size = path.stat().st_size
    except OSError as exc:
        failures.append(_issue("unreadable_output", target_name, f"Cannot stat output: {exc}"))
        return result
    result["size_bytes"] = size
    if size < MIN_FILE_BYTES:
        failures.append(_issue("undersized_output", target_name, f"Output is only {size} bytes", minimum=MIN_FILE_BYTES))

    raw_probe = probe_media(path)
    if not raw_probe.get("ok"):
        failures.append(_issue("probe_failed", target_name, str(raw_probe.get("error") or "ffprobe failed")))
        result["probe"] = raw_probe
        return result
    probe = summarize_probe(raw_probe)
    result["probe"] = probe
    duration = probe.get("duration_s")

    if not probe["has_video"]:
        failures.append(_issue("missing_video_stream", target_name, "No video stream was found"))
    if require_audio and not probe["has_audio"]:
        failures.append(_issue("missing_audio_stream", target_name, "No audio stream was found"))
    if not duration or duration <= 1:
        failures.append(_issue("invalid_duration", target_name, f"Duration is not usable: {duration}"))
    width, height = probe["width"], probe["height"]
    if min(width, height) < min_dimension:
        failures.append(_issue(
            "resolution_below_floor", target_name,
            f"Resolution {width}x{height} is below the {min_dimension}px quality floor",
        ))
    if orientation == "portrait" and not height > width:
        failures.append(_issue("wrong_orientation", target_name, f"Expected portrait but got {width}x{height}"))
    if orientation == "landscape" and not width > height:
        failures.append(_issue("wrong_orientation", target_name, f"Expected landscape but got {width}x{height}"))
    fps = probe.get("fps")
    if fps is None or fps < 29:
        failures.append(_issue("frame_rate_below_floor", target_name, f"Frame rate {fps} is below the 30fps delivery floor"))
    if duration and size and width and height and min(width, height) >= 1080:
        kbps = size * 8 / duration / 1000
        result["avg_kbps"] = round(kbps)
        if kbps < 4000:
            warnings.append(_issue(
                "low_bitrate", target_name,
                f"Average bitrate {kbps:.0f} kbps is unusually low for 1080p; check for over-compression"))

    if duration and expected_duration_s and expected_duration_s > 0:
        difference = abs(duration - expected_duration_s)
        result["expected_duration_s"] = round(expected_duration_s, 3)
        result["duration_difference_s"] = round(difference, 3)
        hard_tolerance = max(8.0, expected_duration_s * 0.15)
        warning_tolerance = max(3.0, expected_duration_s * 0.08)
        if difference > hard_tolerance:
            failures.append(_issue(
                "duration_mismatch", target_name,
                f"Duration differs from the timed script by {difference:.2f}s",
                expected=expected_duration_s, actual=duration, tolerance=hard_tolerance,
            ))
        elif difference > warning_tolerance:
            warnings.append(_issue(
                "duration_drift", target_name,
                f"Duration differs from the timed script by {difference:.2f}s",
                expected=expected_duration_s, actual=duration,
            ))

    video_duration = probe.get("video_duration_s")
    audio_duration = probe.get("audio_duration_s")
    if require_audio and video_duration and audio_duration:
        av_difference = abs(video_duration - audio_duration)
        if av_difference > max(3.0, float(duration or 0) * 0.05):
            failures.append(_issue(
                "av_duration_mismatch", target_name,
                f"Audio/video stream durations differ by {av_difference:.2f}s",
                video_duration=video_duration, audio_duration=audio_duration,
            ))
        elif av_difference > 1.0:
            warnings.append(_issue(
                "av_duration_drift", target_name,
                f"Audio/video stream durations differ by {av_difference:.2f}s",
            ))

    if deep and duration and probe["has_video"]:
        scan = deep_decode_scan(path, duration_s=float(duration), has_audio=bool(probe["has_audio"]))
        result["deep_scan"] = scan
        if not scan.get("ok"):
            failures.append(_issue("decode_failed", target_name, str(scan.get("error") or "full decode failed")))
        longest_black = float(scan.get("black_longest_s") or 0.0)
        if longest_black >= 2.0:
            warnings.append(_issue(
                "long_black_interval", target_name,
                f"Detected a {longest_black:.2f}s near-black interval; review intentionally dark scenes",
            ))
        longest_freeze = float(scan.get("freeze_longest_s") or 0.0)
        if longest_freeze >= 6.0:
            warnings.append(_issue(
                "long_freeze_interval", target_name,
                f"Detected a {longest_freeze:.2f}s visually frozen interval",
            ))
        silence_total = float(scan.get("silence_total_s") or 0.0)
        silence_longest = float(scan.get("silence_longest_s") or 0.0)
        if require_audio and (silence_total >= duration * 0.85 or silence_longest >= duration * 0.80):
            failures.append(_issue(
                "mostly_silent_audio", target_name,
                "The deliverable is silent for most of its duration",
                silence_total_s=silence_total, silence_longest_s=silence_longest,
            ))
    return result


def run_quality_gate(build_dir: str | os.PathLike[str], *, deep: bool = True) -> dict[str, Any]:
    bd = Path(build_dir).resolve()
    script_path = bd / "script.json"
    script = load_json(script_path, {}) or {}
    curation_mode = bool(script.get("curate_scenes"))
    expected_duration = None if curation_mode else expected_script_duration(script)
    targets: list[tuple[str, Path, str | None, bool, bool]] = []
    if curation_mode:
        targets.append(("portrait", bd / "final.mp4", None, False, deep))
    else:
        requested = render_policy.render_outputs(script)
        if "youtube" in requested:
            targets.append(("youtube", bd / "final_youtube.mp4", "landscape", True, deep))
        if "portrait" in requested:
            targets.append(("portrait", bd / "final.mp4", "portrait", True, deep))
        if "short" in requested:
            targets.append(("short", bd / "final_short.mp4", "portrait", True, deep))

        # Explicit alternate music choices are independently probed, but the
        # selected canonical YouTube video is the only required default output.
        manifest = load_json(bd / "music_variants.json", {}) or {}
        seen = {str(path) for _name, path, _orientation, _audio, _deep in targets}
        for row in (manifest.get("variants") or [])[1:]:
            for key, orientation in (("youtube_video", "landscape"), ("video", "portrait")):
                name = row.get(key)
                if not name:
                    continue
                path = bd / name
                if str(path) in seen:
                    continue
                seen.add(str(path))
                targets.append((path.stem, path, orientation, True, False))

    outputs: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for name, path, orientation, require_audio, target_deep in targets:
        output = check_output(
            path,
            target_name=name,
            orientation=orientation,
            require_audio=require_audio,
            expected_duration_s=expected_duration if not curation_mode and name != "short" else None,
            deep=target_deep,
            min_dimension=CURATION_MIN_DIMENSION if curation_mode else MIN_DIMENSION,
        )
        outputs[name] = output
        failures.extend(output["failures"])
        warnings.extend(output["warnings"])

    report = {
        "schema_version": 1,
        "checked_at": utc_now(),
        "build_dir": str(bd),
        "mode": "curation" if curation_mode else "delivery",
        "deep_decode": deep,
        "expected_duration_s": round(expected_duration, 3) if expected_duration else None,
        "passed": not failures,
        "quality_floor": {
            "minimum_file_bytes": MIN_FILE_BYTES,
            "minimum_dimension": MIN_DIMENSION,
            "video_stream_required": True,
            "audio_stream_required": not curation_mode,
            "full_decode_required": deep,
        },
        "outputs": outputs,
        "failures": failures,
        "warnings": warnings,
    }
    atomic_write_json(bd / "quality_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir")
    parser.add_argument("--shallow", action="store_true", help="skip the full ffmpeg decode scan")
    args = parser.parse_args(argv)
    report = run_quality_gate(args.build_dir, deep=not args.shallow)
    if report["passed"]:
        print(f"QUALITY PASS: {len(report['outputs'])} output(s), {len(report['warnings'])} warning(s)")
        for warning in report["warnings"]:
            print(f"warning [{warning['code']}] {warning['target']}: {warning['message']}")
        return 0
    print(f"QUALITY FAIL: {len(report['failures'])} blocking issue(s)", file=sys.stderr)
    for failure in report["failures"]:
        print(f"error [{failure['code']}] {failure['target']}: {failure['message']}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
