"""Persistent output policy for finished video renders."""

VALID_OUTPUTS = ("youtube", "portrait", "short")
DEFAULT_OUTPUTS = ("youtube",)
DEFAULT_MUSIC_CHOICE = 3


def render_outputs(script):
    """Return requested finished canvases; regular YouTube is the global default."""
    if script.get("curate_scenes"):
        return ("portrait",)
    raw = script.get("render_outputs")
    if raw is None:
        return DEFAULT_OUTPUTS
    if isinstance(raw, str):
        aliases = {
            "youtube_only": ("youtube",),
            "all": VALID_OUTPUTS,
        }
        raw = aliases.get(raw.strip().lower(), (raw,))
    if not isinstance(raw, (list, tuple)):
        raise ValueError("render_outputs must be a string or list")
    out = []
    for item in raw:
        name = str(item).strip().lower()
        if name not in VALID_OUTPUTS:
            raise ValueError(
                f"unsupported render output {name!r}; choose from {', '.join(VALID_OUTPUTS)}"
            )
        if name not in out:
            out.append(name)
    if not out:
        raise ValueError("render_outputs cannot be empty")
    return tuple(out)


def music_choices(script):
    """Return the primary score family followed by any explicit alternatives."""
    primary = int(script.get("music_choice", DEFAULT_MUSIC_CHOICE))
    raw = script.get("music_choices")
    if raw is None:
        raw = [primary]
    elif not isinstance(raw, (list, tuple)):
        raw = [raw]
    choices = [primary]
    for item in raw:
        choice = int(item)
        if choice < 1:
            raise ValueError("music choices must be positive integers")
        if choice not in choices:
            choices.append(choice)
    return tuple(choices)


def needs_portrait_segments(script):
    outputs = render_outputs(script)
    return "portrait" in outputs or "short" in outputs


def video_name(canvas, position, item):
    """Return one canonical file plus opt-in alternatives without duplicate copies."""
    if canvas == "youtube":
        if position == 0:
            return "final_youtube.mp4"
        prefix = "final_youtube_music"
    elif canvas == "portrait":
        if position == 0:
            return "final.mp4"
        prefix = "final_music"
    else:
        raise ValueError(f"unsupported canvas: {canvas}")
    choice = int(item.get("variant") or item.get("index") or position + 1)
    return f"{prefix}_{choice:02d}.mp4"


def required_video_names(script):
    outputs = render_outputs(script)
    names = []
    if "youtube" in outputs:
        names.append("final_youtube.mp4")
    if "portrait" in outputs:
        names.append("final.mp4")
    if "short" in outputs:
        names.append("final_short.mp4")
    return tuple(names)
