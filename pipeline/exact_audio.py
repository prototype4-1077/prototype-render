#!/usr/bin/env python3
"""Restore an exact narration file from authenticated repository text parts.

The transport is deliberately lossless: the original bytes are base64 encoded,
split into ordinary Git blobs, decoded on the runner, and then verified before
the destination is atomically published.  This module never transcodes audio.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


PART_RE = re.compile(r"\.part(\d+)$")


class ExactAudioError(RuntimeError):
    """Raised when a narration package is missing, malformed, or inexact."""


def _ordered_parts(pattern: str) -> list[Path]:
    indexed: list[tuple[int, Path]] = []
    for raw_path in glob.glob(pattern):
        path = Path(raw_path)
        match = PART_RE.search(path.name)
        if match:
            indexed.append((int(match.group(1)), path))

    if not indexed:
        raise ExactAudioError(f"no narration parts matched: {pattern}")

    indexed.sort(key=lambda item: item[0])
    indices = [index for index, _ in indexed]
    expected = list(range(len(indexed)))
    if indices != expected:
        raise ExactAudioError(
            f"narration parts must be contiguous from part000; found {indices}"
        )
    return [path for _, path in indexed]


def decode_parts(pattern: str) -> tuple[bytes, list[Path]]:
    """Decode a complete ordered base64 package without altering its bytes."""

    parts = _ordered_parts(pattern)
    encoded_chunks: list[str] = []
    for path in parts:
        try:
            encoded_chunks.append("".join(path.read_text(encoding="ascii").split()))
        except UnicodeError as exc:
            raise ExactAudioError(f"non-ASCII narration part: {path}") from exc

    encoded = "".join(encoded_chunks)
    try:
        return base64.b64decode(encoded, validate=True), parts
    except (binascii.Error, ValueError) as exc:
        raise ExactAudioError("narration parts are not valid complete base64") from exc


def probe_audio(path: Path) -> tuple[str, float]:
    """Return the container format and duration reported by ffprobe."""

    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        info = json.loads(completed.stdout)["format"]
        return str(info["format_name"]), float(info["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise ExactAudioError(f"unable to probe restored narration: {path}") from exc


def restore_exact_audio(
    *,
    parts_glob: str,
    output: Path,
    expected_sha256: str,
    expected_size: int,
    expected_duration: float,
    source_attachment: str,
    report: Path | None = None,
    duration_tolerance: float = 0.001,
) -> dict[str, Any]:
    """Restore, verify, and atomically publish an exact MP3 narration file."""

    data, parts = decode_parts(parts_glob)
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ExactAudioError(
            f"exact audio SHA-256 mismatch: {actual_sha256} != {expected_sha256}"
        )
    if len(data) != expected_size:
        raise ExactAudioError(
            f"exact audio size mismatch: {len(data)} != {expected_size}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)

        format_name, actual_duration = probe_audio(temporary_path)
        if "mp3" not in {name.strip() for name in format_name.split(",")}:
            raise ExactAudioError(f"restored narration is not MP3: {format_name}")
        if abs(actual_duration - expected_duration) > duration_tolerance:
            raise ExactAudioError(
                "exact audio duration mismatch: "
                f"{actual_duration:.6f} != {expected_duration:.6f}"
            )

        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    verification: dict[str, Any] = {
        "source_attachment": source_attachment,
        "transport": "authenticated private GitHub repository base64 parts",
        "part_count": len(parts),
        "sha256": actual_sha256,
        "size_bytes": len(data),
        "duration_seconds": actual_duration,
        "format": format_name,
        "exact_bytes_restored": True,
        "transcoded_before_pipeline": False,
        "pipeline_voiceover_path": output.name,
    }
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    return verification


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", required=True, dest="parts_glob")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sha256", required=True, dest="expected_sha256")
    parser.add_argument("--size", required=True, type=int, dest="expected_size")
    parser.add_argument("--duration", required=True, type=float, dest="expected_duration")
    parser.add_argument("--source-attachment", required=True)
    parser.add_argument("--report", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        verification = restore_exact_audio(**vars(args))
    except ExactAudioError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(json.dumps(verification, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
