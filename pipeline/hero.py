"""Hero shots: stock-frame-conditioned imagery with full still enhancement.
No required paid APIs: images via Pollinations Kontext, depth via MiDaS-small ONNX.

Usage: python3 hero.py <build_dir> <scene_index>
Scene needs: "hero": true, "image_prompt": "what the shot shows"
Writes clip_XX.mp4 (which footage.py then skips). Stages are cached and resumable:
hero_XX.jpg -> hero_XX_depth.npy -> clip_XX.mp4 (atomic)."""
import hashlib, io, json, os, sys, urllib.parse, urllib.request

import numpy as np
from PIL import Image

import motion
import profiles
import still_reference

W, H, FPS = 1344, 768, 30
MODEL_URL = "https://github.com/isl-org/MiDaS/releases/download/v2_1/model-small.onnx"

STYLE = {
    None:  (", natural documentary photograph, candid unstaged contemporary people, "
            "neutral true-to-life color, soft diffused daylight, realistic skin texture, "
            "practical lived-in location, ordinary clothing, clean clear air, subtle film grain, "
            "no haze or fog, no silhouetted figures, no fantasy lighting, no surreal effects"),
    "dmt": ", visionary psychedelic art, hyperdetailed, vivid luminous colors on deep black, intricate sacred geometry",
}


def _valid_image(path):
    """Reject partial JPEG uploads before they can poison a cached hero clip."""
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 20_000:
            return False
        with Image.open(path) as image:
            image.load()
            return image.width >= 512 and image.height >= 288
    except Exception:
        return False


def _file_signature(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()[:20]


def source_matches(scene, path):
    """Return whether a cached hero clip was built from this complete source."""
    return bool(
        _valid_image(path) and
        scene.get("hero_raw_signature") == _file_signature(path)
    )


def model_path():
    p = os.environ.get("HERO_DEPTH_MODEL", "/tmp/models/midas-small.onnx")
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        op = urllib.request.build_opener(); op.addheaders = [("User-Agent", "Mozilla/5.0")]
        urllib.request.install_opener(op)
        urllib.request.urlretrieve(MODEL_URL, p + ".part")
        os.replace(p + ".part", p)
    return p


def generation_url(prompt, seed, reference_url=None):
    params = {
        "width": W,
        "height": H,
        "nologo": "true",
        "enhance": "true",
        "safe": "true",
        "seed": int(seed),
    }
    if reference_url:
        params.update({"model": "kontext", "image": reference_url})
    key = os.environ.get("POLLINATIONS_API_KEY")
    if key:
        params["key"] = key
    return (
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?"
        f"{urllib.parse.urlencode(params)}"
    )


def gen_image(prompt, genre, out, profile=None, reference_url=None, force=False, style_override=None):
    if not force and _valid_image(out):
        return True
    style = style_override or profiles.hero_style(profile, genre) or STYLE.get(genre, STYLE[None])
    subject = profiles.hero_prompt(prompt, profile)
    if reference_url:
        subject = (
            "Transform the supplied stock-video frame into a NEW natural still depicting: "
            f"{subject}. Preserve the reference frame's documentary camera language, lens "
            "perspective, readable exposure, practical lighting, spatial depth, palette, and "
            "production realism. Replace its people, objects, and action wherever the new "
            "subject requires it; do not preserve faces, logos, signage, or readable text. "
            "Make the result look like another frame photographed for the same film"
        )
    full_prompt = subject + style
    last = None
    for seed in (7, 77, 777):
        try:
            url = generation_url(full_prompt, seed, reference_url)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=180).read()
            image = Image.open(io.BytesIO(data)).convert("RGB")
            if len(data) > 20_000 and image.width >= 512 and image.height >= 288:
                partial = out + ".part.jpg"
                image.save(partial, quality=95, subsampling=0)
                os.replace(partial, out)
                return True
        except Exception as e:
            last = e
    print(
        f"WARNING: reference-conditioned image generation failed ({last}); "
        "falling back to genuine stock footage for this beat"
    )
    return False


