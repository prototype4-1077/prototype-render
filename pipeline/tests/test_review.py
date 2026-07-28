import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import learn
import review
import taste


class SceneReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.build = os.path.join(self.tmp.name, "build")
        os.makedirs(self.build)
        self.old_mem, self.old_store = learn.MEM, taste.STORE
        learn.MEM = os.path.join(self.tmp.name, "memory.json")
        taste.STORE = os.path.join(self.tmp.name, "taste.npz")
        self.script = {
            "title": "Review Test",
            "slug": "review-test",
            "scenes": [
                {
                    "text": "The first line.",
                    "query": "moving clock in bright room",
                    "semantic_anchor": "time is visibly moving",
                    "visual_function": "mechanism",
                    "symbol_family": "time_memory",
                    "pexels_id": 101,
                    "start": 0,
                    "duration": 3,
                },
                {
                    "text": "The second line.",
                    "query": "person opens a blue door",
                    "semantic_anchor": "a person makes a choice",
                    "visual_function": "choice",
                    "symbol_family": "pathway",
                    "pexels_id": 202,
                    "start": 3,
                    "duration": 4,
                },
            ],
        }
        self._write_script()

    def tearDown(self):
        learn.MEM, taste.STORE = self.old_mem, self.old_store
        self.tmp.cleanup()

    def _write_script(self):
        with open(os.path.join(self.build, "script.json"), "w") as handle:
            json.dump(self.script, handle)

    def test_generate_creates_standalone_review_and_tracks_script_version(self):
        html_path, json_path = review.generate(self.build)
        self.assertTrue(os.path.exists(html_path))
        self.assertTrue(os.path.exists(json_path))
        metadata = json.load(open(json_path))
        self.assertEqual(len(metadata["scenes"]), 2)
        self.assertIn("make the cause-and-effect mechanism visible",
                      metadata["scenes"][0]["why_chosen"])
        self.assertTrue(review.is_current(self.build))
        html = open(html_path, encoding="utf-8").read()
        self.assertIn("Export feedback", html)
        self.assertIn("Approve remaining", html)
        self.assertIn("Comments for scene", html)

        self.script["scenes"][0]["query"] = "a different moving clock"
        self._write_script()
        self.assertFalse(review.is_current(self.build))

    def test_survey_applies_approved_and_rejected_scene_learning_once(self):
        open(os.path.join(self.build, "final.mp4"), "wb").close()
        open(os.path.join(self.build, "scene-review.html"), "w").close()
        feedback = {
            "slug": "review-test",
            "reviewed_at": "2026-07-16T00:00:00Z",
            "overall": {"decision": "revise", "comments": "One scene needs work."},
            "scenes": [
                {"scene_index": 0, "decision": "approved", "comments": "Keep it."},
                {"scene_index": 1, "decision": "revise",
                 "comments": "Use a front-facing person entering the doorway."},
            ],
        }
        feedback_path = os.path.join(self.tmp.name, "feedback.json")
        with open(feedback_path, "w") as handle:
            json.dump(feedback, handle)

        learn.survey(self.build, feedback_path)
        memory = json.load(open(learn.MEM))
        script = json.load(open(os.path.join(self.build, "script.json")))
        self.assertIn(101, memory["used_ids"])
        self.assertIn(202, memory["banned_ids"])
        self.assertEqual(memory["query_weights"]["moving clock in bright room"], 1)
        self.assertEqual(memory["query_weights"]["person opens a blue door"], -2)
        self.assertNotIn("pexels_id", script["scenes"][1])
        self.assertFalse(os.path.exists(os.path.join(self.build, "final.mp4")))
        self.assertEqual(len(memory["scene_feedback"]), 2)

        learn.survey(self.build, feedback_path)
        memory_again = json.load(open(learn.MEM))
        self.assertEqual(memory_again["query_weights"], memory["query_weights"])
        self.assertEqual(len(memory_again["scene_feedback"]), 2)


if __name__ == "__main__":
    unittest.main()
