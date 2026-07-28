import os
import sys
import unittest

PIPELINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PIPELINE)

import render_policy


class RenderPolicyTests(unittest.TestCase):
    def test_default_is_one_youtube_video_with_current_music_choice(self):
        script = {}
        self.assertEqual(("youtube",), render_policy.render_outputs(script))
        self.assertEqual((3,), render_policy.music_choices(script))
        self.assertEqual(("final_youtube.mp4",), render_policy.required_video_names(script))
        self.assertFalse(render_policy.needs_portrait_segments(script))

    def test_explicit_outputs_and_alternatives_are_opt_in(self):
        script = {
            "render_outputs": ["youtube", "portrait", "short"],
            "music_choice": 3,
            "music_choices": [1, 2, 3],
        }
        self.assertEqual(
            ("youtube", "portrait", "short"),
            render_policy.render_outputs(script),
        )
        self.assertEqual((3, 1, 2), render_policy.music_choices(script))
        self.assertTrue(render_policy.needs_portrait_segments(script))

    def test_primary_output_has_no_duplicate_variant_file(self):
        selected = {"variant": 3}
        alternate = {"variant": 1}
        self.assertEqual(
            "final_youtube.mp4",
            render_policy.video_name("youtube", 0, selected),
        )
        self.assertEqual(
            "final_youtube_music_01.mp4",
            render_policy.video_name("youtube", 1, alternate),
        )

    def test_curation_keeps_legacy_portrait_workflow(self):
        script = {"curate_scenes": [2]}
        self.assertEqual(("portrait",), render_policy.render_outputs(script))


if __name__ == "__main__":
    unittest.main()
