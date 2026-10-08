"""Auto-tighten talking shots: jump-cut out long pauses and stray fillers (嗯/啊/呃).

    ./venv/bin/python -m src.editor.tighten "<project>" [--min-gap 0.55] [--dry-run]

Whisper drops fillers from its text, and beach/wind noise defeats loudness-based silence
detection, so this uses the Silero VAD (whisper.cpp's `whisper-vad-speech-segments`) to find
where a human voice actually is:
  - a gap between speech segments >= min_gap  -> keep ~0.3 s of it, cut the rest
  - a short isolated voice blip that overlaps no subtitle -> a filler, cut it
Results go into each shot's `skip` list (source seconds). Nothing is destroyed: the review
page's toggle sets `skip_on: false` to restore a shot's pauses.

Hand-made skips (retakes, stumbles) are KEPT: tighten records its own spans in `skip_auto`, so on
every run the manual spans are `skip` minus `skip_auto` (on an EDL tighten never touched, all of
`skip` counts as manual). Auto spans never overlap a manual one and never swallow a caption's first or
last word. `--replace` restores the old behaviour (auto spans only). Shots with `"tighten": false`
are left alone (use it where the pause is the content: pans, animals, dusk).
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


def _overlaps(a, b):
    return a[0] < b[1] and a[1] > b[0]


def merge_skips(shot, auto, replace=False):
    """Combine fresh auto spans with the shot's hand-made skips. Returns (skip, skip_auto)."""
    old = [list(x) for x in shot.get("skip", [])]
    prev_auto = [list(x) for x in shot.get("skip_auto", [])]
    manual = [] if replace else [x for x in old if x not in prev_auto]
    keep = []
    for sp in (list(x) for x in auto):
        if any(_overlaps(sp, m) for m in manual):
            continue
        for c in shot.get("subs", []):          # never eat a caption's first or last word
            if sp[0] < c["t0"] + 0.15 < sp[1]:
                sp[1] = round(c["t0"] - 0.08, 3)
            elif sp[0] < c["t1"] - 0.15 < sp[1]:
                sp[0] = round(c["t1"] + 0.05, 3)
        if sp[1] - sp[0] >= 0.12:
            keep.append(sp)
    return sorted(manual + keep), keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--min-gap", type=float, default=0.55)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true", help="drop hand-made skips (old behaviour)")
    a = ap.parse_args()
    edl = E.load(a.project)
    saved = 0.0
    for shot in edl["shots"]:
        if shot.get("audio", "voice") != "voice" or not shot.get("subs") or shot.get("tighten") is False:
            continue
        segs = speech_segments(E.audio_path(edl, shot), shot["in"], shot["out"])
        skips, auto = merge_skips(shot, plan_skips(shot, segs, a.min_gap), a.replace)
        cut = sum(b - x for x, b in skips)
        saved += cut if shot.get("enabled", True) else 0
        n_man = len(skips) - len(auto)
        print(f"{shot['id']} {shot['clip']}: {len(auto)} auto + {n_man} manual cuts, -{cut:.1f}s"
              + ("  (has pip: check its times)" if shot.get("pip") and auto != shot.get("skip_auto", []) else ""))
        shot["skip"], shot["skip_auto"] = skips, auto
        shot.setdefault("skip_on", True)
    print(f"total saved: {saved:.1f}s")
    if not a.dry_run:
        E.save(a.project, edl)


if __name__ == "__main__":
    main()
