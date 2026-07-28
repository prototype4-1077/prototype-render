from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

import feedback_rule_candidates
import stock_supply_analysis
import yt_stats_refresh


class FeedbackRuleCandidateTests(unittest.TestCase):
    def test_comments_become_provisional_candidates_not_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            memory = root / "memory.json"
            output = root / "candidates.json"
            memory.write_text(json.dumps({
                "notes": [
                    "survey(one) scene 3 revise: The graphic does not match the concept.",
                    "Use a strong still image with special effects when stock cannot explain it.",
                ],
                "scene_feedback": [
                    {
                        "slug": "one", "scene_number": 3, "decision": "revise",
                        "comments": "The graphic does not match the concept.",
                        "query": "generic graphic",
                    },
                    {
                        "slug": "two", "scene_number": 4, "decision": "revise",
                        "comments": "Terrible graphics, we need to upgrade that.",
                    },
                ],
            }), encoding="utf-8")
            report = feedback_rule_candidates.build(memory, output)
            by_id = {item["id"]: item for item in report["candidates"]}
            self.assertIn("visual_semantic_match", by_id)
            self.assertIn("effects_still_preference", by_id)
            self.assertIn("graphics_quality_floor", by_id)
            self.assertEqual(by_id["visual_semantic_match"]["status"], "provisional")
            self.assertTrue(by_id["visual_semantic_match"]["human_promotion_required"])
            self.assertIn("No candidate may alter", report["authority_boundary"])


class StockSupplyAnalysisTests(unittest.TestCase):
    def test_raw_exclusion_size_does_not_trigger_reuse_without_supply_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pipeline").mkdir()
            (root / "pipeline" / "memory.json").write_text(json.dumps({
                "used_ids": list(range(1200)), "banned_ids": list(range(100)),
            }), encoding="utf-8")
            output = root / "report.json"
            report = stock_supply_analysis.build(root, output)
            self.assertEqual(report["state"], "insufficient_evidence")
            self.assertIn("exclusion-set size alone", report["recommended_action"])

    def test_persisted_low_supply_can_raise_shadow_experiment_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pipeline").mkdir()
            (root / "pipeline" / "memory.json").write_text(json.dumps({
                "used_ids": list(range(1200)), "banned_ids": list(range(100)),
            }), encoding="utf-8")
            for report_index in range(5):
                build = root / "build" / f"video-{report_index}"
                build.mkdir(parents=True)
                scenes = []
                for scene_index in range(10):
                    scenes.append({
                        "scene_index": scene_index,
                        "result": "literal_storyboard",
                        "candidate_decisions": [],
                        "fallback_reason": "no direct match",
                    })
                (build / "narrative_fidelity_report.json").write_text(json.dumps({
                    "scenes": scenes,
                }), encoding="utf-8")
            report = stock_supply_analysis.build(root, root / "report.json")
            self.assertEqual(report["evidence_strength"], "sufficient")
            self.assertEqual(report["state"], "candidate_starvation_signal")
            self.assertIn("shadow cooldown experiment", report["recommended_action"])


class YouTubeStatsRefreshTests(unittest.TestCase):
    def test_age_normalized_rates(self):
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        result = yt_stats_refresh.rates(
            {"viewCount": "1000", "likeCount": "50", "commentCount": "10"},
            "2026-07-01T00:00:00Z",
            now,
        )
        self.assertEqual(result["video_age_days"], 10.0)
        self.assertEqual(result["views_per_day"], 100.0)
        self.assertEqual(result["likes_per_100_views"], 5.0)
        self.assertEqual(result["comments_per_1000_views"], 10.0)

    def test_success_writes_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipts = root / "receipts.json"
            legacy = root / "legacy.json"
            status = root / "status.json"
            receipts.write_text(json.dumps({
                "video": {"video_id": "abc", "published_at": "2026-07-01T00:00:00Z"}
            }), encoding="utf-8")
            legacy.write_text("{}", encoding="utf-8")
            item = {
                "id": "abc",
                "snippet": {"title": "Video", "publishedAt": "2026-07-01T00:00:00Z"},
                "statistics": {"viewCount": "100", "likeCount": "5", "commentCount": "2"},
                "contentDetails": {"duration": "PT2M"},
                "status": {"privacyStatus": "public"},
            }
            with mock.patch.object(yt_stats_refresh, "RECEIPTS", receipts), \
                    mock.patch.object(yt_stats_refresh, "LEGACY", legacy), \
                    mock.patch.object(yt_stats_refresh, "STATUS", status), \
                    mock.patch.object(yt_stats_refresh, "authorization", return_value=({}, {}, "test")), \
                    mock.patch.object(yt_stats_refresh, "fetch", return_value=[item]):
                report = yt_stats_refresh.refresh(root)
            self.assertEqual(report["status"], "success")
            snapshot = json.load(open(root / "build" / "video" / "yt_stats.json", encoding="utf-8"))
            self.assertEqual(snapshot["views"], 100)
            self.assertEqual(snapshot["likes"], 5)
            self.assertEqual(snapshot["comments"], 2)
            self.assertEqual(snapshot["source"], "youtube_data_api_v3_videos_list")

    def test_permission_failure_is_persisted_without_statistics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipts = root / "receipts.json"
            legacy = root / "legacy.json"
            status = root / "status.json"
            receipts.write_text(json.dumps({"video": {"video_id": "abc"}}), encoding="utf-8")
            legacy.write_text("{}", encoding="utf-8")
            with mock.patch.object(yt_stats_refresh, "RECEIPTS", receipts), \
                    mock.patch.object(yt_stats_refresh, "LEGACY", legacy), \
                    mock.patch.object(yt_stats_refresh, "STATUS", status), \
                    mock.patch.object(yt_stats_refresh, "authorization", side_effect=RuntimeError("missing scope")):
                report = yt_stats_refresh.refresh(root)
            self.assertEqual(report["status"], "permission_or_network_error")
            self.assertFalse((root / "build" / "video" / "yt_stats.json").exists())
            persisted = json.load(open(status, encoding="utf-8"))
            self.assertIn("No statistics were fabricated", persisted["required_action"])


if __name__ == "__main__":
    unittest.main()
