import os
import sys
import tempfile
import unittest

from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import assemble
import captions
import video_format


class VideoFormatTests(unittest.TestCase):
    def test_renderers_expose_portrait_and_native_youtube_canvases(self):
        self.assertTrue(video_format.is_portrait_9_16())
        self.assertTrue(video_format.is_landscape_16_9())
        self.assertEqual((video_format.WIDTH, video_format.HEIGHT), (1080, 1920))
        self.assertEqual((assemble.WIDTH, assemble.HEIGHT), (1080, 1920))
        self.assertEqual((captions.W, captions.H), (1080, 1920))
        self.assertEqual(
            (video_format.YOUTUBE_WIDTH, video_format.YOUTUBE_HEIGHT), (1920, 1080))
        self.assertEqual(
            (assemble.YOUTUBE_WIDTH, assemble.YOUTUBE_HEIGHT), (1920, 1080))
        self.assertEqual((captions.YT_W, captions.YT_H), (1920, 1080))

    def _assert_title_fits(self, title):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "title.png")
            captions.title_png(title, path)
            with Image.open(path) as image:
                self.assertEqual(image.size, (1080, 1920))
                bbox = image.getchannel("A").getbbox()
            self.assertIsNotNone(bbox)
            left, top, right, bottom = bbox
            self.assertGreaterEqual(left, 60)
            self.assertLessEqual(right, 1020)
            self.assertGreaterEqual(top, 540)
            self.assertLessEqual(bottom, 1380)

    def _assert_youtube_title_fits(self, title):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "youtube_title.png")
            captions.youtube_title_png(title, path)
            with Image.open(path) as image:
                self.assertEqual(image.size, (1920, 1080))
                bbox = image.getchannel("A").getbbox()
            self.assertIsNotNone(bbox)
            left, top, right, bottom = bbox
            self.assertGreaterEqual(left, 100)
            self.assertLessEqual(right, 1820)
            self.assertGreaterEqual(top, 80)
            self.assertLessEqual(bottom, 770)

    def test_long_title_wraps_and_shrinks_inside_safe_area(self):
        title = (
            "The Impossibly Complicated Conversation Between Every Version "
            "of Yourself That Ever Believed It Was Too Late"
        )
        self._assert_title_fits(title)
        self._assert_youtube_title_fits(title)

    def test_unbroken_title_token_cannot_overrun_canvas(self):
        self._assert_title_fits("CONSCIOUSNESS" * 12)
        self._assert_youtube_title_fits("CONSCIOUSNESS" * 12)

    def test_youtube_caption_overlay_uses_landscape_canvas(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "youtube_cap.png")
            captions.youtube_caption_png(
                "Awakening is when the universe stops whispering and sends an invoice.",
                ["universe", "invoice"], path)
            with Image.open(path) as image:
                self.assertEqual(image.size, (1920, 1080))
                bbox = image.getchannel("A").getbbox()
            self.assertIsNotNone(bbox)
            self.assertGreaterEqual(bbox[1], 720)
            self.assertLessEqual(bbox[3], 1056)

    def test_performance_directions_are_hidden_from_captions(self):
        self.assertEqual(
            captions.visible_caption_text(
                "[softly] [with quiet intensity] The whole can hear itself."
            ),
            "The whole can hear itself.",
        )
        self.assertEqual(
            captions.visible_caption_text("A literal [bracketed] word remains."),
            "A literal [bracketed] word remains.",
        )


if __name__ == "__main__":
    unittest.main()
