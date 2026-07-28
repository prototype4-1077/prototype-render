"""Generative cinematic score engine v3 (fully synthesized - no licensing, no APIs).
Usage: python3 music.py <out.wav> <seconds> [vo.mp3|-] [genre|-] [profile|-] [variant]
- slow minor chord pads with detuned voices + synthetic reverb (real stereo)
- deep root drone + filtered-noise swells that bloom in the VO's pauses
- subtle heartbeat pulse (philosophy) / shimmering plucks (dmt)
- VO-adaptive: recedes under speech, swells in gaps, builds toward the ending"""
import subprocess, sys, wave
import numpy as np

import profiles

SR = 44100

VARIANT_NAMES = {
    None: ("Cinematic Pulse", "Glass Horizon", "Deep Current"),
    "dmt": ("Prism Drift", "Crystal Orbit", "Deep Portal"),
    "june_oxley": ("Porch Shuffle", "Dusk Fingerpick", "Creekside Stomp"),
}


def variant_family(variant):
    return (max(1, int(variant or 1)) - 1) % 3 + 1


def variant_label(variant, genre=None, profile=None):
    key = "june_oxley" if profile == profiles.JUNE_OXLEY else genre
    names = VARIANT_NAMES.get(key, VARIANT_NAMES[None])
    return names[variant_family(variant) - 1]


def vo_envelope(vo, seconds, n):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", vo, "-ac", "1", "-ar", "8000",
                        "-f", "s16le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if len(x) < 8000:
        return None, None
    hop = 800
    frames = len(x) // hop
    rms = np.sqrt((x[:frames * hop].reshape(frames, hop) ** 2).mean(axis=1))
    rms = rms / (np.percentile(rms, 95) + 1e-9)
    sm = np.clip(np.convolve(rms, np.ones(15) / 15, mode="same"), 0, 1)
    quiet, onsets, run = sm < 0.12, [], 0
    for i, q in enumerate(quiet):
        run = run + 1 if q else 0
        if run == 8:
            onsets.append((i - 7) * hop / 8000.0)
    env = np.interp(np.linspace(0, len(sm) - 1, n), np.arange(len(sm)), sm)
    return env, onsets


def _reverb(x, decay=2.2, mix=0.22, seed=3):
    rng = np.random.default_rng(seed)
    L = int(decay * SR)
    t = np.arange(L) / SR
    ir = rng.standard_normal(L).astype(np.float32) * np.exp(-t / (decay * 0.35))
    ir /= np.abs(ir).sum() ** 0.5 * 40
    m = 1 << int(np.ceil(np.log2(len(x) + L)))
    wet = np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(ir, m))[:len(x)]
    return x * (1 - mix) + wet.astype(np.float32) * mix


def _pad(freqs, n, rng):
    t = np.arange(n) / SR
    v = np.zeros(n, np.float32)
    for f in freqs:
        for det in (-0.15, 0.0, 0.15):                     # detuned voices = width/warmth
            ph = rng.uniform(0, 2 * np.pi)
            for h, a in ((1, 1.0), (2, 0.35), (3, 0.12), (4, 0.05)):
                v += (a / len(freqs)) * np.sin(2 * np.pi * (f + det) * h * t + ph)
    return v * 0.22


def _swell_noise(n, seconds, rng):
    spec = np.fft.rfft(rng.standard_normal(n).astype(np.float32))
    fr = np.fft.rfftfreq(n, 1 / SR)
    spec *= np.exp(-((np.log(fr + 1) - np.log(400)) ** 2) / 1.1)   # airy band ~200-900Hz
    return np.fft.irfft(spec, n)[:n].astype(np.float32) * 0.9


CHORDS = {
    None: [(110.0, 220.0, 261.63, 329.63), (87.31, 174.61, 261.63, 349.23),
           (130.81, 196.0, 261.63, 392.0), (98.0, 196.0, 293.66, 392.0)],   # Am F C G
    "dmt": [(130.81, 196.0, 293.66, 392.0), (146.83, 220.0, 329.63, 440.0),
            (98.0, 196.0, 246.94, 369.99), (110.0, 220.0, 277.18, 415.30)],  # lydian-ish
}

JUNE_CHORDS = [
    (98.00, 123.47, 146.83, 196.00),       # G
    (130.81, 164.81, 196.00, 261.63),      # C
    (98.00, 123.47, 146.83, 196.00),       # G
    (146.83, 185.00, 220.00, 293.66),      # D
]


def _pluck(freq, dur, rng, brightness=1.0):
    """Short, woody string voice: additive twang plus a tiny pick transient."""
    n = max(1, int(dur * SR)); t = np.arange(n) / SR
    x = np.zeros(n, np.float32)
    ph = rng.uniform(0, 2 * np.pi)
    for h, amp in ((1, 1.0), (2, .58), (3, .32), (4, .18), (5, .10)):
        x += amp * np.sin(2 * np.pi * freq * h * t + ph + h * .17) \
             * np.exp(-t * (2.4 + h * .72) * brightness)
    pick_n = min(int(.035 * SR), n)
    if pick_n:
        pick = rng.standard_normal(pick_n).astype(np.float32)
        pick *= np.linspace(1, 0, pick_n, dtype=np.float32) ** 2
        x[:pick_n] += pick * .22
    x *= np.minimum(1, t / .006)
    return x * .22


