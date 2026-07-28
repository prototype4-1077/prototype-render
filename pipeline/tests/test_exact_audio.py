from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))

import exact_audio  # noqa: E402


class ExactAudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = (b"ID3" + bytes(range(256))) * 19
        self.encoded = base64.b64encode(self.source).decode("ascii")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_parts(self, chunk_size: int = 64) -> str:
        for index, offset in enumerate(range(0, len(self.encoded), chunk_size)):
            (self.root / f"vo.mp3.b64.part{index:03d}").write_text(
                self.encoded[offset : offset + chunk_size], encoding="ascii"
            )
        return str(self.root / "vo.mp3.b64.part*")

    @mock.patch.object(exact_audio, "probe_audio", return_value=("mp3", 1.25))
    def test_round_trip_preserves_exact_bytes(self, _probe: mock.Mock) -> None:
        output = self.root / "vo.mp3"
        report = self.root / "audio-verification.json"
        verification = exact_audio.restore_exact_audio(
            parts_glob=self.write_parts(),
            output=output,
            expected_sha256=hashlib.sha256(self.source).hexdigest(),
            expected_size=len(self.source),
            expected_duration=1.25,
            source_attachment="supplied.mp3",
            report=report,
        )
        self.assertEqual(output.read_bytes(), self.source)
        self.assertEqual(verification["sha256"], hashlib.sha256(self.source).hexdigest())
        self.assertEqual(verification["size_bytes"], len(self.source))
        self.assertTrue(verification["exact_bytes_restored"])
        self.assertFalse(verification["transcoded_before_pipeline"])
        self.assertTrue(report.is_file())

    def test_missing_middle_part_is_rejected(self) -> None:
        pattern = self.write_parts()
        (self.root / "vo.mp3.b64.part001").unlink()
        with self.assertRaisesRegex(exact_audio.ExactAudioError, "contiguous"):
            exact_audio.decode_parts(pattern)

    @mock.patch.object(exact_audio, "probe_audio", return_value=("mp3", 1.25))
    def test_sha_mismatch_is_rejected_before_output(self, _probe: mock.Mock) -> None:
        output = self.root / "vo.mp3"
        with self.assertRaisesRegex(exact_audio.ExactAudioError, "SHA-256 mismatch"):
            exact_audio.restore_exact_audio(
                parts_glob=self.write_parts(),
                output=output,
                expected_sha256="0" * 64,
                expected_size=len(self.source),
                expected_duration=1.25,
                source_attachment="supplied.mp3",
            )
        self.assertFalse(output.exists())

    @mock.patch.object(exact_audio, "probe_audio", return_value=("mp3", 2.0))
    def test_duration_mismatch_is_rejected_before_output(self, _probe: mock.Mock) -> None:
        output = self.root / "vo.mp3"
        with self.assertRaisesRegex(exact_audio.ExactAudioError, "duration mismatch"):
            exact_audio.restore_exact_audio(
                parts_glob=self.write_parts(),
                output=output,
                expected_sha256=hashlib.sha256(self.source).hexdigest(),
                expected_size=len(self.source),
                expected_duration=1.25,
                source_attachment="supplied.mp3",
            )
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
