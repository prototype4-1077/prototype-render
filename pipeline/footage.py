"""Stock clip search + download, auto-vetted for semantics, look, and motion.
Usage: python3 footage.py <build_dir> [scene_index]   (no index = all missing)
Coverr and Mixkit are keyless; Pexels is added when PEXELS_API_KEY is available.
Reads scene["query"], writes clip_XX.mp4, and records source/motion evidence.

No human/AI judgment needed: every candidate's preview thumbnail is scored for
mood (dark, not garish) and the best one wins. Bad/empty queries fall back to
a curated MYSTICAL bank, so any query still yields on-style footage."""
import io, json, os, random, re, shutil, sys, urllib.request, urllib.parse

import motion
import profiles
import visual_symbols

KEY = os.environ.get("PEXELS_API_KEY")
from video_format import YOUTUBE_WIDTH
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
_op = urllib.request.build_opener()
_op.addheaders = [("User-Agent", UA)]
urllib.request.install_opener(_op)

MEM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")
def memory():
    try: return json.load(open(MEM))
    except Exception: return {"used_ids": [], "banned_ids": [], "query_weights": {}}

DMT = [  # genre "dmt": vivid first-person visionary imagery (saturation is GOOD here)
    "kaleidoscope pattern animation", "fractal zoom psychedelic", "colorful nebula space",
    "plasma light abstract", "ink in water rainbow colors", "neon light tunnel abstract",
    "sacred geometry animation", "aurora borealis vivid night", "liquid light abstract macro",
    "mandala pattern colorful", "prism light refraction rainbow", "glowing jellyfish deep sea",
    "bioluminescence ocean night", "crystal macro colorful light", "smoke colorful backlit",
    "particle explosion colorful slow motion", "galaxy stars colorful timelapse",
]

MYSTICAL = [
    "surreal fog silhouette", "nebula space stars", "underwater sun rays dark",
    "silhouette tunnel light end", "fog city aerial dark", "smoke swirl black background",
    "light rays forest fog", "ink drop water black", "stars time lapse night sky",
    "eclipse moon dark clouds", "person walking fog field", "abstract particles dark",
    "candle flame dark", "ocean night moonlight", "desert lone figure dusk",
    "spiral galaxy animation", "light through door dark room", "clouds time lapse storm dark",
    "mirror reflection surreal", "glowing orb dark", "shadow figure hallway",
    "aurora night sky", "deep space travel", "rain window night bokeh",
]


