"""Reference continuity and mandatory enhancement for still-derived scenes.

Every still begins with a frame from the most closely related *selected stock
video scene* in the same film.  The saved frame is both an audit artifact and,
for generated hero images, the actual image-to-image conditioning input.

The module deliberately keeps provenance honest.  Reference conditioning,
depth, internal motion, and grading improve a still; they never turn it into
genuine temporal footage or remove it from the 35% still-source budget.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import urllib.request

import numpy as np
from PIL import Image

from video_format import BAND_HEIGHT, BAND_WIDTH


POLICY = "closest_stock_frame_full_enhancement"
ENHANCEMENT_VERSION = 1

REFERENCE_STEPS = (
    "closest_related_stock_scene",
    "stock_video_frame_reference",
    "reference_palette_harmonization",
    "readable_exposure_normalization",
    "natural_detail_recovery",
)
GENERATED_STEPS = ("reference_conditioned_image_generation",)
MOTION_STEPS = (
    "depth_separated_layers",
    "occlusion_background_completion",
    "recipe_specific_internal_motion",
    "restrained_practical_light_motion",
    "cohesive_final_grade",
    "subtle_film_grain",
)

STATIC_MODES = {"static", "still", "pan", "zoom", "ken_burns"}
STILL_KINDS = {"static", "animated_still"}


class StillReferenceError(ValueError):
    """Raised when a still cannot satisfy the reference/enhancement policy."""


_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "because", "before", "but",
    "by", "for", "from", "has", "have", "in", "into", "is", "it", "its",
    "of", "on", "or", "person", "people", "photograph", "scene", "shot",
    "that", "the", "their", "them", "this", "to", "video", "was", "were",
    "while", "with", "you", "your", "natural", "candid", "documentary",
    "cinematic", "realistic", "wide", "close", "up", "bright", "soft",
    "light", "lighting", "daylight",
}


def _norm_word(word):
    word = str(word).lower().strip()
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word


def _terms(scene):
    values = [
        scene.get("image_prompt"), scene.get("symbol_query"), scene.get("query"),
        scene.get("semantic_anchor"), scene.get("primary_symbol"),
        scene.get("visual_function"), scene.get("text"),
    ]
    words = {
        _norm_word(word)
        for word in re.findall(r"[a-zA-Z][a-zA-Z'-]+", " ".join(
            str(value or "") for value in values
        ))
    }
    return {word for word in words if len(word) > 2 and word not in _STOP}


def is_active_still(scene):
    """Whether this scene's current source is a still, not its stale author flag."""
    if scene.get("motion_kind") == "video" or str(
            scene.get("motion_mode") or "").lower() in {
                "video", "stock", "recorded", "i2v", "image_to_video",
            }:
        return False
    if scene.get("motion_kind") in STILL_KINDS:
        return True
    return bool(
        scene.get("hero") or scene.get("source_image") or scene.get("still") or
        scene.get("image") or scene.get("keyframes") or
        scene.get("enhanced_source_image") or scene.get("enhanced_keyframes")
    )


def is_stock_reference_scene(scene):
    return bool(
        scene.get("motion_kind") == "video" and scene.get("motion_verified") and
        (scene.get("stock_id") or scene.get("pexels_id")) and
        scene.get("stock_frame_url") and not scene.get("stock_frame_url_unusable")
    )


def relatedness(target, candidate, target_index=0, candidate_index=0):
    """Deterministic semantic score for choosing continuity footage.

    Literal token overlap carries most of the score.  Planner annotations then
    reward a shared symbol family/prop/function, while timeline distance only
    breaks otherwise similar choices.
    """
    left, right = _terms(target), _terms(candidate)
    overlap = left & right
    lexical = 16.0 * len(overlap) / max(math.sqrt(len(left) * len(right)), 1.0)
    score = lexical
    if target.get("symbol_family") and (
            target.get("symbol_family") == candidate.get("symbol_family")):
        score += 5.0
    if target.get("primary_symbol") and (
            str(target.get("primary_symbol")).lower() ==
            str(candidate.get("primary_symbol")).lower()):
        score += 7.0
    if target.get("visual_function") and (
            target.get("visual_function") == candidate.get("visual_function")):
        score += 2.0
    distance = abs(int(target_index) - int(candidate_index))
    score += 1.5 / (1.0 + distance)
    return round(score, 5)


