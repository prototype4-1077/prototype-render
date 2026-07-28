"""ElevenLabs TTS with character timestamps and per-scene delivery tags.

Usage: python3 tts.py <build_dir>
Reads script.json, writes vo.mp3 + voiceover-manifest.json, and updates scene timing.

Environment:
  ELEVENLABS_API_KEY
  ELEVENLABS_VOICE_ID (default: Liam - Energetic, Social Media Creator)
  ELEVENLABS_MODEL (default: eleven_v3)
  ELEVENLABS_STABILITY_MODE (default: creative)

Per-video overrides:
  elevenlabs_voice_id, elevenlabs_voice_name, elevenlabs_model,
  elevenlabs_stability_mode, voice_settings, auto_audio_tags, and
  scene.audio_tags.

When a script supplies ``elevenlabs_voice_name`` without an ID, the authenticated
ElevenLabs voice library is searched by name. Exactly one normalized exact match
is required. The resolved ID is persisted in script.json and the voiceover
manifest; zero or multiple matches fail instead of silently falling back to Liam.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_VOICE_ID = "TX3LPaxmHKxFdv7VOQHJ"
DEFAULT_VOICE_NAME = "Liam - Energetic, Social Media Creator"
DEFAULT_MODEL_ID = "eleven_v3"
DEFAULT_STABILITY_MODE = "creative"
V3_CHARACTER_LIMIT = 3_000
STABILITY_BY_MODE = {
    "creative": 0.0,
    "natural": 0.5,
    "robust": 1.0,
}
V3_VOICE_SETTINGS = {
    "stability": STABILITY_BY_MODE[DEFAULT_STABILITY_MODE],
    "similarity_boost": 0.75,
    "style": 0.0,
    "speed": 0.91,
}
LEGACY_VOICE_SETTINGS = {
    "stability": 0.55,
    "similarity_boost": 0.75,
    "style": 0.35,
    "speed": 0.92,
}
OPENING_MOOD_TAGS = {
    "laugh": "laughs",
    "laughing": "laughs",
    "laughs": "laughs",
    "comedic": "mischievously",
    "funny": "mischievously",
    "playful": "mischievously",
    "mischievous": "mischievously",
    "mischievously": "mischievously",
    "low": "low voice",
    "low tone": "low voice",
    "low voice": "low voice",
    "thoughtful": "thoughtful",
    "reflective": "thoughtful",
    "sarcastic": "sarcastic",
    "curious": "curious",
    "excited": "excited",
    "dramatic": "dramatic",
    "tense": "tense",
    "calm": "calm",
    "soft": "softly",
    "softly": "softly",
    "whisper": "whispers",
    "whispers": "whispers",
    "neutral": "",
}
_TAG_PATTERN = re.compile(r"^[^\[\]\r\n]{1,48}$")


def _read_script(build_dir: str | os.PathLike[str]) -> dict:
    path = Path(build_dir) / "script.json"
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_voice_name(value: object) -> str:
    """Normalize harmless spacing/case differences without fuzzy matching."""
    return " ".join(str(value or "").split()).casefold()


def _search_voice_library(voice_name: str) -> dict:
    """Return exactly one authenticated voice whose normalized name is exact."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY is required to resolve elevenlabs_voice_name"
        )
    requested = " ".join(str(voice_name).split()).strip()
    if not requested:
        raise ValueError("elevenlabs_voice_name cannot be empty")

    exact: list[dict] = []
    seen: dict[str, dict] = {}
    next_token: str | None = None
    for _page in range(10):
        params: dict[str, object] = {
            "search": requested,
            "page_size": 100,
            "include_total_count": "false",
        }
        if next_token:
            params["next_page_token"] = next_token
        url = "https://api.elevenlabs.io/v2/voices?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "xi-api-key": key,
                "Accept": "application/json",
                "User-Agent": "Prototype-Video/voice-name-resolver",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1_000]
            raise RuntimeError(
                f"ElevenLabs voice search failed with HTTP {error.code}: {detail}"
            ) from error

        for voice in payload.get("voices") or []:
            voice_id = str(voice.get("voice_id") or "").strip()
            name = str(voice.get("name") or "").strip()
            if not voice_id or not name:
                continue
            seen[voice_id] = voice
            if normalize_voice_name(name) == normalize_voice_name(requested):
                exact.append(voice)

        if exact or not payload.get("has_more"):
            break
        next_token = str(payload.get("next_page_token") or "").strip() or None
        if not next_token:
            break

    # De-duplicate pages while preserving evidence for ambiguity.
    exact_by_id = {
        str(item.get("voice_id")): item
        for item in exact
        if item.get("voice_id")
    }
    matches = list(exact_by_id.values())
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(sorted(str(item["voice_id"]) for item in matches))
        raise RuntimeError(
            f"ElevenLabs voice name {requested!r} is ambiguous ({ids}); "
            "set elevenlabs_voice_id explicitly"
        )
    suggestions = sorted({
        str(item.get("name") or "").strip()
        for item in seen.values()
        if str(item.get("name") or "").strip()
    })[:8]
    suffix = f"; search returned: {', '.join(suggestions)}" if suggestions else ""
    raise RuntimeError(
        f"ElevenLabs voice name {requested!r} was not found in the authenticated library"
        f"{suffix}"
    )


