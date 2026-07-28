"""Build and verify render packages from user-supplied plain-text scripts.

The raw source remains authoritative. Spoken words and punctuation are preserved
across scene segmentation; only whitespace between scene boundaries may change.
Recognized bracketed performance directions are never silently removed: the
submission must explicitly choose ``preserve`` or ``extract``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import unicodedata
from typing import Any

SCHEMA_VERSION = 1
INTAKE_VERSION = 1
LIAM_VOICE_ID = "TX3LPaxmHKxFdv7VOQHJ"
LIAM_VOICE_NAME = "Liam - Energetic, Social Media Creator"
KNOWN_PERFORMANCE_CUES = {
    "pause", "long pause", "short pause", "beat", "whisper", "whispers",
    "quietly", "softly", "thoughtful", "thoughtfully", "dry", "wry",
    "laugh", "laughs", "chuckle", "chuckles", "warm", "slow", "slower",
    "quick", "quicker", "measured", "direct", "lower", "building",
    "emphatic", "gentle", "curious", "incredulous", "serious", "playful",
}


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def canonical_spoken_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", normalized).strip()


def digest_text(text: str) -> str:
    return hashlib.sha256(canonical_spoken_text(text).encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()).strip("-")
    return slug or "user-script"


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", canonical_spoken_text(text))


def _recognized_tag(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return normalized in KNOWN_PERFORMANCE_CUES or any(
        cue in normalized for cue in ("pause", "whisper", "chuckle", "laugh", "thought", "slow", "quick")
    )


def extract_performance_tags(raw: str, policy: str | None) -> tuple[str, list[str], list[str]]:
    tags = [match.group(1).strip() for match in re.finditer(r"\[([^\[\]]{1,80})\]", raw)]
    recognized = [tag for tag in tags if _recognized_tag(tag)]
    warnings: list[str] = []
    if recognized and policy not in {"preserve", "extract"}:
        raise ValueError(
            "Recognized bracketed performance directions were found. Set "
            "submission.json performance_tag_policy to 'extract' (keep them out of captions) "
            "or 'preserve' (treat them as spoken text)."
        )
    if policy == "extract":
        spoken = re.sub(
            r"\[([^\[\]]{1,80})\]",
            lambda match: " " if _recognized_tag(match.group(1)) else match.group(0),
            raw,
        )
        if tags and len(recognized) != len(tags):
            warnings.append("Unrecognized bracketed text was preserved as spoken narration.")
        return spoken, recognized, warnings
    return raw, [], warnings


def _atomic_units(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    units: list[str] = []
    for paragraph in paragraphs or [text.strip()]:
        pieces = [
            piece.strip()
            for piece in re.split(r"(?<=[.!?…])\s+", paragraph)
            if piece.strip()
        ]
        units.extend(pieces or [paragraph])
    return units


def segment_text(text: str, target_scenes: int | None = None) -> list[str]:
    spoken = canonical_spoken_text(text)
    if not spoken:
        raise ValueError("The submitted script contains no spoken narration.")
    count = len(_words(spoken))
    desired = target_scenes or int(round(count / 14.0))
    desired = max(3, min(32, desired))
    desired = min(desired, max(1, count))
    units = _atomic_units(text)

    expanded: list[str] = []
    target_words = max(5, int(math.ceil(count / desired)))
    for unit in units:
        words = _words(unit)
        if len(words) <= max(target_words * 2, 28):
            expanded.append(canonical_spoken_text(unit))
            continue
        clauses = [part.strip() for part in re.split(r"(?<=[,;:—–])\s+", unit) if part.strip()]
        if len(clauses) > 1:
            expanded.extend(canonical_spoken_text(part) for part in clauses)
        else:
            expanded.extend(" ".join(words[index:index + target_words]) for index in range(0, len(words), target_words))

    scenes: list[str] = []
    current: list[str] = []
    current_words = 0
    remaining_words = sum(len(_words(unit)) for unit in expanded)
    for index, unit in enumerate(expanded):
        unit_words = len(_words(unit))
        remaining_slots = max(1, desired - len(scenes))
        dynamic_target = max(5, int(math.ceil((remaining_words + current_words) / remaining_slots)))
        if current and current_words + unit_words > dynamic_target * 1.25 and len(scenes) < desired - 1:
            scenes.append(canonical_spoken_text(" ".join(current)))
            current = []
            current_words = 0
        current.append(unit)
        current_words += unit_words
        remaining_words -= unit_words
    if current:
        scenes.append(canonical_spoken_text(" ".join(current)))

    while len(scenes) > desired:
        best = min(range(len(scenes) - 1), key=lambda i: len(_words(scenes[i])) + len(_words(scenes[i + 1])))
        scenes[best:best + 2] = [canonical_spoken_text(scenes[best] + " " + scenes[best + 1])]
    return [scene for scene in scenes if scene]


def _scene_query(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9']+", text)
    return " ".join(words[:20]) or "literal moving visual matching narration"


def _visual_function(index: int, count: int) -> str:
    if index == 0:
        return "hook"
    if index == count - 1:
        return "invitation"
    fraction = index / max(count - 1, 1)
    if fraction < 0.48:
        return "mechanism"
    if fraction < 0.78:
        return "turn"
    return "grounding"


def load_submission(build: Path) -> dict[str, Any]:
    path = build / "submission.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("submission.json must contain one JSON object.")
    return payload


def build_package(build_dir: str | os.PathLike[str], *, overwrite: bool = False) -> dict[str, Any]:
    build = Path(build_dir)
    build.mkdir(parents=True, exist_ok=True)
    source = build / "source-script.txt"
    if not source.exists():
        raise FileNotFoundError(f"Missing authoritative user script: {source}")
    submission = load_submission(build)
    script_path = build / "script.json"
    if script_path.exists() and not overwrite:
        existing = json.loads(script_path.read_text(encoding="utf-8"))
        if existing.get("script_origin") != "user_supplied_plain_text":
            raise FileExistsError("Refusing to overwrite a non-intake script.json. Use an isolated slug.")
        raise FileExistsError("script.json already exists. Re-run with --overwrite only after reviewing the source change.")

    raw = source.read_text(encoding="utf-8")
    performance_policy = submission.get("performance_tag_policy")
    spoken, extracted_tags, warnings = extract_performance_tags(raw, performance_policy)
    canonical = canonical_spoken_text(spoken)
    if not canonical:
        raise ValueError("No spoken narration remains after performance-tag handling.")
    spoken_source = build / "source-spoken.txt"
    spoken_source.write_text(canonical + "\n", encoding="utf-8")

    title = str(submission.get("title") or "").strip()
    if not title:
        first = re.split(r"[.!?]", canonical, maxsplit=1)[0].strip()
        title = " ".join(first.split()[:10]) or "Untitled Script"
    slug = build.name
    declared_slug = str(submission.get("slug") or slug)
    if slugify(declared_slug) != slug:
        raise ValueError(f"submission slug {declared_slug!r} does not match build directory {slug!r}")

    target_scenes = submission.get("target_scenes")
    if target_scenes is not None:
        target_scenes = int(target_scenes)
        if not 3 <= target_scenes <= 40:
            raise ValueError("target_scenes must be between 3 and 40.")
    segments = segment_text(spoken, target_scenes)
    scene_count = len(segments)
    fidelity = str(submission.get("science_fidelity") or "unspecified")
    epistemic_role = "metaphor" if fidelity == "metaphor" else "interpretation"
    scenes = []
    for index, text in enumerate(segments):
        scene = {
            "text": text,
            "epistemic_role": epistemic_role,
            "semantic_anchor": text,
            "visual_function": _visual_function(index, scene_count),
            "narrative_mode": "stock_ok",
            "query": _scene_query(text),
            "motion_kind": "video",
            "motion_mode": "stock",
        }
        if extracted_tags and index == 0:
            scene["audio_tags"] = extracted_tags
        scenes.append(scene)

    wps = max(0.5, float(submission.get("estimated_words_per_second") or 2.1))
    word_count = len(_words(canonical))
    visual_policy = submission.get("visual_policy")
    if not isinstance(visual_policy, dict):
        visual_policy = {
            "mode": "diverse_symbols",
            "max_human_ratio": 0.70,
            "max_family_run": 6,
            "max_generic_human_run": 1,
            "min_families": min(4, max(3, scene_count // 5)),
        }
    script: dict[str, Any] = {
        "title": title,
        "slug": slug,
        "series_label": submission.get("series_label"),
        "title_mode": submission.get("title_mode") or ("series_episode" if submission.get("series_label") else "standalone"),
        "genre": submission.get("genre") or "concept",
        "science_fidelity": fidelity,
        "script_origin": "user_supplied_plain_text",
        "intake_version": INTAKE_VERSION,
        "supplied_script": True,
        "source_script_verbatim": True,
        "source_script_filename": "source-spoken.txt",
        "source_script_sha256": digest_text(canonical),
        "raw_source_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "performance_tag_policy": performance_policy or "none_detected",
        "extracted_performance_tags": extracted_tags,
        "estimated_words_per_second": wps,
        "target_duration_seconds": round(word_count / wps, 3),
        "render_outputs": submission.get("render_outputs") or ["youtube"],
        "auto_audio_tags": False,
        "caption_policy": submission.get("caption_policy") or "minimal_keywords_only",
        "visual_policy": visual_policy,
        "max_still_source_ratio": float(submission.get("max_still_source_ratio") or 0.50),
        "still_image_policy": submission.get("still_image_policy") or "closest_stock_frame_full_enhancement",
        "hero_art_policy": submission.get("hero_art_policy") or "motion_only_no_static_hero",
        "scenes": scenes,
    }
    profile = submission.get("profile")
    if profile:
        script["profile"] = profile
    animation = submission.get("animation_profile")
    if animation:
        script["animation_profile"] = animation
    for key in ("elevenlabs_voice_id", "elevenlabs_voice_name", "elevenlabs_model", "voice_settings", "voice_standard", "user_vo"):
        if key in submission:
            script[key] = submission[key]
    if not profile and "elevenlabs_voice_id" not in script:
        script.update({
            "elevenlabs_model": submission.get("elevenlabs_model") or "eleven_v3",
            "elevenlabs_voice_id": LIAM_VOICE_ID,
            "elevenlabs_voice_name": LIAM_VOICE_NAME,
            "voice_settings": submission.get("voice_settings") or {"similarity_boost": 0.75, "speed": 0.94},
        })

    script_path.write_text(json.dumps(script, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    report = verify_lock(build)
    report.update({
        "schema_version": SCHEMA_VERSION,
        "status": "packaged" if report["passed"] else "failed",
        "scene_count": scene_count,
        "word_count": word_count,
        "target_duration_seconds": script["target_duration_seconds"],
        "warnings": warnings,
        "extracted_performance_tags": extracted_tags,
        "authority_boundary": "Narration and punctuation are locked. Visual planning, timing, captions, and audio delivery may be added without rewriting spoken text.",
    })
    atomic_json(build / "intake-report.json", report)
    if not report["passed"]:
        raise RuntimeError("User script round-trip verification failed.")
    return report


def verify_lock(build_dir: str | os.PathLike[str]) -> dict[str, Any]:
    build = Path(build_dir)
    script_path = build / "script.json"
    if not script_path.exists():
        return {"passed": False, "reason": "missing_script", "message": "script.json does not exist"}
    script = json.loads(script_path.read_text(encoding="utf-8"))
    source_name = str(script.get("source_script_filename") or "source-script.txt")
    source = build / source_name
    if not source.exists():
        return {"passed": False, "reason": "missing_source", "message": f"authoritative source file is missing: {source_name}"}
    expected = canonical_spoken_text(source.read_text(encoding="utf-8"))
    actual = canonical_spoken_text(" ".join(str(scene.get("text") or "") for scene in script.get("scenes") or []))
    expected_sha = digest_text(expected)
    actual_sha = digest_text(actual)
    declared_sha = str(script.get("source_script_sha256") or "")
    passed = expected == actual and (not declared_sha or declared_sha == expected_sha)
    return {
        "passed": passed,
        "reason": None if passed else "narration_mismatch",
        "source_file": source_name,
        "source_sha256": expected_sha,
        "scene_narration_sha256": actual_sha,
        "declared_source_sha256": declared_sha or None,
        "source_character_count": len(expected),
        "scene_character_count": len(actual),
        "message": "spoken narration matches authoritative source" if passed else "scene narration differs from authoritative source text or punctuation",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_only:
        report = verify_lock(args.build_dir)
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
        return 0 if report["passed"] else 2
    try:
        report = build_package(args.build_dir, overwrite=args.overwrite)
    except Exception as exc:
        build = Path(args.build_dir)
        atomic_json(build / "intake-report.json", {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "passed": False,
            "error": str(exc),
        })
        print(f"USER SCRIPT INTAKE BLOCKED: {exc}")
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
