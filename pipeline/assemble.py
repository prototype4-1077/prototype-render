"""Assemble portrait social and native 16:9 YouTube videos from shared scenes.

Usage:
  python3 assemble.py <build_dir> scene <i>
  python3 assemble.py <build_dir> youtube-scene <i>
  python3 assemble.py <build_dir> render-all
  python3 assemble.py <build_dir> youtube-render-all
  python3 assemble.py <build_dir> concat
  python3 assemble.py <build_dir> youtube-concat
"""
import json, os, shutil, subprocess, sys

import audio_variants
import motion
import profiles
from video_format import (
    BAND_HEIGHT, BAND_WIDTH, BAND_Y, FPS, HEIGHT, WIDTH,
    YOUTUBE_HEIGHT, YOUTUBE_WIDTH,
    ENCODE_QUALITY, COLOR_TAGS,
)


def clip_duration(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", f], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FFMPEG FAIL: {' '.join(cmd)}\n{r.stderr[-2000:]}")


def render_scene(bd, i, output_format="portrait"):
    """Render one independently resumable scene for the requested canvas."""
    youtube = output_format == "youtube"
    if output_format not in ("portrait", "youtube"):
        raise ValueError(f"unknown output format: {output_format}")
    with open(f"{bd}/script.json") as f:
        s = json.load(f)
    sc = s["scenes"][i]
    prefix = "youtube_seg" if youtube else "seg"
    seg = f"{bd}/{prefix}_{i:02d}.mp4"
    dur = sc["duration"]
    existing_duration = clip_duration(seg) if os.path.exists(seg) else None
    if existing_duration and existing_duration >= max(dur - .2, .1):
        return print(f"{prefix} {i} exists, skip")
    if os.path.exists(seg):
        print(f"{prefix} {i} is corrupt/truncated; rebuilding")

    cap_prefix = "youtube_cap" if youtube else "cap"
    overlays = [(f"{bd}/{cap_prefix}_{i:02d}.png", None)]
    overlay_key = "youtube_kw_overlays" if youtube else "kw_overlays"
    for ov in sc.get(overlay_key, []):
        t = sc.get("kw_times", {}).get(ov["kw"])
        rel = max(0.0, round(t - sc["start"], 3)) if t is not None else 0.0
        overlays.append((f"{bd}/{ov['png']}", rel))
    title_name = "youtube_title.png" if youtube else "title.png"
    title_path = f"{bd}/{title_name}"
    title = title_path if i == 0 and os.path.exists(title_path) else None

    # Landscape is recomposed from source footage at native 16:9. Portrait keeps
    # the established centered picture band (or its opt-in full-bleed crop).
    if youtube:
        canvas_w, canvas_h = YOUTUBE_WIDTH, YOUTUBE_HEIGHT
        BW, BH, padf = canvas_w, canvas_h, ""
    elif s.get("layout") == "fullbleed":
        canvas_w, canvas_h = WIDTH, HEIGHT
        BW, BH, padf = canvas_w, canvas_h, ""
    else:
        canvas_w, canvas_h = WIDTH, HEIGHT
        BW, BH, BY = BAND_WIDTH, BAND_HEIGHT, BAND_Y
        padf = f",pad={canvas_w}:{canvas_h}:0:{BY}:black"
    geom = f"scale={BW}:{BH}:force_original_aspect_ratio=increase,crop={BW}:{BH}"

    mode = s.get("visual_mode")
    profile = profiles.resolve(s)
    tone = sc.get("tone", "cold")
    if profile == profiles.JUNE_OXLEY:
        grade = ("eq=brightness=0.036:saturation=0.96:contrast=1.025:gamma=1.055,"
                 "colorbalance=rs=0.018:bs=-0.028:rh=0.075:bh=-0.055,"
                 "curves=all='0/0.045 0.5/0.525 1/0.985',"
                 "vignette=angle=PI/8.5")
        grain = 3
    elif mode == "eerie_museum":
        grades = {
            "cold": ("eq=brightness=0.018:saturation=0.76:contrast=1.10:gamma=1.04,"
                     "colorbalance=rs=-0.07:bs=0.11:rh=0.035:bh=-0.035,"),
            "neutral": ("eq=brightness=0.026:saturation=0.80:contrast=1.08:gamma=1.04,"
                        "colorbalance=rs=-0.045:bs=0.075:rh=0.05:bh=-0.045,"),
            "warm": ("eq=brightness=0.038:saturation=0.86:contrast=1.07:gamma=1.05,"
                     "colorbalance=rs=-0.02:bs=0.045:rh=0.09:bh=-0.07,"),
            "gold": ("eq=brightness=0.055:saturation=0.94:contrast=1.06:gamma=1.06,"
                     "colorbalance=rs=0.00:bs=0.02:rh=0.14:bh=-0.10,"),
        }
        grade = (grades.get(tone, grades["cold"]) +
                 "curves=all='0/0.045 0.48/0.515 1/0.985',vignette=angle=PI/7.5")
        grain = 3
    else:
        grade = ("eq=saturation=0.88:contrast=1.05,"
                 "colorbalance=rs=-0.04:bs=0.06:rh=0.05:bh=-0.05,"
                 "curves=all='0/0.035 0.5/0.51 1/0.975',"
                 "vignette=angle=PI/6.5")
        grain = 5

    frames = max(int(dur * FPS), 1)
    mv = {"push": 0, "pull": 1, "drift": 2}.get(sc.get("motion"), i % 3)
    if mv == 0:
        zexpr = "z='min(1.0+0.0009*on,1.13)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    elif mv == 1:
        zexpr = "z='max(1.13-0.0009*on,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    else:
        zexpr = (f"z=1.08:x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'")
    if motion.motion_kind(sc) == motion.ANIMATED:
        zoom = (f"fps={FPS},{grade}{padf},"
                f"noise=alls={grain}:allf=t+u")
    else:
        zoom = (f"fps={FPS},zoompan={zexpr}:d=1:s={BW}x{BH}:fps={FPS},{grade}{padf},"
                f"noise=alls={grain}:allf=t+u")

    cd = clip_duration(sc["clip"]) or dur
    f = dur / max(cd, 0.1)
    offset = 0.0
    if sc.get("trim_start") is not None:
        offset = max(float(sc["trim_start"]), 0.0)
    elif mode == "eerie_museum" and cd > dur + 1.5:
        offset = min(max((cd - dur) * 0.35, 0.0), 3.0)
    inputs = (["-ss", f"{offset:.3f}"] if offset else []) + ["-i", sc["clip"]]
    if f <= 1.02:
        fc = f"[0:v]{geom},{zoom}[v0]"
    elif f <= 2.2:
        fc = f"[0:v]{geom},setpts={f:.4f}*PTS,{zoom}[v0]"
    elif cd <= 12 and f <= 4.4:
        f2 = max(dur / (2 * cd), 1.0)
        fc = (f"[0:v]{geom}[fw];[fw]split[fa][fb];[fb]reverse[rv];"
              f"[fa][rv]concat=n=2:v=1:a=0,setpts={f2:.4f}*PTS,{zoom}[v0]")
    else:
        inputs = ["-stream_loop", "-1", "-i", sc["clip"]]
        fc = f"[0:v]{geom},{zoom}[v0]"
    last = "v0"
    for j, (ov, en) in enumerate(overlays):
        inputs += ["-i", ov]
        opt = f":enable='gte(t,{en})'" if en else ""
        fc += f";[{last}][{j+1}:v]overlay=0:0{opt}[v{j+1}]"
        last = f"v{j+1}"
    if title:
        j = len(overlays) + 1
        inputs += ["-loop", "1", "-t", str(dur), "-i", title]
        title_fade = ("format=rgba," if i == 0 else
                      "format=rgba,fade=t=in:st=0.3:d=0.8:alpha=1,")
        # Scene 0 (James): the title must not hide the opening visual for the
        # whole beat - show it ~3s, then fade to reveal the scene art.
        title_out = (min(3.2, max(dur - 0.7, 1.2)) if i == 0
                     else max(dur - 0.7, 1.2))
        fc += (f";[{j}:v]{title_fade}"
               f"fade=t=out:st={title_out:.2f}:d=0.6:alpha=1[tf]"
               f";[{last}][tf]overlay=0:0[vt]")
        last = "vt"
    if mode == "eerie_museum":
        fc += f";[{last}]null[vf]"
        last = "vf"
    else:
        edge_fade = ("" if i == 0 else "fade=t=in:st=0:d=0.14,")
        fc += (f";[{last}]{edge_fade}"
               f"fade=t=out:st={max(dur-0.14, 0):.2f}:d=0.14[vf]")
        last = "vf"
    run(["ffmpeg", "-v", "error", "-y"] + inputs +
        ["-filter_complex", fc, "-map", f"[{last}]", "-t", str(dur),
         "-an", "-c:v", "libx264", *ENCODE_QUALITY, *COLOR_TAGS,
         "-pix_fmt", "yuv420p", seg])
    print(f"{prefix} {i} done ({canvas_w}x{canvas_h})")


