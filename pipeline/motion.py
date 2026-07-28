"""CPU-first motion compiler and motion-budget accounting.

The pipeline distinguishes three source classes by *duration*:

``static``
    A still whose only movement is crop, pan, or zoom.
``animated_still``
    A still with depth-separated movement, internal/local motion, or evolving
    keyframes.
``video``
    Recorded footage or a true image/text-to-video result.

The distinction is intentionally editorial rather than file-based: encoding a
PNG as MP4 does not magically turn it into video, and adding depth/parallax does
not change its source class.  By default no more than 35% of a finished film may
come from ``static`` plus ``animated_still`` sources.  At least 65% must be true
temporal footage in which the photographed/generated world changes over time.

Scene fields understood by the compiler::

    {
      "source_image": "still_04.png",
      "motion_mode": "depth",             # depth | cinemagraph | keyframes | static
      "motion_recipe": "human",           # optional; inferred from the line
      "motion_strength": 0.8,              # 0.0 .. 1.5
      "keyframes": ["start.png", "end.png"]
    }

Depth animation uses the repo's CPU MiDaS/ONNX estimator, creates an inpainted
background plate for newly exposed pixels, separates foreground/mid/background,
and adds restrained recipe-specific internal motion.  Keyframes use optional
RIFE-ncnn-vulkan when RIFE_BIN is configured, otherwise deterministic optical-
flow interpolation via OpenCV.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import numpy as np

import still_reference
from video_format import BAND_HEIGHT, BAND_WIDTH, FPS, ENCODE_QUALITY, COLOR_TAGS


STATIC = "static"
ANIMATED = "animated_still"
VIDEO = "video"
KINDS = {STATIC, ANIMATED, VIDEO}

STATIC_MODES = {"static", "still", "pan", "zoom", "ken_burns"}
ANIMATED_MODES = {
    "animated", "animated_still", "depth", "parallax", "cinemagraph",
    "keyframes", "flow", "portrait",
}
VIDEO_MODES = {"video", "stock", "recorded", "i2v", "image_to_video"}
COMPILE_MODES = STATIC_MODES | ANIMATED_MODES

DEFAULT_STILL_SOURCE_CAP = 0.50
# Compatibility for callers that imported the old constant.  Budget validation
# itself uses DEFAULT_STILL_SOURCE_CAP and counts animated stills in full.
DEFAULT_STATIC_CAP = DEFAULT_STILL_SOURCE_CAP
W, H = BAND_WIDTH, BAND_HEIGHT


class MotionBudgetError(ValueError):
    """Raised when static-image duration exceeds the configured budget."""


@dataclass(frozen=True)
class MotionReport:
    total_seconds: float
    static_seconds: float
    animated_seconds: float
    video_seconds: float
    static_ratio: float
    still_source_ratio: float
    video_ratio: float
    max_still_source_ratio: float
    scenes: tuple[dict, ...]

    def as_dict(self):
        return {
            "total_seconds": round(self.total_seconds, 3),
            "static_seconds": round(self.static_seconds, 3),
            "animated_still_seconds": round(self.animated_seconds, 3),
            "still_source_seconds": round(
                self.static_seconds + self.animated_seconds, 3
            ),
            "video_seconds": round(self.video_seconds, 3),
            "static_only_ratio": round(self.static_ratio, 4),
            "still_source_ratio": round(self.still_source_ratio, 4),
            "true_motion_ratio": round(self.video_ratio, 4),
            "max_still_source_ratio": round(self.max_still_source_ratio, 4),
            "minimum_true_motion_ratio": round(
                1.0 - self.max_still_source_ratio, 4
            ),
            "passes": (
                self.still_source_ratio <= self.max_still_source_ratio + 1e-9
            ),
            "scenes": list(self.scenes),
        }


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def motion_kind(scene):
    """Return an editorial motion class for one scene.

    Explicit metadata wins.  The fallback recognizes hero animation and stock
    footage, while treating an image or an image encoded as a clip as static.
    """
    explicit = scene.get("motion_kind")
    if explicit in KINDS:
        return explicit

    mode = str(scene.get("motion_mode") or "").strip().lower()
    if mode in STATIC_MODES:
        return STATIC
    if mode in ANIMATED_MODES:
        return ANIMATED
    if mode in VIDEO_MODES:
        return VIDEO

    if scene.get("motion_compiled") or scene.get("hero_generated"):
        return ANIMATED
    if scene.get("pexels_id") or scene.get("stock_id"):
        return VIDEO
    if scene.get("hero"):
        return ANIMATED
    if scene.get("source_image") or scene.get("still") or scene.get("keyframes"):
        return STATIC

    clip = str(scene.get("clip") or "").lower()
    if clip.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return STATIC

    # Normal pipeline scenes with literal search queries are intended to become
    # real footage.  Classifying them before download keeps budget validation
    # deterministic across resumable build passes.
    if scene.get("query"):
        return VIDEO
    if clip.endswith((".mp4", ".mov", ".mkv", ".webm")):
        return VIDEO
    return STATIC


def apply_motion_defaults(script):
    """Persist source metadata and route every still through full enhancement."""
    changed = False
    if "max_still_source_ratio" not in script:
        # Upgrade older scripts without changing a deliberately customized cap.
        script["max_still_source_ratio"] = _float(
            script.get("max_static_ratio"), DEFAULT_STILL_SOURCE_CAP
        )
        changed = True
    if script.get("still_image_policy") != still_reference.POLICY:
        script["still_image_policy"] = still_reference.POLICY
        changed = True
    for scene in script.get("scenes", []):
        if scene.get("motion_kind") not in KINDS:
            scene["motion_kind"] = motion_kind(scene)
            changed = True
        if still_reference.is_active_still(scene):
            target_mode = (
                "keyframes" if len(scene.get("keyframes") or []) > 1
                else "cinemagraph"
            )
            if scene.get("motion_mode") != target_mode:
                scene["motion_mode"] = target_mode
                changed = True
            if scene.get("motion_kind") != ANIMATED:
                scene["motion_kind"] = ANIMATED
                changed = True
            if scene.get("still_reference_policy") != still_reference.POLICY:
                scene["still_reference_policy"] = still_reference.POLICY
                changed = True
    return changed


def report(script):
    cap = _float(
        script.get("max_still_source_ratio", script.get("max_static_ratio")),
        DEFAULT_STILL_SOURCE_CAP,
    )
    cap = min(max(cap, 0.0), 1.0)
    buckets = {STATIC: 0.0, ANIMATED: 0.0, VIDEO: 0.0}
    entries = []
    for i, scene in enumerate(script.get("scenes", [])):
        duration = max(_float(scene.get("duration")), 0.0)
        kind = motion_kind(scene)
        buckets[kind] += duration
        entries.append({
            "index": i,
            "kind": kind,
            "mode": scene.get("motion_mode"),
            "duration": round(duration, 3),
            "source": scene.get("motion_source"),
            "motion_verified": scene.get("motion_verified") if kind == VIDEO else None,
            "motion_evidence": scene.get("motion_evidence") if kind == VIDEO else None,
        })
    total = sum(buckets.values())
    static_ratio = buckets[STATIC] / total if total else 0.0
    still_source_ratio = (
        (buckets[STATIC] + buckets[ANIMATED]) / total if total else 0.0
    )
    video_ratio = buckets[VIDEO] / total if total else 0.0
    return MotionReport(
        total, buckets[STATIC], buckets[ANIMATED], buckets[VIDEO], static_ratio,
        still_source_ratio, video_ratio, cap, tuple(entries),
    )


def validate_budget(script):
    """Return a report or raise with an actionable duration-based error."""
    result = report(script)
    if (result.total_seconds and
            result.still_source_ratio > result.max_still_source_ratio + 1e-9):
        still_seconds = result.static_seconds + result.animated_seconds
        excess = still_seconds - result.total_seconds * result.max_still_source_ratio
        raise MotionBudgetError(
            f"still-derived shots are {result.still_source_ratio:.1%} of the film "
            f"({still_seconds:.1f}s/{result.total_seconds:.1f}s), above the "
            f"{result.max_still_source_ratio:.0%} cap by {excess:.1f}s; animated "
            "stills count toward this cap, so replace that duration with genuine "
            "moving footage"
        )
    return result


def validate_video_evidence(script):
    """Require downloaded/generated video scenes to carry temporal evidence."""
    missing = [
        index for index, scene in enumerate(script.get("scenes", []))
        if motion_kind(scene) == VIDEO and not scene.get("motion_verified")
    ]
    if missing:
        raise MotionBudgetError(
            "true-motion scenes lack temporal verification: "
            + ", ".join(str(index) for index in missing)
        )
    return True


def temporal_evidence(video_path, sample_count=9):
    """Measure non-uniform frame-to-frame change in a real video source.

    The median optical-flow vector is removed before scoring, which discounts a
    simple tripod bump or uniform pan and emphasizes people, objects, foliage,
    screens, light, and other regions changing independently inside the shot.
    This is a provenance check for footage; it never upgrades a still-derived
    scene into the ``video`` class.
    """
    import cv2

    capture = cv2.VideoCapture(video_path)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if not capture.isOpened() or frame_count < 3:
        capture.release()
        return {
            "passes": False,
            "samples": 0,
            "residual_flow_p75": 0.0,
            "active_region_ratio": 0.0,
            "frame_difference": 0.0,
        }

    indexes = np.linspace(
        max(0, int(frame_count * .08)),
        max(1, int(frame_count * .92)),
        max(3, min(int(sample_count), frame_count)),
        dtype=int,
    )
    frames = []
    for index in indexes:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = capture.read()
        if not ok:
            continue
        height, width = frame.shape[:2]
        target_width = 320
        target_height = max(int(round(height * target_width / max(width, 1))), 90)
        gray = cv2.cvtColor(
            cv2.resize(frame, (target_width, target_height)), cv2.COLOR_BGR2GRAY
        )
        frames.append(gray)
    capture.release()

    residuals, active, differences = [], [], []
    for before, after in zip(frames, frames[1:]):
        flow = cv2.calcOpticalFlowFarneback(
            before, after, None, .5, 3, 21, 3, 5, 1.2, 0
        )
        global_vector = np.median(flow.reshape(-1, 2), axis=0)
        residual = np.linalg.norm(flow - global_vector, axis=2)
        residuals.append(float(np.percentile(residual, 75)))
        active.append(float(np.mean(residual > .35)))

        matrix = np.array(
            [[1.0, 0.0, -global_vector[0]],
             [0.0, 1.0, -global_vector[1]]],
            dtype=np.float32,
        )
        aligned = cv2.warpAffine(
            after, matrix, (after.shape[1], after.shape[0]),
            borderMode=cv2.BORDER_REFLECT_101,
        )
        differences.append(float(np.mean(cv2.absdiff(before, aligned))))

    flow_score = float(np.median(residuals)) if residuals else 0.0
    active_ratio = float(np.median(active)) if active else 0.0
    frame_difference = float(np.median(differences)) if differences else 0.0
    passes = (
        (flow_score >= .18 and active_ratio >= .025) or
        (active_ratio >= .08 and frame_difference >= 1.4)
    )
    return {
        "passes": bool(passes),
        "samples": len(frames),
        "residual_flow_p75": round(flow_score, 4),
        "active_region_ratio": round(active_ratio, 4),
        "frame_difference": round(frame_difference, 4),
    }


def write_report(build_dir, script=None):
    if script is None:
        script = json.load(open(os.path.join(build_dir, "script.json")))
    result = report(script)
    with open(os.path.join(build_dir, "motion_report.json"), "w") as handle:
        json.dump(result.as_dict(), handle, indent=2)
    return result


def infer_recipe(scene):
    """Choose a conservative internal-motion recipe from the literal beat."""
    if scene.get("motion_recipe"):
        return str(scene["motion_recipe"]).lower()
    text = " ".join(str(scene.get(k) or "") for k in
                    ("text", "query", "image_prompt")).lower()
    groups = (
        ("organic", ("seed", "root", "plant", "tree", "soil", "green", "grow", "womb")),
        ("paper", ("paper", "notebook", "sentence", "write", "erase", "photograph", "darkroom")),
        ("screen", ("phone", "camera", "record", "screen", "data", "posted", "analytics")),
        ("reflection", ("mirror", "reflection", "storefront", "window", "glass", "audience")),
        ("human", ("person", "people", "human", "face", "voice", "prisoner", "performer", "crowd")),
        ("light", ("light", "darkness", "shadow", "room", "stage")),
    )
    for name, words in groups:
        if any(word in text for word in words):
            return name
    return "atmosphere"


def _path(build_dir, value):
    if not value:
        return None
    return value if os.path.isabs(value) else os.path.join(build_dir, value)


def source_paths(build_dir, scene, index):
    frames = [_path(build_dir, value) for value in scene.get("enhanced_keyframes", [])]
    frames = [value for value in frames if value and os.path.exists(value)]
    if frames:
        return frames
    frames = [_path(build_dir, value) for value in scene.get("keyframes", [])]
    frames = [value for value in frames if value and os.path.exists(value)]
    if frames:
        return frames
    for key in ("enhanced_source_image", "source_image", "still", "image"):
        value = _path(build_dir, scene.get(key))
        if value and os.path.exists(value):
            return [value]
    for candidate in (
        os.path.join(build_dir, f"still_{index:02d}.png"),
        os.path.join(build_dir, f"hero_{index:02d}.jpg"),
    ):
        if os.path.exists(candidate):
            return [candidate]
    return []


def needs_compile(build_dir, scene, index):
    mode = str(scene.get("motion_mode") or "").lower()
    return mode in COMPILE_MODES and bool(source_paths(build_dir, scene, index))


def _cover(image, cv2):
    ih, iw = image.shape[:2]
    scale = max(W / max(iw, 1), H / max(ih, 1))
    nw, nh = max(int(round(iw * scale)), W), max(int(round(ih * scale)), H)
    image = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    x, y = (nw - W) // 2, (nh - H) // 2
    return image[y:y + H, x:x + W]


def _smoothstep(edge0, edge1, value):
    denom = max(float(edge1 - edge0), 1e-6)
    x = np.clip((value - edge0) / denom, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _warp(image, alpha, dx, dy, scale_x, scale_y, cv2):
    matrix = np.array([
        [scale_x, 0.0, dx + W * (1.0 - scale_x) / 2.0],
        [0.0, scale_y, dy + H * (1.0 - scale_y) / 2.0],
    ], dtype=np.float32)
    moved = cv2.warpAffine(image, matrix, (W, H), flags=cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REFLECT_101)
    mask = cv2.warpAffine(alpha, matrix, (W, H), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return moved, np.clip(mask, 0.0, 1.0)


def _composite(base, layer, alpha):
    a = alpha[..., None].astype(np.float32)
    return np.clip(base.astype(np.float32) * (1.0 - a) +
                   layer.astype(np.float32) * a, 0, 255).astype(np.uint8)


def _light_sweep(frame, t, recipe):
    """Animate practical light without turning documentary frames synthetic."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    center = W * (0.18 + 0.64 * t)
    width = W * (0.30 if recipe in {"light", "reflection"} else 0.45)
    glow = np.exp(-((xx - center) / max(width, 1.0)) ** 2)
    vertical = 0.78 + 0.22 * (1.0 - yy / H)
    amount = 0.055 if recipe in {"light", "reflection", "screen"} else 0.028
    gain = 1.0 + amount * glow * vertical
    if recipe == "screen":
        gain *= 0.992 + 0.008 * math.sin(t * math.tau * 5.0)
    return np.clip(frame.astype(np.float32) * gain[..., None], 0, 255).astype(np.uint8)


