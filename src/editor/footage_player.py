"""Raw footage player: watch every unedited clip of a trip back-to-back.

    ./venv/bin/python -m src.editor.footage_player "<project>" [--port 8766]

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

CACHE_ROOT = "/tmp/yt-editor"
DEFAULT_SOURCE = "01 - Unedited"

app = Flask(__name__)
PROJECT = None            # absolute project dir
_lock = threading.Lock()
_clips = {"key": None, "list": []}
_thumb_sem = threading.Semaphore(3)


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
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1d2330;--mute:#6b7280;--line:#e3e6eb;
  --used:#22a55a;--unused:#c9ced6;--accent:#2563eb;--cur:#eaf1ff}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
  font:14px/1.45 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",sans-serif}
.app{display:grid;grid-template-columns:1fr 340px;height:100vh}
main{display:flex;flex-direction:column;padding:14px 18px;min-width:0;overflow:hidden}
header{display:flex;align-items:baseline;gap:14px;margin-bottom:8px}
header h1{font-size:17px;margin:0}
header .est{color:var(--mute)}
.sub{color:var(--mute);margin:-4px 0 10px}
.tog{display:inline-flex;align-items:center;gap:5px;cursor:pointer;user-select:none}
body:not(.showuse) .seg .u,body:not(.showuse) .item .ub,body:not(.showuse) .legend{display:none}
.dayhead{padding:6px 12px;background:#f3f4f6;color:var(--mute);font-size:12px;font-weight:600;
  border-bottom:1px solid var(--line);position:sticky;top:0;z-index:1}
.stage{position:relative;flex:1;min-height:0;background:#000;border-radius:10px;overflow:hidden;
  container-type:size;cursor:default}
.stage:fullscreen{border-radius:0}
.stage:not(.ctl){cursor:none}
.stage video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000}
.stage video.hidden{visibility:hidden}
.stage .msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:#bbb;font-size:16px;pointer-events:none}
.cap{position:absolute;left:50%;bottom:5%;transform:translateX(-50%);width:84%;text-align:center;
  pointer-events:none;transition:bottom .2s ease;z-index:3;
  font-size:clamp(14px,2.4cqw,44px);font-weight:500;line-height:1.4}
.cap span{background:rgba(8,8,8,.75);color:#fff;padding:.1em .45em;border-radius:3px;
  -webkit-box-decoration-break:clone;box-decoration-break:clone}
.cap:empty{display:none}
.bigplay{position:absolute;left:50%;top:50%;width:84px;height:84px;margin:-42px 0 0 -42px;border-radius:50%;background:rgba(0,0,0,.55);pointer-events:none;z-index:3;transition:opacity .2s ease,transform .2s ease}.bigplay::after{content:'';position:absolute;left:33px;top:24px;border-style:solid;border-width:18px 0 18px 30px;border-color:transparent transparent transparent #fff}.bigplay.hide{opacity:0;transform:scale(1.25)}
.stage.ctl .cap{bottom:calc(96px + 3%)}
.ov{position:absolute;left:0;right:0;bottom:0;padding:44px 16px 10px;z-index:4;color:#fff;
  background:linear-gradient(to bottom,transparent,rgba(0,0,0,.65));
  opacity:0;pointer-events:none;transition:opacity .25s ease}
.stage.ctl .ov{opacity:1;pointer-events:auto}
.bar{display:flex;align-items:center;gap:12px;margin-top:8px}
.gtime{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
.info{font-size:12.5px;color:rgba(255,255,255,.78);font-variant-numeric:tabular-nums;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.spacer{flex:1}
button{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);
  border-radius:7px;padding:5px 11px;cursor:pointer}
.ov button{background:transparent;color:#fff;border-color:rgba(255,255,255,.35);padding:4px 10px;white-space:nowrap}
.ov button:hover{background:rgba(255,255,255,.15);border-color:rgba(255,255,255,.6)}
.ov button.on{background:#fff;border-color:#fff;color:#111}
.ov #play{min-width:78px;font-weight:600}
.speeds{display:flex;gap:5px}
.tl-row{position:relative}
.tl{position:relative;height:10px;border-radius:3px;cursor:pointer;overflow:hidden;display:flex;
  transition:height .15s ease}
.tl-row:hover .tl{height:16px}
.seg{position:relative;height:100%;background:rgba(255,255,255,.38);border-right:1px solid rgba(0,0,0,.45)}
body.showuse .seg{background:rgba(255,255,255,.22)}
body.showuse .seg.noedl{background:rgba(255,255,255,.38)}
.seg.day0{border-left:3px solid #fff}
.seg .u{position:absolute;top:0;bottom:0;background:#34d27a}
.seg.cur{background:rgba(255,255,255,.62)}
body.showuse .seg.cur{background:rgba(255,255,255,.4)}
.ph{position:absolute;top:-4px;bottom:-4px;width:3px;margin-left:-1px;background:#ff2d55;
  border-radius:2px;pointer-events:none;z-index:2}
.hover{position:absolute;bottom:22px;transform:translateX(-50%);background:rgba(20,20,20,.9);color:#fff;
  font-size:12px;padding:2px 7px;border-radius:4px;white-space:nowrap;pointer-events:none;display:none}
.below{display:flex;align-items:center;gap:16px;flex-wrap:wrap;color:var(--mute);font-size:12px;margin-top:8px}
.legend{display:flex;gap:12px;align-items:center}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:-1px;margin-right:4px}
aside{border-left:1px solid var(--line);background:var(--panel);display:flex;flex-direction:column;min-height:0}
aside .head{padding:12px 14px;border-bottom:1px solid var(--line);font-weight:600}
aside .head span{color:var(--mute);font-weight:400}
.list{overflow-y:auto;flex:1}
.item{display:grid;grid-template-columns:96px 1fr;gap:9px;padding:8px 12px;
  border-bottom:1px solid #f0f1f4;cursor:pointer}
.item:hover{background:#f7f9fc}
.item.cur{background:var(--cur)}
.item img{width:96px;height:54px;object-fit:cover;border-radius:5px;background:#e5e7eb;display:block}
.item .t{display:flex;gap:6px;align-items:baseline;font-size:13px}
.item .t b{font-weight:600}
.item .t .m{color:var(--mute);font-size:12px;font-variant-numeric:tabular-nums}
.item .ub{position:relative;height:5px;background:var(--unused);border-radius:3px;margin:4px 0;overflow:hidden}
.item .ub.noedl{background:#e5e7eb}
.item .ub i{position:absolute;top:0;bottom:0;background:var(--used)}
.item .first{color:var(--mute);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
</style></head><body>
<div class="app">
<main>
  <header><h1 id="h1">原片预览 · __TITLE__</h1><span class="est" id="est"></span></header>
  <div class="sub">按拍摄顺序连播全部原片，可倍速快速浏览</div>
  <div class="stage ctl" id="stage">
    <video id="va" playsinline preload="auto"></video>
    <video id="vb" class="hidden" playsinline preload="auto" muted></video>
    <div class="msg" id="msg">加载中…</div>
    <div class="bigplay" id="bigplay"></div>
    <div class="cap" id="cap"></div>
    <div class="ov" id="ov">
      <div class="tl-row"><div class="tl" id="tl"></div><div class="ph" id="ph"></div>
        <div class="hover" id="hover"></div></div>
      <div class="bar">
        <button id="play">▶ 播放</button>
        <div class="gtime" id="gtime">0:00 / 0:00</div>
        <div class="info" id="info"></div>
        <div class="spacer"></div>
        <div class="speeds" id="speeds"></div>
        <button id="fs" title="全屏（F）">⛶ 全屏</button>
      </div>
    </div>
  </div>
  <div class="below">
    <span>空格 播放/暂停 · ←/→ 快退/快进 5 秒 · ↑/↓ 上一段/下一段 · 1–5 切换速度 · F 全屏 · 点进度条任意位置跳过去</span>
    <span class="spacer"></span><span class="legend" id="legend"></span>
    <label class="tog"><input type="checkbox" id="showuse">显示成片用到的部分</label>
  </div>
</main>
<aside><div class="head">全部片段 <span id="count"></span></div><div class="list" id="list"></div></aside>
</div>
<script>
const SPEEDS=[1,1.25,1.5,2,3];
const PNAME=document.title.replace(/ · 原片预览$/,'');
let clips=[], starts=[], total=0, idx=0, used={}, hasEdl=false, speed=2;
const srtCache={};
const $=id=>document.getElementById(id);
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
    cur.pause();const old=cur;cur=nxt;nxt=old;
    cur.classList.remove('hidden');nxt.classList.add('hidden');
    cur.muted=false;nxt.removeAttribute('src');nxt.load();nxtIdx=-1;
  }else if(i!==idx||!cur.getAttribute('src')){prepare(cur,i)}
  idx=i;cur.playbackRate=speed;
  const seek=()=>{if(t)cur.currentTime=Math.min(t,Math.max(0,(clips[i].dur||0)-0.05))};
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
  if(idx+1<clips.length)show(idx+1,0,true);else{$('play').textContent='▶ 播放'}}

[$('va'),$('vb')].forEach(v=>{
  v.addEventListener('ended',onEnded);
  v.addEventListener('play',()=>{if(v===cur){$('play').textContent='⏸ 暂停';clearTimeout(hideT);hideT=setTimeout(maybeHide,2500)}});
  v.addEventListener('pause',()=>{if(v===cur){$('play').textContent='▶ 播放';stage.classList.add('ctl')}});
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
    $('legend').innerHTML=`<span><span class="sw" style="background:var(--used)"></span>绿色=用在成片里</span>
      <span><span class="sw" style="background:var(--unused)"></span>灰色=没用上</span><span>已用 ${fmt(u)} / ${fmt(total)}</span>`;
  }else $('legend').textContent='还没有剪辑方案（edl.json），剪好后这里会标出用上的部分';
}
async function loadUsage(){
  try{const r=await (await fetch('/api/usage')).json();hasEdl=r.has_edl;used=r.used;renderUsage()}catch(e){}}

function build(){
  starts=[];total=0;clips.forEach(c=>{starts.push(total);total+=c.dur||0});
  $('count').textContent=`（${clips.length} 段 · ${fmt(total)}）`;
  $('h1').textContent=`原片预览 · ${PNAME} · ${clips.length} 段 · ${fmt(total)}`;
  $('tl').innerHTML=clips.map((c,i)=>`<div class="seg${i&&c.day!==clips[i-1].day?' day0':''}" style="width:${(c.dur||0)/total*100}%"></div>`).join('');
  $('list').innerHTML=clips.map((c,i)=>(i===0||c.day!==clips[i-1].day?`<div class="dayhead">第${c.day}天</div>`:'')+`<div class="item" data-i="${i}" title="相机时钟 ${esc(c.clock)}（可能不准）">
    <img loading="lazy" data-src="/thumb/${encodeURIComponent(c.clip)}" alt="">
    <div style="min-width:0"><div class="t"><b>${esc(c.clip)}</b><span class="m">${esc(c.when.replace(/^第\d+天 · /,''))} · ${fmt(c.dur)}</span></div>
    <div class="ub"></div><div class="first">${c.first?esc(c.first):'<span style="color:#c0c4cc">（无字幕）</span>'}</div></div></div>`).join('');
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
function showCtl(){stage.classList.add('ctl');clearTimeout(hideT);hideT=setTimeout(maybeHide,2500)}
function maybeHide(){if(PIN||cur.paused||ov.matches(':hover'))return;stage.classList.remove('ctl')}
stage.addEventListener('mousemove',showCtl);
stage.addEventListener('mouseleave',()=>{clearTimeout(hideT);if(!PIN&&!cur.paused)stage.classList.remove('ctl')});
function toggleFs(){
  if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});
  else (stage.requestFullscreen||stage.webkitRequestFullscreen).call(stage)}
$('fs').onclick=toggleFs;
// don't let a focused button also react to Space/keys
document.addEventListener('mouseup',()=>{const a=document.activeElement;if(a&&a.tagName==='BUTTON')a.blur()});
document.addEventListener('fullscreenchange',()=>{$('fs').textContent=document.fullscreenElement?'退出全屏':'⛶ 全屏'});

// Buttons never keep keyboard focus from a mouse click, and Space is swallowed on keyup too —
// browsers "click" a focused button on Space *keyup*, so blocking keydown alone isn't enough
// (Space after clicking fullscreen used to exit fullscreen instead of pausing).
document.addEventListener('mousedown',e=>{if(e.target.closest&&e.target.closest('button'))e.preventDefault()},true);
document.addEventListener('keyup',e=>{if(e.code==='Space'&&!/INPUT|SELECT|TEXTAREA/.test(e.target.tagName))e.preventDefault()},true);
document.addEventListener('keydown',e=>{
  if(e.metaKey||e.ctrlKey||e.altKey||!clips.length)return;
  const k=e.key;
  if(k===' '){toggle()}
  else if(k==='ArrowLeft')seekBy(-5);
  else if(k==='ArrowRight')seekBy(5);
  else if(k==='ArrowUp')show(idx-1,0);
  else if(k==='ArrowDown')show(idx+1,0);
  else if(k>='1'&&k<='5')setSpeed(SPEEDS[+k-1]);
  else if(k==='f'||k==='F')toggleFs();
  else return;
  e.preventDefault();e.stopPropagation()},true);

let lastCapKey='';
function tick(){
  if(clips.length){
    const c=clips[idx],t=cur.currentTime||0,g=starts[idx]+t;
    $('ph').style.left=(g/total*100)+'%';
    $('gtime').textContent=`${fmt(g)} / ${fmt(total)}`;   // YouTube-style: whole trip
    $('info').innerHTML=`第 ${idx+1}/${clips.length} 段 · ${esc(c.clip)} · <span title="相机时钟 ${esc(c.clock)}（可能不准）">${esc(c.when)}</span> · 本段 ${fmt(t)} / ${fmt(c.dur)}`;
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
  let su=false;try{su=localStorage.getItem('fp_showuse')==='1'}catch(e){}
  $('showuse').checked=su;document.body.classList.toggle('showuse',su);
  $('showuse').onchange=e=>{document.body.classList.toggle('showuse',e.target.checked);
    try{localStorage.setItem('fp_showuse',e.target.checked?'1':'0')}catch(_){}};await loadUsage();
  $('msg').textContent='';show(0,0,false);requestAnimationFrame(tick);
  setInterval(loadUsage,10000);
})();
// tab title follows playback: "▶ 12/79 · 81 - USVI · 原片预览"
setInterval(()=>{if(!clips.length)return;
  document.title=(cur.paused?'':'▶ ')+(idx+1)+'/'+clips.length+' · '+PNAME+' · 原片预览'},1000);
</script></body></html>
"""


def main():
    global PROJECT
    ap = argparse.ArgumentParser(description="Watch all raw clips of a trip back-to-back")
    ap.add_argument("project", help="project folder name under ~/Desktop, or a path")
    ap.add_argument("--port", type=int, default=8766)
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
