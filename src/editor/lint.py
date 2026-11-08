"""Pre-render checks for an EDL: catch trims that silently break the cut.

    python -m src.editor.lint "<project>"      # prints problems; exit 1 if any error

Errors (render refuses): an enabled shot with out <= in (the renderer used to drop it silently).
Warnings: a caption cut by the shot's out/in point (mid-word), a caption under 0.7 s on screen,
a clip shot under 0.5 s, B-roll that runs past its shot, and the same source footage used twice.
Audio/pacing warnings (research 2026-10-01): a voiceover line over 4 汉字 per second of its picture
window, a voiceover line starting < 0.3 s after a cut, more than 60 s of talk without a
music-only / natural-sound break, and more than 3 sound effects in any minute.
On-screen text (retro 2026-11-08 #2: the review notes he kept repeating, as checks): fillers and
trailing particles in captions/notes, one sentence split across two captions, Chinese numerals that
should be digits, a glossary name whose first mention lacks its English original (src/editor/glossary.json),
and, as an ERROR, internal references on screen (episode numbers like 第117期 / 117 E2, 第一版, v2, preview).
"""
import csv
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
import subprocess
import sys

from . import edl as E
from .captions_clean import FILLER_ONLY, INTERJECTION
from .digits import convert as to_digits

VO_MAX_CPS = 4.0           # 汉字 per second of a voiceover line's picture window (Yunxi at -5% speaks ~4.7-5/s)
VO_MIN_AFTER_CUT = 0.3     # s: let the new picture register before narration starts
TALK_MAX_S = 60.0          # s of talk (speech captions + narration) before a break is due
TALK_BREAK_S = 4.0         # s without speech that counts as a music-only / natural-sound break
SFX_MAX_PER_MIN = 3
MIN_CAPTION_S = 0.7
NOTE_MIN_S = 2.0           # s a yellow note stays up at least
NOTE_READ_CPS = 6.0        # 汉字 per second a viewer reads a note while watching (creator, 109 #10: 「停留可以长一点」)
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
        sp = [x for x in E.shot_subs(s) if x["kind"] != "note"]
        for a_, b_ in zip(sp, sp[1:]):  # a restart: keep only the good take (creator, 2026-10-03)
            ta, tb = re.sub(r"[\W_]", "", a_["text"]), re.sub(r"[\W_]", "", b_["text"])
            if len(ta) >= 3 and b_["t0"] - a_["t1"] < 6 and (tb.startswith(ta) or SequenceMatcher(None, ta, tb).ratio() >= 0.6):
                warns.append(f"{sid}: possible retake 「{a_['text']}」 then 「{b_['text']}」: keep only the good take")
        for x in E.shot_subs(s):
            if x["kind"] != "note" and x["t1"] - x["t0"] < MIN_CAPTION_S:
                warns.append(f"{sid}: caption 「{x['text']}」 on screen only {x['t1'] - x['t0']:.2f} s")
            # a yellow note must stay long enough to read; a skip inside its window eats the time (109 #10)
            need = max(NOTE_MIN_S, count_hanzi(x["text"]) / NOTE_READ_CPS)
            if x["kind"] == "note" and x["t1"] - x["t0"] < need - 0.1:
                warns.append(f"{sid}: note 「{x['text'][:12]}…」 on screen {x['t1'] - x['t0']:.1f} s, needs ~{need:.1f} s to read")
        # overlay collisions (creator, ep 100 review): a top note shown while the top-left tag is up, or two
        # captions on screen at once in the same slot. (Title vs bottom caption is avoided by the renderer.)
        subs_l = E.shot_subs(s)
        if s.get("tag") and s.get("tag_pos", "tl") in ("tl", "tr"):
            for x in subs_l:
                if x.get("pos") == "top" and x["t0"] < min(3.0, E.shot_dur(s)):
                    warns.append(f"{sid}: top note 「{x['text'][:12]}…」 overlaps the place tag in the first 3 s: move one")
        for i, a_ in enumerate(subs_l):
            for b_ in subs_l[i + 1:]:
                if (a_.get("pos") == "top") == (b_.get("pos") == "top") and min(a_["t1"], b_["t1"]) - max(a_["t0"], b_["t0"]) > 0.15:
                    warns.append(f"{sid}: 「{a_['text'][:10]}…」 and 「{b_['text'][:10]}…」 overlap on screen in the same slot")
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
    e2, w2 = onscreen_text(edl)
    errors += e2
    warns += w2
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