def _particles(frame, t, particles, cv2, drift=0.0):
    for x0, y0, speed, radius, opacity in particles:
        y = (y0 - t * speed * H) % H
        x = (x0 + drift + math.sin(t * math.tau + y0 / H * 4.0) * 8.0) % W
        overlay = frame.copy()
        cv2.circle(overlay, (int(x), int(y)), radius, (230, 226, 205), -1,
                   lineType=cv2.LINE_AA)
        frame = cv2.addWeighted(overlay, opacity, frame, 1.0 - opacity, 0)
    return frame


MOTION_3D_VERSION = "multiplane-v1"

CAMERA_MOVES = ("lateral", "push_in", "dolly_zoom", "orbit", "rack_focus")


def _sway(t, phase=0.0, amp=1.0):
    """Handheld micro-movement: two incommensurate sines, deterministic."""
    return amp * (0.6 * math.sin(math.tau * (2.13 * t + phase)) +
                  0.4 * math.sin(math.tau * (3.71 * t + phase + 0.37)))


def camera_path(camera, t, strength=1.0):
    """Per-layer camera parameters for one frame of a multiplane move.

    Returns {layer: (dx, dy, sx, sy, blur_sigma)} for layers bg/mid/near.
    Pure and deterministic; the testable core of the 3D illusion. Layer scale
    and translation DIFFERENTIALS between planes are what read as depth."""
    ease = t * t * (3.0 - 2.0 * t)
    travel = (2.0 * ease - 1.0) * strength
    hx, hy = _sway(t, 0.11, 1.1 * strength), _sway(t, 0.53, 0.7 * strength)
    if camera == "push_in":
        return {
            "bg":   (hx * 0.4, hy * 0.4, 1.0 + 0.030 * ease, 1.0 + 0.030 * ease, 0.0),
            "mid":  (hx * 0.7, hy * 0.7 - 1.0 * ease, 1.0 + 0.055 * ease, 1.0 + 0.055 * ease, 0.0),
            "near": (hx, hy - 2.2 * ease, 1.0 + 0.088 * ease, 1.0 + 0.088 * ease, 0.0),
        }
    if camera == "dolly_zoom":
        return {
            "bg":   (hx * 0.4, hy * 0.4, 1.0 + 0.150 * ease, 1.0 + 0.150 * ease, 0.0),
            "mid":  (hx * 0.7, hy * 0.7, 1.004 + 0.004 * ease, 1.004 + 0.004 * ease, 0.0),
            "near": (hx, hy, 1.010 - 0.022 * ease, 1.010 - 0.022 * ease, 0.0),
        }
    if camera == "orbit":
        arc = math.sin(ease * math.pi)
        return {
            "bg":   (-6.5 * travel + hx * 0.4, 0.8 * arc + hy * 0.4, 1.030, 1.030, 0.0),
            "mid":  (5.0 * travel + hx * 0.7, -0.6 * arc + hy * 0.7, 1.036, 1.036, 0.0),
            "near": (14.0 * travel + hx, -1.6 * arc + hy, 1.046, 1.046, 0.0),
        }
    if camera == "rack_focus":
        cross = _smoothstep(0.18, 0.82, np.float32(t))
        return {
            "bg":   (-1.5 * travel + hx * 0.4, hy * 0.4, 1.028, 1.028, 2.6 * float(cross)),
            "mid":  (2.5 * travel + hx * 0.7, hy * 0.7, 1.034, 1.034, 0.0),
            "near": (6.0 * travel + hx, hy, 1.042, 1.042, 2.2 * float(1.0 - cross)),
        }
    # legacy lateral drift (default)
    return {
        "bg":   (-2.6 * travel + hx * 0.4, -0.5 * _sway(t, 0.9, strength), 1.035, 1.035, 0.0),
        "mid":  (5.0 * travel + hx * 0.7, 1.2 * _sway(t, 0.9, strength), 1.038, 1.038, 0.0),
        "near": (11.5 * travel + hx, 2.0 * _sway(t, 0.9, strength), 1.044, 1.044, 0.0),
    }


