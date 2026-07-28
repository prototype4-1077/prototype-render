import json
import os
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import learn
import profiles
import taste


class ProfileLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_store, self.old_mem = taste.STORE, learn.MEM
        taste.STORE = os.path.join(self.tmp.name, "taste.npz")
        learn.MEM = os.path.join(self.tmp.name, "memory.json")

    def tearDown(self):
        taste.STORE, learn.MEM = self.old_store, self.old_mem
        self.tmp.cleanup()

    def test_profile_taste_is_separate_from_house_taste(self):
        house = np.zeros((8, 512), np.float32); house[:, 0] = 1
        june = np.zeros((8, 512), np.float32); june[:, 1] = 1
        taste.add("approved", house)
        taste.add("approved", june, profiles.JUNE_OXLEY)

        self.assertTrue(taste.ready())
        self.assertTrue(taste.ready(profiles.JUNE_OXLEY))
        self.assertGreater(taste.score([house[0]])[0], taste.score([june[0]])[0])
        self.assertGreater(taste.score([june[0]], profiles.JUNE_OXLEY)[0],
                           taste.score([house[0]], profiles.JUNE_OXLEY)[0])

    def test_record_routes_weights_and_embeddings_to_june(self):
        build = os.path.join(self.tmp.name, "build")
        os.makedirs(build)
        script = {
            "title": "June Test", "slug": "june-test", "profile": "june_oxley",
            "scenes": [{"text": "Bills again.", "query": "bills kitchen table",
                        "pexels_id": 123}],
        }
        with open(os.path.join(build, "script.json"), "w") as f:
            json.dump(script, f)
        vec = np.zeros(512, np.float32); vec[3] = 1
        np.save(os.path.join(build, "emb_00.npy"), vec)

        learn.record(build)
        with open(learn.MEM) as f:
            memory = json.load(f)
        self.assertNotIn("bills kitchen table", memory["query_weights"])
        self.assertEqual(memory["profile_query_weights"]["june_oxley"]
                         ["bills kitchen table"], 1)
        self.assertEqual(memory["videos"][0]["profile"], "june_oxley")
        self.assertEqual(taste._load(profiles.JUNE_OXLEY)[0].shape, (1, 512))
        self.assertEqual(taste._load()[0].shape, (0, 512))


if __name__ == "__main__":
    unittest.main()
