import os
import json
import subprocess
import sys
import tempfile
import unittest
import wave

import numpy as np
from PIL import Image

os.environ.setdefault("PEXELS_API_KEY", "test-key")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import footage
import music
import profiles
import assemble
import prep
from captions import caption_png, title_png


class ProfileMediaTests(unittest.TestCase):
    def test_june_rejects_near_black_frames(self):
        video = {"duration": 8}
        dark = Image.new("RGB", (120, 80), (5, 5, 5))
        warm = Image.new("RGB", (120, 80), (150, 112, 72))
        self.assertGreater(
            footage.mood_score(video, warm, profile=profiles.JUNE_OXLEY),
            footage.mood_score(video, dark, profile=profiles.JUNE_OXLEY) + 80,
        )

    def test_june_music_is_valid_and_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            house = os.path.join(td, "house.wav")
            june = os.path.join(td, "june.wav")
            music.gen(house, 2.0)
            music.gen(june, 2.0, profile=profiles.JUNE_OXLEY)
            arrays = []
            for path in (house, june):
                with wave.open(path, "rb") as w:
                    self.assertEqual(w.getnchannels(), 2)
                    self.assertEqual(w.getframerate(), music.SR)
                    arrays.append(np.frombuffer(w.readframes(w.getnframes()), np.int16))
            self.assertGreater(float(np.abs(arrays[1]).mean()), 10.0)
            self.assertFalse(np.array_equal(arrays[0], arrays[1]))

    def test_june_color_grade_renders_a_vertical_segment(self):
        with tempfile.TemporaryDirectory() as td:
            clip = os.path.join(td, "clip.mp4")
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                "testsrc2=size=640x360:rate=30", "-t", "1.2", "-an",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", clip,
            ], check=True)
            script = {
                "title": "June Test", "slug": "june-test", "profile": "june_oxley",
                "scenes": [{"text": "Now look here.", "keywords": ["look"],
                            "start": 0.0, "duration": 1.0, "clip": clip}],
            }
            with open(os.path.join(td, "script.json"), "w") as f:
                json.dump(script, f)
            caption_png("Now look here.", ["look"], os.path.join(td, "cap_00.png"))
            title_png("June Test", os.path.join(td, "title.png"))
            assemble.render_scene(td, 0)
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0",
                os.path.join(td, "seg_00.mp4"),
            ], check=True, capture_output=True, text=True)
            self.assertEqual(probe.stdout.strip(), "1080,1920")

    def test_prep_routes_june_music_and_sound_design(self):
        with tempfile.TemporaryDirectory() as td:
            script = {
                "title": "Porch Test", "slug": "porch-test", "profile": "june_oxley",
                "scenes": [
                    {"text": "Bills on the table.", "keywords": ["Bills"],
                     "start": 0.0, "duration": 1.0},
                    {"text": "Universe in the mirror.", "keywords": ["Universe"],
                     "start": 1.0, "duration": 1.0},
                ],
            }
            with open(os.path.join(td, "script.json"), "w") as f:
                json.dump(script, f)
            prep.prep(td)
            with open(os.path.join(td, "script.json")) as f:
                saved = json.load(f)
            self.assertEqual(saved["music"], "music_03.wav")
            with wave.open(os.path.join(td, "music_03.wav"), "rb") as w:
                self.assertGreater(w.getnframes(), music.SR * 3)


if __name__ == "__main__":
    unittest.main()
