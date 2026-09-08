#!/usr/bin/env python3
"""
Turn a folder of raw field/library recordings into the city-noise pool.

Two jobs:

1. MEASURE. Every clip gets an `intensity` in 0..1 derived from the audio
   itself rather than from its filename, so the pool can match quiet recordings
   to sparse ground and dense ones to dense ground. Three measurements go into
   it, because loudness alone is a poor description of how present a city
   sounds:

     loudness    RMS in dBFS. The obvious one.
     steadiness  how little the short-term level varies. A continuous wash of
                 traffic is dense; footsteps with gaps between them is sparse,
                 even at the same average level.
     brightness  spectral centroid. Distant city is low rumble; close city has
                 high-frequency detail that doesn't survive the trip.

2. CONVERT. Originals here are 96 kHz/24-bit stereo and over a gigabyte, which
   is hopeless in a browser. Each is downmixed to mono, halved to 48 kHz,
   trimmed to a window from the middle (avoiding any fade at the head or tail)
   and encoded to AAC. Mono is not a compromise: the grain engine spreads
   fragments across the stereo field itself, and a stereo source fights that.

Usage:  python3 prepare_audio.py <source-folder> [--seconds 60]
"""

import argparse, json, math, subprocess, sys, wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
OUT_AUDIO = HERE / "audio"
OUT_DATA = HERE / "data"

TARGET_SR = 48000
BITRATE = 96000


# --- reading ---------------------------------------------------------------

def read_wav(path, max_seconds=None):
    """Return (mono float32 in -1..1, samplerate). Handles 16/24/32-bit PCM."""
    with wave.open(str(path)) as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        n = w.getnframes()
        if max_seconds:
            n = min(n, int(sr * max_seconds))
        raw = w.readframes(n)

    if sw == 2:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 3:
        # 24-bit little-endian packed: widen to int32 via the high byte
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.uint32)
        v = (b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)).astype(np.int32)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        a = v.astype(np.float32) / 8388608.0
    elif sw == 4:
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"{path.name}: unsupported sample width {sw}")

    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


# --- measurement -----------------------------------------------------------

