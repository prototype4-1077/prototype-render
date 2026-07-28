import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import animation_profiles
import governed_build
import profiles
import visual_symbols


def script(profile_name, character=None):
    value = {
        "title": "Animation Fixture",
        "slug": "animation-fixture",
        "animation_profile": profile_name,
        "scenes": [
            {
                "text": "A belief turns like a gear.",
                "query": "interlocking gears turning under warm light",
                "human_role": "none",
                "duration": 5.0,
            },
            {
                "text": "The room changes when attention moves.",
                "query": "ordinary room transforming as a beam of light moves",
                "image_prompt": "ordinary room transforming around a moving beam",
                "hero": True,
                "human_role": "none",
                "duration": 5.0,
            },
            {
                "text": "June watches the road from his porch.",
                "query": "June Oxley rocking on a porch beside a gravel road",
                "human_role": "narrator",
                "duration": 5.0,
            },
        ],
    }
    if character:
        value["profile"] = character
    return value


class AnimationProfileTests(unittest.TestCase):
    def test_three_profiles_are_available(self):
        self.assertEqual(
            set(animation_profiles.profiles()),
            {
                animation_profiles.ANIMATED_TIER1,
                animation_profiles.JUNE_TIER1,
                animation_profiles.JUNE_STANDARD,
            },
        )

    def test_aliases_canonicalize(self):
        self.assertEqual(
            animation_profiles.resolve({"animation_style": "premium animated"}, strict=True),
            animation_profiles.ANIMATED_TIER1,
        )
        self.assertEqual(
            animation_profiles.resolve({"animation_style": "tier1 june oxley"}, strict=True),
            animation_profiles.JUNE_TIER1,
        )
        self.assertEqual(
            animation_profiles.resolve({"animation_style": "regular june oxley animated"}, strict=True),
            animation_profiles.JUNE_STANDARD,
        )

    def test_tier1_contract_sets_real_motion_floor(self):
        value = script(animation_profiles.ANIMATED_TIER1)
        self.assertTrue(animation_profiles.apply_defaults(value))
        self.assertEqual(value["animation_contract_version"], 1)
        self.assertEqual(value["max_still_source_ratio"], 0.2)
        self.assertEqual(value["minimum_true_motion_ratio"], 0.8)
        self.assertEqual(value["caption_policy"], "minimal_keywords_only")
        self.assertIn("premium cinematic animation", value["scenes"][0]["animation_query"])
        self.assertIn("interlocking gears", value["scenes"][0]["animation_base_query"])
        self.assertEqual(animation_profiles.validate(value), [])

    def test_june_tier1_locks_identity_only_on_character_scenes(self):
        value = script(animation_profiles.JUNE_TIER1)
        animation_profiles.apply_defaults(value)
        self.assertEqual(value["profile"], profiles.JUNE_OXLEY)
        self.assertEqual(value["animation_character_reference_id"], "june_oxley_v1")

        object_scene = value["scenes"][0]
        self.assertFalse(object_scene["animation_character_required"])
        self.assertNotIn("animation_character_reference_id", object_scene)
        self.assertNotIn("same original June Oxley character", object_scene["animation_query"])
        self.assertIn("recurring rural small-town setting", object_scene["animation_query"])

        character_scene = value["scenes"][2]
        self.assertTrue(character_scene["animation_character_required"])
        self.assertEqual(
            character_scene["animation_character_reference_id"], "june_oxley_v1"
        )
        self.assertIn("same original June Oxley character", character_scene["animation_query"])
        self.assertIn("no face drift", character_scene["animation_query"])
        self.assertEqual(animation_profiles.validate(value, profiles.JUNE_OXLEY), [])

    def test_june_object_scenes_do_not_receive_character_anatomy(self):
        value = {
            "title": "Object Town",
            "slug": "object-town",
            "profile": "june_oxley",
            "animation_profile": animation_profiles.JUNE_TIER1,
            "scenes": [
                {
                    "text": "The fence remembers the storm.",
                    "query": "wooden fence flexing in wind beside a gravel road",
                    "human_role": "none",
                    "duration": 5.0,
                },
                {
                    "text": "Two squirrels argue over a pecan.",
                    "query": "two squirrels tugging a pecan on a porch rail",
                    "human_role": "none",
                    "duration": 5.0,
                },
            ],
        }
        animation_profiles.apply_defaults(value, profiles.JUNE_OXLEY)
        report = visual_symbols.analyze(value, profiles.JUNE_OXLEY)
        self.assertLessEqual(report["human_presence_ratio"], 0.5)
        for scene in value["scenes"]:
            self.assertFalse(scene["animation_character_required"])
            self.assertNotIn("animation_character_reference_id", scene)
            self.assertNotIn("elderly white rural man", scene["animation_query"])
            self.assertNotIn("same original June Oxley character", scene["animation_query"])

    def test_standard_june_is_lighter_but_not_template_grade(self):
        value = script(animation_profiles.JUNE_STANDARD, profiles.JUNE_OXLEY)
        animation_profiles.apply_defaults(value, profiles.JUNE_OXLEY)
        self.assertEqual(value["animation_quality_tier"], 2)
        self.assertEqual(value["max_still_source_ratio"], 0.3)
        self.assertEqual(value["minimum_true_motion_ratio"], 0.7)
        object_query = value["scenes"][0]["animation_query"]
        character_query = value["scenes"][2]["animation_query"]
        self.assertIn("polished stylized 2D or 2.5D", object_query)
        self.assertIn("no low-grade template graphics", object_query)
        self.assertNotIn("same original June Oxley character", object_query)
        self.assertIn("same original June Oxley character", character_query)

    def test_june_animation_rejects_other_character_profile(self):
        value = script(animation_profiles.JUNE_TIER1, "someone_else")
        with self.assertRaises(ValueError):
            animation_profiles.apply_defaults(value, "someone_else")

    def test_unprofiled_script_is_unchanged(self):
        value = {"title": "Plain", "slug": "plain", "scenes": [{"text": "Still plain."}]}
        before = json.dumps(value, sort_keys=True)
        self.assertFalse(animation_profiles.apply_defaults(value))
        self.assertEqual(json.dumps(value, sort_keys=True), before)

    def test_governed_preflight_persists_style_and_canonical_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = script(animation_profiles.JUNE_STANDARD)
            value["elevenlabs_voice_name"] = "Granpa Spuds Oxley"
            (root / "script.json").write_text(json.dumps(value), encoding="utf-8")
            prepared = governed_build._apply_animation_contract(root)
            saved = json.loads((root / "script.json").read_text(encoding="utf-8"))
            self.assertEqual(prepared["profile"], profiles.JUNE_OXLEY)
            self.assertEqual(
                saved["elevenlabs_voice_id"], "NOpBlnGInO9m6vDvFkFC"
            )
            self.assertEqual(saved["scenes"][0]["query"], saved["scenes"][0]["animation_query"])
            self.assertIn("animation_base_query", saved["scenes"][0])
            self.assertNotIn("same original June Oxley character", saved["scenes"][0]["query"])
            self.assertIn("same original June Oxley character", saved["scenes"][2]["query"])
            self.assertEqual(animation_profiles.validate(saved, profiles.JUNE_OXLEY), [])

    def test_governed_preflight_rejects_wrong_character_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            value = script(animation_profiles.JUNE_STANDARD)
            value["elevenlabs_voice_name"] = "Granpa Spuds Oxley"
            value["elevenlabs_voice_id"] = "TX3LPaxmHKxFdv7VOQHJ"
            (root / "script.json").write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires voice"):
                governed_build._apply_animation_contract(root)


if __name__ == "__main__":
    unittest.main()
