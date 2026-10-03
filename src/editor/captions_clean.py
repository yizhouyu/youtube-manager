"""Proofread every raw clip transcript so nothing un-proofread reaches the creator.

    ./venv/bin/python -m src.editor.captions_clean "<project>"

Reads  edit/scan/srt/<clip>.srt      (raw whisper output)
Writes edit/scan/srt_clean/<clip>.srt (what the footage player shows)

Per cue: if the edit already has a proofread subtitle for that moment (EDL `subs`), use it;
otherwise convert to Simplified Chinese, apply the project glossary
(edit/glossary.json: {"heard": "correct", ...}; "" drops a line that was never said), and drop ASR hallucinations
(broadcaster sign-offs, "字幕by", lone fillers).
"""
import glob
import json
import os
import re
import sys

from . import edl as E

HALLUCINATION = re.compile(r"MING PAO|明镜|点点栏目|点赞|订阅|转发|打赏|字幕|by\s|Amara|中文字幕|谢谢观看")
NAV_PROMPT = re.compile(r"(?i)\b(your destination|destination is|you have arrived|in \d+ (feet|miles?|meters)|turn (left|right)|keep (left|right)|make a u-turn|rerouting|continue( straight| on)?|for (one|\d+|a half|half a) (mile|miles|feet|kilometers?)|then,? turn|at the roundabout|slight (left|right))\b|^on the (left|right)\.?$|^continue\.?$")  # GPS voice: never captioned
# interjection-only lines (哇 / 哎呀 / Oh no no no / Oh my God / There you go): never captioned (creator, 2026-10-03)
INTERJECTION = re.compile(r"(?i)^[\s,，.。!！?？~～…]*((oh|ooh|wow|whoa|hey|hi|hello|yeah|yay|oops|no|yes|okay|ok|god|my|there you go|come on|go|nice|cool|嗨|哈+|哎呀|哎呦|哎哟|哎|唉|哇塞?|呀|啊+|哦|噢|嗯|呃|额|好了你?|好|对+|来+|走+|天哪|我的天)[\s,，.。!！?？~～…]*)+$")
FILLER_ONLY = re.compile(r"^[\s,，.。!！?？~～]*(好|我|哦|哇|嗯|啊|呃|额|唉|哎|对|这么|那个|就是|然后)*[\s,，.。!！?？~～]*$")


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
            if HALLUCINATION.search(text) or FILLER_ONLY.match(text) or NAV_PROMPT.search(text):
                continue
            if not re.search(r"[\u4e00-\u9fff]", text):
                continue  # no Chinese = guides, strangers, background (the creator speaks Chinese); his own English
                # lines that matter are already in the EDL subs above (creator, 2026-10-03: 背景、其他人说的不要字幕)
            if INTERJECTION.match(text) or len(re.sub(r"[\W_]", "", text)) <= 3:
                continue  # stray 1-3 character fragments (嗨, 好了你, 拿哎呀) are fillers: never captioned (creator, 2026-10-03)
            for k, v in glossary.items():
                text = text.replace(k, v)
            if not text.strip(" ，,。"):
                continue  # glossary maps a known mishearing to "" = drop the line
            cues.append({"t0": c["t0"], "t1": c["t1"], "text": text})
        cues.sort(key=lambda x: x["t0"])
        with open(os.path.join(out_dir, clip + ".srt"), "w", encoding="utf-8") as f:
            f.write(E.to_srt(cues))
        n += 1
    return n


if __name__ == "__main__":
    n = clean_project(sys.argv[1])
    if "--mark-proofread" in sys.argv:
        # the agent has read every transcript and filled glossary.json: captions may now be shown
        open(os.path.join(E.edit_dir(sys.argv[1]), "scan", ".proofread"), "w").close()
    print(n, "clips cleaned" + (" (marked proofread)" if "--mark-proofread" in sys.argv else ""))
