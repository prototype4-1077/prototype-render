"""Render caption and title overlays for portrait social and landscape YouTube.

Portrait keeps the established 16:9 picture band and lower caption zone. The
YouTube overlays use a native 1920x1080 safe area with captions in the lower third.
Landscape scene-0 titles also stay inside TikTok's centered 3:4 cover crop.
"""
import os, re
from PIL import Image, ImageDraw, ImageFont

from video_format import (
    BAND_HEIGHT, BAND_Y, HEIGHT, WIDTH, YOUTUBE_HEIGHT, YOUTUBE_WIDTH,
)

W, H = WIDTH, HEIGHT               # 9:16 phone canvas
BAND_H = BAND_HEIGHT               # 16:9 footage band, shared with assemble.py
YT_W, YT_H = YOUTUBE_WIDTH, YOUTUBE_HEIGHT
_F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
CAPTION_FONT = os.environ.get("CAPTION_FONT", os.path.join(_F, "Questrial-Regular.ttf"))
TITLE_FONT = os.environ.get("TITLE_FONT", os.path.join(_F, "Baloo2-ExtraBold.ttf"))
FONT_SIZE = 44
LINE_PAD_X, LINE_PAD_Y, LINE_GAP = 16, 8, 6
BOX_RGBA = (24, 24, 24, 150)       # subtle: near-invisible on the black band
WHITE = (255, 255, 255, 255)
YELLOW = (230, 232, 126, 255)
BLOCK_CENTER_Y = 1430              # below the footage band, above TikTok UI zone
MAX_LINE_W = 820
TITLE_MAX_LINE_W = 940
TITLE_MAX_BLOCK_H = 820            # stays above captions and TikTok UI
TITLE_MIN_FONT_SIZE = 12
TITLE_FONT_STEP = 6
TITLE_EYEBROW_RATIO = 0.34
TITLE_EYEBROW_GAP = 20
TITLE_SOFT_MAX_CHARS = 12  # James: no more than 12 characters on one title line
TITLE_CONNECTOR_WORDS = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "i", "in", "is", "it",
    "my", "of", "on", "or", "the", "to", "we",
})

# Landscape text is larger in pixels but occupies a similar share of the frame.
YT_FONT_SIZE = 50
YT_BLOCK_CENTER_Y = 900
YT_MAX_LINE_W = 1460
YT_TIKTOK_COVER_ASPECT = (3, 4)
YT_TIKTOK_COVER_CROP_W = round(
    YT_H * YT_TIKTOK_COVER_ASPECT[0] / YT_TIKTOK_COVER_ASPECT[1]
)
YT_TIKTOK_COVER_CROP_LEFT = (YT_W - YT_TIKTOK_COVER_CROP_W) // 2
YT_TIKTOK_COVER_CROP_RIGHT = YT_TIKTOK_COVER_CROP_LEFT + YT_TIKTOK_COVER_CROP_W
YT_TITLE_MAX_LINE_W = 700
YT_TITLE_MAX_BLOCK_H = 610
YT_TITLE_CENTER_Y = 445
LEADING_PERFORMANCE_TAGS = re.compile(r"^\s*(?:\[[^\[\]\r\n]{1,80}\]\s*)+")


def _font(path, size):
    f = ImageFont.truetype(path, size)
    try: f.set_variation_by_axes([800])  # no-op for static fonts
    except Exception: pass
    return f


def visible_caption_text(text):
    """Hide leading voice directions while preserving the narrated script."""
    return LEADING_PERFORMANCE_TAGS.sub("", str(text or "")).strip()


def _split_overlong_word(word, font, draw, max_line_w):
    """Split a single unbroken token so it can never escape the safe width."""
    text, marker = word
    if draw.textlength(text, font=font) <= max_line_w:
        return [word]
    parts, cur = [], ""
    for char in text:
        if cur and draw.textlength(cur + char, font=font) > max_line_w:
            parts.append((cur, marker))
            cur = char
        else:
            cur += char
    if cur:
        parts.append((cur, marker))
    return parts


def _wrap(words, font, draw, max_line_w=MAX_LINE_W, split_overlong=True):
    expanded = []
    for word in words:
        expanded.extend(_split_overlong_word(word, font, draw, max_line_w)
                        if split_overlong else [word])
    lines, cur = [], []
    for w in expanded:
        test = " ".join(x[0] for x in cur + [w])
        if cur and draw.textlength(test, font=font) > max_line_w:
            lines.append(cur); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(cur)
    return lines


def _is_title_connector(word):
    token = re.sub(r"[^\w']", "", word).lower()
    return token in TITLE_CONNECTOR_WORDS


def _title_character_count(words):
    """Count visible title characters, ignoring spaces and punctuation."""
    return sum(len(re.sub(r"[^\w']", "", word[0])) for word in words)