def resolve_voice_id(script: dict) -> str:
    explicit = str(script.get("elevenlabs_voice_id") or "").strip()
    if explicit:
        return explicit

    voice_name = str(script.get("elevenlabs_voice_name") or "").strip()
    if voice_name:
        matched = _search_voice_library(voice_name)
        voice_id = str(matched["voice_id"]).strip()
        canonical_name = str(matched.get("name") or voice_name).strip()
        # Persist the exact account identity before generating any audio. This also
        # makes cached-voice fingerprints deterministic on later resumable passes.
        script["elevenlabs_voice_id"] = voice_id
        script["elevenlabs_voice_name"] = canonical_name
        return voice_id

    return str(
        os.environ.get("ELEVENLABS_VOICE_ID")
        or DEFAULT_VOICE_ID
    ).strip()


def resolve_voice_name(script: dict, voice_id: str) -> str:
    configured = str(script.get("elevenlabs_voice_name") or "").strip()
    if configured:
        return configured
    return DEFAULT_VOICE_NAME if voice_id == DEFAULT_VOICE_ID else "custom"


def resolve_model_id(script: dict) -> str:
    return str(
        script.get("elevenlabs_model")
        or os.environ.get("ELEVENLABS_MODEL")
        or DEFAULT_MODEL_ID
    ).strip()


def resolve_stability_mode(script: dict, model_id: str) -> str | None:
    if model_id != DEFAULT_MODEL_ID:
        return None
    mode = str(
        script.get("elevenlabs_stability_mode")
        or os.environ.get("ELEVENLABS_STABILITY_MODE")
        or DEFAULT_STABILITY_MODE
    ).strip().lower()
    if mode not in STABILITY_BY_MODE:
        allowed = ", ".join(STABILITY_BY_MODE)
        raise ValueError(
            f"invalid elevenlabs_stability_mode {mode!r}; choose one of: {allowed}"
        )
    return mode


def resolve_voice_settings(script: dict, model_id: str) -> dict:
    """Return effective settings while keeping Eleven v3 in its named mode.

    v3 maps its Creative/Natural/Robust modes through stability. Legacy numeric
    stability/style values in old scripts are intentionally not allowed to pull
    the upgraded pipeline away from the selected v3 mode. Similarity and speed
    remain safe per-video overrides.
    """
    raw = script.get("voice_settings") or {}
    if not isinstance(raw, dict):
        raise ValueError("voice_settings must be a JSON object")

    if model_id == DEFAULT_MODEL_ID:
        mode = resolve_stability_mode(script, model_id)
        settings = dict(V3_VOICE_SETTINGS)
        settings["stability"] = STABILITY_BY_MODE[mode]
        for key in ("similarity_boost", "speed"):
            if key in raw:
                settings[key] = float(raw[key])
        # ElevenLabs recommends style 0 for v3; the audio tags carry direction.
        settings["style"] = 0.0
        return settings

    settings = dict(LEGACY_VOICE_SETTINGS)
    settings.update(raw)
    return settings


