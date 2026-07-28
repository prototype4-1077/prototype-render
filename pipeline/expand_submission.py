"""Expand a small Think-Tank submission.json into a full pipeline package.

The Think Tank (GPT) can only reliably write a SMALL file through its Action,
so it writes build/<slug>/submission.json:

    {
      "title": "Beliefs Are Software Updates",
      "voice": "liam",            # optional: liam (default) | june
      "series_label": null,       # null/omit = standalone (no yellow eyebrow)
      "scenes": [
        {"text": "...", "visual": "a sleek phone glowing on a dark desk"},
        {"text": "...", "visual": "a camera lens focusing", "hero": true}
      ]
    }

This expands it into script.json + source-script.txt with narration preserved
EXACTLY, lets the visual planner infer families from the authored imagery,
splits any scene over the 220-char cap on a sentence boundary, and writes
package-status.json.

    python3 pipeline/expand_submission.py <slug>
"""
from __future__ import annotations
import hashlib, json, re, sys, unicodedata
from pathlib import Path

VOICES = {
    "liam": ("TX3LPaxmHKxFdv7VOQHJ", "Liam - Energetic, Social Media Creator"),
    "june": ("NOpBlnGInO9m6vDvFkFC", "June Oxley"),
}
TAGS_CYCLE = [["curious", "dry"], ["warm", "inviting"], ["playful", "knowing"],
              ["measured", "precise"], ["intimate", "wondering"], ["sly", "amused"],
              ["spacious", "quiet"], ["hushed", "near-whisper"]]
MAX_CHARS = 220


