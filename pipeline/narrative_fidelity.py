"""Narrative-match scoring for stock footage.

A beautiful or moody clip is not a valid substitute for the action, object, or
relationship named by the narration.  This module keeps that editorial rule
separate from aesthetic scoring and remembers context-specific rejections.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
EDITORIAL_MEMORY = HERE / "editorial_memory.json"

STOP = {
    "a", "an", "and", "are", "as", "at", "be", "because", "before", "but",
    "by", "cinematic", "close", "daylight", "for", "from", "genuine", "in",
    "into", "is", "it", "its", "light", "lighting", "motion", "natural", "of",
    "on", "or", "person", "people", "realistic", "scene", "shot", "the", "then",
    "this", "to", "video", "while", "with", "you", "your",
}

SYNONYMS = {
    "elderly": "old", "older": "old", "route": "path", "road": "path",
    "walkway": "path", "escalator": "path", "camera": "camera", "phone": "phone",
    "smartphone": "phone", "memo": "message", "letter": "message", "note": "message",
    "labels": "label", "tags": "label", "stamps": "stamp", "settings": "setting",
    "filters": "filter", "symbols": "symbol", "icons": "symbol", "receipts": "receipt",
}


def _stem(word: str) -> str:
    word = word.lower().strip("-_' ")
    word = SYNONYMS.get(word, word)
    if len(word) > 6 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 5 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return SYNONYMS.get(word, word)


def tokens(value: object) -> set[str]:
    words = {
        _stem(word)
        for word in re.findall(
            r"[A-Za-z][A-Za-z']+", str(value or "").replace("-", " ")
        )
    }
    return {word for word in words if len(word) > 2 and word not in STOP}


def load_memory() -> dict:
    try:
        value = json.loads(EDITORIAL_MEMORY.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def rules() -> dict:
    return load_memory().get("rules") or {}


def scene_phrases(scene: dict) -> list[str]:
    phrases = [" ".join(str(item).split()) for item in scene.get("keywords") or []]
    phrases = [phrase for phrase in phrases if phrase]
    if not phrases and scene.get("semantic_anchor"):
        phrases.append(" ".join(str(scene["semantic_anchor"]).split()))
    if scene.get("primary_symbol"):
        symbol = " ".join(str(scene["primary_symbol"]).split())
        if symbol and symbol.lower() not in {phrase.lower() for phrase in phrases}:
            phrases.append(symbol)
    return phrases[:5]


def candidate_text(video: dict) -> str:
    url = str(video.get("url") or video.get("source_url") or "")
    slug = url.rsplit("/", 2)[-2] if "/" in url else url
    return " ".join(
        str(value or "")
        for value in (video.get("title"), video.get("description"), slug)
    )


def phrase_scores(scene: dict, video: dict) -> list[float]:
    candidate_terms = tokens(candidate_text(video))
    scores = []
    for phrase in scene_phrases(scene):
        phrase_terms = tokens(phrase)
        if not phrase_terms:
            continue
        scores.append(len(phrase_terms & candidate_terms) / len(phrase_terms))
    return scores


def anchor_coverage(scene: dict, video: dict) -> float:
    scores = phrase_scores(scene, video)
    if not scores:
        return 0.0
    # Multi-clause narration must be represented by more than one lucky noun.
    scores = sorted(scores, reverse=True)
    count = min(2, len(scores))
    return sum(scores[:count]) / count


def query_similarity(left: str, right: str) -> float:
    first, second = tokens(left), tokens(right)
    if not first or not second:
        return 0.0
    return len(first & second) / max(math.sqrt(len(first) * len(second)), 1.0)


def rejected_context(scene: dict, video: dict) -> dict | None:
    stock_id = video.get("id")
    query = str(scene.get("symbol_query") or scene.get("query") or "")
    for approval in load_memory().get("approvals") or []:
        for item in approval.get("rejected_stock_contexts") or []:
            if str(item.get("stock_id")) != str(stock_id):
                continue
            if query_similarity(query, str(item.get("query") or "")) >= 0.28:
                return item
    return None


def direct_match_required(
    scene: dict,
    index: int | None = None,
    total: int | None = None,
) -> bool:
    mode = str(scene.get("narrative_mode") or "").strip().lower()
    if mode in {"literal", "literal_graphic", "direct", "storyboard"}:
        return True
    if mode in {"atmosphere", "abstract", "stock_ok"}:
        return False
    fraction = (
        float(index) / max(float(total or 1), 1.0)
        if index is not None
        else 0.0
    )
    strict_fraction = float(rules().get("strict_first_fraction", 0.72))
    if fraction > strict_fraction:
        return False
    function = str(scene.get("visual_function") or "").lower()
    return function in {"literal_anchor", "mechanism", "recursion"} and bool(
        scene_phrases(scene)
    )


def acceptable(
    scene: dict,
    video: dict,
    index: int | None = None,
    total: int | None = None,
) -> tuple[bool, float, str]:
    rejected = rejected_context(scene, video)
    coverage = anchor_coverage(scene, video)
    if rejected:
        return False, coverage, str(
            rejected.get("reason") or "context rejected by approved edit"
        )
    if not direct_match_required(scene, index, total):
        return True, coverage, "advisory"
    threshold = float(rules().get("minimum_anchor_coverage", 0.18))
    if scene.get("human_role"):
        threshold = float(rules().get("minimum_human_anchor_coverage", 0.10))
    if coverage + 1e-9 < threshold:
        return False, coverage, f"anchor coverage {coverage:.2f} below {threshold:.2f}"
    return True, coverage, "direct match"


def rerank(
    scene: dict,
    scored: Iterable[tuple],
    index: int | None = None,
    total: int | None = None,
):
    """Return accepted candidates with narrative coverage added to the score."""
    rows = []
    decisions = []
    for base, video, thumb, embedding in scored:
        ok, coverage, reason = acceptable(scene, video, index, total)
        final = float(base) + 30.0 * coverage
        decisions.append(
            {
                "stock_id": video.get("id"),
                "base_score": round(float(base), 2),
                "anchor_coverage": round(coverage, 3),
                "accepted": ok,
                "reason": reason,
                "final_score": round(final, 2),
            }
        )
        if ok:
            rows.append((final, video, thumb, embedding))
    rows.sort(key=lambda item: -item[0])
    return rows, decisions
