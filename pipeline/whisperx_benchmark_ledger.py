"""Aggregate WhisperX shadow runs and enforce a conservative promotion gate.

The ledger is evidence only. It never changes the active alignment source.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import statistics
from typing import Any

MIN_SUCCESSFUL_RUNS = 20
MIN_MANUAL_REFERENCE_RUNS = 5
MAX_FAILURE_RATE = 0.05
MIN_MEDIAN_REFERENCE_IMPROVEMENT = 0.03
MAX_COVERAGE_REGRESSION = 0.005


def _load(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _number(payload: dict[str, Any], *keys: str) -> float | None:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def build(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    reports: list[dict[str, Any]] = []
    for path in sorted((root / "build").glob("*/alignment-challenger.json")):
        payload = _load(path)
        if payload:
            payload["_path"] = str(path.relative_to(root))
            reports.append(payload)

    failures = [item for item in reports if item.get("status") == "failed" or item.get("disposition") == "reject_run"]
    successful = [item for item in reports if item not in failures]
    manual = [item for item in successful if item.get("manual_reference")]
    candidates = [
        item
        for item in successful
        if item.get("disposition") in {"candidate_for_manual_review", "candidate_for_promotion_ledger"}
    ]

    current_coverage = [
        value
        for item in successful
        if (value := _number(item, "current", "script_word_coverage")) is not None
    ]
    challenger_coverage = [
        value
        for item in successful
        if (value := _number(item, "challenger", "script_word_coverage")) is not None
    ]
    current_reference = [
        value
        for item in manual
        if (value := _number(item, "current", "manual_reference_word_start_error", "median_seconds"))
        is not None
    ]
    challenger_reference = [
        value
        for item in manual
        if (value := _number(item, "challenger", "manual_reference_word_start_error", "median_seconds"))
        is not None
    ]
    current_scene = [
        value
        for item in successful
        if (value := _number(item, "current", "scene_start_error", "median_seconds")) is not None
    ]
    challenger_scene = [
        value
        for item in successful
        if (value := _number(item, "challenger", "scene_start_error", "median_seconds")) is not None
    ]

    failure_rate = len(failures) / len(reports) if reports else 0.0
    median_current_coverage = _median(current_coverage)
    median_challenger_coverage = _median(challenger_coverage)
    median_current_reference = _median(current_reference)
    median_challenger_reference = _median(challenger_reference)
    reference_improvement = None
    if median_current_reference is not None and median_challenger_reference is not None:
        reference_improvement = median_current_reference - median_challenger_reference

    checks = {
        "successful_runs": {
            "passed": len(successful) >= MIN_SUCCESSFUL_RUNS,
            "actual": len(successful),
            "required": MIN_SUCCESSFUL_RUNS,
        },
        "manual_reference_runs": {
            "passed": len(manual) >= MIN_MANUAL_REFERENCE_RUNS,
            "actual": len(manual),
            "required": MIN_MANUAL_REFERENCE_RUNS,
        },
        "failure_rate": {
            "passed": failure_rate <= MAX_FAILURE_RATE,
            "actual": round(failure_rate, 4),
            "maximum": MAX_FAILURE_RATE,
        },
        "coverage": {
            "passed": (
                median_current_coverage is not None
                and median_challenger_coverage is not None
                and median_challenger_coverage >= median_current_coverage - MAX_COVERAGE_REGRESSION
            ),
            "current_median": median_current_coverage,
            "challenger_median": median_challenger_coverage,
            "maximum_regression": MAX_COVERAGE_REGRESSION,
        },
        "manual_reference_improvement": {
            "passed": (
                reference_improvement is not None
                and reference_improvement >= MIN_MEDIAN_REFERENCE_IMPROVEMENT
            ),
            "current_median_seconds": median_current_reference,
            "challenger_median_seconds": median_challenger_reference,
            "improvement_seconds": reference_improvement,
            "minimum_improvement_seconds": MIN_MEDIAN_REFERENCE_IMPROVEMENT,
        },
    }
    promotion_eligible = all(item["passed"] for item in checks.values())
    ledger = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "shadow_only",
        "production_alignment_source": "unchanged",
        "automatic_promotion": False,
        "promotion_eligible_for_human_decision": promotion_eligible,
        "counts": {
            "total_runs": len(reports),
            "successful_runs": len(successful),
            "failed_runs": len(failures),
            "manual_reference_runs": len(manual),
            "candidate_runs": len(candidates),
        },
        "aggregate": {
            "failure_rate": round(failure_rate, 4),
            "current_script_word_coverage_median": median_current_coverage,
            "challenger_script_word_coverage_median": median_challenger_coverage,
            "current_scene_start_error_median_seconds": _median(current_scene),
            "challenger_scene_start_error_median_seconds": _median(challenger_scene),
            "current_manual_word_start_error_median_seconds": median_current_reference,
            "challenger_manual_word_start_error_median_seconds": median_challenger_reference,
            "manual_reference_improvement_seconds": reference_improvement,
        },
        "promotion_checks": checks,
        "runs": [
            {
                "slug": item.get("slug"),
                "path": item.get("_path"),
                "created_at": item.get("created_at"),
                "disposition": item.get("disposition"),
                "manual_reference": bool(item.get("manual_reference")),
                "model": item.get("model"),
            }
            for item in reports[-100:]
        ],
    }
    output = root / "pipeline" / "whisperx-benchmark-ledger.json"
    output.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown = [
        "# WhisperX Shadow Benchmark Ledger",
        "",
        f"Generated: {ledger['generated_at']}",
        "",
        f"- Total runs: {len(reports)}",
        f"- Successful runs: {len(successful)} / {MIN_SUCCESSFUL_RUNS} required",
        f"- Manual timing references: {len(manual)} / {MIN_MANUAL_REFERENCE_RUNS} required",
        f"- Failed runs: {len(failures)} ({failure_rate:.1%})",
        f"- Eligible for human promotion decision: **{'yes' if promotion_eligible else 'no'}**",
        "",
        "WhisperX remains shadow-only. This ledger cannot switch production alignment.",
        "",
        "## Promotion checks",
        "",
    ]
    for name, item in checks.items():
        markdown.append(f"- {'PASS' if item['passed'] else 'WAIT'} — `{name}`: {json.dumps(item, sort_keys=True)}")
    (root / "pipeline" / "WHISPERX_BENCHMARK.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", nargs="?", default=".")
    args = parser.parse_args()
    print(json.dumps(build(args.repo_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
