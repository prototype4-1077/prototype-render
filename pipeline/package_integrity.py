"""Fingerprint render-package inputs to close the preflight/checkout race.

The digest deliberately excludes generated outputs, diagnostics, request markers,
and materialized review files. It includes script, narration/audio inputs, committed
art, references, continuity contracts, custom score inputs, and package metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

SCHEMA_VERSION = 1
EXACT_EXCLUDES = {
    "preflight-report.json",
    "package-fingerprint.json",
    "render.request",
    "render-started.txt",
    "render-blocked.txt",
    "run-id.txt",
    "governor-summary.json",
    "governor-review.json",
    "render-status.json",
    "quality_report.json",
    "scene-review.json",
    "scene-review.html",
    "alts.json",
    "alts_sheet.jpg",
    "motion_report.json",
    "motion_report_short.json",
    "visual_symbol_report.json",
    "still_reference_report.json",
    "coherence_report.json",
    "music_variants.json",
    "CREDITS.txt",
}
EXCLUDED_DIRS = {"governor", "telemetry", "alts", "__pycache__"}
EXCLUDED_PREFIXES = (
    "clip_", "seg_", "youtube_seg_", "final", "emb_", "cap_", "youtube_cap_",
)
EXCLUDED_SUFFIXES = (
    ".partial", ".part", ".quality-rejected", ".tmp",
)


def _is_generated(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDED_DIRS for part in rel.parts[:-1]):
        return True
    name = rel.name
    if name in EXACT_EXCLUDES:
        return True
    if any(name.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return True
    if any(name.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return True
    if name.endswith(".sfx-ok") or name == ".probe-cache.json":
        return True
    return False


def package_files(build_dir: str | os.PathLike[str]) -> list[Path]:
    root = Path(build_dir).resolve()
    if not root.is_dir():
        return []
    files = [
        path for path in root.rglob("*")
        if path.is_file() and not _is_generated(path, root)
    ]
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def fingerprint(build_dir: str | os.PathLike[str]) -> dict:
    root = Path(build_dir).resolve()
    digest = hashlib.sha256()
    rows = []
    for path in package_files(root):
        rel = path.relative_to(root).as_posix()
        file_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                file_digest.update(block)
        size = path.stat().st_size
        sha = file_digest.hexdigest()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
        digest.update(b"\n")
        rows.append({"path": rel, "size_bytes": size, "sha256": sha})
    return {
        "schema_version": SCHEMA_VERSION,
        "slug": root.name,
        "fingerprint": digest.hexdigest(),
        "file_count": len(rows),
        "files": rows,
    }


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("build_dir")
    snap.add_argument("--output")
    verify = sub.add_parser("verify")
    verify.add_argument("build_dir")
    verify.add_argument("--expected", required=True)
    show = sub.add_parser("show")
    show.add_argument("build_dir")
    args = parser.parse_args(argv)

    payload = fingerprint(args.build_dir)
    if args.command == "snapshot":
        output = Path(args.output) if args.output else Path(args.build_dir) / "package-fingerprint.json"
        atomic_json(output, payload)
        print(payload["fingerprint"])
        return 0
    if args.command == "verify":
        if payload["fingerprint"] != args.expected:
            print(json.dumps({
                "status": "mismatch",
                "expected": args.expected,
                "actual": payload["fingerprint"],
                "slug": payload["slug"],
                "file_count": payload["file_count"],
            }, indent=2))
            return 2
        print(f"PACKAGE INTEGRITY OK {payload['slug']} {payload['fingerprint']}")
        return 0
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