def pick_camera(seed, recipe="atmosphere"):
    """Deterministic per-scene camera-move variety."""
    order = ("push_in", "orbit", "dolly_zoom", "lateral", "rack_focus")
    return order[int(seed) % len(order)]


def _guided_refine(depth, image, cv2, radius=9, eps=2e-3):
    """Snap soft depth edges to image edges (small self-contained guided filter)."""
    guide = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    d = depth.astype(np.float32)
    ksize = (radius * 2 + 1, radius * 2 + 1)
    mean_g = cv2.boxFilter(guide, -1, ksize)
    mean_d = cv2.boxFilter(d, -1, ksize)
    corr_gd = cv2.boxFilter(guide * d, -1, ksize)
    corr_gg = cv2.boxFilter(guide * guide, -1, ksize)
    var_g = corr_gg - mean_g * mean_g
    a = (corr_gd - mean_g * mean_d) / (var_g + eps)
    b = mean_d - a * mean_g
    mean_a = cv2.boxFilter(a, -1, ksize)
    mean_b = cv2.boxFilter(b, -1, ksize)
    return np.clip(mean_a * guide + mean_b, 0.0, 1.0)


def _layer_state(image, depth, cv2):
    depth = cv2.resize(depth.astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
    depth = cv2.GaussianBlur(depth, (0, 0), 5.0)
    lo, hi = float(depth.min()), float(depth.max())
    depth = (depth - lo) / max(hi - lo, 1e-6)
    depth = _guided_refine(depth, image, cv2)
    p35, p62, p82 = np.percentile(depth, (35, 62, 82))
    near = _smoothstep(p62, max(p82, p62 + .02), depth)
    mid_gate = _smoothstep(p35, max(p62, p35 + .02), depth)
    mid = np.clip(mid_gate * (1.0 - near), 0.0, 1.0)

    # Complete only the nearest occluding regions.  The camera path remains
    # deliberately restrained, so this plate is exposed at edges rather than as
    # a large invented background area.
    mask = (near > .62).astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((11, 11), np.uint8), iterations=1)
    if float((mask > 0).mean()) > .38:
        mask = (depth > np.percentile(depth, 90)).astype(np.uint8) * 255
    background = cv2.inpaint(image, mask, 5, cv2.INPAINT_TELEA)
    background = cv2.GaussianBlur(background, (0, 0), .65)
    return background, mid.astype(np.float32), near.astype(np.float32)


