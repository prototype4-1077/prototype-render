import json
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import learn  # noqa: E402
import taste  # noqa: E402


class AudienceLearningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._mem, self._store = learn.MEM, taste.STORE
        learn.MEM = os.path.join(self.tmp, "memory.json")
        taste.STORE = os.path.join(self.tmp, "taste.npz")
        self.bd = os.path.join(self.tmp, "build")
        os.makedirs(self.bd)
        scenes = []
        t = 0.0
        for i in range(10):
            scenes.append({"text": f"beat {i}", "query": f"query {i}",
                           "start": round(t, 2), "duration": 3.0,
                           "pexels_id": 1000 + i})
            t += 3.0
        with open(os.path.join(self.bd, "script.json"), "w") as f:
            json.dump({"slug": "retention-test", "scenes": scenes}, f)
        rng = np.random.default_rng(1)
        for i in range(10):
            np.save(os.path.join(self.bd, f"emb_{i:02d}.npy"),
                    rng.random(512).astype(np.float32))
        elapsed = [i / 99 for i in range(100)]
        watch = []
        for e in elapsed:
            tsec = e * 30.0
            w = 1.0 - 0.001 * tsec
            if 6.0 <= tsec < 9.0:  # scene 2 bleeds hard
                w -= (tsec - 6.0) * 0.15
            elif tsec >= 9.0:
                w -= 0.45
            watch.append(round(max(w, 0.0), 4))
        self.rf = os.path.join(self.bd, "retention.json")
        with open(self.rf, "w") as f:
            json.dump({"video_id": "vid123", "elapsed": elapsed,
                       "watch_ratio": watch}, f)

    def tearDown(self):
        learn.MEM, taste.STORE = self._mem, self._store

    def test_worst_penalized_best_rewarded_idempotent(self):
        learn.audience(self.bd, self.rf)
        m = learn.load()
        self.assertLess(m["query_weights"].get("query 2", 0), 0)
        self.assertTrue(any(w > 0 for w in m["query_weights"].values()))
        self.assertEqual(len(m["audience_feedback"]), 1)
        before = json.dumps(m, sort_keys=True)
        learn.audience(self.bd, self.rf)  # second apply must be a no-op
        self.assertEqual(before, json.dumps(learn.load(), sort_keys=True))

    def test_decay_applies_on_record(self):
        m = learn.load()
        m.setdefault("query_weights", {})["old query"] = 5.0
        learn.save(m)
        learn.record(self.bd)
        self.assertLess(learn.load()["query_weights"]["old query"], 5.0)


class TasteHeadTest(unittest.TestCase):
    def test_head_separates_clusters(self):
        rng = np.random.default_rng(0)
        a = rng.normal(0.1, 0.02, (40, 512))
        r = rng.normal(-0.1, 0.02, (12, 512))
        a /= np.linalg.norm(a, axis=1, keepdims=True)
        r /= np.linalg.norm(r, axis=1, keepdims=True)
        w, b = taste._train_head(a, r)
        sa = 1.0 / (1.0 + np.exp(-(a @ w + b)))
        sr = 1.0 / (1.0 + np.exp(-(r @ w + b)))
        self.assertGreater(float(sa.mean()), 0.8)
        self.assertLess(float(sr.mean()), 0.2)

    def test_score_empty_and_neutral(self):
        self.assertEqual(taste.score([]), [])


if __name__ == "__main__":
    unittest.main()
