"""Run WhisperX as a read-only timing challenger against the production aligner.

This module never edits script.json, words.json, captions, overlays, or scene timing.
It writes compact benchmark evidence to alignment-challenger.json and keeps the
full challenger word list in alignment-challenger-words.json.

Usage:
  python3 pipeline/whisperx_challenger.py build/<slug>
  python3 pipeline/whisperx_challenger.py build/<slug> --raw-result fixture.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import statistics
import time
from typing import Any, Iterable

SCHEMA_VERSION = 1
SUMMARY_NAME = "alignment-challenger.json"
WORDS_NAME = "alignment-challenger-words.json"
REFERENCE_NAME = "alignment-reference.json"
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*|[^\w\s]", re.UNICODE)


def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(token: str) -> str:
    return re.sub(r"[^a-z0-9']", "", str(token).lower().replace("’", "'"))


def percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _script_tokens(script: dict[str, Any]) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    for scene_index, scene in enumerate(script.get("scenes") or []):
        for word_index, raw in enumerate(_TOKEN_RE.findall(str(scene.get("text") or ""))):
            norm = normalize(raw)
            if not norm:
                continue
            tokens.append(
                {
                    "w": raw,
                    "n": norm,
                    "scene_index": scene_index,
                    "word_index": word_index,
                }
            )
    return tokens


def _normalize_words(words: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(words, list):
        return normalized
    for item in words:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("w") or item.get("word") or "").strip()
        token = normalize(raw)
        if not token:
            continue
        try:
            start = float(item.get("s") if item.get("s") is not None else item.get("start"))
            end = float(item.get("e") if item.get("e") is not None else item.get("end"))
        except (TypeError, ValueError):
            continue
        if start < 0 or end < start:
            continue
        normalized.append({"w": raw, "n": token, "s": round(start, 4), "e": round(end, 4)})
    return normalized


def flatten_whisperx(payload: dict[str, Any]) -> list[dict[str, Any]]:
    direct = payload.get("word_segments")
    if isinstance(direct, list):
        return _normalize_words(direct)
    words: list[dict[str, Any]] = []
    for segment in payload.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        words.extend(segment.get("words") or [])
    return _normalize_words(words)


def map_script_to_observed(
    script_tokens: list[dict[str, Any]], observed: list[dict[str, Any]]
) -> dict[int, int]:
    left = [item["n"] for item in script_tokens]
    right = [item["n"] for item in observed]
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    mapping: dict[int, int] = {}
    for left_start, right_start, size in matcher.get_matching_blocks():
        for offset in range(size):
            mapping[left_start + offset] = right_start + offset
    return mapping


def edit_distance(left: list[str], right: list[str]) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, left_item in enumerate(left, 1):
        current = [i]
        for j, right_item in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (left_item != right_item),
                )
            )
        previous = current
    return previous[-1]


def _coverage(script_count: int, mapping: dict[int, int]) -> float:
    return len(mapping) / script_count if script_count else 0.0


def _special_indexes(tokens: list[dict[str, Any]]) -> list[int]:
    result: list[int] = []
    for index, item in enumerate(tokens):
        raw = str(item.get("w") or "")
        if any(char.isdigit() for char in raw) or "'" in raw or "’" in raw:
            result.append(index)
    return result


def _source_metrics(
    name: str,
    script_tokens: list[dict[str, Any]],
    observed: list[dict[str, Any]],
    script: dict[str, Any],
    reference_words: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    mapping = map_script_to_observed(script_tokens, observed)
    script_norm = [item["n"] for item in script_tokens]
    observed_norm = [item["n"] for item in observed]
    scene_first: dict[int, int] = {}
    scene_last: dict[int, int] = {}
    for index, token in enumerate(script_tokens):
        scene_index = int(token["scene_index"])
        scene_first.setdefault(scene_index, index)
        scene_last[scene_index] = index

    scene_start_errors: list[float] = []
    phrase_end_errors: list[float] = []
    scene_rows: list[dict[str, Any]] = []
    for scene_index, scene in enumerate(script.get("scenes") or []):
        first_index = scene_first.get(scene_index)
        last_index = scene_last.get(scene_index)
        observed_start = None
        observed_end = None
        if first_index in mapping:
            observed_start = observed[mapping[first_index]]["s"]
        if last_index in mapping:
            observed_end = observed[mapping[last_index]]["e"]
        planned_start = float(scene.get("start") or 0.0)
        planned_end = planned_start + float(scene.get("duration") or 0.0)
        start_error = abs(observed_start - planned_start) if observed_start is not None else None
        end_error = abs(observed_end - planned_end) if observed_end is not None else None
        if start_error is not None:
            scene_start_errors.append(start_error)
        if end_error is not None:
            phrase_end_errors.append(end_error)
        scene_rows.append(
            {
                "scene_index": scene_index,
                "planned_start": round(planned_start, 3),
                "observed_start": round(observed_start, 3) if observed_start is not None else None,
                "start_abs_error": round(start_error, 3) if start_error is not None else None,
                "planned_end": round(planned_end, 3),
                "observed_last_word_end": round(observed_end, 3) if observed_end is not None else None,
                "end_abs_error": round(end_error, 3) if end_error is not None else None,
            }
        )

    reference_start_errors: list[float] = []
    if reference_words:
        reference_mapping = map_script_to_observed(script_tokens, reference_words)
        for script_index, observed_index in mapping.items():
            reference_index = reference_mapping.get(script_index)
            if reference_index is None:
                continue
            reference_start_errors.append(
                abs(observed[observed_index]["s"] - reference_words[reference_index]["s"])
            )

    specials = _special_indexes(script_tokens)
    special_matched = sum(index in mapping for index in specials)
    error_rate = edit_distance(script_norm, observed_norm) / max(len(script_norm), 1)
    return {
        "source": name,
        "word_count": len(observed),
        "matched_script_words": len(mapping),
        "script_word_coverage": round(_coverage(len(script_tokens), mapping), 4),
        "transcript_word_error_rate": round(error_rate, 4),
        "special_token_count": len(specials),
        "special_token_coverage": round(special_matched / max(len(specials), 1), 4),
        "scene_start_error": {
            "samples": len(scene_start_errors),
            "median_seconds": round(statistics.median(scene_start_errors), 4) if scene_start_errors else None,
            "p95_seconds": round(percentile(scene_start_errors, 0.95), 4) if scene_start_errors else None,
        },
        "phrase_end_error": {
            "samples": len(phrase_end_errors),
            "median_seconds": round(statistics.median(phrase_end_errors), 4) if phrase_end_errors else None,
            "p95_seconds": round(percentile(phrase_end_errors, 0.95), 4) if phrase_end_errors else None,
        },
        "manual_reference_word_start_error": {
            "samples": len(reference_start_errors),
            "median_seconds": round(statistics.median(reference_start_errors), 4)
            if reference_start_errors
            else None,
            "p95_seconds": round(percentile(reference_start_errors, 0.95), 4)
            if reference_start_errors
            else None,
        },
        "scene_rows": scene_rows,
        "mapping": mapping,
    }


def _disagreement(
    script_tokens: list[dict[str, Any]],
    current_words: list[dict[str, Any]],
    challenger_words: list[dict[str, Any]],
) -> dict[str, Any]:
    current_map = map_script_to_observed(script_tokens, current_words)
    challenger_map = map_script_to_observed(script_tokens, challenger_words)
    deltas: list[float] = []
    rows: list[dict[str, Any]] = []
    for script_index in sorted(set(current_map) & set(challenger_map)):
        current = current_words[current_map[script_index]]
        challenger = challenger_words[challenger_map[script_index]]
        delta = challenger["s"] - current["s"]
        deltas.append(abs(delta))
        if abs(delta) >= 0.35 and len(rows) < 40:
            rows.append(
                {
                    "script_index": script_index,
                    "word": script_tokens[script_index]["w"],
                    "current_start": current["s"],
                    "challenger_start": challenger["s"],
                    "delta": round(delta, 3),
                }
            )
    return {
        "mutually_matched_words": len(deltas),
        "median_abs_start_delta_seconds": round(statistics.median(deltas), 4) if deltas else None,
        "p95_abs_start_delta_seconds": round(percentile(deltas, 0.95), 4) if deltas else None,
        "large_disagreements": rows,
    }


def _reference_kind(script: dict[str, Any], reference_words: list[dict[str, Any]]) -> str:
    if reference_words:
        return "manual_word_reference"
    provider = str((script.get("voiceover_config") or {}).get("provider") or "").lower()
    if provider == "elevenlabs" and not script.get("user_vo"):
        return "elevenlabs_scene_alignment"
    return "current_pipeline_scene_timing"


def compare(
    build_dir: Path,
    challenger_words: list[dict[str, Any]],
    *,
    runtime_seconds: float,
    model_config: dict[str, Any],
) -> dict[str, Any]:
    script = _load(build_dir / "script.json", {}) or {}
    current_words = _normalize_words(_load(build_dir / "words.json", []))
    reference_payload = _load(build_dir / REFERENCE_NAME, {}) or {}
    reference_words = _normalize_words(reference_payload.get("words") or [])
    tokens = _script_tokens(script)
    current = _source_metrics(
        "current_faster_whisper",
        tokens,
        current_words,
        script,
        reference_words or None,
    )
    challenger = _source_metrics(
        "whisperx",
        tokens,
        challenger_words,
        script,
        reference_words or None,
    )
    disagreement = _disagreement(tokens, current_words, challenger_words)

    current_scene = current["scene_start_error"]["median_seconds"]
    challenger_scene = challenger["scene_start_error"]["median_seconds"]
    coverage_ok = challenger["script_word_coverage"] >= current["script_word_coverage"] - 0.01
    transcript_ok = challenger["transcript_word_error_rate"] <= current["transcript_word_error_rate"] + 0.01
    better_scene = (
        current_scene is not None
        and challenger_scene is not None
        and challenger_scene + 0.05 < current_scene
    )
    manual_samples = challenger["manual_reference_word_start_error"]["samples"]
    if manual_samples:
        current_manual = current["manual_reference_word_start_error"]["median_seconds"]
        challenger_manual = challenger["manual_reference_word_start_error"]["median_seconds"]
        better_reference = (
            current_manual is not None
            and challenger_manual is not None
            and challenger_manual + 0.03 < current_manual
        )
    else:
        better_reference = False

    if not challenger_words or challenger["script_word_coverage"] < 0.85:
        disposition = "reject_run"
    elif manual_samples and better_reference and coverage_ok and transcript_ok:
        disposition = "candidate_for_promotion_ledger"
    elif better_scene and coverage_ok and transcript_ok:
        disposition = "candidate_for_manual_review"
    else:
        disposition = "observe"

    compact_current = {key: value for key, value in current.items() if key != "mapping"}
    compact_challenger = {key: value for key, value in challenger.items() if key != "mapping"}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now,
        "slug": script.get("slug") or build_dir.name,
        "mode": "shadow_only",
        "production_timing_written": False,
        "promotion_automatic": False,
        "reference_kind": _reference_kind(script, reference_words),
        "manual_reference": bool(reference_words),
        "script_sha256": _sha256(build_dir / "script.json"),
        "voiceover_sha256": _sha256(build_dir / "vo.mp3"),
        "model": model_config,
        "runtime_seconds": round(runtime_seconds, 3),
        "current": compact_current,
        "challenger": compact_challenger,
        "disagreement": disagreement,
        "disposition": disposition,
        "promotion_note": (
            "This run may enter the promotion ledger, but production cannot change until "
            "the aggregate gate has at least 20 successful videos and 5 manually reviewed references."
        ),
    }
    _write(build_dir / SUMMARY_NAME, report)
    _write(
        build_dir / WORDS_NAME,
        {
            "schema_version": 1,
            "slug": report["slug"],
            "source": "whisperx",
            "model": model_config,
            "words": challenger_words,
        },
    )
    return report


def run_whisperx(build_dir: Path, model_config: dict[str, Any]) -> list[dict[str, Any]]:
    import whisperx

    audio_path = build_dir / "vo.mp3"
    if not audio_path.exists():
        raise RuntimeError(f"missing voiceover: {audio_path}")
    device = str(model_config["device"])
    model = whisperx.load_model(
        str(model_config["model"]),
        device,
        compute_type=str(model_config["compute_type"]),
        language=str(model_config["language"]),
        download_root=os.environ.get("WHISPERX_DOWNLOAD_ROOT"),
    )
    audio = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, batch_size=int(model_config["batch_size"]))
    language = str(result.get("language") or model_config["language"])
    align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
    aligned = whisperx.align(
        result.get("segments") or [],
        align_model,
        metadata,
        audio,
        device,
        return_char_alignments=False,
    )
    return flatten_whisperx(aligned)


def _model_config() -> dict[str, Any]:
    try:
        version = importlib.metadata.version("whisperx")
    except importlib.metadata.PackageNotFoundError:
        version = "not-installed"
    return {
        "package": "whisperx",
        "version": version,
        "model": os.environ.get("WHISPERX_MODEL", "base.en"),
        "device": os.environ.get("WHISPERX_DEVICE", "cpu"),
        "compute_type": os.environ.get("WHISPERX_COMPUTE_TYPE", "int8"),
        "batch_size": int(os.environ.get("WHISPERX_BATCH_SIZE", "4")),
        "language": os.environ.get("WHISPERX_LANGUAGE", "en"),
        "diarization": False,
    }


def _failure_report(build_dir: Path, exc: BaseException, config: dict[str, Any]) -> dict[str, Any]:
    script = _load(build_dir / "script.json", {}) or {}
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "slug": script.get("slug") or build_dir.name,
        "mode": "shadow_only",
        "production_timing_written": False,
        "promotion_automatic": False,
        "model": config,
        "status": "failed",
        "error_type": type(exc).__name__,
        "error": str(exc)[:1200],
        "disposition": "reject_run",
    }
    _write(build_dir / SUMMARY_NAME, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir")
    parser.add_argument(
        "--raw-result",
        help="WhisperX-shaped JSON fixture; bypasses model inference for tests/replays.",
    )
    parser.add_argument(
        "--non-blocking",
        action="store_true",
        help="Write a failure sidecar and exit zero; appropriate for shadow workflows.",
    )
    args = parser.parse_args(argv)
    build_dir = Path(args.build_dir).resolve()
    config = _model_config()
    started = time.monotonic()
    try:
        if args.raw_result:
            raw = _load(Path(args.raw_result))
            if not isinstance(raw, dict):
                raise RuntimeError("raw WhisperX result must be a JSON object")
            challenger_words = flatten_whisperx(raw)
            config["inference"] = "fixture"
        else:
            challenger_words = run_whisperx(build_dir, config)
            config["inference"] = "live"
        report = compare(
            build_dir,
            challenger_words,
            runtime_seconds=time.monotonic() - started,
            model_config=config,
        )
        print(json.dumps(report, indent=2))
        return 0 if report["disposition"] != "reject_run" else (0 if args.non_blocking else 2)
    except BaseException as exc:
        report = _failure_report(build_dir, exc, config)
        print(json.dumps(report, indent=2))
        if args.non_blocking:
            return 0
        raise


if __name__ == "__main__":
    raise SystemExit(main())
