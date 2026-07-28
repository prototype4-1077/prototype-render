from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

import backfill_observability
import system_diagnostic_policy


class ObservabilityBackfillTests(unittest.TestCase):
    def test_backfill_is_honest_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = root / "build" / "done"
            build.mkdir(parents=True)
            (build / "governor-summary.json").write_text(json.dumps({
                "slug": "done",
                "status": "done",
                "run_id": "r1",
                "github_run_id": "g1",
                "stages": {
                    "tts": {
                        "attempts": 1,
                        "successes": 1,
                        "failures": 0,
                        "timeouts": 0,
                        "total_duration_s": 12.5,
                        "p50_success_s": 12.5,
                        "p95_success_s": 12.5,
                        "sample_count": 1,
                    }
                },
                "incidents": [],
            }), encoding="utf-8")
            first = backfill_observability.backfill(root)
            self.assertEqual(len(first), 1)
            payload = json.load(open(first[0], encoding="utf-8"))
            self.assertEqual(payload["source"], "governor_summary_backfill")
            self.assertFalse(payload["single_trace"])
            self.assertEqual(payload["span_count"], 0)
            self.assertIsNone(payload["estimated_cost_usd"])
            self.assertEqual(payload["stages"]["tts"]["p95_duration_s"], 12.5)
            self.assertEqual(backfill_observability.backfill(root), [])


class DiagnosticDenominatorTests(unittest.TestCase):
    def test_coverage_uses_render_observed_and_reviewable_denominators(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for slug in ("never-rendered", "rendered-a", "rendered-b"):
                build = root / "build" / slug
                build.mkdir(parents=True)
                (build / "script.json").write_text(json.dumps({"title": slug, "slug": slug}), encoding="utf-8")
            a = root / "build" / "rendered-a"
            b = root / "build" / "rendered-b"
            (a / "governor-summary.json").write_text('{}', encoding="utf-8")
            (a / "telemetry-summary.json").write_text('{}', encoding="utf-8")
            (a / "scene-review.json").write_text('{}', encoding="utf-8")
            (a / "scene-review-feedback.json").write_text('{}', encoding="utf-8")
            (b / "render-status.json").write_text('{}', encoding="utf-8")
            (b / "scene-review.json").write_text('{}', encoding="utf-8")
            coverage = system_diagnostic_policy.evidence_coverage(root)
            self.assertEqual(coverage["package_count"], 3)
            self.assertEqual(coverage["render_observed_count"], 2)
            self.assertEqual(coverage["telemetry_count"], 1)
            self.assertEqual(coverage["telemetry_coverage_of_render_observed"], 0.5)
            self.assertEqual(coverage["reviewable_count"], 2)
            self.assertEqual(coverage["human_feedback_count"], 1)
            self.assertEqual(coverage["human_feedback_coverage_of_reviewable"], 0.5)


if __name__ == "__main__":
    unittest.main()
