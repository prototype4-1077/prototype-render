"""Cut-coherence report: flags visually jarring adjacent-scene transitions.

Uses the CLIP embeddings every render already saves (emb_XX.npy). Low cosine
similarity between consecutive selected clips marks a cut the eye will feel.
Report-only: writes coherence_report.json and never blocks a render; the
threshold can move once swap()/audience() feedback correlates with it.

Usage: python3 coherence.py <build_dir>"""
import json
import os
import sys

import numpy as np

JARRING_BELOW = 0.12


def run(bd):
    embs = {}
    for name in sorted(os.listdir(bd)):
        if name.startswith("emb_") and name.endswith(".npy"):
            try:
                embs[int(name[4:6])] = np.load(os.path.join(bd, name)).ravel()
            except Exception:
                pass
    idx = sorted(embs)
    pairs = []
    for a, b in zip(idx, idx[1:]):
        va, vb = embs[a], embs[b]
        cos = float(va @ vb / ((np.linalg.norm(va) * np.linalg.norm(vb)) + 1e-8))
        pairs.append({"from_scene": a, "to_scene": b,
                      "similarity": round(cos, 4),
                      "jarring": cos < JARRING_BELOW})
    report = {
        "threshold": JARRING_BELOW,
        "pairs": pairs,
        "mean_similarity": (round(float(np.mean([p["similarity"] for p in pairs])), 4)
                            if pairs else None),
        "jarring_cuts": [p["from_scene"] for p in pairs if p["jarring"]],
    }
    with open(os.path.join(bd, "coherence_report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print(f"coherence: {len(pairs)} cuts, {len(report['jarring_cuts'])} flagged jarring")


if __name__ == "__main__":
    run(sys.argv[1])