def normalize_audio_tags(value: object) -> list[str]:
    """Normalize `curious` and `[curious]` to a safe API tag name."""
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        raise ValueError("audio_tags must be a string or list of strings")

    tags: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError("every audio tag must be a string")
        tag = raw.strip()
        if tag.startswith("[") and tag.endswith("]"):
            tag = tag[1:-1].strip()
        if not tag:
            continue
        if not _TAG_PATTERN.fullmatch(tag):
            raise ValueError(
                f"invalid audio tag {raw!r}; use a plain tag such as 'curious'"
            )
        tags.append(tag)
    return tags


def opening_mood_tag(scene: dict) -> list[str] | None:
    """Resolve an optional mood-selected opener without imposing one default."""
    for field in ("opening_mood", "delivery_mood", "tone"):
        if field not in scene:
            continue
        raw = str(scene.get(field) or "").strip().lower()
        if raw not in OPENING_MOOD_TAGS:
            allowed = ", ".join(sorted(OPENING_MOOD_TAGS))
            raise ValueError(
                f"invalid {field} {raw!r}; choose a supported mood: {allowed}"
            )
        tag = OPENING_MOOD_TAGS[raw]
        return [tag] if tag else []
    return None


def infer_audio_tags(scene: dict, index: int, total: int) -> list[str]:
    """Conservative fallback for older scripts that predate scene.audio_tags."""
    text = str(scene.get("text") or "").strip()
    function = str(scene.get("visual_function") or "").strip().lower()

    if index == 0:
        selected = opening_mood_tag(scene)
        if selected is not None:
            return selected
    if index == total - 1:
        return ["whispers"]
    if text.endswith("?"):
        return ["curious"]
    if "!" in text or function in {"transformation", "scale_shift"}:
        return ["excited"]
    return []


def scene_audio_tags(
    script: dict,
    scene: dict,
    index: int,
    total: int,
    model_id: str,
) -> list[str]:
    if model_id != DEFAULT_MODEL_ID:
        return []
    if "audio_tags" in scene:
        return normalize_audio_tags(scene.get("audio_tags"))
    if not script.get("auto_audio_tags", True):
        return []
    return infer_audio_tags(scene, index, total)


