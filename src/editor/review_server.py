"""Local review/edit page for an auto-assembled vlog EDL.

    ./venv/bin/python -m src.editor.review_server "<project>" [--port 8765]

Serves one self-contained HTML page (no CDN) where the creator trims, reorders, splits
and re-captions shots, then saves the EDL and kicks off the renderer:

    python -m src.editor.render "<project>" --preview | --final

The renderer is expected to write `<project>/02 - Export/edit/render_status.json`:
    {"state": "running|done|error", "step": "...", "progress": 0.0-1.0,
     "output": "path", "error": "..."}
Preview output is read from `<project>/02 - Export/edit/preview.mp4`.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time

from flask import Flask, Response, abort, jsonify, request, send_file

from . import edl as E

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_ROOT = "/tmp/yt-editor"

app = Flask(__name__)
PROJECT = None          # project dir (absolute)
RENDER = {"proc": None, "mode": None, "log": None}
_durations = {}
_thumb_sem = threading.Semaphore(4)


# ---------------------------------------------------------------- helpers

def edit_dir():
    return E.edit_dir(PROJECT)


def status_path():
    return os.path.join(edit_dir(), "render_status.json")


def preview_path():
    return os.path.join(edit_dir(), "preview.mp4")


def src_clip(edl, clip):
    """Resolve a clip against the project dir this server was started with."""
    return E.clip_path(dict(edl, project=PROJECT), clip)


def thumb_dir():
    d = os.path.join(CACHE_ROOT, os.path.basename(PROJECT.rstrip("/")), "thumbs")
    os.makedirs(d, exist_ok=True)
    return d


def probe_duration(path):
    if path in _durations:
        return _durations[path]
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30).stdout.strip()
        d = float(out)
    except Exception:
        d = None
    _durations[path] = d
    return d


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate(edl):
    errs = []
    if not isinstance(edl, dict) or not isinstance(edl.get("shots"), list):
        return ["EDL 格式错误：缺少 shots 列表"]
    ids = set()
    grades = edl.get("grades") or {}
    for i, s in enumerate(edl["shots"], 1):
        p = f"镜头 #{i}"
        if not isinstance(s, dict):
            errs.append(f"{p}: 格式错误")
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not sid:
            errs.append(f"{p}: 缺少 id")
        elif sid in ids:
            errs.append(f"{p}: id {sid} 重复")
        ids.add(sid)
        clip = s.get("clip")
        if not isinstance(clip, str) or not clip or "/" in clip or ".." in clip:
            errs.append(f"{p}: clip 无效")
        elif not os.path.isfile(src_clip(edl, clip)):
            errs.append(f"{p}: 找不到素材 {clip}.MP4")
        a, b = s.get("in"), s.get("out")
        if not (_num(a) and _num(b)):
            errs.append(f"{p}: 入点/出点必须是数字")
        elif a < 0 or a >= b:
            errs.append(f"{p}: 入点必须 ≥0 且小于出点 ({a} / {b})")
        if not isinstance(s.get("enabled", True), bool):
            errs.append(f"{p}: enabled 必须是布尔值")
        if s.get("audio", "voice") not in E.AUDIO_GAIN:
            errs.append(f"{p}: audio 必须是 {'/'.join(E.AUDIO_GAIN)}")
        if grades and s.get("grade", "default") not in grades:
            errs.append(f"{p}: 未知调色 {s.get('grade')}")
        t = s.get("title")
        if t is not None and not (isinstance(t, dict) and isinstance(t.get("text", ""), str)):
            errs.append(f"{p}: title 格式错误")
        subs = s.get("subs", [])
        if not isinstance(subs, list):
            errs.append(f"{p}: subs 必须是列表")
            continue
        for j, x in enumerate(subs, 1):
            if not (isinstance(x, dict) and _num(x.get("t0")) and _num(x.get("t1"))
                    and isinstance(x.get("text"), str)):
                errs.append(f"{p} 字幕 {j}: 格式错误")
            elif x["t0"] >= x["t1"]:
                errs.append(f"{p} 字幕 {j}: 开始时间必须小于结束时间")
    return errs


def read_status():
    try:
        with open(status_path(), encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    proc = RENDER["proc"]
    running = False
    if proc is not None:
        rc = proc.poll()
        if rc is None:
            running = True
            st.setdefault("state", "running")
        elif rc != 0 and st.get("state") != "error":
            st = {"state": "error", "error": f"渲染器退出码 {rc}\n" + log_tail()}
        elif rc == 0 and st.get("state") == "running":
            st["state"] = "done"
    st["active"] = running
    st["mode"] = RENDER["mode"]
    return st


def log_tail(n=15):
    try:
        with open(RENDER["log"], encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except Exception:
        return ""


# ---------------------------------------------------------------- routes

@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.get("/api/edl")
def api_edl():
    return jsonify(E.load(PROJECT))


@app.get("/api/durations")
def api_durations():
    edl = E.load(PROJECT)
    clips = sorted({s["clip"] for s in edl["shots"]})
    return jsonify({c: probe_duration(src_clip(edl, c)) for c in clips})


@app.post("/api/save")
def api_save():
    new = request.get_json(silent=True)
    old = E.load(PROJECT)
    if isinstance(new, dict):
        # identity of the project isn't editable from the page
        for k in ("project", "source_dir"):
            if k in old:
                new[k] = old[k]
    errs = validate(new)
    if errs:
        return jsonify({"ok": False, "errors": errs}), 400
    if new == old:
        return jsonify({"ok": True, "unchanged": True})
    hist = os.path.join(edit_dir(), "history")
    os.makedirs(hist, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(hist, f"edl-{stamp}.json")
    k = 1
    while os.path.exists(dst):
        k += 1
        dst = os.path.join(hist, f"edl-{stamp}-{k}.json")
    shutil.copy2(E.edl_path(PROJECT), dst)
    E.save(PROJECT, new)
    return jsonify({"ok": True, "backup": os.path.basename(dst)})


@app.post("/api/render")
def api_render():
    mode = (request.get_json(silent=True) or {}).get("mode", "preview")
    if mode not in ("preview", "final"):
        return jsonify({"ok": False, "error": "mode 必须是 preview 或 final"}), 400
    if RENDER["proc"] is not None and RENDER["proc"].poll() is None:
        return jsonify({"ok": False, "error": "已有渲染任务在运行"}), 409
    if not os.path.isfile(os.path.join(REPO, "src", "editor", "render.py")):
        return jsonify({"ok": False, "error": "渲染模块 src/editor/render.py 尚不存在，无法渲染"}), 503
    os.makedirs(edit_dir(), exist_ok=True)
    with open(status_path(), "w", encoding="utf-8") as f:
        json.dump({"state": "running", "step": "启动渲染器…", "progress": 0.0}, f)
    RENDER["log"] = os.path.join(edit_dir(), "render.log")
    log = open(RENDER["log"], "w", encoding="utf-8")
    try:
        RENDER["proc"] = subprocess.Popen(
            [sys.executable, "-m", "src.editor.render", PROJECT, f"--{mode}"],
            cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
    except Exception as e:
        return jsonify({"ok": False, "error": f"无法启动渲染器: {e}"}), 500
    finally:
        log.close()
    RENDER["mode"] = mode
    return jsonify({"ok": True})


@app.get("/api/render_status")
def api_render_status():
    return jsonify(read_status())


@app.get("/preview.mp4")
def preview():
    p = preview_path()
    if not os.path.isfile(p):
        abort(404)
    return send_file(p, mimetype="video/mp4", conditional=True, max_age=0)


@app.get("/clip/<name>")
def clip(name):
    if "/" in name or ".." in name:
        abort(400)
    p = src_clip(E.load(PROJECT), name)
    if not os.path.isfile(p):
        abort(404)
    return send_file(p, mimetype="video/mp4", conditional=True)


@app.get("/thumb")
def thumb():
    name = request.args.get("clip", "")
    try:
        t = max(0.0, round(float(request.args.get("t", "0")), 1))
    except ValueError:
        abort(400)
    if not name or "/" in name or ".." in name:
        abort(400)
    src = src_clip(E.load(PROJECT), name)
    if not os.path.isfile(src):
        abort(404)
    out = os.path.join(thumb_dir(), f"{name}_{t:.1f}.jpg")
    if not os.path.isfile(out):
        with _thumb_sem:
            if not os.path.isfile(out):
                tmp = out + ".tmp.jpg"
                for tt in (t, max(0.0, t - 0.5), max(0.0, t - 1.5)):
                    subprocess.run(
                        ["ffmpeg", "-v", "error", "-y", "-ss", f"{tt:.2f}", "-i", src,
                         "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "5", tmp],
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
<title>剪辑审阅</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--text:#1d2329;--mut:#6b7580;--acc:#2563eb;--acc2:#dbe6fd;--warn:#b42318;--ok:#067647}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif}
button,input,select,textarea{font:inherit}
button{border:1px solid var(--line);background:#fff;border-radius:6px;padding:4px 10px;cursor:pointer;color:var(--text)}
button:hover{border-color:#b9c0c8;background:#fafbfc}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff}
button.pri:hover{background:#1d4ed8}
button.sm{padding:1px 7px;font-size:12px}
button:disabled{opacity:.5;cursor:default}
input[type=number]{width:78px}
input,select,textarea{border:1px solid var(--line);border-radius:5px;padding:3px 6px;background:#fff}
input:focus,select:focus,textarea:focus{outline:2px solid var(--acc2);border-color:var(--acc)}
input.bad{border-color:var(--warn);background:#fef3f2}
#bar{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.95);backdrop-filter:blur(6px);border-bottom:1px solid var(--line);padding:10px 20px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
#bar h1{font-size:16px;margin:0;font-weight:600}
#total{font-variant-numeric:tabular-nums;color:var(--mut)}
#total b{color:var(--text)}
#dirty{color:var(--warn);font-size:12px;display:none}
.sp{flex:1}
#rs{display:none;align-items:center;gap:8px;font-size:12px;color:var(--mut)}
#rs .pb{width:160px;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
#rs .pb i{display:block;height:100%;background:var(--acc);width:0}
#rs.err{color:var(--warn)}
#rs.done{color:var(--ok)}
main{max-width:1180px;margin:0 auto;padding:16px 20px 80px}
#pv{background:#000;border-radius:10px;overflow:hidden;margin-bottom:16px;display:flex;justify-content:center;align-items:center;min-height:120px}
#pv video{width:100%;max-height:52vh;display:block}
#pv .none{color:#aaa;padding:40px}
#errbox{display:none;white-space:pre-wrap;background:#fef3f2;border:1px solid #fecdca;color:var(--warn);border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:12px}
.shot{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:10px;padding:12px;display:grid;grid-template-columns:44px 330px 1fr;gap:12px}
.shot.off{opacity:.45;background:#f0f1f3}
.shot.off .thumbs img{filter:grayscale(1)}
.idx{text-align:center}
.idx .n{font-weight:600;font-size:16px}
.idx .st{font-variant-numeric:tabular-nums;color:var(--acc);font-size:12px}
.idx .du{font-variant-numeric:tabular-nums;color:var(--mut);font-size:11px}
.idx button{display:block;margin:4px auto 0;width:30px;padding:0}
.thumbs{display:flex;gap:3px}
.thumbs figure{margin:0;flex:1;position:relative}
.thumbs img{width:100%;aspect-ratio:16/9;object-fit:cover;background:#dde1e6;border-radius:4px;display:block}
.thumbs figcaption{position:absolute;left:3px;bottom:3px;font-size:10px;color:#fff;background:rgba(0,0,0,.55);padding:0 4px;border-radius:3px;font-variant-numeric:tabular-nums}
.meta .clip{font-weight:600;font-family:ui-monospace,Menlo,monospace;font-size:13px}
.meta .sid{color:var(--mut);font-size:11px;margin-left:6px}
.meta .note{color:var(--mut);margin:3px 0 8px;font-size:13px}
.ctl{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin-bottom:8px}
.ctl label{display:inline-flex;align-items:center;gap:4px;color:var(--mut);font-size:12px}
.ctl .grp{display:inline-flex;align-items:center;gap:2px}
.ctl .grp button{padding:1px 6px}
.ttl{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px}
.ttl input{width:170px}
.ttl input.dur{width:60px}
.ttl span{color:var(--mut);font-size:12px}
.subs{grid-column:2/4;border-top:1px dashed var(--line);padding-top:8px}
.subs .hd{display:flex;align-items:center;gap:8px;color:var(--mut);font-size:12px;margin-bottom:4px}
.sub{display:flex;gap:6px;align-items:center;margin-bottom:4px}
.sub input[type=number]{width:72px}
.sub input.tx{flex:1}
.sub.out{opacity:.4}
.sub.out input.tx{text-decoration:line-through}
#modal{position:fixed;inset:0;background:rgba(10,14,20,.72);display:none;align-items:center;justify-content:center;z-index:50}
#modal .box{background:#fff;border-radius:12px;padding:14px;width:min(1000px,92vw)}
#modal video{width:100%;max-height:70vh;background:#000;border-radius:8px;display:block}
#modal .row{display:flex;gap:10px;align-items:center;margin-top:10px;flex-wrap:wrap}
#mt{font-variant-numeric:tabular-nums;color:var(--mut)}
.hint{color:var(--mut);font-size:12px}
</style></head><body>
<div id="bar">
  <h1 id="pname">剪辑审阅</h1>
  <span id="total"></span>
  <span id="dirty">● 有未保存的修改</span>
  <span class="sp"></span>
  <span id="rs"><span id="rstext"></span><span class="pb"><i id="rsbar"></i></span></span>
  <button id="bSave">保存</button>
  <button id="bPrev" class="pri">保存并渲染预览</button>
  <button id="bFinal">渲染最终版</button>
</div>
<main>
  <div id="errbox"></div>
  <div id="pv"><div class="none">尚无预览，点击「保存并渲染预览」生成</div></div>
  <div id="list"></div>
</main>
<div id="modal"><div class="box">
  <video id="mv" controls playsinline></video>
  <div class="row">
    <span id="mlabel" style="font-weight:600"></span>
    <span id="mt"></span>
    <span class="sp"></span>
    <button id="mIn">设为入点</button>
    <button id="mOut">设为出点</button>
    <button id="mSplit">在此拆分</button>
    <button id="mClose">关闭 (Esc)</button>
  </div>
  <div class="hint" style="margin-top:6px">空格：播放/暂停 · 播放范围为该镜头的入点→出点</div>
</div></div>
<script>
let D=null, dirty=false, durs={}, modalShot=-1, polling=null;
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const r3=x=>Math.round(x*1000)/1000;
const r1=x=>Math.round(x*10)/10;
function fmt(t){t=Math.max(0,t);const m=Math.floor(t/60),s=Math.floor(t%60);return String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')}
function isOn(s){return s.enabled!==false && s.out>s.in}
function subLive(s,x){return Math.min(x.t1,s.out)-Math.max(x.t0,s.in)>=0.3 && (x.text||'').trim()}
function setDirty(v){dirty=v;$('#dirty').style.display=v?'inline':'none'}
function showErr(msg){const b=$('#errbox');b.textContent=msg||'';b.style.display=msg?'block':'none'}

async function load(){
  D=await (await fetch('/api/edl')).json();
  $('#pname').textContent='剪辑审阅 · '+(D.project||'').split('/').pop();
  document.title='剪辑审阅 · '+(D.project||'').split('/').pop();
  render(); loadPreview();
  fetch('/api/durations').then(r=>r.json()).then(d=>{durs=d;render()});
  const st=await (await fetch('/api/render_status')).json();
  if(st.active) startPoll();
}

function thumbs(s){
  const ts=[s.in,(s.in+s.out)/2,Math.max(s.in,s.out-0.1)];
  const lab=['入','中','出'];
  return ts.map((t,k)=>`<figure><img loading="lazy" src="/thumb?clip=${encodeURIComponent(s.clip)}&t=${r1(t).toFixed(1)}"><figcaption>${lab[k]} ${r1(t).toFixed(1)}</figcaption></figure>`).join('');
}

function subRow(s,i,x,j){
  return `<div class="sub ${subLive(s,x)?'':'out'}" id="sub-${i}-${j}">
    <input type="number" step="0.1" data-i="${i}" data-j="${j}" data-f="sub.t0" value="${x.t0}">
    <span class="hint">→</span>
    <input type="number" step="0.1" data-i="${i}" data-j="${j}" data-f="sub.t1" value="${x.t1}">
    <input class="tx" data-i="${i}" data-j="${j}" data-f="sub.text" value="${esc(x.text)}">
    <button class="sm" data-act="delsub" data-i="${i}" data-j="${j}" title="删除字幕">✕</button></div>`;
}

function row(s,i){
  const t=s.title||{}, dur=durs[s.clip];
  const grades=Object.keys(D.grades||{});
  const gsel=grades.length?`<label>调色 <select data-i="${i}" data-f="grade">${grades.map(g=>`<option ${g===(s.grade||'default')?'selected':''}>${esc(g)}</option>`).join('')}</select></label>`:'';
  (s.subs||[]).sort((a,b)=>a.t0-b.t0);
  return `<div class="shot ${s.enabled===false?'off':''}" id="row-${i}">
   <div class="idx"><div class="n">${i+1}</div><div class="st" id="st-${i}"></div><div class="du" id="du-${i}"></div>
     <button class="sm" data-act="up" data-i="${i}" title="上移" ${i===0?'disabled':''}>▲</button>
     <button class="sm" data-act="down" data-i="${i}" title="下移" ${i===D.shots.length-1?'disabled':''}>▼</button></div>
   <div><div class="thumbs" id="th-${i}">${thumbs(s)}</div></div>
   <div class="meta">
     <div><span class="clip">${esc(s.clip)}</span><span class="sid">${esc(s.id)}${dur?` · 源长 ${dur.toFixed(1)}s`:''}</span></div>
     <div class="note">${esc(s.note||'')}</div>
     <div class="ctl">
       <label><input type="checkbox" data-i="${i}" data-f="enabled" ${s.enabled!==false?'checked':''}> 启用</label>
       <label>入点 <span class="grp"><button data-act="nudge" data-i="${i}" data-f="in" data-d="-0.1">−</button><input type="number" step="0.1" min="0" data-i="${i}" data-f="in" value="${s.in}"><button data-act="nudge" data-i="${i}" data-f="in" data-d="0.1">+</button></span></label>
       <label>出点 <span class="grp"><button data-act="nudge" data-i="${i}" data-f="out" data-d="-0.1">−</button><input type="number" step="0.1" min="0" data-i="${i}" data-f="out" value="${s.out}"><button data-act="nudge" data-i="${i}" data-f="out" data-d="0.1">+</button></span></label>
       <label>音频 <select data-i="${i}" data-f="audio">${['voice','ambient','mute'].map(a=>`<option value="${a}" ${a===(s.audio||'voice')?'selected':''}>${{voice:'人声 voice',ambient:'环境 ambient',mute:'静音 mute'}[a]}</option>`).join('')}</select></label>
       ${gsel}
       <button data-act="play" data-i="${i}">▶ 播放</button>
       <button data-act="split" data-i="${i}">拆分</button>
     </div>
     <div class="ttl"><span>标题</span>
       <input placeholder="标题文字" data-i="${i}" data-f="title.text" value="${esc(t.text||'')}">
       <input placeholder="副标题" data-i="${i}" data-f="title.sub" value="${esc(t.sub||'')}">
       <input class="dur" type="number" step="0.5" min="0.5" title="标题时长 (秒)" data-i="${i}" data-f="title.dur" value="${t.dur??3}">
       <span>地点标签</span><input placeholder="tag" data-i="${i}" data-f="tag" value="${esc(s.tag||'')}">
     </div>
   </div>
   <div class="subs"><div class="hd">字幕（源素材秒数，入点~出点之外的不会渲染）<button class="sm" data-act="addsub" data-i="${i}">＋ 添加字幕</button></div>
     <div id="subs-${i}">${(s.subs||[]).map((x,j)=>subRow(s,i,x,j)).join('')}</div></div>
  </div>`;
}

function render(){
  const y=window.scrollY;
  $('#list').innerHTML=D.shots.map(row).join('');
  recompute(); window.scrollTo(0,y);
}

function recompute(){
  let t=0,n=0;
  D.shots.forEach((s,i)=>{
    const st=document.getElementById('st-'+i), du=document.getElementById('du-'+i);
    if(st) st.textContent=isOn(s)?fmt(t):'—';
    if(du) du.textContent=(s.out-s.in).toFixed(1)+'s';
    if(isOn(s)){t+=s.out-s.in;n++}
    const row=document.getElementById('row-'+i);
    if(row){
      const bad=!(s.in>=0&&s.in<s.out);
      row.querySelectorAll('input[data-f=in],input[data-f=out]').forEach(e=>e.classList.toggle('bad',bad));
      (s.subs||[]).forEach((x,j)=>{const e=document.getElementById(`sub-${i}-${j}`); if(e) e.classList.toggle('out',!subLive(s,x))});
    }
  });
  $('#total').innerHTML=`总时长 <b>${fmt(t)}</b> · ${n}/${D.shots.length} 个镜头`;
}

const thumbTimers={};
function refreshThumbs(i){
  clearTimeout(thumbTimers[i]);
  thumbTimers[i]=setTimeout(()=>{const e=document.getElementById('th-'+i); if(e) e.innerHTML=thumbs(D.shots[i])},400);
}

function setField(i,f,el){
  const s=D.shots[i];
  if(f==='enabled'){s.enabled=el.checked; document.getElementById('row-'+i).classList.toggle('off',!el.checked)}
  else if(f==='in'||f==='out'){const v=parseFloat(el.value); if(!isNaN(v)){s[f]=r3(v); refreshThumbs(i)}}
  else if(f==='audio'||f==='grade'){s[f]=el.value}
  else if(f==='tag'){if(el.value.trim()) s.tag=el.value; else delete s.tag}
  else if(f.startsWith('title.')){
    const k=f.slice(6); s.title=s.title||{text:'',sub:'',dur:3.0};
    s.title[k]=k==='dur'?(parseFloat(el.value)||3.0):el.value;
    if(!s.title.text.trim()&&!(s.title.sub||'').trim()) delete s.title;
  }
  else if(f.startsWith('sub.')){
    const x=s.subs[+el.dataset.j], k=f.slice(4);
    if(k==='text') x.text=el.value; else {const v=parseFloat(el.value); if(!isNaN(v)) x[k]=r3(v)}
  }
  setDirty(true); recompute();
}

$('#list').addEventListener('input',e=>{const el=e.target; if(el.dataset.f) setField(+el.dataset.i,el.dataset.f,el)});
$('#list').addEventListener('change',e=>{const el=e.target; if(el.dataset.f==='enabled'||el.tagName==='SELECT') setField(+el.dataset.i,el.dataset.f,el)});
$('#list').addEventListener('click',e=>{
  const b=e.target.closest('button[data-act]'); if(!b) return;
  const i=+b.dataset.i, s=D.shots[i], a=b.dataset.act;
  if(a==='nudge'){
    const f=b.dataset.f; let v=r3(s[f]+parseFloat(b.dataset.d));
    v=Math.max(0,v); if(durs[s.clip]) v=Math.min(v,r3(durs[s.clip]));
    s[f]=v; const inp=document.querySelector(`#row-${i} input[data-f=${f}]`); inp.value=v;
    setDirty(true); recompute(); refreshThumbs(i); return;
  }
  if(a==='up'&&i>0){[D.shots[i-1],D.shots[i]]=[D.shots[i],D.shots[i-1]]}
  else if(a==='down'&&i<D.shots.length-1){[D.shots[i+1],D.shots[i]]=[D.shots[i],D.shots[i+1]]}
  else if(a==='play'){openModal(i);return}
  else if(a==='split'){
    const def=r1((s.in+s.out)/2);
    const v=prompt(`在源素材的哪一秒拆分？（${s.in} ~ ${s.out} 之间）`,def);
    if(v===null) return; if(!splitAt(i,parseFloat(v))) return;
  }
  else if(a==='addsub'){
    s.subs=s.subs||[]; const last=s.subs.filter(x=>x.t1<=s.out).pop();
    const t0=r3(last&&last.t1<s.out?last.t1:s.in); s.subs.push({t0,t1:r3(Math.min(t0+2,s.out>t0?s.out:t0+2)),text:''});
    render(); setDirty(true);
    const inputs=document.querySelectorAll(`#subs-${i} input.tx`); const inp=[...inputs].find(e=>!e.value); if(inp) inp.focus();
    return;
  }
  else if(a==='delsub'){s.subs.splice(+b.dataset.j,1)}
  else return;
  setDirty(true); render();
});

function newId(){
  let mx=0; D.shots.forEach(s=>{const m=/^s(\d+)$/.exec(s.id); if(m) mx=Math.max(mx,+m[1])});
  let id; do{mx++; id='s'+String(mx).padStart(3,'0')}while(D.shots.some(s=>s.id===id));
  return id;
}
function splitAt(i,t){
  const s=D.shots[i];
  if(isNaN(t)||t<=s.in||t>=s.out){alert(`拆分点必须在入点 ${s.in} 和出点 ${s.out} 之间`);return false}
  t=r3(t);
  const b=JSON.parse(JSON.stringify(s));
  b.id=newId(); b.in=t; s.out=t;
  const subs=s.subs||[];
  s.subs=subs.filter(x=>x.t0<t); b.subs=subs.filter(x=>x.t0>=t);
  delete b.title; delete b.tag; b.fade_in=0; s.fade_out=0;
  b.note=(s.note?s.note+' ':'')+'（拆分后半）';
  D.shots.splice(i+1,0,b); setDirty(true); render(); return true;
}

// ---- modal player
const mv=$('#mv');
function openModal(i){
  modalShot=i; const s=D.shots[i];
  mv.src=`/clip/${encodeURIComponent(s.clip)}#t=${s.in},${s.out}`;
  $('#mlabel').textContent=`#${i+1} ${s.clip}  ${s.in}s → ${s.out}s`;
  $('#modal').style.display='flex'; mv.play().catch(()=>{});
}
function closeModal(){mv.pause(); mv.removeAttribute('src'); mv.load(); $('#modal').style.display='none'; modalShot=-1}
mv.addEventListener('timeupdate',()=>{
  $('#mt').textContent='当前 '+mv.currentTime.toFixed(2)+'s';
  const s=D.shots[modalShot]; if(s&&mv.currentTime>=s.out&&!mv.paused) mv.pause();
});
$('#mClose').onclick=closeModal;
$('#modal').addEventListener('click',e=>{if(e.target.id==='modal') closeModal()});
$('#mIn').onclick=()=>{const s=D.shots[modalShot]; s.in=r3(mv.currentTime); setDirty(true); render()};
$('#mOut').onclick=()=>{const s=D.shots[modalShot]; s.out=r3(mv.currentTime); setDirty(true); render()};
$('#mSplit').onclick=()=>{const i=modalShot,t=mv.currentTime; closeModal(); splitAt(i,t)};
document.addEventListener('keydown',e=>{
  if(modalShot<0) return;
  if(e.key==='Escape'){closeModal();return}
  if(e.code==='Space'&&!/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)){
    e.preventDefault(); const s=D.shots[modalShot];
    if(mv.paused){if(mv.currentTime>=s.out-0.05||mv.currentTime<s.in) mv.currentTime=s.in; mv.play()} else mv.pause();
  }
});

// ---- preview + save + render
async function loadPreview(){
  const r=await fetch('/preview.mp4',{method:'HEAD'});
  const pv=$('#pv');
  if(r.ok){pv.innerHTML=`<video controls preload="metadata" src="/preview.mp4?v=${Date.now()}"></video>`}
  else pv.innerHTML='<div class="none">尚无预览，点击「保存并渲染预览」生成</div>';
}
async function save(){
  for(const s of D.shots) if(!(s.in>=0&&s.in<s.out)){showErr(`镜头 ${s.id}: 入点必须小于出点`);return false}
  const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(D)});
  const j=await r.json();
  if(!j.ok){showErr('保存失败：\n'+(j.errors||[j.error]).join('\n'));return false}
  showErr(''); setDirty(false); flash(j.unchanged?'无改动':'已保存'+(j.backup?'（旧版本备份：'+j.backup+'）':''));
  return true;
}
function flash(msg){const rs=$('#rs'); rs.style.display='flex'; rs.className='done'; $('#rstext').textContent=msg; $('#rsbar').parentNode.style.display='none'; setTimeout(()=>{if(!polling) rs.style.display='none'},3000)}
async function startRender(mode){
  if(!await save()) return;
  const r=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
  const j=await r.json();
  if(!j.ok){showErr('无法渲染：'+j.error);return}
  startPoll();
}
function startPoll(){
  if(polling) return; setBusy(true); pollOnce(); polling=setInterval(pollOnce,2000);
}
async function pollOnce(){
  let st; try{st=await (await fetch('/api/render_status')).json()}catch(e){return}
  const rs=$('#rs'); rs.style.display='flex'; $('#rsbar').parentNode.style.display='';
  const lbl=st.mode==='final'?'最终版':'预览';
  $('#rsbar').style.width=Math.round((st.progress||0)*100)+'%';
  if(st.state==='error'){
    stopPoll(); rs.className='err'; $('#rstext').textContent=lbl+'渲染失败'; showErr('渲染失败：\n'+(st.error||'未知错误'));
  } else if(st.state==='done'&&!st.active){
    stopPoll(); rs.className='done'; $('#rstext').textContent=lbl+'渲染完成'+(st.mode==='final'&&st.output?'：'+st.output:'');
    $('#rsbar').style.width='100%'; if(st.mode!=='final') loadPreview();
  } else {
    rs.className=''; $('#rstext').textContent=`${lbl}渲染中 · ${st.step||''} ${Math.round((st.progress||0)*100)}%`;
  }
}
function stopPoll(){clearInterval(polling); polling=null; setBusy(false)}
function setBusy(b){$('#bPrev').disabled=b; $('#bFinal').disabled=b}
$('#bSave').onclick=save;
$('#bPrev').onclick=()=>startRender('preview');
$('#bFinal').onclick=()=>{if(confirm('保存并渲染最终版？（耗时较长）')) startRender('final')};
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='s'){e.preventDefault();save()}});
load();
</script></body></html>
"""


def main():
    global PROJECT
    ap = argparse.ArgumentParser(description="Review/edit page for an auto-assembled vlog EDL")
    ap.add_argument("project", help="project folder name under ~/Desktop, or a path")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    PROJECT = os.path.abspath(E.project_dir(a.project))
    if not os.path.isfile(E.edl_path(PROJECT)):
        sys.exit(f"No EDL at {E.edl_path(PROJECT)}")
    print(f"Review page: http://{a.host}:{a.port}/")
    app.run(host=a.host, port=a.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
