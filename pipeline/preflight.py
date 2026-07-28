"""Mandatory render-readiness preflight.

This runs before ``render.yml`` is dispatched. It reuses the same canonical
profile and visual-symbol logic as production, applies only bounded safe fixes,
and blocks deterministic package defects before they consume a render runner.

Usage:
    python3 pipeline/preflight.py build/<slug> --fix-safe --record
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

import animation_profiles
import profiles
import visual_symbols
from governor import failure_fingerprint
import operational_memory

SCHEMA_VERSION = 1


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", str(text).lower())


def narration_fingerprint(script: dict) -> str:
    text = "\n".join(str(scene.get("text") or "") for scene in script.get("scenes") or [])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _block(code: str, message: str, *, stage: str = "preflight", store=None) -> dict[str, Any]:
    fingerprint = failure_fingerprint(stage, "failure", message)
    matched = operational_memory.match_solutions(
        code=code,
        fingerprint=fingerprint,
        message=message,
        store=store or operational_memory.DEFAULT_STORE,
    )
    return {
        "code": code,
        "stage": stage,
        "message": message,
        "fingerprint": fingerprint,
        "matched_solution_ids": matched,
    }


def _planned_still(scene: dict, script: dict) -> bool:
    if scene.get("motion_kind") == "video" or scene.get("motion_mode") in {
        "stock", "video", "generated_temporal_video", "limited_2_5d", "local_i2v", "paid_i2v"
    }:
        return False
    if script.get("cartoon_only") and (
        script.get("generated_temporal_video_required")
        or script.get("cartoon_render_mode") in {"limited_2_5d", "local_i2v", "paid_i2v"}
    ):
        return False
    return bool(
        scene.get("hero")
        or scene.get("narrative_mode") == "hero"
        or scene.get("source_image")
        or scene.get("keyframes")
        or scene.get("motion_kind") in {"animated_still", "still", "cinemagraph"}
    )


def _still_budget(script: dict) -> dict[str, Any]:
    scenes = script.get("scenes") or []
    wps = max(float(script.get("estimated_words_per_second") or 2.1), 0.2)
    weights: list[float] = []
    still_weights: list[float] = []
    still_indexes: list[int] = []
    used_exact_durations = True
    for index, scene in enumerate(scenes):
        raw_duration = scene.get("duration")
        if isinstance(raw_duration, (int, float)) and float(raw_duration) > 0:
            weight = float(raw_duration)
        else:
            used_exact_durations = False
            word_count = max(1, len(str(scene.get("text") or "").split()))
            weight = max(0.75, word_count / wps)
        weights.append(weight)
        if _planned_still(scene, script):
            still_weights.append(weight)
            still_indexes.append(index)
    total = sum(weights) or 1.0
    ratio = sum(still_weights) / total
    cap = float(script.get("max_still_source_ratio") or 1.0)
    return {
        "estimated_ratio": round(ratio, 6),
        "cap": round(cap, 6),
        "still_scene_indexes": still_indexes,
        "used_exact_durations": used_exact_durations,
        "passed": ratio <= cap + 1e-9,
    }


def _source_narration_check(build_dir: Path, script: dict) -> dict[str, Any]:
    source = build_dir / "source-narration.txt"
    if not script.get("source_script_verbatim") or not source.exists():
        return {"applicable": False, "passed": True}
    expected = _tokens(source.read_text(encoding="utf-8"))
    actual = _tokens(" ".join(str(scene.get("text") or "") for scene in script.get("scenes") or []))
    return {
        "applicable": True,
        "passed": expected == actual,
        "source_token_count": len(expected),
        "scene_token_count": len(actual),
    }


def _hero_readiness(build_dir: Path, script: dict) -> dict[str, Any]:
    policy = str(script.get("hero_art_policy") or "").strip()
    if policy in {"", "motion_only_no_static_hero"}:
        return {"applicable": False, "passed": True, "policy": policy or None}
    package = {}
    status_path = build_dir / "package-status.json"
    if status_path.exists():
        try:
            package = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            package = {}
    committed = any((build_dir / name).exists() for name in ("hero.png", "hero.jpg", "hero.webp"))
    runtime = package.get("hero_art_mode") == "runtime_scene_generation"
    scene_prompts = any(scene.get("image_prompt") for scene in script.get("scenes") or [])
    passed = committed or (runtime and scene_prompts)
    return {
        "applicable": True,
        "passed": passed,
        "policy": policy,
        "committed_hero": committed,
        "runtime_scene_generation": runtime,
        "scene_prompt_count": sum(1 for scene in script.get("scenes") or [] if scene.get("image_prompt")),
    }


def _canonical_voice(script: dict, profile: str | None, fix_safe: bool) -> tuple[list[str], list[dict[str, Any]]]:
    applied: list[str] = []
    blockers: list[dict[str, Any]] = []
    if not profile:
        return applied, blockers
    bible = profiles.character_bible(profile)
    voice = bible.get("voice") if isinstance(bible, dict) else None
    if not isinstance(voice, dict):
        blockers.append(_block(
            "character_voice_missing_from_bible",
            f"Character profile {profile!r} has no canonical voice record.",
        ))
        return applied, blockers
    voice_id = str(voice.get("voice_id") or "").strip()
    voice_name = str(voice.get("voice_display_name") or "").strip()
    if not voice_id:
        blockers.append(_block(
            "character_voice_missing_from_bible",
            f"Character profile {profile!r} has no canonical voice ID.",
        ))
        return applied, blockers
    existing_id = str(script.get("elevenlabs_voice_id") or "").strip()
    existing_name = str(script.get("elevenlabs_voice_name") or "").strip()
    if existing_id and existing_id != voice_id:
        blockers.append(_block(
            "character_voice_conflict",
            f"Character profile {profile!r} requires voice {voice_id}; script requested {existing_id}.",
        ))
    elif not existing_id and fix_safe:
        script["elevenlabs_voice_id"] = voice_id
        applied.append("sol-june-canonical-voice-v1")
    if existing_name and voice_name and existing_name.casefold() != voice_name.casefold():
        blockers.append(_block(
            "character_voice_name_conflict",
            f"Character profile {profile!r} requires voice name {voice_name!r}; script requested {existing_name!r}.",
        ))
    elif voice_name and not existing_name and fix_safe:
        script["elevenlabs_voice_name"] = voice_name
        if "sol-june-canonical-voice-v1" not in applied:
            applied.append("sol-june-canonical-voice-v1")
    return applied, blockers


def assess(
    build_dir: str | os.PathLike[str],
    *,
    fix_safe: bool = False,
    store: str | os.PathLike[str] = operational_memory.DEFAULT_STORE,
) -> dict[str, Any]:
    build = Path(build_dir)
    script_path = build / "script.json"
    report_path = build / "preflight-report.json"
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    applied_solution_ids: list[str] = []
    checks: dict[str, Any] = {}

    if not script_path.exists():
        report = {
            "schema_version": SCHEMA_VERSION,
            "slug": build.name,
            "passed": False,
            "blockers": [_block("missing_script", f"No script.json at {script_path}", store=store)],
            "warnings": [],
            "checks": {},
            "applied_solution_ids": [],
            "matched_solution_ids": operational_memory.match_solutions(code="missing_script", message="no script.json", store=store),
        }
        _atomic_json(report_path, report)
        return report

    try:
        original = json.loads(script_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report = {
            "schema_version": SCHEMA_VERSION,
            "slug": build.name,
            "passed": False,
            "blockers": [_block("invalid_script_json", f"script.json is invalid: {exc}", store=store)],
            "warnings": [],
            "checks": {},
            "applied_solution_ids": [],
            "matched_solution_ids": operational_memory.match_solutions(code="invalid_script_json", message=str(exc), store=store),
        }
        _atomic_json(report_path, report)
        return report

    script = copy.deepcopy(original)
    original_narration = [str(scene.get("text") or "") for scene in script.get("scenes") or []]
    slug = str(script.get("slug") or build.name)
    if not script.get("title") or not script.get("slug"):
        blockers.append(_block("missing_title_or_slug", "script.json must contain title and slug", store=store))
    # build.py hard-fails any scene text over 220 characters. Catch it here, at
    # zero cost, instead of discovering it mid-render after paid TTS/footage work.
    overlong = [
        (index, len(str(scene.get("text") or "")))
        for index, scene in enumerate(script.get("scenes") or [])
        if len(str(scene.get("text") or "")) > 220
    ]
    if overlong:
        detail = ", ".join(f"scene {index} is {length} chars" for index, length in overlong[:5])
        blockers.append(_block(
            "scene_text_too_long",
            f"scene text must be 220 characters or fewer ({detail}); split on a sentence boundary",
            store=store,
        ))
    if script.get("slug") and script.get("slug") != build.name:
        blockers.append(_block(
            "slug_directory_mismatch",
            f"script slug {script.get('slug')!r} does not match build directory {build.name!r}",
            store=store,
        ))
    scenes = script.get("scenes") or []
    if not scenes:
        blockers.append(_block("missing_scenes", "script contains no scenes", store=store))
    elif any(not str(scene.get("text") or "").strip() for scene in scenes):
        blockers.append(_block("empty_scene_text", "every scene must contain narration text", store=store))

    if script.get("title_mode") == "standalone" and script.get("series_label") not in {None, "", "null"}:
        if fix_safe:
            script["series_label"] = None
            applied_solution_ids.append("sol-standalone-title-eyebrow-v1")
        else:
            blockers.append(_block(
                "standalone_series_label",
                "Standalone video still contains a series label; remove it before render.",
                store=store,
            ))

    try:
        character_profile = profiles.resolve(script, strict=True)
    except ValueError as exc:
        character_profile = None
        blockers.append(_block("unknown_character_profile", str(exc), store=store))

    voice_applied, voice_blockers = _canonical_voice(script, character_profile, fix_safe)
    applied_solution_ids.extend(voice_applied)
    blockers.extend(voice_blockers)

    try:
        animation_name = animation_profiles.resolve(script, strict=True)
        if animation_name and fix_safe:
            if animation_profiles.apply_defaults(script, character_profile=character_profile, strict=True):
                applied_solution_ids.append("sol-june-scene-character-scope-v1" if character_profile == profiles.JUNE_OXLEY else "sol-animation-contract-preflight-v1")
        animation_errors = animation_profiles.validate(script, character_profile)
        for error in animation_errors:
            blockers.append(_block("animation_contract_invalid", error, store=store))
        checks["animation_contract"] = {
            "profile": animation_name,
            "passed": not animation_errors,
            "errors": animation_errors,
        }
    except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        blockers.append(_block("animation_contract_invalid", str(exc), store=store))
        checks["animation_contract"] = {"passed": False, "errors": [str(exc)]}

    if fix_safe:
        visual_symbols.apply_plan(script, character_profile)
    symbol_report = visual_symbols.analyze(script, character_profile)
    checks["visual_symbols"] = symbol_report
    for violation in symbol_report.get("violations") or []:
        blockers.append(_block("visual_symbol_plan", str(violation), store=store))
    for warning in symbol_report.get("warnings") or []:
        warnings.append({"code": "visual_symbol_warning", "message": str(warning)})

    still = _still_budget(script)
    checks["planned_still_budget"] = still
    if not still["passed"]:
        blockers.append(_block(
            "planned_still_budget",
            f"Planned still-derived footage is {still['estimated_ratio']:.1%}; cap is {still['cap']:.1%}. "
            f"Convert enough hero/still scenes to genuine motion before dispatch.",
            store=store,
        ))
    elif not still["used_exact_durations"] and still["estimated_ratio"] >= max(0.0, still["cap"] - 0.03):
        warnings.append({
            "code": "still_budget_near_cap",
            "message": f"Estimated still ratio {still['estimated_ratio']:.1%} is within 3 points of the cap; exact narration timing may push it over.",
        })

    source_check = _source_narration_check(build, script)
    checks["source_narration"] = source_check
    if not source_check["passed"]:
        blockers.append(_block(
            "source_narration_mismatch",
            "Scene narration no longer matches source-narration.txt token-for-token.",
            store=store,
        ))

    hero = _hero_readiness(build, script)
    checks["hero_readiness"] = hero
    if not hero["passed"]:
        blockers.append(_block(
            "hero_art_not_ready",
            "Hero-art policy requires committed art or an explicitly approved runtime scene-generation mode.",
            store=store,
        ))

    if [str(scene.get("text") or "") for scene in script.get("scenes") or []] != original_narration:
        blockers.append(_block(
            "preflight_modified_narration",
            "A safe preflight operation attempted to alter narration; refusing the change.",
            store=store,
        ))
        script["scenes"] = original["scenes"]

    changed = script != original
    if changed and fix_safe and not any(item["code"] == "preflight_modified_narration" for item in blockers):
        script_path.write_text(json.dumps(script, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    matched_solution_ids = sorted(set(
        solution_id
        for blocker in blockers
        for solution_id in blocker.get("matched_solution_ids") or []
    ))
    report = {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "title": script.get("title"),
        "passed": not blockers,
        "fix_safe": fix_safe,
        "script_changed": changed and fix_safe,
        "narration_fingerprint": narration_fingerprint(script),
        "scene_count": len(scenes),
        "word_count": sum(len(str(scene.get("text") or "").split()) for scene in scenes),
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "applied_solution_ids": sorted(set(applied_solution_ids)),
        "matched_solution_ids": matched_solution_ids,
        "prevention_rule_version": 1,
    }
    _atomic_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir")
    parser.add_argument("--fix-safe", action="store_true")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--store", default=str(operational_memory.DEFAULT_STORE))
    args = parser.parse_args(argv)

    report = assess(args.build_dir, fix_safe=args.fix_safe, store=args.store)
    if args.record:
        operational_memory.record_preflight(
            args.build_dir,
            github_run_id=os.environ.get("GITHUB_RUN_ID"),
            commit_sha=os.environ.get("GITHUB_SHA"),
            store=args.store,
        )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        state = "READY" if report["passed"] else "BLOCKED"
        print(f"PREFLIGHT {state}: {report['slug']}")
        for item in report["blockers"]:
            print(f"- BLOCK {item['code']}: {item['message']}")
        for item in report["warnings"]:
            print(f"- WARN {item['code']}: {item['message']}")
        for solution_id in report["applied_solution_ids"]:
            print(f"- SAFE FIX: {solution_id}")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