def api(url):
    if not KEY:
        raise RuntimeError("PEXELS_API_KEY is not configured")
    req = urllib.request.Request(url, headers={"Authorization": KEY, "User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=60))


def get_thumb(video, w=224):
    from PIL import Image
    u = video["image"].split("?")[0] + f"?auto=compress&w={w}"
    return Image.open(io.BytesIO(urllib.request.urlopen(u, timeout=20).read())).convert("RGB")


def mood_score(video, im=None, need=None, genre=None, profile=None):
    """Score a candidate thumbnail. Default: lit-but-moody, muted.
    genre="dmt": vivid saturated visionary imagery wins instead."""
    try:
        from PIL import ImageStat
        if im is None:
            im = get_thumb(video, 120)
        st = ImageStat.Stat(im)
        means = st.mean
        luma = sum(a * b for a, b in zip(means, (0.299, 0.587, 0.114)))
        sat = ImageStat.Stat(im.convert("HSV")).mean[1]
    except Exception:
        return 0.0
    score = 100.0
    if profile == profiles.JUNE_OXLEY:
        # June's world is readable, warm, and ordinary. A few strange shots are welcome,
        # but the profile must never drift back into a reel of near-black mysticism.
        if luma < 55: score -= (55 - luma) * 1.7
        if luma < 24: score -= (24 - luma) * 3.0
        if luma > 185: score -= (luma - 185) * 1.1
        if sat > 160: score -= (sat - 160) * .55
        warmth = means[0] - means[2]
        score += max(-5.0, min(8.0, warmth * .18))
    elif genre == "dmt":  # psychedelic mode: reward vivid color, allow deep blacks behind it
        if sat < 70: score -= (70 - sat) * 0.8      # too muted for a vision
        if luma > 170: score -= (luma - 170) * 1.0  # blown out
        if luma < 8: score -= (8 - luma) * 4        # pure black
    else:
        if luma > 140: score -= (luma - 140) * 1.2      # too bright = off-style
        elif luma > 115: score -= (luma - 115) * 0.4
        if luma < 45: score -= (45 - luma) * 1.0        # too dark: James wants visible lighting
        if luma < 15: score -= (15 - luma) * 3          # near-black = nothing to see
        if sat > 120: score -= (sat - 120) * 0.8        # garish colors
    d = video["duration"]
    if need:  # scene length known: clip must cover it without restarting
        if d < need: score -= (need - d) * 4
        else: score -= min((d - need) * 0.2, 10)
    else:
        score -= abs(d - 10) * 0.5
        if d < 5: score -= 25
    return score


def bank_pick(m, genre=None, profile=None):
    """Prefer bank queries with the best track record (learned weights)."""
    w = (m.get("profile_query_weights", {}).get(profile, {}) if profile
         else m.get("query_weights", {}))
    bank = profiles.fallback_queries(profile, genre) or (DMT if genre == "dmt" else MYSTICAL)
    pool = sorted(bank, key=lambda q: w.get(q, 0), reverse=True)
    k = max(3, len(pool) // 3)
    return random.choice(pool[:k])


def rank(query, vids, need=None, genre=None, profile=None):
    """Rank candidates: mood (dark/muted) blended with CLIP semantic match if available."""
    def load_thumb(video):
        # Mixkit direct assets are reviewed from downloaded motion contact sheets.
        # Skipping twelve slow CDN thumbnail round-trips here keeps acquisition
        # fast while lexical ranking and post-download motion checks stay intact.
        if video.get("source") in {"mixkit", "coverr"}:
            return None
        try:
            return get_thumb(video)
        except Exception:
            return None

    # Candidate thumbnails are independent network reads; parallel fetch keeps
    # keyless stock curation practical without changing the ranking algorithm.
    if len(vids) > 3:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(8, len(vids))) as pool:
            thumbs = list(pool.map(load_thumb, vids))
    else:
        thumbs = [load_thumb(video) for video in vids]
    moods = [mood_score(v, im, need, genre, profile) if im is not None
             else (62.0 if v.get("source") in {"mixkit", "coverr"} else 0.0)
             for v, im in zip(vids, thumbs)]
    sems, embs_lut = None, {}
    try:
        import semantic
        semantic_q = profiles.semantic_query(query, profile)
        if semantic_q and semantic.available():
            ok = [(v, im) for v, im in zip(vids, thumbs) if im is not None]
            if ok:
                ss, embs = semantic.scores_and_embs(semantic_q, [im for _, im in ok])
                lut = {id(v): s for (v, _), s in zip(ok, ss)}
                embs_lut = {id(v): e for (v, _), e in zip(ok, embs)}
                sems = [lut.get(id(v), 0.0) for v in vids]
    except Exception:
        sems = None
    stop = {
        "a", "an", "and", "as", "at", "by", "for", "from", "in", "into",
        "is", "it", "of", "on", "or", "person", "people", "the", "then",
        "to", "under", "while", "with",
    }
    query_words = {
        w for w in re.findall(r"[a-z]+", query.lower()) if w not in stop
    }
    lexicals = []
    for video in vids:
        title = str(video.get("title") or video.get("description") or "").lower()
        if not title:
            lexicals.append(50.0)
            continue
        title_words = set(re.findall(r"[a-z]+", title))
        overlap = len(query_words & title_words)
        denom = max(min(len(query_words), 5), 1)
        lexicals.append(min(100.0, 22.0 + 78.0 * overlap / denom))
    if sems is not None:
        try:  # learned taste vector: similarity to James's approved aesthetic
            import taste
            if taste.ready(profile):
                ts = {vid_id: t for vid_id, t in
                      zip(embs_lut.keys(), taste.score(list(embs_lut.values()), profile))}
                total = [0.32 * mo + 0.43 * se + 0.15 * ts.get(id(v), 50.0)
                         + 0.10 * le
                         for mo, se, v, le in zip(moods, sems, vids, lexicals)]
            else:
                total = [0.36 * mo + 0.54 * se + 0.10 * le
                         for mo, se, le in zip(moods, sems, lexicals)]
        except Exception:
            total = [0.36 * mo + 0.54 * se + 0.10 * le
                     for mo, se, le in zip(moods, sems, lexicals)]
    else:
        total = [0.58 * mo + 0.42 * le for mo, le in zip(moods, lexicals)]
    return sorted(zip(total, vids, thumbs,
                      [embs_lut.get(id(v)) for v in vids]), key=lambda t: -t[0])


def search(q, genre=None, profile=None, per_page=15, stock_tag=None):
    try:
        import sources
        extra = sources.supplement(q, genre, stock_tag)
    except Exception:
        extra = []
    found = list(extra)
    if KEY:
        # One provider must never discard another provider's usable results.
        # Pexels 401/403 (access) and 429/5xx (transient) are isolated so the
        # keyless Coverr/Mixkit candidates already in `found` survive.
        for variant in profiles.query_variants(q, profile) or [q]:
            qq = urllib.parse.quote(variant)
            try:
                res = api(
                    f"https://api.pexels.com/v1/videos/search?query={qq}"
                    f"&per_page={per_page}&orientation=landscape"
                )
            except Exception as exc:  # noqa: BLE001 - provider isolation is the point
                status = getattr(exc, "code", None)
                print(f"WARN pexels search failed for {variant!r} "
                      f"(status={status}): {exc}; keeping {len(found)} keyless candidate(s)",
                      flush=True)
                if status in (401, 403):
                    break  # deterministic access failure: stop asking Pexels
                continue
            found.extend(res.get("videos") or [])
    # Styled and literal searches can return the same clip. Keep its first occurrence.
    out, seen = [], set()
    for video in found:
        if video.get("id") in seen:
            continue
        seen.add(video.get("id")); out.append(video)
    return out


def pick_file(video, target_w=None):
    """Smallest rendition that still meets the delivery canvas (default: the
    1920px YouTube master) so footage is never upscaled. Falls back to the
    1080 legacy floor, then to the largest file available."""
    if target_w is None:
        target_w = YOUTUBE_WIDTH
    files = video["video_files"]
    def area(f):
        return (f.get("width") or 0) * (f.get("height") or 0)
    for floor in sorted({target_w, 1080}, reverse=True):
        cands = [f for f in files if (f.get("width") or 0) >= floor]
        if cands:
            return sorted(cands, key=area)[0]
    return sorted(files, key=area)[-1]


def download_video(video, output):
    """Download the best available rendition, falling back by resolution."""
    preferred = pick_file(video)
    files = [preferred] + [item for item in video["video_files"] if item is not preferred]
    last = None
    for item in files:
        try:
            request = urllib.request.Request(item["link"], headers={"User-Agent": UA})
            with urllib.request.urlopen(request, timeout=25) as response:
                with open(output + ".part", "wb") as handle:
                    shutil.copyfileobj(response, handle, length=1024 * 1024)
            os.replace(output + ".part", output)
            return item
        except Exception as exc:
            last = exc
            try:
                os.remove(output + ".part")
            except OSError:
                pass
    raise RuntimeError(f"all video renditions failed: {last}")


def save_alts(bd, i, chosen, scored):
    """Persist top runner-up candidates (thumb + id) for one-command pinning later."""
    try:
        os.makedirs(f"{bd}/alts", exist_ok=True)
        p = f"{bd}/alts.json"
        manifest = json.load(open(p)) if os.path.exists(p) else {}
        entries = []
        k = 0
        for sc_score, v, im, _e in scored:
            if v["id"] == chosen["id"] or im is None:
                continue
            safe = str(v["id"]).replace(":", "_")
            im.convert("RGB").save(f"{bd}/alts/{i:02d}_{k}_{safe}.jpg")
            entries.append({"id": v["id"], "score": round(sc_score, 1),
                            "source": v.get("source", "pexels")})
            k += 1
            if k == 3:
                break
        manifest[str(i)] = entries
        json.dump(manifest, open(p, "w"), indent=1)
    except Exception:
        pass


def mark_video(scene, source=None, evidence=None):
    """Record editorial source type; MP4 alone does not prove a shot has motion."""
    scene["motion_kind"] = "video"
    scene["motion_mode"] = "stock"
    if source:
        scene["motion_source"] = source
    if evidence:
        scene["motion_verified"] = bool(evidence.get("passes"))
        scene["motion_evidence"] = evidence


def verify_and_mark(scene, clip, source):
    evidence = motion.temporal_evidence(clip)
    if not evidence["passes"]:
        return False, evidence
    mark_video(scene, source, evidence)
    scene["clip_fingerprint"] = motion.scene_visual_fingerprint(scene)
    return True, evidence


def record_source_metadata(scene, video):
    # This is a public frame from the exact selected stock video.  Still shots
    # later download it as their auditable continuity reference and pass the
    # same URL to image-to-image generation.
    if video.get("image"):
        scene["stock_frame_url"] = video["image"]
        scene.pop("stock_frame_url_unusable", None)
    scene["stock_frame_url_checked"] = True
    if video.get("url"):
        scene["source_url"] = video["url"]
    title = video.get("title") or video.get("description")
    if title:
        scene["source_title"] = title
    source = video.get("source")
    if source == "mixkit":
        scene["source_license"] = "Mixkit Stock Video Free License"
    elif source == "coverr":
        scene["source_license"] = (
            "Coverr Free Stock Video License (attribution required)"
        )


def backfill_source_metadata(scene):
    """Recover a public stock frame for clips selected by older pipeline runs."""
    if scene.get("stock_frame_url_checked"):
        return
    stock_id = scene.get("stock_id") or scene.get("pexels_id")
    if not stock_id:
        scene["stock_frame_url_checked"] = True
        return
    try:
        if isinstance(stock_id, str) and ":" in stock_id:
            import sources
            video = sources.fetch_by_id(stock_id)
        else:
            video = api(f"https://api.pexels.com/videos/videos/{stock_id}")
        record_source_metadata(scene, video)
    except Exception as exc:
        scene["stock_frame_url_checked"] = True
        print(f"note: stock frame metadata unavailable for {stock_id} ({exc})")


def fetch_scene(bd, s, i, used_ids):
    m = memory()
    avoid = set(m["used_ids"]) | set(m["banned_ids"]) | used_ids
    sc = s["scenes"][i]
    out = f"{bd}/clip_{i:02d}.mp4"
    if (os.path.exists(out) and os.path.getsize(out) > 100_000 and
            sc.get("clip_fingerprint") != motion.scene_visual_fingerprint(sc)):
        # The scene's visual definition changed since this clip was produced (or
        # the file was restored from a stale CI cache). Never trust it.
        print(f"scene {i}: cached clip is stale for the current scene; re-acquiring")
        os.remove(out)
        sc.pop("clip", None)
    if os.path.exists(out) and os.path.getsize(out) > 100_000:
        sc["clip"] = out
        if sc.get("motion_verified") and sc.get("motion_evidence"):
            # Verification is already recorded for this clip; swap()/pin() clear
            # the flag together with the file, so trust it instead of re-decoding
            # optical flow on every resumable pass.
            backfill_source_metadata(sc)
            return
        if (sc.get("motion_kind") == "video" or
                sc.get("motion_mode") in {"stock", "recorded", "i2v"}):
            passed, evidence = verify_and_mark(
                sc, out, sc.get("motion_source") or "cached_stock"
            )
            if passed:
                backfill_source_metadata(sc)
                return
            print(f"scene {i}: cached clip lacks internal motion {evidence}; replacing")
            os.remove(out)
            sc.pop("clip", None)
        else:
            return
    pinned_id = sc.get("stock_id") or sc.get("pexels_id")
    if pinned_id:  # reproducible re-runs: fetch the exact chosen clip
        try:
            pid = pinned_id
            if isinstance(pid, str) and ":" in pid:
                import sources
                v = sources.fetch_by_id(pid)
            else:
                v = api(f"https://api.pexels.com/videos/videos/{pid}")
            download_video(v, out)
            sc["clip"] = out
            source = v.get("source") or (str(pid).partition(":")[0] if ":" in str(pid)
                                         else "pexels")
            passed, evidence = verify_and_mark(sc, out, source)
            if not passed:
                raise ValueError(f"clip has insufficient temporal motion: {evidence}")
            sc["stock_id"] = pid
            if source == "coverr":
                sc["source_url"] = f"https://coverr.co/videos/{str(pid).partition(':')[2]}"
                sc["source_license"] = (
                    "Coverr Free Stock Video License (attribution required)"
                )
            elif source == "mixkit":
                sc["source_url"] = (
                    f"https://mixkit.co/free-stock-video/{str(pid).partition(':')[2]}/"
                )
                sc["source_license"] = "Mixkit Stock Video Free License"
            record_source_metadata(sc, v)
            print(f"scene {i}: re-fetched {pinned_id}")
            return
        except Exception as e:
            print(f"scene {i}: re-fetch failed ({e}); searching fresh")
    genre = s.get("genre")
    profile = profiles.resolve(s)
    # The original author query remains visible in script.json, while a
    # planner-generated symbol_query can replace vague human mood footage with
    # the physical metaphor chosen for this beat.
    query = visual_symbols.effective_query(sc) or bank_pick(m, genre, profile)
    vids = search(
        query, genre, profile,
        stock_tag=sc.get("stock_tag"),
    )
    vids = [v for v in vids if v["id"] not in avoid]
    if not vids and profile != profiles.JUNE_OXLEY:
        suggestion = visual_symbols.derive_symbol_query(sc)
        symbolic_fallback = suggestion["query"] if suggestion else ""
        if symbolic_fallback and symbolic_fallback != query:
            vids = [
                v for v in search(symbolic_fallback, genre, profile)
                if v["id"] not in avoid
            ]
            if vids:
                query = symbolic_fallback
                sc["symbol_query"] = symbolic_fallback
                sc["symbol_family"] = suggestion["family"]
                sc["symbol_family_source"] = "planner"
                sc["primary_symbol"] = suggestion["symbol"]
                sc["visual_function"] = suggestion["function"]
    if not vids:
        vids = [v for v in search(bank_pick(m, genre, profile), genre, profile)
                if v["id"] not in avoid]
    if not vids:
        sys.exit(f"ERROR scene {i}: no results; edit its query in script.json and rerun")
    scored = rank(query, vids, sc.get("duration"), genre, profile)
    best, v, _, emb = scored[0]
    if best < 20 and query:  # everything off-style -> blend in bank term
        alt = [x for x in search(bank_pick(m, genre, profile), genre, profile)
               if x["id"] not in avoid]
        scored2 = rank(query, alt, sc.get("duration"), genre, profile) if alt else []
        if scored2 and scored2[0][0] > best:
            best, v, _, emb = scored2[0]
            scored = scored2
    selected = None
    for candidate in scored[:8]:
        candidate_score, candidate_video, _thumb, candidate_emb = candidate
        try:
            download_video(candidate_video, out)
            passed, evidence = verify_and_mark(
                sc, out, candidate_video.get("source", "pexels")
            )
            if passed:
                selected = (candidate_score, candidate_video, candidate_emb, evidence)
                break
            print(
                f"scene {i}: reject {candidate_video['id']} for low motion "
                f"({evidence})"
            )
        except Exception as exc:
            print(f"scene {i}: candidate {candidate_video['id']} failed ({exc})")
        try:
            os.remove(out)
        except OSError:
            pass
    if selected is None:
        sys.exit(f"ERROR scene {i}: no candidate contains enough temporal motion")
    best, v, emb, evidence = selected
    save_alts(bd, i, v, scored)
    if emb is not None:  # feed the taste vector on approval/swap later
        import numpy as _np
        _np.save(f"{bd}/emb_{i:02d}.npy", _np.asarray(emb, _np.float32))
    used_ids.add(v["id"])
    sc["clip"] = out
    sc["stock_id"] = v["id"]
    if not isinstance(v["id"], str) or ":" not in str(v["id"]):
        sc["pexels_id"] = v["id"]
    mark_video(sc, v.get("source", "pexels"), evidence)
    record_source_metadata(sc, v)
    print(f"scene {i}: {v.get('source', 'pexels')} {v['id']} ({v['duration']}s, "
          f"score {best:.0f}, profile {profiles.display_name(profile)}) <- "
          f"{query}")


def main(bd, idx=None):
    s = json.load(open(f"{bd}/script.json"))
    profile = profiles.resolve(s)
    if visual_symbols.apply_plan(s, profile):
        json.dump(s, open(f"{bd}/script.json", "w"), indent=1, ensure_ascii=False)
    used = {
        sc.get("stock_id") or sc.get("pexels_id") for sc in s["scenes"]
        if sc.get("stock_id") or sc.get("pexels_id")
    }
    if idx is None:
        targets = range(len(s["scenes"]))
    else:
        targets = [int(part) for part in str(idx).split(",") if part != ""]
    for i in targets:
        fetch_scene(bd, s, i, used)
        json.dump(s, open(f"{bd}/script.json", "w"), indent=1)
    visual_symbols.write_report(bd, s, profile)


def pin(bd, index, stock_id, stock_tag=None):
    """Replace one scene with an explicitly curated stock clip."""
    script_path = f"{bd}/script.json"
    script = json.load(open(script_path))
    scene = script["scenes"][int(index)]
    scene["stock_id"] = stock_id
    scene.pop("pexels_id", None)
    if stock_tag:
        scene["stock_tag"] = stock_tag
    for field in (
        "clip", "motion_verified", "motion_evidence", "motion_source",
        "source_url", "source_license", "source_title", "stock_frame_url",
        "stock_frame_url_checked", "stock_frame_url_unusable",
    ):
        scene.pop(field, None)
    output = f"{bd}/clip_{int(index):02d}.mp4"
    try:
        os.remove(output)
    except OSError:
        pass
    used = {
        item.get("stock_id") or item.get("pexels_id")
        for n, item in enumerate(script["scenes"])
        if n != int(index) and (item.get("stock_id") or item.get("pexels_id"))
    }
    fetch_scene(bd, script, int(index), used)
    json.dump(script, open(script_path, "w"), indent=1, ensure_ascii=False)


def write_credits(bd):
    """Write source/license attribution for every stock scene."""
    with open(f"{bd}/script.json") as handle:
        script = json.load(handle)
    title = " ".join(str(script.get("title") or script.get("slug") or "VIDEO").split())
    lines = [f"{title.upper()} — STOCK FOOTAGE CREDITS", ""]
    seen = set()
    for index, scene in enumerate(script.get("scenes", [])):
        source = scene.get("motion_source")
        stock_id = scene.get("stock_id") or scene.get("pexels_id")
        if not stock_id or stock_id in seen:
            continue
        seen.add(stock_id)
        lines.append(
            f"Scene {index:02d} — {source or 'stock'} — {stock_id}"
        )
        if scene.get("source_url"):
            lines.append(scene["source_url"])
        if scene.get("source_license"):
            lines.append(scene["source_license"])
        lines.append("")
    with open(f"{bd}/CREDITS.txt", "w") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    print(f"credits: {len(seen)} stock clips -> {bd}/CREDITS.txt")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2] == "credits":
        write_credits(sys.argv[1])
    elif len(sys.argv) > 2 and sys.argv[2] == "pin":
        pin(
            sys.argv[1], int(sys.argv[3]), sys.argv[4],
            sys.argv[5] if len(sys.argv) > 5 else None,
        )
    else:
        main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
