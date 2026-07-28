"""Shared helpers for rendering multiple selectable score versions."""
import json
import os
import shutil
import subprocess
import tempfile

import render_policy


MIN_MUSIC_VARIANTS = 1
DEFAULT_DELIVERY_LABEL = "Deep Current"
DEFAULT_DELIVERY_INDEX = 3
_RUNNER = None


def set_runner(runner):
    """Inject the Governor-compatible subprocess runner for in-process mixes."""
    global _RUNNER
    _RUNNER = runner


def entries(script):
    """Return normalized music-variant dictionaries in declared order."""
    raw = script.get("music_variants") or []
    out = []
    for index, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {"file": item}
        if not isinstance(item, dict) or not item.get("file"):
            continue
        row = dict(item)
        row.setdefault("index", index)
        row.setdefault("label", f"Music Choice {index}")
        out.append(row)
    if not out and script.get("music"):
        out = [{"index": 1, "label": "Music Choice 1", "file": script["music"]}]
    return out


def require(script, build_dir, minimum=MIN_MUSIC_VARIANTS):
    found = entries(script)
    if len(found) < minimum:
        raise ValueError(f"expected at least {minimum} music variants; found {len(found)}")
    missing = [x["file"] for x in found if not os.path.exists(os.path.join(build_dir, x["file"]))]
    if missing:
        raise ValueError("missing music variants: " + ", ".join(missing))
    return found


def video_name(index, short=False):
    prefix = "final_short_music" if short else "final_music"
    return f"{prefix}_{index:02d}.mp4"


def youtube_video_name(index):
    """Return the native 16:9 YouTube filename for a music choice."""
    return f"final_youtube_music_{index:02d}.mp4"


def delivery_choice(variants, preferred_label=DEFAULT_DELIVERY_LABEL):
    """Return the primary score, honoring legacy manifests when necessary."""
    if not variants:
        raise ValueError("cannot choose a delivery variant from an empty list")
    for index, item in enumerate(variants, 1):
        if item.get("selected"):
            return index, item
    wanted = preferred_label.strip().casefold()
    for index, item in enumerate(variants, 1):
        if str(item.get("label", "")).strip().casefold() == wanted:
            return index, item
    for index, item in enumerate(variants, 1):
        if int(item.get("variant") or 0) == DEFAULT_DELIVERY_INDEX:
            return index, item
    return 1, variants[0]


def _run(cmd):
    runner = _RUNNER or subprocess.run
    r = runner(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:] or "ffmpeg failed")
    return r


def _voice_mix_settings(voiceover):
    """Read optional per-video voice treatment from the adjacent script.json."""
    try:
        script_path = os.path.join(os.path.dirname(os.path.abspath(voiceover)), "script.json")
        with open(script_path, encoding="utf-8") as handle:
            script = json.load(handle)
        settings = script.get("voice_mix") or {}
        return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def mix(noaudio, voiceover, music_path, total, output, delay_ms=400, music_gain=.26):
    """Mix one score choice while honoring optional per-video voice preservation.

    The standard path keeps the established compressed, -14 LUFS social master.
    A script may opt into ``voice_mix.mode = preserve`` to retain the supplied
    narrator's original dynamics and tone: no compressor, no loudness remaster,
    a very low music bed, and only a transparent safety limiter.
    """
    settings = _voice_mix_settings(voiceover)
    preserve = str(settings.get("mode", "")).strip().casefold() == "preserve"
    tmp = tempfile.mkdtemp(prefix="music-variant-")
    try:
        if preserve:
            voice_gain_db = float(settings.get("voice_gain_db", 1.5))
            preserve_music_gain = float(settings.get("music_gain", 0.06))
            bitrate = str(settings.get("audio_bitrate", "256k"))
            final_tmp = os.path.join(tmp, "final.mp4")
            af = (
                f"[1:a]volume={voice_gain_db}dB,adelay={delay_ms}|{delay_ms},apad[voz];"
                f"[2:a]volume={preserve_music_gain},"
                f"afade=t=out:st={max(total-3, 0)}:d=3[mz];"
                "[voz][mz]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                "alimiter=limit=0.95:attack=5:release=80:level=false[a]"
            )
            _run([
                "ffmpeg", "-v", "error", "-y", "-i", noaudio, "-i", voiceover,
                "-i", music_path, "-filter_complex", af, "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", bitrate, "-t", str(total),
                "-movflags", "+faststart", final_tmp,
            ])
            shutil.copy(final_tmp, output)
            return

        raw = os.path.join(tmp, "raw.mp4")
        af = ("[1:a]acompressor=threshold=-18dB:ratio=3:attack=15:release=180:makeup=4,"
              f"adelay={delay_ms}|{delay_ms},apad[voz];"
              f"[2:a]volume={music_gain},afade=t=out:st={max(total-3, 0)}:d=3[mz];"
              "[voz][mz]amix=inputs=2:duration=first:dropout_transition=0[a]")
        _run(["ffmpeg", "-v", "error", "-y", "-i", noaudio, "-i", voiceover,
              "-i", music_path, "-filter_complex", af, "-map", "0:v", "-map", "[a]",
              "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", str(total), raw])
        runner = _RUNNER or subprocess.run
        measured = runner(
            ["ffmpeg", "-i", raw, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"], capture_output=True, text=True)
        try:
            values = json.loads("{" + measured.stderr.rsplit("{", 1)[1])
            gain = round(-14.0 - float(values["input_i"]) + 1.5, 2)
            master = f"volume={gain}dB,alimiter=limit=0.79:attack=2:release=80:level=false"
        except Exception:
            master = "loudnorm=I=-14:TP=-1.5:LRA=11"
        final_tmp = os.path.join(tmp, "final.mp4")
        _run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-af", master,
              "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-c:a", "aac",
              "-b:a", "256k", "-movflags", "+faststart", final_tmp])
        shutil.copy(final_tmp, output)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_manifest(build_dir, variants, outputs=None):
    if outputs is None:
        try:
            with open(os.path.join(build_dir, "script.json"), encoding="utf-8") as handle:
                outputs = render_policy.render_outputs(json.load(handle))
        except (OSError, ValueError, TypeError):
            outputs = render_policy.DEFAULT_OUTPUTS
    outputs = tuple(outputs)
    delivery_position, delivery_item = delivery_choice(variants)
    rows = []
    for position, item in enumerate(variants):
        row = dict(item)
        if "portrait" in outputs:
            row["video"] = render_policy.video_name("portrait", position, item)
        if "youtube" in outputs:
            row["youtube_video"] = render_policy.video_name("youtube", position, item)
        rows.append(row)
    delivery_row = rows[delivery_position - 1]
    delivery = {
        "index": int(delivery_item.get("variant") or delivery_position),
        "label": delivery_item.get("label", DEFAULT_DELIVERY_LABEL),
        "other_choices": "available_on_request" if len(rows) == 1 else "included",
    }
    if delivery_row.get("video"):
        delivery["portrait_video"] = delivery_row["video"]
    if delivery_row.get("youtube_video"):
        delivery["youtube_video"] = delivery_row["youtube_video"]
    data = {
        "minimum_choices": MIN_MUSIC_VARIANTS,
        "render_outputs": list(outputs),
        "default_index": delivery["index"],
        "delivery": delivery,
        "variants": rows,
    }
    with open(os.path.join(build_dir, "music_variants.json"), "w") as f:
        json.dump(data, f, indent=2)
    return data
