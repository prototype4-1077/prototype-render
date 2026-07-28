"""Local word-level transcription of vo.mp3 (faster-whisper), chunked + resumable.
Usage: python3 transcribe.py <build_dir>     # run repeatedly until it prints 'words.json done'
Writes <build_dir>/words.json: [{"w": word, "s": start, "e": end}, ...]
Chunks of 55s per invocation keep each run inside the sandbox's 45s bash limit."""
import json, os, subprocess, sys

CHUNK = float(os.environ.get("TRANSCRIBE_CHUNK_SECONDS") or 55.0)


def duration(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", f], capture_output=True, text=True)
    return float(r.stdout.strip())


def main(bd):
    vo, out, part = f"{bd}/vo.mp3", f"{bd}/words.json", f"{bd}/words_partial.json"
    if os.path.exists(out):
        return print("words.json done")
    from faster_whisper import WhisperModel
    dur = duration(vo)
    state = json.load(open(part)) if os.path.exists(part) else {"t": 0.0, "words": []}
    t0 = state["t"]
    # decode one chunk to wav (small overlap so boundary words aren't lost)
    a, b = max(0, t0 - 0.4), min(dur, t0 + CHUNK)
    wav = f"{bd}/_chunk.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a), "-to", str(b),
                    "-i", vo, "-ac", "1", "-ar", "16000", wav], check=True)
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "base"), device="cpu", compute_type="int8")
    segs, _ = model.transcribe(wav, word_timestamps=True, language="en")
    for seg in segs:
        for w in seg.words or []:
            ws = round(w.start + a, 3)
            if state["words"] and ws <= state["words"][-1]["s"]:
                continue  # drop overlap duplicates
            state["words"].append({"w": w.word.strip(), "s": ws, "e": round(w.end + a, 3)})
    state["t"] = b
    if b >= dur - 0.05:
        json.dump(state["words"], open(out, "w"))
        for f in (part, wav):
            if os.path.exists(f):
                try: os.remove(f)
                except OSError: pass
        print(f"words.json done ({len(state['words'])} words)")
    else:
        json.dump(state, open(part, "w"))
        print(f"RUN AGAIN (transcribed {b:.0f}/{dur:.0f}s)")


if __name__ == "__main__":
    main(sys.argv[1])
