from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PIPELINE = Path(__file__).resolve().parents[1]
ROOT = PIPELINE.parent
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(ROOT / "intelligence_stack" / "fiftyone"))

import analyze_visual_memory
import fb_publish
import operational_memory
import operational_memory_analysis
import package_integrity
import record_operational_run
import system_diagnostics
import yt_publish


class PackageIntegrityTests(unittest.TestCase):
    def test_source_assets_are_locked_and_generated_outputs_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "video"
            build.mkdir()
            (build / "script.json").write_text('{"title":"A"}', encoding="utf-8")
            (build / "hero_00_raw.jpg").write_bytes(b"committed-reference")
            (build / "final_youtube.mp4").write_bytes(b"generated-output")
            (build / "preflight-report.json").write_text("{}", encoding="utf-8")
            first = package_integrity.fingerprint(build)
            paths = {row["path"] for row in first["files"]}
            self.assertIn("hero_00_raw.jpg", paths)
            self.assertNotIn("final_youtube.mp4", paths)
            self.assertNotIn("preflight-report.json", paths)
            (build / "hero_00_raw.jpg").write_bytes(b"changed-reference")
            second = package_integrity.fingerprint(build)
            self.assertNotEqual(first["fingerprint"], second["fingerprint"])


class OperationalAnalysisTests(unittest.TestCase):
    def _store(self, root: Path) -> Path:
        store = root / "operational"
        (store / "occurrences").mkdir(parents=True)
        (store / "solutions.json").write_text(json.dumps({
            "schema_version": 1,
            "solutions": [
                {"id": "solution-a", "status": "verified", "match": {"codes": ["foo_failure"]}},
                {"id": "solution-b", "status": "verified", "match": {"codes": ["bar_failure"]}},
            ],
        }), encoding="utf-8")
        (store / "prevention_rules.json").write_text('{"schema_version":1,"rules":[]}', encoding="utf-8")
        return store

    def test_multiplicity_and_causal_attribution(self):
        with tempfile.TemporaryDirectory() as temp:
            store = self._store(Path(temp))
            operational_memory.write_occurrence({
                "recorded_at": "2026-01-01T00:00:00+00:00",
                "phase": "render",
                "github_run_id": "1",
                "slug": "fixture",
                "status": "failed",
                "code": "foo_failure",
                "stage": "build",
                "message": "foo failed",
                "reported_count": 3,
                # This stale relation must not blame solution-b.
                "matched_solution_ids": ["solution-b"],
            }, store=store)
            operational_memory.write_occurrence({
                "recorded_at": "2026-01-02T00:00:00+00:00",
                "phase": "render",
                "github_run_id": "2",
                "slug": "fixture",
                "status": "done",
                "code": "render_success",
                "stage": "render",
                "message": "done",
                "verified_solution_ids": ["solution-b"],
            }, store=store)
            report = operational_memory_analysis.build(store)
            self.assertEqual(report["failure_occurrence_count"], 3)
            self.assertEqual(report["solution_evidence"]["solution-a"]["recurrences_after_fix"], 3)
            self.assertEqual(report["solution_evidence"]["solution-b"]["recurrences_after_fix"], 0)
            self.assertEqual(report["solution_evidence"]["solution-b"]["successful_verifications"], 1)

    def test_quality_and_telemetry_evidence_is_captured(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = self._store(root)
            build = root / "build" / "fixture"
            build.mkdir(parents=True)
            (build / "governor-summary.json").write_text(json.dumps({
                "status": "done", "slug": "fixture", "github_run_id": "77", "stages": {}
            }), encoding="utf-8")
            (build / "quality_report.json").write_text(json.dumps({
                "passed": True,
                "warnings": [{"code": "low_bitrate", "target": "youtube", "message": "bitrate low"}],
            }), encoding="utf-8")
            (build / "telemetry-summary.json").write_text(json.dumps({
                "span_count": 4,
                "failure_count": 0,
                "single_trace": True,
                "stages": {"assemble": {"total_duration_s": 12}},
                "recommendations": [{"priority": "medium", "category": "latency", "stage": "assemble", "reason": "slowest"}],
            }), encoding="utf-8")
            paths = record_operational_run.capture(build, store=store)
            self.assertGreaterEqual(len(paths), 4)
            rows = operational_memory._read_occurrences(store)
            codes = {row.get("code") for row in rows}
            self.assertIn("quality_warning:low_bitrate", codes)
            self.assertIn("telemetry_summary", codes)
            self.assertIn("telemetry_recommendation:latency", codes)


class VisualEvidenceTests(unittest.TestCase):
    def test_reviewed_feedback_is_separate_from_automated_risk(self):
        with tempfile.TemporaryDirectory() as temp:
            memory = Path(temp)
            records = [
                {
                    "id": "a", "slug": "one", "scene_number": 1, "decision": "unreviewed",
                    "asset_path": "one.jpg", "risk": {"effective_risk_score": 0.9, "findings": [{"code": "hand_contact"}]},
                    "provider": "stock", "generation_route": "stock", "symbol_family": "human",
                },
                {
                    "id": "b", "slug": "two", "scene_number": 2, "decision": "revise",
                    "comment": "Use a still image with special effects; this does not match the concept.",
                    "asset_path": "two.jpg", "risk": {"effective_risk_score": 0.2, "findings": [{"code": "reflection"}]},
                    "provider": "hero", "generation_route": "hero", "symbol_family": "object_tool",
                },
            ]
            (memory / "manifest.jsonl").write_text(
                "\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8"
            )
            report = analyze_visual_memory.build(memory)
            self.assertEqual(report["reviewed"], 1)
            self.assertEqual(report["reviewed_feedback_tags"]["prefer_effects_still"], 1)
            self.assertEqual(report["reviewed_feedback_tags"]["semantic_mismatch"], 1)
            self.assertEqual(report["automated_risk_tags"]["hand_contact"], 1)
            self.assertEqual(report["automated_risk_tags"]["reflection"], 1)
            self.assertEqual(report["review_queue"][0]["slug"], "one")


class PublishingTests(unittest.TestCase):
    def test_youtube_duplicate_receipt_skips_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / "queue.json"
            result = root / "result.json"
            queue.write_text(json.dumps({"slug": {"title": "T", "description": "D"}}), encoding="utf-8")
            result.write_text(json.dumps({"slug": {"video_id": "abc", "url": "https://youtube.com/watch?v=abc"}}), encoding="utf-8")
            with mock.patch.object(yt_publish, "QUEUE", queue), mock.patch.object(yt_publish, "RESULT", result), \
                    mock.patch.object(yt_publish, "access_token") as token, mock.patch.object(yt_publish, "upload") as upload:
                history = yt_publish.publish(["slug"])
            token.assert_not_called()
            upload.assert_not_called()
            self.assertEqual(history["slug"]["video_id"], "abc")

    def test_facebook_duplicate_receipt_skips_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / "queue.json"
            result = root / "result.json"
            queue.write_text(json.dumps({"slug": {"title": "T", "description": "D"}}), encoding="utf-8")
            result.write_text(json.dumps({"slug": {"video_id": "abc", "url": "https://facebook/abc"}}), encoding="utf-8")
            with mock.patch.object(fb_publish, "QUEUE", queue), mock.patch.object(fb_publish, "RESULT", result), \
                    mock.patch.dict(os.environ, {"FB_PAGE_ID": "1", "FB_PAGE_TOKEN": "x"}), \
                    mock.patch.object(fb_publish, "upload") as upload:
                history = fb_publish.publish(["slug"])
            upload.assert_not_called()
            self.assertEqual(history["slug"]["video_id"], "abc")


class SystemDiagnosticTests(unittest.TestCase):
    def test_unused_evidence_and_missing_receipts_become_findings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "build" / "one").mkdir(parents=True)
            (root / "build" / "one" / "script.json").write_text('{"title":"One","slug":"one","scenes":[]}', encoding="utf-8")
            (root / "pipeline" / "operational_memory").mkdir(parents=True)
            (root / "pipeline" / "operational_memory" / "index.json").write_text('{}', encoding="utf-8")
            (root / "pipeline" / "operational_memory" / "action_queue.json").write_text('{"actions":[]}', encoding="utf-8")
            (root / "pipeline" / "memory.json").write_text(json.dumps({
                "used_ids": list(range(500)), "banned_ids": [], "notes": ["feedback"],
                "scene_feedback": [], "videos": [], "query_weights": {},
            }), encoding="utf-8")
            (root / "pipeline" / "yt_publish_queue.json").write_text('{"one":{"title":"One"}}', encoding="utf-8")
            (root / "pipeline" / "fb_publish_queue.json").write_text('{}', encoding="utf-8")
            (root / "concept" / "visual_memory").mkdir(parents=True)
            (root / "concept" / "visual_memory" / "summary.json").write_text(json.dumps({
                "records": 10, "decisions": {"unreviewed": 10}
            }), encoding="utf-8")
            report = system_diagnostics.diagnostic(root)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("visual_memory_unanalyzed", codes)
            self.assertIn("free_text_notes_not_structured", codes)
            self.assertIn("permanent_stock_exclusion_growth", codes)
            self.assertIn("youtube_receipt_history_missing", codes)


if __name__ == "__main__":
    unittest.main()
