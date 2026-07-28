import json
from pathlib import Path
import tempfile
import unittest

from pipeline import whisperx_benchmark_ledger
from pipeline import whisperx_challenger


class WhisperXChallengerTests(unittest.TestCase):
    def _build(self, root: Path, *, manual_reference: bool = False) -> Path:
        build = root / "build" / "test-video"
        build.mkdir(parents=True)
        script = {
            "title": "Test Video",
            "slug": "test-video",
            "voiceover_config": {"provider": "ElevenLabs"},
            "scenes": [
                {
                    "text": "The signal starts here.",
                    "start": 0.2,
                    "duration": 1.8,
                },
                {
                    "text": "Then 4 doors open.",
                    "start": 2.0,
                    "duration": 2.0,
                },
            ],
        }
        (build / "script.json").write_text(json.dumps(script), encoding="utf-8")
        (build / "vo.mp3").write_bytes(b"test-audio")
        current_words = [
            {"w": "The", "s": 0.25, "e": 0.45},
            {"w": "signal", "s": 0.48, "e": 0.88},
            {"w": "starts", "s": 0.9, "e": 1.2},
            {"w": "here", "s": 1.22, "e": 1.6},
            {"w": "Then", "s": 2.12, "e": 2.38},
            {"w": "4", "s": 2.4, "e": 2.55},
            {"w": "doors", "s": 2.57, "e": 2.9},
            {"w": "open", "s": 2.92, "e": 3.35},
        ]
        (build / "words.json").write_text(json.dumps(current_words), encoding="utf-8")
        if manual_reference:
            reference = {
                "schema_version": 1,
                "reviewed_by": "James",
                "words": [
                    {"w": "The", "s": 0.2, "e": 0.42},
                    {"w": "signal", "s": 0.44, "e": 0.82},
                    {"w": "starts", "s": 0.84, "e": 1.16},
                    {"w": "here", "s": 1.18, "e": 1.55},
                    {"w": "Then", "s": 2.02, "e": 2.3},
                    {"w": "4", "s": 2.32, "e": 2.48},
                    {"w": "doors", "s": 2.5, "e": 2.83},
                    {"w": "open", "s": 2.85, "e": 3.28},
                ],
            }
            (build / "alignment-reference.json").write_text(
                json.dumps(reference), encoding="utf-8"
            )
        return build

    def _challenger_words(self):
        return whisperx_challenger._normalize_words(
            [
                {"w": "The", "s": 0.2, "e": 0.42},
                {"w": "signal", "s": 0.44, "e": 0.82},
                {"w": "starts", "s": 0.84, "e": 1.16},
                {"w": "here", "s": 1.18, "e": 1.55},
                {"w": "Then", "s": 2.02, "e": 2.3},
                {"w": "4", "s": 2.32, "e": 2.48},
                {"w": "doors", "s": 2.5, "e": 2.83},
                {"w": "open", "s": 2.85, "e": 3.28},
            ]
        )

    def test_flatten_whisperx_segments(self):
        payload = {
            "segments": [
                {
                    "words": [
                        {"word": "Hello", "start": 0.1, "end": 0.4},
                        {"word": "world", "start": 0.5, "end": 0.9},
                    ]
                }
            ]
        }
        words = whisperx_challenger.flatten_whisperx(payload)
        self.assertEqual([item["n"] for item in words], ["hello", "world"])

    def test_shadow_report_never_writes_production_timing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = self._build(root)
            before_script = (build / "script.json").read_bytes()
            before_words = (build / "words.json").read_bytes()
            report = whisperx_challenger.compare(
                build,
                self._challenger_words(),
                runtime_seconds=1.2,
                model_config={"package": "whisperx", "version": "test"},
            )
            self.assertFalse(report["production_timing_written"])
            self.assertEqual((build / "script.json").read_bytes(), before_script)
            self.assertEqual((build / "words.json").read_bytes(), before_words)
            self.assertTrue((build / "alignment-challenger.json").exists())
            self.assertTrue((build / "alignment-challenger-words.json").exists())
            self.assertEqual(report["challenger"]["special_token_coverage"], 1.0)

    def test_manual_reference_can_nominate_but_not_promote(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = self._build(root, manual_reference=True)
            report = whisperx_challenger.compare(
                build,
                self._challenger_words(),
                runtime_seconds=1.0,
                model_config={"package": "whisperx", "version": "test"},
            )
            self.assertTrue(report["manual_reference"])
            self.assertEqual(report["disposition"], "candidate_for_promotion_ledger")
            self.assertFalse(report["promotion_automatic"])

    def test_ledger_waits_for_minimum_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pipeline").mkdir()
            build = self._build(root, manual_reference=True)
            whisperx_challenger.compare(
                build,
                self._challenger_words(),
                runtime_seconds=1.0,
                model_config={"package": "whisperx", "version": "test"},
            )
            ledger = whisperx_benchmark_ledger.build(root)
            self.assertFalse(ledger["promotion_eligible_for_human_decision"])
            self.assertEqual(ledger["counts"]["successful_runs"], 1)
            self.assertFalse(ledger["promotion_checks"]["successful_runs"]["passed"])
            self.assertTrue((root / "pipeline" / "whisperx-benchmark-ledger.json").exists())


if __name__ == "__main__":
    unittest.main()
