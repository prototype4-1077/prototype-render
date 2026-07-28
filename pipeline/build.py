"""One-command build orchestrator. Run repeatedly until it prints DONE.

    python3 build.py <build_dir>

Each run loads API keys from .env itself, checks fonts, validates script.json,
then advances the build as far as it can within a ~30s budget and exits with:
    RUN AGAIN  (progress note)      -> just run the same command again
    DONE -> final_youtube.mp4 (default) -> finished
    ERROR: <what> | FIX: <how>      -> fix, then run again
Every step is resumable; running again never breaks anything."""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request

import motion
import hero
import audio_variants
import render_policy
import profiles
import review
import still_reference
import visual_symbols

T0 = time.time()
BUDGET = 30
HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = {
    "Questrial-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/questrial/Questrial-Regular.ttf",
    "Baloo2-ExtraBold.ttf": None,  # instanced from variable font below
    "Baloo2.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/baloo2/Baloo2%5Bwght%5D.ttf",
}


def left(): return BUDGET - (time.time() - T0)


def out(msg): print(msg); sys.exit(0)


def err(what, fix): print(f"ERROR: {what} | FIX: {fix}"); sys.exit(1)


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return r


def load_env():
    envf = os.path.join(HERE, ".env")
    if os.path.exists(envf):
        for line in open(envf):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)
    if not os.environ.get("ELEVENLABS_API_KEY"):
        err("missing ELEVENLABS_API_KEY", "add it to pipeline/.env")
    if not os.environ.get("PEXELS_API_KEY"):
        print("note: PEXELS_API_KEY is not configured; using keyless stock providers")


def ensure_fonts():
    fdir = os.path.join(HERE, "fonts")
    os.makedirs(fdir, exist_ok=True)
    ua = [("User-Agent", "Mozilla/5.0")]
    op = urllib.request.build_opener(); op.addheaders = ua
    urllib.request.install_opener(op)
    for name, url in FONTS.items():
        p = os.path.join(fdir, name)
        if os.path.exists(p) or url is None:
            continue
        try:
            urllib.request.urlretrieve(url, p)
        except Exception as e:
            err(f"font download failed ({name}): {e}",
                "check network egress is 'All domains', then rerun")
    eb = os.path.join(fdir, "Baloo2-ExtraBold.ttf")
    if not os.path.exists(eb):
        r = sh([sys.executable, "-m", "fontTools.varLib.instancer",
                os.path.join(fdir, "Baloo2.ttf"), "wght=800", "-o", eb])
        if r.returncode != 0:  # fonttools missing -> variable font works too (regular weight)
            shutil.copy(os.path.join(fdir, "Baloo2.ttf"), eb)


def validate(bd):
    p = f"{bd}/script.json"
    if not os.path.exists(p):
        err("no script.json", f"write {p} per HANDOFF.md template")
    try:
        s = json.load(open(p))
    except Exception as e:
        err(f"script.json is not valid JSON: {e}", "fix the JSON syntax")
    if not s.get("title") or not s.get("slug"):
        err("script.json missing title/slug", "add them")
    try:
        profile = profiles.resolve(s, strict=True)
    except ValueError as e:
        err(str(e), "remove the profile or use profile: june_oxley")
    if profile and s.get("profile") != profile:
        s["profile"] = profile
        json.dump(s, open(p, "w"), indent=1, ensure_ascii=False)
    sc = s.get("scenes") or []
    user_vo = os.path.exists(f"{bd}/vo.mp3") and not any(x.get("start") is not None for x in sc[:1]) \
              or s.get("user_vo")
    # Scene-count and word-count are pacing guidance for AI-written scripts. When
    # James supplies verbatim text (supplied_script) or a voiceover, they become
    # advisory only, honoring the "supplied scripts, any length" policy.
    lenient = os.path.exists(f"{bd}/vo.mp3") or s.get("user_vo") or s.get("supplied_script")
    soft = (lambda what, fix: print(f"note: {what} ({fix}) - allowed, supplied/verbatim script"))\
        if lenient else err
    if not 14 <= len(sc) <= 30:
        soft(f"{len(sc)} scenes", "aim for 18-26 scenes (one sentence/beat each)")
    words = sum(len(x.get("text", "").split()) for x in sc)
    if not 250 <= words <= 450:
        soft(f"script is {words} words", "aim for 300-400 words total")
    for i, x in enumerate(sc):
        if not x.get("text"):
            err(f"scene {i} has no text", "every scene needs a 'text' sentence")
        if len(x["text"]) > 220:
            err(f"scene {i} text too long ({len(x['text'])} chars)", "split it into two scenes")
        low = x["text"].lower()
        for k in x.get("keywords", []):
            if k.lower().split()[0] not in low:
                print(f"note: scene {i} keyword '{k}' not found in text (won't highlight)")
    # Give every beat an explicit visual job before spending time or API calls.
    # Advisory scripts receive a report; new scripts that opt into the standing
    # diverse-symbol policy fail early on severe human/family repetition.
    changed = visual_symbols.apply_plan(s, profile)
    report = visual_symbols.write_report(bd, s, profile)
    if changed:
        json.dump(s, open(p, "w"), indent=1, ensure_ascii=False)
    for warning in report["warnings"]:
        print(f"note: visual symbols: {warning}")
    if report["violations"]:
        err(
            "visual symbol plan: " + "; ".join(report["violations"]),
            "replace generic human queries with varied physical symbols or assign a concrete human_role",
        )
    return s


