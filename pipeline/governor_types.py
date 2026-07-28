"""Operational Governor for the resumable video pipeline.

The creative learner in :mod:`learn` decides what makes a better video.  This
module has a separate job: make production observable, bounded, recoverable,
and progressively more efficient without weakening any quality requirement.

It intentionally uses only the Python standard library so it is available
before the pipeline's heavier ML dependencies finish importing.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import uuid
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
MEDIA_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a"}
TRANSIENT_PATTERNS = (
    "timeout", "timed out", "rate limit", "too many requests", "429",
    "500", "502", "503", "504", "connection reset", "connection refused",
    "connection aborted", "temporary failure", "temporarily unavailable",
    "service unavailable", "bad gateway", "gateway timeout", "network",
    "eai_again", "broken pipe", "remote disconnected", "try again",
    "resource exhausted", "server error", "upstream",
)
DETERMINISTIC_PATTERNS = (
    "missing elevenlabs_api_key", "missing pexels_api_key", "no script.json",
    "not valid json", "missing title/slug", "unsupported", "invalid argument",
    "permission denied", "no such file", "insufficient credits", "quota exceeded",
)


# Conservative defaults are replaced by history-derived values only after five
# successful observations.  The learned value is always bounded by floor/hard.
POLICIES: dict[str, dict[str, float]] = {
    "probe": {"floor": 10, "soft": 30, "idle": 20, "hard": 60},
    "font": {"floor": 30, "soft": 120, "idle": 90, "hard": 240},
    "tts": {"floor": 60, "soft": 240, "idle": 180, "hard": 480},
    "transcribe": {"floor": 180, "soft": 600, "idle": 360, "hard": 900},
    "align": {"floor": 30, "soft": 180, "idle": 120, "hard": 300},
    "footage": {"floor": 60, "soft": 300, "idle": 180, "hard": 600},
    "credits": {"floor": 30, "soft": 180, "idle": 120, "hard": 300},
    "motion": {"floor": 180, "soft": 720, "idle": 360, "hard": 1200},
    "hero": {"floor": 180, "soft": 720, "idle": 360, "hard": 1200},
    "curate": {"floor": 180, "soft": 720, "idle": 360, "hard": 1200},
    "prep": {"floor": 120, "soft": 480, "idle": 300, "hard": 900},
    "assemble": {"floor": 90, "soft": 480, "idle": 240, "hard": 900},
    "ffmpeg": {"floor": 90, "soft": 480, "idle": 240, "hard": 900},
    "shortcut": {"floor": 120, "soft": 600, "idle": 300, "hard": 900},
    "altsheet": {"floor": 30, "soft": 180, "idle": 120, "hard": 300},
    "quality": {"floor": 120, "soft": 900, "idle": 420, "hard": 1500},
    "build_pass": {"floor": 600, "soft": 1500, "idle": 900, "hard": 1800},
    "general": {"floor": 60, "soft": 300, "idle": 180, "hard": 600},
}


@dataclasses.dataclass(frozen=True)
class StageSpec:
    """Classification and safety metadata for one subprocess."""

    name: str
    item: str | None = None
    expected_outputs: tuple[Path, ...] = ()
    min_output_bytes: int = 1
    retry_safe: bool = True

    @property
    def label(self) -> str:
        return f"{self.name}:{self.item}" if self.item else self.name


@dataclasses.dataclass(frozen=True)
class PolicyDecision:
    soft_timeout_s: float
    idle_timeout_s: float
    hard_timeout_s: float
    source: str
    sample_count: int
    historical_p95_s: float | None = None


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile without a third-party dependency."""
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    weight = rank - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def redact_secrets(text: str) -> str:
    """Remove common credential forms while preserving diagnostic context."""
    value = text or ""
    value = re.sub(
        r"(?i)(api[_-]?key|authorization|token|secret)\s*[:=]\s*(?:bearer\s+)?\S+",
        r"\1=<redacted>",
        value,
    )
    value = re.sub(r"(?i)\bbearer\s+[a-z0-9._~+/-]{12,}", "Bearer <redacted>", value)
    value = re.sub(r"\b(?:sk|xi)-[A-Za-z0-9_-]{12,}\b", "<redacted-key>", value)
    return value


def normalize_error(text: str, limit: int = 420) -> str:
    """Produce a stable, secret-safe error signature for incident clustering."""
    value = redact_secrets(text or "unknown failure").strip().lower()
    value = re.sub(r"\b[a-f0-9]{20,}\b", "<id>", value)
    value = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", value)
    value = re.sub(r"(?:[a-zA-Z]:)?[/\\][^\s:]+", "<path>", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def failure_fingerprint(stage: str, kind: str, text: str) -> str:
    normalized = normalize_error(text)
    digest = hashlib.sha256(f"{stage}|{kind}|{normalized}".encode("utf-8")).hexdigest()
    return digest[:16]


def classify_failure(text: str) -> str:
    # Keep status numbers (429/5xx) for classification; fingerprint
    # normalization intentionally removes them later to cluster equivalent errors.
    normalized = re.sub(r"\s+", " ", redact_secrets(text or "").lower()).strip()[:4000]
    if any(pattern in normalized for pattern in DETERMINISTIC_PATTERNS):
        return "deterministic"
    if any(pattern in normalized for pattern in TRANSIENT_PATTERNS):
        return "transient"
    return "unknown"


def _int_arg(value: str | None) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _command_parts(command: Sequence[str] | str, shell: bool = False) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command) if not shell else [command]
    return [str(part) for part in command]


