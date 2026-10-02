"""Local review/edit page for an auto-assembled vlog EDL.

    ./venv/bin/python -m src.editor.review_server "<project>" [--port 8766]

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
import re
import shutil
import subprocess
import sys
import threading
import time

from flask import Flask, Response, abort, jsonify, request, send_file

from . import edl as E
from . import questions as QS
from . import chat as CHAT
from . import theme as THEME

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_ROOT = "/tmp/yt-editor"

app = Flask(__name__)
PROJECT = None          # project dir (absolute)
RENDER = {"proc": None, "mode": None, "log": None}
_durations = {}
_thumb_sem = threading.Semaphore(4)


# ---------------------------------------------------------------- helpers

QS.register(app, lambda: PROJECT)
CHAT.register(app, lambda: PROJECT)


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
        if s.get("card"):
            pass  # generated title card: no source clip
        elif not isinstance(clip, str) or not clip or "/" in clip or ".." in clip:
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
        if not isinstance(s.get("skip_on", True), bool):
            errs.append(f"{p}: skip_on 必须是布尔值")
        sk = s.get("skip", [])
        if not (isinstance(sk, list) and all(
                isinstance(x, list) and len(x) == 2 and all(map(_num, x)) for x in sk)):
            errs.append(f"{p}: skip 格式错误")
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
    r = jsonify(E.load(PROJECT))
    r.headers["X-Mtime"] = edl_mtime()
    return r


def edl_mtime():
    try:
        return str(os.stat(E.edl_path(PROJECT)).st_mtime_ns)
    except OSError:
        return ""


@app.get("/api/mtime")
def api_mtime():
    return jsonify({"mtime": edl_mtime()})


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
        return jsonify({"ok": True, "unchanged": True, "mtime": edl_mtime()})
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
    return jsonify({"ok": True, "backup": os.path.basename(dst), "mtime": edl_mtime()})


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


@app.get("/api/preview_latest")
def api_preview_latest():
    vdir = os.path.join(edit_dir(), "previews")
    names = sorted(f for f in os.listdir(vdir) if f.startswith("preview-")) if os.path.isdir(vdir) else []
    return jsonify({"name": names[-1] if names else None})


@app.get("/previews/<name>")
def preview_version(name):
    if not re.fullmatch(r"preview-\d{8}-\d{6}\.mp4", name):
        abort(404)
    p = os.path.join(edit_dir(), "previews", name)
    if not os.path.isfile(p):
        abort(404)
    # versions never change once written, so the browser may cache them
    return send_file(p, mimetype="video/mp4", conditional=True, max_age=3600)


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
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%230ea5e9'/%3E%3Cstop offset='1' stop-color='%232563eb'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='64' height='64' rx='15' fill='url%28%23g%29'/%3E%3Cg fill='none' stroke='white' stroke-width='5' stroke-linecap='round'%3E%3Ccircle cx='20' cy='44' r='7'/%3E%3Ccircle cx='44' cy='44' r='7'/%3E%3Cpath d='M25 39 L46 14 M39 39 L18 14'/%3E%3C/g%3E%3C/svg%3E">
<style>
__THEME_CSS__
input.bad{border-color:var(--danger);background:var(--danger-soft)}
#bar{position:sticky;top:0;z-index:10;background:var(--surface)}
#bar .hdr{border-bottom:1px solid var(--line)}
#dirty{color:var(--danger);font-size:13px;display:none;white-space:nowrap}
#dirty::before{content:'';display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--danger);margin-right:6px;vertical-align:1px}
#bar .acts-top{display:flex;gap:8px;align-items:center}
#bar .acts-top button{height:32px;padding:0 14px}
#rs{display:none;padding:8px 16px 10px;font-size:13px;color:var(--text-2);border-bottom:1px solid var(--line)}
#rs .pb{height:6px;background:var(--surface-3);border-radius:3px;overflow:hidden;margin-top:6px}
#rs .pb i{display:block;height:100%;background:var(--accent);width:0;transition:width .4s}
#rs.err{color:var(--danger)} #rs.done{color:var(--ok)} #rs.done .pb i{background:var(--ok)}
#stale{display:none;padding:7px 16px;background:var(--q-soft);border-bottom:1px solid var(--q-line);color:var(--q-ink);font-size:13px;text-align:center}
#stale button{font-size:12px;padding:2px 10px;margin-left:6px}
/* ---- two columns: shot list | sticky rail (preview, questions, chat) */
.layout{display:grid;grid-template-columns:minmax(0,1fr) clamp(480px,44vw,640px);align-items:start}
main{padding:16px;min-width:0}
.rail{position:sticky;top:var(--barh,52px);height:calc(100vh - var(--barh,52px));display:flex;flex-direction:column;gap:12px;
  padding:16px 16px 16px 0;min-height:0}
#help{display:flex;gap:10px;align-items:center;background:var(--accent-soft);border:1px solid var(--accent-line);color:var(--text-2);
  border-radius:var(--r);padding:7px 8px 7px 14px;margin-bottom:12px;font-size:13px}
#help .tx{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#help b{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;background:var(--accent);color:#fff;font-size:11px;font-weight:600;margin:0 4px 0 8px;vertical-align:1px}
#help b:first-child{margin-left:0}
#help button{width:26px;height:26px;padding:0;flex:none;color:var(--text-3)}
body.nohelp #help{display:none}
#errbox{display:none;white-space:pre-wrap;background:var(--danger-soft);border:1px solid #fecdca;color:var(--danger);border-radius:var(--r);padding:10px 12px;margin-bottom:12px;font-size:13px}
#listEnd{margin:18px 0 0;padding:22px 0 40vh;text-align:center;color:var(--text-3);font-size:14px;border-top:1px dashed var(--line-2)}
#listEnd b{color:var(--text)}
#listEnd a{color:var(--accent);text-decoration:none}
/* ---- preview */
#pvwrap{flex:none}
#pv{background:var(--stage);border-radius:var(--r-lg);overflow:hidden;display:flex;justify-content:center;align-items:center;aspect-ratio:16/9;
  max-height:46vh;position:relative;box-shadow:var(--sh-1)}
#pv video{width:100%;height:100%;object-fit:contain;display:block}
#pvnew{display:none;position:absolute;left:50%;top:10px;transform:translateX(-50%);z-index:4;border:0;border-radius:999px;padding:6px 14px;font-size:13px;
  background:var(--accent);color:#fff;box-shadow:var(--sh-2);cursor:pointer;white-space:nowrap}
.bigplay{position:absolute;left:50%;top:50%;width:68px;height:68px;margin:-34px 0 0 -34px;border-radius:50%;background:rgba(0,0,0,.5);backdrop-filter:blur(4px);
  pointer-events:none;z-index:3;transition:opacity .2s ease,transform .2s ease}
.bigplay::after{content:'';position:absolute;left:27px;top:20px;border-style:solid;border-width:14px 0 14px 23px;border-color:transparent transparent transparent #fff}
.bigplay.hide{opacity:0;transform:scale(1.25)}#pvv{cursor:pointer}
#pv:fullscreen{border-radius:0}#pv:fullscreen video{max-height:100vh;width:100%;height:100%}
#follow{display:none;position:absolute;right:10px;top:10px;z-index:2;border:0;border-radius:999px;padding:4px 12px;font-size:12px;background:rgba(255,255,255,.94);
  color:var(--accent);box-shadow:var(--sh-2)}
#pv .none{color:var(--stage-mute);padding:30px;font-size:13px;text-align:center}
#qstrip{display:none;position:relative;height:14px;margin:6px auto 0;cursor:default}
body.hasq #qstrip.on{display:block}
#qstrip .tr{position:absolute;left:0;right:0;top:9px;height:3px;border-radius:2px;background:var(--line-2)}
#qstrip .ph{position:absolute;top:6px;width:2px;height:9px;margin-left:-1px;background:var(--text-3);border-radius:1px}
#qstrip .qm{position:absolute;top:0;width:0;height:0;margin-left:-6px;border-left:6px solid transparent;border-right:6px solid transparent;
  border-top:9px solid var(--q);cursor:pointer}
#qstrip .qm.done{border-top-color:var(--used)}
#qcard .qa-card{margin:0;box-shadow:var(--sh-1)}
#qside{display:none;flex:0 1 auto;min-height:0;max-height:min(24%,180px);overflow:hidden;flex-direction:column}
body.hasq #qside{display:flex}
body.qactive #qside{display:none}   /* the pop-up card already shows that question: give the room to the chat */
#qpanel{overflow-y:auto;padding:8px 8px 16px;min-height:0;-webkit-mask-image:linear-gradient(to bottom,#000 calc(100% - 22px),transparent)}
#chatDock{flex:1 1 240px;min-height:200px;overflow:hidden}
#chatDock.min{flex:none;min-height:0}
#chatDock #cb{border:0;border-radius:0}
/* ---- shot cards */
.shot{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);margin-bottom:12px;padding:14px;
  display:grid;grid-template-columns:minmax(170px,32%) minmax(0,1fr);gap:16px;box-shadow:var(--sh-1);transition:border-color .15s,box-shadow .15s}
.shot.cur{border-color:var(--accent-line);box-shadow:inset 3px 0 0 var(--accent),0 0 0 3px var(--accent-soft)}
.thumbs{display:flex;gap:3px;align-self:start;align-items:flex-start}
.thumbs img{flex:1;min-width:0;width:33%;aspect-ratio:16/9;object-fit:cover;background:var(--surface-3);border-radius:6px;display:block}
.thumbs .card{width:100%;aspect-ratio:48/9;display:flex;align-items:center;justify-content:center;border-radius:6px;font-weight:600;font-size:15px;color:#1f2937;
  box-shadow:inset 0 0 0 1px rgba(0,0,0,.06)}
.hd{display:flex;align-items:baseline;gap:10px;margin-bottom:8px}
.hd .n{font-weight:600;font-size:14px;color:var(--text-3);font-variant-numeric:tabular-nums}
.hd .ti{font-weight:600;font-size:15px;flex:1;min-width:0}
.at{color:var(--accent);font-variant-numeric:tabular-nums;font-size:13px;cursor:pointer;white-space:nowrap;padding:1px 6px;border-radius:6px}
.at:hover{background:var(--accent-soft)}
.acts{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 10px}
button.soft{background:var(--accent-soft);border-color:transparent;color:var(--accent);font-weight:500}
button.soft:hover{background:#e0eaff;border-color:transparent}
.seg2{display:inline-flex;border:1px solid var(--line-2);border-radius:var(--r-sm);overflow:hidden;background:var(--surface)}
.seg2 button{border:0;border-radius:0;padding:5px 12px;color:var(--text-2)}
.seg2 button+button{border-left:1px solid var(--line-2)}
.seg2 button.on{background:var(--ok-soft);color:var(--ok);font-weight:500;cursor:default}
.seg2 button:not(.on):hover{background:var(--danger-soft);color:var(--danger)}
.zm{color:var(--text-3);font-size:13px}
.trim{display:flex;gap:10px 14px;flex-wrap:wrap;align-items:center;font-size:13px;margin:0 0 6px}
.stp{display:inline-flex;align-items:center;gap:8px}
.stp .lb{color:var(--text-2)}
.stp .box{display:inline-flex;align-items:center;border:1px solid var(--line-2);border-radius:var(--r-sm);overflow:hidden;background:var(--surface);height:30px}
.stp .box:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-ring)}
.stp button{border:0;border-radius:0;height:100%;padding:0 7px;font-size:12px;color:var(--text-2);background:var(--surface-2);font-variant-numeric:tabular-nums}
.stp button:hover{background:var(--surface-3);color:var(--text)}
.stp .u{font-size:12px;color:var(--text-3);padding:0 7px 0 1px;align-self:center}
.stp input{width:46px;border:0;border-left:1px solid var(--line);border-right:1px solid var(--line);border-radius:0;text-align:right;height:100%;
  padding:0 4px;font-variant-numeric:tabular-nums;font-size:13px;box-shadow:none !important}
.stp input::-webkit-inner-spin-button{display:none}
.stp .num{display:inline-flex;align-items:center;height:100%;border-left:1px solid var(--line);border-right:1px solid var(--line)}
.stp .num input{border:0}
.trim .du{color:var(--text-3);font-size:13px;font-variant-numeric:tabular-nums;white-space:nowrap}
.skip{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--q-ink);background:var(--q-soft);border:1px solid var(--q-line);border-radius:var(--r-sm);padding:3px 4px 3px 10px;margin:8px 0;width:fit-content;max-width:100%}
.skip button{font-size:12px;padding:1px 9px;background:transparent;border-color:transparent;color:var(--q-ink);text-decoration:underline;text-underline-offset:2px}
.skip button:hover{background:rgba(245,158,11,.12);border-color:transparent}
.skip.off{color:var(--text-3);background:var(--surface-2);border-color:var(--line)}
.skip.off button{color:var(--text-2)}
.lines{margin-top:10px}
.lines .line{display:flex;margin-bottom:4px}
.lines input{flex:1;border-color:transparent;background:var(--surface-2);padding:5px 9px;font-size:14px}
.lines input:hover{border-color:var(--line-2)}
.lines .line.out input{opacity:.45;text-decoration:line-through}
.lines .cap{color:var(--text-3);font-size:12px;margin-bottom:4px}
details{margin-top:10px;border-top:1px solid var(--surface-3);padding-top:8px}
summary{cursor:pointer;color:var(--text-3);font-size:13px;user-select:none;width:fit-content}
summary:hover{color:var(--text)}
.more{display:grid;grid-template-columns:96px 1fr;gap:10px 12px;align-items:center;margin-top:10px;font-size:13px}
.more .k{color:var(--text-3);font-size:13px}
.more .v{display:flex;gap:6px;align-items:center;flex-wrap:wrap;color:var(--text-2)}
.more input.w,.more select{width:170px}
.more input.n{width:64px}
.more button.sm,.subrow button.sm{font-size:12px;padding:2px 9px}
.subrow{display:flex;gap:5px;align-items:center;margin-bottom:4px;width:100%}
.subrow input.n{width:62px}
.subrow input.tx{flex:1}
.mono{font-family:var(--mono);font-size:12px;color:var(--text-3)}
.hint{color:var(--text-3);font-size:12px}
.shot.off{display:flex;align-items:center;gap:12px;padding:7px 8px 7px 14px;background:var(--surface-2);color:var(--text-3);border-style:dashed;box-shadow:none;font-size:13px}
.shot.off .n{text-decoration:line-through;font-variant-numeric:tabular-nums}
.shot.off .ti{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.shot.off button{font-size:12px;padding:2px 10px}
/* ---- per-shot player */
#modal{position:fixed;inset:0;background:rgba(10,14,20,.6);backdrop-filter:blur(2px);display:none;align-items:center;justify-content:center;z-index:50}
#modal .box{background:var(--surface);border-radius:var(--r-lg);padding:14px;width:min(1000px,92vw);box-shadow:var(--sh-2)}
#modal video{width:100%;max-height:70vh;background:var(--stage);border-radius:var(--r);display:block}
#modal .row{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
#modal .sp{flex:1}
#mt{font-variant-numeric:tabular-nums;color:var(--text-3)}
@media (max-width:1360px){.shot{grid-template-columns:200px minmax(0,1fr)}}
@media (max-width:900px){.layout{grid-template-columns:1fr}.rail{position:static;height:auto;padding:16px 16px 0}#chatDock{height:320px;flex:none}}
__QA_CSS__
</style></head><body>
<div id="bar">
 <div class="hdr">
  <span class="kind">剪辑审阅</span><span class="sep"></span><span class="pname" id="pname"></span>
  <span class="meta" id="total"></span>
  <span id="dirty">有修改还没保存</span>
  <span class="sp"></span>
  <div class="acts-top">
   <button id="bSave" title="保存（⌘S）">保存</button>
   <button id="bFinal" class="outline">导出成片</button>
   <button id="bPrev" class="pri">更新预览</button>
  </div>
 </div>
 <div id="stale">文件已被更新，保存会覆盖对方的修改<button id="bReload">重新载入</button></div>
 <div id="rs"><span id="rstext"></span><div class="pb"><i id="rsbar"></i></div></div>
</div>
<div class="layout">
<main>
  <div id="help"><span class="tx"><b>1</b>看预览 <b>2</b>不要的点「删掉」，太长改开始/结束 <b>3</b>「更新预览」看效果 <b>4</b>满意了「导出成片」</span><button class="ghost" id="helpX" title="不再显示">✕</button></div>
  <div id="errbox"></div>
  <div id="list"></div>
  <div id="listEnd">— 已经到最后一段了 —<br><span id="listEndInfo"></span><br><a href="#" onclick="window.scrollTo({top:0,behavior:'smooth'});return false">↑ 回到顶部</a></div>
</main>
<aside class="rail">
  <div id="pvwrap"><div id="pv"><div class="none">还没有预览，点右上角「更新预览」生成</div></div>
    <div id="qstrip" title="黄色 = 有问题想问你（点一下跳过去），绿色 = 已回答"><div class="tr"></div><div class="ph"></div><div id="qmarks"></div></div></div>
  <div id="qcard"></div>
  <div id="qside" class="panel"><div id="qpanel" class="scroll"></div></div>
  <div id="chatDock" class="panel"></div>
</aside>
</div>
<div id="modal"><div class="box">
  <video id="mv" controls playsinline></video>
  <div class="row">
    <span id="mlabel" style="font-weight:600"></span>
    <span id="mt"></span>
    <span class="sp"></span>
    <button id="mIn">从这里开始</button>
    <button id="mOut">到这里结束</button>
    <button id="mSplit">从当前播放位置切成两段</button>
    <button id="mClose">关闭</button>
  </div>
  <div class="hint" style="margin-top:6px">空格：播放 / 暂停 · Esc：关闭</div>
</div></div>
<script>
let D=null, base='', mtime='', dirty=false, durs={}, modalShot=-1, polling=null, finalArmed=null, openMore=new Set();
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const r3=x=>Math.round(x*1000)/1000;
const r1=x=>Math.round(x*10)/10;
const AUDIO={voice:'保留原声(说话)',ambient:'原声调小(环境)',mute:'静音'};
const GRADE={default:'默认',underwater:'水下',underwater_haze:'水下(浑浊)'};
function fmt(t){t=Math.max(0,t);const m=Math.floor(t/60),s=Math.floor(t%60);return m+':'+String(s).padStart(2,'0')}
function isOn(s){return s.enabled!==false && s.out>s.in}
// mirrors edl.kept_ranges / shot_dur / src_to_local
function skipScan(s,force){
  const on=force||s.skip_on!==false, sk=on?(s.skip||[]).map(x=>[+x[0],+x[1]]).sort((a,b)=>a[0]-b[0]||a[1]-b[1]):[];
  const rs=[]; let cur=s.in, n=0;
  for(let [a,b] of sk){a=Math.max(a,s.in); b=Math.min(b,s.out); if(b-a<=0.02||a<cur) continue; rs.push([cur,a]); cur=b; n++}
  rs.push([cur,s.out]);
  return {ranges:rs.filter(([a,b])=>b-a>0.02), n};
}
function kept(s){return skipScan(s).ranges}
function sdur(s){return '_qdur' in s?s._qdur:kept(s).reduce((t,[a,b])=>t+b-a,0)/Math.max(0.25,+(s.speed||1))}  // timelapse shots play faster
function local(s,t){let acc=0; for(const [a,b] of kept(s)){if(t<=b) return acc+Math.max(0,t-a); acc+=b-a} return acc}
function subLive(s,x){const t0=Math.max(x.t0,s.in),t1=Math.min(x.t1,s.out); return t1>t0&&local(s,t1)-local(s,t0)>=0.3}
function skipHtml(s,i){
  if(!(s.skip||[]).length) return '';
  const k=skipScan(s,true), sec=(s.out-s.in)-k.ranges.reduce((t,[a,b])=>t+b-a,0);
  if(!k.n) return '';
  return s.skip_on===false
    ?`<div class="skip off">✂ 已恢复原样（有 ${k.n} 处停顿/嗯啊可去掉，共 ${sec.toFixed(1)} 秒）<button class="sm" data-act="skipon" data-i="${i}">重新去掉</button></div>`
    :`<div class="skip">✂ 已自动去掉 ${k.n} 处停顿/嗯啊（共 ${sec.toFixed(1)} 秒）<button class="sm" data-act="skipon" data-i="${i}">恢复原样</button></div>`;
}
function zoomHtml(s){const z=s.zoom; if(!z||typeof z!=='object') return ''; return `<span class="zm">🔍 镜头慢慢${(+z.to)<(+z.from)?'拉远':'推近'}</span>`}
function setDirty(v){dirty=v;$('#dirty').style.display=v?'inline':'none'}
// dirty only when the EDL really differs from the last loaded/saved version (spurious
// input events from autofill/form-restore, or no-op edits, must not flag it)
function markBase(){base=JSON.stringify(D); setDirty(false)}
function changed(){setDirty(JSON.stringify(D)!==base)}
function showErr(msg){const b=$('#errbox');b.textContent=msg||'';b.style.display=msg?'block':'none'}
function starts(){let t=0;return D.shots.map(s=>{const a=t;if(isOn(s))t+=sdur(s);return a})}

async function fetchEdl(){
  const r=await fetch('/api/edl'); D=await r.json(); mtime=r.headers.get('X-Mtime')||'';
  $('#stale').style.display='none'; markBase();
}
async function checkRemote(){
  if(!D) return;
  let m; try{m=(await (await fetch('/api/mtime')).json()).mtime}catch(e){return}
  if(!m||m===mtime) return;
  if(dirty){$('#stale').style.display='block'; return}
  if(modalShot>=0) return;             // don't yank the list while a clip is playing
  await fetchEdl(); render();
}
async function load(){
  await fetchEdl();
  const name=(D.project||'').split('/').pop();
  $('#pname').textContent=name; PNAME=name; document.title=name+' · 剪辑审阅';
  render(); loadPreview();
  fetch('/api/durations').then(r=>r.json()).then(d=>{durs=d;render()});
  const st=await (await fetch('/api/render_status')).json();
  if(st.active) startPoll();
}

function thumbs(s){
  if(s.card)  // generated time card: no source clip, show a mini card instead
    return `<div class="card" style="background:${esc(s.card.bg||'#ffd84d')}">${esc(s.card.text)}</div>`;
  return [s.in,(s.in+s.out)/2,Math.max(s.in,s.out-0.1)].map(t=>
    `<img loading="lazy" src="/thumb?clip=${encodeURIComponent(s.clip)}&t=${r1(t).toFixed(1)}">`).join('');
}
function trimLabel(f){return f==='in'?'开始':'结束'}
function tfmt(v){v=+v||0; return v.toFixed(Math.round(v*100)%10?2:1)}   // 9 -> 9.0, 0.12 -> 0.12

function moreHtml(s,i){
  const t=s.title||{}, dur=durs[s.clip];
  const grades=Object.keys(D.grades||{});
  const subs=(s.subs||[]).map((x,j)=>`<div class="subrow">
      <input class="n" type="number" step="0.1" data-i="${i}" data-j="${j}" data-f="sub.t0" value="${x.t0}" title="开始（秒）">–
      <input class="n" type="number" step="0.1" data-i="${i}" data-j="${j}" data-f="sub.t1" value="${x.t1}" title="结束（秒）">
      <input class="tx" data-i="${i}" data-j="${j}" data-f="sub.text" value="${esc(x.text)}">
      <button class="sm" data-act="delsub" data-i="${i}" data-j="${j}">删除</button></div>`).join('');
  return `<div class="more">
    <span class="k">声音</span><span class="v"><select data-i="${i}" data-f="audio">${Object.keys(AUDIO).map(a=>`<option value="${a}" ${a===(s.audio||'voice')?'selected':''}>${AUDIO[a]}</option>`).join('')}</select></span>
    ${grades.length?`<span class="k">画面调色</span><span class="v"><select data-i="${i}" data-f="grade">${grades.map(g=>`<option value="${esc(g)}" ${g===(s.grade||'default')?'selected':''}>${esc(GRADE[g]||g)}</option>`).join('')}</select></span>`:''}
    <span class="k">大标题</span><span class="v"><input class="w" data-i="${i}" data-f="title.text" value="${esc(t.text||'')}" placeholder="不填就没有"></span>
    <span class="k">小标题</span><span class="v"><input class="w" data-i="${i}" data-f="title.sub" value="${esc(t.sub||'')}"></span>
    <span class="k">标题显示秒数</span><span class="v"><input class="n" type="number" step="0.5" min="0.5" data-i="${i}" data-f="title.dur" value="${t.dur??3}"></span>
    <span class="k">左上角地名</span><span class="v"><input class="w" data-i="${i}" data-f="tag" value="${esc(s.tag||'')}" placeholder="不填就没有"></span>
    <span class="k">字幕（带时间）</span><span class="v" style="display:block">${subs||'<span class="hint">没有字幕</span>'}
       <button class="sm" data-act="addsub" data-i="${i}">＋ 加一句字幕</button></span>
    <span class="k">顺序</span><span class="v"><button class="sm" data-act="up" data-i="${i}" ${i===0?'disabled':''}>往前移</button>
       <button class="sm" data-act="down" data-i="${i}" ${i===D.shots.length-1?'disabled':''}>往后移</button></span>
    <span class="k">切开</span><span class="v"><button class="sm" data-act="split" data-i="${i}">从当前播放位置切成两段</button>
       <span class="hint">（先播放，停在想切的地方再点）</span></span>
    <span class="k">素材文件</span><span class="v mono">${esc(s.clip)}.MP4${dur?` · 全长 ${dur.toFixed(1)}s`:''} · ${esc(s.id)}</span>
  </div>`;
}

function row(s,i,st){
  const title=esc(s.note||s.clip);
  if(s.enabled===false) return `<div class="shot off" id="row-${i}"><span class="n">#${i+1}</span><span class="ti">已删掉 · ${title}</span>
     <button data-act="toggle" data-i="${i}">恢复</button></div>`;
  const lines=(s.subs||[]).map((x,j)=>`<div class="line ${subLive(s,x)?'':'out'}" id="sub-${i}-${j}" title="${subLive(s,x)?'':'不在这段的开始~结束之间，不会显示'}">
      <input data-i="${i}" data-j="${j}" data-f="sub.text" value="${esc(x.text)}"></div>`).join('');
  return `<div class="shot" id="row-${i}">
   <div class="thumbs" id="th-${i}">${thumbs(s)}</div>
   <div>
     <div class="hd"><span class="n">#${i+1}</span><span class="ti">${title}</span>
       <span class="at" data-act="seek" data-i="${i}" id="st-${i}" title="在上方预览里跳到这里">⏱ ${fmt(st)}</span></div>
     <div class="acts">
       <button class="soft" data-act="play" data-i="${i}">▶ 播放这段</button>
       <span class="seg2" title="删掉的镜头不会出现在成片里，随时可以恢复"><button class="on" tabindex="-1">✓ 保留</button><button data-act="toggle" data-i="${i}">删掉</button></span>
       ${zoomHtml(s)}
     </div>
     <div class="trim">
       ${['in','out'].map(f=>`<span class="stp"><span class="lb" id="lb-${f}-${i}">${trimLabel(f)}</span><span class="box">
         <button data-act="nudge" data-i="${i}" data-f="${f}" data-d="-0.5" title="${f==='in'?'提前':'往前'} 0.5 秒">−0.5</button>
         <span class="num"><input type="number" step="0.1" min="0" data-i="${i}" data-f="${f}" value="${tfmt(s[f])}" title="秒（素材里的位置）"><span class="u">s</span></span>
         <button data-act="nudge" data-i="${i}" data-f="${f}" data-d="0.5" title="往后 0.5 秒">+0.5</button></span></span>`).join('')}
       <span class="du" id="du-${i}">共 ${sdur(s).toFixed(1)} 秒</span>
     </div>
     <div id="sk-${i}">${skipHtml(s,i)}</div>
     ${lines?`<div class="lines"><div class="cap">字幕</div>${lines}</div>`:''}
     <details data-i="${i}" ${openMore.has(s.id)?'open':''}><summary>更多设置</summary>${moreHtml(s,i)}</details>
   </div></div>`;
}

function render(){
  const y=window.scrollY, st=starts();
  $('#list').innerHTML=D.shots.map((s,i)=>row(s,i,st[i])).join('');
  recompute(); progScroll(); window.scrollTo(0,y);
  if(curIdx>=0){const r=document.getElementById('row-'+curIdx); if(r) r.classList.add('cur')}
}

function recompute(){
  const st=starts(); let n=0,t=0;
  D.shots.forEach((s,i)=>{
    if(isOn(s)){n++;t+=sdur(s)}
    const a=document.getElementById('st-'+i); if(a) a.textContent='⏱ '+fmt(st[i]);
    const du=document.getElementById('du-'+i); if(du) du.textContent=`共 ${sdur(s).toFixed(1)} 秒`;
    const sk=document.getElementById('sk-'+i); if(sk&&s.enabled!==false) sk.innerHTML=skipHtml(s,i);
    ['in','out'].forEach(f=>{const l=document.getElementById(`lb-${f}-${i}`); if(l) l.textContent=trimLabel(f)});
    const row=document.getElementById('row-'+i);
    if(row&&s.enabled!==false){
      const bad=!(s.in>=0&&s.in<s.out);
      row.querySelectorAll('input[data-f=in],input[data-f=out]').forEach(e=>e.classList.toggle('bad',bad));
      (s.subs||[]).forEach((x,j)=>{const e=document.getElementById(`sub-${i}-${j}`); if(e) e.classList.toggle('out',!subLive(s,x))});
    }
  });
  $('#total').innerHTML=`成片 <b>${fmt(t)}</b> · ${n} 段`;
  const le=document.getElementById('listEndInfo'); if(le) le.innerHTML=`共 <b>${n}</b> 段 · 成片 <b>${fmt(t)}</b>`;
}

const thumbTimers={};
function refreshThumbs(i){
  clearTimeout(thumbTimers[i]);
  thumbTimers[i]=setTimeout(()=>{const e=document.getElementById('th-'+i); if(e) e.innerHTML=thumbs(D.shots[i])},400);
}
function clampT(s,v){v=Math.max(0,v); if(durs[s.clip]) v=Math.min(v,r3(durs[s.clip])); return r3(v)}

function setField(i,f,el){
  const s=D.shots[i];
  if(f==='in'||f==='out'){const v=parseFloat(el.value); if(!isNaN(v)&&r3(v)!==s[f]){s[f]=r3(v); delete s._qdur; refreshThumbs(i)}}
  else if(f==='audio'||f==='grade'){s[f]=el.value}
  else if(f==='tag'){if(el.value.trim()) s.tag=el.value; else delete s.tag}
  else if(f.startsWith('title.')){
    const k=f.slice(6); s.title=s.title||{text:'',sub:'',dur:3.0};
    s.title[k]=k==='dur'?(parseFloat(el.value)||3.0):el.value;
    if(!(s.title.text||'').trim()&&!(s.title.sub||'').trim()) delete s.title;
  }
  else if(f.startsWith('sub.')){
    const j=+el.dataset.j, x=s.subs[j], k=f.slice(4);
    if(k==='text'){x.text=el.value; document.querySelectorAll(`#row-${i} input[data-f="sub.text"][data-j="${j}"]`).forEach(e=>{if(e!==el) e.value=el.value})}
    else {const v=parseFloat(el.value); if(!isNaN(v)) x[k]=r3(v)}
  }
  changed(); recompute();
}

const L=$('#list');
L.addEventListener('input',e=>{const el=e.target; if(el.dataset.f) setField(+el.dataset.i,el.dataset.f,el)});
L.addEventListener('toggle',e=>{const d=e.target; if(d.tagName!=='DETAILS') return; const id=D.shots[+d.dataset.i].id; d.open?openMore.add(id):openMore.delete(id)},true);
L.addEventListener('click',e=>{
  const b=e.target.closest('[data-act]'); if(!b) return;
  const i=+b.dataset.i, s=D.shots[i], a=b.dataset.act;
  if(a==='nudge'){
    const f=b.dataset.f, v=clampT(s,s[f]+parseFloat(b.dataset.d)); if(v!==s[f]){s[f]=v; delete s._qdur}
    document.querySelector(`#row-${i} input[data-f=${f}]`).value=tfmt(s[f]);
    changed(); recompute(); refreshThumbs(i); return;
  }
  if(a==='seek'){seekPreview(starts()[i]);return}
  if(a==='play'){openModal(i);return}
  if(a==='toggle'){s.enabled=s.enabled===false}
  else if(a==='skipon'){s.skip_on=s.skip_on===false; delete s._qdur}
  else if(a==='up'&&i>0){[D.shots[i-1],D.shots[i]]=[D.shots[i],D.shots[i-1]]}
  else if(a==='down'&&i<D.shots.length-1){[D.shots[i+1],D.shots[i]]=[D.shots[i],D.shots[i+1]]}
  else if(a==='split'){
    if(modalShot===i){splitAt(i,mv.currentTime);closeModal();return}
    openModal(i,true); return;
  }
  else if(a==='addsub'){
    s.subs=s.subs||[]; const last=s.subs.filter(x=>x.t1<s.out).pop();
    const t0=r3(last?Math.max(last.t1,s.in):s.in); s.subs.push({t0,t1:r3(Math.max(t0+0.5,Math.min(t0+2,s.out))),text:''});
  }
  else if(a==='delsub'){s.subs.splice(+b.dataset.j,1)}
  else return;
  changed(); render();
});

function newId(){
  let mx=0; D.shots.forEach(s=>{const m=/^s(\d+)$/.exec(s.id); if(m) mx=Math.max(mx,+m[1])});
  let id; do{mx++; id='s'+String(mx).padStart(3,'0')}while(D.shots.some(s=>s.id===id));
  return id;
}
function splitAt(i,t){
  const s=D.shots[i];
  if(isNaN(t)||t<=s.in+0.2||t>=s.out-0.2){showErr(`切开的位置要在这段的开始 ${s.in}s 和结束 ${s.out}s 之间`);return false}
  showErr(''); t=r3(t);
  const b=JSON.parse(JSON.stringify(s));
  b.id=newId(); b.in=t; s.out=t; delete s._qdur; delete b._qdur;
  const subs=s.subs||[];
  s.subs=subs.filter(x=>x.t0<t); b.subs=subs.filter(x=>x.t0>=t);
  delete b.title; delete b.tag; b.fade_in=0; s.fade_out=0;
  b.note=(s.note||'')+'（后半段）';
  D.shots.splice(i+1,0,b); changed(); render(); return true;
}

// ---- per-shot player
const mv=$('#mv');
function openModal(i,forSplit){
  modalShot=i; const s=D.shots[i];
  mv.src=`/clip/${encodeURIComponent(s.clip)}#t=${s.in},${s.out}`;
  $('#mlabel').textContent=forSplit?`#${i+1} 停在想切开的位置，再点「从当前播放位置切成两段」`:`#${i+1} ${s.note||''}`;
  $('#modal').style.display='flex'; mv.play().catch(()=>{});
}
function closeModal(){mv.pause(); mv.removeAttribute('src'); mv.load(); $('#modal').style.display='none'; modalShot=-1}
mv.addEventListener('timeupdate',()=>{
  const s=D.shots[modalShot]; if(!s) return;
  $('#mt').textContent=`${Math.max(0,mv.currentTime-s.in).toFixed(1)}s / ${(s.out-s.in).toFixed(1)}s`;
  if(mv.currentTime>=s.out&&!mv.paused) mv.pause();
});
$('#mClose').onclick=closeModal;
$('#modal').addEventListener('click',e=>{if(e.target.id==='modal') closeModal()});
$('#mIn').onclick=()=>{const s=D.shots[modalShot]; if(mv.currentTime<s.out){s.in=r3(mv.currentTime); delete s._qdur; changed(); render()}};
$('#mOut').onclick=()=>{const s=D.shots[modalShot]; if(mv.currentTime>s.in){s.out=r3(mv.currentTime); delete s._qdur; changed(); render()}};
$('#mSplit').onclick=()=>{const i=modalShot,t=mv.currentTime; closeModal(); splitAt(i,t)};
// Buttons never keep keyboard focus from a mouse click, and Space is swallowed on keyup too —
// browsers "click" a focused button on Space *keyup*, so blocking keydown alone isn't enough
// (Space after clicking fullscreen used to exit fullscreen instead of pausing).
document.addEventListener('mousedown',e=>{if(e.target.closest&&e.target.closest('button'))e.preventDefault()},true);
document.addEventListener('keyup',e=>{if(e.code==='Space'&&!/INPUT|SELECT|TEXTAREA/.test(e.target.tagName))e.preventDefault()},true);
function pvToggleFs(){const v=document.getElementById('pvv');
  if(document.fullscreenElement) document.exitFullscreen().catch(()=>{}); else if(v) v.requestFullscreen().catch(()=>{})}
document.addEventListener('fullscreenchange',()=>setTimeout(()=>{
  // native fullscreen leaves focus on the controls' fullscreen button (shadow DOM): Space would
  // re-trigger it. Blur it so Space reaches our handler and just plays/pauses.
  const a=document.activeElement; if(a&&a.blur) a.blur(); document.body.focus&&document.body.focus()},0));
// Click anywhere on the picture (not the control bar at the bottom) to play/pause, like YouTube.
document.addEventListener('click',e=>{const v=e.target; if(!v||v.id!=='pvv') return;
  const r=v.getBoundingClientRect(); if(e.clientY>r.bottom-Math.min(44,r.height*0.2)) return;  // native control bar
  e.preventDefault(); v.paused?v.play().catch(()=>{}):v.pause()},true);
setInterval(()=>{const v=document.getElementById('pvv'),g=document.getElementById('pvbig'); if(v&&g) g.classList.toggle('hide',!v.paused)},150);
// Preview player keys (also in fullscreen). Capture phase + preventDefault so the browser's own
// media controls or a focused button don't handle the same key a second time.
document.addEventListener('keydown',e=>{
  if(modalShot>=0||e.metaKey||e.ctrlKey||e.altKey) return;
  if(/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)||e.target.isContentEditable) return;
  const v=document.getElementById('pvv'); if(!v) return;
  // Handle keys even when the <video> itself has focus (after a click or in native fullscreen):
  // Chrome's media element does not toggle on Space by itself, so leaving it to the browser did nothing.
  if(e.code==='Space'||e.key==='k'){e.preventDefault();e.stopPropagation(); v.paused?v.play():v.pause()}
  else if(e.key==='ArrowRight'){e.preventDefault();e.stopPropagation(); v.currentTime=Math.min(v.duration||1e9,v.currentTime+5)}
  else if(e.key==='ArrowLeft'){e.preventDefault();e.stopPropagation(); v.currentTime=Math.max(0,v.currentTime-5)}
  else if(e.key==='f'||e.key==='F'){e.preventDefault();e.stopPropagation();
    pvToggleFs()}
},true);
document.addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&e.key==='s'){e.preventDefault();save();return}
  if(modalShot<0) return;
  if(e.key==='Escape'){closeModal();return}
  if(e.code==='Space'&&!/INPUT|SELECT/.test(e.target.tagName)){
    e.preventDefault(); const s=D.shots[modalShot];
    if(mv.paused){if(mv.currentTime>=s.out-0.05||mv.currentTime<s.in) mv.currentTime=s.in; mv.play()} else mv.pause();
  }
});

// ---- preview, save, render
// Each render is a new versioned file; we never pull the file out from under a playing video.
let PVNAME=null;
async function latestPreview(){try{return (await (await fetch('/api/preview_latest')).json()).name}catch(e){return null}}
async function loadPreview(keep){
  const n=await latestPreview();
  let src=null;
  if(n){src='/previews/'+n; PVNAME=n}
  else{const r=await fetch('/preview.mp4',{method:'HEAD'}); if(r.ok) src='/preview.mp4?v='+Date.now()}
  const old=$('#pvv'); const wasMuted=old?old.muted:false;
  if(old){old.pause(); old.removeAttribute('src'); old.load()}  // free its connections, or the new one stalls
  $('#pv').innerHTML=(src?`<video id="pvv" controls preload="auto" src="${src}"></video><div class="bigplay" id="pvbig"></div><button id="pvnew">新预览已生成 · 点这里切换（从当前位置继续）</button>`
    :'<div class="none">还没有预览，点右上角「更新预览」生成</div>')+'<button id="follow">↩ 跟随播放</button>';
  const nv=$('#pvv');
  if(nv){nv.muted=wasMuted}
  if(nv&&keep){const restore=()=>{nv.currentTime=Math.min(keep.t,Math.max(0,nv.duration-0.5)); if(keep.playing) nv.play().catch(()=>{})};
    nv.readyState>=1?restore():nv.addEventListener('loadedmetadata',restore,{once:true})}
  const nb=$('#pvnew'); if(nb) nb.onclick=()=>swapPreview();
  $('#follow').onclick=()=>{resumeFollow(); curIdx=-2; onPreviewTime(true)};
  const v=$('#pvv'); if(v){v.addEventListener('timeupdate',()=>onPreviewTime(false)); v.addEventListener('seeked',()=>onPreviewTime(true))}
}
function swapPreview(){const v=$('#pvv'); loadPreview(v?{t:v.currentTime,playing:!v.paused&&!v.ended}:null)}
async function checkNewPreview(){
  const n=await latestPreview(); if(!n||n===PVNAME) return;
  const v=$('#pvv');
  if(!v||v.paused||v.ended) swapPreview();                 // not watching: switch quietly, keep position
  else {const b=$('#pvnew'); if(b) b.style.display='block'} // watching: offer, never interrupt
}
setInterval(checkNewPreview,5000);
function seekPreview(t){
  const v=$('#pvv'); if(!v){showErr('还没有预览，先点「更新预览」');return}
  resumeFollow(); v.currentTime=t+0.01; v.play().catch(()=>{});
}
// ---- cards follow the preview
let curIdx=-1, followOff=0, progUntil=0;
function progScroll(ms=1500){progUntil=Date.now()+ms}
window.addEventListener('scrollend',()=>{if(progUntil>Date.now()) progUntil=Date.now()+100});
function shotAt(t){
  const st=starts(); let last=-1;
  for(let i=0;i<D.shots.length;i++){if(!isOn(D.shots[i])) continue; last=i; if(t<st[i]+sdur(D.shots[i])) return i}
  return last;
}
function following(){return Date.now()>=followOff}
function pauseFollow(){
  followOff=Date.now()+6000; const v=$('#pvv');
  $('#follow').style.display=v&&!v.paused?'block':'none';
}
function resumeFollow(){followOff=0; $('#follow').style.display='none'}
function scrollToCard(i){
  const r=document.getElementById('row-'+i); if(!r) return;
  const top=r.getBoundingClientRect().top+window.scrollY-$('#bar').offsetHeight-12;
  progScroll(); window.scrollTo({top:Math.max(0,top),behavior:'smooth'});
}
function onPreviewTime(force){
  const v=$('#pvv'); if(!v||!D) return;
  if(!following()) return; if($('#follow').style.display!=='none') $('#follow').style.display='none';
  const i=shotAt(v.currentTime);
  if(i!==curIdx){
    const o=document.getElementById('row-'+curIdx); if(o) o.classList.remove('cur');
    curIdx=i; const r=document.getElementById('row-'+i); if(r) r.classList.add('cur');
    scrollToCard(i);
  } else if(force) scrollToCard(i);
}
window.addEventListener('scroll',()=>{if(Date.now()>progUntil) pauseFollow()},{passive:true});
['wheel','touchmove'].forEach(ev=>window.addEventListener(ev,()=>{progUntil=0; pauseFollow()},{passive:true}));
L.addEventListener('focusin',pauseFollow);
L.addEventListener('input',pauseFollow);
setInterval(()=>{if(following()&&$('#follow').style.display!=='none') $('#follow').style.display='none'},1000);
async function save(){
  for(const [k,s] of D.shots.entries()) if(!(s.in>=0&&s.in<s.out)){showErr(`第 ${k+1} 段：开始时间要早于结束时间`);return false}
  const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(D)});
  const j=await r.json();
  if(!j.ok){showErr('保存失败：\n'+(j.errors||[j.error]).join('\n'));return false}
  if(j.mtime) mtime=j.mtime; $('#stale').style.display='none';
  showErr(''); base=JSON.stringify(D); setDirty(false); if(!polling) flash(j.unchanged?'没有改动':'已保存（旧版本已自动备份）');
  return true;
}
function flash(msg){const rs=$('#rs'); rs.style.display='block'; rs.className='done'; $('#rstext').textContent=msg; $('#rsbar').parentNode.style.display='none'; setTimeout(()=>{if(!polling) rs.style.display='none'},3000)}
async function startRender(mode){
  if(!await save()) return;
  const r=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
  const j=await r.json();
  if(!j.ok){showErr('没法开始生成：'+j.error);return}
  startPoll();
}
function startPoll(){if(polling) return; setBusy(true); pollOnce(); polling=setInterval(pollOnce,2000)}
var PNAME='';
function tabTitle(t){document.title=t?t+' · '+PNAME:PNAME+' · 剪辑审阅'}
async function pollOnce(){
  let st; try{st=await (await fetch('/api/render_status')).json()}catch(e){return}
  const rs=$('#rs'); rs.style.display='block'; $('#rsbar').parentNode.style.display='';
  const lbl=st.mode==='final'?'导出成片':'生成预览';
  const p=Math.round((st.progress||0)*100);
  $('#rsbar').style.width=p+'%';
  if(st.state==='error'){
    stopPoll(); tabTitle('⚠️ '+lbl+'失败'); rs.className='err'; $('#rstext').textContent=lbl+'失败'; showErr(lbl+'失败：\n'+(st.error||'未知错误'));
  } else if(st.state==='done'&&!st.active){
    stopPoll(); tabTitle(st.mode==='final'?'✅ 成片已导出':'✅ 预览已更新'); setTimeout(()=>tabTitle(''),6000); rs.className='done'; $('#rsbar').style.width='100%';
    $('#rstext').textContent=st.mode==='final'?'成片已导出'+(st.output?'：'+st.output:''):'预览已更新';
    if(st.mode!=='final') checkNewPreview();
  } else { tabTitle(`⏳ ${p}% ${lbl}中`); rs.className=''; $('#rstext').textContent=`${lbl}中… ${st.step||''}（${p}%）`; }
}
function stopPoll(){clearInterval(polling); polling=null; setBusy(false)}
function setBusy(b){$('#bPrev').disabled=b; $('#bFinal').disabled=b}
function disarmFinal(){clearTimeout(finalArmed); finalArmed=null; const b=$('#bFinal'); b.textContent='导出成片'; b.classList.remove('danger')}
document.addEventListener('mouseup',e=>{const b=e.target.closest&&e.target.closest('button'); if(b) setTimeout(()=>b.blur(),0)});
$('#bSave').onclick=save;
$('#bPrev').onclick=()=>startRender('preview');
$('#bFinal').onclick=()=>{
  const b=$('#bFinal');
  if(!finalArmed){b.textContent='再点一次确认'; b.classList.add('danger'); finalArmed=setTimeout(disarmFinal,4000); return}
  disarmFinal(); startRender('final');
};
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
new ResizeObserver(()=>document.documentElement.style.setProperty('--barh',$('#bar').offsetHeight+'px')).observe($('#bar'));
window.addEventListener('pageshow',e=>{if(e.persisted) checkRemote()});
$('#bReload').onclick=async()=>{await fetchEdl(); render()};
try{if(localStorage.getItem('rv_help')==='0') document.body.classList.add('nohelp')}catch(e){}
$('#helpX').onclick=()=>{document.body.classList.add('nohelp'); try{localStorage.setItem('rv_help','0')}catch(e){}};
window.addEventListener('focus',checkRemote);
setInterval(checkRemote,15000);
load();
</script>
<script>
__QA_JS__
// ---- questions for the creator, popping up next to the preview at their cut time
(()=>{
  const pv=()=>document.getElementById('pvv');
  let QI=[], qDur=0, qW=0;
  function drawMarks(){
    const v=pv(), box=document.getElementById('qmarks'), d=v&&v.duration;
    qDur=d||0; if(!box) return;
    box.innerHTML=d?QI.map(({q,p})=>`<div class="qm${q.answer?' done':''}" data-id="${esc(q.id)}" style="left:${Math.min(100,p/d*100)}%" title="${esc(fmt(p)+' '+q.text)}"></div>`).join(''):'';
  }
  const api=initQuestions({
    root:document.getElementById('qpanel'), card:document.getElementById('qcard'),
    pos:q=>typeof q.t==='number'?q.t:null,
    now:()=>{const v=pv(); return v&&v.readyState>=1?v.currentTime:null},
    playing:()=>{const v=pv(); return !!v&&!v.paused&&!v.ended},
    pause:()=>{const v=pv(); if(v) v.pause()},
    seek:t=>seekPreview(t),
    label:(q,p)=>fmt(p),
    markers:it=>{QI=it; drawMarks()},
    onTick:(pos,q)=>{
      document.body.classList.toggle('qactive',!!q);
      const v=pv(), st=document.getElementById('qstrip');
      st.classList.toggle('on',!!v);
      if(!v) return;
      if((v.duration||0)!==qDur) drawMarks();
      const w=v.clientWidth; if(w&&w!==qW){qW=w; st.style.width=w+'px'}   // line up under the picture
      if(qDur&&pos!=null) st.querySelector('.ph').style.left=Math.min(100,pos/qDur*100)+'%';
    }
  });
  document.getElementById('qmarks').addEventListener('click',e=>{const m=e.target.closest('.qm'); if(m) api.jump(m.dataset.id)});
})();
</script></body></html>
"""


# Chat messages carry where he is: the preview's cut time, plus the raw clip/time while a shot's own player is open.
CHAT_CTX = r"""<script>window.chatCtx=()=>{const v=document.getElementById('pvv'),c={cut_t:v?Math.round((v.currentTime||0)*10)/10:null};
  if(modalShot>=0&&D&&D.shots[modalShot]){c.clip=D.shots[modalShot].clip;c.clip_t=Math.round((mv.currentTime||0)*10)/10}return c}</script></body>"""
PAGE = CHAT.inject(QS.inject(PAGE.replace("__THEME_CSS__", THEME.CSS)).replace("</body>", CHAT_CTX, 1), "cut")


def main():
    global PROJECT
    ap = argparse.ArgumentParser(description="Review/edit page for an auto-assembled vlog EDL")
    ap.add_argument("project", help="project folder name under ~/Desktop, or a path")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    PROJECT = os.path.abspath(E.project_dir(a.project))
    if not os.path.isfile(E.edl_path(PROJECT)):
        sys.exit(f"No EDL at {E.edl_path(PROJECT)}")
    print(f"Review page: http://{a.host}:{a.port}/")
    app.run(host=a.host, port=a.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
