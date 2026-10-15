"""One line per raw clip: what was said, where it lands in the cut, and what was left out. No viewing needed.

    ./venv/bin/python -m src.editor.clip_index "<project>"

Writes <project>/02 - Export/edit/scan/clip_index.md from scan/meta.json + edl.json + scan/srt_clean (or srt).
The reviewer reads this before 审片 to see unused footage at a glance; the rough-cutter adds reasons for
unused clips in the last column (the generator keeps existing reasons when re-run).
"""
import json
import os
import re
import sys

from . import edl as E


def _srt(path):
    if not os.path.exists(path):
        return []
    rows = []
    for blk in re.split(r"\n\s*\n", open(path, encoding="utf-8").read().strip()):
        ls = blk.strip().split("\n")
        if len(ls) >= 3 and "-->" in ls[1]:
            a, b = [sum(float(x) * m for x, m in zip(t.replace(",", ".").split(":"), (3600, 60, 1))) for t in ls[1].split("-->")]
            rows.append((a, b, " ".join(ls[2:]).strip()))
    return rows


def _mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def main(project):
    ed = E.edit_dir(project)
    meta = json.load(open(os.path.join(ed, "scan", "meta.json")))
    edl = E.load(project)
    rows, total = E.timeline(edl)
    used = {}
    for s, t0 in rows:
        used.setdefault(s["clip"], []).append((s, t0))
    out = os.path.join(ed, "scan", "clip_index.md")
    old = {}  # keep reasons the rough-cutter already wrote
    if os.path.exists(out):
        for l in open(out, encoding="utf-8"):
            c = l.split("|")
            if len(c) >= 7 and c[2].strip() in meta:
                old[c[2].strip()] = c[6].strip()
    L = [f"# Clip index — {os.path.basename(E.project_dir(project))}", "",
         f"Cut {_mmss(total)}. 'Used' = source range → 成片 time. 'Left out' = transcript lines not in the cut.", "",
         "| # | clip | dur | used | left out (speech) | reason / content |", "|---|---|---|---|---|---|"]
    for i, (clip, m) in enumerate(meta.items(), 1):
        srtp = next((p for p in (os.path.join(ed, "scan", d, clip + ".srt") for d in ("srt_clean", "srt")) if os.path.exists(p)), "")
        lines = _srt(srtp)
        kept = []
        u = []
        for s, t0 in used.get(clip, []):
            kept += E.kept_ranges(s)
            u.append(f"{s['id']} {s['in']:.0f}–{s['out']:.0f}s→{_mmss(t0)}")
        left = [x for a, b, x in lines if not any(a < kb - 0.2 and b > ka + 0.2 for ka, kb in kept)]
        lo = "；".join(left)
        lo = lo[:60] + "…" if len(lo) > 60 else lo
        if lines and m["dur"] - lines[-1][1] > 4:  # ASR often stops early under music; 105 #22 lost a line this way
            lo = (lo + " " if lo else "") + f"⚠ 转写止于 {lines[-1][1]:.0f}s/{m['dur']:.0f}s"
        L.append(f"| {i} | {clip} | {m['dur']:.0f}s | {', '.join(u) or '**未用**'} | {lo} | {old.get(clip, '')} |")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(out, f"{len(meta)} clips, {sum(1 for c in meta if c not in used)} unused")


if __name__ == "__main__":
    main(sys.argv[1])