def classify_command(
    command: Sequence[str] | str,
    build_dir: str | os.PathLike[str],
    *,
    shell: bool = False,
    stage_override: str | None = None,
) -> StageSpec:
    """Map a command to a stage and any output safe to quarantine on failure."""
    bd = Path(build_dir)
    parts = _command_parts(command, shell=shell)
    basenames = [Path(part).name.lower() for part in parts]

    if stage_override:
        return StageSpec(stage_override)

    executable = basenames[0] if basenames else ""
    script_index = next((i for i, name in enumerate(basenames) if name.endswith(".py")), None)
    script = basenames[script_index] if script_index is not None else ""
    args = parts[script_index + 1 :] if script_index is not None else parts[1:]

    if executable == "ffprobe":
        return StageSpec("probe", retry_safe=True)
    if executable == "ffmpeg":
        output = Path(parts[-1]) if len(parts) > 1 and not parts[-1].startswith("-") else None
        outputs = (output,) if output else ()
        return StageSpec("ffmpeg", expected_outputs=outputs, min_output_bytes=10_000)
    if "fonttools.varlib.instancer" in " ".join(parts).lower():
        return StageSpec("font")
    if script == "tts.py":
        return StageSpec("tts", expected_outputs=(bd / "vo.mp3",), min_output_bytes=2_000)
    if script == "transcribe.py":
        return StageSpec("transcribe", expected_outputs=(bd / "words.json",), min_output_bytes=20)
    if script == "align.py":
        return StageSpec("align")
    if script == "footage.py":
        item = args[-1] if args else None
        if item == "credits":
            return StageSpec("credits", expected_outputs=(bd / "CREDITS.txt",), min_output_bytes=1)
        index = _int_arg(item)
        output = (bd / f"clip_{index:02d}.mp4",) if index is not None else ()
        return StageSpec("footage", str(index) if index is not None else None, output, 100_000)
    if script == "motion.py":
        index = _int_arg(args[-1] if args else None)
        output = (bd / f"clip_{index:02d}.mp4",) if index is not None else ()
        return StageSpec("motion", str(index) if index is not None else None, output, 100_000)
    if script == "hero.py":
        index = _int_arg(args[-1] if args else None)
        output = (bd / f"clip_{index:02d}.mp4",) if index is not None else ()
        return StageSpec("hero", str(index) if index is not None else None, output, 100_000)
    if script == "curate.py":
        return StageSpec("curate", expected_outputs=(bd / "final.mp4",), min_output_bytes=100_000)
    if script == "prep.py":
        return StageSpec("prep")
    if script == "assemble.py":
        mode = args[-2] if len(args) >= 2 else "scene"
        index = _int_arg(args[-1] if args else None)
        if index is None:
            return StageSpec("assemble", mode)
        prefix = "youtube_seg" if mode == "youtube-scene" else "seg"
        return StageSpec("assemble", f"{mode}:{index}", (bd / f"{prefix}_{index:02d}.mp4",), 100_000)
    if script == "shortcut.py":
        return StageSpec("shortcut", expected_outputs=(bd / "final_short.mp4",), min_output_bytes=100_000)
    if script == "altsheet.py":
        return StageSpec("altsheet", expected_outputs=(bd / "alts_sheet.jpg",), min_output_bytes=5_000)
    if script == "quality_gate.py":
        return StageSpec("quality", expected_outputs=(bd / "quality_report.json",), min_output_bytes=20)
    if script == "governed_build.py":
        return StageSpec("build_pass")
    return StageSpec("general")


def artifact_signature(build_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Cheap signal that useful pipeline output is still changing.

    Governor bookkeeping is excluded, otherwise its own heartbeat would look
    like pipeline progress and a zombie worker could never be detected.
    """
    root = Path(build_dir)
    if not root.exists():
        return {"count": 0, "bytes": 0, "latest_mtime_ns": 0, "digest": "0"}
    entries: list[str] = []
    total = 0
    latest = 0
    count = 0
    excluded = {"governor-summary.json", "render-status.json", "quality_report.json"}
    try:
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in {"governor", ".git", "__pycache__"}]
            for name in files:
                if name in excluded or name.endswith(".partial"):
                    continue
                path = Path(current) / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                rel = path.relative_to(root).as_posix()
                count += 1
                total += stat.st_size
                latest = max(latest, stat.st_mtime_ns)
                entries.append(f"{rel}:{stat.st_size}:{stat.st_mtime_ns}")
    except OSError:
        pass
    digest = hashlib.sha1("\n".join(sorted(entries)).encode("utf-8")).hexdigest()[:12]
    return {"count": count, "bytes": total, "latest_mtime_ns": latest, "digest": digest}


def signatures_differ(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return before.get("digest") != after.get("digest")


def retry_budget(failure_class: str, occurrence: int, *, historical_recovery_rate: float | None = None) -> int:
    """Bounded retry policy.  Never retries known deterministic failures."""
    if failure_class == "deterministic":
        return 0
    budget = 2 if failure_class == "transient" else 1
    if historical_recovery_rate is not None and historical_recovery_rate >= 0.6:
        budget += 1
    # Circuit breaker: no fingerprint receives more than three retries.
    return min(3, budget)
