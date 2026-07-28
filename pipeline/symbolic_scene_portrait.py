"""Portrait-safe wrapper for the deterministic symbolic scene renderer.

It preserves the complete 16:9 symbolic composition inside a cinematic 9:16
canvas, preventing center-crop loss of paired or edge-positioned metaphors.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys

from video_format import ENCODE_QUALITY, COLOR_TAGS
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import symbolic_scene as base

OUT_W, OUT_H = 1080, 1920
FPS = base.FPS


def compose_portrait(scene_img: Image.Image, palette: str, t: float) -> Image.Image:
    """Return a native 9:16 frame with the entire symbolic frame visible."""
    # Full-canvas atmosphere: an enlarged, darkened blur of the exact same scene.
    scale = max(OUT_W / scene_img.width, OUT_H / scene_img.height)
    bw, bh = int(scene_img.width * scale), int(scene_img.height * scale)
    bg = scene_img.resize((bw, bh), Image.Resampling.LANCZOS)
    left, top = (bw - OUT_W) // 2, (bh - OUT_H) // 2
    bg = bg.crop((left, top, left + OUT_W, top + OUT_H)).filter(
        ImageFilter.GaussianBlur(58)
    ).convert("RGBA")
    bg.alpha_composite(Image.new("RGBA", (OUT_W, OUT_H), (2, 5, 10, 150)))

    # Preserve the complete approved symbolic composition at a large readable size.
    panel_w = 1030
    panel_h = round(panel_w * base.H / base.W)
    panel = scene_img.resize((panel_w, panel_h), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", (panel_w, panel_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, panel_w - 1, panel_h - 1), radius=34, fill=255
    )
    panel.putalpha(mask)
    x = (OUT_W - panel_w) // 2
    y = 220 + round(18 * math.sin(base.TAU * t * 0.55))

    shadow = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (x - 13, y - 13, x + panel_w + 13, y + panel_h + 13),
        radius=45,
        fill=(0, 0, 0, 150),
        outline=(225, 242, 250, 55),
        width=3,
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    bg.alpha_composite(shadow)
    bg.alpha_composite(panel, (x, y))

    # Low-contrast continuation keeps the lower canvas alive behind captions.
    _, _, accent, light = base.PALETTES[palette]
    overlay = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for k in range(3):
        yy = 1050 + k * 165 + 20 * math.sin(base.TAU * t + k)
        points = []
        for j in range(80):
            u = j / 79
            xx = 70 + u * (OUT_W - 140)
            points.append(
                (xx, yy + (16 + 8 * k) * math.sin(base.TAU * (2.2 + k * 0.45) * u + base.TAU * t))
            )
        od.line(
            points,
            fill=(*base._mix(accent, light, k / 4), 65 - k * 12),
            width=3,
        )
    bg.alpha_composite(overlay)
    return bg.convert("RGB")


def render_clip(scene: dict, output: Path) -> None:
    duration = max(float(scene.get("duration") or 4.0), 0.5)
    frames = max(1, int(math.ceil(duration * FPS)))
    palette = scene.get("symbolic_palette") or "cyan"
    if palette not in base.PALETTES:
        palette = "cyan"
    _, _, accent, light = base.PALETTES[palette]
    kind = scene.get("symbolic_kind")
    renderer = base.RENDERERS.get(kind)
    if renderer is None:
        raise ValueError(f"unknown symbolic_kind: {kind}")

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".part.mp4")
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{OUT_W}x{OUT_H}", "-r", str(FPS), "-i", "-",
        "-an", "-c:v", "libx264", *ENCODE_QUALITY, *COLOR_TAGS,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for frame_index in range(frames):
            t = frame_index / max(frames - 1, 1)
            scene_img = base._background(palette, t)
            renderer(scene_img, t, accent, light)
            shade = Image.new("RGBA", scene_img.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(shade)
            sd.rectangle((0, 0, base.W, 60), fill=(0, 0, 0, 80))
            sd.rectangle((0, base.H - 58, base.W, base.H), fill=(0, 0, 0, 70))
            scene_img.paste(shade, (0, 0), shade)
            portrait = compose_portrait(scene_img, palette, t)
            process.stdin.write(np.asarray(portrait, dtype=np.uint8).tobytes())
    finally:
        if process.stdin:
            process.stdin.close()
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg exited {return_code}")
    os.replace(partial, output)


def main(build_dir: str, index: int) -> None:
    build = Path(build_dir)
    script_path = build / "script.json"
    script = json.loads(script_path.read_text(encoding="utf-8"))
    scene = script["scenes"][index]
    output = build / f"clip_{index:02d}.mp4"
    if (
        output.exists()
        and output.stat().st_size > 100_000
        and scene.get("portrait_symbolic_render_version") == 1
    ):
        print(f"portrait symbolic {index}: exists")
        return

    render_clip(scene, output)
    evidence = base.motion.temporal_evidence(str(output))
    motion_ok = bool(
        evidence.get("passes")
        or (
            evidence.get("active_region_ratio", 0) >= 0.015
            and evidence.get("frame_difference", 0) >= 2.4
        )
    )
    evidence["passes"] = motion_ok
    evidence["verification_profile"] = "deterministic_symbolic_portrait_v1"
    if not motion_ok:
        raise RuntimeError(
            f"portrait symbolic scene {index} failed temporal verification: {evidence}"
        )
    scene.update(
        {
            "clip": str(output),
            "motion_kind": "video",
            "motion_mode": "video",
            "motion_source": "deterministic_symbolic",
            "motion_verified": True,
            "motion_evidence": evidence,
            "symbolic_render_version": 2,
            "portrait_symbolic_render_version": 1,
            "portrait_safe": True,
            "source_width": OUT_W,
            "source_height": OUT_H,
        }
    )
    script_path.write_text(
        json.dumps(script, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"portrait symbolic {index}: {scene.get('symbolic_kind')} done "
        f"({output.stat().st_size} bytes)"
    )


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
