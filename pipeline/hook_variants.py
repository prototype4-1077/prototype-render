"""Render cheap VISUAL hook variants (A/B) of an already-built video.

script.json may declare:
  "hook_variants": [
    {"label": "B", "scenes": {"0": {"query": "...", "symbol_family": "..."}}}
  ]

Only visual fields may differ. Text is locked: changing narration would shift
every scene's timing and force a full re-render, while a visual-only variant
re-renders just the overridden scenes (build.py is resumable) and re-runs the
cheap concat/mux - the whole point of hook A/B being nearly free.

For each variant this tool: snapshots affected artifacts + script.json,
applies the overrides and clears those scenes' selections, reruns build.py,
renames final*.mp4 -> final*_hook<label>.mp4, then restores the originals.

Usage: python3 hook_variants.py <build_dir>"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

VISUAL_KEYS = {"query", "symbol_query", "image_prompt", "symbol_family",
               "visual_function", "primary_symbol", "human_role"}
CLEAR_KEYS = ("pexels_id", "stock_id", "source_id", "source_title", "source_url",
              "clip", "motion_verified", "motion_source", "symbol_family_source",
              "stock_frame_url", "stock_frame_url_checked")


def scene_files(bd, i):
    return [os.path.join(bd, pattern.format(i=i)) for pattern in
            ("clip_{i:02d}.mp4", "seg_{i:02d}.mp4", "youtube_seg_{i:02d}.mp4",
             "emb_{i:02d}.npy")]


def apply_overrides(script, variant):
    """Pure: returns (new_script, affected_indices). Raises on non-visual keys."""
    overrides = variant.get("scenes") or {}
    if not overrides:
        raise ValueError("hook variant has no scene overrides")
    new = copy.deepcopy(script)
    affected = []
    for key, fields in overrides.items():
        i = int(key)
        if i < 0 or i >= len(new["scenes"]):
            raise ValueError(f"hook variant scene index out of range: {i}")
        bad = set(fields) - VISUAL_KEYS
        if bad:
            raise ValueError(
                f"hook variants may only change visual fields, not {sorted(bad)}; "
                "changing text shifts narration timing and forces a full re-render")
        scene = new["scenes"][i]
        scene.update(fields)
        for k in CLEAR_KEYS:
            scene.pop(k, None)
        affected.append(i)
    return new, sorted(affected)


def run(bd):
    with open(os.path.join(bd, "script.json"), encoding="utf-8") as f:
        script = json.load(f)
    variants = script.get("hook_variants") or []
    if not variants:
        print("hook_variants: none declared in script.json")
        return
    finals = [n for n in os.listdir(bd) if n.startswith("final") and n.endswith(".mp4")
              and "_hook" not in n]
    if not finals:
        raise SystemExit("hook_variants: run the normal build first (no final*.mp4 found)")
    for variant in variants:
        label = str(variant.get("label") or "B")
        new_script, affected = apply_overrides(script, variant)
        snap = tempfile.mkdtemp(prefix=f"hook{label}-snapshot-")
        saved = []
        for i in affected:
            for path in scene_files(bd, i):
                if os.path.exists(path):
                    dest = os.path.join(snap, os.path.basename(path))
                    shutil.copy2(path, dest)
                    saved.append((path, dest))
                    os.remove(path)
        for name in finals:
            src = os.path.join(bd, name)
            shutil.copy2(src, os.path.join(snap, name))
            saved.append((src, os.path.join(snap, name)))
            os.remove(src)
        shutil.copy2(os.path.join(bd, "script.json"), os.path.join(snap, "script.json"))
        try:
            with open(os.path.join(bd, "script.json"), "w", encoding="utf-8") as f:
                json.dump(new_script, f, indent=1)
            subprocess.run([sys.executable, os.path.join(HERE, "build.py"), bd], check=True)
            for name in finals:
                built = os.path.join(bd, name)
                if os.path.exists(built):
                    stem, ext = os.path.splitext(name)
                    os.replace(built, os.path.join(bd, f"{stem}_hook{label}{ext}"))
        finally:
            shutil.copy2(os.path.join(snap, "script.json"), os.path.join(bd, "script.json"))
            for original, backup in saved:
                shutil.copy2(backup, original)
            shutil.rmtree(snap, ignore_errors=True)
        print(f"hook_variants: variant {label} rendered "
              f"({len(affected)} scene(s) re-picked: {affected})")


if __name__ == "__main__":
    run(sys.argv[1])