def concat(bd, output_format="portrait"):
    """Concatenate and mix every music choice for one canvas."""
    youtube = output_format == "youtube"
    if output_format not in ("portrait", "youtube"):
        raise ValueError(f"unknown output format: {output_format}")
    s = json.load(open(f"{bd}/script.json"))
    n = len(s["scenes"])
    prefix = "youtube_seg" if youtube else "seg"
    for i, scene in enumerate(s["scenes"]):
        duration = clip_duration(f"{bd}/{prefix}_{i:02d}.mp4")
        if duration is None or duration < max(float(scene["duration"]) - .2, .1):
            raise SystemExit(f"{prefix} {i} is corrupt or truncated; rerender it")
    list_name = "youtube_list.txt" if youtube else "list.txt"
    with open(f"{bd}/{list_name}", "w") as f:
        for i in range(n):
            f.write(f"file '{prefix}_{i:02d}.mp4'\n")
    noaudio_name = "youtube_video_noaudio.mp4" if youtube else "video_noaudio.mp4"
    noaudio = f"{bd}/{noaudio_name}"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", f"{bd}/{list_name}", "-c", "copy", noaudio])
    vo = s.get("voiceover")
    total = sum(sc["duration"] for sc in s["scenes"])
    concatenated = clip_duration(noaudio)
    if concatenated is None or concatenated < total - .5:
        raise SystemExit(f"concat truncated at {concatenated or 0:.1f}s; expected {total:.1f}s")
    variants = audio_variants.entries(s)
    final_name = "final_youtube.mp4" if youtube else "final.mp4"
    if vo and variants:
        variants = audio_variants.require(s, bd)
        for i, item in enumerate(variants, 1):
            name = (audio_variants.youtube_video_name(i) if youtube
                    else audio_variants.video_name(i))
            output = f"{bd}/{name}"
            audio_variants.mix(noaudio, f"{bd}/{vo}", f"{bd}/{item['file']}", total, output)
            print(f"{os.path.basename(output)} done: {item['label']}")
        first = (audio_variants.youtube_video_name(1) if youtube
                 else audio_variants.video_name(1))
        shutil.copy(f"{bd}/{first}", f"{bd}/{final_name}")
        audio_variants.write_manifest(bd, variants)
    elif vo:
        run(["ffmpeg", "-v", "error", "-y", "-i", noaudio,
             "-i", f"{bd}/{vo}", "-map", "0:v", "-map", "1:a",
             "-af", "adelay=400|400,apad", "-c:v", "copy", "-c:a", "aac",
             "-t", str(total), f"{bd}/{final_name}"])
    else:
        os.replace(noaudio, f"{bd}/{final_name}")
    print(f"{final_name} done")


if __name__ == "__main__":
    bd, cmd = sys.argv[1], sys.argv[2]
    if cmd == "scene":
        render_scene(bd, int(sys.argv[3]))
    elif cmd == "youtube-scene":
        render_scene(bd, int(sys.argv[3]), "youtube")
    elif cmd in ("render-all", "youtube-render-all"):
        script = json.load(open(f"{bd}/script.json"))
        output_format = "youtube" if cmd.startswith("youtube") else "portrait"
        for index in range(len(script.get("scenes", []))):
            render_scene(bd, index, output_format)
    elif cmd == "concat":
        concat(bd)
    elif cmd == "youtube-concat":
        concat(bd, "youtube")