def _group_title_words(words, use_character_hint=True):
    """Group title tokens for readable cover-safe lines.

    A line normally contains at most two words; a short connector can make it
    three. Ten visible characters is a strong wrapping hint, while the final
    rendered pixel width remains the hard safety check.
    """
    lines, cur = [], []
    for word in words:
        candidate = cur + [word]
        limit = 3 if any(_is_title_connector(item[0]) for item in candidate) else 2
        over_word_limit = len(candidate) > limit
        over_character_hint = (
            use_character_hint
            and len(candidate) > 1
            and _title_character_count(candidate) > TITLE_SOFT_MAX_CHARS
        )
        if cur and (over_word_limit or over_character_hint):
            lines.append(cur)
            cur = [word]
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines


def _wrap_title(words, font, draw, max_line_w, split_overlong,
                use_character_hint=True):
    """Apply title readability rules, then honor the pixel safe area."""
    lines = []
    for grouped in _group_title_words(words, use_character_hint):
        lines.extend(_wrap(grouped, font, draw, max_line_w, split_overlong))
    return lines


def _caption_png(text, keywords, out_path, width, height, font_size,
                 block_center_y, max_line_w, kw_overlay_prefix=None):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(CAPTION_FONT, font_size)
    kwmap = {}
    for j, k in enumerate(keywords):
        for wd in re.findall(r"[\w']+", k.lower()):
            kwmap.setdefault(wd, j)
    words = [(w, kwmap.get(re.sub(r"[^\w']", "", w).lower()))
             for w in visible_caption_text(text).split()]
    lines = _wrap(words, font, d, max_line_w=max_line_w)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent + 2 * LINE_PAD_Y
    total_h = len(lines) * line_h + (len(lines) - 1) * LINE_GAP
    y = min(block_center_y - total_h // 2, height - total_h - 24)
    dynamic = kw_overlay_prefix is not None
    ovs = {}
    if dynamic:
        for j in set(kwmap.values()):
            ovs[j] = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for line in lines:
        line_text = " ".join(w for w, _ in line)
        lw = d.textlength(line_text, font=font)
        x0 = (width - lw) / 2
        d.rounded_rectangle([x0 - LINE_PAD_X, y, x0 + lw + LINE_PAD_X, y + line_h],
                            radius=6, fill=BOX_RGBA)
        x = x0
        for w, j in line:
            hot = j is not None
            base_fill = WHITE if (dynamic or not hot) else YELLOW
            d.text((x, y + LINE_PAD_Y), w, font=font, fill=base_fill)
            if dynamic and hot:
                ImageDraw.Draw(ovs[j]).text((x, y + LINE_PAD_Y), w, font=font, fill=YELLOW)
            x += d.textlength(w + " ", font=font)
        y += line_h + LINE_GAP
    img.save(out_path)
    result = []
    if dynamic:
        for j, ov in sorted(ovs.items()):
            p = f"{kw_overlay_prefix}{j}.png"
            ov.save(p)
            result.append((keywords[j], p))
    return result


def caption_png(text, keywords, out_path, kw_overlay_prefix=None):
    """Render the established 1080x1920 social caption overlay."""
    return _caption_png(text, keywords, out_path, W, H, FONT_SIZE,
                        BLOCK_CENTER_Y, MAX_LINE_W, kw_overlay_prefix)


def youtube_caption_png(text, keywords, out_path, kw_overlay_prefix=None):
    """Render a native 1920x1080 lower-third caption overlay."""
    return _caption_png(text, keywords, out_path, YT_W, YT_H, YT_FONT_SIZE,
                        YT_BLOCK_CENTER_Y, YT_MAX_LINE_W, kw_overlay_prefix)


def _fit_title(title, draw, font_size, max_line_w=TITLE_MAX_LINE_W,
               max_block_h=TITLE_MAX_BLOCK_H, cover_safe_layout=False):
    """Return a title layout that shrinks to fit its safe area.

    James's rule: group into readable lines of at most TITLE_SOFT_MAX_CHARS (12)
    visible characters FIRST, then shrink the font until that grouping fits the
    page. This keeps short titles like "THE LOOP" on one line and lets the font
    adjust to fit, rather than over-splitting a title just to hold a large font.
    """
    words = [(w, False) for w in title.split()]
    grouped = _group_title_words(words, use_character_hint=True)
    size = max(int(font_size), TITLE_MIN_FONT_SIZE)
    while size >= TITLE_MIN_FONT_SIZE:
        font = _font(TITLE_FONT, size)
        ascent, descent = font.getmetrics()
        line_h = int((ascent + descent) * 0.98)
        widest = max(
            draw.textlength(" ".join(w for w, _ in line), font=font)
            for line in grouped
        )
        total_h = line_h * len(grouped)
        if widest <= max_line_w and total_h <= max_block_h:
            return font, grouped, line_h
        size -= TITLE_FONT_STEP
    # Last resort at the minimum font: split any single word too wide to fit,
    # so an unbreakable title can never escape the safe crop.
    font = _font(TITLE_FONT, TITLE_MIN_FONT_SIZE)
    lines = []
    for line in grouped:
        lines.extend(_wrap(line, font, draw, max_line_w, split_overlong=True))
    ascent, descent = font.getmetrics()
    return font, lines, int((ascent + descent) * 0.98)


def _draw_shadowed_line(draw, text, x, y, font, fill=WHITE, shadow_scale=1.0):
    offsets = [
        (-4 * shadow_scale, 4 * shadow_scale),
        (4 * shadow_scale, 4 * shadow_scale),
        (0, 6 * shadow_scale),
        (0, -3 * shadow_scale),
    ]
    for dx, dy in offsets:
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 170))
    draw.text((x, y), text, font=font, fill=fill)


