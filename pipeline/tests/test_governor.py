from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_variants  # noqa: E402
from governor import (  # noqa: E402
    PipelineGovernor,
    artifact_signature,
    classify_command,
    classify_failure,
    failure_fingerprint,
    normalize_error,
    percentile,
)


class GovernorPureFunctionTests(unittest.TestCase):
    def test_percentile_interpolates(self):
        self.assertEqual(percentile([1], 0.95), 1)
        self.assertAlmostEqual(percentile([1, 2, 3, 4], 0.5), 2.5)

    def test_failure_fingerprint_is_stable_and_redacted(self):
        first = failure_fingerprint("hero", "failure", "API_KEY=secret123 timeout after 98 seconds /tmp/a")
        second = failure_fingerprint("hero", "failure", "API_KEY=other456 timeout after 12 seconds /tmp/b")
        self.assertEqual(first, second)
        normalized = normalize_error("Authorization: bearer-secret at /tmp/private/file 12345")
        self.assertNotIn("bearer-secret", normalized)
        self.assertNotIn("12345", normalized)

    def test_failure_classification(self):
        self.assertEqual(classify_failure("HTTP 503 service unavailable"), "transient")
        self.assertEqual(classify_failure("no script.json"), "deterministic")
        self.assertEqual(classify_failure("unexpected renderer exit"), "unknown")

    def test_command_classification_finds_scene_output(self):
        spec = classify_command(
            [sys.executable, "/repo/pipeline/assemble.py", "/tmp/build/demo", "youtube-scene", "7"],
            "/tmp/build/demo",
        )
        self.assertEqual(spec.name, "assemble")
        self.assertEqual(spec.item, "youtube-scene:7")
        self.assertEqual(spec.expected_outputs[0].name, "youtube_seg_07.mp4")

    def test_audio_variant_runner_can_be_governed(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        audio_variants.set_runner(fake_runner)
        try:
            audio_variants._run(["ffmpeg", "-version"])
        finally:
            audio_variants.set_runner(None)
        self.assertEqual(calls[0][0], ["ffmpeg", "-version"])
        self.assertTrue(calls[0][1]["capture_output"])


class GovernorIntegrationTests(unittest.TestCase):
    def test_history_drives_bounded_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "build" / "old"
            old.mkdir(parents=True)
            (old / "governor-summary.json").write_text(json.dumps({
                "stages": {"tts": {"success_durations_s": [10, 11, 12, 13, 14]}},
            }))
            current = root / "build" / "current"
            current.mkdir()
            governor = PipelineGovernor(current, repo_root=root, heartbeat_seconds=0.05)
            policy = governor.policy_for("tts")
            self.assertEqual(policy.source, "history")
            self.assertEqual(policy.sample_count, 5)
            self.assertGreaterEqual(policy.soft_timeout_s, 60)
            self.assertLess(policy.soft_timeout_s, 480)

    def test_successful_process_is_recorded_and_summarized(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_dir = root / "build" / "demo"
            build_dir.mkdir(parents=True)
            governor = PipelineGovernor(build_dir, repo_root=root, heartbeat_seconds=0.05)
            result = governor.run([sys.executable, "-c", "print('ok')"], timeout=2)
            self.assertEqual(result.returncode, 0)
            self.assertIn("ok", result.stdout)
            summary = governor.finalize("done", passes=1)
            self.assertEqual(summary["status"], "done")
            self.assertEqual(summary["stages"]["general"]["successes"], 1)
            self.assertTrue((build_dir / "governor-summary.json").exists())

    def test_timeout_kills_process_and_quarantines_partial_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_dir = root / "build" / "demo"
            pipeline_dir = root / "pipeline"
            build_dir.mkdir(parents=True)
            pipeline_dir.mkdir()
            script = pipeline_dir / "tts.py"
            script.write_text("import time\ntime.sleep(10)\n")
            (build_dir / "vo.mp3").write_bytes(b"partial")
            governor = PipelineGovernor(build_dir, repo_root=root, heartbeat_seconds=0.05)
            result = governor.run([sys.executable, str(script), str(build_dir)], timeout=0.25)
            self.assertEqual(result.returncode, 124)
            self.assertIn("GovernorTimeout", result.stderr)
            self.assertFalse((build_dir / "vo.mp3").exists())
            quarantined = list(build_dir.glob("vo.mp3.partial.*"))
            self.assertEqual(len(quarantined), 1)
            failure = governor.latest_failure()
            self.assertEqual(failure["stage"], "tts")
            self.assertEqual(failure["status"], "timeout")

    def test_artifact_signature_ignores_governor_heartbeat_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            (build_dir / "real.txt").write_text("x")
            first = artifact_signature(build_dir)
            (build_dir / "governor").mkdir()
            (build_dir / "governor" / "current.json").write_text("{}")
            second = artifact_signature(build_dir)
            self.assertEqual(first["digest"], second["digest"])


if __name__ == "__main__":
    unittest.main()
