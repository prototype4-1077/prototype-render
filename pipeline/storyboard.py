"""Deterministic literal motion graphics for narration that stock cannot depict.

The approved ``trained-not-to-look`` revision established a clear rule: when a
line names labels, counters, settings, evidence, or a mental mechanism, show the
mechanism itself instead of substituting unrelated lifestyle footage. These
cards are deliberately simple, readable, and fully temporal.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import motion
from video_format import BAND_HEIGHT as H, BAND_WIDTH as W, FPS

HERE = Path(__file__).resolve().parent
BG = (9, 19, 27)
BG2 = (23, 17, 24)
INK = (238, 229, 196)
CYAN = (90, 220, 231)
CORAL = (234, 112, 101)
MAGENTA = (211, 94, 178)
GOLD = (227, 190, 91)
MUTED = (112, 137, 145)

GRAPHIC_CUES = {
    "autofocus", "balance scale", "belief lens", "camera filter", "counter",
    "evidence board", "filter settings", "focus box", "interface", "label",
    "like counter", "magnifying", "maze", "pedestal", "preset", "receipt",
    "rubber stamp", "settings panel", "stamp", "timeline conveyor", "toggle",
    "viewfinder",
}
ABSTRACT_TERMS = {
    "ambition", "belief", "deception", "evil intent", "exhaustion", "failure",
    "fear", "importance", "impossible", "love", "normal", "perception",
    "popularity", "realistic", "selfish", "success", "value", "worth",
}


def _font(name: str, size: int):
    paths = [HERE / "fonts" / name, HERE / "fonts" / "Questrial-Regular.ttf"]
    for path in paths:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def head(size=30):
    return _font("Baloo2-ExtraBold.ttf", size)


def body(size=22):
    return _font("Questrial-Regular.ttf", size)


def _clean(value: object, limit: int = 22) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().upper()
    if len(text) <= limit:
        return text
    words, out = text.split(), []
    for word in words:
        if len(" ".join(out + [word])) > limit:
            break
        out.append(word)
    return " ".join(out) or text[:limit]


def phrases(scene: dict) -> list[str]:
    values = [
        _clean(item)
        for item in scene.get("keywords") or []
        if str(item).strip()
    ]
    if not values and scene.get("primary_symbol"):
        values = [_clean(scene["primary_symbol"])]
    if not values and scene.get("semantic_anchor"):
        values = [_clean(scene["semantic_anchor"])]
    return values[:4] or ["NOTICE", "LOOK AGAIN"]


def preferred(
    scene: dict,
    index: int | None = None,
    total: int | None = None,
) -> bool:
    mode = str(scene.get("narrative_mode") or "").lower()
    if mode in {"literal_graphic", "storyboard"}:
        return True
    if mode in {"stock", "stock_ok", "atmosphere"}:
        return False
    fraction = float(index or 0) / max(float(total or 1), 1.0)
    if fraction > 0.72:
        return False
    blob = " ".join(
        str(value or "").lower()
        for value in (
            scene.get("query"),
            scene.get("symbol_query"),
            scene.get("semantic_anchor"),
            scene.get("primary_symbol"),
            " ".join(map(str, scene.get("keywords") or [])),
        )
    )
    # A simple, concrete phone-camera line was retained in the approved edit.
    if len(str(scene.get("text") or "")) < 70 and "smartphone camera" in blob:
        return False
    if any(cue in blob for cue in GRAPHIC_CUES):
        return True
    abstract_hits = sum(1 for term in ABSTRACT_TERMS if term in blob)
    family = str(scene.get("symbol_family") or "").lower()
    function = str(scene.get("visual_function") or "").lower()
    return abstract_hits >= 2 and family in {
        "identity", "language", "perception", "object_tool", "collective",
        "time_memory", "geometry", "light_atmosphere", "pathway",
    } and function in {
        "literal_anchor", "mechanism", "contrast", "recursion", "boundary",
    }


def _ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


_YY, _XX = np.mgrid[0:H, 0:W].astype(np.float32)
_MIX = (_YY / max(H - 1, 1))[..., None]
_VIGNETTE = (
    ((_XX - W / 2) / W) ** 2 + ((_YY - H / 2) / H) ** 2
)[..., None]
_BG_A = np.asarray(BG, dtype=np.float32).reshape(1, 1, 3)
_BG_B = np.asarray(BG2, dtype=np.float32).reshape(1, 1, 3)
_BASE_BACKGROUND = (
    _BG_A * (1.0 - _MIX)
    + _BG_B * _MIX
    - _VIGNETTE * np.asarray([14, 11, 8], np.float32)
)
_BACKGROUND_IMAGE = Image.fromarray(
    np.clip(_BASE_BACKGROUND, 0, 255).astype(np.uint8), "RGB"
)


def _background(_progress: float) -> Image.Image:
    # Motion lives in the objects, counters, lenses, and scan lines. Keeping the
    # plate cached makes a multi-scene build fast and memory-stable.
    return _BACKGROUND_IMAGE.copy()


def _header(draw: ImageDraw.ImageDraw, scene: dict):
    label = _clean(
        scene.get("semantic_anchor")
        or scene.get("primary_symbol")
        or "STORYLINE",
        46,
    )
    draw.text((W // 2, 36), label, font=head(24), fill=MUTED, anchor="mm")


def _card(draw, box, text, fill=INK, outline=CYAN):
    x0, y0, x1, y1 = map(int, box)
    draw.rounded_rectangle(
        (x0, y0, x1, y1), radius=12, fill=fill, outline=outline, width=2
    )
    draw.text(
        ((x0 + x1) // 2, (y0 + y1) // 2),
        text,
        font=head(22),
        fill=BG,
        anchor="mm",
    )


def _labels(image, scene, progress):
    draw = ImageDraw.Draw(image)
    _header(draw, scene)
    values = phrases(scene)
    draw.ellipse((135, 105, 235, 205), outline=MUTED, width=4)
    draw.polygon(
        [(105, 440), (265, 440), (238, 220), (132, 220)],
        fill=(35, 44, 55),
        outline=MUTED,
    )
    colors = (INK, (220, 235, 224), (240, 214, 190), (213, 225, 233))
    for number, text in enumerate(values):
        phase = _ease((progress - number * 0.12) / 0.35)
        y = 150 + number * 74
        x = 300 + phase * (120 + number * 42)
        _card(
            draw,
            (x, y, x + 250, y + 52),
            text,
            fill=colors[number % 4],
            outline=(70, 80, 86),
        )
    scan_x = int(80 + (W - 160) * ((progress * 0.7) % 1.0))
    draw.line((scan_x, 92, scan_x, H - 42), fill=(50, 160, 170), width=2)


def _path(image, scene, progress):
    draw = ImageDraw.Draw(image)
    _header(draw, scene)
    left, top, right, bottom = 110, 92, W - 110, H - 72
    draw.rounded_rectangle(
        (left, top, right, bottom),
        18,
        fill=(235, 230, 207),
        outline=(130, 126, 112),
        width=3,
    )
    for x in range(left + 40, right - 20, 70):
        for y in range(top + 35, bottom - 20, 58):
            if (x // 70 + y // 58) % 3:
                draw.line((x, y, x + 35, y), fill=(120, 118, 107), width=3)
            else:
                draw.line((x, y, x, y + 30), fill=(120, 118, 107), width=3)
    points = [
        (150, bottom - 55),
        (300, bottom - 140),
        (470, bottom - 140),
        (600, top + 180),
        (790, top + 180),
        (910, top + 95),
    ]
    upto = max(2, int(2 + _ease(progress) * (len(points) - 2)))
    draw.line(points[:upto], fill=CORAL, width=7, joint="curve")
    travel = min(progress * 1.05, 0.999) * (len(points) - 1)
    point_index = min(int(travel), len(points) - 2)
    fraction = travel - point_index
    x = points[point_index][0] * (1 - fraction) + points[point_index + 1][0] * fraction
    y = points[point_index][1] * (1 - fraction) + points[point_index + 1][1] * fraction
    draw.ellipse(
        (x - 12, y - 12, x + 12, y + 12),
        fill=CYAN,
        outline=(255, 255, 255),
        width=2,
    )
    values = phrases(scene)
    for number, text in enumerate(values[:2]):
        _card(
            draw,
            (
                right - 245,
                bottom - 90 - number * 66,
                right - 25,
                bottom - 44 - number * 66,
            ),
            text,
            fill=INK if number == 0 else (222, 230, 216),
            outline=(120, 120, 110),
        )


def _counters(image, scene, progress):
    draw = ImageDraw.Draw(image)
    _header(draw, scene)
    values = phrases(scene) + ["VALUE", "WORTH"]
    for number, x in enumerate((120, 590)):
        color = CYAN if number == 0 else MAGENTA
        draw.rounded_rectangle(
            (x, 120, x + 370, 320),
            18,
            fill=(12, 27, 36),
            outline=color,
            width=4,
        )
        draw.text(
            (x + 185, 160),
            values[number] if number < len(values) else "MEASURE",
            font=head(24),
            fill=color,
            anchor="mm",
        )
        amount = int((9100 + number * 180) * _ease(min(progress * 1.4, 1.0)))
        draw.text(
            (x + 185, 232),
            f"{amount:,}",
            font=head(48),
            fill=INK,
            anchor="mm",
        )
        draw.line((x + 85, 280, x + 285, 280), fill=color, width=4)
    pulse = 1.0 + 0.08 * math.sin(progress * math.tau * 2)
    center_x, center_y = W // 2, 430
    size = 55 * pulse
    draw.polygon(
        [
            (center_x, center_y + size),
            (center_x - size, center_y),
            (center_x - size * 0.7, center_y - size * 0.55),
            (center_x, center_y - size * 0.05),
            (center_x + size * 0.7, center_y - size * 0.55),
            (center_x + size, center_y),
        ],
        fill=GOLD,
    )
    draw.text(
        (center_x, 540), "VALUE  ≠  WORTH", font=head(26), fill=INK, anchor="mm"
    )


def _clock(image, scene, progress):
    draw = ImageDraw.Draw(image)
    _header(draw, scene)
    values = phrases(scene) + ["AMBITION", "REALISTIC"]
    draw.line((W // 2, 95, W // 2, H - 55), fill=(75, 67, 72), width=2)
    center_x, center_y, radius = 265, 260, 105
    draw.ellipse(
        (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        ),
        fill=(235, 230, 207),
        outline=(120, 115, 105),
        width=4,
    )
    angle = -math.pi / 2 + progress * math.tau * 1.2
    draw.line(
        (
            center_x,
            center_y,
            center_x + math.cos(angle) * 72,
            center_y + math.sin(angle) * 72,
        ),
        fill=CORAL,
        width=6,
    )
    draw.line((center_x, center_y, center_x, center_y - 55), fill=(45, 48, 50), width=5)
    draw.text(
        (center_x, 405),
        f"{values[0]} → {values[1] if len(values) > 1 else 'AMBITION'}",
        font=head(22),
        fill=INK,
        anchor="mm",
    )
    object_x, object_y = 760, 400
    draw.ellipse((object_x - 15, object_y - 35, object_x + 15, object_y - 5), fill=GOLD)
    spread = 70 + 120 * _ease(progress)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse(
        (
            object_x - spread,
            object_y - 15 - spread * 0.45,
            object_x + spread,
            object_y + spread * 0.45,
        ),
        fill=(45, 10, 20, 120),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    image.paste(shadow, (0, 0), shadow)
    draw = ImageDraw.Draw(image)
    draw.ellipse((object_x - 15, object_y - 35, object_x + 15, object_y - 5), fill=GOLD)
    draw.text(
        (object_x, 505),
        f"{values[2] if len(values) > 2 else 'FEAR'} → "
        f"{values[3] if len(values) > 3 else 'REALISTIC'}",
        font=head(22),
        fill=INK,
        anchor="mm",
    )


def _perception(image, scene, progress):
    draw = ImageDraw.Draw(image)
    _header(draw, scene)
    draw.rounded_rectangle(
        (90, 95, W - 90, H - 60),
        18,
        fill=(16, 36, 44),
        outline=(67, 103, 112),
        width=3,
    )
    icons = [
        (215, 300, "DOOR"),
        (430, 280, "FACE"),
        (650, 300, "OBJECT"),
        (860, 270, "LOVE"),
    ]
    for number, (x, y, label) in enumerate(icons):
        fill = (226, 218, 186) if number == 0 else (80, 88, 95)
        draw.rounded_rectangle(
            (x - 70, y - 70, x + 70, y + 70),
            12,
            fill=fill,
            outline=(90, 110, 115),
            width=2,
        )
        if number != 0:
            draw.text(
                (x, y), label, font=head(18), fill=(170, 175, 175), anchor="mm"
            )
    target = int((progress * 2.2) % len(icons))
    x, y, _label = icons[target]
    padding = 88 + 7 * math.sin(progress * math.tau * 3)
    draw.rectangle(
        (x - padding, y - padding, x + padding, y + padding),
        outline=CYAN,
        width=5,
    )
    values = phrases(scene)
    draw.text(
        (W // 2, 505),
        f"AUTOFOCUS: {values[target % len(values)]}",
        font=head(25),
        fill=INK,
        anchor="mm",
    )
    scan_y = int(115 + (H - 210) * ((progress * 0.8) % 1.0))
    draw.line((105, scan_y, W - 105, scan_y), fill=(70, 150, 158), width=2)


def _evidence(image, scene, progress):
    draw = ImageDraw.Draw(image)
    _header(draw, scene)
    draw.rounded_rectangle(
        (70, 85, 720, H - 55),
        18,
        fill=(91, 61, 36),
        outline=(150, 110, 68),
        width=4,
    )
    values = phrases(scene)
    palette = [
        (235, 226, 184),
        (195, 225, 213),
        (238, 190, 190),
        (213, 211, 235),
    ]
    positions = [(120, 130), (360, 115), (145, 295), (430, 300)]
    for number, text in enumerate(values):
        x, y = positions[number % len(positions)]
        phase = _ease((progress - number * 0.10) / 0.35)
        adjusted_y = y + (1 - phase) * 60
        _card(
            draw,
            (x, adjusted_y, x + 205, adjusted_y + 62),
            text,
            fill=palette[number % 4],
            outline=(100, 70, 45),
        )
    lens_x = 250 + 340 * (0.5 + 0.5 * math.sin(progress * math.tau))
    lens_y = 250 + 90 * math.sin(progress * math.tau * 0.7)
    draw.ellipse(
        (lens_x - 95, lens_y - 95, lens_x + 95, lens_y + 95),
        outline=CYAN,
        width=8,
    )
    draw.line(
        (lens_x + 70, lens_y + 70, lens_x + 150, lens_y + 150),
        fill=CYAN,
        width=12,
    )
    draw.rounded_rectangle(
        (770, 170, 1010, 430),
        14,
        fill=(18, 30, 34),
        outline=MUTED,
        width=3,
    )
    draw.text((890, 205), "UNNOTICED", font=head(20), fill=MUTED, anchor="mm")
    card_y = 250 + int((progress * 100) % 120)
    _card(
        draw,
        (800, card_y, 980, card_y + 52),
        "KIND",
        fill=(202, 231, 204),
        outline=(80, 120, 90),
    )


def _filter(image, scene, progress):
    draw = ImageDraw.Draw(image)
    _header(draw, scene)
    draw.rounded_rectangle(
        (90, 105, 560, H - 70),
        18,
        fill=(220, 214, 180),
        outline=(120, 120, 100),
        width=3,
    )
    draw.polygon(
        [(110, 125), (410, 125), (545, H - 90), (290, H - 90)],
        fill=(236, 229, 190),
    )
    draw.rounded_rectangle(
        (620, 90, 1010, H - 55),
        20,
        fill=(12, 32, 40),
        outline=(100, 160, 170),
        width=3,
    )
    draw.text((815, 130), "FILTER SETTINGS", font=head(25), fill=INK, anchor="mm")
    values = phrases(scene) + ["DANGER", "REJECTION", "NOT ENOUGH", "TRUST"]
    for number, label in enumerate(values[:4]):
        y = 205 + number * 78
        draw.text((670, y), label, font=body(20), fill=INK, anchor="lm")
        enabled = number < 3 or progress > 0.75
        fill = CYAN if enabled else MUTED
        draw.rounded_rectangle((900, y - 16, 970, y + 16), 16, outline=fill, width=3)
        knob_x = 952 if enabled else 918
        draw.ellipse((knob_x - 11, y - 11, knob_x + 11, y + 11), fill=fill)
    draw.text(
        (815, 540), "INSTALLED YEARS AGO", font=body(16), fill=MUTED, anchor="mm"
    )


def _scale(image, scene, progress):
    draw = ImageDraw.Draw(image)
    _header(draw, scene)
    center_x, center_y = W // 2, 270
    tilt = math.sin(progress * math.pi) * 0.08
    length = 520
    left_x = center_x - length / 2
    left_y = center_y - math.sin(tilt) * length / 2
    right_x = center_x + length / 2
    right_y = center_y + math.sin(tilt) * length / 2
    draw.line((left_x, left_y, right_x, right_y), fill=GOLD, width=8)
    draw.line((center_x, center_y, center_x, 505), fill=GOLD, width=14)
    draw.polygon(
        [(center_x, 470), (center_x - 70, 555), (center_x + 70, 555)],
        fill=GOLD,
    )
    values = phrases(scene) + ["DECEPTION", "INHERITANCE"]
    for number, (x, y) in enumerate(((left_x, left_y), (right_x, right_y))):
        draw.line((x, y, x, y + 120), fill=GOLD, width=3)
        draw.arc((x - 100, y + 70, x + 100, y + 160), 0, 180, fill=GOLD, width=5)
        _card(
            draw,
            (x - 90, y + 95, x + 90, y + 145),
            values[number],
            fill=(55, 31, 59) if number == 0 else INK,
            outline=GOLD,
        )


def _generic(image, scene, progress):
    draw = ImageDraw.Draw(image)
    _header(draw, scene)
    values = phrases(scene)
    width = min(250, (W - 120) // max(len(values), 1) - 20)
    colors = (INK, (215, 230, 218), (236, 205, 195), (218, 211, 235))
    for number, text in enumerate(values):
        phase = _ease((progress - number * 0.12) / 0.4)
        x = 70 + number * ((W - 140) / max(len(values), 1))
        y = 250 + (1 - phase) * 90
        _card(
            draw,
            (x, y, x + width, y + 90),
            text,
            fill=colors[number % 4],
            outline=(80, 95, 100),
        )
    draw.line((80, 470, W - 80, 470), fill=CYAN, width=3)
    dot = 80 + (W - 160) * ((progress * 0.75) % 1.0)
    draw.ellipse((dot - 10, 460, dot + 10, 480), fill=CORAL)


def frame(scene: dict, progress: float) -> Image.Image:
    image = _background(progress)
    blob = " ".join(
        str(value or "").lower()
        for value in (
            scene.get("query"),
            scene.get("semantic_anchor"),
            " ".join(map(str, scene.get("keywords") or [])),
        )
    )
    if "filter" in blob or "setting" in blob or "toggle" in blob:
        _filter(image, scene, progress)
    elif "scale" in blob or ("deception" in blob and "inherit" in blob):
        _scale(image, scene, progress)
    elif any(
        word in blob
        for word in (
            "receipt", "evidence", "exhibit", "belief lens", "love note", "selfish",
        )
    ):
        _evidence(image, scene, progress)
    elif any(
        word in blob
        for word in (
            "autofocus", "preset", "recognize", "viewfinder", "symbol recognition",
        )
    ):
        _perception(image, scene, progress)
    elif any(word in blob for word in ("exhaustion", "ambition", "fear", "realistic")):
        _clock(image, scene, progress)
    elif any(word in blob for word in ("money", "popularity", "value", "worth", "counter")):
        _counters(image, scene, progress)
    elif any(word in blob for word in ("maze", "route", "path", "walk past", "guide")):
        _path(image, scene, progress)
    elif any(
        word in blob
        for word in (
            "label", "name tag", "stamp", "success", "failure", "normal", "impossible",
        )
    ):
        _labels(image, scene, progress)
    else:
        _generic(image, scene, progress)
    return image


def render_scene(build_dir: str, script: dict, index: int) -> dict:
    scene = script["scenes"][int(index)]
    duration = max(float(scene.get("duration") or 5.0), 0.5)
    output = Path(build_dir) / f"clip_{int(index):02d}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    if (
        scene.get("storyboard_generated")
        and output.exists()
        and output.stat().st_size > 100_000
    ):
        evidence = scene.get("motion_evidence") or motion.temporal_evidence(str(output))
        if evidence.get("passes"):
            return {
                "scene_index": int(index),
                "text": scene.get("text"),
                "keywords": phrases(scene),
                "semantic_anchor": scene.get("semantic_anchor"),
                "query": scene.get("query"),
                "output": output.name,
                "motion_evidence": evidence,
                "cached": True,
            }
    frame_count = max(1, int(math.ceil(duration * FPS)))
    command = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-an", "-vf", "noise=alls=4:allf=t+u",
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", "1200k", "-minrate", "1200k", "-maxrate", "1200k",
        "-bufsize", "1200k", "-x264-params", "nal-hrd=cbr:force-cfr=1",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for number in range(frame_count):
            progress = number / max(frame_count - 1, 1)
            process.stdin.write(frame(scene, progress).tobytes())
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr is not None else b""
        code = process.wait()
    except BaseException:
        process.kill()
        raise
    if code:
        raise RuntimeError(
            stderr.decode("utf-8", "replace")[-1200:]
            or "ffmpeg storyboard encode failed"
        )
    evidence = motion.temporal_evidence(str(output))
    if not evidence.get("passes"):
        raise RuntimeError(f"generated storyboard lacks sufficient motion: {evidence}")
    for key in (
        "stock_id", "pexels_id", "stock_frame_url", "stock_frame_url_checked",
        "source_url", "source_title", "source_license", "hero", "hero_generated",
        "hero_fallback", "hero_fallback_reason", "still_reference_scene",
        "still_reference_stock_id", "still_reference_source", "still_reference_url",
        "still_reference_frame",
    ):
        scene.pop(key, None)
    scene.update(
        {
            "clip": str(output),
            "narrative_mode": "literal_graphic",
            "motion_kind": motion.VIDEO,
            "motion_mode": "generated_graphic",
            "motion_source": "literal_storyboard",
            "motion_verified": True,
            "motion_evidence": evidence,
            "storyboard_generated": True,
            "storyboard_version": 1,
            "clip_fingerprint": motion.scene_visual_fingerprint(scene),
        }
    )
    plan = {
        "scene_index": int(index),
        "text": scene.get("text"),
        "keywords": phrases(scene),
        "semantic_anchor": scene.get("semantic_anchor"),
        "query": scene.get("query"),
        "output": output.name,
        "motion_evidence": evidence,
    }
    (Path(build_dir) / f"storyboard_{int(index):02d}.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return plan
