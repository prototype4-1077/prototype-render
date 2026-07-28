"""Plan and audit the visual symbol language of a narrated video.

The renderer used to treat a vague human reaction shot as a universal answer to
an abstract sentence.  This module makes the visual choice explicit.  It tracks
which symbol family carries each beat, why a human is present, and whether the
sequence repeats one shorthand so often that the idea becomes visually flat.

The planner is deliberately deterministic and dependency-free.  It does not
rewrite narration.  It preserves a concrete query, but when a query is missing
or is only generic human mood footage it can add ``symbol_query``: a physical,
searchable metaphor derived from the spoken line.  ``footage.py`` searches that
query while retaining the original query for review.

Usage:
    python3 visual_symbols.py plan build/<slug>
    python3 visual_symbols.py report build/<slug>
    python3 visual_symbols.py validate build/<slug>
"""
from __future__ import annotations

from collections import Counter
import json
import math
import os
import re
import sys


POLICY_NAME = "diverse_symbols"
JUNE_OXLEY = "june_oxley"

FAMILIES = (
    "human",
    "collective",
    "perception",
    "language",
    "architecture",
    "pathway",
    "identity",
    "time_memory",
    "object_tool",
    "nature",
    "world_scale",
    "geometry",
    "transformation",
    "light_atmosphere",
)

# Query/prompt terms describe what will actually be shown and therefore take
# precedence over narration terms when classifying a planned scene.
FAMILY_PATTERNS = {
    "collective": (
        "crowd", "commuters", "community", "many people", "public square",
        "audience", "protest", "tribe", "group of people", "workers together",
    ),
    "perception": (
        "eye", "eyes", "lens", "magnifying glass", "reflection", "reflected",
        "binocular", "camera viewfinder", "looking glass", "optical", "gallery of eyes",
    ),
    "language": (
        "word", "words", "letter", "letters", "alphabet", "sentence", "handwriting",
        "notebook", "book", "dictionary", "newspaper", "typewriter", "printed page",
        "question mark", "label", "speech bubble", "ink on paper",
    ),
    "architecture": (
        "door", "doorway", "hallway", "room", "wall", "window", "stair", "stairs",
        "house", "building", "cage", "prison", "corridor", "threshold", "ceiling",
        "gate", "frame", "border", "storefront",
    ),
    "pathway": (
        "arrow", "arrows", "crossroad", "fork in road", "road", "path", "pathway",
        "trail", "direction sign", "signpost", "maze", "route", "compass needle",
    ),
    "identity": (
        "mask", "costume", "uniform", "clothing", "coat", "jacket", "mannequin",
        "portrait", "double exposure face", "layered face", "faceless", "name tag",
    ),
    "time_memory": (
        "clock", "watch", "hourglass", "calendar", "record needle", "vinyl record",
        "old photograph", "photo album", "film projector", "archive", "childhood photo",
        "timeline", "metronome",
    ),
    "object_tool": (
        "key", "lock", "hammer", "pen", "phone", "smartphone", "screen", "map",
        "compass", "tool", "menu", "scale", "balance", "mail", "package", "mirror",
        "prism", "radio", "microphone", "steering wheel", "furniture", "chair",
    ),
    "nature": (
        "seed", "soil", "root", "plant", "tree", "flower", "garden", "river", "ocean",
        "water", "rain", "storm", "cloud", "forest", "bird", "fish", "mountain",
        "sunrise", "sunset", "grass", "field", "fire", "smoke",
    ),
    "world_scale": (
        "globe", "planet", "earth", "world", "city skyline", "city upside down",
        "landscape", "desert", "horizon", "aerial city", "universe", "galaxy",
        "house seen from above", "map territory",
    ),
    "geometry": (
        "circle", "ring", "sphere", "spiral", "grid", "line", "lines", "triangle",
        "cube", "recursive", "nested", "fractal", "geometric", "wavelength", "spectrum",
    ),
    "transformation": (
        "morph", "melting", "breaks open", "breaking open", "germinating", "developing",
        "rearrange", "rearranging", "turns into", "changes shape", "unfolding",
        "dissolving", "growing", "opening", "tilting floor",
    ),
    "light_atmosphere": (
        "light beam", "sun ray", "shadow", "silhouette", "fog", "haze", "candle flame",
        "darkness", "glow", "illuminated", "neon", "dust in light", "curtain moving",
    ),
}

FAMILY_PRIORITY = (
    "language", "identity", "time_memory", "pathway", "perception", "architecture",
    "object_tool", "nature", "world_scale", "geometry", "transformation", "collective",
    "light_atmosphere",
)

