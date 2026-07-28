"""Opt-in recurring-character profiles for video-specific creative direction.

Profiles describe who inhabits the film. Animation profiles describe how the film
moves. The two layers are intentionally separate and composable.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

JUNE_OXLEY = "june_oxley"

_ALIASES = {
    "june_oxley": JUNE_OXLEY,
    "juneoxley": JUNE_OXLEY,
    "june": JUNE_OXLEY,
    "papa_june": JUNE_OXLEY,
    "grandpa_june": JUNE_OXLEY,
    "granpa_june": JUNE_OXLEY,
    "grandpa_spuds_oxley": JUNE_OXLEY,
    "granpa_spuds_oxley": JUNE_OXLEY,
}

_JUNE_ORDINARY = (
    "June Oxley rocking on a weathered wooden front porch in warm daylight",
    "June Oxley driving an old pickup truck along a rural gravel road",
    "small town diner counter with ceiling fan and coffee steam",
    "feed store aisle with seed sacks and practical farm tools",
    "bait shop counter with tackle boxes and hand-painted local signs",
    "old rural garage with carburetor parts on a workbench",
    "church picnic tables under shade trees in a tiny town",
    "water tower above a quiet two-lane main street",
    "moonshine shed behind a weathered rural house at dusk",
    "cornfield moving in wind under readable warm daylight",
    "barking dog beside a chain link fence in a lived-in backyard",
    "unpaid bills spread across a kitchen table beside a coffee mug",
    "worn work boots walking a dusty country road",
    "rusted mailbox beside a gravel road in daylight",
    "coffee mug on a porch rail in morning sunlight",
    "empty rocking chair on June Oxley's weathered front porch",
)

_JUNE_STRANGE = (
    "ordinary porch mirror reflecting an impossible star field",
    "cosmic light appearing over an ordinary cornfield",
    "church ceiling fan turning beneath a briefly visible universe",
    "moonshine jar casting impossible geometry across a shed wall",
)

_VISION_WORDS = (
    "astral", "cosmic", "cosmos", "dmt", "dream", "fractal", "galaxy",
    "illusion", "infinite", "mystical", "psychedelic", "spirit", "universe",
    "vision", "wormhole",
)

_JUNE_HUMAN_CUES = (
    "driver", "hands steering", "man ", " man", "narrator", "person ",
    " person", "sitting", "smoking", "standing", "walking", "porch",
)

_OTHER_SUBJECTS = (
    "boy", "child", "cousin", "crowd", "daughter", "dog", "earl", "girl",
    "neighbor", "people", "waitress", "woman", "wife",
)


def _key(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def character_bible(profile: str | None) -> dict:
    if profile != JUNE_OXLEY:
        return {}
    path = Path(__file__).resolve().parents[1] / "concept" / "characters" / "june_oxley.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def resolve(script: dict | None, strict: bool = False) -> str | None:
    """Return the canonical recurring-character profile name."""
    script = script or {}
    raw = next((script.get(k) for k in ("profile", "character_style", "character")
                if script.get(k)), None)
    if raw is None:
        return None
    found = _ALIASES.get(_key(raw))
    if found is None and strict:
        raise ValueError(f"unknown profile {raw!r}; supported: june_oxley")
    return found


def detect_from_text(text: str) -> str | None:
    """Detect an explicitly named profile in an issue/request description."""
    t = " ".join(str(text).lower().split())
    if re.search(r"\b(june oxley|papa june|grandpa june|granpa june|granpa spuds oxley)\b", t):
        return JUNE_OXLEY
    return None


def is_visionary(text: str) -> bool:
    t = str(text).lower()
    return any(word in t for word in _VISION_WORDS)


def identity_query(text: str, profile: str | None) -> str:
    """Keep June's recurring subject visually stable without rewriting locals."""
    q = " ".join(str(text).split()).strip()
    if profile != JUNE_OXLEY or not q:
        return q
    q = re.sub(
        r"\bold(?:er)?\s+black\s+(?:southern\s+)?man\b",
        "June Oxley, elderly white rural man",
        q,
        flags=re.I,
    )
    low = q.lower()
    if "june oxley" in low or any(subject in low for subject in _OTHER_SUBJECTS):
        return q
    if any(cue in low for cue in _JUNE_HUMAN_CUES):
        return f"{q}, June Oxley, elderly white rural man"
    return q


