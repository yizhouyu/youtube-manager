"""Proofread every raw clip transcript so nothing un-proofread reaches the creator.

    ./venv/bin/python -m src.editor.captions_clean "<project>"

Reads  edit/scan/srt/<clip>.srt      (raw whisper output)
Writes edit/scan/srt_clean/<clip>.srt (what the footage player shows)

Per cue: if the edit already has a proofread subtitle for that moment (EDL `subs`), use it;
otherwise convert to Simplified Chinese, apply the project glossary
(edit/glossary.json: {"heard": "correct", ...}), and drop ASR hallucinations
(broadcaster sign-offs, "字幕by", lone fillers).
"""
import glob
import json
import os
import re
import sys

from . import edl as E

HALLUCINATION = re.compile(r"MING PAO|明镜|点点栏目|点赞|订阅|转发|打赏|字幕|by\s|Amara|中文字幕|谢谢观看")
FILLER_ONLY = re.compile(r"^[\s,，.。!！?？~～]*(好|我|哦|哇|嗯|啊|呃|额|唉|哎|对)*[\s,，.。!！?？~～]*$")


def _parse(path):
    txt = open(path, encoding="utf-8").read().replace("\r", "")
    out = []
    for block in txt.strip().split("\n\n"):
        lines = block.split("\n")
        m = [l for l in lines if "-->" in l]
        if not m:
            continue
        a, b = [x.strip() for x in m[0].split("-->")]
        ts = lambda s: sum(float(x) * y for x, y in zip(s.replace(",", ".").split(":"), (3600, 60, 1)))
        text = " ".join(lines[lines.index(m[0]) + 1:]).strip()
        out.append({"t0": ts(a), "t1": ts(b), "text": text})
    return out


def clean_project(project):
    try:
        from opencc import OpenCC
        t2s = OpenCC("t2s").convert
    except ImportError:
        t2s = lambda s: s
    edit = E.edit_dir(project)
    gpath = os.path.join(edit, "glossary.json")
    glossary = json.load(open(gpath, encoding="utf-8")) if os.path.exists(gpath) else {}
    proofread = {}
    if os.path.exists(E.edl_path(project)):
        for s in E.load(project)["shots"]:
            proofread.setdefault(s["clip"], []).extend(
                x for x in s.get("subs", []) if x.get("kind", "speech") == "speech")
    out_dir = os.path.join(edit, "scan", "srt_clean")
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for path in sorted(glob.glob(os.path.join(edit, "scan", "srt", "*.srt"))):
        clip = os.path.basename(path)[:-4]
        subs = proofread.get(clip, [])
        cues = []
        for c in _parse(path):
            # prefer the edit's proofread lines that overlap this raw cue
            hits = [s for s in subs if min(s["t1"], c["t1"]) - max(s["t0"], c["t0"]) > 0.3 * (c["t1"] - c["t0"])]
            if hits:
                for s in hits:
                    if not any(x["t0"] == s["t0"] for x in cues):
                        cues.append({"t0": s["t0"], "t1": s["t1"], "text": s["text"]})
                continue
            text = t2s(c["text"])
            if HALLUCINATION.search(text) or FILLER_ONLY.match(text):
                continue
            for k, v in glossary.items():
                text = text.replace(k, v)
            cues.append({"t0": c["t0"], "t1": c["t1"], "text": text})
        cues.sort(key=lambda x: x["t0"])
        with open(os.path.join(out_dir, clip + ".srt"), "w", encoding="utf-8") as f:
            f.write(E.to_srt(cues))
        n += 1
    return n


if __name__ == "__main__":
    print(clean_project(sys.argv[1]), "clips proofread")