def measure(mono, sr):
    win = int(sr * 0.05)                       # 50 ms frames
    frames = mono[: len(mono) // win * win].reshape(-1, win)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)

    loud = 20 * math.log10(float(np.sqrt((mono ** 2).mean()) + 1e-12))

    # steadiness: spread of the level distribution in dB. A wide spread means
    # gaps and events; a narrow one means a continuous bed.
    db = 20 * np.log10(rms + 1e-12)
    spread = float(np.percentile(db, 95) - np.percentile(db, 20))

    # brightness: spectral centroid over a decimated slice, in Hz
    step = max(1, sr // 16000)
    d = mono[::step]
    seg = int(len(d) // 32)
    cents = []
    for i in range(0, min(32 * seg, len(d) - seg), seg):
        chunk = d[i:i + seg] * np.hanning(seg)
        mag = np.abs(np.fft.rfft(chunk))
        freqs = np.fft.rfftfreq(seg, 1.0 / (sr / step))
        s = mag.sum()
        if s > 0:
            cents.append(float((freqs * mag).sum() / s))
    centroid = float(np.median(cents)) if cents else 0.0

    return {"loudness": round(loud, 2), "spread": round(spread, 2),
            "centroid": round(centroid, 1)}


# What the recording is called turns out to be a better description of how
# present it is than what it measures. Library recordings arrive already
# level-matched by the publisher, so dBFS describes the master, not the street:
# measured on its own this set ranks "Quiet, Night" above "Dense City Centre
# Crowd", which is plainly wrong. Meanwhile the tags are written by whoever
# stood there holding the mic.
#
# So descriptors lead and measurements only separate clips the words rank
# equally. Adjust these weights, or just edit `intensity` in data/pool.json by
# hand — the pool reads the number, not how it was arrived at.
WORDS = {
    "dense": 2.0, "crowd": 2.0, "busy": 2.0, "traffic": 1.5, "lively": 1.5,
    "walla": 1.0, "heavy": 1.0, "pedestrians": 0.5, "people": 0.5,
    "passing": 0.5, "pass": 0.5,
    "quiet": -2.5, "far": -2.0, "distant": -1.5, "rumble": -1.5,
    "night": -1.5, "skyline": -1.0, "hum": -0.5,
}


def normalise(clips):
    """One 0..1 intensity per clip: descriptors first, measurements as tiebreak."""
    def scale(v):
        v = np.asarray(v, dtype=np.float64)
        lo, hi = v.min(), v.max()
        return np.zeros_like(v) if hi - lo < 1e-9 else (v - lo) / (hi - lo)

    words = scale([sum(WORDS.get(w, 0.0) for w in c["label"].split("-"))
                   for c in clips])
    loud = scale([c["m"]["loudness"] for c in clips])
    bright = scale([c["m"]["centroid"] for c in clips])

    # brightness is the one measurement that survives level-matching: distant
    # city loses its high end to the air, close city keeps it
    blend = 0.72 * words + 0.16 * bright + 0.12 * loud
    blend = scale(blend)
    for c, v in zip(clips, blend):
        c["intensity"] = round(float(v), 3)


# --- conversion ------------------------------------------------------------

def slug(name):
    keep = []
    for part in name.replace("_", " ").replace(",", " ").split():
        p = "".join(ch for ch in part.lower() if ch.isalnum())
        if p and p not in ("es", "ambience", "epidemic", "sound", "urban"):
            keep.append(p)
    return "-".join(keep)[:64].strip("-") or "clip"


def convert(mono, sr, seconds, dest):
    if mono is None:                     # already encoded, only remeasuring
        return dest.stat().st_size
    # take the window from the middle: heads and tails of library recordings
    # tend to carry fades, and a fade granulates into a swell that reads as an
    # event rather than as texture
    want = int(sr * seconds)
    if len(mono) > want:
        start = (len(mono) - want) // 2
        mono = mono[start:start + want]

    if sr % TARGET_SR == 0 and sr != TARGET_SR:
        f = sr // TARGET_SR
        mono = mono[: len(mono) // f * f].reshape(-1, f).mean(axis=1)
        sr = TARGET_SR

    # gentle edge fades so the loop boundary can't click when a grain
    # happens to straddle it
    edge = min(int(sr * 0.05), len(mono) // 4)
    if edge > 0:
        ramp = np.linspace(0, 1, edge, dtype=np.float32)
        mono[:edge] *= ramp
        mono[-edge:] *= ramp[::-1]

    peak = float(np.abs(mono).max())
    if peak > 0.999:                    # only touch it if it would clip
        mono = mono / peak * 0.999

    tmp = dest.with_suffix(".tmp.wav")
    with wave.open(str(tmp), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((mono * 32767).astype("<i2").tobytes())

    subprocess.run(
        ["afconvert", "-f", "m4af", "-d", f"aac@{sr}", "-b", str(BITRATE),
         "-q", "127", str(tmp), str(dest)],
        check=True, capture_output=True)
    tmp.unlink()
    return dest.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--force", action="store_true",
                    help="re-encode even if the output already exists")
    args = ap.parse_args()

    src = Path(args.source).expanduser()
    files = sorted(p for p in src.iterdir()
                   if p.suffix.lower() == ".wav" and not p.name.startswith("."))
    if not files:
        sys.exit(f"no .wav files in {src}")

    OUT_AUDIO.mkdir(exist_ok=True)
    OUT_DATA.mkdir(exist_ok=True)

    # Two passes on purpose. These decode to well over a gigabyte of float32
    # in total, so nothing holds audio between files — pass one measures and
    # discards, pass two re-reads only what it needs to convert.
    print(f"{len(files)} files\n")
    clips = []
    for p in files:
        mono, sr = read_wav(p)
        m = measure(mono, sr)
        clips.append({"src_path": p, "sr": sr, "m": m,
                      "label": slug(p.stem), "duration": len(mono) / sr})
        print(f"  measured  {m['loudness']:7.2f} dBFS  "
              f"spread {m['spread']:5.1f}  centroid {m['centroid']:7.0f} Hz  "
              f"{p.stem[:52]}")
        del mono

    normalise(clips)
    clips.sort(key=lambda c: c["intensity"])

    print(f"\nintensity ranking (quiet/sparse -> loud/dense):\n")
    out = []
    total = 0
    for c in clips:
        name = f"place_{c['label']}.m4a"
        dest = OUT_AUDIO / name
        if dest.exists() and not args.force:
            size = convert(None, None, args.seconds, dest)
        else:
            # only decode the window we're keeping, plus a little slack for
            # the centre-trim to have something to choose from
            mono, sr = read_wav(c["src_path"], max_seconds=args.seconds * 3)
            size = convert(mono, sr, args.seconds, dest)
            del mono
        total += size
        bar = "#" * int(c["intensity"] * 34)
        print(f"  {c['intensity']:.3f} {bar:<34} {c['label'][:44]}")
        out.append({
            "id": Path(name).stem,
            "kind": "place",
            "label": c["label"].replace("-", " "),
            "src": f"audio/{name}",
            "intensity": c["intensity"],
            "seconds": round(min(c["duration"], args.seconds), 1),
            "measured": c["m"],
        })

    (OUT_DATA / "pool.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote data/pool.json and {len(out)} files "
          f"({total/1e6:.1f} MB, was {sum(p.stat().st_size for p in files)/1e6:.0f} MB)")


if __name__ == "__main__":
    main()
