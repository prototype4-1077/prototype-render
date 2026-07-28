"""Curated Pexels photo slides with restrained cinematic motion.

Usage:
    python3 stock_slides.py <build_dir> render-all
    python3 stock_slides.py <build_dir> render <scene-index>
    python3 stock_slides.py <build_dir> audit

This renderer intentionally produces photographic slides, not procedural graphics.
Each scene is assembled from one or two high-resolution licensed stock photos with
slow Ken Burns movement and a short dissolve. Selection metadata and attribution
are written beside the build for review.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re

from video_format import ENCODE_QUALITY, COLOR_TAGS
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

WIDTH, HEIGHT, FPS = 1920, 1080, 30
TRANSITION = 0.65
API = "https://api.pexels.com/v1/search"
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "in", "into", "is", "it", "of", "on", "or", "the", "their", "to",
    "with", "realistic", "cinematic", "editorial", "photo", "photography", "stock",
    "adult", "people", "person", "scene", "image", "quiet", "subtle", "natural",
}


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            "command failed: " + " ".join(command) + "\n" +
            ((result.stderr or result.stdout)[-1800:])
        )
    return result


def terms(value: str) -> set[str]:
    return {
        token.lower() for token in re.findall(r"[A-Za-z][A-Za-z'-]+", value or "")
        if len(token) > 2 and token.lower() not in STOP
    }


def request_json(url: str, api_key: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": api_key,
            "User-Agent": "TikTok-Video-Pipeline/stock-slides",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def search(query: str, api_key: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "query": query,
        "orientation": "landscape",
        "size": "large",
        "per_page": 30,
        "locale": "en-US",
    })
    payload = request_json(f"{API}?{params}", api_key)
    return list(payload.get("photos") or [])


def score(photo: dict[str, Any], query: str, used: set[int], avoid: set[str]) -> float:
    pid = int(photo.get("id") or 0)
    if not pid or pid in used:
        return -1e9
    width = float(photo.get("width") or 0)
    height = float(photo.get("height") or 1)
    if width < 1600 or height < 900:
        return -1e6
    text = " ".join([
        str(photo.get("alt") or ""),
        str(photo.get("url") or ""),
        str(photo.get("photographer") or ""),
    ])
    pterms = terms(text)
    qterms = terms(query)
    overlap = len(pterms & qterms)
    avoid_hits = len(pterms & avoid)
    ratio = width / max(height, 1.0)
    ratio_score = max(0.0, 1.0 - abs(ratio - 16 / 9) / 1.5)
    pixels = min(width * height / 1_000_000, 30.0)
    return overlap * 12.0 + ratio_score * 5.0 + pixels * 0.18 - avoid_hits * 18.0


def choose(scene: dict[str, Any], api_key: str, used: set[int], count: int) -> list[dict[str, Any]]:
    queries = [scene.get("stock_query") or scene.get("query") or scene.get("text")]
    queries.extend(scene.get("stock_query_fallbacks") or [])
    avoid = terms(" ".join(scene.get("avoid_terms") or []))
    ranked: list[tuple[float, dict[str, Any]]] = []
    seen: set[int] = set()
    for query in queries:
        for photo in search(str(query), api_key):
            pid = int(photo.get("id") or 0)
            if pid in seen:
                continue
            seen.add(pid)
            ranked.append((score(photo, str(query), used, avoid), photo))
    ranked.sort(key=lambda row: row[0], reverse=True)
    selected = [photo for value, photo in ranked if value > -1000][:count]
    if len(selected) < count:
        raise RuntimeError(
            f"only {len(selected)} usable Pexels photos for: {queries[0]!r}"
        )
    used.update(int(photo["id"]) for photo in selected)
    return selected


def download(url: str, output: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read(35 * 1024 * 1024)
    partial = output.with_suffix(output.suffix + ".part")
    partial.write_bytes(raw)
    with Image.open(partial) as image:
        image.verify()
    partial.replace(output)


def prepare(source: Path, output: Path) -> None:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image = ImageOps.fit(
        image,
        (2560, 1440),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.47),
    )
    image = ImageEnhance.Color(image).enhance(0.93)
    image = ImageEnhance.Contrast(image).enhance(1.055)
    image = ImageEnhance.Sharpness(image).enhance(1.08)
    image = ImageEnhance.Brightness(image).enhance(0.985)
    image.save(output, quality=96, subsampling=0, optimize=True)


def duration(path: Path) -> float:
    value = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ]).stdout.strip()
    return float(value)


def motion_filter(style: int, seconds: float) -> str:
    frames = max(int(math.ceil(seconds * FPS)), 1)
    if style % 4 == 0:
        z = "min(1.065,1.0+on*0.00042)"
        x = "iw/2-(iw/zoom/2)"
        y = f"ih/2-(ih/zoom/2)-12+24*on/{frames}"
    elif style % 4 == 1:
        z = "1.055"
        x = f"(iw-iw/zoom)*on/{frames}"
        y = "ih/2-(ih/zoom/2)"
    elif style % 4 == 2:
        z = "max(1.0,1.065-on*0.00040)"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    else:
        z = "1.055"
        x = f"(iw-iw/zoom)*(1-on/{frames})"
        y = "ih/2-(ih/zoom/2)+8*sin(on/45)"
    return (
        "scale=2560:1440:force_original_aspect_ratio=increase,"
        "crop=2560:1440,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={WIDTH}x{HEIGHT}:fps={FPS},"
        "eq=contrast=1.02:saturation=0.97:brightness=-0.004,"
        "vignette=angle=PI/7.5,noise=alls=1.4:allf=t+u,format=yuv420p"
    )


def render_photo(image: Path, seconds: float, output: Path, style: int) -> None:
    run([
        "ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(FPS),
        "-i", str(image), "-vf", motion_filter(style, seconds), "-t", f"{seconds:.4f}",
        "-an", "-c:v", "libx264", *ENCODE_QUALITY, *COLOR_TAGS,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ])


def combine(parts: list[Path], total: float, output: Path) -> None:
    if len(parts) == 1:
        run([
            "ffmpeg", "-v", "error", "-y", "-i", str(parts[0]), "-t", f"{total:.4f}",
            "-c", "copy", str(output),
        ])
        return
    command = ["ffmpeg", "-v", "error", "-y"]
    for part in parts:
        command += ["-i", str(part)]
    chain = []
    elapsed = duration(parts[0])
    previous = "0:v"
    for index in range(1, len(parts)):
        label = f"x{index}"
        offset = max(elapsed - TRANSITION, 0.01)
        chain.append(
            f"[{previous}][{index}:v]xfade=transition=fade:duration={TRANSITION}:"
            f"offset={offset:.4f}[{label}]"
        )
        elapsed += duration(parts[index]) - TRANSITION
        previous = label
    command += [
        "-filter_complex", ";".join(chain), "-map", f"[{previous}]", "-t", f"{total:.4f}",
        "-an", "-c:v", "libx264", *ENCODE_QUALITY, *COLOR_TAGS,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ]
    run(command)


def slide_motion_evidence(path: Path) -> dict[str, Any]:
    import cv2
    import numpy as np

    capture = cv2.VideoCapture(str(path))
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if not capture.isOpened() or count < 3:
        capture.release()
        return {"passes": False, "samples": 0, "frame_difference": 0.0}
    indexes = np.linspace(max(0, int(count * .08)), max(1, int(count * .92)), 9, dtype=int)
    frames = []
    for index in indexes:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = capture.read()
        if ok:
            gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
            frames.append(gray)
    capture.release()
    values = [float(np.mean(cv2.absdiff(a, b))) for a, b in zip(frames, frames[1:])]
    median = float(np.median(values)) if values else 0.0
    return {
        "passes": bool(median >= 0.85),
        "samples": len(frames),
        "frame_difference": round(median, 4),
    }


def render_scene(build_dir: Path, index: int, api_key: str, used: set[int], manifest: dict[str, Any]) -> None:
    script_path = build_dir / "script.json"
    script = json.loads(script_path.read_text(encoding="utf-8"))
    scene = script["scenes"][index]
    total = max(float(scene["duration"]), 1.0)
    count = int(scene.get("stock_photo_count") or (2 if total >= 6.5 else 1))
    selected = choose(scene, api_key, used, count)
    raw_dir = build_dir / "stock_slides" / "raw"
    ready_dir = build_dir / "stock_slides" / "ready"
    raw_dir.mkdir(parents=True, exist_ok=True)
    ready_dir.mkdir(parents=True, exist_ok=True)

    slide_rows = []
    images = []
    for slot, photo in enumerate(selected):
        pid = int(photo["id"])
        raw = raw_dir / f"scene_{index:02d}_{slot}_{pid}.jpg"
        ready = ready_dir / f"scene_{index:02d}_{slot}_{pid}.jpg"
        source_url = (photo.get("src") or {}).get("original") or (photo.get("src") or {}).get("large2x")
        if not source_url:
            raise RuntimeError(f"Pexels photo {pid} has no downloadable source")
        if not raw.exists():
            download(str(source_url), raw)
        prepare(raw, ready)
        images.append(ready)
        slide_rows.append({
            "id": pid,
            "photographer": photo.get("photographer"),
            "photographer_url": photo.get("photographer_url"),
            "photo_url": photo.get("url"),
            "alt": photo.get("alt"),
            "source": source_url,
            "local": str(ready.relative_to(build_dir)),
        })

    with tempfile.TemporaryDirectory(prefix=f"slide-{index:02d}-") as temp:
        temp_dir = Path(temp)
        if len(images) == 1:
            lengths = [total]
        else:
            base = (total + TRANSITION * (len(images) - 1)) / len(images)
            lengths = [base] * len(images)
        parts = []
        for slot, (image, seconds) in enumerate(zip(images, lengths)):
            part = temp_dir / f"part_{slot}.mp4"
            render_photo(image, seconds, part, index * 3 + slot)
            parts.append(part)
        output = build_dir / f"clip_{index:02d}.mp4"
        combine(parts, total, output)

    evidence = slide_motion_evidence(output)
    if not evidence["passes"]:
        raise RuntimeError(f"scene {index} rendered too statically: {evidence}")
    scene.update({
        "clip": str(output),
        "motion_kind": "animated_still",
        "motion_mode": "ken_burns",
        "motion_source": "pexels_photo",
        "stock_slide_evidence": evidence,
        "stock_photo_ids": [row["id"] for row in slide_rows],
    })
    script_path.write_text(json.dumps(script, indent=1, ensure_ascii=False), encoding="utf-8")
    manifest.setdefault("scenes", {})[str(index)] = {
        "query": scene.get("stock_query"),
        "duration": total,
        "photos": slide_rows,
        "motion": evidence,
    }
    (build_dir / "stock_slides_report.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def write_credits(build_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "Photos provided by Pexels — https://www.pexels.com",
        "The following photographs were selected by the TikTok Video Pipeline:",
        "",
    ]
    seen = set()
    for scene_index, scene in sorted(manifest.get("scenes", {}).items(), key=lambda item: int(item[0])):
        for photo in scene.get("photos", []):
            pid = photo.get("id")
            if pid in seen:
                continue
            seen.add(pid)
            lines.append(
                f"Scene {int(scene_index)+1}: Photo {pid} by {photo.get('photographer')} — "
                f"{photo.get('photo_url')}"
            )
    (build_dir / "CREDITS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_all(build_dir: Path) -> None:
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("PEXELS_API_KEY is required for stock slides")
    script = json.loads((build_dir / "script.json").read_text(encoding="utf-8"))
    used: set[int] = set()
    manifest: dict[str, Any] = {
        "style": "curated editorial stock-photo slides",
        "provider": "Pexels",
        "scenes": {},
    }
    for index in range(len(script["scenes"])):
        print(f"stock slide {index + 1}/{len(script['scenes'])}", flush=True)
        render_scene(build_dir, index, api_key, used, manifest)
    write_credits(build_dir, manifest)


def audit(build_dir: Path) -> None:
    script = json.loads((build_dir / "script.json").read_text(encoding="utf-8"))
    failures = []
    report = {"scenes": {}}
    for index, scene in enumerate(script["scenes"]):
        path = build_dir / f"clip_{index:02d}.mp4"
        evidence = slide_motion_evidence(path)
        report["scenes"][str(index)] = {
            "clip": str(path),
            "duration": duration(path) if path.exists() else None,
            "motion": evidence,
            "photo_ids": scene.get("stock_photo_ids") or [],
        }
        if not evidence["passes"]:
            failures.append(index)
    (build_dir / "stock_slides_motion_audit.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    if failures:
        raise SystemExit("stock-slide motion failed: " + ", ".join(map(str, failures)))
    print(f"stock-slide motion passed for all {len(script['scenes'])} scenes")


def main(argv: list[str] | None = None) -> None:
    args = list(argv or sys.argv[1:])
    if len(args) < 2:
        raise SystemExit("usage: stock_slides.py <build_dir> <render-all|render|audit> [scene]")
    build_dir = Path(args[0])
    command = args[1]
    if command == "render-all":
        render_all(build_dir)
    elif command == "render":
        api_key = os.environ.get("PEXELS_API_KEY", "").strip()
        if not api_key:
            raise SystemExit("PEXELS_API_KEY is required")
        render_scene(build_dir, int(args[2]), api_key, set(), {"scenes": {}})
    elif command == "audit":
        audit(build_dir)
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
