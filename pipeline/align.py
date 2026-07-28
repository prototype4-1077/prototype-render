"""Scene timing + per-keyword ignition times for the voiceover.
Usage: python3 align.py <build_dir>
Priority: words.json (local whisper, from transcribe.py) -> ElevenLabs forced
alignment -> proportional fallback. Fills scene start/duration and, when word
times exist, scene kw_times {keyword: absolute_seconds} for word-synced captions."""
import json, os, re, subprocess, sys

TAIL = 1.6


def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def vo_duration(vo):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", vo], capture_output=True, text=True)
    return float(r.stdout.strip())


def match_words(script_words, spoken):
    """Sequential fuzzy match; returns per-script-word time (or None)."""
    times, j = [], 0
    for sw in script_words:
        t, n = None, norm(sw)
        if n:
            for k in range(j, min(j + 10, len(spoken))):
                if norm(spoken[k]["w"]) == n:
                    t, j = spoken[k]["s"], k + 1
                    break
        times.append(t)
    # interpolate gaps
    known = [(i, t) for i, t in enumerate(times) if t is not None]
    if not known:
        return None
    for i in range(len(times)):
        if times[i] is None:
            prev = max((k for k in known if k[0] < i), default=known[0], key=lambda x: x[0])
            nxt = min((k for k in known if k[0] > i), default=known[-1], key=lambda x: x[0])
            if nxt[0] == prev[0]:
                times[i] = prev[1]
            else:
                f = (i - prev[0]) / (nxt[0] - prev[0])
                times[i] = prev[1] + f * (nxt[1] - prev[1])
    return times


def elevenlabs_starts(vo, texts, full):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return None
    r = subprocess.run(["curl", "-s", "-X", "POST",
                        "https://api.elevenlabs.io/v1/forced-alignment",
                        "-H", f"xi-api-key: {key}",
                        "-F", f"file=@{vo}", "-F", f"text={full}"],
                       capture_output=True, text=True, timeout=180)
    try:
        chars = json.loads(r.stdout)["characters"]
        if abs(len(chars) - len(full)) > 2:
            return None
        starts, pos = [], 0
        for t in texts:
            starts.append(chars[min(pos, len(chars) - 1)]["start"])
            pos += len(t) + 1
        return starts
    except Exception:
        return None


def align(bd):
    s = json.load(open(f"{bd}/script.json"))
    vo = f"{bd}/vo.mp3"
    texts = [sc["text"] for sc in s["scenes"]]
    full = " ".join(texts)
    dur = vo_duration(vo)
    starts, word_times, src = None, None, "proportional"

    wj = f"{bd}/words.json"
    if os.path.exists(wj):
        spoken = json.load(open(wj))
        wt = match_words(full.split(), spoken)
        if wt:
            word_times, src = wt, "whisper"
            starts, pos = [], 0
            for t in texts:
                starts.append(word_times[pos])
                pos += len(t.split())
    if starts is None:
        starts = elevenlabs_starts(vo, texts, full)
        if starts: src = "elevenlabs"
    if starts is None:
        total_words = sum(len(t.split()) for t in texts)
        starts, acc = [], 0
        for t in texts:
            starts.append(acc / total_words * (dur - 1.0) + 0.2)
            acc += len(t.split())

    ends = starts[1:] + [dur + TAIL]
    pos = 0
    for sc, st, en in zip(s["scenes"], starts, ends):
        sc["start"] = round(st, 3)
        sc["duration"] = round(max(en - st, 1.5), 3)
        if word_times:  # keyword ignition times for word-synced captions
            sw = sc["text"].split()
            kt = {}
            for kw in sc.get("keywords", []):
                first = norm(kw.split()[0])
                for i, w in enumerate(sw):
                    if norm(w) == first and word_times[pos + i] is not None:
                        kt[kw] = round(word_times[pos + i], 3)
                        break
            if kt:
                sc["kw_times"] = kt
        pos += len(sc["text"].split())
    s["voiceover"] = "vo.mp3"
    json.dump(s, open(f"{bd}/script.json", "w"), indent=1, ensure_ascii=False)
    total = sum(sc["duration"] for sc in s["scenes"])
    print(f"aligned {len(texts)} scenes over {dur:.1f}s VO via {src} (video {total:.1f}s)")


if __name__ == "__main__":
    align(sys.argv[1])