def _encode_frames(frames, duration, output, width=W, height=H):
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    partial = output + ".part.mp4"
    command = [
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}", "-r", str(FPS), "-i", "-", "-an",
        "-c:v", "libx264", *ENCODE_QUALITY, *COLOR_TAGS,
        "-pix_fmt", "yuv420p", "-t", f"{duration:.4f}", partial,
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for frame in frames:
            process.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
    finally:
        if process.stdin:
            process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError("motion encode failed")
    os.replace(partial, output)


def render_depth_animation(image_path, depth, duration, output, recipe="atmosphere",
                           strength=0.75, seed=0, camera="auto"):
    """Render a deterministic multiplane move from one still and depth map.

    camera: lateral | push_in | dolly_zoom | orbit | rack_focus | auto
    (auto picks per-seed for variety). Plane differentials in translation and
    scale produce the deep-parallax "the photo is moving" illusion."""
    import cv2

    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"cannot read image: {image_path}")
    image = _cover(image, cv2)
    background, mid_alpha, near_alpha = _layer_state(image, depth, cv2)
    frames = max(int(round(max(duration, 1 / FPS) * FPS)), 1)
    strength = min(max(_float(strength, .75), 0.0), 1.5)
    if camera == "auto" or camera not in CAMERA_MOVES:
        camera = pick_camera(seed, recipe)
    rng = np.random.default_rng(int(seed))

    def make_particles(count, size_lo, size_hi, op_lo, op_hi):
        return [
            (float(rng.uniform(0, W)), float(rng.uniform(0, H)),
             float(rng.uniform(.02, .08)), int(rng.integers(size_lo, size_hi)),
             float(rng.uniform(op_lo, op_hi)))
            for _ in range(count)
        ]

    dust_far = make_particles(9, 2, 4, .018, .04)   # soft, behind the near plane
    dust_near = make_particles(9, 1, 3, .03, .08)   # crisp, in front of everything

    def maybe_blur(plane, sigma):
        if sigma and sigma > 0.05:
            return cv2.GaussianBlur(plane, (0, 0), float(sigma))
        return plane

    def generate():
        for index in range(frames):
            t = index / max(frames - 1, 1)
            ease = t * t * (3.0 - 2.0 * t)
            breath = math.sin(t * math.tau * (0.72 if recipe == "human" else 1.0))
            path = camera_path(camera, t, strength)

            bx, by, bsx, bsy, bblur = path["bg"]
            mx, my, msx, msy, mblur = path["mid"]
            nx, ny, nsx, nsy, nblur = path["near"]

            # recipe accents ride on top of the camera move
            if recipe == "human":
                ny -= 1.7 * breath * strength
                nsy += .0045 * breath * strength
            elif recipe == "organic":
                ny -= 2.4 * ease * strength
                nsx += .007 * ease * strength
                nsy += .012 * ease * strength
            elif recipe == "reflection":
                nx += 2.5 * math.sin(t * math.tau * .5) * strength
            elif recipe == "paper":
                nx *= .42
                ny *= .35

            bg, _ = _warp(maybe_blur(background, bblur),
                          np.ones((H, W), np.float32), bx, by, bsx, bsy, cv2)
            mid, ma = _warp(maybe_blur(image, mblur), mid_alpha, mx, my, msx, msy, cv2)
            near, na = _warp(maybe_blur(image, nblur), near_alpha, nx, ny, nsx, nsy, cv2)

            frame = _composite(bg, mid, ma)
            if recipe in {"organic", "atmosphere", "light", "human"}:
                frame = _particles(frame, t, dust_far, cv2, drift=mx * 0.6)
            frame = _composite(frame, near, na)
            frame = _light_sweep(frame, t, recipe)
            if recipe in {"organic", "atmosphere", "light"}:
                frame = _particles(frame, t, dust_near, cv2, drift=nx * 1.15)
            yield frame

    _encode_frames(generate(), duration, output)


