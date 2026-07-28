from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governor_report import aggregate  # noqa: E402


class GovernorReportTests(unittest.TestCase):
    def test_aggregate_surfaces_recurring_incident_and_tail(self):
        summaries = []
        for i in range(5):
            summaries.append({
                "slug": f"v{i}",
                "status": "done" if i < 4 else "failed",
                "stages": {
                    "hero": {
                        "attempts": 1,
                        "successes": 1,
                        "failures": 0,
                        "timeouts": 0,
                        "total_duration_s": [10, 12, 15, 20, 400][i],
                        "success_durations_s": [[10, 12, 15, 20, 400][i]],
                    },
                },
                "incidents": [{
                    "fingerprint": "abc",
                    "stage": "hero",
                    "kind": "failure",
                    "failure_class": "unknown",
                    "normalized_error": "renderer exit",
                    "count": 1,
                }] if i < 3 else [],
                "quality": {},
            })
        report = aggregate(summaries)
        self.assertEqual(report["runs_analyzed"], 5)
        self.assertEqual(report["recurring_incidents"][0]["count"], 3)
        categories = {item["category"] for item in report["recommendations"]}
        self.assertIn("recurring_incident", categories)
        self.assertIn("tail_latency", categories)


if __name__ == "__main__":
    unittest.main()
