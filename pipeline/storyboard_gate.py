"""Reject visual drift for deterministic storyboards.

The gate verifies that every narrated scene was rendered by the exact symbolic
renderer requested in script.json. It prevents stock search, stale hero clips,
or provider metadata from silently replacing the approved visual meaning.
"""
from __future__ import annotations

import json, os, subprocess, sys
from pathlib import Path

ALLOWED_KINDS = {
    "identity_flow", "keys_bills_object", "whirlpool_material",
    "whirlpool_persistence", "forces_pattern", "self_change",
    "memory_tiles", "relationship_pieces", "self_rebuild",
    "song_not_object", "song_transfer", "body_receiver", "wifi_taxes",
    "kitchen_forget", "family_network", "city_bricks", "flame_process",
    "costume_dance", "thing_vs_pattern", "instrument_final",
}


def probe(path: Path) -> tuple[bool, float]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ], capture_output=True, text=True)
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        duration = 0.0
    return result.returncode == 0 and duration > 0.5, duration


def validate(build_dir: str) -> dict:
    bd = Path(build_dir)
    script = json.loads((bd / "script.json").read_text(encoding="utf-8"))
    rows, failures = [], []
    scenes = script.get("scenes") or []
    if len(scenes) != 20:
        failures.append(f"expected 20 audited scenes, found {len(scenes)}")
    for index, scene in enumerate(scenes):
        kind = scene.get("symbolic_kind")
        clip = bd / f"clip_{index:02d}.mp4"
        ok, actual_duration = probe(clip) if clip.exists() else (False, 0.0)
        expected = float(scene.get("duration") or 0.0)
        source_ok = scene.get("motion_source") == "deterministic_symbolic"
        kind_ok = kind in ALLOWED_KINDS
        version_ok = scene.get("symbolic_render_version") == 2
        evidence_ok = bool((scene.get("motion_evidence") or {}).get("passes"))
        no_stock = not any(scene.get(key) for key in (
            "stock_id", "pexels_id", "source_url", "stock_frame_url",
            "hero_generated", "hero_fallback",
        ))
        duration_ok = ok and abs(actual_duration - expected) <= max(.25, expected * .025)
        passed = all((source_ok, kind_ok, version_ok, evidence_ok, no_stock, duration_ok))
        row = {
            "index": index, "kind": kind, "passed": passed,
            "source_ok": source_ok, "kind_ok": kind_ok,
            "version_ok": version_ok, "evidence_ok": evidence_ok,
            "no_stock_substitution": no_stock, "duration_ok": duration_ok,
            "expected_duration": round(expected, 3),
            "actual_duration": round(actual_duration, 3),
            "semantic_anchor": scene.get("semantic_anchor"),
        }
        rows.append(row)
        if not passed:
            failures.append(f"scene {index} failed storyboard gate: {row}")
    report = {
        "schema_version": 1,
        "slug": script.get("slug"),
        "passed": not failures,
        "scene_count": len(scenes),
        "exact_audio_sha256": script.get("external_audio_sha256"),
        "failures": failures,
        "scenes": rows,
    }
    (bd / "storyboard_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    report = validate(sys.argv[1])
    print(f"storyboard gate: {'PASS' if report['passed'] else 'FAIL'} ({report['scene_count']} scenes)")
    if not report["passed"]:
        for failure in report["failures"]:
            print(f"ERROR: {failure}", file=sys.stderr)
        raise SystemExit(1)
