#!/usr/bin/env python3
"""Score scene-generation risk and route fragile visuals away from free-form stills."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

RISK_RULES = {
    "multiple_hands": (5, (r"\btwo hands\b", r"\bboth hands\b", r"\bmultiple hands\b")),
    "hand_contact": (4, (r"hand.*(?:touch|grip|hold|strike|merge)", r"(?:touch|grip|hold|strike|merge).*hand")),
    "anatomy_transform": (5, (r"(?:hand|finger|body|face|limb).*(?:dissolv|morph|merge|becom|grow)",)),
    "reflection": (3, (r"\bmirror\b", r"\breflection\b", r"reflected (?:face|body|hand|person)")),
    "medical_contact": (4, (r"\bsurgeon\b", r"\bsurgical\b", r"\bscalpel\b", r"\bneedle\b")),
    "tool_grasp": (4, (r"(?:hand|fingers).*(?:tool|hammer|cane|blade|instrument)",)),
    "crowd_or_many_subjects": (3, (r"\bcrowd\b", r"\bseveral people\b", r"\bmany people\b")),
    "body_plus_effect": (2, (r"person.*(?:outline|glow|transparent|energy|anatomical)",)),
    "complex_simultaneity": (2, (r"\bwhile\b.*\bwhile\b", r"\bboth\b.*\band\b.*\band\b")),
}

SAFE_ROUTES = {"stock", "comfyui", "nonhuman_geometry"}


def scene_text(scene: dict[str, Any]) -> str:
    return " ".join(
        str(scene.get(key) or "")
        for key in ("semantic_anchor", "query", "image_prompt", "text", "revision_note")
    ).lower()


def assess_scene(scene: dict[str, Any], index: int = 0) -> dict[str, Any]:
    text = scene_text(scene)
    findings = []
    score = 0
    for code, (weight, patterns) in RISK_RULES.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            score += weight
            findings.append({"code": code, "weight": weight})

    constraints = [str(item).lower() for item in scene.get("generation_constraints") or []]
    safe_flag = scene.get("lower_model_safe") is True
    workflow_id = str(scene.get("comfy_workflow_id") or "")
    route = str(scene.get("generation_route") or scene.get("route") or "")
    generated = bool(scene.get("hero") or scene.get("image_prompt") or scene.get("pure_generated_still"))

    mitigations = 0
    if safe_flag:
        mitigations += 2
    if len(constraints) >= 4:
        mitigations += 2
    if workflow_id:
        mitigations += 2
    if route in SAFE_ROUTES:
        mitigations += 1
    effective = max(0, score - mitigations)

    if effective >= 7:
        recommendation = "stock_or_nonhuman_geometry"
    elif effective >= 4:
        recommendation = "constrained_comfyui_or_stock"
    else:
        recommendation = route or "normal_pipeline"

    return {
        "scene_index": index,
        "generated_candidate": generated,
        "raw_risk_score": score,
        "mitigation_score": mitigations,
        "effective_risk_score": effective,
        "findings": findings,
        "lower_model_safe": safe_flag,
        "generation_constraints": constraints,
        "comfy_workflow_id": workflow_id or None,
        "declared_route": route or None,
        "recommendation": recommendation,
        "passes_enforcement": not generated or effective < 7,
    }


def assess_script(script: dict[str, Any]) -> dict[str, Any]:
    scenes = script.get("scenes") or []
    reports = [assess_scene(scene, index) for index, scene in enumerate(scenes)]
    blocked = [item for item in reports if not item["passes_enforcement"]]
    review = [item for item in reports if item["effective_risk_score"] >= 4]
    return {
        "slug": script.get("slug"),
        "scene_count": len(scenes),
        "blocked_count": len(blocked),
        "review_count": len(review),
        "passed": not blocked,
        "blocked": blocked,
        "review": review,
        "scenes": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("script")
    parser.add_argument("--enforce", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    path = Path(args.script)
    script = json.loads(path.read_text(encoding="utf-8"))
    report = assess_script(script)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"visual risk: {report['slug']} — {report['blocked_count']} blocked, "
            f"{report['review_count']} review"
        )
        for item in report["blocked"]:
            print(
                f"BLOCK scene {item['scene_index'] + 1}: score "
                f"{item['effective_risk_score']} -> {item['recommendation']}"
            )
    return 1 if args.enforce and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