def tts_fingerprint(script: "dict", model_id: "str") -> "str":
    """Identity of the voice take: text+tags+voice+model+stability. If any of it
    changes, a cached vo.mp3 is stale and must be regenerated."""
    import hashlib
    text, tags = build_tts_text(script, model_id)
    basis = "|".join([
        text,
        json.dumps(tags, ensure_ascii=False),
        str(script.get("elevenlabs_voice_id", "")),
        str(script.get("elevenlabs_voice_name", "")),
        str(model_id),
        str(script.get("elevenlabs_stability_mode", "")),
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def build_tts_text(script: dict, model_id: str) -> tuple[str, list[list[str]]]:
    scenes = script.get("scenes") or []
    chunks: list[str] = []
    applied: list[list[str]] = []
    total = len(scenes)

    for index, scene in enumerate(scenes):
        text = str(scene.get("text") or "").strip()
        if not text:
            raise ValueError(f"scene {index} has no narration text")
        tags = scene_audio_tags(script, scene, index, total, model_id)
        prefix = " ".join(f"[{tag}]" for tag in tags)
        chunks.append(f"{prefix} {text}".strip())
        applied.append(tags)

    tagged_text = " ".join(chunks)
    if model_id == DEFAULT_MODEL_ID and len(tagged_text) > V3_CHARACTER_LIMIT:
        raise ValueError(
            f"Eleven v3 request is {len(tagged_text):,} characters; "
            f"limit is {V3_CHARACTER_LIMIT:,}. Shorten the script or reduce audio tags."
        )
    return tagged_text, applied


def build_request(script: dict) -> tuple[str, str, str | None, dict, dict, list[list[str]]]:
    voice_id = resolve_voice_id(script)
    model_id = resolve_model_id(script)
    stability_mode = resolve_stability_mode(script, model_id)
    voice_settings = resolve_voice_settings(script, model_id)
    text, applied_tags = build_tts_text(script, model_id)
    payload: dict[str, object] = {
        "text": text,
        "model_id": model_id,
        "voice_settings": voice_settings,
    }
    if script.get("language_code"):
        payload["language_code"] = script["language_code"]
    if script.get("elevenlabs_seed") is not None:
        payload["seed"] = int(script["elevenlabs_seed"])
    return voice_id, model_id, stability_mode, voice_settings, payload, applied_tags


def apply_scene_timings(script: dict, alignment: dict) -> None:
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not chars or len(chars) != len(starts) or len(chars) != len(ends):
        raise RuntimeError("ElevenLabs returned incomplete character alignment")

    aligned_text = "".join(chars)
    pos = 0
    for index, scene in enumerate(script["scenes"]):
        text = scene["text"]
        start_index = aligned_text.find(text, pos)
        if start_index < 0:
            raise RuntimeError(
                f"could not locate scene {index} text in ElevenLabs alignment"
            )
        end_index = start_index + len(text)
        scene["_t0"] = starts[min(start_index, len(starts) - 1)]
        scene["_t1"] = ends[min(end_index - 1, len(ends) - 1)]
        pos = end_index

    for index, scene in enumerate(script["scenes"]):
        next_start = (
            script["scenes"][index + 1]["_t0"]
            if index + 1 < len(script["scenes"])
            else scene["_t1"] + 2.0
        )
        scene["start"] = round(scene["_t0"], 3)
        scene["duration"] = round(
            max(2.0, next_start - scene["_t0"]) + (0.4 if index == 0 else 0),
            3,
        )
        del scene["_t0"], scene["_t1"]


def _call_elevenlabs(voice_id: str, payload: dict) -> dict:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")

    query = urllib.parse.urlencode({"output_format": "mp3_44100_128"})
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
        f"?{query}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1_000]
        raise RuntimeError(
            f"ElevenLabs TTS failed with HTTP {error.code}: {detail}"
        ) from error


def tts(build_dir: str | os.PathLike[str]) -> None:
    root = Path(build_dir)
    script = _read_script(root)
    (
        voice_id,
        model_id,
        stability_mode,
        voice_settings,
        payload,
        applied_tags,
    ) = build_request(script)
    voice_name = resolve_voice_name(script, voice_id)

    response = _call_elevenlabs(voice_id, payload)
    audio = response.get("audio_base64")
    alignment = response.get("alignment") or response.get("normalized_alignment")
    if not audio or not alignment:
        raise RuntimeError("ElevenLabs response omitted audio or alignment")

    (root / "vo.mp3").write_bytes(base64.b64decode(audio))
    apply_scene_timings(script, alignment)
    script["voiceover"] = "vo.mp3"
    script["elevenlabs_voice_id"] = voice_id
    script["elevenlabs_voice_name"] = voice_name
    script["elevenlabs_model"] = model_id
    if stability_mode:
        script["elevenlabs_stability_mode"] = stability_mode
    script["voiceover_config"] = {
        "provider": "ElevenLabs",
        "voice_id": voice_id,
        "voice_name": voice_name,
        "model_id": model_id,
        "stability_mode": stability_mode,
        "voice_settings": voice_settings,
        "audio_tags_enabled": model_id == DEFAULT_MODEL_ID,
    }
    (root / "script.json").write_text(
        json.dumps(script, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "tts_fingerprint": tts_fingerprint(script, model_id),
        "provider": "ElevenLabs",
        "voice_id": voice_id,
        "voice_name": voice_name,
        "model_id": model_id,
        "stability_mode": stability_mode,
        "voice_settings": voice_settings,
        "request_characters": len(str(payload["text"])),
        "scene_audio_tags": [
            {"scene": index, "tags": tags}
            for index, tags in enumerate(applied_tags)
            if tags
        ],
    }
    (root / "voiceover-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    total = sum(scene["duration"] for scene in script["scenes"])
    print(
        f"vo.mp3 written with {voice_name}/{model_id}/{stability_mode or 'custom'}, "
        f"{len(script['scenes'])} scenes, total {total:.1f}s"
    )


if __name__ == "__main__":
    tts(sys.argv[1])