# ---- on-screen text (retro 2026-11-08 #2) --------------------------------------------------------
# 1. fillers: a trailing particle (120: 「字幕的结尾应该不需要"啊"」) or an interjection phrase (121: 「一般"妈呀"
#    不要剪进字幕」); whole-line interjections reuse captions_clean's lists.
TRAIL_PARTICLES = "啊呀吧嘛哦呢啦哈"
TRAIL_OK = ("酒吧", "网吧", "贴吧", "干嘛", "阿罗哈", "奥马哈", "苏打吧")  # words, not particles
QUESTION_PARTICLES = "呢吧"           # 「…怎么走呢」「去哪呢？」: a grammatical question particle, left alone
QUESTION_RX = re.compile(r"[？?]$|什么|怎么|为什么|为啥|哪|谁|多少|几")
FILLER_PHRASES = ("哎呀妈呀", "妈呀", "我的天", "我的妈", "哇塞", "天哪", "天呐", "哎呀", "哎哟", "哎呦")
_END_PUNCT = " \t，,。.！!？?~～…、"
# 2. one sentence split across two cues in a shot (120: 「很和重要 应该要放在一句话…你不要切成两条」): only on a
#    strong grammatical signal (the first cue can't end there, or the second can't start there), since his
#    captions carry no end punctuation at all.
SPLIT_GAP_S = 2.5                    # the signals below are grammatical, so a pause doesn't end the sentence: the raw
                                     # 117–122 transcripts split real sentences at 0.0–2.3 s gaps (「…他们的很」|「重要的一个部分」)
SPLIT_MAX_HANZI = 28                 # the merged cue must still fit two lines
DANGLING_END = re.compile(r"(?:因为|所以|但是|而且|并且|如果|虽然|或者|以及|就是说|比如|非常|比较|对于|关于|"
                          r"(?<![平暖温柔缓祥附总])和|很|最|跟|被|从|[（(《“])$")   # a cue can't end on these
CONT_START = re.compile(r"^(?:的(?!确)|了(?![解不])|们|吗|呢|和|与|以及|或者|并且|而且|似的|[）)》”」])")  # nor start
# 3. digits: src.editor.digits.convert, with set phrases protected (memory caption-digits: keep 第一/一路/百年)
DIGIT_KEEP = re.compile(r"(?<![零〇一二两三四五六七八九十百千])(?:第一|一路|百年|一起|一下|一点(?!钟)|一些|一样|一直|一天|"
                        r"一会|一边|一切|一共|一般|一定|四周|四处|十分(?!钟)|千万|万一|一一)")
# 4. internal references (122: 「这里不用写序号（e.g. 117 118) 因为这是内部编号」; 10/23: 「左下角有写"第一版"」)
INTERNAL_RX = [
    (re.compile(r"第\s*1\d\d\s*[期集]"), "an episode number"),
    (re.compile(r"(?<![\d.])1\d\d\s*[期集](?![市团合])"), "an episode number"),
    (re.compile(r"(?i)(?<![A-Za-z])(?:ep|episode)\s*\.?\s*#?\s*1\d\d(?!\d)"), "an episode number"),
    (re.compile(r"(?<![\d.$#])1\d\d\s*[-_·]?\s*[Ee][1-9]\d?(?![\dA-Za-z])"), "an episode id"),
    (re.compile(r"(?<![\d.$#])#1\d\d(?!\d)"), "an episode number"),
    (re.compile(r"(?<![\d.$])1\d\d(?:[ 、,，/]+1\d\d)+(?![\d%A-Za-z\u3400-\u9fff])"), "episode numbers"),
    (re.compile(r"第\s*[一二三四五六七八九十\d]+\s*版(?!本)"), "a version label"),
    (re.compile(r"(?<![A-Za-z0-9])v\d+(?:\.\d+)?(?![A-Za-z0-9])"), "a version label"),
    (re.compile(r"(?i)(?<![A-Za-z])(?:preview|draft|todo|tbd)(?![A-Za-z])|预览|草稿|占位"), "a work-in-progress word"),
]
# 5. original names (122: 「人道协会也要放英语」, 「欧胡岛要写oahu」): the first on-screen mention is bilingual
GLOSSARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glossary.json")
NAME_WINDOW_S = 5.0                  # the English may sit in a tag/note shown up to this many seconds later (a title, then the place tag)


