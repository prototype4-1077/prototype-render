import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PIPELINE = Path(__file__).resolve().parents[1]
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

from governor import PipelineGovernor
from observability import TelemetrySession
from telemetry_report import build_report


class ObservabilityTests(unittest.TestCase):
    def _build(self, root: Path) -> Path:
        build = root / "build" / "trace-test"
        build.mkdir(parents=True)
        script = {
            "title": "Trace Test",
            "slug": "trace-test",
            "scenes": [
                {
                    "text": "A quiet signal moves.",
                    "start": 0.0,
                    "duration": 2.0,
                    "visual_function": "mechanism",
                    "symbol_family": "signals",
                    "hero": True,
                    "image_prompt": "secret cinematic prompt that must not enter telemetry",
                    "generation_provider": "fixture-provider",
                    "generation_model": "fixture-model",
                    "workflow": "single_subject_v1",
                    "seed": 42,
                }
            ],
        }
        (build / "script.json").write_text(json.dumps(script), encoding="utf-8")
        return build

    def test_session_records_scene_span_without_prompt_text(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ,
            {
                "VIDEO_TRACE_ID": "1234567890abcdef1234567890abcdef",
                "PIPELINE_TELEMETRY_DISABLED": "0",
            },
            clear=False,
        ):
            build = self._build(Path(temp))
            session = TelemetrySession(build, run_id="a" * 32, mode="test")
            handle = session.start_stage(
                stage="hero",
                item="0",
                label="hero:0",
            )
            session.finish_stage(
                handle,
                status="success",
                returncode=0,
                duration_s=1.25,
                made_progress=True,
                artifact_after={"count": 2, "bytes": 200000, "digest": "abc"},
            )
            session.finish_run("done", {"passes": 1, "incidents": []})
            spans_text = (build / "telemetry" / "spans.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("secret cinematic prompt", spans_text)
            self.assertIn("video.prompt.sha256", spans_text)
            self.assertIn("fixture-provider", spans_text)
            report = build_report(build)
            self.assertTrue(report["single_trace"], report)
            self.assertEqual(report["trace_ids"], ["1234567890abcdef1234567890abcdef"])
            self.assertEqual(report["scene_span_count"], 1)
            self.assertFalse(report["privacy"]["prompt_text_recorded"])

    def test_governor_behavior_is_preserved_and_failure_is_measured(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ,
            {
                "VIDEO_TRACE_ID": "abcdefabcdefabcdefabcdefabcdefab",
                "PIPELINE_TELEMETRY_DISABLED": "0",
                "GOVERNOR_CONSOLE_HEARTBEATS": "0",
            },
            clear=False,
        ):
            build = self._build(Path(temp))
            governor = PipelineGovernor(build, heartbeat_seconds=0.1)
            success = governor.run(
                [sys.executable, "-c", "print('ok')"],
                stage_override="general",
                timeout=10,
            )
            failure = governor.run(
                [sys.executable, "-c", "import sys; sys.exit(3)"],
                stage_override="general",
                timeout=10,
            )
            self.assertEqual(success.returncode, 0)
            self.assertEqual(failure.returncode, 3)
            governor.finalize("done", passes=1)
            self.assertTrue((build / "governor-summary.json").exists())
            report = build_report(build)
            self.assertEqual(report["stages"]["general"]["attempts"], 2)
            self.assertEqual(report["stages"]["general"]["failures"], 1)
            self.assertEqual(report["failure_count"], 1)

    def test_shared_trace_id_across_process_sessions(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ,
            {
                "VIDEO_TRACE_ID": "fedcbafedcbafedcbafedcbafedcbafe",
                "PIPELINE_TELEMETRY_DISABLED": "0",
            },
            clear=False,
        ):
            build = self._build(Path(temp))
            first = TelemetrySession(build, run_id="1" * 32, github_run_id="100")
            h1 = first.start_stage(stage="tts", item=None, label="tts")
            first.finish_stage(h1, status="success", returncode=0, duration_s=0.1)
            first.finish_run("done")
            second = TelemetrySession(build, run_id="1" * 32, github_run_id="100")
            h2 = second.start_stage(stage="assemble", item="youtube-scene:0", label="assemble")
            second.finish_stage(h2, status="success", returncode=0, duration_s=0.2)
            second.finish_run("done")
            report = build_report(build)
            self.assertTrue(report["single_trace"], report)
            self.assertEqual(report["trace_ids"], ["fedcbafedcbafedcbafedcbafedcbafe"])
            self.assertGreaterEqual(report["span_count"], 4)

    def test_disabled_telemetry_is_non_blocking(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ,
            {"PIPELINE_TELEMETRY_DISABLED": "1"},
            clear=False,
        ):
            build = self._build(Path(temp))
            governor = PipelineGovernor(build, heartbeat_seconds=0.1)
            result = governor.run(
                [sys.executable, "-c", "print('still works')"],
                stage_override="general",
                timeout=10,
            )
            governor.finalize("done", passes=1)
            self.assertEqual(result.returncode, 0)
            self.assertTrue((build / "governor-summary.json").exists())


if __name__ == "__main__":
    unittest.main()
