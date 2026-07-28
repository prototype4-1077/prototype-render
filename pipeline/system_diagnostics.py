"""Repository-wide diagnostic for the Concept Engine and render system.

This report does not change creative policy. It measures whether evidence is
captured, analyzed, and converted into action across production, visual review,
telemetry, publishing, audience analytics, and experimental subsystems.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "pipeline" / "system_diagnostics"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def pct(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def priority_rank(value: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(value, 5)


def finding(
    findings: list[dict[str, Any]],
    *,
    code: str,
    priority: str,
    area: str,
    title: str,
    evidence: Any,
    action: str,
    status: str = "open",
    automatic_patch: bool = False,
) -> None:
    findings.append({
        "code": code,
        "priority": priority,
        "area": area,
        "title": title,
        "evidence": evidence,
        "action": action,
        "status": status,
        "automatic_patch": automatic_patch,
    })


def build_coverage(root: Path) -> dict[str, Any]:
    builds = [path for path in sorted((root / "build").glob("*")) if path.is_dir() and (path / "script.json").exists()]
    files = {
        "governor_summary": "governor-summary.json",
        "quality_report": "quality_report.json",
        "telemetry_summary": "telemetry-summary.json",
        "scene_feedback": "scene-review-feedback.json",
        "scene_feedback_request": "scene-feedback.request.json",
        "youtube_stats": "yt_stats.json",
        "preflight_report": "preflight-report.json",
        "scene_review": "scene-review.json",
    }
    counts = {name: sum((path / filename).exists() for path in builds) for name, filename in files.items()}
    feedback = sum(
        any((path / filename).exists() for filename in ("scene-review-feedback.json", "scene-feedback.request.json"))
        for path in builds
    )
    return {
        "build_count": len(builds),
        "counts": counts,
        "coverage": {name: pct(count, len(builds)) for name, count in counts.items()},
        "human_feedback_count": feedback,
        "human_feedback_coverage": pct(feedback, len(builds)),
    }


def aggregate_current_reports(root: Path) -> dict[str, Any]:
    quality_warning_counts: Counter[str] = Counter()
    quality_failure_counts: Counter[str] = Counter()
    telemetry_recommendations: Counter[str] = Counter()
    governor_recommendations: Counter[str] = Counter()
    stage_duration: dict[str, list[float]] = defaultdict(list)
    statuses: Counter[str] = Counter()

    for build in (root / "build").glob("*"):
        if not build.is_dir():
            continue
        quality = load(build / "quality_report.json", {}) or {}
        if not isinstance(quality, dict):
            quality = {}
        for item in quality.get("warnings") or []:
            if isinstance(item, dict):
                quality_warning_counts[str(item.get("code") or "unknown")] += 1
        for item in quality.get("failures") or []:
            if isinstance(item, dict):
                quality_failure_counts[str(item.get("code") or "unknown")] += 1
        telemetry = load(build / "telemetry-summary.json", {}) or {}
        if not isinstance(telemetry, dict):
            telemetry = {}
        for item in telemetry.get("recommendations") or []:
            if isinstance(item, dict):
                telemetry_recommendations[str(item.get("category") or "unknown")] += 1
        for stage, metrics in (telemetry.get("stages") or {}).items():
            if not isinstance(metrics, dict):
                continue
            try:
                value = metrics.get("p95_duration_s") or metrics.get("total_duration_s")
                if value is not None:
                    stage_duration[str(stage)].append(float(value))
            except (TypeError, ValueError):
                pass
        governor = load(build / "governor-review.json", {}) or {}
        if not isinstance(governor, dict):
            governor = {}
        for item in governor.get("recommendations") or []:
            if isinstance(item, dict):
                governor_recommendations[str(item.get("category") or "unknown")] += 1
        summary = load(build / "governor-summary.json", {}) or {}
        if isinstance(summary, dict) and summary:
            statuses[str(summary.get("status") or "unknown")] += 1

    return {
        "quality_warning_counts": dict(quality_warning_counts.most_common()),
        "quality_failure_counts": dict(quality_failure_counts.most_common()),
        "telemetry_recommendation_counts": dict(telemetry_recommendations.most_common()),
        "governor_recommendation_counts": dict(governor_recommendations.most_common()),
        "render_statuses": dict(statuses),
        "stage_signals": {
            stage: {
                "samples": len(values),
                "mean_s": round(sum(values) / len(values), 3),
                "max_s": round(max(values), 3),
            }
            for stage, values in sorted(stage_duration.items()) if values
        },
    }


def memory_snapshot(root: Path) -> dict[str, Any]:
    memory = load(root / "pipeline" / "memory.json", {}) or {}
    if not isinstance(memory, dict):
        memory = {}
    profile_weights = memory.get("profile_query_weights") or {}
    if not isinstance(profile_weights, dict):
        profile_weights = {}
    return {
        "used_ids": len(memory.get("used_ids") or []),
        "banned_ids": len(memory.get("banned_ids") or []),
        "query_weights": len(memory.get("query_weights") or {}),
        "profile_query_weights": {
            profile: len(values or {}) for profile, values in profile_weights.items()
            if isinstance(values, dict)
        },
        "notes": len(memory.get("notes") or []),
        "scene_feedback": len(memory.get("scene_feedback") or []),
        "videos": len(memory.get("videos") or []),
        "scene_review_ids": len(memory.get("scene_review_ids") or []),
        "structured_note_rules": len(memory.get("structured_note_rules") or []),
    }


def publishing_snapshot(root: Path) -> dict[str, Any]:
    pipeline = root / "pipeline"
    result = {}
    for platform, queue_name, result_name in (
        ("youtube", "yt_publish_queue.json", "yt_published_result.json"),
        ("facebook", "fb_publish_queue.json", "fb_published_result.json"),
    ):
        queue = load(pipeline / queue_name, {}) or {}
        history = load(pipeline / result_name, {}) or {}
        queue_slugs = set(queue) if isinstance(queue, dict) else set()
        history_slugs = set(history) if isinstance(history, dict) else set()
        result[platform] = {
            "queued": len(queue_slugs),
            "published_receipts": len(history_slugs),
            "published_still_in_queue": sorted(queue_slugs & history_slugs),
            "queued_without_receipt": sorted(queue_slugs - history_slugs),
            "receipt_file_exists": (pipeline / result_name).exists(),
        }
    return result


def evolution_snapshot(root: Path) -> dict[str, Any]:
    state = load(root / "concept" / "evolution_state" / "LATEST.json", {}) or {}
    if not isinstance(state, dict):
        state = {}
    raw_queue = state.get("curiosity_queue") or []
    queue = raw_queue if isinstance(raw_queue, list) else []
    structured = [item for item in queue if isinstance(item, dict)]
    legacy = [item for item in queue if not isinstance(item, dict)]
    taxonomy = []
    for item in structured:
        why_now = item.get("why_now") or {}
        if isinstance(why_now, dict) and why_now.get("kind") == "taxonomy_gap":
            taxonomy.append(item)
    capabilities = state.get("capability_report") or {}
    if not isinstance(capabilities, dict):
        capabilities = {}
    slugs = set()
    for item in taxonomy:
        why_now = item.get("why_now") or {}
        if isinstance(why_now, dict) and why_now.get("slug"):
            slugs.add(str(why_now["slug"]))
    return {
        "state_exists": bool(state),
        "curiosity_items": len(queue),
        "structured_curiosity_items": len(structured),
        "legacy_curiosity_items": len(legacy),
        "legacy_curiosity_examples": [str(item)[:180] for item in legacy[:20]],
        "taxonomy_gap_items": len(taxonomy),
        "taxonomy_gap_slugs": sorted(slugs)[:100],
        "capabilities_demonstrated": capabilities.get("demonstrated"),
        "capabilities_total": capabilities.get("total"),
        "requires_human_selection": state.get("requires_human_selection"),
    }


def diagnostic(root: Path = ROOT) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    coverage = build_coverage(root)
    reports = aggregate_current_reports(root)
    memory = memory_snapshot(root)
    publishing = publishing_snapshot(root)
    evolution = evolution_snapshot(root)
    operational = load(root / "pipeline" / "operational_memory" / "index.json", {}) or {}
    if not isinstance(operational, dict):
        operational = {}
    operational_actions = load(root / "pipeline" / "operational_memory" / "action_queue.json", {}) or {}
    if not isinstance(operational_actions, dict):
        operational_actions = {}
    visual = load(root / "concept" / "visual_memory" / "action_report.json", {}) or {}
    if not isinstance(visual, dict):
        visual = {}
    visual_summary = load(root / "concept" / "visual_memory" / "summary.json", {}) or {}
    if not isinstance(visual_summary, dict):
        visual_summary = {}
    whisperx = load(root / "pipeline" / "whisperx-benchmark-ledger.json", {}) or {}
    if not isinstance(whisperx, dict):
        whisperx = {}

    if coverage["build_count"] and coverage["coverage"]["telemetry_summary"] < 0.50:
        finding(
            findings,
            code="telemetry_coverage_low",
            priority="high",
            area="observability",
            title="Most builds have no committed telemetry summary",
            evidence={"coverage": coverage["coverage"]["telemetry_summary"], "count": coverage["counts"]["telemetry_summary"], "builds": coverage["build_count"]},
            action="Backfill compact telemetry summaries for recent completed renders and keep the post-render workflow mandatory.",
        )
    if coverage["build_count"] and coverage["human_feedback_coverage"] < 0.10:
        finding(
            findings,
            code="human_feedback_coverage_low",
            priority="high",
            area="learning",
            title="Creative memory is dominated by unreviewed scenes",
            evidence={"coverage": coverage["human_feedback_coverage"], "reviewed_builds": coverage["human_feedback_count"], "builds": coverage["build_count"]},
            action="Prioritize completed videos with asset-backed review surveys; do not promote automated risk frequency into taste rules.",
        )
    if visual_summary and not visual:
        finding(
            findings,
            code="visual_memory_unanalyzed",
            priority="high",
            area="visual_memory",
            title="Visual-memory data exists without a reviewed-evidence action report",
            evidence={"records": visual_summary.get("records"), "decisions": visual_summary.get("decisions")},
            action="Run the visual-memory analyzer and commit its reviewed feedback cohorts and review queue.",
            automatic_patch=True,
        )
    elif visual:
        for action in visual.get("actions") or []:
            if not isinstance(action, dict):
                continue
            finding(
                findings,
                code=f"visual:{action.get('category')}:{action.get('key', 'general')}",
                priority=str(action.get("priority") or "medium"),
                area="visual_memory",
                title=str(action.get("category") or "Visual-memory action").replace("_", " ").title(),
                evidence=action.get("evidence"),
                action=str(action.get("action") or "Review the visual evidence cohort."),
            )
    for action in operational_actions.get("actions") or operational.get("action_queue") or []:
        if not isinstance(action, dict):
            continue
        finding(
            findings,
            code=f"operational:{action.get('category')}:{action.get('key')}",
            priority=str(action.get("priority") or "medium"),
            area="operations",
            title=str(action.get("category") or "Operational action").replace("_", " ").title(),
            evidence=action.get("evidence"),
            action=str(action.get("action") or "Investigate the operational evidence."),
        )
    if reports["quality_warning_counts"]:
        for code, count in reports["quality_warning_counts"].items():
            if count >= 2:
                finding(
                    findings,
                    code=f"repeated_quality_warning:{code}",
                    priority="medium",
                    area="quality",
                    title=f"Quality warning repeats: {code}",
                    evidence={"current_build_reports": count},
                    action="Run a targeted encoding or assembly challenger and require unchanged visual/audio quality before adoption.",
                )
    if memory["notes"] and memory["structured_note_rules"] == 0:
        finding(
            findings,
            code="free_text_notes_not_structured",
            priority="medium",
            area="learning",
            title="Feedback notes are stored but not converted into candidate rules",
            evidence={"notes": memory["notes"], "structured_note_rules": memory["structured_note_rules"]},
            action="Cluster repeated reviewed notes into provisional rules with examples, counterexamples, and a human promotion gate.",
        )
    if memory["used_ids"] >= 500:
        finding(
            findings,
            code="permanent_stock_exclusion_growth",
            priority="medium",
            area="asset_selection",
            title="The permanent stock exclusion set is large",
            evidence={"used_ids": memory["used_ids"], "banned_ids": memory["banned_ids"]},
            action="Measure candidate starvation. Consider age- and context-aware reuse after a long cooldown while keeping explicitly banned IDs permanent.",
        )
    for platform, state in publishing.items():
        if state["published_still_in_queue"]:
            finding(
                findings,
                code=f"{platform}_published_still_queued",
                priority="medium",
                area="publishing",
                title=f"{platform.title()} queue contains already-published videos",
                evidence=state["published_still_in_queue"],
                action="Keep the metadata queue if useful, but rely on durable receipt checks and make duplicate posting require an explicit force flag.",
                automatic_patch=True,
            )
        if state["queued"] and not state["receipt_file_exists"]:
            finding(
                findings,
                code=f"{platform}_receipt_history_missing",
                priority="high",
                area="publishing",
                title=f"{platform.title()} publishing has no durable receipt history",
                evidence=state,
                action="Persist and commit platform video IDs after every successful upload; refuse duplicates by default.",
                automatic_patch=True,
            )
    if evolution["legacy_curiosity_items"]:
        finding(
            findings,
            code="evolution_legacy_queue_entries",
            priority="medium",
            area="concept_engine",
            title="The evolution queue mixes legacy strings with structured records",
            evidence={"count": evolution["legacy_curiosity_items"], "examples": evolution["legacy_curiosity_examples"][:10]},
            action="Migrate legacy queue strings into explicit proposal records or archive them; do not count them as structured taxonomy evidence.",
        )
    if evolution["taxonomy_gap_items"] >= 10:
        finding(
            findings,
            code="evolution_taxonomy_gap_flood",
            priority="medium",
            area="concept_engine",
            title="The evolution queue is flooded with taxonomy gaps",
            evidence={"count": evolution["taxonomy_gap_items"], "examples": evolution["taxonomy_gap_slugs"][:15]},
            action="Separate legacy packages missing metadata from genuinely novel concepts before treating every uncataloged slug as a map failure.",
        )
    if not whisperx:
        finding(
            findings,
            code="whisperx_ledger_absent",
            priority="low",
            area="alignment",
            title="The WhisperX challenger has no materialized benchmark ledger",
            evidence="pipeline/whisperx-benchmark-ledger.json is absent",
            action="Run shadow alignment on eligible successful videos and add the first manually reviewed timing references before considering promotion.",
        )
    provisional = [
        solution_id for solution_id, proof in (operational.get("solution_evidence") or {}).items()
        if isinstance(proof, dict) and proof.get("catalog_status") != "verified"
    ]
    if provisional:
        finding(
            findings,
            code="provisional_operational_solutions",
            priority="medium",
            area="operations",
            title="Some operational solutions still need verification",
            evidence=provisional,
            action="Satisfy each stated verification requirement before marking it verified; do not promote by elapsed time alone.",
        )

    findings.sort(key=lambda item: (priority_rank(item["priority"]), item["area"], item["code"]))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "summary": {
            "finding_count": len(findings),
            "open_count": sum(item["status"] == "open" for item in findings),
            "priorities": dict(Counter(item["priority"] for item in findings)),
            "automatic_patch_candidates": sum(bool(item["automatic_patch"]) for item in findings),
        },
        "coverage": coverage,
        "current_reports": reports,
        "operational_memory": {
            "occurrence_count": operational.get("occurrence_count"),
            "open_failure_count": operational.get("open_failure_count"),
            "warning_counts": operational.get("warning_counts") or {},
            "advisory_counts": operational.get("advisory_counts") or {},
        },
        "visual_memory": {
            "records": visual.get("records") or visual_summary.get("records"),
            "reviewed": visual.get("reviewed"),
            "reviewed_coverage": visual.get("reviewed_coverage"),
            "asset_coverage": visual.get("asset_coverage"),
        },
        "creative_memory": memory,
        "publishing": publishing,
        "evolution": evolution,
        "whisperx": whisperx.get("counts") if whisperx else None,
        "findings": findings,
        "authority_boundary": "This diagnostic may propose or apply deterministic infrastructure safeguards. It cannot rewrite narration, change science or political meaning, alter James's approved visual intent, publish, or promote experimental systems without the relevant approval gate.",
    }
    return payload


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# System Diagnostic",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"Findings: {report['summary']['finding_count']} — priorities {json.dumps(report['summary']['priorities'], sort_keys=True)}",
        "",
        "## Action queue",
        "",
    ]
    for item in report["findings"]:
        lines.extend([
            f"### [{item['priority'].upper()}] {item['title']}",
            f"- Area: `{item['area']}`",
            f"- Code: `{item['code']}`",
            f"- Evidence: {json.dumps(item['evidence'], ensure_ascii=False, sort_keys=True)}",
            f"- Action: {item['action']}",
            "",
        ])
    lines.extend([
        "## Authority boundary",
        "",
        report["authority_boundary"],
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    report = diagnostic(Path(args.root).resolve())
    out = Path(args.out_dir)
    atomic_json(out / "LATEST.json", report)
    atomic_text(out / "LATEST.md", render_markdown(report))
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