def _validate_title_bounds(img, safe_bounds, label):
    """Fail early when antialiased title pixels escape a required crop."""
    if safe_bounds is None:
        return
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError(f"{label} title rendered no visible pixels")
    left, top, right, bottom = bbox
    safe_left, safe_top, safe_right, safe_bottom = safe_bounds
    if left < safe_left or top < safe_top or right > safe_right or bottom > safe_bottom:
        raise ValueError(
            f"{label} title escaped safe bounds: bbox={bbox}, safe={safe_bounds}"
        )


def _title_png(title, out_path, width, height, center_y, max_line_w,
               max_block_h, font_size, eyebrow=None, safe_bounds=None,
               safe_label="canvas", cover_safe_layout=False):
    """Render a title, optionally with a smaller series label above it."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    title = " ".join(title.upper().split()) or "UNTITLED"
    eyebrow = " ".join((eyebrow or "").upper().split())

    eyebrow_font = None
    eyebrow_lines = []
    eyebrow_line_h = 0
    eyebrow_total_h = 0
    gap = 0
    if eyebrow:
        eyebrow_size = max(24, int(font_size * TITLE_EYEBROW_RATIO))
        eyebrow_font, eyebrow_lines, eyebrow_line_h = _fit_title(
            eyebrow, d, eyebrow_size, max_line_w, max_block_h // 3,
            cover_safe_layout=cover_safe_layout,
        )
        eyebrow_total_h = eyebrow_line_h * len(eyebrow_lines)
        gap = max(10, int(TITLE_EYEBROW_GAP * width / W))

    main_block_h = max(TITLE_MIN_FONT_SIZE, max_block_h - eyebrow_total_h - gap)
    font, lines, line_h = _fit_title(
        title, d, font_size, max_line_w, main_block_h,
        cover_safe_layout=cover_safe_layout,
    )
    main_total_h = line_h * len(lines)
    total_h = eyebrow_total_h + gap + main_total_h
    y = center_y - total_h // 2

    if eyebrow:
        for line in eyebrow_lines:
            words = " ".join(w for w, _ in line)
            lw = d.textlength(words, font=eyebrow_font)
            x = (width - lw) / 2
            _draw_shadowed_line(d, words, x, y, eyebrow_font,
                                fill=YELLOW, shadow_scale=0.55)
            y += eyebrow_line_h
        y += gap

    for line in lines:
        words = " ".join(w for w, _ in line)
        lw = d.textlength(words, font=font)
        x = (width - lw) / 2
        _draw_shadowed_line(d, words, x, y, font)
        y += line_h
    _validate_title_bounds(img, safe_bounds, safe_label)
    img.save(out_path)
    return out_path


def title_png(title, out_path, font_size=190, eyebrow=None):
    """Render the established title over the portrait picture band."""
    return _title_png(title, out_path, W, H, BAND_Y + BAND_H // 2,
                      TITLE_MAX_LINE_W, TITLE_MAX_BLOCK_H, font_size, eyebrow)


def youtube_title_png(title, out_path, font_size=170, eyebrow=None):
    """Render a 16:9 title that survives TikTok's centered 3:4 cover crop."""
    return _title_png(
        title, out_path, YT_W, YT_H, YT_TITLE_CENTER_Y,
        YT_TITLE_MAX_LINE_W, YT_TITLE_MAX_BLOCK_H, font_size, eyebrow,
        safe_bounds=(YT_TIKTOK_COVER_CROP_LEFT, 0,
                     YT_TIKTOK_COVER_CROP_RIGHT, YT_H),
        safe_label="TikTok 3:4 cover crop",
        cover_safe_layout=True,
    )
