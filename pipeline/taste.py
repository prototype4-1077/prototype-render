"""Learned taste vector: scores candidates by similarity to James's approved aesthetic.
Data lives in pipeline/taste.npz (approved [n,512], rejected [m,512] CLIP embeddings).
Character profiles use their own named arrays so a specialized look cannot distort the
house style (and the house style cannot pull a new character back toward itself).
Fed automatically: every render saves the chosen clip's embedding (emb_XX.npy);
learn.py record -> approved, learn.py swap -> rejected. Needs >=8 approved to activate."""
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "taste.npz")


def _names(profile=None):
    suffix = f"__{profile}" if profile else ""
    return f"approved{suffix}", f"rejected{suffix}"


def _all():
    if not os.path.exists(STORE):
        return {}
    with np.load(STORE) as d:
        return {name: d[name] for name in d.files}


def _load(profile=None):
    d = _all()
    ak, rk = _names(profile)
    return (d.get(ak, np.zeros((0, 512), np.float32)),
            d.get(rk, np.zeros((0, 512), np.float32)))


def add(kind, vecs, profile=None):
    d = _all()
    ak, rk = _names(profile)
    a, r = _load(profile)
    v = np.asarray(vecs, np.float32).reshape(-1, a.shape[1] if a.size else 512)
    v = v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-8)
    if kind == "approved": a = np.vstack([a, v])
    else: r = np.vstack([r, v])
    d[ak], d[rk] = a, r
    np.savez_compressed(STORE, **d)
    return len(a), len(r)


def ready(profile=None):
    a, _ = _load(profile)
    return len(a) >= 8


HEAD_MIN_APPROVED = 30
HEAD_MIN_REJECTED = 8


def _train_head(a, r, iters=400, lr=0.5, l2=1e-3):
    """Class-balanced logistic head on unit CLIP embeddings (pure numpy)."""
    X = np.vstack([a, r]).astype(np.float64)
    y = np.concatenate([np.ones(len(a)), np.zeros(len(r))])
    sw = np.where(y == 1, len(y) / (2.0 * len(a)), len(y) / (2.0 * len(r)))
    w = np.zeros(X.shape[1])
    b = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(X @ w + b)))
        g = (p - y) * sw
        w -= lr * (X.T @ g / len(y) + l2 * w)
        b -= lr * float(g.mean())
    return w, b


def score(embs, profile=None):
    """List of embeddings -> 0-100 taste scores (50 = neutral).

    With enough labeled data (>=30 approved and >=8 rejected) a class-balanced
    logistic head replaces the centroid heuristic; below that threshold the
    original centroid behavior is preserved exactly."""
    if not len(embs):
        return []
    a, r = _load(profile)
    if len(a) < 8:
        return [50.0] * len(embs)
    if len(a) >= HEAD_MIN_APPROVED and len(r) >= HEAD_MIN_REJECTED:
        E = np.asarray([np.asarray(e, np.float32).ravel() for e in embs], np.float64)
        E = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-8)
        w, b = _train_head(a, r)
        p = 1.0 / (1.0 + np.exp(-(E @ w + b)))
        return [float(min(100.0, max(0.0, v * 100.0))) for v in p]
    ma = a.mean(0); ma /= np.linalg.norm(ma) + 1e-8
    mr = None
    if len(r) >= 3:
        mr = r.mean(0); mr /= np.linalg.norm(mr) + 1e-8
    out = []
    for e in embs:
        e = np.asarray(e, np.float32).ravel()
        e = e / (np.linalg.norm(e) + 1e-8)
        s = float(e @ ma) - (float(e @ mr) if mr is not None else 0.0)
        out.append(max(0.0, min(100.0, 50 + s * 250)))
    return out
