"""Run aggregation and recommendations for the Pipeline Governor."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from governor_types import (
    SCHEMA_VERSION,
    atomic_write_json,
    failure_fingerprint,
    load_json,
    normalize_error,
    percentile,
    utc_now,
)


class GovernorSummaryMixin:
    def finalize(
        self,
        status: str,
        *,
        passes: int = 0,
        quality_report: Mapping[str, Any] | None = None,
        last_message: str | None = None,
    ) -> dict[str, Any]:
        events = self.events()
        stage_events = [event for event in events if event.get("event") == "stage_end"]
        stage_stats: dict[str, dict[str, Any]] = {}
        incidents: dict[str, dict[str, Any]] = {}
        policy_snapshot: dict[str, Any] = {}
        for event in stage_events:
            stage = str(event.get("stage") or "unknown")
            metrics = stage_stats.setdefault(
                stage,
                {
                    "attempts": 0,
                    "successes": 0,
                    "failures": 0,
                    "timeouts": 0,
                    "total_duration_s": 0.0,
                    "success_durations_s": [],
                },
            )
            metrics["attempts"] += 1
            duration = float(event.get("duration_s") or 0.0)
            metrics["total_duration_s"] += duration
            if event.get("status") == "success":
                metrics["successes"] += 1
                metrics["success_durations_s"].append(round(duration, 3))
            else:
                metrics["failures"] += 1
                if event.get("status") == "timeout":
                    metrics["timeouts"] += 1
                fp = event.get("fingerprint") or failure_fingerprint(stage, str(event.get("status")), str(event.get("stderr_tail")))
                incident = incidents.setdefault(
                    str(fp),
                    {
                        "fingerprint": fp,
                        "stage": stage,
                        "kind": event.get("status"),
                        "failure_class": event.get("failure_class"),
                        "normalized_error": normalize_error(str(event.get("stderr_tail") or event.get("stdout_tail"))),
                        "count": 0,
                        "last_item": event.get("item"),
                    },
                )
                incident["count"] += 1
                incident["last_item"] = event.get("item")
            if event.get("policy"):
                policy_snapshot[stage] = event["policy"]

        for metrics in stage_stats.values():
            durations = metrics["success_durations_s"]
            metrics["total_duration_s"] = round(metrics["total_duration_s"], 3)
            metrics["p50_success_s"] = round(percentile(durations, 0.5), 3) if durations else None
            metrics["p95_success_s"] = round(percentile(durations, 0.95), 3) if durations else None

        quality = dict(quality_report or load_json(self.build_dir / "quality_report.json", {}) or {})
        recommendations = self._recommendations(stage_stats, list(incidents.values()), quality)
        summary = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "github_run_id": self.github_run_id,
            "slug": self.build_dir.name,
            "status": status,
            "passes": passes,
            "finished_at": utc_now(),
            "last_message": last_message,
            "mode": self.mode,
            "stages": stage_stats,
            "incidents": sorted(incidents.values(), key=lambda item: (-item["count"], item["stage"])),
            "policy": policy_snapshot,
            "quality": quality,
            "recommendations": recommendations,
        }
        atomic_write_json(self.summary_path, summary)
        atomic_write_json(self.directory / "summary.json", summary)
        self.record_event("governor_finished", status=status, passes=passes, recommendations=recommendations)
        self.write_current(state=status, passes=passes, finished_at=summary["finished_at"])
        return summary

    @staticmethod
    def _recommendations(
        stages: Mapping[str, Mapping[str, Any]],
        incidents: Sequence[Mapping[str, Any]],
        quality: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        for incident in incidents[:5]:
            stage = incident.get("stage")
            if incident.get("kind") == "timeout":
                action = "Inspect this stage's provider/worker path; the Governor now terminates it and preserves completed artifacts."
            elif incident.get("failure_class") == "transient":
                action = "Keep bounded retry enabled and monitor whether the same fingerprint recovers on the next pass."
            else:
                action = "Treat as deterministic after repeated occurrence; fix the input or implementation instead of adding retries."
            recommendations.append(
                {
                    "priority": "high" if int(incident.get("count") or 0) > 1 else "medium",
                    "stage": stage,
                    "fingerprint": incident.get("fingerprint"),
                    "reason": f"{incident.get('count', 1)} occurrence(s): {incident.get('normalized_error')}",
                    "action": action,
                }
            )
        ranked = sorted(
            ((name, float(values.get("total_duration_s") or 0.0)) for name, values in stages.items()),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if ranked and ranked[0][1] > 60:
            recommendations.append(
                {
                    "priority": "medium",
                    "stage": ranked[0][0],
                    "reason": f"Largest measured latency contribution in this run ({ranked[0][1]:.1f}s).",
                    "action": "Optimize or parallelize this stage only after its quality outputs remain unchanged in a champion/challenger comparison.",
                }
            )
        warnings = quality.get("warnings") or []
        if warnings:
            recommendations.append(
                {
                    "priority": "medium",
                    "stage": "quality",
                    "reason": f"Quality gate emitted {len(warnings)} warning(s).",
                    "action": "Review warnings before allowing any speed-oriented policy to become the champion.",
                }
            )
        return recommendations