def ranked_reference_scenes(script, target_index):
    """Return eligible selected-stock scenes, closest relationship first."""
    target = script["scenes"][int(target_index)]
    ranked = []
    for index, candidate in enumerate(script.get("scenes", [])):
        if index == int(target_index) or not is_stock_reference_scene(candidate):
            continue
        score = relatedness(target, candidate, target_index, index)
        ranked.append((score, abs(index - int(target_index)), index, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return ranked


def stock_targets(build_dir, script):
    """True-motion scenes that must be acquired before still generation starts."""
    out = []
    for index, scene in enumerate(script.get("scenes", [])):
        if scene.get("motion_kind") != "video":
            continue
        clip = os.path.join(build_dir, f"clip_{index:02d}.mp4")
        ready = os.path.exists(clip) and os.path.getsize(clip) > 100_000
        if not ready or not scene.get("motion_verified"):
            out.append(index)
    # Older scripts may have verified/cached clips but no saved provider frame.
    # Make one metadata-only pass when a still needs a reference. Providers that
    # have no public thumbnail are marked checked so this never loops forever.
    needs_reference = any(is_active_still(scene) for scene in script.get("scenes", []))
    if needs_reference:
        for index, scene in enumerate(script.get("scenes", [])):
            if (scene.get("motion_kind") == "video" and
                    str(scene.get("motion_mode") or "").lower() == "stock" and
                    not scene.get("stock_frame_url_checked") and index not in out):
                out.append(index)
    return out


def _valid_image(path):
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 4_000:
            return False
        with Image.open(path) as image:
            image.verify()
        return True
    except Exception:
        return False


def _download_snapshot(url, output):
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    )
    data = urllib.request.urlopen(request, timeout=35).read(20 * 1024 * 1024)
    image = Image.open(io.BytesIO(data)).convert("RGB")
    if image.width < 240 or image.height < 135:
        raise ValueError("stock reference frame is too small")
    partial = output + ".part.jpg"
    image.save(partial, quality=94, subsampling=0)
    os.replace(partial, output)


def bind_reference(build_dir, script, target_index):
    """Save and record the exact public frame used to condition one still."""
    target_index = int(target_index)
    target = script["scenes"][target_index]
    ranked = ranked_reference_scenes(script, target_index)
    if not ranked:
        raise StillReferenceError(
            f"scene {target_index} has no verified stock-video scene with a public "
            "frame; acquire the genuine-footage scenes before generating this still"
        )

    output = os.path.join(build_dir, f"stock_reference_{target_index:02d}.jpg")
    errors = []
    for score, _distance, index, source in ranked:
        url = source.get("stock_frame_url")
        same = (
            target.get("still_reference_scene") == index and
            target.get("still_reference_stock_id") == (
                source.get("stock_id") or source.get("pexels_id")
            ) and target.get("still_reference_url") == url
        )
        try:
            if not (same and _valid_image(output)):
                _download_snapshot(url, output)
            target.update({
                "still_reference_policy": POLICY,
                "still_reference_scene": index,
                "still_reference_stock_id": (
                    source.get("stock_id") or source.get("pexels_id")
                ),
                "still_reference_source": source.get("motion_source") or "stock",
                "still_reference_url": url,
                "still_reference_frame": os.path.basename(output),
                "still_reference_match_score": score,
            })
            _add_steps(target, REFERENCE_STEPS)
            return {
                "scene_index": index,
                "stock_id": target["still_reference_stock_id"],
                "url": url,
                "path": output,
                "score": score,
            }
        except Exception as exc:
            # A dead provider thumbnail is not an eligible frame.  Persisting
            # this during the current build lets validation agree with the
            # successful next-ranked reference instead of retrying forever.
            source["stock_frame_url_unusable"] = True
            errors.append(f"scene {index}: {exc}")
    raise StillReferenceError(
        f"scene {target_index} could not save a stock reference frame "
        f"({'; '.join(errors[:3])})"
    )


def _path(build_dir, value):
    if not value:
        return None
    return value if os.path.isabs(value) else os.path.join(build_dir, value)


def _cover(image, width=BAND_WIDTH, height=BAND_HEIGHT):
    ih, iw = image.shape[:2]
    scale = max(width / max(iw, 1), height / max(ih, 1))
    nw, nh = max(int(round(iw * scale)), width), max(int(round(ih * scale)), height)
    import cv2
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    x, y = (nw - width) // 2, (nh - height) // 2
    return resized[y:y + height, x:x + width]


def enhance_image(source, reference, output):
    """Make one image belong beside its reference without copying its content."""
    import cv2

    image = cv2.imread(source)
    ref = cv2.imread(reference)
    if image is None:
        raise StillReferenceError(f"cannot read still image: {source}")
    if ref is None:
        raise StillReferenceError(f"cannot read stock reference: {reference}")
    image = _cover(image)
    ref = _cover(ref)

    # Restrained LAB transfer ties palette/exposure to the neighboring footage
    # while retaining the generated/source photograph's own local color.
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    ref_lab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)
    out_lab = lab.copy()
    for channel in range(3):
        source_mean, source_std = cv2.meanStdDev(lab[..., channel])
        ref_mean, ref_std = cv2.meanStdDev(ref_lab[..., channel])
        sm, ss = float(source_mean[0, 0]), max(float(source_std[0, 0]), 1.0)
        rm, rs = float(ref_mean[0, 0]), max(float(ref_std[0, 0]), 1.0)
        ratio = min(max(rs / ss, .72), 1.38)
        matched = (lab[..., channel] - sm) * ratio + rm
        strength = .34 if channel == 0 else .28
        out_lab[..., channel] = lab[..., channel] * (1.0 - strength) + matched * strength
    harmonized = cv2.cvtColor(
        np.clip(out_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR
    )

    # Lift unreadable stills, but never manufacture the rejected gold-fog look.
    gray = cv2.cvtColor(harmonized, cv2.COLOR_BGR2GRAY)
    luma = float(np.mean(gray))
    if luma < 58:
        gamma = min(max(math.log(.34) / math.log(max(luma / 255.0, .03)), .72), .96)
        table = np.array([
            np.clip((value / 255.0) ** gamma * 255.0, 0, 255)
            for value in range(256)
        ], dtype=np.uint8)
        harmonized = cv2.LUT(harmonized, table)

    # A mild unsharp mask restores camera-like detail after generation/resizing.
    soft = cv2.GaussianBlur(harmonized, (0, 0), 1.05)
    harmonized = cv2.addWeighted(harmonized, 1.12, soft, -.12, 0)
    partial = output + ".part.jpg"
    if not cv2.imwrite(partial, harmonized, [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise StillReferenceError(f"could not write enhanced still: {output}")
    os.replace(partial, output)
    return output


def _digest(paths):
    value = hashlib.sha256()
    value.update(f"{POLICY}:{ENHANCEMENT_VERSION}".encode())
    for path in paths:
        value.update(os.path.basename(path).encode())
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                value.update(block)
    return value.hexdigest()[:20]


def _raw_source_paths(build_dir, scene, index):
    keyframes = [_path(build_dir, item) for item in scene.get("keyframes", [])]
    keyframes = [item for item in keyframes if item and os.path.exists(item)]
    if keyframes:
        return keyframes
    for key in ("source_image", "still", "image"):
        item = _path(build_dir, scene.get(key))
        if item and os.path.exists(item):
            return [item]
    for name in (f"still_{index:02d}.png", f"hero_{index:02d}.jpg"):
        item = os.path.join(build_dir, name)
        if os.path.exists(item):
            return [item]
    return []


def prepare_source_assets(build_dir, script, index):
    """Reference-match supplied/keyframe stills, preserving all originals."""
    index = int(index)
    scene = script["scenes"][index]
    sources = _raw_source_paths(build_dir, scene, index)
    if not sources:
        raise StillReferenceError(f"scene {index} has no source still to enhance")
    reference = bind_reference(build_dir, script, index)
    signature = _digest(sources + [reference["path"]])
    outputs = [
        os.path.join(
            build_dir,
            f"enhanced_still_{index:02d}.jpg" if len(sources) == 1 else
            f"enhanced_still_{index:02d}_{position:02d}.jpg",
        )
        for position in range(len(sources))
    ]
    if not (
        scene.get("still_reference_signature") == signature and
        all(_valid_image(path) for path in outputs)
    ):
        for source, output in zip(sources, outputs):
            enhance_image(source, reference["path"], output)
    scene["still_reference_signature"] = signature
    if len(outputs) > 1:
        scene["enhanced_keyframes"] = [os.path.basename(path) for path in outputs]
        scene.pop("enhanced_source_image", None)
    else:
        scene["enhanced_source_image"] = os.path.basename(outputs[0])
        scene.pop("enhanced_keyframes", None)
    _add_steps(scene, REFERENCE_STEPS)
    return outputs


def enhance_generated_image_standalone(build_dir, script, index, raw_image, output):
    """Finish a PURELY generated hero image with no stock-reference conditioning,
    preserving its own mood (used when a scene sets an explicit hero_style, e.g.
    a magical/eerie image that must not be exposure-matched to bright footage)."""
    import cv2
    scene = script["scenes"][int(index)]
    image = cv2.imread(raw_image)
    if image is None:
        raise StillReferenceError(f"cannot read still image: {raw_image}")
    image = _cover(image)
    soft = cv2.GaussianBlur(image, (0, 0), 1.05)   # gentle camera-like detail only
    image = cv2.addWeighted(image, 1.12, soft, -.12, 0)
    cv2.imwrite(output, image)
    scene["enhanced_source_image"] = os.path.basename(output)
    scene["still_reference_signature"] = _digest([raw_image])
    scene["pure_generated_still"] = True  # no stock reference by design
    _add_steps(scene, GENERATED_STEPS)
    return output


def enhance_generated_image(build_dir, script, index, raw_image, output):
    """Finish a reference-conditioned hero image before depth animation."""
    scene = script["scenes"][int(index)]
    reference = bind_reference(build_dir, script, index)
    enhance_image(raw_image, reference["path"], output)
    scene["enhanced_source_image"] = os.path.basename(output)
    scene["still_reference_signature"] = _digest([raw_image, reference["path"]])
    _add_steps(scene, REFERENCE_STEPS + GENERATED_STEPS)
    return output


def _add_steps(scene, steps):
    current = list(scene.get("still_enhancement_steps") or [])
    for step in steps:
        if step not in current:
            current.append(step)
    scene["still_enhancement_steps"] = current


def mark_motion_complete(scene):
    _add_steps(scene, MOTION_STEPS)
    scene["still_enhancement_version"] = ENHANCEMENT_VERSION
    scene["still_enhanced"] = True


def reference_is_current(build_dir, script, index):
    scene = script["scenes"][int(index)]
    if not is_active_still(scene) or not scene.get("still_enhanced"):
        return False
    if scene.get("still_enhancement_version") != ENHANCEMENT_VERSION:
        return False
    frame = _path(build_dir, scene.get("still_reference_frame"))
    if not frame or not _valid_image(frame):
        return False
    ranked = ranked_reference_scenes(script, index)
    if not ranked:
        return False
    _score, _distance, source_index, source = ranked[0]
    return bool(
        scene.get("still_reference_policy") == POLICY and
        scene.get("still_reference_scene") == source_index and
        scene.get("still_reference_stock_id") == (
            source.get("stock_id") or source.get("pexels_id")
        ) and scene.get("still_reference_url") == source.get("stock_frame_url")
    )


def validation_errors(build_dir, script):
    errors = []
    for index, scene in enumerate(script.get("scenes", [])):
        if not is_active_still(scene):
            continue
        mode = str(scene.get("motion_mode") or "").lower()
        if mode in STATIC_MODES:
            errors.append(f"scene {index} uses unenhanced still mode {mode}")
        if not scene.get("pure_generated_still") and not reference_is_current(build_dir, script, index):
            errors.append(f"scene {index} lacks a current closest-stock frame reference")
        if not scene.get("still_enhanced"):
            errors.append(f"scene {index} has not completed the full still enhancement path")
        missing = set(MOTION_STEPS) - set(scene.get("still_enhancement_steps") or [])
        if missing:
            errors.append(
                f"scene {index} is missing enhancement steps: {', '.join(sorted(missing))}"
            )
    return errors


def validate(build_dir, script):
    errors = validation_errors(build_dir, script)
    if errors:
        raise StillReferenceError("; ".join(errors))
    return True


def write_report(build_dir, script=None):
    if script is None:
        script = json.load(open(os.path.join(build_dir, "script.json")))
    errors = validation_errors(build_dir, script)
    scenes = []
    for index, scene in enumerate(script.get("scenes", [])):
        if not is_active_still(scene):
            continue
        scenes.append({
            "index": index,
            "reference_scene": scene.get("still_reference_scene"),
            "reference_stock_id": scene.get("still_reference_stock_id"),
            "reference_source": scene.get("still_reference_source"),
            "reference_frame": scene.get("still_reference_frame"),
            "reference_match_score": scene.get("still_reference_match_score"),
            "motion_mode": scene.get("motion_mode"),
            "enhancement_version": scene.get("still_enhancement_version"),
            "enhancements": scene.get("still_enhancement_steps") or [],
            "passes": reference_is_current(build_dir, script, index),
        })
    report = {
        "policy": POLICY,
        "enhancement_version": ENHANCEMENT_VERSION,
        "passes": not errors,
        "violations": errors,
        "still_scenes": scenes,
    }
    with open(os.path.join(build_dir, "still_reference_report.json"), "w") as handle:
        json.dump(report, handle, indent=2)
    return report
