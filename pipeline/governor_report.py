"""Aggregate Governor run summaries into an operational improvement report."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from governor import atomic_write_json, load_json, percentile, utc_now


def collect_summaries(repo_root: str | Path, limit: int = 250) -> list[dict[str, Any]]:
    root = Path(repo_root).resolve()
    paths = list((root / "build").glob("*/governor-summary.json"))
    try:
        paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        pass
    summaries: list[dict[str, Any]] = []
    for path in paths[:limit]:
        payload = load_json(path, None)
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["_path"] = str(path)
            summaries.append(payload)
    return summaries


def aggregate(summaries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    summaries = list(summaries)
    stage_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "attempts": 0,
        "successes": 0,
        "failures": 0,
        "timeouts": 0,
        "total_duration_s": 0.0,
        "success_durations_s": [],
    })
    incidents: dict[str, dict[str, Any]] = {}
    quality_failures: dict[str, int] = defaultdict(int)
    quality_warnings: dict[str, int] = defaultdict(int)
    statuses: dict[str, int] = defaultdict(int)

    for summary in summaries:
        statuses[str(summary.get("status") or "unknown")] += 1
        for stage, metrics in (summary.get("stages") or {}).items():
            bucket = stage_data[str(stage)]
            for key in ("attempts", "successes", "failures", "timeouts"):
                bucket[key] += int(metrics.get(key) or 0)
            bucket["total_duration_s"] += float(metrics.get("total_duration_s") or 0.0)
            bucket["success_durations_s"].extend(
                float(value) for value in (metrics.get("success_durations_s") or [])
                if isinstance(value, (int, float)) and value >= 0
            )
        for incident in summary.get("incidents") or []:
            fingerprint = str(incident.get("fingerprint") or "unknown")
            entry = incidents.setdefault(fingerprint, {
                "fingerprint": fingerprint,
                "stage": incident.get("stage"),
                "kind": incident.get("kind"),
                "failure_class": incident.get("failure_class"),
                "normalized_error": incident.get("normalized_error"),
                "count": 0,
                "slugs": [],
            })
            entry["count"] += int(incident.get("count") or 1)
            slug = summary.get("slug")
            if slug and slug not in entry["slugs"]:
                entry["slugs"].append(slug)
        quality = summary.get("quality") or {}
        for failure in quality.get("failures") or []:
            quality_failures[str(failure.get("code") or "unknown")] += 1
        for warning in quality.get("warnings") or []:
            quality_warnings[str(warning.get("code") or "unknown")] += 1

    stages: dict[str, dict[str, Any]] = {}
    for name, values in stage_data.items():
        durations = values.pop("success_durations_s")
        attempts = values["attempts"]
        values["total_duration_s"] = round(values["total_duration_s"], 3)
        values["failure_rate"] = round(values["failures"] / attempts, 4) if attempts else 0.0
        values["timeout_rate"] = round(values["timeouts"] / attempts, 4) if attempts else 0.0
        values["p50_success_s"] = round(percentile(durations, 0.5), 3) if durations else None
        values["p95_success_s"] = round(percentile(durations, 0.95), 3) if durations else None
        values["sample_count"] = len(durations)
        stages[name] = values

    recommendations: list[dict[str, Any]] = []
    recurring = sorted(incidents.values(), key=lambda item: (-item["count"], str(item.get("stage"))))
    for incident in recurring:
        if incident["count"] < 2:
            continue
        recommendations.append({
            "priority": "high" if incident["count"] >= 4 else "medium",
            "category": "recurring_incident",
            "stage": incident.get("stage"),
            "fingerprint": incident["fingerprint"],
            "evidence": f"{incident['count']} occurrence(s) across {len(incident['slugs'])} build(s)",
            "action": (
                "Eliminate the root cause before increasing retry limits. Keep the fingerprint as the regression key."
                if incident.get("failure_class") != "transient"
                else "Check provider health/routing and retain bounded recovery until the occurrence rate falls."
            ),
        })
    for stage, metrics in sorted(stages.items(), key=lambda pair: pair[1]["total_duration_s"], reverse=True):
        if metrics["attempts"] >= 3 and metrics["timeout_rate"] >= 0.1:
            recommendations.append({
                "priority": "high",
                "category": "timeout_rate",
                "stage": stage,
                "evidence": f"{metrics['timeout_rate']:.1%} timeout rate over {metrics['attempts']} attempt(s)",
                "action": "Profile waiting versus active progress, then add a provider fallback or split this stage into smaller checkpoints.",
            })
        p50, p95 = metrics.get("p50_success_s"), metrics.get("p95_success_s")
        if metrics["sample_count"] >= 5 and p50 and p95 and p95 >= max(120, p50 * 3):
            recommendations.append({
                "priority": "medium",
                "category": "tail_latency",
                "stage": stage,
                "evidence": f"p50={p50:.1f}s, p95={p95:.1f}s",
                "action": "Investigate the slow cohort by provider, scene type, and artifact size; optimize the tail rather than the median.",
            })
    if quality_failures:
        code, count = max(quality_failures.items(), key=lambda item: item[1])
        recommendations.append({
            "priority": "high",
            "category": "quality_floor",
            "stage": "quality",
            "evidence": f"Most common blocking quality code: {code} ({count} occurrence(s))",
            "action": "Fix this defect upstream; the Governor will not trade it away for faster completion.",
        })

    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "runs_analyzed": len(summaries),
        "statuses": dict(sorted(statuses.items())),
        "stages": dict(sorted(stages.items())),
        "recurring_incidents": recurring,
        "quality_failure_codes": dict(sorted(quality_failures.items(), key=lambda item: (-item[1], item[0]))),
        "quality_warning_codes": dict(sorted(quality_warnings.items(), key=lambda item: (-item[1], item[0]))),
        "recommendations": recommendations,
    }


def render_text(report: Mapping[str, Any]) -> str:
    lines = [
        f"Governor review: {report.get('runs_analyzed', 0)} run(s)",
        f"Statuses: {json.dumps(report.get('statuses') or {}, sort_keys=True)}",
        "",
        "Stage scorecard:",
    ]
    for stage, metrics in sorted(
        (report.get("stages") or {}).items(),
        key=lambda pair: pair[1].get("total_duration_s", 0),
        reverse=True,
    ):
        lines.append(
            f"- {stage}: attempts={metrics['attempts']} failures={metrics['failures']} "
            f"timeouts={metrics['timeouts']} p50={metrics.get('p50_success_s')}s "
            f"p95={metrics.get('p95_success_s')}s"
        )
    lines.append("")
    lines.append("Recommended improvements:")
    for item in report.get("recommendations") or []:
        lines.append(
            f"- [{item.get('priority')}] {item.get('stage')}: {item.get('evidence')} — {item.get('action')}"
        )
    if not report.get("recommendations"):
        lines.append("- No recurring problem has enough evidence yet; continue collecting runs.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--output", help="write JSON report to this path")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    report = aggregate(collect_summaries(args.repo_root, args.limit))
    if args.output:
        atomic_write_json(Path(args.output), report)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_text(report), end="\n" if args.json else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
