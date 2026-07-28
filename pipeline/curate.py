"""Create visual candidate sheets for human review before pinning Pexels IDs.

Usage:
    python3 pipeline/curate.py build/<slug> 4,7,18

Each requested scene gets a JPG containing the twelve highest-ranked clips and
a JSON sidecar with IDs/scores. This turns a vague reroll into a deterministic
editorial choice while keeping the normal render path fully automatic.
"""
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

from video_format import ENCODE_QUALITY, COLOR_TAGS

import footage
import profiles
import visual_symbols


COLS, ROWS = 4, 3
CELL_W, CELL_H = 400, 260
HEADER_H = 96


def wrap(draw, text, width):
    words = text.split()
    lines, line = [], []
    for word in words:
        test = " ".join(line + [word])
        if line and draw.textlength(test) > width:
            lines.append(" ".join(line))
            line = [word]
        else:
            line.append(word)
    if line:
        lines.append(" ".join(line))
    return lines[:3]


def sheet_for_scene(build_dir, script, i, out_dir):
    scene = script["scenes"][i]
    profile = profiles.resolve(script)
    query = visual_symbols.effective_query(scene)
    videos = footage.search(query, script.get("genre"), profile, per_page=32)
    ranked = footage.rank(
        query,
        videos,
        scene.get("duration"),
        script.get("genre"),
        profile,
    )[: COLS * ROWS]
    if not ranked:
        raise RuntimeError(f"scene {i}: no candidates for {query!r}")

    canvas = Image.new("RGB", (COLS * CELL_W, HEADER_H + ROWS * CELL_H), (14, 16, 20))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=16)
    draw.text((18, 12), f"SCENE {i:02d}", fill=(244, 222, 108), font=font)
    y = 38
    for line in wrap(draw, query, canvas.width - 36):
        draw.text((18, y), line, fill=(235, 235, 235), font=small)
        y += 18

    meta = []
    for n, (score, video, thumb, _embedding) in enumerate(ranked):
        row, col = divmod(n, COLS)
        x, y = col * CELL_W, HEADER_H + row * CELL_H
        try:
            source = thumb if thumb is not None else footage.get_thumb(video, 520)
            thumb = ImageOps.fit(source, (CELL_W, CELL_H - 36),
                                 method=Image.Resampling.LANCZOS)
        except Exception:
            thumb = Image.new("RGB", (CELL_W, CELL_H - 36), (35, 35, 35))
        canvas.paste(thumb, (x, y))
        draw.rectangle((x, y + CELL_H - 36, x + CELL_W, y + CELL_H), fill=(0, 0, 0))
        label = f"#{n + 1:02d}  ID {video['id']}  score {score:.1f}  {video['duration']}s"
        draw.text((x + 9, y + CELL_H - 28), label, fill=(255, 255, 255), font=small)
        meta.append({"rank": n + 1, "id": video["id"], "score": round(score, 3),
                     "duration": video["duration"], "url": video.get("url")})

    stem = os.path.join(out_dir, f"scene_{i:02d}")
    canvas.save(stem + ".jpg", quality=92)
    json.dump({"scene": i, "text": scene["text"], "query": query, "candidates": meta},
              open(stem + ".json", "w"), indent=2, ensure_ascii=False)
    print(f"scene {i}: {len(meta)} candidates -> {stem}.jpg")


def make_reel(out_dir, build_dir):
    """Encode the sheets as final.mp4 so the existing render artifact uploads them."""
    sheets = sorted(os.path.join(out_dir, x) for x in os.listdir(out_dir)
                    if x.startswith("scene_") and x.endswith(".jpg"))
    if not sheets:
        raise RuntimeError("no curation sheets were created")
    listing = os.path.join(out_dir, "reel.txt")
    with open(listing, "w") as f:
        for path in sheets:
            f.write(f"file '{os.path.abspath(path)}'\n")
            f.write("duration 5\n")
        f.write(f"file '{os.path.abspath(sheets[-1])}'\n")
    out = os.path.join(build_dir, "final.mp4")
    r = subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing,
        "-vf", "scale=1600:880:force_original_aspect_ratio=decrease,"
               "pad=1600:880:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p",
        "-r", "30", "-c:v", "libx264", *ENCODE_QUALITY, *COLOR_TAGS,
        "-movflags", "+faststart", out,
    ], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"curation reel ffmpeg failed: {r.stderr[-800:]}")
    print(f"curation reel -> {out}")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: curate.py build/<slug> 4,7,18")
    build_dir = sys.argv[1].rstrip("/")
    script = json.load(open(f"{build_dir}/script.json"))
    profile = profiles.resolve(script)
    if visual_symbols.apply_plan(script, profile):
        json.dump(
            script, open(f"{build_dir}/script.json", "w"),
            indent=1, ensure_ascii=False,
        )
    visual_symbols.write_report(build_dir, script, profile)
    indexes = [int(x) for x in sys.argv[2].split(",") if x.strip()]
    out_dir = os.path.join(build_dir, "curation")
    os.makedirs(out_dir, exist_ok=True)
    for i in indexes:
        if not 0 <= i < len(script["scenes"]):
            raise SystemExit(f"scene index out of range: {i}")
        sheet_for_scene(build_dir, script, i, out_dir)
    make_reel(out_dir, build_dir)


if __name__ == "__main__":
    main()