def probe_ok(f):
    return sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", f]).returncode == 0


def main(bd):
    bd = bd.rstrip("/")
    load_env()
    ensure_fonts()
    s = validate(bd)
    n = len(s["scenes"])
    py = sys.executable

    # Editorial curation mode: use the existing, trusted render workflow to
    # return ranked Pexels contact sheets as a temporary final.mp4 artifact.
    # This avoids blind rerolls when a narration line needs a rare exact image.
    if s.get("curate_scenes"):
        indexes = s["curate_scenes"]
        if isinstance(indexes, list):
            indexes = ",".join(str(i) for i in indexes)
        r = sh([py, os.path.join(HERE, "curate.py"), bd, str(indexes)])
        if r.returncode != 0:
            err(f"curation failed: {r.stderr[-500:]}", "refine the affected scene queries and rerun")
        print(r.stdout.strip())
        out(f"DONE -> {bd}/final.mp4 (curation reel)")

    # 1. voiceover (generate) or align (user-provided vo.mp3 without timings)
    # Stale-voice guard: a cached vo.mp3 from a previous script version must not
    # survive a text/tag/voice change (same class of bug as clip fingerprints).
    if os.path.exists(f"{bd}/vo.mp3") and not s.get("user_vo"):
        try:
            import tts as _tts
            _mf_path = f"{bd}/voiceover-manifest.json"
            _mf = json.load(open(_mf_path)) if os.path.exists(_mf_path) else {}
            _want = _tts.tts_fingerprint(s, s.get("elevenlabs_model", "eleven_v3"))
            if _mf.get("tts_fingerprint") != _want:
                for _f in ("vo.mp3", "words.json", "voiceover-manifest.json"):
                    try: os.remove(f"{bd}/{_f}")
                    except OSError: pass
                out("RUN AGAIN (stale voiceover removed; regenerating)")
        except Exception as _e:
            print(f"vo fingerprint check skipped: {_e}")
    if not os.path.exists(f"{bd}/vo.mp3"):
        r = sh([py, os.path.join(HERE, "tts.py"), bd])
        if r.returncode != 0:
            err(f"tts failed: {r.stderr[-300:]}", "check ELEVENLABS_API_KEY / credits, rerun")
        out(f"RUN AGAIN (voiceover done, {n} scenes timed)")
    # 1b. local word-level transcription (word-synced captions), if faster-whisper exists
    need_words = not os.path.exists(f"{bd}/words.json") and not os.path.exists(f"{bd}/final.mp4")
    if need_words:
        try:
            import faster_whisper  # noqa
            while not os.path.exists(f"{bd}/words.json"):
                if left() < 12:
                    out("RUN AGAIN (transcribing VO for word-synced captions)")
                r = sh([py, os.path.join(HERE, "transcribe.py"), bd])
                if r.returncode != 0:
                    print(f"note: transcription failed ({r.stderr[-160:]}); captions will be static")
                    break
            # re-time scenes with word-level data
            for x in s["scenes"]:
                x.pop("duration", None)
            json.dump(s, open(f"{bd}/script.json", "w"), indent=1, ensure_ascii=False)
        except ImportError:
            print("note: faster-whisper not installed; captions will be static-highlight")

    if any(x.get("duration") is None for x in s["scenes"]):
        r = sh([py, os.path.join(HERE, "align.py"), bd])
        if r.returncode != 0:
            err(f"align failed: {r.stderr[-300:]}", "rerun; fallback timing needs only ffprobe")
        print(r.stdout.strip())
        out(f"RUN AGAIN (user VO aligned to {n} scenes)")

    s = json.load(open(f"{bd}/script.json"))

    # Motion is editorial metadata, not a file-extension guess.  Persist the
    # source class before acquiring footage so resumable passes agree about the
    # duration budget.
    if motion.apply_motion_defaults(s):
        json.dump(s, open(f"{bd}/script.json", "w"), indent=1, ensure_ascii=False)

    # 2. Acquire genuine stock footage first.  Its selected public frame is the
    # visual reference for every later still, so hero generation can inherit the
    # actual film's lens, palette, lighting, and production texture.
    stock_pending = still_reference.stock_targets(bd, s)
    if stock_pending:
        # One batched invocation: the CLIP scoring model loads once for every
        # pending scene instead of once per scene (its load alone is ~30s).
        if left() < 60:
            out(f"RUN AGAIN (stock references pending: {len(stock_pending)})")
        batch = ",".join(str(i) for i in stock_pending)
        r = sh([py, os.path.join(HERE, "footage.py"), bd, batch])
        if r.returncode != 0:
            err(f"footage batch [{batch}]: {r.stderr[-300:]}",
                "edit the failing scene's query in script.json, rerun")
    if stock_pending:
        out(f"RUN AGAIN (genuine footage ready; next: reference-matched stills)")

    s = json.load(open(f"{bd}/script.json"))

    # 2a. Supplied/keyframe stills are copied into reference-matched derivatives,
    # then compiled with the full enhancement path. Originals are never changed.
    for i, sc in enumerate(s["scenes"]):
        if sc.get("hero"):
            continue
        if not motion.needs_compile(bd, sc, i):
            continue
        clip = f"{bd}/clip_{i:02d}.mp4"
        if (sc.get("motion_compiled") and os.path.exists(clip) and
                os.path.getsize(clip) > 100_000 and
                still_reference.reference_is_current(bd, s, i)):
            continue
        if left() < 25:
            out(f"RUN AGAIN (next: motion shot {i})")
        r = sh([py, os.path.join(HERE, "motion.py"), "compile", bd, str(i)])
        if r.returncode != 0:
            err(f"motion scene {i}: {r.stderr[-300:]}",
                "fix source_image/keyframes or set motion_mode to stock")
        print(r.stdout.strip())
        s = json.load(open(f"{bd}/script.json"))

    # 2b. Hero shots: the closest related selected stock frame is the actual
    # Kontext image-to-image input, followed by palette/exposure harmonization,
    # depth layers, background completion, and restrained internal motion.
    for i, sc in enumerate(s["scenes"]):
        if not sc.get("hero") or sc.get("motion_kind") == motion.VIDEO:
            continue
        clip = f"{bd}/clip_{i:02d}.mp4"
        raw = f"{bd}/hero_{i:02d}_raw.jpg"
        if (os.path.exists(clip) and os.path.getsize(clip) > 100_000 and
                sc.get("clip_fingerprint") == motion.scene_visual_fingerprint(sc) and
                hero.source_matches(sc, raw) and
                (sc.get("hero_style") or still_reference.reference_is_current(bd, s, i))):
            continue
        if left() < 25:
            out(f"RUN AGAIN (next: hero shot {i})")
        r = sh([py, os.path.join(HERE, "hero.py"), bd, str(i)])
        if r.returncode != 0:
            print(f"note: hero {i} failed ({r.stderr[-160:]}); falling back to stock footage")
            # Do not let an older, unreferenced hero clip mask the fallback.
            try:
                os.remove(clip)
            except OSError:
                pass
        else:
            print(r.stdout.strip())

    # 2c. A hero can fall back to genuine stock when reference-conditioned image
    # generation is temporarily unavailable. Ordinary missing scenes also land here.
    missing = [i for i in range(n)
               if not (os.path.exists(f"{bd}/clip_{i:02d}.mp4")
                       and os.path.getsize(f"{bd}/clip_{i:02d}.mp4") > 100_000)]
    if missing:
        if left() < 60:
            out(f"RUN AGAIN (footage pending: {len(missing)}/{n})")
        batch = ",".join(str(i) for i in missing)
        r = sh([py, os.path.join(HERE, "footage.py"), bd, batch])
        if r.returncode != 0:
            err(f"footage batch [{batch}]: {r.stderr[-300:]}",
                "edit the failing scene's query in script.json, rerun")
    if missing:
        out(f"RUN AGAIN (footage complete {n}/{n})")

    # Coverr's free license requires attribution.  Generate this on every
    # completed acquisition pass so both workflow artifacts and Releases carry
    # the exact sources used by the current script.
    r = sh([py, os.path.join(HERE, "footage.py"), bd, "credits"])
    if r.returncode != 0:
        err(f"stock credits failed: {r.stderr[-300:]}", "rerun the build")
    print(r.stdout.strip())

    # A pan/zoom or depth/keyframe animation remains still-derived even when
    # encoded as MP4. Enforce the source cap by seconds after all footage is
    # resolved and emit a reviewable manifest.
    s = json.load(open(f"{bd}/script.json"))
    visual_report = visual_symbols.write_report(bd, s, profiles.resolve(s))
    if visual_report["violations"]:
        err(
            "visual symbol plan after timing: " + "; ".join(visual_report["violations"]),
            "diversify long human/symbol runs before acquiring replacement footage",
        )
    motion.write_report(bd, s)
    still_reference.write_report(bd, s)
    try:
        mr = motion.validate_budget(s)
        motion.validate_video_evidence(s)
        still_reference.validate(bd, s)
    except motion.MotionBudgetError as e:
        err(str(e), "replace still-derived scenes with verified moving footage")
    except still_reference.StillReferenceError as e:
        err(str(e), "regenerate the still from its closest selected stock-frame reference")
    still_seconds = mr.static_seconds + mr.animated_seconds
    print(f"motion budget: still-derived {mr.still_source_ratio:.1%} "
          f"({still_seconds:.1f}s/{mr.total_seconds:.1f}s); "
          f"true motion {mr.video_ratio:.1%}")

    # 3. Generate only the overlays and score requested by the output policy.
    try:
        outputs = render_policy.render_outputs(s)
        audio_variants.require(s, bd)
        music_ready = True
    except ValueError:
        outputs = render_policy.render_outputs(s)
        music_ready = False
    portrait_segments = render_policy.needs_portrait_segments(s)
    youtube_segments = "youtube" in outputs
    required_overlays = []
    if portrait_segments:
        required_overlays.extend([
            f"{bd}/cap_{n-1:02d}.png",
            f"{bd}/title.png",
        ])
    if youtube_segments:
        required_overlays.extend([
            f"{bd}/youtube_cap_{n-1:02d}.png",
            f"{bd}/youtube_title.png",
        ])
    if any(not os.path.exists(path) for path in required_overlays) or not music_ready:
        if left() < 15:
            out("RUN AGAIN (next: selected overlays and score)")
        r = sh([py, os.path.join(HERE, "prep.py"), bd])
        if r.returncode != 0:
            err(
                f"prep failed: {r.stderr[-300:]}",
                "rerun; if fonts missing delete fonts/ and rerun",
            )
        print(r.stdout.strip())
        out(f"RUN AGAIN ({', '.join(outputs)} overlays + selected score ready)")

    # 4. Render only scene canvases needed by the requested finished files.
    if portrait_segments:
        for i in range(n):
            seg = f"{bd}/seg_{i:02d}.mp4"
            if os.path.exists(seg):
                continue
            if left() < 12:
                out(f"RUN AGAIN (rendered {i}/{n} portrait scenes)")
            r = sh([py, os.path.join(HERE, "assemble.py"), bd, "scene", str(i)])
            if r.returncode != 0:
                err(
                    f"render portrait scene {i}: {r.stderr[-300:]}",
                    "rerun; if it repeats, delete that seg file",
                )
        for i in range(n):
            seg = f"{bd}/seg_{i:02d}.mp4"
            if not probe_ok(seg):
                try:
                    os.remove(seg)
                    out(f"RUN AGAIN (portrait seg {i} was corrupt, will re-render)")
                except OSError:
                    err(
                        f"portrait seg {i} corrupt and undeletable",
                        "enable file deletion, delete it, rerun",
                    )

    if youtube_segments:
        for i in range(n):
            seg = f"{bd}/youtube_seg_{i:02d}.mp4"
            if os.path.exists(seg):
                continue
            if left() < 12:
                out(f"RUN AGAIN (rendered {i}/{n} YouTube scenes)")
            r = sh([
                py, os.path.join(HERE, "assemble.py"), bd, "youtube-scene", str(i)
            ])
            if r.returncode != 0:
                err(
                    f"render YouTube scene {i}: {r.stderr[-300:]}",
                    "rerun; if it repeats, delete that YouTube seg file",
                )
        for i in range(n):
            seg = f"{bd}/youtube_seg_{i:02d}.mp4"
            if not probe_ok(seg):
                try:
                    os.remove(seg)
                    out(f"RUN AGAIN (YouTube seg {i} was corrupt, will re-render)")
                except OSError:
                    err(
                        f"YouTube seg {i} corrupt and undeletable",
                        "enable file deletion, delete it, rerun",
                    )

    # 5. Assemble one canonical video per requested canvas. Explicit alternative
    # score choices receive additional files; the selected score remains canonical.
    try:
        variants = audio_variants.require(s, bd)
    except ValueError as e:
        err(str(e), "rerun prep to generate the selected music choice")

    def assemble_canvas(canvas, segment_prefix, canonical_name):
        targets = [
            f"{bd}/{render_policy.video_name(canvas, position, item)}"
            for position, item in enumerate(variants)
        ]
        if all(os.path.exists(path) and probe_ok(path) for path in targets):
            return
        if left() < 20:
            out(f"RUN AGAIN (next: {canvas} final assembly)")
        tmp = tempfile.mkdtemp()
        try:
            lst = os.path.join(tmp, f"{canvas}-list.txt")
            with open(lst, "w") as handle:
                for scene_index in range(n):
                    handle.write(
                        f"file '{os.path.abspath(bd)}/{segment_prefix}"
                        f"{scene_index:02d}.mp4'\n"
                    )
            noaudio = os.path.join(tmp, f"{canvas}-noaudio.mp4")
            result = sh([
                "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                "-i", lst, "-c", "copy", noaudio,
            ])
            if result.returncode != 0:
                err(f"{canvas} concat: {result.stderr[-300:]}", "rerun")
            total = sum(scene["duration"] for scene in s["scenes"])
            for position, (item, target) in enumerate(zip(variants, targets)):
                if os.path.exists(target) and probe_ok(target):
                    continue
                try:
                    audio_variants.mix(
                        noaudio, f"{bd}/vo.mp3", f"{bd}/{item['file']}", total, target
                    )
                    print(f"{os.path.basename(target)} done: {item['label']}")
                except Exception as e:
                    err(f"{canvas} music choice {position + 1} mix: {e}", "rerun")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        canonical = f"{bd}/{canonical_name}"
        if not probe_ok(canonical):
            try:
                os.remove(canonical)
            except OSError:
                pass
            out(f"RUN AGAIN ({canonical_name} was incomplete, will redo)")

    if "portrait" in outputs:
        assemble_canvas("portrait", "seg_", "final.mp4")
    if "youtube" in outputs:
        assemble_canvas("youtube", "youtube_seg_", "final_youtube.mp4")

    # 6. A portrait short is opt-in and reuses portrait segments only when requested.
    if "short" in outputs:
        short = f"{bd}/final_short.mp4"
        if not (os.path.exists(short) and probe_ok(short)):
            if left() < 20:
                out("RUN AGAIN (next: requested short cut)")
            r = sh([py, os.path.join(HERE, "shortcut.py"), bd])
            if r.returncode != 0:
                err(f"short cut failed: {r.stderr[-300:]}", "rerun")
            print(r.stdout.strip())

    audio_variants.write_manifest(bd, variants, outputs)
    sheet = f"{bd}/alts_sheet.jpg"
    if not os.path.exists(sheet) and os.path.exists(f"{bd}/alts.json"):
        if left() < 15:
            out("RUN AGAIN (next: review sheet)")
        r = sh([py, os.path.join(HERE, "altsheet.py"), bd])
        print(r.stdout.strip() if r.returncode == 0 else "note: review sheet failed")

    # Every finished video ships with a standalone, machine-readable scene survey.
    if not review.is_current(bd):
        if left() < 25:
            out("RUN AGAIN (next: scene review survey)")
        try:
            review.generate(bd)
        except Exception as e:
            err(
                f"scene review survey: {e}",
                "rerun; if it repeats, inspect pipeline/review.py",
            )

    finished = [f"{bd}/{name}" for name in render_policy.required_video_names(s)]
    missing = [path for path in finished if not probe_ok(path)]
    if missing:
        err("required output missing: " + ", ".join(missing), "rerun")
    print("DONE -> " + " + ".join(finished))
    print(f"After James approves: python3 {os.path.join(HERE, 'learn.py')} record {bd}")
    print(f"If he dislikes scene i's footage: python3 {os.path.join(HERE, 'learn.py')} swap {bd} <i>")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        err("no build dir given", "run: python3 build.py build/<slug>")
    main(sys.argv[1])

