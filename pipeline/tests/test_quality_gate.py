from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import quality_gate  # noqa: E402


class QualityGateTests(unittest.TestCase):
    def test_parse_ratio(self):
        self.assertEqual(quality_gate.parse_ratio("30/1"), 30)
        self.assertEqual(quality_gate.parse_ratio("24000/1001"), 24000 / 1001)
        self.assertIsNone(quality_gate.parse_ratio("0/0"))

    def test_expected_duration_prefers_timed_scene_end(self):
        script = {"scenes": [
            {"start": 0, "duration": 2.5},
            {"start": 2.5, "duration": 3.0},
        ]}
        self.assertEqual(quality_gate.expected_script_duration(script), 5.5)

    def test_check_output_enforces_orientation_and_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final.mp4"
            path.write_bytes(b"x" * (quality_gate.MIN_FILE_BYTES + 1))
            probe = {
                "ok": True,
                "format": {"duration": "50", "format_name": "mp4", "bit_rate": "1000000"},
                "streams": [
                    {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1", "codec_name": "h264", "duration": "50"},
                    {"codec_type": "audio", "codec_name": "aac", "duration": "50"},
                ],
            }
            with mock.patch.object(quality_gate, "probe_media", return_value=probe):
                result = quality_gate.check_output(
                    path,
                    target_name="portrait",
                    orientation="portrait",
                    require_audio=True,
                    expected_duration_s=30,
                    deep=False,
                )
            codes = {issue["code"] for issue in result["failures"]}
            self.assertIn("wrong_orientation", codes)
            self.assertIn("duration_mismatch", codes)

    def test_run_quality_gate_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            (build_dir / "script.json").write_text(json.dumps({
                "scenes": [{"start": 0, "duration": 10}],
            }))
            passing = {"path": "fake", "failures": [], "warnings": []}
            with mock.patch.object(quality_gate, "check_output", return_value=passing) as check:
                report = quality_gate.run_quality_gate(build_dir, deep=False)
            self.assertTrue(report["passed"])
            self.assertEqual(check.call_count, 1)
            self.assertEqual(check.call_args.kwargs["target_name"], "youtube")
            self.assertEqual(check.call_args.kwargs["orientation"], "landscape")
            saved = json.loads((build_dir / "quality_report.json").read_text())
            self.assertTrue(saved["passed"])

    def test_curation_mode_does_not_require_youtube_or_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            (build_dir / "script.json").write_text(json.dumps({
                "curate_scenes": [1],
                "scenes": [{"duration": 2}],
            }))
            passing = {"path": "fake", "failures": [], "warnings": []}
            with mock.patch.object(quality_gate, "check_output", return_value=passing) as check:
                report = quality_gate.run_quality_gate(build_dir, deep=False)
            self.assertTrue(report["passed"])
            self.assertEqual(report["mode"], "curation")
            self.assertEqual(check.call_count, 1)
            kwargs = check.call_args.kwargs
            self.assertFalse(kwargs["require_audio"])
            self.assertIsNone(kwargs["orientation"])

    def test_explicit_music_alternatives_are_independently_probed(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            (build_dir / "script.json").write_text(json.dumps({
                "scenes": [{"start": 0, "duration": 10}],
            }))
            (build_dir / "music_variants.json").write_text(json.dumps({
                "variants": [
                    {"variant": 3, "youtube_video": "final_youtube.mp4"},
                    {"variant": 1, "youtube_video": "final_youtube_music_01.mp4"},
                ],
            }))
            passing = {"path": "fake", "failures": [], "warnings": []}
            with mock.patch.object(quality_gate, "check_output", return_value=passing) as check:
                report = quality_gate.run_quality_gate(build_dir, deep=True)
            self.assertTrue(report["passed"])
            self.assertEqual(check.call_count, 2)
            calls = {call.kwargs["target_name"]: call.kwargs for call in check.call_args_list}
            self.assertTrue(calls["youtube"]["deep"])
            self.assertFalse(calls["final_youtube_music_01"]["deep"])



if __name__ == "__main__":
    unittest.main()
