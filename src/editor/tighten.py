"""Auto-tighten talking shots: jump-cut out long pauses and stray fillers (嗯/啊/呃).

    ./venv/bin/python -m src.editor.tighten "<project>" [--min-gap 0.55] [--dry-run]

Whisper drops fillers from its text, and beach/wind noise defeats loudness-based silence
detection, so this uses the Silero VAD (whisper.cpp's `whisper-vad-speech-segments`) to find
where a human voice actually is:
  - a gap between speech segments >= min_gap  -> keep ~0.3 s of it, cut the rest
  - a short isolated voice blip that overlaps no subtitle -> a filler, cut it
Results go into each shot's `skip` list (source seconds). Nothing is destroyed: the review
page's toggle sets `skip_on: false` to restore a shot's pauses.
"""
import argparse
import os
import re
import subprocess
import tempfile

from . import edl as E

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
VAD_MODEL = os.path.join(REPO, "models", "ggml-silero-vad.bin")


def speech_segments(src, t0, t1):
    """Voice segments (absolute source seconds) inside [t0, t1] of a clip."""
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}",
                        "-i", src, "-vn", "-ac", "1", "-ar", "16000", f.name], check=True)
        out = subprocess.run(["whisper-vad-speech-segments", "-vm", VAD_MODEL, "-f", f.name,
                              "--vad-min-speech-duration-ms", "120", "--vad-min-silence-duration-ms", "200",
                              "--vad-speech-pad-ms", "40", "-np"], capture_output=True, text=True).stdout
    # the tool reports centiseconds
    return [(t0 + float(a) / 100, t0 + float(b) / 100)
            for a, b in re.findall(r"start = ([\d.]+), end = ([\d.]+)", out)]


def plan_skips(shot, segs, min_gap=0.55, keep_gap=0.3, filler_max=0.55):
    subs = [(s["t0"] - 0.1, s["t1"] + 0.1) for s in shot.get("subs", [])]
    covered = lambda a, b: any(a < y and b > x for x, y in subs)
    # fillers: short blips no subtitle accounts for, with air on both sides
    voice = []
    for i, (a, b) in enumerate(segs):
        prev_gap = a - segs[i - 1][1] if i else 1.0
        next_gap = segs[i + 1][0] - b if i + 1 < len(segs) else 1.0
        if b - a <= filler_max and not covered(a, b) and prev_gap >= 0.2 and next_gap >= 0.2:
            continue
        voice.append((a, b))
    skips = []
    for (a0, b0), (a1, b1) in zip(voice, voice[1:]):
        gap = a1 - b0
        if gap >= min_gap:
            skips.append([round(b0 + keep_gap * 0.6, 3), round(a1 - keep_gap * 0.4, 3)])
    return [s for s in skips if s[1] - s[0] >= 0.2 and shot["in"] < s[0] and s[1] < shot["out"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--min-gap", type=float, default=0.55)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    edl = E.load(a.project)
    saved = 0.0
    for shot in edl["shots"]:
        if shot.get("audio", "voice") != "voice" or not shot.get("subs"):
            continue
        segs = speech_segments(E.audio_path(edl, shot), shot["in"], shot["out"])
        skips = plan_skips(shot, segs, a.min_gap)
        cut = sum(b - x for x, b in skips)
        saved += cut if shot.get("enabled", True) else 0
        print(f"{shot['id']} {shot['clip']}: {len(skips)} cuts, -{cut:.1f}s")
        shot["skip"] = skips
        shot.setdefault("skip_on", True)
    print(f"total saved: {saved:.1f}s")
    if not a.dry_run:
        E.save(a.project, edl)


if __name__ == "__main__":
    main()
