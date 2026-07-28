import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hook_variants  # noqa: E402


class HookVariantTests(unittest.TestCase):
    def setUp(self):
        self.script = {"slug": "x", "scenes": [
            {"text": "a", "query": "q0", "pexels_id": 1, "clip": "clip_00.mp4"},
            {"text": "b", "query": "q1", "pexels_id": 2},
        ]}

    def test_visual_override_applies_and_clears_selection(self):
        new, affected = hook_variants.apply_overrides(
            self.script, {"label": "B", "scenes": {"0": {"query": "alt hook"}}})
        self.assertEqual(affected, [0])
        self.assertEqual(new["scenes"][0]["query"], "alt hook")
        self.assertNotIn("pexels_id", new["scenes"][0])
        self.assertNotIn("clip", new["scenes"][0])
        self.assertEqual(self.script["scenes"][0]["query"], "q0")  # original untouched
        self.assertEqual(new["scenes"][1], self.script["scenes"][1])

    def test_text_change_rejected(self):
        with self.assertRaises(ValueError):
            hook_variants.apply_overrides(
                self.script, {"scenes": {"0": {"text": "new hook line"}}})

    def test_bad_index_rejected(self):
        with self.assertRaises(ValueError):
            hook_variants.apply_overrides(self.script, {"scenes": {"9": {"query": "x"}}})


if __name__ == "__main__":
    unittest.main()