def query_variants(query: str, profile: str | None) -> list[str]:
    """Search literal meaning plus a light recurring-world cue."""
    q = identity_query(query, profile)
    if profile != JUNE_OXLEY or not q:
        return [q] if q else []
    if is_visionary(q):
        styled = f"{q}, grounded rural folk surrealism entering an ordinary small town"
    else:
        styled = f"{q}, lived-in rural small town documentary, warm readable daylight"
    return [styled, q]


def semantic_query(query: str, profile: str | None) -> str:
    q = identity_query(query, profile)
    if profile != JUNE_OXLEY:
        return q
    if is_visionary(q):
        return (
            f"literal {q}; an ordinary porch, diner, garage, road, church picnic, or shed "
            "briefly becomes surreal; tactile, warm, deadpan, and grounded rather than glossy fantasy"
        )
    return (
        f"literal {q}; candid lived-in rural small-town life, warm natural light, weathered "
        "practical details, everyday work clothes, gentle humor, no political imagery"
    )


def fallback_queries(profile: str | None, genre: str | None = None) -> tuple[str, ...] | None:
    if profile != JUNE_OXLEY:
        return None
    return _JUNE_ORDINARY + (_JUNE_STRANGE if genre == "dmt" else _JUNE_STRANGE[:2])


def hero_style(profile: str | None, genre: str | None = None) -> str | None:
    """Return shared June-world art direction without forcing June into every shot.

    ``hero_prompt``/``identity_query`` adds June's identity only when the literal
    request contains a human cue. Object, weather, animal, vehicle, and town-detail
    heroes retain the same world without being turned into portraits.
    """
    if profile != JUNE_OXLEY:
        return None
    return (
        ", lived-in rural small-town America, warm natural light, tactile weathered "
        "materials, practical everyday detail, gentle deadpan humor, coherent recurring "
        "town art direction, no political imagery, no generic motivational gloss"
    )


def hero_prompt(prompt: str, profile: str | None) -> str:
    return identity_query(prompt, profile)


def writer_context(profile: str | None) -> str:
    if profile != JUNE_OXLEY:
        return ""
    return """JUNE OXLEY PROFILE (apply only to this explicitly named video):
- June is a jolly rural elder and front-porch philosopher. Use the ElevenLabs voice named Granpa Spuds Oxley; never silently substitute Liam.
- His ethical center is simple: do right by people, especially when nobody is keeping score. He has no political identity and does not enter partisan or culture-war topics.
- Begin with one specific local encounter in the porch/diner/feed-store/bait-shop/garage/gravel-road/water-tower/moonshine-shed world.
- Humor comes from timing, ordinary details, his own assumptions, and a strange rural comeback—not from treating him as stupid or making another group the punchline.
- Let the encounter reveal a deeper question about belief, perception, kindness, DMT, memory, attention, or the small ways reality fibs.
- DMT is a personal report, interpretation, or metaphor unless a scientific statement is separately sourced and fidelity-labeled. Moonshine is a comic prop, never a recipe or proof.
- Use one original consistent June Oxley face and recurring town continuity; no rotating elderly stock models, meme-grandpa design, or permanent joke banner.
- Keep most object, animal, weather, vehicle, and town-detail scenes free of June; character continuity applies only when he is actually shown.
- Land back on the porch, weather, mug, body, or neighbor, then hand the viewer an open question.
- Set the top-level JSON field exactly to \"profile\": \"june_oxley\"."""


def display_name(profile: str | None) -> str:
    return "June Oxley" if profile == JUNE_OXLEY else "default"
