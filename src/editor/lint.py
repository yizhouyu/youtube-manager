"""Pre-render checks for an EDL: catch trims that silently break the cut.

    python -m src.editor.lint "<project>"      # prints problems; exit 1 if any error

Errors (render refuses): an enabled shot with out <= in (the renderer used to drop it silently).
Warnings: a caption cut by the shot's out/in point (mid-word), a caption under 0.7 s on screen,
a clip shot under 0.5 s, B-roll that runs past its shot, and the same source footage used twice.
Audio/pacing warnings (research 2026-10-01): a voiceover line over 4 汉字 per second of its picture
window, a voiceover line starting < 0.3 s after a cut, more than 60 s of talk without a
music-only / natural-sound break, and more than 3 sound effects in any minute.
"""
import csv
import os
import re
import subprocess
import sys

from . import edl as E

VO_MAX_CPS = 4.0           # 汉字 per second of a voiceover line's picture window (Yunxi at -5% speaks ~4.7-5/s)
VO_MIN_AFTER_CUT = 0.3     # s: let the new picture register before narration starts
TALK_MAX_S = 60.0          # s of talk (speech captions + narration) before a break is due
TALK_BREAK_S = 4.0         # s without speech that counts as a music-only / natural-sound break
SFX_MAX_PER_MIN = 3
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
    warns += audio_pacing(edl)
    used.sort()
    for i in range(1, len(used)):
        c0, a0, b0, w0 = used[i - 1]
        c1, a1, b1, w1 = used[i]
        if c0 == c1 and min(b0, b1) - a1 > 1.0:
            warns.append(f"{c0} {a1:.1f}–{min(b0, b1):.1f} s used twice ({w0} and {w1}; fine for a cold-open teaser)")
    return errors, warns


def count_hanzi(text):
    """Spoken length in 汉字: CJK characters, each Latin word as ~2, each digit as 1."""
    return (len(re.findall(r"[\u3400-\u9fff]", text)) + 2 * len(re.findall(r"[A-Za-z]+", text))
            + len(re.findall(r"[0-9]", text)))


def vo_text(edl, entry):
    """The words of a voiceover line: the entry's `text`, else its row in edit/tts/script.tsv (id or
    file = the file's stem), else its row in edit/tts/SCRIPT.md (a | File | … | Text | … | table)."""
    if entry.get("text"):
        return entry["text"]
    edit = E.edit_dir(edl["project"])
    stem = os.path.splitext(os.path.basename(entry.get("file", "")))[0]
    base = os.path.basename(entry.get("file", ""))
    tsv = os.path.join(edit, "tts", "script.tsv")
    if os.path.exists(tsv):
        with open(tsv, encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter="\t"))
        head = [c.strip().lower() for c in rows[0]] if rows else []
        col = head.index("tts_text") if "tts_text" in head else 1
        for r in rows:
            if r and (r[0].strip() == stem or os.path.splitext(os.path.basename(r[0].strip()))[0] == stem) and len(r) > col:
                return r[col]
    md = os.path.join(edit, "tts", "SCRIPT.md")
    if os.path.exists(md):
        col = None
        with open(md, encoding="utf-8") as f:
            for line in f:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                hdr = [c for c in cells if c.lower() in ("text", "line", "tts_text", "台词")]
                if line.lstrip().startswith("|") and hdr:
                    col = cells.index(hdr[0])
                elif col is not None and line.lstrip().startswith("|") and base and base in cells[0] and len(cells) > col:
                    return cells[col]
    return None


def _dur(path):
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30)
        return float(p.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _ts(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def audio_pacing(edl):
    """Warnings about narration density/placement, talk without a break, and sfx density."""
    warns = []
    if not edl.get("shots"):
        return warns
    rows, total = E.timeline(edl)
    if not rows:
        return warns
    order = [s["id"] for s in edl["shots"]]
    starts = {s["id"]: st for s, st in rows}
    cuts = sorted(st for _s, st in rows if st > 0)

    def first_start(sid):
        if sid not in order:
            return None
        return next((starts[x] for x in order[order.index(sid):] if x in starts), None)

    speech = sorted((x["t0"], x["t1"]) for x in E.timeline_subs(edl) if x["kind"] == "speech")
    music_cuts = sorted(t for t in (first_start(m.get("start")) for m in edl.get("music", [])) if t)
    vo = []
    for v in edl.get("voiceover", []):
        t0 = first_start(v.get("start"))
        if t0 is None:
            continue
        t0 += float(v.get("at", 0.0))
        path = os.path.join(E.edit_dir(edl["project"]), v.get("file", ""))
        vo.append((t0, _dur(path) if os.path.exists(path) else 0.0, v))
    vo.sort(key=lambda x: x[0])
    for i, (t0, d, v) in enumerate(vo):
        name = v.get("file", "?")
        prev_cut = max([c for c in cuts if c <= t0 + 1e-6], default=None)
        if prev_cut is not None and t0 - prev_cut < VO_MIN_AFTER_CUT - 1e-3 and not v.get("jcut"):
            warns.append(f"voiceover {name} at {_ts(t0)} starts {t0 - prev_cut:.2f} s after a cut "
                         f"(< {VO_MIN_AFTER_CUT} s: let the picture register, or mark \"jcut\": true)")
        text = vo_text(edl, v)
        if not text:
            continue
        # its window: until the next narration line, music section, or on-camera speech after it
        ends = [total] + [x[0] for x in vo[i + 1:i + 2]] + [m for m in music_cuts if m > t0 + 0.5] + \
               [a for a, _b in speech if a >= t0 + d - 0.05]
        window = min(ends) - t0
        n = count_hanzi(text)
        if window > 0 and n / window > VO_MAX_CPS:
            warns.append(f"voiceover {name} at {_ts(t0)}: {n} 字 in a {window:.1f} s window = {n / window:.1f}/s "
                         f"(> {VO_MAX_CPS:g}/s: shorten the line or give it a longer shot)")
    # talk without a break: merge speech captions + narration whose gaps are shorter than a break
    talk = sorted(speech + [(t0, t0 + d) for t0, d, _v in vo if d > 0])
    run = None
    for a, b in talk:
        if run and a - run[1] < TALK_BREAK_S:
            run[1] = max(run[1], b)
            continue
        if run and run[1] - run[0] > TALK_MAX_S:
            warns.append(f"talk runs {run[1] - run[0]:.0f} s without a break ({_ts(run[0])}–{_ts(run[1])}): "
                         f"give it a music-only / natural-sound beat (>= {TALK_BREAK_S:g} s, ideally 8–15 s)")
        run = [a, b]
    if run and run[1] - run[0] > TALK_MAX_S:
        warns.append(f"talk runs {run[1] - run[0]:.0f} s without a break ({_ts(run[0])}–{_ts(run[1])}): "
                     f"give it a music-only / natural-sound beat (>= {TALK_BREAK_S:g} s, ideally 8–15 s)")
    # sfx density (narration lines used as sfx don't count)
    fx = sorted(st + float(f.get("at", 0.0)) for s, st in rows for f in s.get("sfx", [])
                if not (f.get("tts", f.get("file", "").replace("\\", "/").startswith("tts/"))))
    i, last_warned = 0, -1e9
    for j, t in enumerate(fx):
        while fx[i] < t - 60.0:
            i += 1
        if j - i + 1 > SFX_MAX_PER_MIN and fx[i] > last_warned:
            warns.append(f"{j - i + 1} sound effects within a minute ({_ts(fx[i])}–{_ts(t)}): "
                         f"more than {SFX_MAX_PER_MIN}/min reads cheap — keep the motivated ones")
            last_warned = t
    return warns


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
