import os
import sys
import unittest


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import visual_symbols


class VisualSymbolPlannerTests(unittest.TestCase):
    def test_reference_vocabulary_uses_distinct_symbol_families(self):
        examples = {
            "perception": "gallery wall filled with different human eyes",
            "language": "scattered alphabet letters move beneath a hand",
            "architecture": "one door opens in a hallway",
            "pathway": "two arrows point in opposite directions",
            "time_memory": "record needle turns beside old photographs",
            "nature": "seed germinating in dark soil",
            "world_scale": "city upside down above a desert landscape",
            "geometry": "nested illuminated rings expand recursively",
            "object_tool": "compass turns beside a folded map",
        }
        for expected, query in examples.items():
            with self.subTest(expected=expected):
                scene = {"text": "A philosophical beat.", "query": query}
                self.assertEqual(visual_symbols.classify_scene(scene), expected)

    def test_generic_human_mood_gets_a_physical_symbol_query(self):
        scene = {
            "text": "The words no longer fit the truth you are trying to name.",
            "keywords": ["words", "truth"],
            "query": "thoughtful person looking out window moody",
        }
        script = {"scenes": [scene]}
        self.assertTrue(visual_symbols.apply_plan(script))
        self.assertIn("printed words", scene["symbol_query"])
        self.assertEqual(scene["symbol_family"], "language")
        self.assertEqual(visual_symbols.effective_query(scene), scene["symbol_query"])
        self.assertFalse(visual_symbols.is_generic_human(scene))

    def test_concrete_human_action_is_preserved_and_given_a_role(self):
        scene = {
            "text": "She crosses the threshold and enters the room.",
            "query": "woman opens wooden door and walks through bright hallway",
        }
        script = {"scenes": [scene]}
        visual_symbols.apply_plan(script)
        self.assertNotIn("symbol_query", scene)
        self.assertEqual(scene["symbol_family"], "architecture")
        self.assertEqual(scene["human_role"], "explorer")
        self.assertFalse(visual_symbols.is_generic_human(scene))

    def test_symbol_fallback_prefers_semantics_over_forced_rotation(self):
        suggestion = visual_symbols.derive_symbol_query(
            {"text": "The belief changes the path."},
            recent_families=["language", "language"],
        )
        self.assertEqual(suggestion["family"], "language")

    def test_explicit_editorial_choice_is_never_overwritten(self):
        scene = {
            "text": "The thought remains unfinished.",
            "query": "person sitting alone",
            "symbol_family": "geometry",
            "visual_function": "recursion",
            "primary_symbol": "spiral",
            "human_role": "scale_reference",
        }
        visual_symbols.apply_plan({"scenes": [scene]})
        self.assertEqual(scene["symbol_family"], "geometry")
        self.assertEqual(scene["visual_function"], "recursion")
        self.assertEqual(scene["primary_symbol"], "spiral")
        self.assertEqual(scene["human_role"], "scale_reference")

    def test_june_profile_keeps_literal_character_footage(self):
        scene = {
            "text": "June says the truth is hiding from the electric bill.",
            "query": "old white Southern man staring at unpaid bill on porch",
        }
        visual_symbols.apply_plan({"scenes": [scene]}, visual_symbols.JUNE_OXLEY)
        self.assertNotIn("symbol_query", scene)


class VisualSymbolAuditTests(unittest.TestCase):
    def _generic_people_script(self, strict=True):
        script = {
            "scenes": [
                {
                    "text": f"He waits quietly for beat {index}.",
                    "query": "thoughtful person standing alone in fog",
                }
                for index in range(12)
            ]
        }
        if strict:
            script["visual_policy"] = visual_symbols.POLICY_NAME
        return script

    def test_strict_policy_rejects_generic_human_repetition(self):
        report = visual_symbols.analyze(self._generic_people_script())
        self.assertFalse(report["passes"])
        self.assertGreater(report["human_presence_ratio"], .9)
        self.assertTrue(any("generic human filler repeats" in item
                            for item in report["violations"]))

    def test_negated_human_terms_do_not_count_as_visible_people(self):
        scene = {
            "text": "The room finally becomes quiet.",
            "query": (
                "small brass bell before a dark television, object-only composition, "
                "no people, faces, hands or bodies"
            ),
            "symbol_family": "object_tool",
        }
        self.assertFalse(visual_symbols.uses_human(scene))
        self.assertEqual(visual_symbols.observed_family(scene), "object_tool")

    def test_advisory_policy_reports_without_blocking(self):
        report = visual_symbols.analyze(self._generic_people_script(strict=False))
        self.assertTrue(report["passes"])
        self.assertFalse(report["violations"])
        self.assertTrue(report["warnings"])

    def test_default_policy_allows_a_coherent_five_scene_family_run(self):
        script = {
            "visual_policy": visual_symbols.POLICY_NAME,
            "scenes": [
                {"text": f"Beat {index}.", "query": "nested rings expand slowly"}
                for index in range(5)
            ] + [
                {"text": "A doorway opens.", "query": "one door opens in a hallway"},
                {"text": "A seed grows.", "query": "seed germinating in dark soil"},
                {"text": "A map turns.", "query": "compass turns beside a folded map"},
                {"text": "The record spins.", "query": "record needle beside old photographs"},
                {"text": "The doorway closes.", "query": "one door closes in a hallway"},
            ],
        }
        report = visual_symbols.analyze(script)
        self.assertTrue(report["passes"])
        self.assertEqual(report["longest_family_run"]["length"], 5)
        self.assertEqual(report["policy"]["max_family_run"], 6)
        self.assertEqual(report["policy"]["min_families"], 4)

    def test_labels_cannot_fake_visual_diversity(self):
        labels = [
            "geometry", "nature", "language", "architecture", "pathway", "perception",
        ]
        script = self._generic_people_script()
        for index, scene in enumerate(script["scenes"]):
            scene["symbol_family"] = labels[index % len(labels)]
            scene["human_role"] = "observer"
        report = visual_symbols.analyze(script)
        self.assertEqual(report["symbol_family_count"], 1)
        self.assertFalse(report["passes"])
        self.assertTrue(all(row["query_family"] == "light_atmosphere"
                            for row in report["scenes"]))

    def test_diverse_symbol_sequence_passes_strict_policy(self):
        queries = [
            "gallery wall filled with different eyes",
            "hand draws arrows in two directions",
            "printed letters move beneath magnifying glass",
            "one door opens in bright hallway",
            "seed germinates in dark soil time lapse",
            "compass turns beside folded map",
            "nested rings expand slowly",
            "rotating globe reflected against moving city",
            "record needle moves beside old photos",
            "person removes mask in mirror",
            "crowd crosses public square",
            "storm clouds clear over landscape",
        ]
        script = {
            "visual_policy": visual_symbols.POLICY_NAME,
            "scenes": [
                {"text": f"Beat {index} changes the idea.", "query": query}
                for index, query in enumerate(queries)
            ],
        }
        report = visual_symbols.validate(script)
        self.assertTrue(report["passes"])
        self.assertGreaterEqual(report["symbol_family_count"], 6)
        self.assertLessEqual(report["longest_family_run"]["length"], 3)


if __name__ == "__main__":
    unittest.main()
