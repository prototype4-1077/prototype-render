import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import editorial_timeline
import export_verify
import locked_audio
import revision_cache
import selective_revision


class EditorialRevisionTests(unittest.TestCase):
    def _script(self):
        return {
            "title": "Test",
            "slug": "test",
            "scenes": [
                {"text": "one", "start": 0.0, "duration": 1.0, "clip": "old"},
                {"text": "two", "start": 1.0, "duration": 1.0, "clip": "old"},
                {"text": "three?", "start": 2.0, "duration": 1.0, "clip": "old"},
            ],
        }

    def _write_locked_audio(self, build: Path) -> str:
        audio = build / locked_audio.LOCKED_NAME
        audio.write_bytes(b"approved-delivery-audio" * 100)
        digest = hashlib.sha256(audio.read_bytes()).hexdigest()
        (build / locked_audio.MANIFEST_NAME).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "locked_audio": audio.name,
                    "locked_audio_sha256": digest,
                }
            ),
            encoding="utf-8",
        )
        return digest

    def test_boundary_matching(self):
        planned = export_verify.planned_boundaries([1.0, 2.0, 3.0])
        self.assertEqual(planned, [1.0, 3.0])
        matches, extra = export_verify.match_boundaries(
            planned, [1.08, 3.1, 5.5], tolerance=0.2
        )
        self.assertEqual(matches[0]["detected"], 1.08)
        self.assertEqual(matches[1]["detected"], 3.1)
        self.assertEqual(extra, [5.5])

    def test_narration_fingerprint_locks_text_and_timing(self):
        script = self._script()
        before = editorial_timeline.narration_fingerprint(script)
        script["scenes"][0]["query"] = "new visual only"
        self.assertEqual(before, editorial_timeline.narration_fingerprint(script))
        script["scenes"][0]["text"] = "changed"
        self.assertNotEqual(before, editorial_timeline.narration_fingerprint(script))

    def test_selective_revision_preserves_approved_hashes_and_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            script = self._script()
            (build / "script.json").write_text(json.dumps(script), encoding="utf-8")
            locked_hash = self._write_locked_audio(build)
            for index in range(3):
                (build / f"clip_{index:02d}.mp4").write_bytes(bytes([index + 1]) * 100_001)
                (build / f"youtube_seg_{index:02d}.mp4").write_bytes(bytes([index + 11]) * 100_001)
            feedback = {
                "slug": "test",
                "scenes": [
                    {"scene_index": 0, "decision": "approved", "comments": "ok"},
                    {"scene_index": 1, "decision": "revise", "comments": "replace"},
                    {"scene_index": 2, "decision": "approved", "comments": "ok"},
                ],
                "overall": {"decision": "revise"},
            }
            (build / "scene-feedback.request.json").write_text(
                json.dumps(feedback), encoding="utf-8"
            )
            revision_cache.build_manifest(build, run_id="123")
            report = selective_revision.prepare(build)
            self.assertEqual(report["revised_scenes"], [1])
            self.assertEqual(report["locked_audio_sha256"], locked_hash)
            self.assertTrue((build / "youtube_seg_00.mp4").exists())
            self.assertFalse((build / "youtube_seg_01.mp4").exists())
            revised_script = json.loads((build / "script.json").read_text())
            self.assertNotIn("clip", revised_script["scenes"][1])
            self.assertEqual(revised_script["scenes"][1]["text"], "two")

            (build / "clip_01.mp4").write_bytes(b"n" * 100_001)
            (build / "youtube_seg_01.mp4").write_bytes(b"r" * 100_001)
            (build / "final_youtube.mp4").write_bytes(b"f" * 100_001)
            result = selective_revision.finalize(build)
            self.assertTrue(result["passed"], result)
            self.assertEqual(result["approved_scenes_preserved"], 2)
            self.assertTrue(result["approved_delivery_audio_preserved"])
            self.assertEqual(result["locked_audio_sha256"], locked_hash)

    def test_otio_round_trip_when_installed(self):
        try:
            import opentimelineio  # noqa: F401
        except ImportError:
            self.skipTest("OpenTimelineIO not installed")
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            script = self._script()
            (build / "script.json").write_text(json.dumps(script), encoding="utf-8")
            locked_hash = self._write_locked_audio(build)
            for index in range(3):
                (build / f"youtube_seg_{index:02d}.mp4").write_bytes(b"v" * 100)
            manifest = editorial_timeline.build_timeline(build)
            self.assertEqual(manifest["scene_count"], 3)
            self.assertEqual(manifest["locked_delivery_audio_sha256"], locked_hash)
            verification = editorial_timeline.verify_timeline(build)
            self.assertTrue(verification["passed"], verification)
            self.assertEqual(verification["locked_delivery_audio_sha256"], locked_hash)


if __name__ == "__main__":
    unittest.main()
