"""Raw footage player: watch every unedited clip of a trip back-to-back.

    ./venv/bin/python -m src.editor.footage_player "<project>" [--port 8765]

Plays `<project>/01 - Unedited/*.MP4` in capture order (ffprobe creation_time, then
filename) as one continuous stream, with speed presets, a whole-trip timeline, a clip list
with thumbnails and per-clip captions (`02 - Export/edit/scan/srt/<CLIP>.srt`).

Works with or without an EDL. When `02 - Export/edit/edl.json` exists, the timeline shows
which parts of each raw clip end up in the current cut (enabled shots' kept ranges plus
b-roll inserts); the page re-reads it every 10 s so it tracks an edit in progress.

Read-only: nothing inside the source folder is ever written. Probe results and thumbnails
are cached under /tmp/yt-editor/<project>/.
"""
import argparse
import json
import os
import re
import subprocess
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, Response, abort, jsonify, send_file

from . import edl as E
from . import questions as QS
from . import chat as CHAT
from . import theme as THEME

CACHE_ROOT = "/tmp/yt-editor"
DEFAULT_SOURCE = "01 - Unedited"

app = Flask(__name__)
PROJECT = None            # absolute project dir
_lock = threading.Lock()
_clips = {"key": None, "list": []}
_thumb_sem = threading.Semaphore(3)
QS.register(app, lambda: PROJECT)
CHAT.register(app, lambda: PROJECT)


# ---------------------------------------------------------------- helpers

def cache_dir(*sub):
    d = os.path.join(CACHE_ROOT, os.path.basename(PROJECT.rstrip("/")), *sub)
    os.makedirs(d, exist_ok=True)
    return d


def load_edl():
    try:
        return E.load(PROJECT)
    except (OSError, ValueError):
        return None


def source_dir():
    edl = load_edl()
    sub = (edl or {}).get("source_dir") or DEFAULT_SOURCE
    return os.path.join(PROJECT, sub)


def srt_path(clip):
    """Only PROOFREAD captions are ever shown (edit/scan/srt_clean, see captions_clean.py);
    raw whisper output never reaches the page. Re-proofread when the edit or glossary changed."""
    path = os.path.join(E.edit_dir(PROJECT), "scan", "srt_clean", clip + ".srt")
    if not os.path.exists(os.path.join(E.edit_dir(PROJECT), "scan", ".proofread")):
        return path + ".not-yet"  # the agent hasn't proofread this project yet: show no captions
    raw = os.path.join(E.edit_dir(PROJECT), "scan", "srt", clip + ".srt")
    if os.path.exists(raw):
        deps = [E.edl_path(PROJECT), os.path.join(E.edit_dir(PROJECT), "glossary.json"), raw]
        newest = max((os.path.getmtime(d) for d in deps if os.path.exists(d)), default=0)
        if not os.path.exists(path) or os.path.getmtime(path) < newest:
            from .captions_clean import clean_project
            clean_project(PROJECT)
    return path


def probe(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=creation_time",
             "-of", "json", path], capture_output=True, text=True, timeout=60).stdout
        fmt = json.loads(out).get("format", {})
        return {"dur": float(fmt.get("duration") or 0),
                "ctime": (fmt.get("tags") or {}).get("creation_time", "")}
    except Exception:
        return {"dur": 0.0, "ctime": ""}


_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            blocks = re.split(r"\n\s*\n", f.read().replace("\r", ""))
    except OSError:
        return []
    out = []
    for b in blocks:
        lines = [x for x in b.strip().split("\n") if x.strip()]
        for i, ln in enumerate(lines):
            m = _TS.search(ln)
            if m:
                g = [int(x) for x in m.groups()]
                t0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                t1 = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                text = " ".join(lines[i + 1:]).strip()
                if text:
                    out.append({"t0": t0, "t1": t1, "text": text})
                break
    return out