HUMAN_TERMS = (
    "person", "people", "man", "woman", "boy", "girl", "child", "teenager", "adult",
    "face", "hands", "hand", "couple", "friend", "worker", "student", "parent",
    "mother", "father", "crowd", "commuter", "audience", "performer", "driver",
)

HUMAN_EXCLUSION_TERMS = tuple(sorted(
    set(HUMAN_TERMS) | {"face", "faces", "body", "bodies", "skin", "skins"},
    key=len,
    reverse=True,
))
_HUMAN_EXCLUSION_TERM = "(?:" + "|".join(
    re.escape(term) for term in HUMAN_EXCLUSION_TERMS
) + ")"
_HUMAN_EXCLUSION_MODIFIER = (
    r"(?:(?:visible|additional|extra|other|new|unrelated|recognizable|realistic|"
    r"full|exposed|narrator|human)\s+)*"
)
_HUMAN_EXCLUSION_RE = re.compile(
    r"\b(?:no|without)\s+"
    + _HUMAN_EXCLUSION_MODIFIER + _HUMAN_EXCLUSION_TERM
    + r"(?:(?:\s*,\s*|\s+(?:or|and)\s+)"
    + _HUMAN_EXCLUSION_MODIFIER + _HUMAN_EXCLUSION_TERM + r")*"
)

CONCRETE_HUMAN_ACTIONS = (
    "writes", "writing", "draws", "drawing", "opens", "opening", "closes", "closing",
    "enters", "entering", "leaves", "leaving", "carries", "carrying", "builds", "building",
    "plants", "planting", "drives", "driving", "records", "recording", "types", "typing",
    "picks", "placing", "returns", "turning", "crosses", "walking through", "speaks",
    "talking", "listens", "listening", "dances", "dancing", "removes", "holds",
    "hands over", "repairs", "cooks", "sorting", "measures", "points", "raises hand",
)

VAGUE_HUMAN_TERMS = (
    "thoughtful", "thinking", "pensive", "sad", "worried", "confused", "stares", "staring",
    "looks", "looking", "stands", "standing", "sits", "sitting", "alone", "silhouette",
    "contemplative", "emotional", "mysterious", "moody", "walking in fog",
)

ROLE_PATTERNS = (
    ("collective", ("crowd", "many people", "commuters", "audience", "community", "tribe")),
    ("creator", ("write", "draw", "build", "make", "create", "plant", "compose", "repair")),
    ("chooser", ("choose", "choice", "decide", "select", "turn toward", "two doors", "arrows")),
    ("explorer", ("enter", "cross", "walk through", "step into", "doorway", "threshold", "path")),
    ("observer", ("watch", "look", "see", "observe", "lens", "eye", "reflection")),
    ("guardian", ("protect", "hold back", "defend", "shield", "guard")),
    ("performer", ("perform", "stage", "audience", "camera", "selfie", "pose", "dance")),
    ("relationship", ("conversation", "couple", "friend", "parent", "child", "together")),
)

PRIMARY_SYMBOLS = (
    "eye", "lens", "magnifying glass", "mirror", "door", "window", "wall", "cage", "stair", "arrow", "road",
    "path", "word", "letter", "book", "notebook", "phone", "clock", "record", "needle",
    "map", "compass", "key", "lock", "seed", "tree", "river", "water", "fire", "smoke",
    "prism", "ring", "circle", "sphere", "globe", "city", "bridge", "thread", "mask",
    "uniform", "crowd", "hand", "face",
)


