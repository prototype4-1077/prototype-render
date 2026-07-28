from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


PIPELINE = Path(__file__).resolve().parents[1]
REPO_ROOT = PIPELINE.parent
sys.path.insert(0, str(PIPELINE))

import tts  # noqa: E402


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class ElevenV3TTSTests(unittest.TestCase):
    def test_defaults_target_liam_v3_at_max_creativity(self) -> None:
        script = {
            "voice_settings": {
                "stability": 0.31,
                "similarity_boost": 0.72,
                "style": 0.35,
                "speed": 0.95,
            }
        }
        settings = tts.resolve_voice_settings(script, tts.DEFAULT_MODEL_ID)
        self.assertEqual(tts.DEFAULT_VOICE_ID, "TX3LPaxmHKxFdv7VOQHJ")
        self.assertEqual(tts.DEFAULT_MODEL_ID, "eleven_v3")
        self.assertEqual(settings["stability"], 0.0)
        self.assertEqual(settings["style"], 0.0)
        self.assertEqual(settings["similarity_boost"], 0.72)
        self.assertEqual(settings["speed"], 0.95)

    def test_named_stability_modes_map_to_v3_values(self) -> None:
        for mode, expected in tts.STABILITY_BY_MODE.items():
            with self.subTest(mode=mode):
                settings = tts.resolve_voice_settings(
                    {"elevenlabs_stability_mode": mode}, tts.DEFAULT_MODEL_ID
                )
                self.assertEqual(settings["stability"], expected)

    def test_explicit_tags_do_not_change_scene_text(self) -> None:
        script = {
            "scenes": [
                {"text": "Listen closely.", "audio_tags": "[whispers]"},
                {"text": "What happens next?", "audio_tags": ["curious"]},
            ]
        }
        original = copy.deepcopy(script)
        text, tags = tts.build_tts_text(script, tts.DEFAULT_MODEL_ID)
        self.assertEqual(
            text,
            "[whispers] Listen closely. [curious] What happens next?",
        )
        self.assertEqual(tags, [["whispers"], ["curious"]])
        self.assertEqual(script, original)

    def test_auto_tags_leave_plain_opener_neutral(self) -> None:
        script = {
            "scenes": [
                {"text": "You think this is ordinary."},
                {"text": "Could it be something else?"},
                {"text": "The pattern turns inside out!", "visual_function": "transformation"},
                {"text": "And then you notice the silence."},
            ]
        }
        _text, tags = tts.build_tts_text(script, tts.DEFAULT_MODEL_ID)
        self.assertEqual(tags[0], [])
        self.assertEqual(tags[1], ["curious"])
        self.assertEqual(tags[2], ["excited"])
        self.assertEqual(tags[3], ["whispers"])

    def test_opening_mood_selects_delivery_instead_of_fixed_hook(self) -> None:
        cases = {
            "laughing": ["laughs"],
            "low tone": ["low voice"],
            "thoughtful": ["thoughtful"],
            "sarcastic": ["sarcastic"],
            "curious": ["curious"],
            "excited": ["excited"],
            "neutral": [],
        }
        for mood, expected in cases.items():
            with self.subTest(mood=mood):
                scene = {"text": "Opening line.", "opening_mood": mood}
                self.assertEqual(tts.infer_audio_tags(scene, 0, 2), expected)

    def test_invalid_opening_mood_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid opening_mood"):
            tts.infer_audio_tags(
                {"text": "Opening line.", "opening_mood": "randomly musical"},
                0,
                2,
            )

    def test_explicit_empty_tags_disable_auto_tag_for_one_scene(self) -> None:
        script = {
            "scenes": [
                {"text": "Is this neutral?", "audio_tags": []},
                {"text": "Close."},
            ]
        }
        _text, tags = tts.build_tts_text(script, tts.DEFAULT_MODEL_ID)
        self.assertEqual(tags[0], [])
        self.assertEqual(tags[1], ["whispers"])

    def test_alignment_finds_spoken_text_after_tag_characters(self) -> None:
        aligned_text = "[curious] Hello there. [whispers] Stay awake."
        starts = [index / 10 for index in range(len(aligned_text))]
        ends = [(index + 1) / 10 for index in range(len(aligned_text))]
        script = {
            "scenes": [
                {"text": "Hello there."},
                {"text": "Stay awake."},
            ]
        }
        tts.apply_scene_timings(
            script,
            {
                "characters": list(aligned_text),
                "character_start_times_seconds": starts,
                "character_end_times_seconds": ends,
            },
        )
        self.assertEqual(script["scenes"][0]["start"], 1.0)
        self.assertEqual(script["scenes"][1]["start"], 3.4)
        self.assertGreaterEqual(script["scenes"][0]["duration"], 2.0)

    def test_nested_or_multiline_tag_is_rejected(self) -> None:
        for tag in ("[curious][excited]", "curious\nexcited"):
            with self.subTest(tag=tag):
                with self.assertRaisesRegex(ValueError, "invalid audio tag"):
                    tts.normalize_audio_tags(tag)

    def test_voice_name_resolves_exact_match_and_persists_id(self) -> None:
        payload = {
            "voices": [
                {"voice_id": "spuds123", "name": "Granpa   Spuds Oxley"},
                {"voice_id": "other", "name": "Other Voice"},
            ],
            "has_more": False,
        }
        script = {"elevenlabs_voice_name": "granpa spuds oxley"}
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}, clear=False), \
             mock.patch("urllib.request.urlopen", return_value=_FakeResponse(json.dumps(payload).encode())):
            voice_id = tts.resolve_voice_id(script)
        self.assertEqual(voice_id, "spuds123")
        self.assertEqual(script["elevenlabs_voice_id"], "spuds123")
        self.assertEqual(script["elevenlabs_voice_name"], "Granpa   Spuds Oxley")

    def test_voice_name_resolution_rejects_ambiguity(self) -> None:
        payload = {
            "voices": [
                {"voice_id": "a", "name": "Granpa Spuds Oxley"},
                {"voice_id": "b", "name": "granpa spuds oxley"},
            ],
            "has_more": False,
        }
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}, clear=False), \
             mock.patch("urllib.request.urlopen", return_value=_FakeResponse(json.dumps(payload).encode())):
            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                tts.resolve_voice_id({"elevenlabs_voice_name": "Granpa Spuds Oxley"})

    def test_voice_name_resolution_rejects_missing_match(self) -> None:
        payload = {
            "voices": [{"voice_id": "other", "name": "Other Voice"}],
            "has_more": False,
        }
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}, clear=False), \
             mock.patch("urllib.request.urlopen", return_value=_FakeResponse(json.dumps(payload).encode())):
            with self.assertRaisesRegex(RuntimeError, "was not found"):
                tts.resolve_voice_id({"elevenlabs_voice_name": "Granpa Spuds Oxley"})

    def test_voice_name_changes_tts_fingerprint(self) -> None:
        base = {"scenes": [{"text": "Hello."}], "elevenlabs_voice_id": "same"}
        first = copy.deepcopy(base)
        first["elevenlabs_voice_name"] = "Voice A"
        second = copy.deepcopy(base)
        second["elevenlabs_voice_name"] = "Voice B"
        self.assertNotEqual(
            tts.tts_fingerprint(first, tts.DEFAULT_MODEL_ID),
            tts.tts_fingerprint(second, tts.DEFAULT_MODEL_ID),
        )

    def test_reality_machine_tags_never_enter_caption_text(self) -> None:
        path = REPO_ROOT / "build" / "the-reality-machine-dmt-v3" / "script.json"
        script = json.loads(path.read_text(encoding="utf-8"))
        caption_text = " ".join(scene["text"] for scene in script["scenes"])
        tagged_text, applied = tts.build_tts_text(script, tts.DEFAULT_MODEL_ID)

        self.assertEqual(len(script["scenes"]), 30)
        self.assertNotIn("[", caption_text)
        self.assertNotIn("]", caption_text)
        self.assertIn("[long pause] [thoughtful] I took DMT", tagged_text)
        self.assertIn("[shouting] “Who built this?”", tagged_text)
        self.assertIn("[annoyed] “I definitely did not build this.", tagged_text)
        self.assertEqual(applied[14], ["shouting"])
        self.assertEqual(applied[17], ["annoyed"])
        self.assertLessEqual(len(tagged_text), tts.V3_CHARACTER_LIMIT)


if __name__ == "__main__":
    unittest.main()
