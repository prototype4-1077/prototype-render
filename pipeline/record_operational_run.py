"""Capture one render outcome into durable operational memory.

Unlike the original compatibility recorder, this module keeps solution evidence
causal: successful runs verify only solutions exercised by preflight, while a
failure is attributed only to solutions that match that failure itself. Quality
warnings and telemetry recommendations become durable evidence instead of being
left inside per-build reports.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import operational_memory
from governor import failure_fingerprint, normalize_error

SUCCESS = {"done", "success", "passed"}


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def exact_matches(code: str, fingerprint: str | None, message: str, store: Path) -> list[str]:
    return operational_memory.match_solutions(
        code=code,
        fingerprint=fingerprint,
        message=message,
        store=store,
    )


def warning_records(build: Path, common: dict[str, Any], store: Path) -> list[Path]:
    quality = load(build / "quality_report.json", {}) or {}
    paths: list[Path] = []
    for warning in quality.get("warnings") or []:
        code = f"quality_warning:{warning.get('code') or 'unknown'}"
        target = str(warning.get("target") or "quality")
        message = str(warning.get("message") or warning)
        fingerprint = failure_fingerprint("quality", code, f"{target}|{message}")
        paths.append(operational_memory.write_occurrence({
            **common,
            "phase": "quality",
            "status": "warning",
            "code": code,
            "stage": "quality",
            "target": target,
            "message": message,
            "normalized_error": normalize_error(message),
            "fingerprint": fingerprint,
            "details": {k: v for k, v in warning.items() if k not in {"code", "target", "message"}},
            "matched_solution_ids": exact_matches(code, fingerprint, message, store),
        }, store=store))
    return paths


def telemetry_records(build: Path, common: dict[str, Any], store: Path) -> list[Path]:
    telemetry = load(build / "telemetry-summary.json", {}) or {}
    if not telemetry:
        return []
    paths: list[Path] = []
    message = (
        f"Telemetry summary: {int(telemetry.get('span_count') or 0)} spans, "
        f"{int(telemetry.get('failure_count') or 0)} traced failures."
    )
    paths.append(operational_memory.write_occurrence({
        **common,
        "phase": "telemetry",
        "status": "informational",
        "code": "telemetry_summary",
        "stage": "telemetry",
        "message": message,
        "normalized_error": normalize_error(message),
        "stage_metrics": telemetry.get("stages") or {},
        "scene_span_count": telemetry.get("scene_span_count"),
        "single_trace": telemetry.get("single_trace"),
        "estimated_cost_usd": telemetry.get("estimated_cost_usd"),
        "credits_used": telemetry.get("credits_used"),
        "matched_solution_ids": [],
    }, store=store))
    for index, item in enumerate(telemetry.get("recommendations") or []):
        category = str(item.get("category") or "telemetry")
        stage = str(item.get("stage") or "telemetry")
        recommendation_message = str(item.get("reason") or item.get("action") or item)
        code = f"telemetry_recommendation:{category}"
        fingerprint = failure_fingerprint(stage, code, recommendation_message)
        paths.append(operational_memory.write_occurrence({
            **common,
            "phase": "telemetry",
            "status": "advisory",
            "code": code,
            "stage": stage,
            "message": recommendation_message,
            "normalized_error": normalize_error(recommendation_message),
            "fingerprint": fingerprint,
            "priority": item.get("priority"),
            "recommendation": item,
            "item": index,
            "matched_solution_ids": exact_matches(code, fingerprint, recommendation_message, store),
        }, store=store))
    return paths


def capture(
    build_dir: str | os.PathLike[str],
    *,
    github_run_id: str | None = None,
    commit_sha: str | None = None,
    store: str | os.PathLike[str] = operational_memory.DEFAULT_STORE,
) -> list[Path]:
    build = Path(build_dir)
    store_path = Path(store)
    summary = load(build / "governor-summary.json", {}) or {}
    render_status = load(build / "render-status.json", {}) or {}
    preflight = load(build / "preflight-report.json", {}) or {}
    quality = summary.get("quality") or load(build / "quality_report.json", {}) or {}
    telemetry = load(build / "telemetry-summary.json", {}) or {}

    status = str(summary.get("status") or render_status.get("state") or "unknown")
    slug = str(summary.get("slug") or render_status.get("slug") or build.name)
    run_id = github_run_id or summary.get("github_run_id") or os.environ.get("GITHUB_RUN_ID")
    exercised = sorted(set(
        (preflight.get("applied_solution_ids") or [])
        + (preflight.get("matched_solution_ids") or [])
    ))
    common = {
        "github_run_id": run_id,
        "run_id": summary.get("run_id") or render_status.get("run_id"),
        "commit_sha": commit_sha or os.environ.get("GITHUB_SHA"),
        "slug": slug,
        "narration_fingerprint": preflight.get("narration_fingerprint"),
        "render_status": status,
    }
    paths: list[Path] = []

    if status in SUCCESS:
        paths.append(operational_memory.write_occurrence({
            **common,
            "phase": "render",
            "status": "done",
            "code": "render_success",
            "stage": "render",
            "message": str(summary.get("last_message") or render_status.get("last_message") or "Render completed"),
            "quality_passed": bool(quality.get("passed", True)),
            "verified_solution_ids": exercised,
            "matched_solution_ids": exercised,
            "stage_metrics": summary.get("stages") or {},
            "telemetry_stage_metrics": telemetry.get("stages") or {},
            "estimated_cost_usd": telemetry.get("estimated_cost_usd"),
            "credits_used": telemetry.get("credits_used"),
        }, store=store_path))
    else:
        incidents = summary.get("incidents") or []
        if not incidents:
            message = str(summary.get("last_message") or render_status.get("last_message") or f"Render ended with status {status}")
            incidents = [{
                "stage": "render",
                "failure_class": "unknown",
                "fingerprint": failure_fingerprint("render", "failure", message),
                "normalized_error": normalize_error(message),
                "count": 1,
            }]
        for ordinal, incident in enumerate(incidents):
            message = str(incident.get("normalized_error") or summary.get("last_message") or render_status.get("last_message") or status)
            stage = str(incident.get("stage") or "render")
            fingerprint = str(incident.get("fingerprint") or failure_fingerprint(stage, "failure", message))
            code = str(incident.get("code") or f"{stage}_failure")
            regressed = exact_matches(code, fingerprint, message, store_path)
            paths.append(operational_memory.write_occurrence({
                **common,
                "phase": "render",
                "status": "quality_failed" if status == "quality_failed" else "failed",
                "code": code,
                "stage": stage,
                "item": incident.get("last_item", ordinal),
                "failure_class": incident.get("failure_class"),
                "fingerprint": fingerprint,
                "message": message,
                "normalized_error": normalize_error(message),
                "reported_count": max(1, int(incident.get("count") or 1)),
                "regressed_solution_ids": regressed,
                "matched_solution_ids": regressed,
            }, store=store_path))

    paths.extend(warning_records(build, common, store_path))
    paths.extend(telemetry_records(build, common, store_path))
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir")
    parser.add_argument("--github-run-id")
    parser.add_argument("--commit-sha")
    parser.add_argument("--store", default=str(operational_memory.DEFAULT_STORE))
    args = parser.parse_args(argv)
    paths = capture(
        args.build_dir,
        github_run_id=args.github_run_id,
        commit_sha=args.commit_sha,
        store=args.store,
    )
    print("\n".join(str(path) for path in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