def _flows(a, b, cv2):
    small_size = (W // 2, H // 2)
    aa = cv2.resize(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), small_size)
    bb = cv2.resize(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), small_size)
    kwargs = dict(pyr_scale=.5, levels=4, winsize=25, iterations=4,
                  poly_n=7, poly_sigma=1.5, flags=0)
    ab = cv2.calcOpticalFlowFarneback(aa, bb, None, **kwargs)
    ba = cv2.calcOpticalFlowFarneback(bb, aa, None, **kwargs)
    ab = cv2.resize(ab, (W, H), interpolation=cv2.INTER_CUBIC) * 2.0
    ba = cv2.resize(ba, (W, H), interpolation=cv2.INTER_CUBIC) * 2.0
    return ab, ba


def _flow_blend(a, b, ab, ba, t, grid_x, grid_y, cv2):
    ease = t * t * (3.0 - 2.0 * t)
    wa = cv2.remap(a, grid_x - ab[..., 0] * ease, grid_y - ab[..., 1] * ease,
                   cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    wb = cv2.remap(b, grid_x - ba[..., 0] * (1.0 - ease),
                   grid_y - ba[..., 1] * (1.0 - ease), cv2.INTER_LINEAR,
                   borderMode=cv2.BORDER_REFLECT_101)
    return cv2.addWeighted(wa, 1.0 - ease, wb, ease, 0)


def _rife_binary():
    configured = os.environ.get("RIFE_BIN")
    if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
        return configured
    return shutil.which("rife-ncnn-vulkan")


def _render_rife(images, duration, output, binary, cv2):
    """Use RIFE's portable CPU path when the optional executable is installed."""
    frames = max(int(round(duration * FPS)), len(images))
    with tempfile.TemporaryDirectory() as td:
        source, rendered = os.path.join(td, "in"), os.path.join(td, "out")
        os.makedirs(source); os.makedirs(rendered)
        for i, image in enumerate(images):
            cv2.imwrite(os.path.join(source, f"{i:08d}.png"), image)
        result = subprocess.run([
            binary, "-i", source, "-o", rendered, "-n", str(frames), "-g", "-1",
        ], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"RIFE failed: {result.stderr[-300:]}")
        command = [
            "ffmpeg", "-v", "error", "-y", "-framerate", str(FPS),
            "-i", os.path.join(rendered, "%08d.png"), "-an", "-c:v", "libx264",
            *ENCODE_QUALITY, *COLOR_TAGS, "-pix_fmt", "yuv420p",
            "-t", f"{duration:.4f}", output + ".part.mp4",
        ]
        subprocess.run(command, check=True)
        os.replace(output + ".part.mp4", output)


def render_keyframes(paths, duration, output, recipe="atmosphere"):
    """Animate two or more staged images with RIFE or CPU optical flow."""
    import cv2

    images = []
    for path in paths:
        image = cv2.imread(path)
        if image is None:
            raise ValueError(f"cannot read keyframe: {path}")
        images.append(_cover(image, cv2))
    if len(images) < 2:
        raise ValueError("keyframe animation needs at least two readable images")

    binary = _rife_binary()
    if binary:
        try:
            return _render_rife(images, duration, output, binary, cv2)
        except Exception as exc:
            print(f"note: RIFE unavailable ({exc}); using CPU optical flow")

    pairs = [(_flows(a, b, cv2), a, b) for a, b in zip(images, images[1:])]
    total_frames = max(int(round(duration * FPS)), len(images))
    grid_x, grid_y = np.meshgrid(np.arange(W, dtype=np.float32),
                                 np.arange(H, dtype=np.float32))

    def generate():
        for index in range(total_frames):
            overall = index / max(total_frames - 1, 1) * (len(images) - 1)
            pair_index = min(int(overall), len(pairs) - 1)
            local = overall - pair_index
            (ab, ba), a, b = pairs[pair_index]
            frame = _flow_blend(a, b, ab, ba, local, grid_x, grid_y, cv2)
            yield _light_sweep(frame, index / max(total_frames - 1, 1), recipe)

    _encode_frames(generate(), duration, output)


def _estimate_depth(image_path, output, force=False):
    # Import lazily to keep motion reporting/test collection independent of the
    # heavier ONNX/OpenCV stack.
    import hero
    return hero.depth_map(image_path, output, force=force)


def compile_scene(build_dir, index):
    script_path = os.path.join(build_dir, "script.json")
    script = json.load(open(script_path))
    scene = script["scenes"][index]
    # Direct CLI compilation obeys the same rule as build.py: save the closest
    # selected stock frame, reference-match the still, and preserve originals.
    still_reference.prepare_source_assets(build_dir, script, index)
    paths = source_paths(build_dir, scene, index)
    if not paths:
        raise ValueError(f"scene {index} has no source image or keyframes")
    duration = max(_float(scene.get("duration")), 1.0)
    mode = str(scene.get("motion_mode") or "depth").lower()
    recipe = infer_recipe(scene)
    output = os.path.join(build_dir, f"clip_{index:02d}.mp4")

    if len(paths) > 1 or mode in {"keyframes", "flow"}:
        render_keyframes(paths, duration + .25, output, recipe)
        mode = "keyframes"
        kind = ANIMATED
    else:
        # Static/pan/zoom authoring hints are upgraded: a permitted still always
        # receives depth, completed occlusions, local motion, and moving light.
        depth_file = os.path.join(build_dir, f"motion_{index:02d}_depth.npy")
        depth_signature = scene.get("still_reference_signature")
        depth = _estimate_depth(
            paths[0], depth_file,
            force=scene.get("motion_depth_signature") != depth_signature,
        )
        render_depth_animation(paths[0], depth, duration + .25, output, recipe,
                               scene.get("motion_strength", .75), index)
        mode = "cinemagraph"
        kind = ANIMATED
        scene["motion_depth_signature"] = depth_signature

    scene.update({
        "clip": output,
        "motion_mode": mode,
        "motion_kind": kind,
        "motion_recipe": recipe,
        "motion_compiled": True,
    })
    still_reference.mark_motion_complete(scene)
    json.dump(script, open(script_path, "w"), indent=1, ensure_ascii=False)
    write_report(build_dir, script)
    print(f"motion {index}: {mode}/{recipe} -> {output}")


def adopt_stills(build_dir):
    """Turn an existing still-based build into an explicit motion build.

    This is intentionally non-generative: it discovers the approved stills and
    optional ``keyframe_NN_early/late`` continuity edits already present in the
    build directory, then records the recipe that ``compile`` should use.  The
    command is useful when upgrading an older render without changing its
    script, captions, timing, or source art.
    """
    script_path = os.path.join(build_dir, "script.json")
    script = json.load(open(script_path))
    script["max_still_source_ratio"] = DEFAULT_STILL_SOURCE_CAP
    strengths = {
        "organic": .82,
        "paper": .50,
        "screen": .58,
        "reflection": .62,
        "human": .54,
        "light": .68,
        "atmosphere": .58,
    }
    adopted = 0
    staged = 0
    for index, scene in enumerate(script.get("scenes", [])):
        still_name = f"still_{index:02d}.png"
        if not os.path.exists(os.path.join(build_dir, still_name)):
            continue
        scene["source_image"] = still_name
        recipe = infer_recipe(scene)
        scene["motion_recipe"] = recipe
        scene["motion_strength"] = strengths.get(recipe, .58)

        early_name = f"keyframe_{index:02d}_early.png"
        late_name = f"keyframe_{index:02d}_late.png"
        early = os.path.exists(os.path.join(build_dir, early_name))
        late = os.path.exists(os.path.join(build_dir, late_name))
        keyframes = ([early_name] if early else []) + [still_name] + (
            [late_name] if late else []
        )
        if early or late:
            scene["keyframes"] = keyframes
            scene["motion_mode"] = "keyframes"
            staged += 1
        else:
            scene.pop("keyframes", None)
            scene["motion_mode"] = "cinemagraph"
        scene["motion_kind"] = ANIMATED
        scene.pop("motion_compiled", None)
        adopted += 1

    json.dump(script, open(script_path, "w"), indent=1, ensure_ascii=False)
    result = write_report(build_dir, script)
    print(f"adopted {adopted} stills ({staged} staged transformations); "
          f"still-source budget {result.still_source_ratio:.1%}/"
          f"{result.max_still_source_ratio:.0%}")


def plan_mix(build_dir, still_indexes):
    """Reserve approved still-derived beats and route every other scene to stock.

    ``still_indexes`` is an explicit editorial decision, not an optimizer: the
    strongest metaphor/tableau beats stay animated while ordinary physical
    actions are guaranteed to request genuine footage.
    """
    script_path = os.path.join(build_dir, "script.json")
    script = json.load(open(script_path))
    keep = {int(index) for index in still_indexes}
    script["max_still_source_ratio"] = DEFAULT_STILL_SOURCE_CAP
    for index, scene in enumerate(script.get("scenes", [])):
        if index in keep:
            scene["motion_kind"] = ANIMATED
            if not scene.get("motion_mode"):
                scene["motion_mode"] = "cinemagraph"
            local_clip = os.path.join(build_dir, f"clip_{index:02d}.mp4")
            if os.path.exists(local_clip):
                scene["clip"] = local_clip
            continue
        for field in (
            "source_image", "keyframes", "motion_strength", "motion_recipe",
            "motion_compiled", "hero_generated", "hero", "clip",
        ):
            scene.pop(field, None)
        scene["motion_kind"] = VIDEO
        scene["motion_mode"] = "stock"
        scene["motion_source"] = "pending_stock"

    json.dump(script, open(script_path, "w"), indent=1, ensure_ascii=False)
    result = validate_budget(script)
    write_report(build_dir, script)
    still_seconds = result.static_seconds + result.animated_seconds
    print(
        f"mix planned: {len(keep)} animated still scenes, "
        f"{still_seconds:.1f}s/{result.total_seconds:.1f}s "
        f"({result.still_source_ratio:.1%}); true-motion target "
        f"{result.video_ratio:.1%}"
    )


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    if len(argv) < 2:
        raise SystemExit(
            "usage: motion.py <adopt-stills|plan-mix|compile|compile-all|"
            "report|validate> "
            "<build_dir> [scene]"
        )
    command, build_dir = argv[:2]
    script = json.load(open(os.path.join(build_dir, "script.json")))
    if command == "compile":
        if len(argv) < 3:
            raise SystemExit("compile requires a scene index")
        compile_scene(build_dir, int(argv[2]))
    elif command == "compile-all":
        for index, scene in enumerate(script.get("scenes", [])):
            if needs_compile(build_dir, scene, index):
                compile_scene(build_dir, index)
        final_script = json.load(open(os.path.join(build_dir, "script.json")))
        result = validate_budget(final_script)
        write_report(build_dir, final_script)
        print(f"motion compile complete: still-derived "
              f"{result.still_source_ratio:.1%} "
              f"<= {result.max_still_source_ratio:.0%}")
    elif command == "adopt-stills":
        adopt_stills(build_dir)
    elif command == "plan-mix":
        if len(argv) < 3:
            raise SystemExit("plan-mix requires comma-separated still scene indexes")
        plan_mix(build_dir, [x for x in argv[2].split(",") if x.strip()])
    elif command == "report":
        result = write_report(build_dir, script)
        print(json.dumps(result.as_dict(), indent=2))
    elif command == "validate":
        result = validate_budget(script)
        write_report(build_dir, script)
        print(f"motion budget passes: still-derived "
              f"{result.still_source_ratio:.1%} "
              f"<= {result.max_still_source_ratio:.0%}")
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()


def scene_visual_fingerprint(scene):
    """Hash of the fields that define what a scene's clip should LOOK like.

    Cached/committed clip files are only trusted when the recorded fingerprint
    matches, so a stale clip from an earlier scene definition (e.g. restored by
    the CI footage cache) can never silently stand in for a revised visual."""
    import hashlib as _hashlib
    import json as _json
    payload = {key: scene.get(key) for key in (
        "hero", "hero_style", "image_prompt", "query", "symbol_query",
        "pexels_id", "stock_id", "narrative_mode",
    )}
    if scene.get("hero") or scene.get("hero_style") or scene.get("image_prompt"):
        # Still-derived clips also depend on the motion engine version; stock
        # footage does not, so its cache identity is left untouched.
        payload["motion_3d_version"] = MOTION_3D_VERSION
    return _hashlib.sha256(
        _json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()[:16]


# Standing rule (James, photoreal era): generated stills are PHOTOGRAPHS of
# the impossible — documentary magical realism, engineered for deep parallax.
# Full doctrine: pipeline/PHOTOREAL_STYLE.md
EFFECTS_STILL_STYLE = (
    ", cinematic 35mm film still, photorealistic, anamorphic lens character, "
    "shallow depth of field with a real out-of-focus foreground element close "
    "to camera, subject in the middle distance, deep background falling into "
    "atmospheric haze, one motivated practical light source, natural surface "
    "textures and small real-world imperfections, fine film grain, muted "
    "filmic color grade, exactly one impossible element photographed as "
    "physically real and lit by the scene's own light, documentary magical "
    "realism, deep three-plane composition, "
    "no text, no words, no letters, no captions, no labels, no diagrams, "
    "no watermark, not an illustration, not digital art"
)