def depth_map(img_path, out, force=False):
    import cv2, onnxruntime as ort
    if os.path.exists(out) and not force:
        return np.load(out)
    img = cv2.imread(img_path)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    inp = cv2.resize(rgb, (256, 256)).transpose(2, 0, 1)[None]
    mean = np.array([0.485, 0.456, 0.406], np.float32).reshape(1, 3, 1, 1)
    std = np.array([0.229, 0.224, 0.225], np.float32).reshape(1, 3, 1, 1)
    sess = ort.InferenceSession(model_path(), providers=["CPUExecutionProvider"])
    d = sess.run(None, {sess.get_inputs()[0].name: (inp - mean) / std})[0][0]
    d = (d - d.min()) / (d.max() - d.min() + 1e-6)          # 0=far 1=near
    d = cv2.resize(d, (img.shape[1], img.shape[0]))
    d = cv2.GaussianBlur(d, (31, 31), 0)                     # soft edges = fewer tears
    np.save(out, d.astype(np.float32))
    return d


def render(img_path, depth, dur, out, mode=0, recipe="atmosphere"):
    """Depth-layered cinemagraph with background completion and local motion."""
    motion.render_depth_animation(
        img_path, depth, dur, out, recipe=recipe, strength=.78, seed=mode,
    )


def main(bd, i):
    s = json.load(open(f"{bd}/script.json"))
    sc = s["scenes"][i]
    out = f"{bd}/clip_{i:02d}.mp4"
    raw = f"{bd}/hero_{i:02d}_raw.jpg"
    raw_signature = _file_signature(raw) if _valid_image(raw) else None
    # A finished clip is reusable across resumable Governor passes. Pure heroes
    # (hero_style) have no stock reference, so gate reuse on the clip existing
    # rather than reference_is_current. The raw-image signature also prevents a
    # repaired or replaced source JPEG from reusing an older cached clip.
    if (os.path.exists(out) and os.path.getsize(out) > 100_000 and
            sc.get("clip_fingerprint") == motion.scene_visual_fingerprint(sc) and
            source_matches(sc, raw) and
            (sc.get("hero_style") or still_reference.reference_is_current(bd, s, i))):
        print(f"hero {i}: exists"); return
    prompt = sc.get("image_prompt") or sc["text"]
    style_override = sc.get("hero_style")
    if style_override == "effects":  # scripts opt in by name, not by pasting the style
        style_override = motion.EFFECTS_STILL_STYLE
    pure = bool(style_override)  # purely generated, no stock-reference conditioning
    reference = ({"url": None, "path": None, "scene_index": None}
                 if pure else still_reference.bind_reference(bd, s, i))
    img, dep = f"{bd}/hero_{i:02d}.jpg", f"{bd}/hero_{i:02d}_depth.npy"
    # Reuse a pre-generated (committed) raw still when present so renders never
    # depend on the image provider being reachable from CI. Otherwise generate.
    have_committed = _valid_image(raw)
    generated = gen_image(
        prompt, s.get("genre"), raw, profiles.resolve(s),
        reference_url=reference["url"], force=not have_committed,
        style_override=style_override,
    )
    if not generated:
        sc["hero"] = False
        sc["hero_fallback"] = "stock"
        sc["hero_fallback_reason"] = "reference_conditioned_provider_unavailable"
        for key in (
            "hero_generated", "motion_compiled", "still_reference_generation_model",
            "still_reference_motion_complete", "motion_source", "hero_raw_signature",
        ):
            sc.pop(key, None)
        for path in (raw, raw + ".part.jpg", img, dep, out):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        json.dump(s, open(f"{bd}/script.json", "w"), indent=1, ensure_ascii=False)
        print(f"hero {i}: disabled after bounded provider failure; stock fallback queued")
        return
    raw_signature = _file_signature(raw)
    if pure:
        still_reference.enhance_generated_image_standalone(bd, s, i, raw, img)
    else:
        still_reference.enhance_generated_image(bd, s, i, raw, img)
    d = depth_map(img, dep, force=True)
    recipe = motion.infer_recipe(sc)
    render(img, d, sc.get("duration", 8) + 0.5, out, mode=i, recipe=recipe)
    sc["clip"] = out
    sc["clip_fingerprint"] = motion.scene_visual_fingerprint(sc)
    sc["hero_generated"] = True
    sc["hero_raw_signature"] = raw_signature
    sc["motion_mode"] = "cinemagraph"
    sc["motion_kind"] = motion.ANIMATED
    sc["motion_recipe"] = recipe
    sc["motion_compiled"] = True
    sc["motion_source"] = "reference_conditioned_still"
    sc["still_reference_generation_model"] = "pollinations_kontext"
    still_reference.mark_motion_complete(sc)
    json.dump(s, open(f"{bd}/script.json", "w"), indent=1, ensure_ascii=False)
    print(
        f"hero {i}: generated from stock scene {reference['scene_index']} "
        f"({prompt[:60]}...)"
    )


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
