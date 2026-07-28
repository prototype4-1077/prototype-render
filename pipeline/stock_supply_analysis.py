"""Analyze stock-selection supply from persisted narrative-fidelity evidence.

The current selector permanently excludes used and banned IDs. This report does
not relax that rule. It measures direct-match candidate counts, stock fallbacks,
and rejection reasons so a future cooldown experiment is evidence-led rather
than triggered by the raw size of the exclusion set alone.
"""
from __future__ import annotations

from collections import Counter
import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "pipeline" / "stock_supply_report.json"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def build(repo_root: Path = ROOT, output: Path = OUTPUT) -> dict[str, Any]:
    memory = load(repo_root / "pipeline" / "memory.json", {}) or {}
    if not isinstance(memory, dict):
        memory = {}
    rows = []
    reports = 0
    for build_dir in sorted((repo_root / "build").glob("*")):
        report_path = build_dir / "narrative_fidelity_report.json"
        if not report_path.exists():
            continue
        payload = load(report_path, {}) or {}
        if not isinstance(payload, dict):
            continue
        reports += 1
        for row in safe_list(payload.get("scenes")):
            if not isinstance(row, dict):
                continue
            decisions = [item for item in safe_list(row.get("candidate_decisions")) if isinstance(item, dict)]
            result = str(row.get("result") or "unknown")
            rows.append({
                "slug": build_dir.name,
                "scene_index": row.get("scene_index"),
                "result": result,
                "candidate_count": len(decisions),
                "candidate_decisions": decisions,
                "fallback_reason": row.get("fallback_reason") or (row.get("plan") or {}).get("fallback_reason") if isinstance(row.get("plan"), dict) else row.get("fallback_reason"),
            })

    results = Counter(row["result"] for row in rows)
    candidate_counts = [row["candidate_count"] for row in rows if row["candidate_count"] > 0]
    zero_candidate = sum(
        row["candidate_count"] == 0 and row["result"] in {
            "literal_storyboard", "effects_still", "stock_fallback_from_storyboard",
        }
        for row in rows
    )
    low_candidate = sum(0 < row["candidate_count"] <= 2 for row in rows)
    fallback = sum(row["result"] in {"literal_storyboard", "effects_still", "stock_fallback_from_storyboard"} for row in rows)
    rejection_reasons: Counter[str] = Counter()
    coverage_buckets: Counter[str] = Counter()
    for row in rows:
        for decision in row["candidate_decisions"]:
            reason = str(decision.get("reason") or decision.get("decision") or decision.get("status") or "unknown")
            rejection_reasons[reason] += 1
            coverage = decision.get("coverage") or decision.get("anchor_coverage")
            try:
                value = float(coverage)
            except (TypeError, ValueError):
                continue
            if value >= 0.75:
                coverage_buckets["high"] += 1
            elif value >= 0.40:
                coverage_buckets["medium"] += 1
            else:
                coverage_buckets["low"] += 1

    scene_count = len(rows)
    fallback_rate = fallback / scene_count if scene_count else 0.0
    low_supply_rate = (zero_candidate + low_candidate) / scene_count if scene_count else 0.0
    used = len(memory.get("used_ids") or [])
    banned = len(memory.get("banned_ids") or [])
    evidence_strength = "sufficient" if reports >= 5 and scene_count >= 50 else "developing"
    if evidence_strength == "sufficient" and low_supply_rate >= 0.35:
        state = "candidate_starvation_signal"
        action = (
            "Run a shadow cooldown experiment: allow old approved IDs only in the challenger, "
            "never banned IDs, and compare direct-match quality before changing production."
        )
    elif evidence_strength == "sufficient":
        state = "no_current_starvation_signal"
        action = "Keep permanent exclusion unchanged; continue monitoring candidate supply and fallback rate."
    else:
        state = "insufficient_evidence"
        action = (
            "Persist candidate-decision reports for more completed renders before evaluating a cooldown. "
            "The exclusion-set size alone is not evidence of starvation."
        )

    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "reports_analyzed": reports,
        "scenes_analyzed": scene_count,
        "result_counts": dict(results),
        "candidate_count_samples": len(candidate_counts),
        "mean_candidate_count_when_recorded": round(sum(candidate_counts) / len(candidate_counts), 3) if candidate_counts else None,
        "zero_candidate_fallbacks": zero_candidate,
        "low_candidate_scenes": low_candidate,
        "fallback_count": fallback,
        "fallback_rate": round(fallback_rate, 4),
        "low_supply_rate": round(low_supply_rate, 4),
        "top_rejection_reasons": dict(rejection_reasons.most_common(20)),
        "anchor_coverage_buckets": dict(coverage_buckets),
        "permanent_exclusion_counts": {"used_ids": used, "banned_ids": banned},
        "evidence_strength": evidence_strength,
        "state": state,
        "recommended_action": action,
        "measurement_boundary": (
            "Candidate decisions reflect narrative-fidelity reranking after search. This report cannot "
            "reconstruct every raw API result or prove that exclusions caused a missing candidate."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args(argv)
    report = build(Path(args.repo_root).resolve(), Path(args.output))
    print(json.dumps({
        "reports_analyzed": report["reports_analyzed"],
        "scenes_analyzed": report["scenes_analyzed"],
        "state": report["state"],
        "fallback_rate": report["fallback_rate"],
        "low_supply_rate": report["low_supply_rate"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
