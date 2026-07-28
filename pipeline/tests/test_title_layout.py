import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import captions


def group(text):
    words = [(word, False) for word in text.split()]
    # These tests exercise the ordinary title word-count rule. The optional
    # character hint is reserved for TikTok cover-safe layout and is covered
    # separately in test_tiktok_cover_title.py.
    return [[word for word, _ in line]
            for line in captions._group_title_words(words, use_character_hint=False)]


class TitleLayoutTests(unittest.TestCase):
    def test_content_words_are_limited_to_two_per_line(self):
        self.assertEqual(
            group("ALPHA BETA GAMMA DELTA EPSILON"),
            [["ALPHA", "BETA"], ["GAMMA", "DELTA"], ["EPSILON"]],
        )

    def test_short_pronoun_allows_three_words(self):
        self.assertEqual(group("I FOUND REALITY"), [["I", "FOUND", "REALITY"]])

    def test_short_preposition_allows_three_words(self):
        self.assertEqual(group("LIGHT ON WATER"), [["LIGHT", "ON", "WATER"]])

    def test_punctuation_does_not_hide_connector(self):
        self.assertEqual(group("DMT: A STRANGE JESTER"), [["DMT:", "A", "STRANGE"], ["JESTER"]])

    def test_no_title_line_ever_exceeds_three_words(self):
        lines = group("I WALKED INTO A PALACE ON THE EDGE OF TIME")
        self.assertTrue(all(len(line) <= 3 for line in lines))


if __name__ == "__main__":
    unittest.main()