def _porch_score(n, seconds, rng, variant=1):
    """Dry front-porch shuffle: guitar/banjo twang, upright bass, and soft brush."""
    out = np.zeros(n, np.float32)
    family = variant_family(variant)
    bpm = {1: 84.0, 2: 76.0, 3: 92.0}[family]
    beat = 60.0 / bpm
    total_beats = int(seconds / beat) + 1

    def add(x, at, gain=1.0):
        i0 = int(at * SR)
        if i0 >= n: return
        L = min(len(x), n - i0)
        out[i0:i0 + L] += x[:L] * gain

    for b in range(total_beats):
        at = b * beat
        chord = JUNE_CHORDS[(b // 4) % len(JUNE_CHORDS)]
        within = b % 4
        # Root/fifth thump keeps the bed moving without becoming a full country song.
        bass_f = chord[0] / 2 if within % 2 == 0 else chord[2] / 2
        add(_pluck(bass_f, min(1.0, seconds - at + .1), rng, .72), at, .34)
        chord_beats = (0, 2) if family != 2 else (0, 3)
        if within in chord_beats:
            for j, f in enumerate(chord[1:]):
                add(_pluck(f, min(1.35, seconds - at + .1), rng, .92),
                    at + j * .018, .20)
        # A restrained banjo-like roll on the offbeats supplies the "hickish" identity.
        roll = ((chord[2] * 2, chord[1] * 2, chord[3] * 2) if family != 2
                else (chord[1] * 2, chord[3] * 2))
        for j, f in enumerate(roll):
            st = at + beat * ((.50 + j * .16) if family != 3 else (.34 + j * .20))
            if st < seconds:
                add(_pluck(f, min(.55, seconds - st + .1), rng,
                           1.05 if family == 2 else 1.35), st,
                    .075 if family == 2 else .10)
        # Dry brush/shaker, deliberately quieter than the strings.
        st = at + beat * .5
        if st < seconds:
            L = min(int(.11 * SR), n - int(st * SR))
            brush = rng.standard_normal(L).astype(np.float32)
            brush *= np.exp(-np.arange(L) / SR / .035)
            add(brush, st, .012)
    return out


def gen(path, seconds, vo=None, genre=None, profile=None, variant=1):
    vo = None if vo in (None, "", "-") else vo
    genre = None if genre in (None, "", "-") else genre
    profile = None if profile in (None, "", "-") else profile
    variant = max(1, int(variant or 1))
    family = variant_family(variant)
    rng = np.random.default_rng(11 + variant * 101)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    # 1. chord pads, 14s bars with 4s equal-power crossfades
    june = profile == profiles.JUNE_OXLEY
    chords = list(JUNE_CHORDS if june else CHORDS.get(genre, CHORDS[None]))
    if family == 2:
        chords = chords[2:] + chords[:2]
        chords = [tuple(f * 1.05946 for f in chord) for chord in chords]
    elif family == 3:
        chords = list(reversed(chords))
        chords = [tuple(f * .89090 for f in chord) for chord in chords]
    if june:
        bpm = {1: 84.0, 2: 76.0, 3: 92.0}[family]
        bar, xf = 4 * 60 / bpm, .45
    else:
        bar, xf = {1: (14.0, 4.0), 2: (10.5, 3.0), 3: (18.0, 5.5)}[family]
    pads = np.zeros(n, np.float32)
    i, pos = 0, 0.0
    while pos < seconds:
        seg_n = min(int((bar + xf) * SR), n - int(pos * SR))
        if seg_n <= 0: break
        seg = _pad(chords[i % len(chords)], seg_n, rng) * (.20 if june else 1.0)
        w = np.ones(seg_n, np.float32)
        f = min(int(xf * SR), seg_n // 2)
        w[:f] = np.sin(np.linspace(0, np.pi / 2, f)) ** 2
        w[-f:] = np.cos(np.linspace(0, np.pi / 2, f)) ** 2
        s0 = int(pos * SR)
        pads[s0:s0 + seg_n] += seg * w
        pos += bar; i += 1
    # 2. root drone (octave below chord roots)
    drone_gain = .035 if june else {1: 1.0, 2: .55, 3: 1.22}[family]
    root = {1: 55.0, 2: 65.41, 3: 43.65}[family]
    drone = drone_gain * (0.16 * np.sin(2 * np.pi * root * t) +
                          0.08 * np.sin(2 * np.pi * (root + .7) * t))
    # 3. airy noise swells (slow LFO; later re-shaped by VO pauses)
    swell_lfo = 0.5 + 0.5 * np.sin(2 * np.pi * {1: .021, 2: .033, 3: .014}[family] * t
                                      + {1: 1.2, 2: .2, 3: 2.4}[family])
    air = _swell_noise(n, seconds, rng) * swell_lfo * (0.025 if june else 0.14)
    v = pads + drone + air
    # 4. genre motion layer
    if june:
        v += _porch_score(n, seconds, rng, variant)
    elif genre == "dmt":  # slow pentatonic plucks, long tails
        scale = [523.25, 587.33, 659.26, 783.99, 880.0, 1046.5]
        spacing = {1: 4.5, 2: 3.25, 3: 6.2}[family]
        for st in np.arange(2.0, seconds - 3, spacing):
            f = scale[int(rng.integers(len(scale)))]
            i0 = int(st * SR); L = min(int(3.5 * SR), n - i0)
            tt = np.arange(L) / SR
            v[i0:i0 + L] += ({1: .05, 2: .065, 3: .032}[family]
                              * np.exp(-tt / ({1: 1.4, 2: 1.0, 3: 2.2}[family]))
                              * np.sin(2 * np.pi * f * tt))
    elif family == 2:   # glassy upper-register horizon, no heartbeat
        scale = [261.63, 329.63, 392.0, 493.88, 523.25]
        for st in np.arange(1.5, seconds - 1, 5.25):
            f = scale[int(rng.integers(len(scale)))]
            i0 = int(st * SR); L = min(int(2.8 * SR), n - i0)
            tt = np.arange(L) / SR
            bell = (np.sin(2 * np.pi * f * tt) + .32 * np.sin(2 * np.pi * f * 2.01 * tt))
            v[i0:i0 + L] += .038 * bell * np.exp(-tt / 1.25)
    else:               # sparse pulse; version 3 is slower and deeper
        beat = np.zeros(n, np.float32)
        spacing = 2.2 if family == 1 else 3.4
        beat_f = 52 if family == 1 else 38
        for st in np.arange(1.0, seconds - 1, spacing):
            i0 = int(st * SR); L = min(int((.35 if family == 1 else .7) * SR), n - i0)
            tt = np.arange(L) / SR
            beat[i0:i0 + L] += np.exp(-tt / (.09 if family == 1 else .24)) \
                                * np.sin(2 * np.pi * beat_f * tt)
        v += beat * (.10 if family == 1 else .075)
    decay = (.9 if june else (2.6 if genre == "dmt" else {1: 2.2, 2: 3.0, 3: 1.8}[family]))
    mix = (.12 if june else {1: .22, 2: .30, 3: .16}[family])
    v = _reverb(v, decay=decay, mix=mix, seed=3 + variant)
    # 5. VO adaptation: duck under speech, bloom in pauses, arc to the ending
    speech, onsets = (None, None)
    if vo:
        try: speech, onsets = vo_envelope(vo, seconds, n)
        except Exception: speech = None
    if speech is not None:
        if len(speech) < n: speech = np.pad(speech, (0, n - len(speech)), mode="edge")
        v *= 1.15 - 0.6 * speech[:n]
        v *= 1.0 + 0.3 * np.exp(-0.5 * ((t / seconds - 0.92) / 0.18) ** 2) * (t / seconds)
        for k, on in enumerate(onsets or []):
            if 2 < on < seconds - 2:
                f = ([392.0, 440.0, 493.88] if june else [329.63, 392.0, 440.0])[k % 3]
                i0 = int(on * SR); L = min(int(3 * SR), n - i0)
                tt = np.arange(L) / SR
                if june:
                    lick = _pluck(f, L / SR, rng, .9)[:L]
                    v[i0:i0 + L] += lick * .10
                else:
                    v[i0:i0 + L] += 0.05 * np.exp(-tt / 1.1) * np.sin(2 * np.pi * f * tt) \
                                    * np.minimum(1, tt / 0.12)
    # 6. stereo (Haas micro-delay) + fades + write
    env = np.minimum(1.0, np.minimum(t / 4.0, np.maximum(seconds - t, 0) / 4.0))
    v = np.clip(v * env * 0.9, -1, 1)
    d = int(0.011 * SR)
    left = v
    right = np.concatenate([np.zeros(d, np.float32), v[:-d]])
    st2 = (np.stack([left, right], 1) * 32000).astype(np.int16)
    w = wave.open(path, "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(st2.tobytes()); w.close()
    label = variant_label(variant, genre, profile)
    print(f"music: {seconds:.1f}s score ({label}, choice {variant}"
          f"{', VO-adaptive' if speech is not None else ''})")


if __name__ == "__main__":
    gen(sys.argv[1], float(sys.argv[2]),
        sys.argv[3] if len(sys.argv) > 3 else None,
        sys.argv[4] if len(sys.argv) > 4 else None,
        sys.argv[5] if len(sys.argv) > 5 else None,
        int(sys.argv[6]) if len(sys.argv) > 6 else 1)
