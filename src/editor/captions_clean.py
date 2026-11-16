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


def _context_terms(edit):
    """Proper nouns from edit/asr_context.txt (the --context string handed to the ASR)."""
    try:
        txt = open(os.path.join(edit, "asr_context.txt"), encoding="utf-8").read()
    except OSError:
        return []
    return [t.strip() for t in re.split(r"[,，、\n]", txt) if len(t.strip()) >= 2]


def _leaked(text, terms):
    """Share of a line's letters that are context terms: on a clip with no speech the ASR can read its own
    context string back as a transcript (128's 0495: 「天地万圣节泡泡玛特Pop Mart…」, creator 11/15: 字幕错位)."""
    core = re.sub(r"[\W_]", "", text)
    if not core:
        return 0.0
    left = text
    for t in sorted(terms, key=len, reverse=True):
        left = left.replace(t, "")
    return 1 - len(re.sub(r"[\W_]", "", left)) / len(core)


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
    terms = _context_terms(edit)
    for path in sorted(glob.glob(os.path.join(edit, "scan", "srt", "*.srt"))):
        clip = os.path.basename(path)[:-4]
        subs = proofread.get(clip, [])
        cues = []
        raw = _parse(path)
        # the whole clip reads back the context string (≥ 4 distinct terms, mostly nothing else): no speech at all
        joined = "".join(c["text"] for c in raw)
        if terms and sum(t in joined for t in terms) >= 4 and _leaked(joined, terms) > 0.6:
            raw = [c for c in raw if _leaked(c["text"], terms) < 0.5]
        for c in raw:
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
            text = re.sub(r"^[嗯啊呃额哦唉]+[，,\s]*|[，,\s]*[嗯啊呃额哦唉]+$", "", text).strip()  # filler sounds at the edges
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
        # the ASR cuts lines at ~16 characters, sometimes inside a word (「…跟上面的这 / 个动画同步」, creator 11/15:
        # 「“这个”不要分在两行」): join a cue with the next when they touch and the first doesn't end a clause
        merged = []
        for c in cues:
            p = merged[-1] if merged else None
            if (p and c["t0"] - p["t1"] < 0.15 and p["text"][-1:] not in "，。！？、；：,.!?;:…"
                    and len(p["text"]) + len(c["text"]) <= 26):
                p["t1"], p["text"] = c["t1"], p["text"] + c["text"]
            else:
                merged.append(dict(c))
        cues = merged
        with open(os.path.join(out_dir, clip + ".srt"), "w", encoding="utf-8") as f:
            f.write(E.to_srt(cues))
        n += 1
    return n


if __name__ == "__main__":
    # `--help` once became a project name and left a "~/Desktop/--help" folder (2026-10-20)
    if len(sys.argv) < 2 or sys.argv[1].startswith("-") or not os.path.isdir(E.project_dir(sys.argv[1])):
        sys.exit("usage: python -m src.editor.captions_clean <project> [--mark-proofread]  (project folder must exist)")
    n = clean_project(sys.argv[1])
    if "--mark-proofread" in sys.argv:
        # the agent has read every transcript and filled glossary.json: captions may now be shown
        open(os.path.join(E.edit_dir(sys.argv[1]), "scan", ".proofread"), "w").close()
    print(n, "clips cleaned" + (" (marked proofread)" if "--mark-proofread" in sys.argv else ""))
