"""Cluster stored feedback into provisional, human-reviewed production rules.

This tool never promotes a rule. It preserves examples, source decisions, and
counterexamples so James or a reviewed code change can decide whether a pattern
belongs in production policy.
"""
from __future__ import annotations

from collections import defaultdict
import argparse
import datetime as dt
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "pipeline" / "memory.json"
OUTPUT = ROOT / "pipeline" / "feedback_rule_candidates.json"

RULES = {
    "visual_semantic_match": {
        "title": "Visual must clearly represent the spoken concept",
        "patterns": ("does not match", "doesn't match", "unrelated", "represents what", "represent what", "reflect the concept", "wrong visual", "not what"),
    },
    "literal_action_accuracy": {
        "title": "Literal actions must visibly perform the stated action",
        "patterns": ("looks like", "doesn't look like", "does not look like", "actually walking", "painting the", "should show", "need to see"),
    },
    "graphics_quality_floor": {
        "title": "Reject low-grade or unclear generic graphics",
        "patterns": ("terrible graphics", "upgrade", "lower grade", "cheap", "bad graphic", "poor graphic", "generic graphic"),
    },
    "effects_still_preference": {
        "title": "Use a strong still with effects when stock cannot explain the beat",
        "patterns": ("still image", "special effects", "effects still", "image with effects"),
    },
    "stock_first_preference": {
        "title": "Prefer genuine moving stock when a direct match exists",
        "patterns": ("stock footage", "look for stock", "stock first", "genuine stock"),
    },
    "cartoon_animation_definition": {
        "title": "Animated requests mean coherent cartoon animation",
        "patterns": ("cartoon", "animated means", "cartoon animated"),
    },
    "scene_continuity": {
        "title": "Adjacent conceptual beats should share a coherent visual world",
        "patterns": ("same scene", "connect", "continuous", "continuity", "different world", "successive scenes"),
    },
    "character_solidity": {
        "title": "Recurring character must be solid and grounded in the scene",
        "patterns": ("ghost", "transparent", "solid", "pasted on", "floaty"),
    },
    "character_lip_sync": {
        "title": "Visible speaking character requires mouth movement",
        "patterns": ("lip", "mouth", "narrator is speaking", "when speaking"),
    },
    "deep_parallax": {
        "title": "Concept backgrounds should use strong layered depth",
        "patterns": ("coming off the page", "parallax", "3d effect", "deep 3d", "background depth"),
    },
    "title_safe_zone": {
        "title": "Titles must remain readable inside platform crop zones",
        "patterns": ("title placement", "cutting off", "cut off", "thumbnail", "safe zone", "one line"),
    },
    "caption_restraint": {
        "title": "Do not print performance tags or dense paragraph captions",
        "patterns": ("show the tags", "does not show the tags", "caption", "text box", "paragraph"),
    },
    "voice_identity": {
        "title": "Preserve the exact requested narrator and supplied audio",
        "patterns": ("exact audio", "exact supplied", "no exceptions", "voice id", "spuds", "liam fallback", "narrator voice"),
    },
    "dmt_motion_language": {
        "title": "DMT videos benefit from psychedelic moving graphics in moderation",
        "patterns": ("psychedelic moving", "dmt video", "one or two less", "moving graphics"),
    },
    "dramatic_object_specificity": {
        "title": "Use the most conceptually specific version of a physical object",
        "patterns": ("increase the dramatic effect", "highlights the point", "empty wooden", "would be better", "stronger image"),
    },
}


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def normalize(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def classify(text: str) -> list[str]:
    low = normalize(text).lower()
    return sorted(rule_id for rule_id, rule in RULES.items() if any(pattern in low for pattern in rule["patterns"]))


def source_rows(memory: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen = set()
    for item in memory.get("scene_feedback") or []:
        if not isinstance(item, dict):
            continue
        comment = normalize(item.get("comments"))
        if not comment:
            continue
        key = (item.get("slug"), item.get("scene_number"), comment)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "source": "scene_feedback",
            "slug": item.get("slug"),
            "scene_number": item.get("scene_number"),
            "decision": item.get("decision"),
            "comment": comment,
            "query": item.get("query"),
            "profile": item.get("profile"),
        })
    for note in memory.get("notes") or []:
        comment = normalize(note)
        if not comment:
            continue
        match = re.match(r"survey\(([^)]+)\)\s+(?:scene\s+(\d+)\s+)?([^:]+):\s*(.*)", comment, flags=re.I)
        if match:
            slug, scene, decision, body = match.groups()
            body = normalize(body)
        else:
            slug, scene, decision, body = None, None, None, comment
        key = (slug, int(scene) if scene else None, body)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "source": "note",
            "slug": slug,
            "scene_number": int(scene) if scene else None,
            "decision": normalize(decision).lower() if decision else None,
            "comment": body,
            "query": None,
            "profile": None,
        })
    return rows


def build(memory_path: Path = MEMORY, output: Path = OUTPUT) -> dict[str, Any]:
    memory = load(memory_path, {}) or {}
    if not isinstance(memory, dict):
        memory = {}
    rows = source_rows(memory)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    uncategorized = []
    for row in rows:
        matches = classify(row["comment"])
        if not matches:
            uncategorized.append(row)
        for rule_id in matches:
            buckets[rule_id].append(row)

    candidates = []
    for rule_id, examples in buckets.items():
        decisions = defaultdict(int)
        slugs = set()
        for item in examples:
            decisions[str(item.get("decision") or "unknown")] += 1
            if item.get("slug"):
                slugs.add(str(item["slug"]))
        candidates.append({
            "id": rule_id,
            "title": RULES[rule_id]["title"],
            "status": "provisional",
            "human_promotion_required": True,
            "evidence_count": len(examples),
            "affected_slugs": sorted(slugs),
            "decisions": dict(sorted(decisions.items())),
            "examples": examples[:12],
            "promotion_requirement": (
                "Review examples for a shared root cause, find at least one counterexample or "
                "scope boundary, then encode a regression test before production promotion."
            ),
        })
    candidates.sort(key=lambda item: (-item["evidence_count"], item["id"]))
    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source_note_count": len(memory.get("notes") or []),
        "source_scene_feedback_count": len(memory.get("scene_feedback") or []),
        "unique_commented_evidence": len(rows),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "uncategorized_count": len(uncategorized),
        "uncategorized_examples": uncategorized[:30],
        "authority_boundary": (
            "These are candidate rules, not production policy. No candidate may alter scripts, "
            "visual routing, voices, or publishing until a human reviews scope and a regression test exists."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", default=str(MEMORY))
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args(argv)
    report = build(Path(args.memory), Path(args.output))
    print(json.dumps({
        "unique_commented_evidence": report["unique_commented_evidence"],
        "candidate_count": report["candidate_count"],
        "uncategorized_count": report["uncategorized_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