def clip_list():
    """All raw clips in capture order, with duration / capture time / first caption line.
    Probe results are cached on disk keyed by file size + mtime."""
    src = source_dir()
    try:
        names = sorted(f for f in os.listdir(src)
                       if f.lower().endswith(".mp4") and not f.startswith("."))
    except OSError:
        names = []
    stats = {}
    for n in names:
        st = os.stat(os.path.join(src, n))
        stats[n] = f"{st.st_size}:{int(st.st_mtime)}"
    key = (src, tuple(sorted(stats.items())))
    with _lock:
        if _clips["key"] == key:
            return _clips["list"]
        cache_file = os.path.join(cache_dir(), "rawprobe.json")
        try:
            with open(cache_file, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
        todo = [n for n in names if cache.get(n, {}).get("stat") != stats[n]]
        with ThreadPoolExecutor(8) as ex:
            for n, r in zip(todo, ex.map(lambda n: probe(os.path.join(src, n)), todo)):
                cache[n] = dict(r, stat=stats[n])
        with open(cache_file + ".tmp", "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(cache_file + ".tmp", cache_file)
        rows = []
        for n in names:
            stem = os.path.splitext(n)[0]
            c = cache[n]
            subs = parse_srt(srt_path(stem))
            ct = c["ctime"]
            # show the camera clock as written; no timezone conversion
            m = re.match(r"\d{4}-(\d\d)-(\d\d)T(\d\d):(\d\d)", ct)
            rows.append({"clip": stem, "file": n, "dur": round(c["dur"], 3), "ctime": ct,
                         "clock": f"{m[1]}-{m[2]} {m[3]}:{m[4]}" if m else "",
                         "first": subs[0]["text"] if subs else "",
                         "has_srt": bool(subs)})
        rows.sort(key=lambda r: (r["ctime"] or "9999", r["clip"]))
        label_days(rows)
        _clips["key"], _clips["list"] = key, rows
        return rows


DAY_GAP = 6 * 3600


def label_days(rows):
    """Camera clocks are often off by hours, so wall-clock times mislead. Group clips into
    shooting days (a new day starts after a > 6 h gap) and label each clip with its offset
    from that day's first clip: "第1天 · +0:14". The raw camera clock stays in `clock`."""
    day, day0, prev_end = 0, None, None
    for r in rows:
        try:
            t = datetime.strptime(r["ctime"][:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        except ValueError:
            t = None
        if t is None:
            r["day"], r["when"] = day or 1, f"第{day or 1}天"
            continue
        if prev_end is None or t - prev_end > DAY_GAP:
            day, day0 = day + 1, t
        prev_end = max(prev_end or t, t + r["dur"])
        m = int((t - day0) // 60)
        r["day"], r["when"] = day, f"第{day}天 · +{m // 60}:{m % 60:02d}"


def clip_file(name):
    """Whitelisted clip -> absolute path, else 404."""
    for r in clip_list():
        if r["clip"] == name:
            return os.path.join(source_dir(), r["file"])
    abort(404)


def merge(rs):
    out = []
    for a, b in sorted(rs):
        if out and a <= out[-1][1] + 0.05:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[round(a, 2), round(b, 2)] for a, b in out]


def usage():
    """{clip: [[a, b], ...]} source ranges used by the current cut, or None without an EDL."""
    edl = load_edl()
    if not edl or not isinstance(edl.get("shots"), list):
        return None
    used = {}
    for s in edl["shots"]:
        try:
            if not s.get("enabled", True) or s["out"] <= s["in"]:
                continue
            used.setdefault(s["clip"], []).extend(E.kept_ranges(s))
            for b in s.get("broll") or []:
                a = float(b.get("in", 0))
                used.setdefault(b["clip"], []).append((a, a + float(b.get("dur", 0))))
        except (KeyError, TypeError, ValueError):
            continue
    return {c: merge(rs) for c, rs in used.items()}


# ---------------------------------------------------------------- routes

@app.get("/")
def index():
    return Response(PAGE.replace("__TITLE__", os.path.basename(PROJECT.rstrip("/"))),
                    mimetype="text/html")


@app.get("/api/clips")
def api_clips():
    return jsonify(clip_list())


@app.get("/api/usage")
def api_usage():
    u = usage()
    return jsonify({"has_edl": u is not None, "used": u or {}})


@app.get("/api/srt/<name>")
def api_srt(name):
    clip_file(name)
    return jsonify(parse_srt(srt_path(name)))


@app.get("/clip/<name>")
def clip(name):
    return send_file(clip_file(name), mimetype="video/mp4", conditional=True)


@app.get("/thumb/<name>")
def thumb(name):
    src = clip_file(name)
    dur = next((r["dur"] for r in clip_list() if r["clip"] == name), 0) or 0
    out = os.path.join(cache_dir("rawthumbs"), name + ".jpg")
    if not os.path.isfile(out):
        with _thumb_sem:
            if not os.path.isfile(out):
                tmp = out + ".tmp.jpg"
                for tt in (dur * 0.25, 0.0):
                    subprocess.run(
                        ["ffmpeg", "-v", "error", "-y", "-ss", f"{tt:.2f}", "-i", src,
                         "-frames:v", "1", "-vf", "scale=240:-2", "-q:v", "5", tmp],
                        capture_output=True, timeout=60)
                    if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
                        os.replace(tmp, out)
                        break
    if not os.path.isfile(out):
        abort(404)
    return send_file(out, mimetype="image/jpeg", max_age=86400)


# ---------------------------------------------------------------- page

PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · 原片预览</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%23fb923c'/%3E%3Cstop offset='1' stop-color='%23e11d48'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='64' height='64' rx='15' fill='url%28%23g%29'/%3E%3Crect x='12' y='16' width='40' height='32' rx='5' fill='none' stroke='white' stroke-width='4'/%3E%3Cpath d='M28 25 L40 32 L28 39 Z' fill='white'/%3E%3Cg fill='white'%3E%3Crect x='16' y='10' width='5' height='4' rx='1'/%3E%3Crect x='29' y='10' width='5' height='4' rx='1'/%3E%3Crect x='42' y='10' width='5' height='4' rx='1'/%3E%3Crect x='16' y='50' width='5' height='4' rx='1'/%3E%3Crect x='29' y='50' width='5' height='4' rx='1'/%3E%3Crect x='42' y='50' width='5' height='4' rx='1'/%3E%3C/g%3E%3C/svg%3E">
<style>
__THEME_CSS__
html,body{height:100%}
.app{display:flex;flex-direction:column;height:100vh}
.body{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) clamp(300px,25vw,380px)}
main{display:flex;flex-direction:column;padding:16px;min-width:0;min-height:0}
/* ---- video stage (always dark) */
.stage{position:relative;flex:none;width:100%;aspect-ratio:16/9;max-height:calc(100vh - var(--hdr) - 32px - 40px);
  background:var(--stage);border-radius:var(--r-lg);overflow:hidden;container-type:size;cursor:default;box-shadow:var(--sh-1)}
/* fullscreen = this whole area (video + rail), so the chat stays on screen (chat.py: .fs / .fs-rail / .fs-float) */
.body.fs main{padding:0;min-height:0;height:100vh}
.body.fs .stage{border-radius:0;max-height:none;aspect-ratio:auto;width:100%;height:100%;box-shadow:none}
.body.fs .below,.body.fs .lists{display:none !important}
.stage:not(.ctl){cursor:none}
.stage video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:var(--stage)}
.stage video.hidden{visibility:hidden}
.stage .msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:var(--stage-mute);font-size:16px;pointer-events:none}
.cap{position:absolute;left:50%;bottom:5%;transform:translateX(-50%);width:84%;text-align:center;
  pointer-events:none;transition:bottom .2s ease;z-index:3;
  font-size:clamp(14px,2.4cqw,44px);font-weight:500;line-height:1.4}
.cap span{background:rgba(8,8,8,.75);color:#fff;padding:.1em .45em;border-radius:4px;
  -webkit-box-decoration-break:clone;box-decoration-break:clone}
.cap:empty{display:none}
.bigplay{position:absolute;left:50%;top:50%;width:76px;height:76px;margin:-38px 0 0 -38px;border-radius:50%;background:rgba(0,0,0,.5);
  backdrop-filter:blur(4px);pointer-events:none;z-index:3;transition:opacity .2s ease,transform .2s ease}
.bigplay::after{content:'';position:absolute;left:30px;top:22px;border-style:solid;border-width:16px 0 16px 26px;border-color:transparent transparent transparent #fff}
.bigplay.hide{opacity:0;transform:scale(1.25)}
.stage.ctl .cap{bottom:calc(92px + 3%)}
.ov{position:absolute;left:0;right:0;bottom:0;padding:40px 14px 10px;z-index:4;color:var(--stage-ink);
  background:linear-gradient(to bottom,transparent,rgba(0,0,0,.72));
  opacity:0;pointer-events:none;transition:opacity .25s ease}
.stage.ctl .ov{opacity:1;pointer-events:auto}
.bar{display:flex;align-items:center;gap:12px;margin-top:8px;height:32px}
.gtime{font-size:16px;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap;color:#fff}
.info{font-size:13px;color:var(--stage-mute);font-variant-numeric:tabular-nums;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.spacer{flex:1}
.ov button{background:transparent;color:#fff;border:0;border-radius:var(--r-sm);padding:0;height:32px;min-width:32px;
  display:inline-grid;place-items:center;white-space:nowrap}
.ov button:hover{background:rgba(255,255,255,.14)}
.ov button svg{display:block}
.speeds{display:flex;height:28px;border-radius:var(--r-sm);background:rgba(255,255,255,.12);padding:2px;gap:2px}
.speeds button{height:24px;min-width:0;padding:0 9px;font-size:12px;font-weight:500;border-radius:6px;color:var(--stage-ink);font-variant-numeric:tabular-nums}
.speeds button.on{background:#fff;color:#111}
.tl-row{position:relative}
.tl{position:relative;height:8px;border-radius:4px;cursor:pointer;overflow:hidden;display:flex;transition:height .15s ease}
.tl-row:hover .tl{height:14px}
.seg{position:relative;height:100%;background:rgba(255,255,255,.4);border-right:1px solid rgba(0,0,0,.5)}
body.showuse .seg{background:rgba(255,255,255,.2)}
body.showuse .seg.noedl{background:rgba(255,255,255,.4)}
.seg.day0{border-left:3px solid #fff}
.seg .u{position:absolute;top:0;bottom:0;background:var(--used)}
.seg.cur{background:rgba(255,255,255,.62)}
body.showuse .seg.cur{background:rgba(255,255,255,.38)}
body:not(.showuse) .seg .u,body:not(.showuse) .item .ub,body:not(.showuse) .legend{display:none}
.ph{position:absolute;top:-4px;bottom:-4px;width:3px;margin-left:-1px;background:#ff3b5c;border-radius:2px;pointer-events:none;z-index:2}
.hover{position:absolute;bottom:22px;transform:translateX(-50%);background:rgba(20,20,20,.92);color:#fff;
  font-size:12px;padding:3px 8px;border-radius:6px;white-space:nowrap;pointer-events:none;display:none;font-variant-numeric:tabular-nums}
.qms{position:absolute;left:0;right:0;top:-11px;height:0;z-index:3}
.qm{position:absolute;top:0;width:0;height:0;margin-left:-6px;border-left:6px solid transparent;border-right:6px solid transparent;
  border-top:8px solid var(--q);cursor:pointer;filter:drop-shadow(0 0 1px rgba(0,0,0,.8))}
.qm.done{border-top-color:var(--used)}
/* ---- row under the stage: legend, toggle, shortcuts */
.below{display:flex;align-items:center;gap:16px;color:var(--text-3);font-size:13px;margin-top:10px;min-height:28px}
.legend{display:flex;gap:14px;align-items:center;white-space:nowrap;font-variant-numeric:tabular-nums}
.legend b{color:var(--text);font-weight:600}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;vertical-align:-1px;margin-right:6px}
.tog{display:inline-flex;align-items:center;gap:8px;cursor:pointer;user-select:none;white-space:nowrap;color:var(--text-2)}
.tog input{position:absolute;opacity:0;width:0;height:0}
.tog .knob{width:28px;height:16px;border-radius:999px;background:var(--line-2);position:relative;transition:background .15s;flex:none}
.tog .knob::after{content:'';position:absolute;left:2px;top:2px;width:12px;height:12px;border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.2);transition:transform .15s}
.tog input:checked+.knob{background:var(--used)}
.tog input:checked+.knob::after{transform:translateX(12px)}
.keys{position:relative}
.keys>button{font-size:13px;padding:3px 10px;color:var(--text-2)}
.keypop{display:none;position:absolute;right:0;bottom:calc(100% + 8px);z-index:20;width:300px;padding:10px 12px;
  background:var(--surface);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--sh-2);color:var(--text-2);font-size:13px}
.keys:hover .keypop,.keys.open .keypop{display:block}
.keypop div{display:flex;justify-content:space-between;align-items:center;padding:3px 0}
/* ---- right rail */
.rail{display:flex;flex-direction:column;gap:12px;padding:16px 16px 16px 0;min-height:0}
#qcard .qa-card{margin:0;box-shadow:var(--sh-1)}
.lists{flex:0 1 auto;max-height:34vh;min-height:0;display:flex;flex-direction:column;overflow:hidden}
.lists.closed .pane{display:none}.lists.closed .tabs{border-bottom:0;padding-bottom:6px}
#listTog{margin-left:auto;color:var(--text-3);font-weight:400}
.tabs{display:flex;gap:2px;padding:6px 6px 0;border-bottom:1px solid var(--line);flex:none}
.tab{border:0;background:transparent;border-radius:var(--r-sm) var(--r-sm) 0 0;padding:6px 12px 8px;font-size:13px;font-weight:500;color:var(--text-3);
  position:relative}
.tab:hover{background:transparent;color:var(--text)}
.tab.on{color:var(--text)}
.tab.on::after{content:'';position:absolute;left:12px;right:12px;bottom:-1px;height:2px;border-radius:2px;background:var(--accent)}
.tab .n{color:var(--text-3);font-weight:400;margin-left:2px;font-variant-numeric:tabular-nums}
.tab .n.open{color:var(--q-ink);font-weight:500}
body:not(.hasq) #qtab{display:none}
.pane{flex:1;min-height:0;overflow-y:auto}
.pane[hidden]{display:none}
#qpanel{padding:8px}
#chatDock{flex:1 1 auto;min-height:280px;overflow:hidden}
#chatDock.min{flex:0 0 auto;min-height:0}
.rail:has(#chatDock.min) .lists{flex:1 1 auto;max-height:none}
#chatDock #cb{border:0;border-radius:0}

.dayhead{padding:8px 12px 6px;background:var(--surface);color:var(--text-2);font-size:12px;font-weight:600;
  border-bottom:1px solid var(--line);position:sticky;top:0;z-index:1}
.item{display:grid;grid-template-columns:88px 1fr;gap:10px;padding:8px 12px;border-bottom:1px solid var(--surface-3);cursor:pointer;position:relative}
.item:hover{background:var(--surface-2)}
.item.cur{background:var(--accent-soft)}
.item.cur::before{content:'';position:absolute;left:0;top:8px;bottom:8px;width:3px;border-radius:0 3px 3px 0;background:var(--accent)}
.item img{width:88px;height:50px;object-fit:cover;border-radius:6px;background:var(--surface-3);display:block}
.item .t{display:flex;gap:6px;align-items:baseline;font-size:13px}
.item .t b{font-weight:600}
.item .t .m{color:var(--text-3);font-size:12px;font-variant-numeric:tabular-nums}
.item .ub{position:relative;height:4px;background:var(--unused);border-radius:2px;margin:5px 0;overflow:hidden}
.item .ub.noedl{background:var(--surface-3)}
.item .ub i{position:absolute;top:0;bottom:0;background:var(--used)}
.item .first{color:var(--text-3);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item .first .none{color:var(--faint)}
__QA_CSS__
</style></head><body>
<div class="app">
<header class="hdr">
  <span class="kind">原片预览</span><span class="sep"></span><span class="pname">__TITLE__</span>
  <span class="meta" id="hmeta"></span><span class="sp"></span><span class="meta" id="est"></span>
</header>
<div class="body" data-fsroot>
<main>
  <div class="stage ctl" id="stage">
    <video id="va" playsinline preload="auto"></video>
    <video id="vb" class="hidden" playsinline preload="auto" muted></video>
    <div class="msg" id="msg">加载中…</div>
    <div class="bigplay" id="bigplay"></div>
    <div class="cap" id="cap"></div>
    <div class="ov" id="ov">
      <div class="tl-row"><div class="tl" id="tl"></div><div class="ph" id="ph"></div><div class="qms" id="qms"></div>
        <div class="hover" id="hover"></div></div>
      <div class="bar">
        <button id="play" title="播放 / 暂停（空格）"></button>
        <div class="gtime" id="gtime">0:00 / 0:00</div>
        <div class="info" id="info"></div>
        <div class="spacer"></div>
        <div class="speeds" id="speeds" title="速度（数字键 1–5）"></div>
        <button id="fs" title="全屏（F）"></button>
      </div>
    </div>
  </div>
  <div class="below">
    <span class="legend" id="legend"></span>
    <label class="tog" title="在进度条和片段列表里标出用在成片里的部分"><input type="checkbox" id="showuse"><span class="knob"></span>标出成片用到的部分</label>
    <span class="spacer"></span>
    <div class="keys" id="keys"><button class="ghost" id="keysBtn"><svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" style="vertical-align:-3px;margin-right:5px"><rect x="1.5" y="4" width="13" height="8.5" rx="1.8"/><path d="M4 6.7h.01M6.3 6.7h.01M8.6 6.7h.01M10.9 6.7h.01M5 9.6h6" stroke-linecap="round" stroke-width="1.6"/></svg>快捷键</button><div class="keypop">
      <div><span>播放 / 暂停</span><span><kbd>空格</kbd></span></div>
      <div><span>快退 / 快进 5 秒</span><span><kbd>←</kbd><kbd>→</kbd></span></div>
      <div><span>上一段 / 下一段</span><span><kbd>↑</kbd><kbd>↓</kbd></span></div>
      <div><span>切换速度 1x–3x</span><span><kbd>1</kbd>–<kbd>5</kbd></span></div>
      <div><span>全屏（右边留着聊天）</span><span><kbd>F</kbd></span></div>
      <div><span>全屏时聊天：右边 / 悬浮</span><span><kbd>C</kbd></span></div>
      <div><span>跳到任意位置</span><span>点进度条</span></div>
    </div></div>
  </div>
</main>
<aside class="rail" data-fsrail>
  <div id="qcard"></div>
  <div class="panel lists closed" id="lists">
    <div class="tabs"><button class="tab on" data-tab="list">片段<span class="n" id="count"></span></button><button class="tab" data-tab="qpanel" id="qtab">问题<span class="n" id="qcount"></span></button><button class="tab" id="listTog" title="片段列表默认收起，聊天框更大">展开 ▾</button></div>
    <div class="pane scroll" id="list"></div>
    <div class="pane scroll" id="qpanel" hidden></div>
  </div>
  <div id="chatDock" class="panel"></div>
</aside>
</div>
</div>
<script>
const SPEEDS=[1,1.25,1.5,2,3];
const PNAME=document.title.replace(/ · 原片预览$/,'');
let clips=[], starts=[], total=0, idx=0, used={}, hasEdl=false, speed=2;
const srtCache={};
const $=id=>document.getElementById(id);
const IC={play:'<svg width="18" height="18" viewBox="0 0 16 16"><path d="M4.5 2.8v10.4L13 8z" fill="currentColor"/></svg>',
  pause:'<svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor"><rect x="3.5" y="2.8" width="3.2" height="10.4" rx="1"/><rect x="9.3" y="2.8" width="3.2" height="10.4" rx="1"/></svg>',
  fs:'<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10"/></svg>',
  fsx:'<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M6 2.5V6H2.5M13.5 6H10V2.5M10 13.5V10h3.5M2.5 10H6v3.5"/></svg>'};
function playUI(p){$('play').innerHTML=p?IC.pause:IC.play}
function fsUI(){const f=!!(window.cbFs&&cbFs.active());$('fs').innerHTML=f?IC.fsx:IC.fs;$('fs').title=f?'退出全屏（F / Esc）':'全屏，右边留着聊天（F）'}
playUI(false);fsUI();
let cur=$('va'), nxt=$('vb'), nxtIdx=-1;
try{const s=parseFloat(localStorage.getItem('fp_speed'));if(SPEEDS.includes(s))speed=s}catch(e){}

function fmt(t){t=Math.max(0,Math.round(t));const h=Math.floor(t/3600),m=Math.floor(t%3600/60),s=t%60;
  return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(s).padStart(2,'0')}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}

function setSpeed(s){speed=s;cur.playbackRate=s;nxt.playbackRate=s;
  try{localStorage.setItem('fp_speed',String(s))}catch(e){}
  document.querySelectorAll('#speeds button').forEach(b=>b.classList.toggle('on',+b.dataset.s===s));
  updEst()}
function updEst(){
  if(!total){$('est').textContent='';return}
  const left=total-(starts[idx]||0)-(cur.currentTime||0);
  $('est').textContent=`全部看完约 ${Math.max(1,Math.round(total/speed/60))} 分钟 @${speed}x · 剩下约 ${Math.max(0,Math.round(left/speed/60))} 分钟`}

function srt(clip){
  if(!srtCache[clip])srtCache[clip]=fetch('/api/srt/'+encodeURIComponent(clip)).then(r=>r.ok?r.json():[]).catch(()=>[]);
  return srtCache[clip]}

function prepare(v,i){v.src='/clip/'+encodeURIComponent(clips[i].clip);v.playbackRate=speed;v.load()}

function preloadNext(){
  const n=idx+1;
  if(n>=clips.length||nxtIdx===n)return;
  nxtIdx=n;nxt.muted=true;prepare(nxt,n);srt(clips[n].clip)}

function show(i,t,autoplay){
  i=Math.max(0,Math.min(clips.length-1,i));
  const wasPlaying=autoplay!==undefined?autoplay:!cur.paused;
  if(i===nxtIdx&&i!==idx){          // swap in the preloaded element: no gap
    swapping=true;cur.pause();swapping=false;const old=cur;cur=nxt;nxt=old;
    cur.classList.remove('hidden');nxt.classList.add('hidden');
    cur.muted=false;nxt.removeAttribute('src');nxt.load();nxtIdx=-1;
  }else if(i!==idx||!cur.getAttribute('src')){prepare(cur,i)}
  idx=i;cur.playbackRate=speed;
  const seek=()=>{if(t!=null)cur.currentTime=Math.min(t,Math.max(0,(clips[i].dur||0)-0.05))};
  if(cur.readyState>=1)seek();else cur.addEventListener('loadedmetadata',seek,{once:true});
  if(wasPlaying)cur.play().catch(()=>{});
  $('msg').textContent='';
  markCurrent();srt(clips[i].clip);preloadNext()}

function markCurrent(){
  document.querySelectorAll('.item.cur,.seg.cur').forEach(e=>e.classList.remove('cur'));
  const it=items()[idx],sg=$('tl').children[idx];
  if(it){it.classList.add('cur');it.scrollIntoView({block:'nearest',behavior:'smooth'})}
  if(sg)sg.classList.add('cur')}

function onEnded(e){if(e.target!==cur)return;
  if(idx+1<clips.length)show(idx+1,0,true);else playUI(false)}

[$('va'),$('vb')].forEach(v=>{
  v.addEventListener('ended',onEnded);
  v.addEventListener('play',()=>{if(v===cur){playUI(true);if(stage.classList.contains('ctl')){clearTimeout(hideT);hideT=setTimeout(maybeHide,2500)}}});
  v.addEventListener('pause',()=>{if(v===cur&&!swapping&&!v.ended){playUI(false);stage.classList.add('ctl')}});
  v.addEventListener('ratechange',()=>{if(v.playbackRate!==speed)v.playbackRate=speed});
  v.addEventListener('error',()=>{if(v===cur&&v.getAttribute('src'))$('msg').textContent='这段播放失败（浏览器可能不支持此编码）'});
});

function toggle(){if(cur.paused)cur.play().catch(()=>{});else cur.pause()}
// YouTube-style big ▶ in the middle while paused (both <video> elements swap roles, so poll)
setInterval(()=>{const b=document.getElementById('bigplay');if(b)b.classList.toggle('hide',!cur.paused)},150);
function seekBy(d){const t=cur.currentTime+d;
  if(t<0&&idx>0){show(idx-1,Math.max(0,clips[idx-1].dur+t))}
  else if(t>=(clips[idx].dur||1e9)&&idx+1<clips.length){show(idx+1,t-clips[idx].dur)}
  else cur.currentTime=Math.max(0,t)}
function jumpGlobal(g){let i=0;while(i+1<clips.length&&starts[i+1]<=g)i++;show(i,g-starts[i])}

function items(){return $('list').querySelectorAll('.item')}
function renderUsage(){
  const segs=$('tl').children,its=items();
  clips.forEach((c,i)=>{
    const rs=used[c.clip]||[],d=c.dur||1;
    const html=rs.map(([a,b])=>`<i class="u" style="left:${a/d*100}%;width:${Math.max(.3,(b-a)/d*100)}%"></i>`).join('');
    if(segs[i]){segs[i].innerHTML=html.replace(/<i class="u"/g,'<div class="u"').replace(/<\/i>/g,'</div>');segs[i].classList.toggle('noedl',!hasEdl)}
    const ub=its[i]&&its[i].querySelector('.ub');
    if(ub){ub.innerHTML=html;ub.classList.toggle('noedl',!hasEdl)}
  });
  if(hasEdl){
    const u=clips.reduce((s,c)=>s+(used[c.clip]||[]).reduce((x,[a,b])=>x+Math.min(b,c.dur)-a,0),0);
    $('legend').innerHTML=`<span title="绿色 = 用在成片里"><i class="sw" style="background:var(--used)"></i>用在成片 <b>${fmt(u)}</b> / ${fmt(total)}</span>
      <span title="灰色 = 没用上"><i class="sw" style="background:var(--unused)"></i>没用上</span>`;
  }else $('legend').textContent='还没有剪辑方案（edl.json），剪好后这里会标出用上的部分';
}
async function loadUsage(){
  try{const r=await (await fetch('/api/usage')).json();hasEdl=r.has_edl;used=r.used;renderUsage()}catch(e){}}

function build(){
  starts=[];total=0;clips.forEach(c=>{starts.push(total);total+=c.dur||0});
  $('count').textContent=clips.length;
  $('hmeta').innerHTML=`<b>${clips.length}</b> 段 · 共 <b>${fmt(total)}</b>`;
  $('tl').innerHTML=clips.map((c,i)=>`<div class="seg${i&&c.day!==clips[i-1].day?' day0':''}" style="width:${(c.dur||0)/total*100}%"></div>`).join('');
  $('list').innerHTML=clips.map((c,i)=>(i===0||c.day!==clips[i-1].day?`<div class="dayhead">第${c.day}天</div>`:'')+`<div class="item" data-i="${i}" title="相机时钟 ${esc(c.clock)}（可能不准）">
    <img loading="lazy" data-src="/thumb/${encodeURIComponent(c.clip)}" alt="">
    <div style="min-width:0"><div class="t"><b>${esc(c.clip)}</b><span class="m">${esc(c.when.replace(/^第\d+天 · /,''))} · ${fmt(c.dur)}</span></div>
    <div class="ub"></div><div class="first">${c.first?esc(c.first):'<span class="none">（无字幕）</span>'}</div></div></div>`).join('');
  $('list').querySelectorAll('.item').forEach(el=>el.onclick=()=>show(+el.dataset.i,0,true));
  const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){const im=e.target;im.src=im.dataset.src;io.unobserve(im)}}),{root:$('list'),rootMargin:'300px'});
  $('list').querySelectorAll('img').forEach(im=>io.observe(im));
  $('speeds').innerHTML=SPEEDS.map(s=>`<button data-s="${s}">${s}x</button>`).join('');
  $('speeds').querySelectorAll('button').forEach(b=>b.onclick=()=>setSpeed(+b.dataset.s));
}

const tl=$('tl');
function tlAt(e){const r=tl.getBoundingClientRect();return Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*total}
tl.addEventListener('click',e=>jumpGlobal(tlAt(e)));
tl.addEventListener('mousemove',e=>{const g=tlAt(e);let i=0;while(i+1<clips.length&&starts[i+1]<=g)i++;
  const h=$('hover');h.style.display='block';h.style.left=(g/total*100)+'%';
  h.textContent=`${fmt(g)} · ${clips[i].clip} ${clips[i].when}`});
tl.addEventListener('mouseleave',()=>$('hover').style.display='none');
$('play').onclick=toggle;
const stage=$('stage'),ov=$('ov');
stage.addEventListener('click',toggle);
stage.addEventListener('dblclick',e=>{if(!ov.contains(e.target))toggleFs()});
ov.addEventListener('click',e=>e.stopPropagation());
ov.addEventListener('dblclick',e=>e.stopPropagation());
// YouTube-style auto-hide: visible while paused, on mouse movement, or hovering the controls
const PIN=new URLSearchParams(location.search).has('ctl');
let hideT=0;
let lastUse=0, swapping=false;   // last time the viewer touched the controls; clip hand-off in progress
function showCtl(){lastUse=Date.now();stage.classList.add('ctl');clearTimeout(hideT);hideT=setTimeout(maybeHide,2500)}
// Don't hide while the viewer is using the controls (e.g. picking a speed right as the next clip
// starts): the new clip's 'play' event used to restart the timer and fold the bar mid-click.
function maybeHide(){if(PIN||cur.paused||ov.matches(':hover'))return;
  const idle=Date.now()-lastUse; if(idle<2500){clearTimeout(hideT);hideT=setTimeout(maybeHide,2600-idle);return}
  stage.classList.remove('ctl')}
['mousedown','touchstart','wheel'].forEach(ev=>stage.addEventListener(ev,()=>{lastUse=Date.now()},{passive:true,capture:true}));
stage.addEventListener('mousemove',showCtl);
stage.addEventListener('mouseleave',()=>{clearTimeout(hideT);if(!PIN&&!cur.paused)stage.classList.remove('ctl')});
function toggleFs(){window.cbFs.toggle()}   // fullscreen = video + chat rail (chat.py)
$('fs').onclick=toggleFs;
// don't let a focused button also react to Space/keys
document.addEventListener('mouseup',()=>{const a=document.activeElement;if(a&&a.tagName==='BUTTON')a.blur()});
window.addEventListener('cbfs',fsUI);
// shortcuts popover (also opens on hover) and the rail tabs
$('keysBtn').onclick=e=>{e.stopPropagation();$('keys').classList.toggle('open')};
document.addEventListener('click',e=>{if(!$('keys').contains(e.target))$('keys').classList.remove('open')});
$('keys').addEventListener('mouseleave',()=>$('keys').classList.remove('open'));
document.addEventListener('keydown',e=>{if(e.key==='Escape')$('keys').classList.remove('open')});
function setTab(t){document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('on',b.dataset.tab===t));
  ['list','qpanel'].forEach(id=>$(id).hidden=id!==t);try{localStorage.setItem('fp_tab',t)}catch(e){}
  if(t==='list')markCurrent()}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));

