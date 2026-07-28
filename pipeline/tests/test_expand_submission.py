import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import expand_submission


class ExpandSubmissionTests(unittest.TestCase):
    def test_voice_tag_moves_to_audio_and_family_follows_visual(self):
        with tempfile.TemporaryDirectory() as td:
            build = Path(td)
            (build / "submission.json").write_text(json.dumps({
                "title": "A Test",
                "scenes": [{
                    "text": "[with quiet intensity] Two eyes create one depth.",
                    "visual": "close-up of two eyes reflecting the same street",
                }],
            }), encoding="utf-8")

            expand_submission.expand("a-test", build)
            script = json.loads((build / "script.json").read_text(encoding="utf-8"))
            scene = script["scenes"][0]

            self.assertEqual(scene["text"], "Two eyes create one depth.")
            self.assertEqual(scene["audio_tags"], ["with quiet intensity"])
            self.assertNotIn("symbol_family", scene)
            self.assertEqual(script["visual_policy"]["max_family_run"], 6)
            self.assertEqual(script["visual_policy"]["min_families"], 4)
            self.assertEqual(script["max_still_source_ratio"], 0.50)
            self.assertNotIn("[with quiet intensity]", (build / "source-script.txt").read_text())


if __name__ == "__main__":
    unittest.main()
