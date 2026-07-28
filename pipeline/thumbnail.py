"""Generate a 1280x720 YouTube thumbnail for a build slug.

Base image from Pollinations (free, keyless) using the package's hero prompt,
then a bold title overlay. Honors the title rule: the yellow series eyebrow
appears ONLY for series videos (series_label set and title_mode != standalone);
standalone videos show just the core title.
"""
from __future__ import annotations
import json, os, urllib.parse, urllib.request
from pathlib import Path

W, H = 1280, 720
POPPINS_URL = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf"
FONT_CACHE = "/tmp/Poppins-Bold.ttf"
DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font_path() -> str:
    if os.path.exists(FONT_CACHE) and os.path.getsize(FONT_CACHE) > 10000:
        return FONT_CACHE
    try:
        req = urllib.request.Request(POPPINS_URL, headers={"User-Agent": "pipeline"})
        data = urllib.request.urlopen(req, timeout=30).read()
        if len(data) > 10000:
            Path(FONT_CACHE).write_bytes(data)
            return FONT_CACHE
    except Exception:
        pass
    return DEJAVU


def _base_prompt(build_dir: Path, script: dict) -> str:
    hp = build_dir / "hero-prompt.json"
    if hp.exists():
        try:
            p = json.loads(hp.read_text()).get("prompt")
            if p:
                return str(p).split("Title overlay")[0].strip().rstrip(".")
        except Exception:
            pass
    for sc in script.get("scenes", []):
        if sc.get("hero") and sc.get("image_prompt"):
            return str(sc["image_prompt"])
    for sc in script.get("scenes", []):
        if sc.get("image_prompt"):
            return str(sc["image_prompt"])
    return f"cinematic photoreal atmospheric still evoking: {script.get('title','')}"


def _fetch_base(prompt: str, seed: int = 7):
    from PIL import Image
    import io
    full = prompt + ", cinematic photoreal, dramatic practical light, moody, 35mm, no text, no words, no letters, no watermark"
    enc = urllib.parse.quote(full)
    url = f"https://image.pollinations.ai/prompt/{enc}?width={W}&height={H}&nologo=true&enhance=true&seed={seed}&model=flux"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pipeline"})
        data = urllib.request.urlopen(req, timeout=90).read()
        im = Image.open(io.BytesIO(data)).convert("RGB")
        if im.size != (W, H):
            s = max(W / im.width, H / im.height)
            im = im.resize((int(im.width * s), int(im.height * s)))
            x = (im.width - W) // 2; y = (im.height - H) // 2
            im = im.crop((x, y, x + W, y + H))
        return im
    except Exception:
        from PIL import Image as I
        return I.new("RGB", (W, H), (12, 14, 20))


def _wrap(title: str, font_path: str, max_w: int, max_lines: int = 3):
    from PIL import ImageFont, ImageDraw, Image
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = title.upper().split()
    for size in range(160, 54, -6):
        f = ImageFont.truetype(font_path, size)
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= max_w:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(d.textlength(l, font=f) <= max_w for l in lines):
            return f, size, lines
    f = ImageFont.truetype(font_path, 66)
    return f, 66, words[:max_lines]


def generate(slug: str, build_dir, out=None, portrait: bool = False) -> str:
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance
    global W, H
    if portrait:
        W, H = 1080, 1920
    else:
        W, H = 1280, 720
    build_dir = Path(build_dir)
    script = json.loads((build_dir / "script.json").read_text())
    title = script.get("title") or slug.replace("-", " ").title()
    series = script.get("series_label")
    standalone = (script.get("title_mode") == "standalone") or (series in (None, "", "null"))
    eyebrow = None if standalone else str(series).upper()

    img = _fetch_base(_base_prompt(build_dir, script))
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(1.12)
    scrim = Image.new("L", (W, H), 0); sd = ImageDraw.Draw(scrim)
    for yy in range(H):
        sd.line([(0, yy), (W, yy)], fill=min(int(210 * max(0, (yy - H * 0.34) / (H * 0.66))), 210))
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, scrim)

    d = ImageDraw.Draw(img)
    fp = _font_path()
    margin = 70
    f, size, lines = _wrap(title, fp, W - 2 * margin, 4 if portrait else 3)
    lh = int(size * 1.02)
    cy = H - margin - lh * len(lines) + 6
    for i, t in enumerate(lines):
        last = (i == len(lines) - 1)
        fill = (255, 214, 10) if (last and standalone) else (255, 255, 255)
        d.text((margin + 6, cy + 8), t, font=f, fill=(0, 0, 0))
        d.text((margin, cy), t, font=f, fill=fill, stroke_width=8, stroke_fill=(0, 0, 0))
        cy += lh
    if eyebrow:
        ef = ImageFont.truetype(fp, 36)
        d.text((margin, 52), eyebrow, font=ef, fill=(255, 214, 10), stroke_width=3, stroke_fill=(0, 0, 0))

    out = Path(out) if out else (build_dir / "thumbnail.jpg")
    img.save(out, quality=92)
    return str(out)


if __name__ == "__main__":
    import sys
    print(generate(sys.argv[1], Path("build") / sys.argv[1]))