// Buttons never keep keyboard focus from a mouse click, and Space is swallowed on keyup too —
// browsers "click" a focused button on Space *keyup*, so blocking keydown alone isn't enough
// (Space after clicking fullscreen used to exit fullscreen instead of pausing).
document.addEventListener('mousedown',e=>{if(e.target.closest&&e.target.closest('button'))e.preventDefault()},true);
document.addEventListener('keyup',e=>{if(e.code==='Space'&&!/INPUT|SELECT|TEXTAREA/.test(e.target.tagName))e.preventDefault()},true);
document.addEventListener('keydown',e=>{
  if(e.metaKey||e.ctrlKey||e.altKey||!clips.length)return;
  if(e.target.closest&&e.target.closest('textarea,input[type=text]'))return;  // typing an answer
  const k=e.key;
  if(k===' '){toggle()}
  else if(k==='ArrowLeft')seekBy(-5);
  else if(k==='ArrowRight')seekBy(5);
  else if(k==='ArrowUp')show(idx-1,0);
  else if(k==='ArrowDown')show(idx+1,0);
  else if(k>='1'&&k<='5'){setSpeed(SPEEDS[+k-1]);showCtl()}  // show the bar so the new speed is visible
  else if(k==='f'||k==='F')toggleFs();
  else return;
  e.preventDefault();e.stopPropagation()},true);

