"""Calibrate the raw system diagnostic to evidence-eligible denominators.

The repository contains many abandoned, experimental, and never-rendered build
packages. Those remain useful inventory, but they are not a fair denominator for
telemetry or review coverage. This policy layer compares telemetry to builds with
render evidence, feedback to reviewable builds, and audience analytics to the
verified published-video receipt catalog.
"""
from __future__ import annotations

from collections import Counter
import argparse
import json
from pathlib import Path
from typing import Any

import system_diagnostics

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "pipeline" / "system_diagnostics"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def pct(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def evidence_coverage(root: Path) -> dict[str, Any]:
    packages = [
        path for path in sorted((root / "build").glob("*"))
        if path.is_dir() and (path / "script.json").exists()
    ]
    render_evidence_names = (
        "governor-summary.json", "render-status.json", "quality_report.json",
        "telemetry-summary.json", "run-id.txt",
    )
    review_names = ("scene-review.json", "scene-review.html")
    feedback_names = ("scene-review-feedback.json", "scene-feedback.request.json")
    observed = [path for path in packages if any((path / name).exists() for name in render_evidence_names)]
    reviewable = [path for path in packages if any((path / name).exists() for name in review_names)]
    telemetry = [path for path in observed if (path / "telemetry-summary.json").exists()]
    feedback = [path for path in reviewable if any((path / name).exists() for name in feedback_names)]
    governor = [path for path in observed if (path / "governor-summary.json").exists()]
    quality = [path for path in observed if (path / "quality_report.json").exists()]

    receipts = load(root / "pipeline" / "yt_published_result.json", {}) or {}
    receipt_slugs = set(receipts) if isinstance(receipts, dict) else set()
    stats_slugs = {
        slug for slug in receipt_slugs
        if (root / "build" / slug / "yt_stats.json").exists()
    }
    missing_stats = sorted(receipt_slugs - stats_slugs)
    return {
        "package_count": len(packages),
        "render_observed_count": len(observed),
        "reviewable_count": len(reviewable),
        "telemetry_count": len(telemetry),
        "governor_summary_count": len(governor),
        "quality_report_count": len(quality),
        "human_feedback_count": len(feedback),
        "youtube_published_receipt_count": len(receipt_slugs),
        "youtube_stats_count": len(stats_slugs),
        "telemetry_coverage_of_render_observed": pct(len(telemetry), len(observed)),
        "human_feedback_coverage_of_reviewable": pct(len(feedback), len(reviewable)),
        "youtube_stats_coverage_of_published": pct(len(stats_slugs), len(receipt_slugs)),
        "inventory_boundary": (
            "package_count includes experiments and abandoned builds; telemetry, feedback, and "
            "audience coverage use render-observed, reviewable, or verified-published denominators."
        ),
        "render_observed_slugs": [path.name for path in observed],
        "reviewable_slugs": [path.name for path in reviewable],
        "feedback_slugs": [path.name for path in feedback],
        "youtube_stats_slugs": sorted(stats_slugs),
        "youtube_missing_stats_slugs": missing_stats,
    }


def _finding(
    *, code: str, priority: str, area: str, title: str,
    evidence: Any, action: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "priority": priority,
        "area": area,
        "title": title,
        "evidence": evidence,
        "action": action,
        "status": "open",
        "automatic_patch": False,
    }


def priority_rank(value: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(value, 5)


def build(root: Path = ROOT) -> dict[str, Any]:
    report = system_diagnostics.diagnostic(root)
    raw_coverage = report.get("coverage") or {}
    coverage = evidence_coverage(root)
    coverage["all_package_file_coverage"] = raw_coverage
    report["coverage"] = coverage
    replaced_codes = {
        "telemetry_coverage_low",
        "human_feedback_coverage_low",
        "free_text_notes_not_structured",
        "permanent_stock_exclusion_growth",
    }
    findings = [
        item for item in (report.get("findings") or [])
        if item.get("code") not in replaced_codes
    ]

    telemetry_ratio = coverage["telemetry_coverage_of_render_observed"]
    if coverage["render_observed_count"] and telemetry_ratio < 0.80:
        findings.append(_finding(
            code="telemetry_coverage_low",
            priority="high" if telemetry_ratio < 0.50 else "medium",
            area="observability",
            title="Render-observed builds are missing telemetry summaries",
            evidence={
                "coverage": telemetry_ratio,
                "telemetry_count": coverage["telemetry_count"],
                "render_observed_count": coverage["render_observed_count"],
            },
            action=(
                "Backfill honest stage summaries from Governor evidence where available and "
                "keep native OpenTelemetry capture mandatory for new renders."
            ),
        ))

    feedback_ratio = coverage["human_feedback_coverage_of_reviewable"]
    if coverage["reviewable_count"] and feedback_ratio < 0.50:
        findings.append(_finding(
            code="human_feedback_coverage_low",
            priority="medium",
            area="learning",
            title="Too few reviewable videos have exported human feedback",
            evidence={
                "coverage": feedback_ratio,
                "feedback_count": coverage["human_feedback_count"],
                "reviewable_count": coverage["reviewable_count"],
                "reviewable_slugs": coverage["reviewable_slugs"],
                "feedback_slugs": coverage["feedback_slugs"],
            },
            action=(
                "Review the highest-value completed videos first. Keep automated risk tags as "
                "screening evidence until James supplies a decision."
            ),
        ))

    audience_ratio = coverage["youtube_stats_coverage_of_published"]
    if coverage["youtube_published_receipt_count"] and audience_ratio < 0.75:
        findings.append(_finding(
            code="youtube_audience_analytics_coverage_low",
            priority="high" if audience_ratio < 0.35 else "medium",
            area="audience_learning",
            title="Most verified YouTube posts have no stored performance snapshot",
            evidence={
                "coverage": audience_ratio,
                "stats_count": coverage["youtube_stats_count"],
                "published_receipts": coverage["youtube_published_receipt_count"],
                "missing_stats_slugs": coverage["youtube_missing_stats_slugs"],
            },
            action=(
                "Refresh public YouTube statistics for every verified receipt on a schedule, "
                "then compare creative cohorts only after normalizing for video age."
            ),
        ))

    feedback_candidates = load(root / "pipeline" / "feedback_rule_candidates.json", {}) or {}
    if isinstance(feedback_candidates, dict) and feedback_candidates.get("candidate_count"):
        top = [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "evidence_count": item.get("evidence_count"),
            }
            for item in (feedback_candidates.get("candidates") or [])[:10]
            if isinstance(item, dict)
        ]
        findings.append(_finding(
            code="feedback_rule_candidates_ready",
            priority="medium",
            area="learning",
            title="Stored feedback has been organized into provisional rule candidates",
            evidence={
                "candidate_count": feedback_candidates.get("candidate_count"),
                "unique_commented_evidence": feedback_candidates.get("unique_commented_evidence"),
                "top_candidates": top,
            },
            action=(
                "Review candidate scope and counterexamples. Promote only candidates with a "
                "human decision and a regression test."
            ),
        ))

    stock_supply = load(root / "pipeline" / "stock_supply_report.json", {}) or {}
    if isinstance(stock_supply, dict) and stock_supply:
        state = str(stock_supply.get("state") or "insufficient_evidence")
        priority = "high" if state == "candidate_starvation_signal" else "low" if state == "no_current_starvation_signal" else "medium"
        findings.append(_finding(
            code=f"stock_supply:{state}",
            priority=priority,
            area="asset_selection",
            title="Permanent stock exclusion now has a measured supply signal",
            evidence={
                "state": state,
                "reports_analyzed": stock_supply.get("reports_analyzed"),
                "scenes_analyzed": stock_supply.get("scenes_analyzed"),
                "fallback_rate": stock_supply.get("fallback_rate"),
                "low_supply_rate": stock_supply.get("low_supply_rate"),
                "exclusions": stock_supply.get("permanent_exclusion_counts"),
                "measurement_boundary": stock_supply.get("measurement_boundary"),
            },
            action=str(stock_supply.get("recommended_action") or "Continue collecting selection evidence."),
        ))

    findings.sort(key=lambda item: (priority_rank(str(item.get("priority"))), str(item.get("area")), str(item.get("code"))))
    report["findings"] = findings
    report["summary"] = {
        "finding_count": len(findings),
        "open_count": sum(item.get("status") == "open" for item in findings),
        "priorities": dict(Counter(str(item.get("priority") or "unknown") for item in findings)),
        "automatic_patch_candidates": sum(bool(item.get("automatic_patch")) for item in findings),
    }
    report["denominator_policy"] = coverage["inventory_boundary"]
    report["feedback_rule_candidates"] = {
        "candidate_count": feedback_candidates.get("candidate_count") if isinstance(feedback_candidates, dict) else None,
        "authority_boundary": feedback_candidates.get("authority_boundary") if isinstance(feedback_candidates, dict) else None,
    }
    report["stock_supply"] = stock_supply if isinstance(stock_supply, dict) else {}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    report = build(Path(args.root).resolve())
    out = Path(args.out_dir)
    system_diagnostics.atomic_json(out / "LATEST.json", report)
    system_diagnostics.atomic_text(out / "LATEST.md", system_diagnostics.render_markdown(report))
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
