"""Extract and preserve the exact approved delivery audio across visual revisions."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

LOCKED_NAME = "locked_delivery_audio.m4a"
MANIFEST_NAME = "locked-audio-manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audio_stream_md5(path: Path) -> str:
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
            "-c:a", "copy", "-f", "md5", "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not value.startswith("MD5="):
        raise SystemExit(f"could not fingerprint audio stream in {path}")
    return value.split("=", 1)[1].strip()


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,duration,bit_rate,sample_rate,channels",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    streams = json.loads(result.stdout).get("streams") or []
    if not streams:
        raise SystemExit(f"no audio stream in {path}")
    stream = streams[0]
    return {
        "codec": stream.get("codec_name"),
        "duration": float(stream.get("duration") or 0.0),
        "bit_rate": int(stream.get("bit_rate") or 0),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
    }


def extract(source_video: str | Path, build_dir: str | Path) -> dict[str, Any]:
    source_video = Path(source_video).resolve()
    build_dir = Path(build_dir).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)
    target = build_dir / LOCKED_NAME
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", str(source_video),
            "-map", "0:a:0", "-vn", "-c:a", "copy", str(target),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"could not copy approved audio: {result.stderr[-1000:]}")
    probe = _probe(target)
    if probe["duration"] <= 0.0:
        raise SystemExit("approved audio has invalid duration")
    manifest = {
        "schema_version": 2,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_video": source_video.name,
        "source_video_sha256": _sha256(source_video),
        "locked_audio": target.name,
        "locked_audio_sha256": _sha256(target),
        "locked_audio_stream_md5": _audio_stream_md5(target),
        "audio": probe,
        "policy": "stream-copy approved final audio; visual revisions may not alter it",
    }
    (build_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def apply(video: str | Path, build_dir: str | Path) -> dict[str, Any]:
    video = Path(video).resolve()
    build_dir = Path(build_dir).resolve()
    if "short" in video.stem.lower():
        return {
            "video": video.name,
            "skipped": True,
            "reason": "short cuts have their own narration edit and music master",
        }
    locked = build_dir / LOCKED_NAME
    manifest_path = build_dir / MANIFEST_NAME
    if not locked.exists() or not manifest_path.exists():
        raise SystemExit("locked delivery audio is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("locked_audio_sha256")
    actual = _sha256(locked)
    if expected != actual:
        raise SystemExit("locked delivery audio hash changed")
    expected_stream = manifest.get("locked_audio_stream_md5") or _audio_stream_md5(locked)
    with tempfile.NamedTemporaryFile(
        prefix=f".{video.stem}-locked-", suffix=video.suffix, dir=video.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(locked),
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy",
                "-movflags", "+faststart", str(temporary),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit(f"could not apply locked audio: {result.stderr[-1000:]}")
        os.replace(temporary, video)
    finally:
        temporary.unlink(missing_ok=True)
    video_stream = _audio_stream_md5(video)
    if video_stream != expected_stream:
        raise SystemExit("final video audio packets do not match the approved delivery audio")
    result_payload = {
        "video": video.name,
        "video_sha256": _sha256(video),
        "locked_audio_sha256": actual,
        "locked_audio_stream_md5": expected_stream,
        "video_audio_stream_md5": video_stream,
        "exact_audio_match": True,
        "audio": _probe(video),
    }
    return result_payload


def verify(build_dir: str | Path) -> dict[str, Any]:
    build_dir = Path(build_dir).resolve()
    locked = build_dir / LOCKED_NAME
    manifest_path = build_dir / MANIFEST_NAME
    failures: list[dict[str, Any]] = []
    if not manifest_path.exists():
        failures.append({"code": "missing_locked_audio_manifest"})
        manifest: dict[str, Any] = {}
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stream_md5 = None
    if not locked.exists():
        failures.append({"code": "missing_locked_audio"})
    elif manifest.get("locked_audio_sha256") != _sha256(locked):
        failures.append({"code": "locked_audio_hash_mismatch"})
    elif manifest.get("locked_audio_stream_md5"):
        stream_md5 = _audio_stream_md5(locked)
        if manifest.get("locked_audio_stream_md5") != stream_md5:
            failures.append({"code": "locked_audio_stream_mismatch"})
    return {
        "schema_version": 2,
        "passed": not failures,
        "locked_audio": locked.name,
        "locked_audio_sha256": _sha256(locked) if locked.exists() else None,
        "locked_audio_stream_md5": stream_md5 or manifest.get("locked_audio_stream_md5"),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    extract_parser = sub.add_parser("extract")
    extract_parser.add_argument("source_video")
    extract_parser.add_argument("build_dir")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("video")
    apply_parser.add_argument("build_dir")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("build_dir")
    args = parser.parse_args(argv)
    if args.command == "extract":
        report = extract(args.source_video, args.build_dir)
    elif args.command == "apply":
        report = apply(args.video, args.build_dir)
    else:
        report = verify(args.build_dir)
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