let lastCapKey='';
function tick(){
  if(clips.length){
    const c=clips[idx],t=cur.currentTime||0,g=starts[idx]+t;
    $('ph').style.left=(g/total*100)+'%';
    $('gtime').textContent=`${fmt(g)} / ${fmt(total)}`;   // YouTube-style: whole trip
    $('info').innerHTML=`${idx+1}/${clips.length} · ${esc(c.clip)} · <span title="相机时钟 ${esc(c.clock)}（可能不准）">${esc(c.when)}</span> · 本段 ${fmt(t)} / ${fmt(c.dur)}`;
    const p=srtCache[c.clip];
    if(p&&p.v!==undefined){
      const line=p.v.find(s=>t>=s.t0&&t<s.t1);
      const key=c.clip+'|'+(line?line.text:'');
      if(key!==lastCapKey){lastCapKey=key;
        $('cap').innerHTML=line?'<span>'+esc(line.text)+'</span>':''}
    }else if(p&&!p.w){p.w=1;p.then(v=>p.v=v)}
  }
  requestAnimationFrame(tick)}
setInterval(updEst,2000);

(async()=>{
  clips=await (await fetch('/api/clips')).json();
  if(!clips.length){$('msg').textContent='没找到素材（01 - Unedited 里没有 MP4）';return}
  build();setSpeed(speed);
  let su=true;try{su=localStorage.getItem('fp_showuse2')!=='0'}catch(e){}
  $('showuse').checked=su;document.body.classList.toggle('showuse',su);
  $('showuse').onchange=e=>{document.body.classList.toggle('showuse',e.target.checked);
    try{localStorage.setItem('fp_showuse2',e.target.checked?'1':'0')}catch(_){}};await loadUsage();
  $('msg').textContent='';show(0,0,false);requestAnimationFrame(tick);
  setInterval(loadUsage,10000);
  initQA();
  let t0='list';try{if(localStorage.getItem('fp_tab')==='qpanel')t0='qpanel'}catch(e){}
  if(t0!=='list')setTab(t0);
})();
// ---- questions for the creator, popping up beside the video at their raw-clip time
function initQA(){
  const pos=q=>{if(!q.clip||typeof q.clip_t!=='number')return null;
    const i=clips.findIndex(c=>c.clip===q.clip);return i<0?null:starts[i]+Math.min(q.clip_t,clips[i].dur||q.clip_t)};
  const api=initQuestions({
    root:$('qpanel'), card:$('qcard'), pos,
    count:(open,n)=>{const e=$('qcount');e.textContent=open||n;e.classList.toggle('open',open>0);
      if(!n&&!$('qpanel').hidden)setTab('list')},
    now:()=>clips.length&&cur.readyState>=1?starts[idx]+(cur.currentTime||0):null,
    playing:()=>!cur.paused&&!cur.ended,
    pause:()=>cur.pause(),
    seek:g=>{let i=0;while(i+1<clips.length&&starts[i+1]<=g)i++;show(i,g-starts[i],true)},
    label:q=>`${q.clip} · ${fmt(q.clip_t)}`,
    markers:it=>{$('qms').innerHTML=total?it.map(({q,p})=>`<div class="qm${q.answer?' done':''}" data-id="${esc(q.id)}" style="left:${p/total*100}%" title="${esc(q.clip+' · '+fmt(q.clip_t)+' '+q.text)}"></div>`).join(''):''},
  });
  $('qms').addEventListener('click',e=>{const m=e.target.closest('.qm');if(m)api.jump(m.dataset.id)});
}
// tab title follows playback: "▶ 12/79 · 81 - USVI · 原片预览"
setInterval(()=>{if(!clips.length)return;
  document.title=(cur.paused?'':'▶ ')+(idx+1)+'/'+clips.length+' · '+PNAME+' · 原片预览'},1000);