def load_glossary(path=GLOSSARY_PATH):
    """{chinese: [accepted English forms, canonical first]} from src/editor/glossary.json."""
    try:
        with open(path, encoding="utf-8") as f:
            names = json.load(f).get("names", {})
    except (OSError, ValueError):
        return {}
    return {k: [v] if isinstance(v, str) else list(v) for k, v in names.items() if v}


def _fold(text):
    """Lowercase, no accents/macrons, no ʻokina or apostrophes: Haleʻiwa == Haleiwa == hale'iwa."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[ʻʼ'’‘`]", "", t).lower()


def onscreen_items(edl):
    """Every piece of on-screen text in timeline order: dicts with t0/t1 (timeline s), sid, kind
    (speech | note | title | tag | card | label) and text. Captions are clipped/skip-mapped like the render."""
    rows, _total = E.timeline(edl)
    items = []

    def local(s, t):
        try:
            return E.src_to_local(s, float(t))
        except (TypeError, ValueError):
            return 0.0

    for s, st in rows:
        sid, dur = s.get("id", "?"), E.shot_dur(s)
        t = s.get("title") or {}
        for k in ("kicker", "text", "sub"):
            if isinstance(t, dict) and str(t.get(k) or "").strip():
                items.append({"t0": st, "t1": st + float(t.get("dur", 3.0)), "sid": sid, "kind": "title", "text": t[k]})
        if str(s.get("tag") or "").strip():
            ta = local(s, s["tag_at"]) if s.get("tag_at") is not None else 0.0
            items.append({"t0": st + ta, "t1": st + ta + float(s.get("tag_dur", 3.0)), "sid": sid, "kind": "tag",
                          "text": s["tag"]})
        c = s.get("card") or {}
        for k in ("text", "sub"):
            if isinstance(c, dict) and str(c.get(k) or "").strip():
                items.append({"t0": st, "t1": st + dur, "sid": sid, "kind": "card", "text": c[k]})
        for m in (s.get("marks") or []) + (s.get("spots") or []):
            if str(m.get("label") or "").strip():
                items.append({"t0": st + local(s, m.get("t0", s["in"])), "t1": st + local(s, m.get("t1", s["out"])),
                              "sid": sid, "kind": "label", "text": m["label"]})
        g = s.get("gauge") or {}
        if isinstance(g, dict) and str(g.get("label") or "").strip():
            items.append({"t0": st, "t1": st + dur, "sid": sid, "kind": "label", "text": g["label"]})
        for i, x in enumerate(E.shot_subs(s)):
            items.append({"t0": st + x["t0"], "t1": st + x["t1"], "sid": sid, "kind": x["kind"], "text": x["text"],
                          "local0": x["t0"], "local1": x["t1"], "n": i})
    items.sort(key=lambda x: x["t0"])
    return items


def _q(text, n=24):
    return text if len(text) <= n else text[:n] + "…"


def digits_fix(text):
    """The caption with Chinese numerals as Arabic digits, set phrases left alone; == text if nothing to do."""
    keep = []

    def hide(m):
        keep.append(m.group(0))
        return chr(0xE000 + len(keep) - 1)
    out = to_digits(DIGIT_KEEP.sub(hide, text))
    return re.sub("[\ue000-\uf8ff]", lambda m: keep[ord(m.group(0)) - 0xE000], out)


def filler_warn(text):
    """Why a caption/note reads as filler, or None."""
    t = text.strip()
    if INTERJECTION.match(t) or FILLER_ONLY.match(t):
        return "is only an interjection/filler: drop the cue"
    for p in FILLER_PHRASES:
        if p in t:
            return f"has the interjection 「{p}」: cut it from the caption"
    core = t.rstrip(_END_PUNCT)
    if core and core[-1] in TRAIL_PARTICLES and not core.endswith(TRAIL_OK):
        if core[-1] in QUESTION_PARTICLES and QUESTION_RX.search(t.rstrip(" \t")):
            return None
        return f"ends in the particle 「{core[-1]}」: drop it"
    return None


def split_sentence(a, b):
    """True when cue b reads as the second half of cue a's sentence (caller checks same shot, gap <= 0.4 s)."""
    ta, tb = a["text"].strip(), b["text"].strip()
    if not ta or not tb or ta[-1] in _END_PUNCT:
        return False
    if count_hanzi(ta) + count_hanzi(tb) > SPLIT_MAX_HANZI:
        return False
    if ta.count("（") > ta.count("）") or ta.count("《") > ta.count("》"):
        return True
    return bool(DANGLING_END.search(ta) or CONT_START.match(tb))


