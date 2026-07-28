import os
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import captions


class TikTokCoverTitleTests(unittest.TestCase):
    def _render_bbox(self, title):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "youtube_title.png")
            captions.youtube_title_png(title, path)
            with Image.open(path) as image:
                self.assertEqual(image.size, (1920, 1080))
                return image.getchannel("A").getbbox()

    def test_centered_cover_crop_geometry_is_three_by_four(self):
        self.assertEqual(captions.YT_TIKTOK_COVER_CROP_W, 810)
        self.assertEqual(captions.YT_TIKTOK_COVER_CROP_LEFT, 555)
        self.assertEqual(captions.YT_TIKTOK_COVER_CROP_RIGHT, 1365)
        self.assertLess(captions.YT_TITLE_MAX_LINE_W,
                        captions.YT_TIKTOK_COVER_CROP_W)

    def test_message_from_your_future_prefers_cover_safe_three_line_grouping(self):
        title_words = [(word, False) for word in "MESSAGE FROM YOUR FUTURE".split()]
        grouped = captions._group_title_words(title_words)
        grouped_text = [" ".join(word for word, _ in line) for line in grouped]
        # 12-char rule (James): lines pack up to 12 visible chars
        self.assertEqual(grouped_text, ["MESSAGE FROM", "YOUR FUTURE"])
        for line in grouped_text:
            visible = sum(len(w) for w in line.split())
            self.assertLessEqual(visible, 12)

        canvas = Image.new("RGBA", (captions.YT_W, captions.YT_H))
        draw = ImageDraw.Draw(canvas)
        font, lines, _line_h = captions._fit_title(
            "MESSAGE FROM YOUR FUTURE",
            draw,
            170,
            captions.YT_TITLE_MAX_LINE_W,
            captions.YT_TITLE_MAX_BLOCK_H,
            cover_safe_layout=True,
        )
        self.assertLessEqual(len(lines), 3)
        self.assertEqual(
            [word for line in lines for word, _ in line],
            [word for word, _ in title_words],
        )
        self.assertGreaterEqual(font.size, captions.TITLE_MIN_FONT_SIZE)
        for line in lines:
            text = " ".join(word for word, _ in line)
            self.assertLessEqual(
                draw.textlength(text, font=font), captions.YT_TITLE_MAX_LINE_W)

        bbox = self._render_bbox("Message From Your Future")
        self.assertIsNotNone(bbox)
        self.assertGreaterEqual(bbox[0], captions.YT_TIKTOK_COVER_CROP_LEFT)
        self.assertLessEqual(bbox[2], captions.YT_TIKTOK_COVER_CROP_RIGHT)

    def test_long_and_unbroken_titles_cannot_escape_cover_crop(self):
        titles = [
            (
                "The Impossibly Complicated Conversation Between Every Version "
                "of Yourself That Ever Believed It Was Too Late"
            ),
            "CONSCIOUSNESS" * 12,
        ]
        for title in titles:
            with self.subTest(title=title[:40]):
                bbox = self._render_bbox(title)
                self.assertIsNotNone(bbox)
                self.assertGreaterEqual(
                    bbox[0], captions.YT_TIKTOK_COVER_CROP_LEFT)
                self.assertLessEqual(
                    bbox[2], captions.YT_TIKTOK_COVER_CROP_RIGHT)
                self.assertGreaterEqual(bbox[1], 0)
                self.assertLessEqual(bbox[3], captions.YT_H)


if __name__ == "__main__":
    unittest.main()
