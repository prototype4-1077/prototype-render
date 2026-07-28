"""Generate portrait + YouTube overlays and (if missing) synth music beds.
Usage: python3 prep.py <build_dir>"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from captions import caption_png, title_png, youtube_caption_png, youtube_title_png
import audio_variants
import music as score
import profiles
import render_policy


def _is_generated_music(name):
    base = os.path.basename(name or "")
    return base == "music.wav" or (base.startswith("music_") and base.endswith(".wav"))


def prepare_music(bd, s):
    """Prepare only the selected score unless alternatives were explicitly requested."""
    total = sum(sc.get("duration", 8) for sc in s["scenes"])
    profile = profiles.resolve(s)
    custom, seen = [], set()

    declared = s.get("music_variants") or []
    for item in declared:
        if isinstance(item, str):
            item = {"file": item}
        elif isinstance(item, dict):
            item = dict(item)
        else:
            continue
        name = item.get("file")
        if (name and name not in seen and not _is_generated_music(name)
                and os.path.exists(os.path.join(bd, name))):
            custom.append({
                "file": name,
                "label": item.get("label", "Custom Score"),
                "source": "custom",
            })
            seen.add(name)
    current = s.get("music")
    if (current and current not in seen and not _is_generated_music(current)
            and os.path.exists(os.path.join(bd, current))):
        custom.insert(0, {"file": current, "label": "Custom Score", "source": "custom"})
        seen.add(current)

    generated = []
    if custom:
        variants = custom if s.get("music_choices") else custom[:1]
    else:
        variants = []
        for choice in render_policy.music_choices(s):
            name = "music.wav" if choice == 1 else f"music_{choice:02d}.wav"
            path = os.path.join(bd, name)
            if not os.path.exists(path):
                subprocess.run([
                    sys.executable,
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "music.py"),
                    path, str(total + 2),
                    f"{bd}/vo.mp3" if os.path.exists(f"{bd}/vo.mp3") else "-",
                    s.get("genre") or "-", profile or "-", str(choice),
                ], check=True)
            row = {
                "file": name,
                "label": score.variant_label(choice, s.get("genre"), profile),
                "source": "generated",
                "variant": choice,
                "index": choice,
            }
            variants.append(row)
            generated.append(row)

    variants[0]["selected"] = True
    s["music_choice"] = int(variants[0].get("variant") or s.get("music_choice", 3))
    s["music_variant_count"] = len(variants)
    s["music_variants"] = variants
    s["music"] = variants[0]["file"]
    with open(f"{bd}/script.json", "w") as f:
        json.dump(s, f, indent=1, ensure_ascii=False)

    for item in generated:
        marker = os.path.join(bd, item["file"] + ".sfx-ok")
        if os.path.exists(marker):
            continue
        try:
            subprocess.run([
                sys.executable,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfx.py"),
                bd, item["file"],
            ], check=True)
            with open(marker, "w") as f:
                f.write("ok\n")
        except Exception as e:
            print(f"note: sfx skipped for {item['file']} ({e})")
    return s


def prep(bd):
    with open(f"{bd}/script.json") as f:
        s = json.load(f)
    outputs = render_policy.render_outputs(s)
    portrait_assets = render_policy.needs_portrait_segments(s)
    youtube_assets = "youtube" in outputs
    for i, sc in enumerate(s["scenes"]):
        if sc.get("kw_times"):
            if portrait_assets:
                ovs = caption_png(
                    sc["text"], sc.get("keywords", []), f"{bd}/cap_{i:02d}.png",
                    kw_overlay_prefix=f"{bd}/cap_{i:02d}_kw",
                )
                sc["kw_overlays"] = [
                    {"kw": key, "png": os.path.basename(path)} for key, path in ovs
                ]
            if youtube_assets:
                yt_ovs = youtube_caption_png(
                    sc["text"], sc.get("keywords", []),
                    f"{bd}/youtube_cap_{i:02d}.png",
                    kw_overlay_prefix=f"{bd}/youtube_cap_{i:02d}_kw",
                )
                sc["youtube_kw_overlays"] = [
                    {"kw": key, "png": os.path.basename(path)} for key, path in yt_ovs
                ]
        else:
            if portrait_assets:
                caption_png(
                    sc["text"], sc.get("keywords", []), f"{bd}/cap_{i:02d}.png"
                )
            if youtube_assets:
                youtube_caption_png(
                    sc["text"], sc.get("keywords", []),
                    f"{bd}/youtube_cap_{i:02d}.png",
                )
    with open(f"{bd}/script.json", "w") as f:
        json.dump(s, f, indent=1, ensure_ascii=False)
    # Yellow series bug only for genuine series episodes (DMT, June Oxley, Reality Machine...).
    # Standalone videos show the core title only.
    eyebrow = s.get("title_eyebrow") or s.get("series_label")
    if (s.get("title_mode") == "standalone") or s.get("series_label") in (None, "", "null"):
        eyebrow = None
    if portrait_assets:
        title_png(s["title"], f"{bd}/title.png", eyebrow=eyebrow)
    if youtube_assets:
        youtube_title_png(s["title"], f"{bd}/youtube_title.png", eyebrow=eyebrow)
    s = prepare_music(bd, s)
    print(
        f"prep done: {len(s['scenes'])} scenes for {', '.join(outputs)} + "
        f"{len(s['music_variants'])} selected music choice(s)"
    )


if __name__ == "__main__":
    prep(sys.argv[1])
