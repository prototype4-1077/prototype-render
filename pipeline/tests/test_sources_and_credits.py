import json
import os
import sys
import tempfile
import unittest
from unittest import mock


PIPELINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PIPELINE not in sys.path:
    sys.path.insert(0, PIPELINE)

import footage
import sources


class KeylessStockTests(unittest.TestCase):
    def test_coverr_candidate_exposes_exact_video_thumbnail(self):
        page = (
            'https://cdn.coverr.co/videos/coverr-window-light-1234/720p.mp4 '
            'https://cdn.coverr.co/videos/coverr-premium-ignore-9999/720p.mp4'
        )
        with mock.patch.object(sources, "_text", return_value=page):
            candidates = sources.coverr("window light")
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["id"], "coverr:coverr-window-light-1234")
        self.assertEqual(
            candidate["image"],
            "https://cdn.coverr.co/videos/coverr-window-light-1234/thumbnail?width=640",
        )

    def test_pinned_coverr_candidate_retains_thumbnail(self):
        candidate = sources.fetch_by_id("coverr:coverr-window-light-1234")
        self.assertEqual(
            candidate["image"],
            "https://cdn.coverr.co/videos/coverr-window-light-1234/thumbnail?width=640",
        )


class CreditsTests(unittest.TestCase):
    def test_credits_use_current_video_title(self):
        with tempfile.TemporaryDirectory() as build_dir:
            script = {
                "title": "The Mirror Catches Up",
                "scenes": [{
                    "motion_source": "coverr",
                    "stock_id": "coverr:clip-1",
                    "source_url": "https://coverr.co/videos/clip-1",
                    "source_license": "Coverr Free Stock Video License",
                }],
            }
            with open(os.path.join(build_dir, "script.json"), "w") as handle:
                json.dump(script, handle)
            footage.write_credits(build_dir)
            with open(os.path.join(build_dir, "CREDITS.txt")) as handle:
                credits = handle.read()
        self.assertTrue(
            credits.startswith("THE MIRROR CATCHES UP — STOCK FOOTAGE CREDITS")
        )
        self.assertIn("coverr:clip-1", credits)


if __name__ == "__main__":
    unittest.main()
