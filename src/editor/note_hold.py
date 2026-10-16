"""Stretch yellow notes that are not on screen long enough to read (creator, 109 #10: 「黄色的字幕停留可以长一点」).

    python -m src.editor.note_hold "<project>" [--dry]

For each note shorter than lint's reading time, move its end later (then its start earlier) inside the same
shot, stopping at the shot edges and at the next/previous caption in the same slot. Prints what still falls short
(the shot itself is too short: carry the note into the next shot by hand or trim the text).
"""
import json
import shutil
import sys
import time

from . import edl as E
from .lint import NOTE_MIN_S, NOTE_READ_CPS, count_hanzi


def _shown(s, x):
    """On-screen seconds of sub `x` in shot `s` (skips removed)."""
    t = {**s, "subs": [x]}
    v = E.shot_subs(t)
    return v[0]["t1"] - v[0]["t0"] if v else 0.0


def fix(s):
    out, short = [], []
    subs = s.get("subs") or []
    for x in subs:
        if x.get("kind") != "note":
            continue
        need = max(NOTE_MIN_S, count_hanzi(x["text"]) / NOTE_READ_CPS)
        if _shown(s, x) >= need - 0.1:
            continue
        top = x.get("pos") == "top"
        same = [y for y in subs if y is not x and (y.get("pos") == "top") == top]
        hi = min([s["out"]] + [y["t0"] for y in same if y["t0"] >= x["t1"] - 0.01])
        lo = max([s["in"]] + [y["t1"] for y in same if y["t1"] <= x["t0"] + 0.01])
        if top and s.get("tag") and s.get("tag_pos", "tl") in ("tl", "tr"):   # never slide under the place tag (109, 1:23)
            lo = max(lo, min(x["t0"], s.get("tag_at", s["in"]) + s.get("tag_dur", 3.0)))
        old = (x["t0"], x["t1"])
        while _shown(s, x) < need and x["t1"] < hi - 0.06:   # 0.06 > rounding slack, or this never ends
            x["t1"] = round(min(hi - 0.05, x["t1"] + 0.1), 2)
        while _shown(s, x) < need and x["t0"] > lo + 0.06:
            x["t0"] = round(max(lo + 0.05, x["t0"] - 0.1), 2)
        if (x["t0"], x["t1"]) != old:
            out.append(f"{s['id']}: 「{x['text'][:12]}…」 {old[0]}–{old[1]} → {x['t0']}–{x['t1']} ({_shown(s, x):.1f}/{need:.1f} s)")
        if _shown(s, x) < need - 0.1:
            short.append(f"{s['id']}: 「{x['text'][:12]}…」 still {_shown(s, x):.1f}/{need:.1f} s (shot too short)")
    return out, short


def main(project, dry=False):
    edl = E.load(project)
    done, short = [], []
    for s in edl.get("shots", []):
        if s.get("enabled", True) and s.get("clip"):
            a, b = fix(s)
            done += a
            short += b
    print("\n".join(done + short) or "all notes long enough")
    if done and not dry:
        p = E.edl_path(project)
        shutil.copy(p, p.replace("edl.json", f"history/edl.{time.strftime('%Y%m%d-%H%M%S')}.json"))
        E.save(project, edl)


if __name__ == "__main__":
    main(sys.argv[1], "--dry" in sys.argv)