# A physical query must be searchable and must contain something that can move.
# These are alternatives only for a missing query or generic human mood footage.
NARRATIVE_SYMBOL_RULES = (
    {
        "family": "language",
        "triggers": ("word", "language", "sentence", "name", "label", "truth", "belief", "story"),
        "query": "hand moves magnifying glass across printed words on paper natural side light close up",
        "symbol": "word",
        "function": "literal_anchor",
    },
    {
        "family": "pathway",
        "triggers": ("choice", "choose", "direction", "road", "path", "turn", "decision", "possibility"),
        "query": "hand draws two arrows pointing different directions on paper soft window light close up",
        "symbol": "arrow",
        "function": "choice",
    },
    {
        "family": "perception",
        "triggers": ("see", "seeing", "look", "perception", "observe", "watch", "perspective", "view"),
        "query": "magnifying lens moves across an ordinary landscape changing what is in focus daylight",
        "symbol": "lens",
        "function": "perspective_shift",
    },
    {
        "family": "architecture",
        "triggers": ("door", "wall", "room", "boundary", "border", "cage", "locked", "inside", "outside"),
        "query": "one real door opens while neighboring doors remain closed in bright lived-in hallway",
        "symbol": "door",
        "function": "boundary",
    },
    {
        "family": "time_memory",
        "triggers": ("time", "past", "memory", "remember", "future", "yesterday", "years", "moment"),
        "query": "record needle travels across spinning vinyl beside old photographs soft window light",
        "symbol": "record needle",
        "function": "time",
    },
    {
        "family": "identity",
        "triggers": ("identity", "self", "personality", "mask", "costume", "version of you", "who you are"),
        "query": "person removes a plain mask before a mirror in natural daylight realistic documentary",
        "symbol": "mask",
        "function": "identity",
    },
    {
        "family": "nature",
        "triggers": ("grow", "growth", "heal", "healing", "become", "root", "seed", "change", "freedom"),
        "query": "seed germinates and roots spread through dark soil time lapse with soft daylight",
        "symbol": "seed",
        "function": "transformation",
    },
    {
        "family": "geometry",
        "triggers": ("infinite", "includes itself", "recursive", "pattern", "frequency", "spectrum", "whole light"),
        "query": "nested illuminated rings expand through one another on dark blue background slow motion",
        "symbol": "ring",
        "function": "recursion",
    },
    {
        "family": "world_scale",
        "triggers": ("world", "reality", "society", "civilization", "universe", "collective", "entire life"),
        "query": "slowly rotating globe reflected against moving city streets in clear daylight",
        "symbol": "globe",
        "function": "scale_shift",
    },
    {
        "family": "object_tool",
        "triggers": ("control", "influence", "tool", "guide", "signal", "information", "map", "measure"),
        "query": "compass needle turns beside a folded map and resting hand natural window light close up",
        "symbol": "compass",
        "function": "mechanism",
    },
    {
        "family": "architecture",
        "triggers": ("division", "divide", "separate", "enemy", "belonging", "tribe"),
        "query": "movable wall divides one lived-in room while people remain visible on both sides daylight",
        "symbol": "wall",
        "function": "division",
    },
    {
        "family": "light_atmosphere",
        "triggers": ("fear", "anger", "grief", "emotion", "pain", "hope", "peace"),
        "query": "storm shadow crosses a bright room then clears through the window natural time lapse",
        "symbol": "shadow",
        "function": "emotional_weather",
    },
)


class VisualSymbolError(ValueError):
    pass


def _normalize(value) -> str:
    return " ".join(str(value or "").lower().split())


