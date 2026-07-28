"""Consolidate local OpenTelemetry spans and metrics into a compact render report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _load_spans(path: Path) -> list[dict[str, Any]]:
    spans: dict[str, dict[str, Any]] = {}
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                span_id = str(record.get("span_id") or "")
                if span_id:
                    spans[span_id] = record
    except OSError:
        pass
    return list(spans.values())


def _load_metrics(directory: Path) -> list[dict[str, Any]]:
    values = []
    for path in sorted(directory.glob("metrics-*.json")):
        payload = _load_json(path)
        if isinstance(payload, dict):
            values.append(payload)
    return values


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def build_report(build_dir: str | Path) -> dict[str, Any]:
    build_dir = Path(build_dir).resolve()
    telemetry_dir = build_dir / "telemetry"
    spans = _load_spans(telemetry_dir / "spans.jsonl")
    metrics = _load_metrics(telemetry_dir)
    traces = sorted({str(span.get("trace_id")) for span in spans if span.get("trace_id")})
    process_ids = sorted(
        {
            int((span.get("attributes") or {}).get("process.pid"))
            for span in spans
            if str((span.get("attributes") or {}).get("process.pid", "")).isdigit()
        }
    )

    stage_rows: dict[str, dict[str, Any]] = {}
    scene_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for span in spans:
        name = str(span.get("name") or "")
        attributes = span.get("attributes") or {}
        if not name.startswith("video.stage."):
            continue
        stage = str(attributes.get("pipeline.stage") or name.removeprefix("video.stage."))
        duration = float(span.get("duration_s") or 0.0)
        status = str(attributes.get("pipeline.stage.status") or span.get("status") or "")
        row = stage_rows.setdefault(
            stage,
            {
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "timeouts": 0,
                "total_duration_s": 0.0,
                "durations_s": [],
            },
        )
        row["attempts"] += 1
        row["successes" if status == "success" else "failures"] += 1
        row["timeouts"] += int(bool(attributes.get("pipeline.stage.timed_out")))
        row["total_duration_s"] += duration
        row["durations_s"].append(duration)
        if status != "success":
            failures.append(
                {
                    "stage": stage,
                    "item": attributes.get("pipeline.stage.item"),
                    "status": status,
                    "failure_class": attributes.get("pipeline.failure.class"),
                    "fingerprint": attributes.get("pipeline.failure.fingerprint"),
                    "duration_s": round(duration, 3),
                }
            )
        if attributes.get("video.scene.index") is not None:
            scene_rows.append(
                {
                    "scene_index": int(attributes["video.scene.index"]),
                    "scene_number": int(attributes.get("video.scene.number") or 0),
                    "stage": stage,
                    "status": status,
                    "duration_s": round(duration, 3),
                    "provider": attributes.get("gen_ai.provider.name"),
                    "model": attributes.get("gen_ai.request.model"),
                    "workflow": attributes.get("video.generation.workflow"),
                    "hero": bool(attributes.get("video.scene.hero")),
                    "revised": bool(attributes.get("video.scene.revised")),
                    "prompt_sha256": attributes.get("video.prompt.sha256"),
                    "visual_function": attributes.get("video.scene.visual_function"),
                    "symbol_family": attributes.get("video.scene.symbol_family"),
                    "credits_used": attributes.get("video.credits.used"),
                    "cost_usd": attributes.get("video.cost.usd"),
                    "visual_risk_score": attributes.get("video.visual_risk.score"),
                }
            )

    stages = {}
    for stage, row in stage_rows.items():
        durations = [float(value) for value in row.pop("durations_s")]
        stages[stage] = {
            **row,
            "total_duration_s": round(float(row["total_duration_s"]), 3),
            "p50_duration_s": round(median(durations), 3) if durations else None,
            "p95_duration_s": (
                round(float(_percentile(durations, 0.95)), 3) if durations else None
            ),
        }

    event_counts: dict[str, int] = {}
    sdk_processes = 0
    otlp_processes = 0
    for payload in metrics:
        sdk_processes += int(bool(payload.get("sdk_active")))
        otlp_processes += int(bool(payload.get("otlp_configured")))
        for name, count in (payload.get("events") or {}).items():
            event_counts[str(name)] = event_counts.get(str(name), 0) + int(count or 0)

    slowest = sorted(
        (
            {
                "stage": stage,
                "total_duration_s": values["total_duration_s"],
                "attempts": values["attempts"],
            }
            for stage, values in stages.items()
        ),
        key=lambda item: float(item["total_duration_s"]),
        reverse=True,
    )[:8]
    total_cost = sum(float(row.get("cost_usd") or 0.0) for row in scene_rows)
    total_credits = sum(float(row.get("credits_used") or 0.0) for row in scene_rows)
    report = {
        "schema_version": 1,
        "slug": build_dir.name,
        "trace_ids": traces,
        "single_trace": len(traces) == 1,
        "span_count": len(spans),
        "process_count": len(process_ids),
        "process_ids": process_ids,
        "sdk_active_processes": sdk_processes,
        "otlp_configured_processes": otlp_processes,
        "stages": stages,
        "slowest_stages": slowest,
        "scene_span_count": len(scene_rows),
        "scenes": sorted(scene_rows, key=lambda row: (row["scene_index"], row["stage"])),
        "failure_count": len(failures),
        "failures": failures,
        "event_counts": event_counts,
        "estimated_cost_usd": round(total_cost, 6),
        "credits_used": round(total_credits, 3),
        "privacy": {
            "prompt_text_recorded": False,
            "prompt_hash_recorded": True,
            "secrets_recorded": False,
        },
        "recommendations": [],
    }
    if slowest:
        report["recommendations"].append(
            {
                "priority": "medium",
                "category": "latency",
                "stage": slowest[0]["stage"],
                "reason": f"Largest traced duration contribution ({slowest[0]['total_duration_s']:.1f}s).",
                "action": "Investigate only after quality remains unchanged in a champion/challenger comparison.",
            }
        )
    if failures:
        report["recommendations"].append(
            {
                "priority": "high",
                "category": "reliability",
                "reason": f"{len(failures)} failed or timed-out traced stage attempt(s).",
                "action": "Group failures by fingerprint, provider, scene type, and cache state before changing retry policy.",
            }
        )
    if traces and len(traces) > 1:
        report["recommendations"].append(
            {
                "priority": "high",
                "category": "trace_continuity",
                "reason": f"The render emitted {len(traces)} trace IDs instead of one.",
                "action": "Check VIDEO_TRACE_ID propagation into child processes.",
            }
        )
    output = build_dir / "telemetry-summary.json"
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir")
    parser.add_argument("--require-spans", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(args.build_dir)
    print(json.dumps(report, indent=2))
    if args.require_spans and not report["span_count"]:
        return 2
    if report["trace_ids"] and not report["single_trace"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
