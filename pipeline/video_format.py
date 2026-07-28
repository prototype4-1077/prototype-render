"""Canonical geometry for every social and YouTube video export.

Keep canvas dimensions here so rendering, captions, and release outputs cannot
silently drift to different aspect ratios.
"""

WIDTH = 1080
HEIGHT = 1920
FPS = 30

ASPECT_WIDTH = 9
ASPECT_HEIGHT = 16

# Default letterboxed picture area inside the portrait canvas.
BAND_WIDTH = WIDTH
BAND_HEIGHT = 608
BAND_Y = (HEIGHT - BAND_HEIGHT) // 2

# Regular YouTube uses a native 16:9 landscape canvas. This is recomposed from
# the source footage; the portrait render is never stretched or pillarboxed.
YOUTUBE_WIDTH = 1920
YOUTUBE_HEIGHT = 1080
YOUTUBE_ASPECT_WIDTH = 16
YOUTUBE_ASPECT_HEIGHT = 9


def is_portrait_9_16(width=WIDTH, height=HEIGHT):
    """Return True when dimensions are an exact 9:16 display ratio."""
    return width * ASPECT_HEIGHT == height * ASPECT_WIDTH


def is_landscape_16_9(width=YOUTUBE_WIDTH, height=YOUTUBE_HEIGHT):
    """Return True when dimensions are an exact 16:9 display ratio."""
    return width * YOUTUBE_ASPECT_HEIGHT == height * YOUTUBE_ASPECT_WIDTH


assert is_portrait_9_16(), "Canonical social canvas must remain 9:16 portrait"
assert is_landscape_16_9(), "Canonical YouTube canvas must remain 16:9 landscape"


# --- Deliverable encode policy (single source of truth) ---------------------
# 'slow' + CRF 18 maximizes quality-per-bit so more of the master survives
# platform re-encoding; BT.709 tags stop players/platforms from guessing the
# color space and shifting the grade. Drafts may use ENCODE_DRAFT.
ENCODE_QUALITY = ("-preset", "slow", "-crf", "18")
ENCODE_DRAFT = ("-preset", "veryfast", "-crf", "21")
COLOR_TAGS = ("-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709")
AUDIO_BITRATE = "256k"
