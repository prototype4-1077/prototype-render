"""Verify every story-locked source is native portrait and preserves full symbols."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        width, height = result.stdout.strip().split("x", 1)
        return int(width), int(height)
    except Exception:
        return 0, 0


def main(build_dir: str) -> int:
    build = Path(build_dir)
    script = json.loads((build / "script.json").read_text(encoding="utf-8"))
    failures = []
    rows = []
    for index, scene in enumerate(script.get("scenes") or []):
        clip = build / f"clip_{index:02d}.mp4"
        width, height = dimensions(clip) if clip.exists() else (0, 0)
        row = {
            "index": index,
            "kind": scene.get("symbolic_kind"),
            "portrait_safe": scene.get("portrait_safe") is True,
            "portrait_version": scene.get("portrait_symbolic_render_version"),
            "width": width,
            "height": height,
            "native_9_16": width == 1080 and height == 1920,
            "source": scene.get("motion_source"),
        }
        row["passed"] = all(
            (
                row["portrait_safe"],
                row["portrait_version"] == 1,
                row["native_9_16"],
                row["source"] == "deterministic_symbolic",
            )
        )
        rows.append(row)
        if not row["passed"]:
            failures.append(f"scene {index} is not a verified portrait-safe source: {row}")
    report = {
        "schema_version": 1,
        "slug": script.get("slug"),
        "passed": not failures and len(rows) == 20,
        "scene_count": len(rows),
        "failures": failures,
        "scenes": rows,
    }
    (build / "portrait_storyboard_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"portrait storyboard gate: {'PASS' if report['passed'] else 'FAIL'} "
        f"({len(rows)} scenes)"
    )
    if not report["passed"]:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
