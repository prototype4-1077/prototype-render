"""Backfill compact observability summaries from durable Governor evidence.

Historical runs cannot be given traces they never emitted. This backfill is
explicit about that limitation: it preserves stage timing/status/incident data
from the committed Governor summary, marks ``single_trace`` false, and never
claims provider spans or costs that were not recorded.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def stage_payload(metrics: Any) -> dict[str, Any]:
    row = metrics if isinstance(metrics, dict) else {}
    return {
        "attempts": int(row.get("attempts") or 0),
        "successes": int(row.get("successes") or 0),
        "failures": int(row.get("failures") or 0),
        "timeouts": int(row.get("timeouts") or 0),
        "total_duration_s": float(row.get("total_duration_s") or 0.0),
        "p50_duration_s": row.get("p50_success_s") or row.get("p50_duration_s"),
        "p95_duration_s": row.get("p95_success_s") or row.get("p95_duration_s"),
        "sample_count": int(row.get("sample_count") or len(row.get("success_durations_s") or [])),
        "source": "governor_summary_backfill",
    }


def build_summary(build: Path) -> dict[str, Any] | None:
    governor = load(build / "governor-summary.json", {}) or {}
    if not isinstance(governor, dict) or not governor:
        return None
    review = load(build / "governor-review.json", {}) or {}
    if not isinstance(review, dict):
        review = {}
    incidents = governor.get("incidents") or []
    recommendations = []
    for item in review.get("recommendations") or []:
        if isinstance(item, dict):
            recommendations.append({
                "priority": item.get("priority"),
                "category": item.get("category"),
                "stage": item.get("stage"),
                "reason": item.get("evidence") or item.get("action"),
                "action": item.get("action"),
                "source": "governor_review_backfill",
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "source": "governor_summary_backfill",
        "historical_limitations": [
            "No OpenTelemetry spans were emitted for this historical run.",
            "Provider calls, scene spans, costs, and credits cannot be reconstructed from Governor summaries.",
        ],
        "slug": governor.get("slug") or build.name,
        "run_id": governor.get("run_id"),
        "github_run_id": governor.get("github_run_id"),
        "status": governor.get("status"),
        "finished_at": governor.get("finished_at"),
        "single_trace": False,
        "span_count": 0,
        "scene_span_count": 0,
        "failure_count": sum(max(1, int(item.get("count") or 1)) for item in incidents if isinstance(item, dict)),
        "stages": {
            str(stage): stage_payload(metrics)
            for stage, metrics in (governor.get("stages") or {}).items()
        },
        "recommendations": recommendations,
        "estimated_cost_usd": None,
        "credits_used": None,
    }


def backfill(repo_root: str | os.PathLike[str], *, force: bool = False) -> list[Path]:
    root = Path(repo_root).resolve()
    written: list[Path] = []
    for build in sorted((root / "build").glob("*")):
        if not build.is_dir() or not (build / "governor-summary.json").exists():
            continue
        target = build / "telemetry-summary.json"
        if target.exists() and not force:
            continue
        payload = build_summary(build)
        if payload:
            atomic_json(target, payload)
            written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    paths = backfill(args.repo_root, force=args.force)
    print(json.dumps({"written": [str(path) for path in paths], "count": len(paths)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