def canonical_spoken_text(text: str) -> str:
    """Match pipeline/user_script_intake.py exactly so the verbatim lock passes."""
    normalized = unicodedata.normalize("NFC", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", normalized).strip()


def extract_leading_performance_tags(text: str) -> tuple[str, list[str]]:
    """Move leading ElevenLabs directions out of captioned narration."""
    tags = []
    remaining = str(text or "")
    while match := re.match(r"^\s*\[([^\[\]\r\n]{1,80})\]\s*", remaining):
        tags.append(match.group(1).strip())
        remaining = remaining[match.end():]
    return remaining.strip(), tags


def _audio_tags(explicit, inline: list[str], fallback: list[str]) -> list[str]:
    if isinstance(explicit, str):
        explicit = [explicit]
    return [str(tag).strip().strip("[]") for tag in (explicit or inline or fallback) if str(tag).strip()]



def _split_long(text: str) -> list[str]:
    out = []
    while len(text) > MAX_CHARS:
        cut = text.rfind(". ", 0, MAX_CHARS)
        if cut < 40:
            cut = text.rfind(" ", 0, MAX_CHARS)
        if cut < 40:
            cut = MAX_CHARS - 1
        out.append(text[:cut + 1].strip())
        text = text[cut + 1:].strip()
    out.append(text)
    return [t for t in out if t]


def expand(slug: str, build_dir=None) -> dict:
    build_dir = Path(build_dir or (Path("build") / slug))
    sub = json.loads((build_dir / "submission.json").read_text(encoding="utf-8"))
    title = sub.get("title") or slug.replace("-", " ").title()
    series = sub.get("series_label")
    voice_id, voice_name = VOICES.get(str(sub.get("voice") or "liam").lower(), VOICES["liam"])

    raw = sub.get("scenes") or []
    if not raw:
        raise ValueError("submission.json has no scenes")

    scenes, texts, idx = [], [], 0
    for item in raw:
        if isinstance(item, str):
            item = {"text": item}
        spoken, inline_tags = extract_leading_performance_tags(str(item.get("text", "")))
        visual = (item.get("visual") or item.get("query")
                  or "cinematic evocative imagery for: " + spoken[:60])
        for part_index, piece in enumerate(_split_long(spoken)):
            scene = {
                "text": piece,
                "epistemic_role": "metaphor",
                "audio_tags": _audio_tags(
                    item.get("audio_tags"),
                    inline_tags if part_index == 0 else [],
                    TAGS_CYCLE[idx % len(TAGS_CYCLE)],
                ),
                "keywords": [],
                "semantic_anchor": "beat %d" % (idx + 1),
                "visual_function": "beat %d" % (idx + 1),
                "primary_symbol": visual[:60],
            }
            if item.get("symbol_family"):
                scene["symbol_family"] = item["symbol_family"]
            if item.get("hero"):
                scene.update({
                    "narrative_mode": "hero", "hero": True, "hero_style": "effects",
                    "image_prompt": "cinematic photoreal, " + visual +
                    ", shallow depth of field, restrained practical lighting, muted filmic grade, subtle grain",
                })
            else:
                scene.update({"narrative_mode": "stock_ok", "query": visual,
                              "motion_kind": "video", "motion_mode": "stock"})
            scenes.append(scene)
            texts.append(piece)
            idx += 1

    narration = " ".join(texts)
    (build_dir / "source-script.txt").write_text(narration + "\n", encoding="utf-8")
    (build_dir / "narration.txt").write_text(narration + "\n", encoding="utf-8")

    script = {
        "title": title, "slug": slug, "series_label": series,
        "title_mode": "standalone" if not series else "series",
        "genre": "concept", "science_fidelity": "metaphor",
        "evidence_boundary": sub.get("evidence_boundary")
        or "Figurative language in this script is illustrative metaphor, not a scientific claim.",
        "desired_movement": sub.get("desired_movement") or "",
        "grounding": sub.get("grounding")
        or "The closing beats return the viewer to their own room and breath.",
        "invitation": sub.get("invitation") or texts[-1],
        "end_card_question": sub.get("end_card_question") or texts[-1],
        "optimization_target": "belief_analysis",
        "target_duration_seconds": round(len(narration.split()) / 2.1, 1),
        # Long-form only by default. Shorts are paused; a submission can still
        # opt in explicitly with "render_outputs": ["youtube", "portrait"].
        "render_outputs": sub.get("render_outputs") or ["youtube"],
        "script_origin": "think_tank_submission",
        "supplied_script": True, "source_script_verbatim": True,
        "source_script_filename": "source-script.txt",
        "source_script_sha256": hashlib.sha256(canonical_spoken_text(narration).encode("utf-8")).hexdigest(),
        "elevenlabs_model": "eleven_v3", "elevenlabs_voice_id": voice_id,
        "elevenlabs_voice_name": voice_name, "elevenlabs_stability_mode": "creative",
        "auto_audio_tags": False,
        "voice_settings": {"similarity_boost": 0.75, "speed": 0.97},
        "voice_standard": sub.get("voice_standard")
        or "Liam - warm, sly, a brilliant friend at midnight; spacious and intimate through the turn, near-whisper on the closing question.",
        "visual_policy": {"mode": "diverse_symbols", "max_human_ratio": 0.70,
                          "max_family_run": 6, "max_generic_human_run": 1, "min_families": 4},
        "max_still_source_ratio": 0.50,
        "still_image_policy": "closest_stock_frame_full_enhancement",
        "music_choice": 3, "music_variant_count": 1,
        "caption_policy": "minimal_keywords_only",
        # A submission with no hero scenes has no image_prompt anywhere, so the
        # hero-art gate would block a package that legitimately needs no hero art.
        "hero_art_policy": ("runtime_generated" if any(s.get("hero") for s in scenes)
                            else "motion_only_no_static_hero"),
        "hero_art_status": "runtime_generation_allowed",
        "scenes": scenes,
    }
    (build_dir / "script.json").write_text(
        json.dumps(script, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (build_dir / "package-status.json").write_text(json.dumps({
        "schema_version": 1, "slug": slug, "package_ready": True, "narration_locked": True,
        "scene_count": len(scenes), "word_count": len(narration.split()),
        "hero_art_mode": "runtime_scene_generation",
        "render_request_created": False, "blocked_reason": None,
        "source": "expanded from submission.json",
    }, indent=1) + "\n", encoding="utf-8")
    return {"slug": slug, "scenes": len(scenes), "words": len(narration.split())}


if __name__ == "__main__":
    print(json.dumps(expand(sys.argv[1]), indent=1))