def onscreen_text(edl, glossary=None):
    """(errors, warns) for on-screen text: fillers, split sentences, digits, internal refs, original names."""
    errors, warns = [], []
    items = onscreen_items(edl)
    for x in items:
        sid, kind, text = x["sid"], x["kind"], x["text"]
        what = {"speech": "caption", "note": "note"}.get(kind, kind)
        for rx, why in INTERNAL_RX:
            m = rx.search(text)
            if m:
                errors.append(f"{sid}: {what} 「{_q(text)}」 shows {why} 「{m.group(0)}」: internal, never on screen")
                break
        if kind in ("speech", "note"):
            why = filler_warn(text)
            if why:
                warns.append(f"{sid}: {what} 「{_q(text)}」 {why}")
        new = digits_fix(text)
        if new != text:
            warns.append(f"{sid}: {what} 「{_q(text, 30)}」 → 「{_q(new, 30)}」: Arabic digits (src.editor.digits)")
    by_shot = {}
    for x in items:
        if x["kind"] == "speech":
            by_shot.setdefault(x["sid"], []).append(x)
    for sid, cues in by_shot.items():
        cues.sort(key=lambda c: c["local0"])
        for a, b in zip(cues, cues[1:]):
            if 0 <= b["local0"] - a["local1"] <= SPLIT_GAP_S and split_sentence(a, b):
                warns.append(f"{sid}: 「{_q(a['text'], 18)}」 | 「{_q(b['text'], 18)}」 look like one sentence: "
                             f"merge into one cue joined with ，")
    warns += original_names(items, load_glossary() if glossary is None else glossary)
    return errors, warns


def original_names(items, glossary):
    """A glossary name whose first on-screen mention has no English original in sight."""
    warns, groups = [], {}
    for zh, forms in glossary.items():
        groups.setdefault(_fold(forms[0]), (forms[0], set()))[1].update(_fold(f) for f in forms)
    canon_of = {zh: _fold(forms[0]) for zh, forms in glossary.items()}
    seen = set()
    for x in items:
        for zh in sorted(glossary, key=len, reverse=True):
            key = canon_of[zh]
            if key in seen or zh not in x["text"]:
                continue
            seen.add(key)
            eng, forms = groups[key]
            near = [y["text"] for y in items if y["t0"] <= x["t0"] + NAME_WINDOW_S and y["t1"] >= x["t0"] - 0.5]
            if not any(f in _fold(t) for t in near for f in forms):
                where = {"speech": "caption", "note": "note"}.get(x["kind"], x["kind"])
                warns.append(f"{x['sid']}: first mention of {zh} ({where} 「{_q(x['text'])}」) has no original name: "
                             f"add {eng}")
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
