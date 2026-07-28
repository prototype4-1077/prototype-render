"""Selectable animation contracts for premium and June Oxley animated videos.

The top-level ``animation_profile`` field is independent of ``profile``:
``profile`` selects the recurring character; ``animation_profile`` selects how the
film moves and is art-directed. Unprofiled videos remain unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

ANIMATED_TIER1 = "animated_tier1"
JUNE_TIER1 = "june_oxley_animated_tier1"
JUNE_STANDARD = "june_oxley_animated_standard"
CONTRACT_VERSION = 1

_DATA = Path(__file__).with_name("animation_style_profiles.json")

_ALIASES = {
    "animated": ANIMATED_TIER1,
    "tier_1_animated": ANIMATED_TIER1,
    "tier1_animated": ANIMATED_TIER1,
    "animated_tier1": ANIMATED_TIER1,
    "premium_animated": ANIMATED_TIER1,
    "june_oxley_tier1": JUNE_TIER1,
    "tier1_june_oxley": JUNE_TIER1,
    "june_oxley_animated_tier1": JUNE_TIER1,
    "premium_june_oxley_animated": JUNE_TIER1,
    "june_oxley_animated": JUNE_STANDARD,
    "june_oxley_standard": JUNE_STANDARD,
    "june_oxley_animated_standard": JUNE_STANDARD,
    "regular_june_oxley_animated": JUNE_STANDARD,
}

_CHARACTER_ROLES = {
    "narrator", "observer", "chooser", "creator", "explorer", "guardian",
    "performer", "relationship", "collective", "scale_reference",
}
_HARD_NON_CHARACTER_ROLES = {"none", "no_human", "object", "environment"}
_NON_CHARACTER_ROLES = {"", *_HARD_NON_CHARACTER_ROLES, "unspecified"}
_CHARACTER_CUES = (
    "june oxley", "june", "earl", "clyde", "neighbor", "waitress",
    "man", "woman", "person", "people", "driver", "hand", "hands", "face",
)
_OBJECT_REWRITE_CUES = _CHARACTER_CUES + (
    "townspeople", "locals", "silhouette", "traveler", "travelers",
    "actor", "actors", "cast", "ex",
)


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def profiles() -> dict[str, dict[str, Any]]:
    payload = json.loads(_DATA.read_text(encoding="utf-8"))
    return payload["profiles"]


def resolve(script: dict | None, strict: bool = False) -> str | None:
    script = script or {}
    raw = next((script.get(k) for k in ("animation_profile", "animation_style", "animated_style")
                if script.get(k)), None)
    if raw is None:
        return None
    found = _ALIASES.get(_key(raw))
    if found is None and strict:
        choices = ", ".join(sorted(profiles()))
        raise ValueError(f"unknown animation_profile {raw!r}; supported: {choices}")
    return found


def contract(name: str | None) -> dict[str, Any] | None:
    if name is None:
        return None
    return dict(profiles()[name])


def display_name(name: str | None) -> str:
    data = contract(name)
    return data["display_name"] if data else "default"


def is_june(name: str | None) -> bool:
    return name in {JUNE_TIER1, JUNE_STANDARD}


def is_tier1(name: str | None) -> bool:
    data = contract(name)
    return bool(data and int(data["quality_tier"]) == 1)


def _append_once(text: str, suffix: str) -> str:
    base = " ".join(str(text or "").split()).strip()
    if not base:
        return suffix
    marker = suffix.split(",", 1)[0].lower()
    if marker and marker in base.lower():
        return base
    return f"{base}, {suffix}"


def _has_word(text: str, cue: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(cue)}(?![a-z0-9])", text))


def _mentions_any(text: str, cues: tuple[str, ...]) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    return any(_has_word(normalized, cue) for cue in cues)


def _scene_needs_character(scene: dict, required_character: str | None, base_query: str) -> bool:
    """Return whether the requested shot actually contains the recurring character.

    A June animation profile defines a shared town-wide art direction. It must not
    inject an elderly man into tractors, fences, squirrels, weather, or other
    object-led metaphor scenes. An explicit ``human_role: none`` is authoritative.
    """
    if not required_character:
        return False
    role = _key(scene.get("human_role") or "")
    if role in _HARD_NON_CHARACTER_ROLES:
        return False
    explicit = scene.get("animation_character_required")
    if isinstance(explicit, bool):
        return explicit
    if role in _CHARACTER_ROLES:
        return True
    if role not in _NON_CHARACTER_ROLES:
        return True
    visual = scene.get("symbol_query") or base_query or scene.get("image_prompt") or ""
    return _mentions_any(str(visual), _CHARACTER_CUES)


def _object_led_query(scene: dict) -> str:
    anchor = " ".join(str(
        scene.get("semantic_anchor") or scene.get("primary_symbol")
        or "rural visual metaphor"
    ).split())
    return (
        f"{anchor}, expressed through moving objects, architecture, weather, animals, "
        "vehicles or light in a rural setting, no people, no hands, no faces, no visible body"
    )


def _needs_object_rewrite(scene: dict, required_character: str | None,
                          character_required: bool, literal_query: str) -> bool:
    if not required_character or character_required:
        return False
    role = _key(scene.get("human_role") or "")
    return role in _HARD_NON_CHARACTER_ROLES and _mentions_any(
        literal_query, _OBJECT_REWRITE_CUES
    )


def _merge_visual_policy(script: dict, data: dict) -> bool:
    changed = False
    raw = script.get("visual_policy")
    policy = dict(raw) if isinstance(raw, dict) else {}
    desired = {
        "mode": "diverse_symbols",
        "max_human_ratio": data["max_human_ratio"],
        "max_family_run": data["max_family_run"],
        "max_generic_human_run": data["max_generic_human_run"],
        "animation_profile": script["animation_profile"],
    }
    for key, value in desired.items():
        if policy.get(key) != value:
            policy[key] = value
            changed = True
    if raw != policy:
        script["visual_policy"] = policy
        changed = True
    return changed


def apply_defaults(script: dict, character_profile: str | None = None, strict: bool = True) -> bool:
    """Apply one idempotent animation contract to a script in memory."""
    name = resolve(script, strict=strict)
    if name is None:
        return False
    data = contract(name)
    assert data is not None
    changed = False
    required_character = data.get("character_profile")
    if required_character:
        existing = character_profile or script.get("profile")
        if existing and _key(existing) not in {_key(required_character), "june_oxley"}:
            raise ValueError(
                f"animation_profile {name!r} requires profile: june_oxley; got {existing!r}"
            )
        if script.get("profile") != required_character:
            script["profile"] = required_character
            changed = True
    elif character_profile == "june_oxley":
        note = (
            "June Oxley detected with regular Tier 1 animation; use a June-specific "
            "animation profile when recurring character continuity is required."
        )
        if script.get("animation_profile_note") != note:
            script["animation_profile_note"] = note
            changed = True

    canonical = name
    desired_top = {
        "animation_profile": canonical,
        "animation_contract_version": CONTRACT_VERSION,
        "animation_quality_tier": data["quality_tier"],
        "animation_display_name": data["display_name"],
        "animation_character_reference_id": data.get("character_reference_id"),
        "animation_source_priority": data["source_priority"],
        "animation_camera_language": data["camera_language"],
        "animation_design_language": data["design_language"],
        "caption_policy": data["caption_policy"],
        "max_still_source_ratio": data["max_still_source_ratio"],
        "minimum_true_motion_ratio": data["minimum_true_motion_ratio"],
    }
    for key, value in desired_top.items():
        if value is None:
            continue
        if script.get(key) != value:
            script[key] = value
            changed = True
    changed = _merge_visual_policy(script, data) or changed

    general_suffix = data["prompt_suffix"]
    character_suffix = data.get("character_prompt_suffix") or ""
    for index, scene in enumerate(script.get("scenes") or []):
        role = _key(scene.get("human_role") or "")
        if role in _HARD_NON_CHARACTER_ROLES:
            if scene.pop("animation_character_required", None) is not None:
                changed = True
            if scene.pop("animation_character_reference_id", None) is not None:
                changed = True

        literal_query = (
            scene.get("animation_base_query") or scene.get("query")
            or scene.get("image_prompt") or scene.get("text") or ""
        )
        character_required = _scene_needs_character(
            scene, required_character, str(literal_query)
        )
        render_base = scene.get("symbol_query") or literal_query
        object_rewrite = _needs_object_rewrite(
            scene, required_character, character_required, str(render_base)
        )
        if object_rewrite:
            render_base = _object_led_query(scene)
            if scene.get("animation_object_query") != render_base:
                scene["animation_object_query"] = render_base
                changed = True
            if scene.get("symbol_query") != render_base:
                scene["symbol_query"] = render_base
                changed = True
        elif "animation_object_query" in scene:
            scene.pop("animation_object_query", None)
            changed = True

        desired_scene = {
            "animation_profile": canonical,
            "animation_quality_tier": data["quality_tier"],
            "animation_source_preference": data["source_priority"],
            "animation_camera_language": data["camera_language"],
            "animation_design_language": data["design_language"],
            "animation_scene_index": index,
            "animation_character_required": character_required,
        }
        for key, value in desired_scene.items():
            if scene.get(key) != value:
                scene[key] = value
                changed = True
        reference_id = data.get("character_reference_id") if character_required else None
        if reference_id:
            if scene.get("animation_character_reference_id") != reference_id:
                scene["animation_character_reference_id"] = reference_id
                changed = True
        elif "animation_character_reference_id" in scene:
            scene.pop("animation_character_reference_id", None)
            changed = True

        if scene.get("animation_base_query") != literal_query:
            scene["animation_base_query"] = literal_query
            changed = True
        styled = _append_once(str(render_base), general_suffix)
        if character_required and character_suffix:
            styled = _append_once(styled, character_suffix)
        if scene.get("animation_query") != styled:
            scene["animation_query"] = styled
            changed = True

        if scene.get("hero") or scene.get("image_prompt"):
            literal_prompt = (
                scene.get("animation_base_prompt") or scene.get("image_prompt")
                or literal_query
            )
            if scene.get("animation_base_prompt") != literal_prompt:
                scene["animation_base_prompt"] = literal_prompt
                changed = True
            prompt_base = render_base if object_rewrite else literal_prompt
            styled_prompt = _append_once(str(prompt_base), general_suffix)
            if character_required and character_suffix:
                styled_prompt = _append_once(styled_prompt, character_suffix)
            if scene.get("image_prompt") != styled_prompt:
                scene["image_prompt"] = styled_prompt
                changed = True

        if not scene.get("motion_kind") and scene.get("query"):
            scene["motion_kind"] = "video"
            scene.setdefault("motion_mode", "stock")
            changed = True
    return changed


def effective_query(scene: dict, name: str | None) -> str:
    if name is None:
        return str(scene.get("query") or "")
    return str(scene.get("animation_query") or scene.get("query") or "")


def hero_style(name: str | None) -> str:
    data = contract(name)
    return f", {data['prompt_suffix']}" if data else ""


def writer_context(name: str | None) -> str:
    data = contract(name)
    if not data:
        return ""
    return (
        f"ANIMATION PROFILE: {name} ({data['display_name']})\n"
        f"- Design language: {data['design_language']}\n"
        f"- Camera language: {data['camera_language']}\n"
        f"- True-motion floor: {data['minimum_true_motion_ratio']:.0%}; still-derived cap: "
        f"{data['max_still_source_ratio']:.0%}.\n"
        f"- Captions: {data['caption_policy']}.\n"
        "- Use one ruling visual system, one strong symbol per beat, and no cheap template animation.\n"
        "- Recurring-character anatomy belongs only in scenes that actually show the character.\n"
        "- A scene explicitly marked human_role: none must be rendered through objects or environment.\n"
        f"- Set top-level JSON field exactly to \"animation_profile\": \"{name}\"."
    )


def validate(script: dict, character_profile: str | None = None) -> list[str]:
    name = resolve(script, strict=True)
    if name is None:
        return []
    data = contract(name)
    assert data is not None
    errors: list[str] = []
    if script.get("animation_contract_version") != CONTRACT_VERSION:
        errors.append("animation_contract_version must be 1")
    if float(script.get("max_still_source_ratio", 1.0)) > float(data["max_still_source_ratio"]) + 1e-9:
        errors.append(
            f"{name} still-derived cap must be <= {data['max_still_source_ratio']:.0%}"
        )
    if is_june(name):
        resolved_character = character_profile or script.get("profile")
        if _key(resolved_character or "") != "june_oxley":
            errors.append(f"{name} requires profile: june_oxley")
        if script.get("animation_character_reference_id") != "june_oxley_v1":
            errors.append("June animation must lock animation_character_reference_id: june_oxley_v1")
    for index, scene in enumerate(script.get("scenes") or []):
        if scene.get("animation_profile") != name:
            errors.append(f"scene {index} missing canonical animation_profile")
        if not scene.get("animation_query"):
            errors.append(f"scene {index} missing animation_query")
        needs_character = bool(scene.get("animation_character_required"))
        has_reference = bool(scene.get("animation_character_reference_id"))
        if needs_character != has_reference and is_june(name):
            errors.append(
                f"scene {index} character/reference mismatch: "
                f"required={needs_character}, reference={has_reference}"
            )
        role = _key(scene.get("human_role") or "")
        if role in _HARD_NON_CHARACTER_ROLES and needs_character:
            errors.append(
                f"scene {index} is human_role={role} but requests the recurring character"
            )
    return errors
