"""Pre-render checks for an EDL: catch trims that silently break the cut.

    python -m src.editor.lint "<project>"      # prints problems; exit 1 if any error

Errors (render refuses): an enabled shot with out <= in (the renderer used to drop it silently).
Warnings: a caption cut by the shot's out/in point (mid-word), a caption under 0.7 s on screen,
a clip shot under 0.5 s, B-roll that runs past its shot, and the same source footage used twice.
"""
import sys

from . import edl as E

MIN_CAPTION_S = 0.7
MIN_SHOT_S = 0.5
EDGE_SLACK = 0.15


def check(edl):
    errors, warns = [], []
    used = []  # (clip, a, b, where)
    for s in edl.get("shots", []):
        if not s.get("enabled", True):
            continue
        sid = s.get("id", "?")
        if not s.get("clip"):  # cards and title shots
            continue
        if s["out"] <= s["in"]:
            errors.append(f"{sid}: out {s['out']} <= in {s['in']} — shot would vanish")
            continue
        dur = E.shot_dur(s)
        if dur < MIN_SHOT_S:
            warns.append(f"{sid}: only {dur:.2f} s long (flash cut)")
        for x in s.get("subs", []):
            if x.get("kind") == "note" or x["t1"] <= s["in"] or x["t0"] >= s["out"]:
                continue
            if x["t1"] > s["out"] + EDGE_SLACK:
                warns.append(f"{sid}: out {s['out']} cuts caption 「{x['text']}」 (ends {x['t1']})")
            if x["t0"] < s["in"] - EDGE_SLACK:
                warns.append(f"{sid}: in {s['in']} cuts caption 「{x['text']}」 (starts {x['t0']})")
        for x in E.shot_subs(s):
            if x["kind"] != "note" and x["t1"] - x["t0"] < MIN_CAPTION_S:
                warns.append(f"{sid}: caption 「{x['text']}」 on screen only {x['t1'] - x['t0']:.2f} s")
        for a, b in E.kept_ranges(s):
            used.append((s["clip"], a, b, sid))
        for b in s.get("broll") or []:
            if b.get("at", 0) + b.get("dur", 0) > (s["out"] - s["in"]) + EDGE_SLACK:
                warns.append(f"{sid}: B-roll {b.get('clip')} runs past the end of the shot")
            a0 = float(b.get("in", 0))
            used.append((b.get("clip"), a0, a0 + float(b.get("dur", 0)), f"{sid} B-roll"))
    ids = [s.get("id") for s in edl.get("shots", [])]
    for v in edl.get("voiceover", []):
        if v.get("start") not in ids:
            errors.append(f"voiceover {v.get('file')}: start shot {v.get('start')!r} not in the EDL")
    used.sort()
    for i in range(1, len(used)):
        c0, a0, b0, w0 = used[i - 1]
        c1, a1, b1, w1 = used[i]
        if c0 == c1 and min(b0, b1) - a1 > 1.0:
            warns.append(f"{c0} {a1:.1f}–{min(b0, b1):.1f} s used twice ({w0} and {w1}; fine for a cold-open teaser)")
    return errors, warns


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: python -m src.editor.lint "<project>"')
    errors, warns = check(E.load(sys.argv[1]))
    for m in errors:
        print("ERROR  " + m)
    for m in warns:
        print("warn   " + m)
    if not errors and not warns:
        print("EDL lint: clean")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
