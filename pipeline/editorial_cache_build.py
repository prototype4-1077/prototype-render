"""Rebuild scene masters from cached clips without re-fetching or regenerating art.

This is used after a successful full render to create the selective-revision
cache. It trusts the successful render's already-validated clip files, then
recreates overlays, scene masters, and canonical finals in a clean job.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

import build
import hero
import still_reference
import tts


def _install_cache_only_policy(build_dir: Path) -> None:
    def only_missing_clips(_bd, script):
        return [
            index for index, _scene in enumerate(script.get("scenes") or [])
            if not (build_dir / f"clip_{index:02d}.mp4").exists()
        ]

    still_reference.stock_targets = only_missing_clips
    still_reference.reference_is_current = lambda *_args, **_kwargs: True
    still_reference.validate = lambda *_args, **_kwargs: None
    hero.source_matches = lambda *_args, **_kwargs: True


def _ensure_voice_manifest(build_dir: Path) -> None:
    """Prevent a valid cached voice take from being mistaken for stale audio.

    The render cache historically stored vo.mp3 and words.json but not the small
    voiceover manifest. Reconstruct only the fingerprint field used by build.py;
    the actual approved delivery mix is separately locked from the finished file.
    """
    voice = build_dir / "vo.mp3"
    manifest = build_dir / "voiceover-manifest.json"
    script_path = build_dir / "script.json"
    if not voice.exists() or manifest.exists() or not script_path.exists():
        return
    script = json.loads(script_path.read_text(encoding="utf-8"))
    if script.get("user_vo"):
        return
    model_id = tts.resolve_model_id(script)
    manifest.write_text(
        json.dumps(
            {
                "tts_fingerprint": tts.tts_fingerprint(script, model_id),
                "restored_for_editorial_cache": True,
                "model_id": model_id,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )


def run(build_dir: str | Path, *, max_passes: int = 30) -> int:
    build_dir = Path(build_dir).resolve()
    _ensure_voice_manifest(build_dir)
    _install_cache_only_policy(build_dir)
    build.BUDGET = float(os.environ.get("EDITORIAL_BUILD_PASS_BUDGET", "1200"))
    for pass_number in range(1, max_passes + 1):
        build.T0 = time.time()
        print(f"EDITORIAL CACHE pass {pass_number}/{max_passes}", flush=True)
        try:
            build.main(str(build_dir))
            return 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 0
            if code not in (0, None):
                return int(code)
            continue
    print("editorial cache build exceeded resumable pass limit", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir")
    parser.add_argument("--max-passes", type=int, default=30)
    args = parser.parse_args(argv)
    return run(args.build_dir, max_passes=args.max_passes)


if __name__ == "__main__":
    raise SystemExit(main())
