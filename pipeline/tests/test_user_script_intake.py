from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import preflight
import user_script_intake


class UserScriptIntakeTests(unittest.TestCase):
    def test_plain_text_round_trip_preserves_words_and_punctuation(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "my-script"
            build.mkdir()
            source = "You call it normal—until the room changes. Don't blink. What did you expect?"
            (build / "source-script.txt").write_text(source, encoding="utf-8")
            (build / "submission.json").write_text(json.dumps({
                "title": "My Script",
                "target_scenes": 3,
            }), encoding="utf-8")
            report = user_script_intake.build_package(build)
            self.assertTrue(report["passed"], report)
            script = json.loads((build / "script.json").read_text(encoding="utf-8"))
            reconstructed = " ".join(scene["text"] for scene in script["scenes"])
            self.assertEqual(
                user_script_intake.canonical_spoken_text(source),
                user_script_intake.canonical_spoken_text(reconstructed),
            )
            self.assertEqual(script["source_script_filename"], "source-spoken.txt")
            self.assertTrue(script["source_script_verbatim"])
            self.assertFalse((build / "render.request").exists())

    def test_punctuation_only_change_breaks_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "punctuation-lock"
            build.mkdir()
            (build / "source-script.txt").write_text("This matters—doesn't it?", encoding="utf-8")
            (build / "submission.json").write_text('{"title":"Punctuation Lock","target_scenes":3}', encoding="utf-8")
            user_script_intake.build_package(build)
            script_path = build / "script.json"
            script = json.loads(script_path.read_text(encoding="utf-8"))
            script["scenes"][0]["text"] = script["scenes"][0]["text"].replace("—", ",")
            script_path.write_text(json.dumps(script), encoding="utf-8")
            report = user_script_intake.verify_lock(build)
            self.assertFalse(report["passed"])
            self.assertEqual(report["reason"], "narration_mismatch")

    def test_legacy_source_script_filename_is_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "legacy-source"
            build.mkdir()
            text = "One exact line. Another exact line. Final question?"
            (build / "source-script.txt").write_text(text, encoding="utf-8")
            (build / "script.json").write_text(json.dumps({
                "title": "Legacy Source",
                "slug": "legacy-source",
                "source_script_verbatim": True,
                "source_script_sha256": user_script_intake.digest_text(text),
                "scenes": [{"text": "One exact line."}, {"text": "Another exact line."}, {"text": "Final question?"}],
            }), encoding="utf-8")
            self.assertTrue(user_script_intake.verify_lock(build)["passed"])

    def test_performance_tags_require_explicit_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "tag-policy"
            build.mkdir()
            (build / "source-script.txt").write_text("[long pause] This line begins quietly. Then it opens.", encoding="utf-8")
            (build / "submission.json").write_text('{"title":"Tag Policy"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "performance_tag_policy"):
                user_script_intake.build_package(build)

    def test_extract_policy_keeps_tags_out_of_spoken_text_and_captions(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "tag-extract"
            build.mkdir()
            (build / "source-script.txt").write_text("[whisper] This is the knife line. Then the room returns.", encoding="utf-8")
            (build / "submission.json").write_text(json.dumps({
                "title": "Tag Extract",
                "performance_tag_policy": "extract",
                "target_scenes": 3,
            }), encoding="utf-8")
            user_script_intake.build_package(build)
            script = json.loads((build / "script.json").read_text(encoding="utf-8"))
            spoken = " ".join(scene["text"] for scene in script["scenes"])
            self.assertNotIn("[whisper]", spoken)
            self.assertIn("whisper", script["scenes"][0]["audio_tags"])
            self.assertTrue(user_script_intake.verify_lock(build)["passed"])

    def test_short_script_does_not_require_sixty_second_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "short-script"
            build.mkdir()
            (build / "source-script.txt").write_text("A short thought. A quiet room. What changes?", encoding="utf-8")
            (build / "submission.json").write_text('{"title":"Short Script","target_scenes":3}', encoding="utf-8")
            report = user_script_intake.build_package(build)
            self.assertTrue(report["passed"])
            script = json.loads((build / "script.json").read_text(encoding="utf-8"))
            self.assertLess(script["target_duration_seconds"], 60)
            self.assertNotIn("user_vo", script)

    def test_non_intake_script_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "protected"
            build.mkdir()
            (build / "source-script.txt").write_text("New words.", encoding="utf-8")
            (build / "script.json").write_text('{"title":"Existing","slug":"protected","scenes":[{"text":"Approved words."}]}', encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "non-intake"):
                user_script_intake.build_package(build)

    def test_representative_plain_text_package_passes_production_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / "ready-script"
            build.mkdir()
            source = " ".join([
                "An alarm clock rings beside an unopened notebook.",
                "A wooden door opens into a bright hallway.",
                "A river carries one leaf around a stone.",
                "A paper map folds until two roads touch.",
                "A mirror catches a room from another angle.",
                "A train changes tracks beneath a signal light.",
                "A seed splits and pushes through dark soil.",
                "A balance scale settles after one weight moves.",
                "A lighthouse beam turns across moving water.",
                "A key rests beside a lock on a workbench.",
                "The room grows quiet enough to hear your breath.",
                "Which ordinary object would you test first?",
            ])
            (build / "source-script.txt").write_text(source, encoding="utf-8")
            (build / "submission.json").write_text(json.dumps({
                "title": "Ready Script",
                "target_scenes": 12,
                "science_fidelity": "metaphor",
            }), encoding="utf-8")
            user_script_intake.build_package(build)
            report = preflight.assess(build, fix_safe=True)
            self.assertTrue(report["passed"], report)
            self.assertTrue(user_script_intake.verify_lock(build)["passed"])


if __name__ == "__main__":
    unittest.main()
