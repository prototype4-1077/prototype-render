"""Optional CLIP semantic scorer for footage candidates (quality upgrade).
If open_clip/torch aren't installed, footage.py silently skips semantic scoring.
Env: CLIP_CACHE (default /tmp/clipcache) for the ViT-B-32 openai checkpoint."""
import os

_model = _pre = _tok = None


def available():
    """Enabled when SEMANTIC_CLIP=1 or in CI (GitHub Actions). Off by default in
    time-limited sandboxes: model load ~30s exceeds the 45s bash budget."""
    gate = os.environ.get("SEMANTIC_CLIP")
    if gate == "0":
        return False
    if gate != "1" and not os.environ.get("GITHUB_ACTIONS"):
        return False
    try:
        import open_clip, torch  # noqa
        return True
    except Exception:
        return False


def _load():
    global _model, _pre, _tok
    if _model is None:
        import open_clip, torch
        cache = os.environ.get("CLIP_CACHE", "/tmp/clipcache")
        local = os.path.join(cache, "open_clip_model.safetensors")
        pretrained = local if os.path.exists(local) else "laion2b_s34b_b79k"
        _model, _, _pre = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained=pretrained, cache_dir=cache)
        _model.eval()
        _tok = open_clip.get_tokenizer("ViT-B-32")
    return _model, _pre, _tok


def scores_and_embs(query, images):
    """Returns ([0..100 semantic scores], [512-d image embeddings])."""
    import torch
    model, pre, tok = _load()
    with torch.no_grad():
        tf = model.encode_text(tok([f"a cinematic shot of {query}"]))
        tf /= tf.norm(dim=-1, keepdim=True)
        batch = torch.stack([pre(im.convert("RGB")) for im in images])
        imf = model.encode_image(batch)
        imf /= imf.norm(dim=-1, keepdim=True)
        sims = (imf @ tf.T).squeeze(1).tolist()
    embs = [e.numpy() for e in imf]
    # typical CLIP cosine range ~0.10 (unrelated) .. 0.35 (spot-on) -> 0..100
    return [max(0.0, min(100.0, (s - 0.10) * 400)) for s in sims], embs


def scores(query, images):
    return scores_and_embs(query, images)[0]