</script>
<script>
__QA_JS__
</script><script>(function(){const L=document.getElementById('lists'),b=document.getElementById('listTog');
let open=false;try{open=localStorage.getItem('fp_lists_open')==='1'}catch(e){}
const set=o=>{open=o;L.classList.toggle('closed',!o);b.textContent=o?'收起 ▴':'展开 ▾';try{localStorage.setItem('fp_lists_open',o?'1':'0')}catch(e){}};
set(open);b.addEventListener('click',e=>{e.stopPropagation();set(!open)});
document.querySelectorAll('.tabs .tab[data-tab]').forEach(t=>t.addEventListener('click',()=>{if(!open)set(true)}));})();</script></body></html>
"""
PAGE = CHAT.inject(QS.inject(PAGE.replace("__THEME_CSS__", THEME.CSS)).replace("</body>", "<script>window.chatCtx=()=>({clip:(clips[idx]||{}).clip,clip_t:Math.round((cur.currentTime||0)*10)/10})</script></body>", 1), "raw")


def main():
    global PROJECT
    ap = argparse.ArgumentParser(description="Watch all raw clips of a trip back-to-back")
    ap.add_argument("project", help="project folder name under ~/Desktop, or a path")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    PROJECT = os.path.abspath(E.project_dir(a.project))
    if not os.path.isdir(PROJECT):
        raise SystemExit(f"No project folder: {PROJECT}")
    n = len(clip_list())
    print(f"{n} clips in {source_dir()}")
    print(f"Footage player: http://{a.host}:{a.port}/")
    app.run(host=a.host, port=a.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