def _has(text: str, phrase: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _count_hits(text: str, patterns) -> int:
    return sum(1 for pattern in patterns if _has(text, pattern))


def _human_presence_text(value) -> str:
    """Remove explicit human exclusions before auditing what will appear."""
    return _normalize(_HUMAN_EXCLUSION_RE.sub(" ", _normalize(value)))


def _visual_text(scene: dict) -> str:
    # symbol_query replaces the ordinary stock query.  Keeping both here would
    # incorrectly report a human as present after the planner deliberately
    # replaced generic human filler with an object or structural metaphor.
    search_query = scene.get("symbol_query") or scene.get("query") or ""
    return _normalize(" ".join(str(value or "") for value in (
        search_query, scene.get("image_prompt"),
    )))


def _family_from_text(text: str) -> str | None:
    scores = {
        family: _count_hits(text, patterns)
        for family, patterns in FAMILY_PATTERNS.items()
    }
    best = max(scores.values(), default=0)
    if best:
        # A specific semantic family beats a generic mood/background family
        # when a visual legitimately contains more than one kind of object.
        return next(family for family in FAMILY_PRIORITY if scores[family] == best)
    if _count_hits(_human_presence_text(text), HUMAN_TERMS):
        return "human"
    return None


def classify_scene(scene: dict) -> str:
    explicit = _normalize(scene.get("symbol_family")).replace(" ", "_")
    if explicit in FAMILIES and scene.get("symbol_family_source") != "auto":
        return explicit
    visual = _visual_text(scene)
    family = _family_from_text(visual) if visual else None
    if family:
        return family
    narration = _normalize(scene.get("text"))
    return _family_from_text(narration) or "human"


def observed_family(scene: dict) -> str:
    """Infer the family from the actual effective visual request.

    Audit counts use this instead of trusting an author-supplied label.  An
    explicit label still communicates intent, but it cannot make a reel of
    generic people appear diverse on paper.
    """
    visual = _visual_text(scene)
    return (_family_from_text(visual) if visual else None) or classify_scene(scene)


def uses_human(scene: dict, family: str | None = None) -> bool:
    family = family or classify_scene(scene)
    visual = _human_presence_text(_visual_text(scene))
    return family in {"human", "collective"} or _count_hits(visual, HUMAN_TERMS) > 0


def infer_human_role(scene: dict) -> str | None:
    if not uses_human(scene):
        return None
    blob = _normalize(f"{_visual_text(scene)} {scene.get('text', '')}")
    for role, patterns in ROLE_PATTERNS:
        if _count_hits(blob, patterns):
            return role
    if _has(blob, "tiny person") or _has(blob, "lone figure"):
        return "scale_reference"
    return "unspecified"


def is_generic_human(scene: dict, family: str | None = None) -> bool:
    family = family or classify_scene(scene)
    if not uses_human(scene, family):
        return False
    visual = _visual_text(scene)
    if _count_hits(visual, CONCRETE_HUMAN_ACTIONS):
        return False
    # A named role is meaningful editorial intent, even if the body is still.
    role = _normalize(scene.get("human_role"))
    if role and role != "unspecified":
        return False
    vague = bool(_count_hits(visual, VAGUE_HUMAN_TERMS) or family == "human")
    if not vague:
        return False
    if family in {"human", "collective", "light_atmosphere"}:
        return True
    # A window or room is frequently just scenery behind the old default
    # "thoughtful person" shot.  A door opening, crossing a threshold, or any
    # other concrete architectural action is already caught above and kept.
    if family == "architecture" and primary_symbol(scene, family) in {"window", "room"}:
        return True
    return False


def infer_visual_function(scene: dict) -> str:
    explicit = _normalize(scene.get("visual_function")).replace(" ", "_")
    if explicit:
        return explicit
    text = _normalize(scene.get("text"))
    rules = (
        ("recursion", ("includes itself", "recursive", "inside itself", "infinite")),
        ("boundary", ("border", "boundary", "inside", "outside", "wall", "cage")),
        ("choice", ("choice", "choose", "decide", "direction")),
        ("perspective_shift", ("seeing", "perception", "perspective", "way of looking")),
        ("transformation", ("become", "change", "rearrange", "turns into", "develop")),
        ("collective", ("everyone", "society", "civilization", "tribe", "people")),
        ("contrast", ("but", "instead", "rather than", "not the", "different")),
    )
    for function, patterns in rules:
        if _count_hits(text, patterns):
            return function
    return "literal_anchor"


def infer_anchor(scene: dict) -> str:
    explicit = " ".join(str(scene.get("semantic_anchor") or "").split())
    if explicit:
        return explicit
    keywords = [" ".join(str(item).split()) for item in scene.get("keywords", []) if str(item).strip()]
    if keywords:
        return keywords[0]
    words = [
        word for word in re.findall(r"[a-z']+", _normalize(scene.get("text")))
        if len(word) > 4 and word not in {
            "because", "through", "something", "sometimes", "which", "there", "their",
            "about", "before", "after", "would", "could", "should", "every", "yourself",
        }
    ]
    return " ".join(words[:3]) or "spoken beat"


def primary_symbol(scene: dict, family: str | None = None) -> str:
    explicit = _normalize(scene.get("primary_symbol")).replace("_", " ")
    if explicit:
        return explicit
    visual = _visual_text(scene)
    for symbol in PRIMARY_SYMBOLS:
        if _has(visual, symbol):
            return symbol
    return family or classify_scene(scene)


def _symbol_candidates(scene: dict):
    keywords = scene.get("keywords") or []
    text = _normalize(f"{scene.get('text', '')} {' '.join(map(str, keywords))}")
    candidates = []
    for order, rule in enumerate(NARRATIVE_SYMBOL_RULES):
        score = _count_hits(text, rule["triggers"])
        if score:
            candidates.append((score, -order, rule))
    return [item[2] for item in sorted(candidates, reverse=True)]


def derive_symbol_query(scene: dict, recent_families=()):
    candidates = _symbol_candidates(scene)
    if not candidates:
        return None
    # Narrative fit outranks artificial rotation. Adjacent scenes may continue
    # one visual family when they are developing the same metaphor.
    return candidates[0]


def effective_query(scene: dict) -> str:
    return " ".join(str(scene.get("symbol_query") or scene.get("query") or "").split())


def apply_plan(script: dict, profile: str | None = None) -> bool:
    """Annotate scenes and add symbolic alternatives for weak human filler."""
    changed = False
    recent = []
    for index, scene in enumerate(script.get("scenes", [])):
        # First classify the author-provided query so generic-human detection is honest.
        initial_family = classify_scene(scene)
        weak_human = is_generic_human(scene, initial_family)
        missing_query = not _normalize(scene.get("query")) and not _normalize(scene.get("image_prompt"))
        if (weak_human or missing_query) and not scene.get("symbol_query") and profile != JUNE_OXLEY:
            suggestion = derive_symbol_query(scene, recent)
            if suggestion:
                scene["symbol_query"] = suggestion["query"]
                scene["symbol_family"] = suggestion["family"]
                scene["symbol_family_source"] = "planner"
                scene.setdefault("primary_symbol", suggestion["symbol"])
                scene.setdefault("visual_function", suggestion["function"])
                changed = True

        family = classify_scene(scene)
        values = {
            "symbol_family": family,
            "visual_function": infer_visual_function(scene),
            "semantic_anchor": infer_anchor(scene),
            "primary_symbol": primary_symbol(scene, family),
        }
        for key, value in values.items():
            if (key == "symbol_family" and value
                    and scene.get("symbol_family_source") == "auto"
                    and scene.get(key) != value):
                scene[key] = value
                changed = True
                continue
            if not scene.get(key) and value:
                scene[key] = value
                changed = True
                if key == "symbol_family":
                    scene["symbol_family_source"] = "auto"
        role = infer_human_role(scene)
        if role and not scene.get("human_role"):
            scene["human_role"] = role
            changed = True
        recent.append(family)
    return changed


def _longest_run(values, predicate=lambda value: True):
    best_value, best_start, best_len = None, 0, 0
    current_value, current_start, current_len = None, 0, 0
    for index, value in enumerate(values):
        if predicate(value) and value == current_value:
            current_len += 1
        elif predicate(value):
            current_value, current_start, current_len = value, index, 1
        else:
            current_value, current_start, current_len = None, index + 1, 0
        if current_len > best_len:
            best_value, best_start, best_len = current_value, current_start, current_len
    return {"value": best_value, "start": best_start, "length": best_len}


def _policy(script: dict, profile: str | None):
    raw = script.get("visual_policy")
    if isinstance(raw, dict):
        mode = raw.get("mode") or "advisory"
        custom = raw
    else:
        mode = raw or "advisory"
        custom = {}
    strict = mode in {POLICY_NAME, "strict", "enforce"}
    defaults = {
        "mode": mode,
        "strict": strict,
        "max_human_ratio": .70,
        "max_family_run": 6,
        "max_generic_human_run": 2 if profile == JUNE_OXLEY else 1,
        "min_families": 4,
    }
    for key in tuple(defaults):
        if key in custom and key not in {"strict"}:
            defaults[key] = custom[key]
    return defaults


def analyze(script: dict, profile: str | None = None) -> dict:
    apply_plan(script, profile)
    scenes = script.get("scenes", [])
    families = [observed_family(scene) for scene in scenes]
    human = [uses_human(scene, family) for scene, family in zip(scenes, families)]
    generic = [is_generic_human(scene, family) for scene, family in zip(scenes, families)]
    weights = [max(float(scene.get("duration") or 1.0), .01) for scene in scenes]
    total = sum(weights) or 1.0
    human_ratio = sum(weight for weight, flag in zip(weights, human) if flag) / total
    generic_ratio = sum(weight for weight, flag in zip(weights, generic) if flag) / total
    family_counts = Counter(families)
    symbol_counts = Counter(primary_symbol(scene, family)
                            for scene, family in zip(scenes, families))
    family_run = _longest_run(families)
    generic_run = _longest_run(
        ["generic_human" if flag else None for flag in generic],
        predicate=lambda value: value is not None,
    )
    policy = _policy(script, profile)
    warnings, violations = [], []
    unique = len(family_counts)
    min_families = min(int(policy["min_families"]), max(3, math.ceil(len(scenes) / 3)))

    checks = []
    if len(scenes) >= 10 and unique < min_families:
        checks.append(
            f"only {unique} symbol families across {len(scenes)} scenes; use at least {min_families}"
        )
    if human_ratio > float(policy["max_human_ratio"]):
        checks.append(
            f"human imagery occupies {human_ratio:.0%}; target <= {float(policy['max_human_ratio']):.0%}"
        )
    if family_run["length"] > int(policy["max_family_run"]):
        checks.append(
            f"{family_run['value']} repeats for {family_run['length']} consecutive scenes "
            f"starting at scene {family_run['start']}"
        )
    if generic_run["length"] > int(policy["max_generic_human_run"]):
        checks.append(
            f"generic human filler repeats for {generic_run['length']} consecutive scenes "
            f"starting at scene {generic_run['start']}"
        )
    repeated_limit = max(3, math.ceil(len(scenes) * .20))
    for symbol, count in symbol_counts.most_common():
        if count > repeated_limit:
            warnings.append(
                f"primary symbol {symbol!r} appears {count} times; vary the metaphor vocabulary"
            )
    if generic_ratio > .15:
        warnings.append(
            f"generic human filler occupies {generic_ratio:.0%}; people should have a named symbolic role"
        )
    if policy["strict"]:
        violations.extend(checks)
    else:
        warnings.extend(checks)

    scene_rows = []
    for index, (scene, family, human_flag, generic_flag) in enumerate(
            zip(scenes, families, human, generic)):
        selected_description = _normalize(
            f"{scene.get('source_title', '')} {scene.get('source_url', '')}"
        )
        selected_family = _family_from_text(selected_description) if selected_description else None
        scene_rows.append({
            "index": index,
            "text": scene.get("text"),
            "semantic_anchor": scene.get("semantic_anchor"),
            "visual_function": scene.get("visual_function"),
            "symbol_family": scene.get("symbol_family") or family,
            "query_family": family,
            "primary_symbol": primary_symbol(scene, family),
            "human_present": human_flag,
            "human_role": scene.get("human_role"),
            "generic_human": generic_flag,
            "original_query": scene.get("query"),
            "effective_query": effective_query(scene),
            "selected_family": selected_family,
        })

    # A transparent 0-100 editorial score, not a machine-vision claim.
    family_score = min(1.0, unique / max(min_families, 1))
    human_score = min(1.0, float(policy["max_human_ratio"]) / max(human_ratio, .001))
    run_score = min(1.0, int(policy["max_family_run"]) / max(family_run["length"], 1))
    generic_score = 1.0 - min(generic_ratio, 1.0)
    score = round(100 * (.35 * family_score + .25 * human_score
                         + .20 * run_score + .20 * generic_score), 1)
    return {
        "policy": policy,
        "passes": not violations,
        "score": score,
        "scene_count": len(scenes),
        "symbol_family_count": unique,
        "family_counts": dict(family_counts),
        "primary_symbol_counts": dict(symbol_counts),
        "human_presence_ratio": round(human_ratio, 4),
        "generic_human_ratio": round(generic_ratio, 4),
        "longest_family_run": family_run,
        "longest_generic_human_run": generic_run,
        "warnings": list(dict.fromkeys(warnings)),
        "violations": list(dict.fromkeys(violations)),
        "scenes": scene_rows,
    }


def write_report(build_dir: str, script: dict, profile: str | None = None) -> dict:
    report = analyze(script, profile)
    path = os.path.join(build_dir, "visual_symbol_report.json")
    with open(path, "w") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return report


def validate(script: dict, profile: str | None = None) -> dict:
    report = analyze(script, profile)
    if report["violations"]:
        raise VisualSymbolError("; ".join(report["violations"]))
    return report


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    if len(argv) != 2 or argv[0] not in {"plan", "report", "validate"}:
        raise SystemExit("usage: visual_symbols.py <plan|report|validate> build/<slug>")
    command, build_dir = argv
    script_path = os.path.join(build_dir, "script.json")
    script = json.load(open(script_path))
    try:
        import profiles
        profile = profiles.resolve(script)
    except Exception:
        profile = None
    changed = apply_plan(script, profile)
    if command == "plan" or changed:
        with open(script_path, "w") as handle:
            json.dump(script, handle, indent=1, ensure_ascii=False)
    report = write_report(build_dir, script, profile)
    if command == "validate" and report["violations"]:
        raise SystemExit("ERROR: " + "; ".join(report["violations"]))
    print(
        f"visual symbols: {report['score']:.1f}/100, "
        f"{report['symbol_family_count']} families, "
        f"human presence {report['human_presence_ratio']:.0%}, "
        f"generic human {report['generic_human_ratio']:.0%}"
    )
    for warning in report["warnings"]:
        print(f"warning: {warning}")


if __name__ == "__main__":
    main()
