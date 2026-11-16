"""「本地视频」 in 审片.app: any video he drags onto the window, played with the review pages' player (0.75×–3×).

Not tied to an episode (creator 2026-11-16: QuickTime has no 2×, so he piggybacks on this player). Flow:
  * the Swift app takes the drop (DropWebView in app/main.swift: real file paths, the web view never navigates to the
    file) and hands the paths to the shell page, which POSTs them to /api/local/add;
  * each file is COPIED into ~/Movies/审片播放器/ (the original is never moved or changed). Same volume (Desktop,
    Downloads: APFS) = clonefile(2), instant and no extra disk space until one side changes; another volume (external
    drive) = a chunked copy in a thread with progress (/api/local/list `jobs`), and while it runs the player plays the
    original through /local/src/<job id> (only that dropped file, only while its copy runs; then it redirects to the
    copy). Same name + same size already in the folder = no second copy;
  * the sidebar lists whatever video is in that folder (newest first), so files put there in Finder show up too;
  * /local/v/<name> serves only regular files directly inside that folder (resolved symlinks, no `..`, no hidden
    files, video extensions only); /local/play is the player page; positions + the last speed are kept in
    ~/Library/Application Support/审片/local_player.json.
「在 Finder 中显示」 / 「从列表移除」 (= the copy goes to the macOS Trash) are done by the Swift app (NSWorkspace /
FileManager.trashItem), never here: nothing in this module deletes a finished copy.

Env (tests): SHENPIAN_LOCAL (the folder), SHENPIAN_STATE (its directory holds local_player.json).
"""
import ctypes
import json
import os
import secrets
import shutil
import threading
import time
import urllib.parse

from flask import Response, abort, jsonify, redirect, request, send_file

from . import theme as THEME

HOME = os.path.expanduser("~")
# the WebView (WebKit) plays mp4 / mov / m4v; webm (VP8/VP9) on recent macOS; mkv only when WebKit knows its codecs
EXTS = {".mp4": "video/mp4", ".m4v": "video/x-m4v", ".mov": "video/quicktime", ".webm": "video/webm",
        ".mkv": "video/x-matroska"}
SPEEDS = (0.75, 1, 1.25, 1.5, 2, 3)
CHUNK = 8 << 20


def folder():
    d = os.environ.get("SHENPIAN_LOCAL") or os.path.join(HOME, "Movies", "审片播放器")
    os.makedirs(d, exist_ok=True)
    return os.path.realpath(d)


def state_file():
    st = os.environ.get("SHENPIAN_STATE") or os.path.join(HOME, "Library", "Application Support", "审片", "ports.json")
    return os.path.join(os.path.dirname(st), "local_player.json")


def safe_path(name):
    """The file `name` directly inside the folder, or None. A bare, visible file name with a video extension whose
    resolved path (symlinks followed) is a regular file right inside the resolved folder."""
    if not isinstance(name, str) or not name or len(name) > 255 or any(c in name for c in "/\\\0") \
            or name.startswith(".") or os.path.splitext(name)[1].lower() not in EXTS:
        return None
    d = folder()
    p = os.path.realpath(os.path.join(d, name))
    if os.path.dirname(p) != d or not os.path.isfile(p):
        return None
    return p


# ---------------------------------------------------------------- positions + last speed

_state_lock = threading.Lock()


def load_state():
    try:
        with open(state_file(), encoding="utf-8") as f:
            s = json.load(f)
        if isinstance(s, dict):
            s.setdefault("pos", {})
            return s
    except (OSError, ValueError):
        pass
    return {"speed": 1, "pos": {}}


def _save_state(s):
    os.makedirs(os.path.dirname(state_file()), exist_ok=True)
    tmp = state_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, state_file())


def remember(name, t=None, dur=None, speed=None, volume=None):
    """Store where he is in `name` (near the end = finished: the next open starts from the top) and the last speed."""
    with _state_lock:
        s = load_state()
        if speed is not None:
            s["speed"] = speed
        if volume is not None:
            s["volume"] = volume
        if name is not None and t is not None:
            done = bool(dur) and t >= dur - 5
            s["pos"][name] = {"t": 0 if done else round(t, 1), "dur": round(dur or 0, 1), "done": done,
                              "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _save_state(s)
        return s


# ---------------------------------------------------------------- the folder

def list_videos():
    """[{name, size, added, t, dur, done}] newest first (ctime: when the file arrived in the folder)."""
    d = folder()
    pos = load_state()["pos"]
    rows = []
    try:
        names = os.listdir(d)
    except OSError:
        return []
    for n in names:
        p = safe_path(n)
        if not p:
            continue
        st = os.stat(os.path.join(d, n))
        ps = pos.get(n) or {}
        rows.append({"name": n, "size": st.st_size, "added": st.st_ctime, "t": ps.get("t") or 0,
                     "dur": ps.get("dur") or 0, "done": bool(ps.get("done")), "notes": open_comments(n)})
    return sorted(rows, key=lambda r: (-r["added"], r["name"]))


# ---------------------------------------------------------------- copying in

JOBS = {}   # id -> {id, name, orig, src, size, copied, state: copying | done | error, error, started, ended}
_jobs_lock = threading.Lock()
_libc = ctypes.CDLL(None, use_errno=True)


def _clone(src, dst):
    """APFS clonefile(2): an instant copy-on-write copy on the same volume. False when it can't (other volume)."""
    fn = getattr(_libc, "clonefile", None)
    if fn is None or os.environ.get("SHENPIAN_NO_CLONE") == "1":   # tests: force the chunked copy
        return False
    return fn(os.fsencode(src), os.fsencode(dst), ctypes.c_uint32(0)) == 0


def _finish(job, tmp):
    """The finished temp file becomes <name> (a fresh name if one appeared meanwhile)."""
    d = folder()
    stem, ext = os.path.splitext(job["name"])
    name, k = job["name"], 2
    while os.path.lexists(os.path.join(d, name)):
        name, k = f"{stem} ({k}){ext}", k + 1
    os.rename(tmp, os.path.join(d, name))
    job.update(name=name, copied=job["size"], state="done", ended=time.time())


def _copy(job, tmp):
    try:
        with open(job["src"], "rb") as fi, open(tmp, "wb") as fo:
            while True:
                b = fi.read(CHUNK)
                if not b:
                    break
                fo.write(b)
                job["copied"] += len(b)
        shutil.copystat(job["src"], tmp)
        with _jobs_lock:
            _finish(job, tmp)
    except Exception as e:   # disk full, drive unplugged, ...
        job.update(state="error", error=f"拷贝失败：{e.__class__.__name__}: {e}"[:300], ended=time.time())
        try:
            os.remove(tmp)   # our own half-written temp file (hidden, never listed), not a copy he has
        except OSError:
            pass


def add(path, wait=False):
    """_add, and the copy remembers where it came from (批注 write a sidecar next to that original, local_comments.py)."""
    r = _add(path, wait)
    src = os.path.realpath(path)
    if os.path.dirname(src) != folder():
        remember_orig(r["name"], src)
    return r


def remember_orig(name, src, guessed=False):
    with _state_lock:
        s = load_state()
        o = s.setdefault("orig", {})
        if o.get(name, {}).get("path") != src or o.get(name, {}).get("guessed") != guessed:
            o[name] = {"path": src, "guessed": guessed, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            _save_state(s)


def open_comments(name):
    """How many unresolved 批注 a video has (the sidebar shows it)."""
    try:
        with open(os.path.join(folder(), ".comments", name + ".json"), encoding="utf-8") as f:
            return sum(1 for c in json.load(f).get("comments") or [] if not c.get("resolved"))
    except (OSError, ValueError, AttributeError):
        return 0


def _add(path, wait=False):
    """Copy one dropped file into the folder. -> {name, ready, job, dup}; ready = the copy can be played now.
    Raises ValueError with a message for him (not a video, a folder, missing, no space, ...)."""
    if not isinstance(path, str) or not path or not os.path.isabs(path) or "\0" in path:
        raise ValueError("这不是一个文件路径")
    base = os.path.basename(path.rstrip("/"))
    src = os.path.realpath(path)
    if os.path.isdir(src):
        raise ValueError(f"「{base}」是文件夹，请把里面的视频文件拖进来")
    if not os.path.isfile(src):
        raise ValueError(f"找不到「{base}」")
    ext = os.path.splitext(base)[1].lower()
    if ext not in EXTS:
        raise ValueError(f"「{base}」不是能播的视频（支持 mp4 / mov / m4v / webm，mkv 要看编码）")
    try:
        size = os.path.getsize(src)
        with open(src, "rb"):
            pass
    except OSError as e:
        raise ValueError(f"读不了「{base}」：{e.strerror or e}（系统设置 › 隐私与安全性 › 文件和文件夹 里给「审片」开权限）") from None
    d = folder()
    if os.path.dirname(src) == d:   # already one of ours (e.g. dragged back in from Finder)
        return {"name": os.path.basename(src), "ready": True, "job": None, "dup": True}
    with _jobs_lock:
        for j in JOBS.values():   # the same file is being copied right now
            if j["state"] == "copying" and j["orig"] == base and j["size"] == size:
                return {"name": j["name"], "ready": False, "job": j["id"], "dup": True}
        stem = os.path.splitext(base.lstrip(".") or "video" + ext)[0]
        name, k = stem + ext, 2
        busy = {j["name"] for j in JOBS.values() if j["state"] == "copying"}
        while os.path.lexists(os.path.join(d, name)) or name in busy:
            p = os.path.join(d, name)
            if name not in busy and os.path.isfile(p) and not os.path.islink(p) and os.path.getsize(p) == size:
                return {"name": name, "ready": True, "job": None, "dup": True}   # same name + size: already here
            name, k = f"{stem} ({k}){ext}", k + 1
        jid = secrets.token_hex(8)
        job = {"id": jid, "name": name, "orig": base, "src": src, "size": size, "copied": 0, "state": "copying",
               "error": None, "started": time.time(), "ended": None}
        tmp = os.path.join(d, f".partial-{jid}{ext}")
        if _clone(src, tmp):   # instant: nothing to show progress for
            _finish(job, tmp)
            return {"name": job["name"], "ready": True, "job": None, "dup": False}
        free = shutil.disk_usage(d).free
        if size + (512 << 20) > free:
            raise ValueError(f"磁盘空间不够：「{base}」{size / 1e9:.1f} GB，只剩 {free / 1e9:.1f} GB")
        JOBS[jid] = job
    th = threading.Thread(target=_copy, args=(job, tmp), daemon=True)
    th.start()
    if wait:
        th.join()
    return {"name": job["name"], "ready": job["state"] == "done", "job": jid, "dup": False}


def known(name):
    """A video of the folder, or one still being copied in (its player and position work before the copy is there)."""
    return bool(safe_path(name)) or any(j["state"] == "copying" and j["name"] == name for j in list(JOBS.values()))


def jobs_now():
    """Copies running now, plus ones that ended in the last 10 s (the sidebar shows 「拷好了」 / the error)."""
    now = time.time()
    return [{k: j[k] for k in ("id", "name", "orig", "size", "copied", "state", "error")}
            for j in list(JOBS.values()) if j["state"] == "copying" or now - (j["ended"] or 0) < 10]


# ---------------------------------------------------------------- routes

def _same_origin():
    """POSTs only from this server's own pages (the shell / player); a JSON body is required too."""
    o = request.headers.get("Origin")
    if o and urllib.parse.urlsplit(o).netloc != request.host:
        abort(403)
    if not request.is_json:
        abort(415)


def register(app):
    @app.get("/api/local/list")
    def api_local_list():
        return jsonify({"folder": folder(), "items": list_videos(), "jobs": jobs_now()})

    @app.post("/api/local/add")
    def api_local_add():
        _same_origin()
        paths = (request.get_json(silent=True) or {}).get("paths")
        if not isinstance(paths, list) or not paths or len(paths) > 50:
            return jsonify({"ok": False, "error": "没有文件"}), 400
        items, rejected = [], []
        for p in paths:
            try:
                items.append(add(p))
            except ValueError as e:
                rejected.append({"path": p if isinstance(p, str) else "", "error": str(e)})
        return jsonify({"ok": bool(items), "items": items, "rejected": rejected})

    @app.get("/api/local/state")
    def api_local_state():
        name = request.args.get("name")
        if not known(name):
            abort(404)
        s = load_state()
        job = JOBS.get(request.args.get("job") or "")
        return jsonify({"name": name, "speed": s.get("speed", 1), "volume": s.get("volume"),
                        **(s["pos"].get(name) or {"t": 0, "dur": 0, "done": False}),
                        "job": {k: job[k] for k in ("id", "name", "size", "copied", "state", "error")} if job else None})

    @app.post("/api/local/pos")
    def api_local_pos():
        _same_origin()
        b = request.get_json(silent=True) or {}
        name, t, dur, sp, vol = b.get("name"), b.get("t"), b.get("dur"), b.get("speed"), b.get("volume")
        if name is not None and not known(name):
            return jsonify({"ok": False}), 404
        num = lambda x, hi: isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= hi   # noqa: E731
        if (t is not None and not num(t, 1e6)) or (dur is not None and not num(dur, 1e6)) \
                or (sp is not None and sp not in SPEEDS) or (vol is not None and not num(vol, 1)):
            return jsonify({"ok": False}), 400
        remember(name, t, dur, sp, vol)
        return jsonify({"ok": True})

    @app.get("/local/v/<path:name>")
    def local_video(name):
        p = safe_path(name)
        if not p:
            abort(404)
        return send_file(p, mimetype=EXTS[os.path.splitext(p)[1].lower()], conditional=True, max_age=0)

    @app.get("/local/src/<jid>")
    def local_src(jid):
        """The original of a file being copied in, so it plays at once; once the copy is there, the copy."""
        j = JOBS.get(jid)
        if not j or j["state"] == "error":
            abort(404)
        if j["state"] == "done":
            return redirect("/local/v/" + urllib.parse.quote(j["name"]))
        return send_file(j["src"], mimetype=EXTS[os.path.splitext(j["src"])[1].lower()] if
                         os.path.splitext(j["src"])[1].lower() in EXTS else "video/mp4", conditional=True, max_age=0)

    from . import local_comments as LC   # 批注 (local_comments.py imports this module)

    @app.get("/api/local/comments")
    def api_local_comments():
        name = request.args.get("name")
        if not known(name):
            abort(404)
        return jsonify(LC.get(name))

    @app.post("/api/local/comments")
    def api_local_comments_change():
        _same_origin()
        b = request.get_json(silent=True) or {}
        if not known(b.get("name")):
            return jsonify({"ok": False, "error": "没有这个视频"}), 404
        try:
            return jsonify(dict(LC.change(b["name"], b.get("op"), b), ok=True))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.get("/api/local/comments.md")
    def api_local_comments_md():
        """The md without image links (「复制全部批注」, for a session that can't see this Mac)."""
        name = request.args.get("name")
        if not known(name):
            abort(404)
        LC.get(name)
        return Response(LC.markdown(name, images=None), mimetype="text/plain; charset=utf-8")

    @app.get("/local/play")
    def local_play():
        return Response(PAGE, mimetype="text/html")


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>本地视频</title>
<style>
__THEME_CSS__
html,body{height:100%;overflow:hidden}
body{background:var(--bg);user-select:none}
.page{display:grid;grid-template-columns:minmax(0,1fr);height:100vh}
html.notes .page{grid-template-columns:minmax(0,1fr) clamp(320px,27vw,420px)}
.stage{min-width:0;min-height:0;display:flex;flex-direction:column;align-items:center;padding:16px 24px 12px}
#wrap{--ar:1.7778;position:relative;width:min(100%,calc((100vh - 96px)*var(--ar)));flex:none}
#pv{position:relative;width:100%;aspect-ratio:var(--ar);background:var(--stage);border-radius:var(--r-lg);overflow:hidden;box-shadow:var(--sh-1)}
#pv video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block;cursor:pointer}
#msg{position:absolute;inset:0;display:none;align-items:center;justify-content:center;text-align:center;padding:30px;color:var(--stage-ink);
  font-size:14px;line-height:1.9;z-index:6;background:var(--stage)}
#msg.on{display:flex}
#msg small{color:var(--stage-mute);font-size:12px}
.bigplay{position:absolute;left:50%;top:50%;width:76px;height:76px;margin:-38px 0 0 -38px;border-radius:50%;background:rgba(0,0,0,.5);backdrop-filter:blur(4px);
  pointer-events:none;z-index:3;transition:opacity .2s ease,transform .2s ease}
.bigplay::after{content:'';position:absolute;left:30px;top:23px;border-style:solid;border-width:15px 0 15px 25px;border-color:transparent transparent transparent #fff}
.bigplay.hide{opacity:0;transform:scale(1.25)}
#toast{position:absolute;left:50%;top:14px;transform:translate(-50%,-8px);z-index:8;padding:7px 16px;border-radius:999px;background:rgba(20,20,22,.86);
  color:#fff;font-size:13px;opacity:0;pointer-events:none;transition:opacity .2s,transform .2s;white-space:nowrap}
#toast.on{opacity:1;transform:translate(-50%,0)}
/* YouTube-style controls on the picture (same look as the 成片 player in review_server.py): progress bar, then
   play + time | speeds, volume, fullscreen. Always shown in the window; in fullscreen they fade after 2.5 s of stillness. */
#ui{position:absolute;left:0;right:0;bottom:0;z-index:5;padding:36px 12px 2px;color:#fff;pointer-events:none;
  background:linear-gradient(transparent,rgba(0,0,0,.22) 35%,rgba(0,0,0,.62));transition:opacity .25s}
#ui>*{pointer-events:auto}
html.fs.idle #ui{opacity:0}
html.fs.idle #ui>*{pointer-events:none}
html.fs.idle .stage,html.fs.idle .stage *{cursor:none!important}
#bar{position:relative;height:24px;cursor:pointer;touch-action:none}
#bar .tr{position:absolute;left:0;right:0;bottom:6px;height:4px;border-radius:2px;background:rgba(255,255,255,.26);overflow:hidden;transition:height .1s,bottom .1s}
#bar:hover .tr,#bar.drag .tr{bottom:4px;height:8px}
#bar .bf,#bar .pl{position:absolute;left:0;top:0;bottom:0;width:0}
#bar .bf{background:rgba(255,255,255,.22)}
#bar .pl{background:rgba(255,255,255,.92)}
#bar .ph{position:absolute;top:16px;width:0;height:0;pointer-events:none}
#bar .ph::before{content:'';position:absolute;left:-7px;top:-7px;width:14px;height:14px;border-radius:50%;background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,.25);
  transform:scale(0);transition:transform .1s}
#bar:hover .ph::before,#bar.drag .ph::before{transform:scale(1)}
#tip{position:absolute;bottom:26px;transform:translateX(-50%);display:none;background:rgba(20,20,20,.88);color:#fff;font-size:12px;font-weight:600;
  padding:2px 8px;border-radius:6px;font-variant-numeric:tabular-nums;white-space:nowrap;pointer-events:none}
#bar:hover #tip,#bar.drag #tip{display:block}
#ctl{display:flex;align-items:center;gap:2px;height:40px}
#ctl .sp{flex:1}
#ctl button{border:0;background:transparent;color:#fff;padding:0}
#ctl>button,#vol>button{width:36px;height:36px;border-radius:8px;display:inline-grid;place-items:center;filter:drop-shadow(0 1px 1px rgba(0,0,0,.45))}
#ctl>button:hover,#vol>button:hover{background:rgba(255,255,255,.16)}
#ctl svg{width:20px;height:20px}
#time{margin-left:6px;font-size:13px;color:rgba(255,255,255,.82);font-variant-numeric:tabular-nums;white-space:nowrap;text-shadow:0 1px 2px rgba(0,0,0,.6)}
#time b{color:#fff;font-weight:600}
#speeds{display:flex;gap:2px;padding:2px;border-radius:8px;background:rgba(255,255,255,.14);margin-right:6px}
#speeds button{height:24px;padding:0 8px;border-radius:6px;color:rgba(255,255,255,.85);font-size:12px;font-weight:600;font-variant-numeric:tabular-nums}
#speeds button:hover{background:rgba(255,255,255,.14)}
#speeds button.on{background:#fff;color:#111}
#vol{display:flex;align-items:center}
#volS{position:relative;width:0;height:36px;overflow:hidden;cursor:pointer;touch-action:none;transition:width .15s}
#vol:hover #volS,#volS.drag{width:76px}
#volS::before,#volS i{content:'';position:absolute;left:8px;top:16.5px;height:3px;border-radius:2px}
#volS::before{right:8px;background:rgba(255,255,255,.3)}
#volS i{width:0;background:#fff}
#volS i::after{content:'';position:absolute;right:-6px;top:-4.5px;width:12px;height:12px;border-radius:50%;background:#fff}
/* under the player: the file name, the copy line, the keys */
#row{display:flex;align-items:baseline;gap:12px;padding:10px 2px 0;width:100%;min-width:0}
#nm{font-size:17px;font-weight:600;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#cp{font-size:12px;color:var(--text-3);white-space:nowrap;font-variant-numeric:tabular-nums}
#row .sp{flex:1}
#keys{font-size:12px;color:var(--text-3);white-space:nowrap}
#keys kbd{font-size:11px;padding:1px 5px}
#keys span+span{margin-left:10px}
@media (max-width:1100px){#keys{display:none}}
/* fullscreen: the picture fills the window (in the app the window itself goes fullscreen, see app_server pageFs) */
html.fs body{background:#000}
html.fs .stage{padding:0;justify-content:center}
html.fs #wrap{width:min(100%,calc(100vh*var(--ar)))}
html.fs #pv{border-radius:0;box-shadow:none}
html.fs #row{display:none}
html.fs #ui{padding:48px 18px 6px}
/* ---- 批注 (local_comments.py): toggle in the control bar, a rail on the right; not a chat, nothing is sent anywhere */
#bNotes{height:26px!important;width:auto!important;padding:0 10px!important;display:inline-flex!important;align-items:center;white-space:nowrap;margin-right:6px;border-radius:7px;font-size:12px;font-weight:600;
  color:rgba(255,255,255,.88)!important;background:rgba(255,255,255,.14)!important;filter:none!important}
#bNotes:hover{background:rgba(255,255,255,.24)!important}
#bNotes.on{background:#fff!important;color:#111!important}
#bNotes i{font-style:normal;font-variant-numeric:tabular-nums;margin-left:5px;opacity:.75}
#bar .cmk{position:absolute;top:1px;width:0;height:0;margin-left:-5px;border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:8px solid var(--box);cursor:pointer;filter:drop-shadow(0 0 1px rgba(0,0,0,.7))}
html:not(.notes) #bar .cmk{display:none}
.bx{position:absolute;z-index:6;border:2px solid var(--box);border-radius:3px;pointer-events:none;display:none;box-shadow:0 0 0 1px rgba(0,0,0,.5)}
.bxdraw{position:absolute;z-index:7;cursor:crosshair;background:var(--box-veil)}
#rail{display:none;flex-direction:column;min-height:0;background:var(--bg-rail);color:var(--text);border-left:1px solid var(--line);user-select:text;font-size:var(--fs)}
html.notes #rail{display:flex}
.rh{display:flex;align-items:center;gap:8px;padding:12px 12px 6px 16px;flex:none}
.rh b{font-size:var(--fs-md);font-weight:600}
.rh #rn{color:var(--text-3);font-size:var(--fs-sm);font-variant-numeric:tabular-nums}
.rh .sp{flex:1}
.rh button{height:28px;padding:0 10px;font-size:var(--fs-sm);border-radius:999px;border:1px solid var(--btn-sec-line);background:var(--btn-sec-bg);color:var(--btn-sec-ink)}
.rh button:hover{background:var(--surface-2)}
#rsc{padding:0 16px 8px;font-size:var(--fs-xs);color:var(--text-3);line-height:1.6;flex:none;word-break:break-all}
#rsc.warn{color:var(--q-ink)}
#rlist{flex:1;min-height:0;overflow-y:auto;padding:4px 10px 10px;border-top:1px solid var(--line)}
.rempty{color:var(--text-3);font-size:var(--fs-sm);text-align:center;padding:24px 12px;line-height:1.8}
.rsec{font-size:var(--fs-xs);color:var(--text-3);padding:12px 6px 4px}
.cm{padding:8px 8px 9px;border-radius:var(--r-sm);transition:background var(--dur-1) var(--ease)}
.cm:hover{background:var(--surface-2)}
.cm.on{background:var(--accent-soft)}
.cm .ch{display:flex;align-items:center;gap:6px;font-size:var(--fs-xs);color:var(--text-3)}
.cm .ct{color:var(--accent);font-weight:600;font-variant-numeric:tabular-nums;cursor:pointer;font-size:var(--fs-sm)}
.cm .ct:hover{text-decoration:underline}
.cm .ch .sp{flex:1}
.cm .ch button{border:0;background:transparent;color:var(--text-3);font-size:var(--fs-xs);height:22px;padding:0 6px;border-radius:6px;visibility:hidden}
.cm:hover .ch button,.cm .ch button.res{visibility:visible}
.cm .ch button:hover{background:var(--surface-3);color:var(--text)}
.cm .ch button.del:hover{color:var(--danger)}
.cm .ch button.res{width:22px;padding:0;border:1.5px solid var(--line-2);border-radius:50%;height:22px;color:transparent;font-weight:700}
.cm .ch button.res:hover{border-color:var(--st-pass);color:var(--st-pass);background:transparent}
.cm.done .ch button.res{background:var(--st-pass);border-color:var(--st-pass);color:#fff}
.cm .cx{margin-top:3px;white-space:pre-wrap;word-break:break-word;line-height:1.55;color:var(--text)}
.cm.done .cx{color:var(--text-3)}
.cm.done .ct{color:var(--text-3)}
.cm textarea,#rin{width:100%;resize:none;border:1px solid var(--line-2);border-radius:var(--r-sm);padding:7px 10px;font:inherit;line-height:1.45;
  background:var(--surface);color:var(--text)}
.cm textarea{margin-top:4px;min-height:54px;border-color:var(--accent-line)}
#rform{flex:none;border-top:1px solid var(--line);padding:10px 12px 12px;display:flex;flex-direction:column;gap:7px}
#rin{min-height:40px;max-height:140px}
#rin:focus,.cm textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-ring)}
.rrow{display:flex;align-items:center;gap:6px}
.rrow .sp{flex:1}
#rat{font-size:var(--fs-xs);color:var(--text-3);font-variant-numeric:tabular-nums}
#rat b{color:var(--accent);font-weight:600}
.rrow button{height:30px;padding:0 12px;font-size:var(--fs-sm);border-radius:var(--r-sm);border:1px solid var(--btn-sec-line);background:var(--btn-sec-bg);color:var(--btn-sec-ink)}
.rrow button.on{color:var(--accent);border-color:var(--accent-line);background:var(--accent-soft)}
.rrow button.pri{background:var(--btn-pri-bg);border-color:var(--btn-pri-bg);color:var(--btn-pri-ink)}
/* fullscreen keeps the rail, dark */
html.fs #rail{background:#16171a;border-left-color:#26272b;color-scheme:dark;--surface:#232327;--surface-2:#1d1e21;--surface-3:#303035;--line:#2a2b30;
  --line-2:#3a3b40;--text:#f5f5f7;--text-2:#c7c7cc;--text-3:#8e8e93;--accent-soft:rgba(10,132,255,.18);--btn-sec-bg:#2c2c30;--btn-sec-ink:#f5f5f7;
  --btn-sec-line:#3a3b40;--q-ink:#ffc566;--accent:#4ca2ff}
</style></head><body><div class="page">
<main class="stage">
  <div id="wrap"><div id="pv"><video id="v" playsinline preload="auto"></video><div class="bigplay hide" id="big"></div><div id="msg"></div><div id="toast"></div>
    <div id="ui"><div id="bar"><div class="tr"><div class="bf"></div><div class="pl"></div></div><div class="ph"></div><div id="tip"></div></div>
      <div id="ctl"><button id="bPlay" title="播放 / 暂停（空格）"></button><span id="time"></span><span class="sp"></span>
        <button id="bNotes" title="批注：边看边记，存下来给做这个视频的 session（C）">批注</button><span id="speeds" title="速度（[ 慢一档 · ] 快一档）"></span><span id="vol"><button id="bMute"></button><span id="volS" title="音量"><i></i></span></span><button id="bFs"></button></div></div></div></div>
  <div id="row"><span id="nm"></span><span id="cp"></span><span class="sp"></span>
    <span id="keys"><span><kbd>空格</kbd> 播放/暂停</span><span><kbd>←</kbd><kbd>→</kbd> 5 秒</span><span><kbd>J</kbd><kbd>L</kbd> 10 秒</span><span><kbd>[</kbd><kbd>]</kbd> 速度</span><span><kbd>F</kbd> 全屏</span><span><kbd>M</kbd> 静音</span><span><kbd>C</kbd> 批注</span></span></div>
</main>
<aside id="rail">
  <div class="rh"><b>批注</b><span id="rn"></span><span class="sp"></span><button id="bCopy" title="复制成 Markdown（不带图），可以贴给别的 session">复制全部批注</button></div>
  <div id="rsc"></div>
  <div id="rlist" class="scroll"></div>
  <form id="rform"><textarea id="rin" rows="2" placeholder="写批注…（自动记下当前时间；回车存，Shift+回车换行）"></textarea>
    <div class="rrow"><span id="rat"></span><span class="sp"></span><button type="button" id="bBox" title="在画面上拖一个框，跟这条批注一起存（Esc 取消）">框选</button><button type="submit" class="pri" id="bAdd">存</button></div></form>
</aside></div>
<script>
const $=id=>document.getElementById(id), v=$('v');
const Q=new URLSearchParams(location.search), NAME=Q.get('name')||'', JOB=Q.get('job')||'';
const SPEEDS=[0.75,1,1.25,1.5,2,3], inApp=window.top!==window;
const enc=encodeURIComponent, esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).catch(()=>{});
function fmt(t){t=Math.max(0,t||0);const h=Math.floor(t/3600),m=Math.floor(t%3600/60),s=Math.floor(t%60);
  return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(s).padStart(2,'0')}
const gb=n=>n>=1e9?(n/1e9).toFixed(1)+' GB':Math.max(1,Math.round(n/1e6))+' MB';
let speed=1, toastT=0;
function toast(s){const t=$('toast');t.textContent=s;t.classList.add('on');clearTimeout(toastT);toastT=setTimeout(()=>t.classList.remove('on'),1600)}
const IC_PLAY='<svg viewBox="0 0 16 16" fill="currentColor"><path d="M4.5 2.8v10.4c0 .5.5.8.9.5l8-5.2a.6.6 0 0 0 0-1l-8-5.2c-.4-.3-.9 0-.9.5z"/></svg>',
      IC_PAUSE='<svg viewBox="0 0 16 16" fill="currentColor"><rect x="3.5" y="2.5" width="3" height="11" rx="1"/><rect x="9.5" y="2.5" width="3" height="11" rx="1"/></svg>',
      IC_VOL='<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6v4h2.5l3.5 3V3L5 6z" fill="currentColor"/><path d="M11 5.5a3.5 3.5 0 0 1 0 5M12.8 3.8a6 6 0 0 1 0 8.4"/></svg>',
      IC_MUTE='<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6v4h2.5l3.5 3V3L5 6z" fill="currentColor"/><path d="M11 6l3.5 4M14.5 6L11 10"/></svg>',
      IC_FS='<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10"/></svg>',
      IC_FSX='<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M6 2.5V6H2.5M13.5 6H10V2.5M10 13.5V10h3.5M2.5 10H6v3.5"/></svg>';
$('nm').textContent=NAME;document.title=NAME||'本地视频';
$('speeds').innerHTML=SPEEDS.map(r=>`<button data-r="${r}">${r}×</button>`).join('');
function setSpeed(r,say){speed=r;v.defaultPlaybackRate=r;v.playbackRate=r;
  document.querySelectorAll('#speeds button').forEach(b=>b.classList.toggle('on',+b.dataset.r===r));
  if(say)toast(r+'×');post('/api/local/pos',{speed:r})}
function stepSpeed(d){const i=SPEEDS.indexOf(speed),j=Math.max(0,Math.min(SPEEDS.length-1,(i<0?1:i)+d));setSpeed(SPEEDS[j],true)}
const playPause=()=>{if(v.error)return;v.paused?v.play().catch(()=>{}):v.pause()};
const seekBy=d=>{v.currentTime=Math.max(0,Math.min((v.duration||1e9)-0.05,v.currentTime+d));poke()};
// ---- fullscreen: in the app the window goes fullscreen and the shell hides its chrome (same as the episode pages)
let FS=false;
function applyFs(on){FS=on;document.documentElement.classList.toggle('fs',on);setTimeout(()=>window.BOX&&BOX.redraw(),60);$('bFs').innerHTML=on?IC_FSX:IC_FS;$('bFs').title=on?'退出全屏（F / Esc）':'全屏（F）';tick()}
function toggleFs(){if(inApp){applyFs(!FS);try{parent.postMessage({shenpian:'fs',on:FS},'*')}catch(e){}return}
  if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});else document.documentElement.requestFullscreen().catch(()=>applyFs(!FS))}
document.addEventListener('fullscreenchange',()=>applyFs(!!document.fullscreenElement));
// ---- the source: the copy in the folder, or (while a copy from another drive runs) the original, then the copy
let job=null;
function setSrc(u,t,play){v.src=u;v.addEventListener('loadedmetadata',()=>{if(t>0)v.currentTime=t;v.playbackRate=speed;if(play)v.play().catch(()=>{})},{once:true})}
async function init(){
  let st={};try{st=await (await fetch('/api/local/state?name='+enc(NAME)+'&job='+enc(JOB))).json()}catch(e){}
  if(!st.name){msg('找不到这个视频了<br><small>它可能被移走或放进了废纸篓</small>');return}
  setSpeed(SPEEDS.includes(st.speed)?st.speed:1);if(typeof st.volume==='number')v.volume=st.volume;
  job=st.job&&st.job.state==='copying'?st.job:null;
  const t=st.t>3&&(!st.dur||st.t<st.dur-5)?st.t:0;
  setSrc(job?'/local/src/'+enc(job.id):'/local/v/'+enc(NAME),t,true);
  if(t)toast('从 '+fmt(t)+' 继续');
  if(job)watchJob()}
async function watchJob(){
  while(job){let j=null;try{j=(await (await fetch('/api/local/state?name='+enc(NAME)+'&job='+enc(job.id))).json()).job}catch(e){}
    if(!j){$('cp').textContent='';job=null;break}
    if(j.state==='copying'){$('cp').textContent=`正在拷贝到「影片/审片播放器」 ${Math.floor(j.copied/j.size*100)}% · ${gb(j.copied)} / ${gb(j.size)}（先播原文件）`}
    else if(j.state==='done'){job=null;$('cp').textContent='已拷好';setTimeout(()=>$('cp').textContent='',3000);
      if(!v.error)setSrc('/local/v/'+enc(j.name),v.currentTime,!v.paused);break}
    else{job=null;$('cp').textContent=j.error||'拷贝失败';break}
    await new Promise(r=>setTimeout(r,700))}}
function msg(h){$('msg').innerHTML=h;$('msg').classList.add('on')}
v.addEventListener('error',()=>msg(`这个视频在这里播不了<br><small>${esc(NAME)}<br>WebKit 不认识它的编码（mkv、部分 webm / avi 常见）。可以用 IINA 或 VLC 打开，或者让 agent 转成 mp4 再拖进来。</small>`));
v.addEventListener('loadedmetadata',()=>{if(v.videoWidth&&v.videoHeight)$('wrap').style.setProperty('--ar',(v.videoWidth/v.videoHeight).toFixed(4))});
// ---- where he is: every 5 s while playing, on pause, when the page goes away
let lastSaved=-1;
function savePos(force){if(!v.duration||v.error)return;const t=Math.round(v.currentTime*10)/10;if(!force&&Math.abs(t-lastSaved)<1)return;lastSaved=t;
  const b=JSON.stringify({name:NAME,t,dur:v.duration});
  if(force==='beacon'&&navigator.sendBeacon)navigator.sendBeacon('/api/local/pos',new Blob([b],{type:'application/json'}));else post('/api/local/pos',JSON.parse(b))}
setInterval(()=>{if(!v.paused)savePos()},5000);
v.addEventListener('pause',()=>savePos(true));v.addEventListener('ended',()=>savePos(true));
addEventListener('pagehide',()=>savePos('beacon'));
// ---- controls
$('ctl').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;e.stopPropagation();
  if(b.dataset.r)setSpeed(+b.dataset.r);else if(b.id==='bPlay')playPause();else if(b.id==='bFs')toggleFs();
  else if(b.id==='bMute'){if(v.muted||!v.volume){v.muted=false;if(!v.volume)v.volume=1}else v.muted=true}tick()});
(function(){const s=$('volS');let on=false;
  const set=e=>{const r=s.getBoundingClientRect(),x=Math.max(0,Math.min(1,(e.clientX-r.left-8)/(r.width-16)));v.volume=Math.round(x*100)/100;v.muted=x===0;tick()};
  s.addEventListener('pointerdown',e=>{if(e.button)return;on=true;s.classList.add('drag');s.setPointerCapture(e.pointerId);set(e);e.preventDefault()});
  s.addEventListener('pointermove',e=>{if(on)set(e)});
  const end=()=>{if(!on)return;on=false;s.classList.remove('drag');post('/api/local/pos',{volume:v.volume})};s.addEventListener('pointerup',end);s.addEventListener('pointercancel',end)})();
let scrub=null;
(function(){const b=$('bar');
  const at=e=>{const r=b.getBoundingClientRect();return Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))};
  b.addEventListener('pointermove',e=>{const x=at(e);$('tip').style.left=(x*100)+'%';$('tip').textContent=fmt(x*(v.duration||0));
    if(scrub!=null){scrub=x*(v.duration||0);v.currentTime=scrub;tick()}});
  b.addEventListener('pointerdown',e=>{if(e.button||!v.duration)return;b.setPointerCapture(e.pointerId);b.classList.add('drag');scrub=at(e)*v.duration;v.currentTime=scrub;tick();e.preventDefault()});
  const end=()=>{if(scrub==null)return;scrub=null;b.classList.remove('drag');tick()};b.addEventListener('pointerup',end);b.addEventListener('pointercancel',end)})();
v.addEventListener('click',e=>{e.preventDefault();playPause()});
v.addEventListener('dblclick',e=>{e.preventDefault();toggleFs()});
// in fullscreen the controls (and cursor) fade after 2.5 s of stillness while playing
let actT=0,act=false;
function poke(){act=true;clearTimeout(actT);actT=setTimeout(()=>{act=false;tick()},2500);tick()}
document.addEventListener('mousemove',poke);
function tick(){const d=v.duration||0,t=scrub!=null?scrub:v.currentTime||0;
  document.documentElement.classList.toggle('idle',FS&&!v.paused&&!act&&scrub==null&&!$('ui').matches(':hover'));
  $('big').classList.toggle('hide',!v.paused||!!v.error||!d);
  const pi=v.paused?IC_PLAY:IC_PAUSE,pl=$('bPlay');if(pl.dataset.i!==pi){pl.dataset.i=pi;pl.innerHTML=pi}
  const mo=v.muted||!v.volume,mu=$('bMute'),mi=mo?IC_MUTE:IC_VOL;if(mu.dataset.i!==mi){mu.dataset.i=mi;mu.innerHTML=mi;mu.title=mo?'取消静音（M）':'静音（M）'}
  $('volS').querySelector('i').style.width=`calc((100% - 16px)*${mo?0:v.volume})`;
  const tx=d?`<b>${fmt(t)}</b> / ${fmt(d)}`:'';if($('time').dataset.t!==tx){$('time').dataset.t=tx;$('time').innerHTML=tx}
  let bf=0;for(let i=0;i<v.buffered.length;i++)if(v.buffered.start(i)<=t+0.5)bf=Math.max(bf,v.buffered.end(i));
  const pc=d?Math.min(100,t/d*100):0;$('bar').querySelector('.pl').style.width=pc+'%';$('bar').querySelector('.bf').style.width=(d?Math.min(100,bf/d*100):0)+'%';
  $('bar').querySelector('.ph').style.left=pc+'%'}
setInterval(tick,100);['play','pause','volumechange','seeked','loadedmetadata'].forEach(n=>v.addEventListener(n,tick));
applyFs(false);
// ---- keys: Space / K play-pause, ← → 5 s, J L 10 s, [ ] speed, F fullscreen, M mute, Esc leaves fullscreen
function key(e){const k=e.key;
  if(e.target&&(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||e.target.isContentEditable))return false;   // typing a note
  if(e.code==='Space'||k===' '||k==='k'||k==='K')playPause();
  else if(k==='ArrowRight')seekBy(5);else if(k==='ArrowLeft')seekBy(-5);
  else if(k==='l'||k==='L')seekBy(10);else if(k==='j'||k==='J')seekBy(-10);
  else if(k===']'||k==='】')stepSpeed(1);else if(k==='['||k==='【')stepSpeed(-1);
  else if(k==='f'||k==='F')toggleFs();
  else if(k==='m'||k==='M'){v.muted=!v.muted;toast(v.muted?'静音':'有声');poke()}
  else if(k==='Escape'&&BOX.drawing())return false;
  else if(k==='Escape'&&FS)toggleFs();
  else if(k==='c'||k==='C'){if(!NOTES.on)setNotes(true);setTimeout(()=>$('rin').focus(),30)}
  else return false;
  return true}
document.addEventListener('keydown',e=>{if(e.metaKey||e.ctrlKey||e.altKey)return;if(key(e)){e.preventDefault();e.stopPropagation()}},true);
// buttons never keep focus (Space would click them on keyup)
document.addEventListener('mousedown',e=>{if(e.target.closest&&e.target.closest('button'))e.preventDefault()},true);
document.addEventListener('keyup',e=>{if(e.code==='Space')e.preventDefault()},true);
// from the shell: keys pressed while it has focus, pause on leaving, fullscreen ended by the window (green button)
addEventListener('message',e=>{const d=e.data;if(!d)return;
  if(d.shenpian==='key')key({key:d.key,code:d.code});
  else if(d.shenpian==='pause')v.pause();
  else if(d.shenpian==='fsoff'&&FS)applyFs(false)});
// ---- 批注 (local_comments.py): one click turns it on for this video; each note keeps the media time (speed doesn't
// matter) and an optional 框选 box; ✓ = resolved. Saved in the app and, next to the original file, <stem>.comments.md.
let NOTES={on:false,comments:[],sidecar:{}}, noteT=null, wasPlaying=false, editing=0;
const fmtN=t=>{const k=Math.round((t||0)*10);return String(Math.floor(k/600)).padStart(2,'0')+':'+(k%600/10).toFixed(1).padStart(4,'0')};
// 框选: drag a rectangle on the picture (same as the episode pages' box notes in chat.py)
window.BOX=null;const BOX=window.BOX=(function(){let pend=null,ov=null,hideT=0,shown=null;const pv=$('pv');
  function frame(){const P=pv.getBoundingClientRect(),vw=v.videoWidth||16,vh=v.videoHeight||9,k=Math.min(P.width/vw,P.height/vh),w=vw*k,h=vh*k;
    return {x:(P.width-w)/2,y:(P.height-h)/2,w,h}}
  function el(){let e=pv.querySelector(':scope>.bx');if(!e){e=document.createElement('div');e.className='bx';pv.appendChild(e)}return e}
  function draw(b){shown=b;const f=frame(),e=el();Object.assign(e.style,{left:f.x+b[0]*f.w+'px',top:f.y+b[1]*f.h+'px',width:b[2]*f.w+'px',height:b[3]*f.h+'px',display:'block'})}
  function hide(){shown=null;const e=pv.querySelector('.bx');if(e)e.style.display='none'}
  function mark(){$('bBox').classList.toggle('on',!!pend);$('bBox').textContent=pend?'已框选 ✕':'框选'}
  function stop(b){if(ov){ov.remove();ov=null}document.removeEventListener('keydown',esc,true);
    if(b&&b[2]>0.01&&b[3]>0.01){pend=b.map(x=>Math.round(x*10000)/10000);draw(pend);$('rin').focus();toast('框好了 · 写批注')}else{pend=null;hide()}mark()}
  const esc=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();stop(null)}};
  function start(){if(!v.videoWidth){toast('没有画面可以框');return}grab();hide();const f=frame();ov=document.createElement('div');ov.className='bxdraw';
    Object.assign(ov.style,{left:f.x+'px',top:f.y+'px',width:f.w+'px',height:f.h+'px'});pv.appendChild(ov);toast('在画面上拖一个框');
    let p0=null;const at=e=>{const r=ov.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]};
    const rect=(a,b)=>[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.abs(a[0]-b[0]),Math.abs(a[1]-b[1])];
    document.addEventListener('keydown',esc,true);['click','dblclick','mousedown'].forEach(n=>ov.addEventListener(n,e=>e.stopPropagation()));
    ov.addEventListener('pointerdown',e=>{e.preventDefault();e.stopPropagation();p0=at(e);ov.setPointerCapture(e.pointerId)});
    ov.addEventListener('pointermove',e=>{if(p0)draw(rect(p0,at(e)))});
    ov.addEventListener('pointerup',e=>{if(p0)stop(rect(p0,at(e)))})}
  $('bBox').onclick=e=>{e.stopPropagation();if(pend){pend=null;hide();mark()}else start()};
  v.addEventListener('play',()=>{if(!pend)hide()});
  return {take:()=>pend,drawing:()=>!!ov,clear(){pend=null;hide();mark()},
    show(b){const go=()=>{draw(b);clearTimeout(hideT);hideT=setTimeout(()=>{if(!pend&&v.paused===false)hide()},6000)};v.videoWidth?go():v.addEventListener('loadedmetadata',go,{once:true})},
    redraw(){const b=pend||shown;if(b)draw(b)}}})();
addEventListener('resize',()=>BOX.redraw());
// the moment a note is about: when he starts it (first key / 框选), the video pauses there; saving resumes it
function grab(){if(noteT!=null)return;noteT=v.currentTime||0;wasPlaying=!v.paused;v.pause();$('rat').innerHTML='记在 <b>'+fmtN(noteT)+'</b>'}
function release(resume){noteT=null;$('rat').textContent='';if(resume&&wasPlaying)v.play().catch(()=>{});wasPlaying=false}
$('rin').addEventListener('input',()=>{if($('rin').value.trim())grab()});
$('rin').addEventListener('keydown',e=>{e.stopPropagation();
  if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault();saveNote()}
  else if(e.key==='Escape'){e.preventDefault();$('rin').blur();if(!$('rin').value.trim()){BOX.clear();release(true)}}});
$('rform').onsubmit=e=>{e.preventDefault();saveNote()};
async function saveNote(){const text=$('rin').value.trim();if(!text){toast('先写点什么');return}
  const t=noteT!=null?noteT:v.currentTime||0;const j=await noteOp('add',{t,text,box:BOX.take(),dur:v.duration||null});
  if(!j)return;$('rin').value='';BOX.clear();release(true)}
async function noteOp(op,b){let j=null;
  try{const r=await fetch('/api/local/comments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({name:NAME,op},b))});j=await r.json()}catch(e){}
  if(!j||!j.ok){toast((j&&j.error)||'没存上，再试一次');return null}
  NOTES=j;renderNotes();return j}
async function loadNotes(){if(editing)return;try{const r=await fetch('/api/local/comments?name='+enc(NAME));if(r.ok)NOTES=await r.json()}catch(e){return}renderNotes()}
function setNotes(on){document.documentElement.classList.toggle('notes',on);if(!!NOTES.on!==on){NOTES.on=on;noteOp('toggle',{on})}renderNotes();
  setTimeout(()=>{BOX.redraw();tick()},50)}
$('bNotes').onclick=e=>{e.stopPropagation();setNotes(!NOTES.on)};
function renderNotes(){const on=!!NOTES.on,cs=NOTES.comments||[],open=cs.filter(c=>!c.resolved),done=cs.filter(c=>c.resolved);
  document.documentElement.classList.toggle('notes',on);$('bNotes').classList.toggle('on',on);
  $('bNotes').innerHTML='批注'+(open.length?`<i>${open.length}</i>`:'');
  $('rn').textContent=cs.length?`${open.length} 条待处理`+(done.length?` · ${done.length} 条已解决`:''):'';
  const sc=NOTES.sidecar||{};$('rsc').classList.toggle('warn',!sc.ok);
  $('rsc').textContent=sc.ok?'同步写在原文件旁边：'+sc.md.split('/').pop()+(sc.guessed?'（原文件是按名字和大小找到的）':''):(sc.why||'');$('rsc').title=sc.md||sc.orig||'';
  const item=c=>`<div class="cm${c.resolved?' done':''}" data-id="${c.id}"><div class="ch"><button class="res" data-a="res" title="${c.resolved?'改回待处理':'标为已解决'}">✓</button>`
    +`<span class="ct" data-a="go" title="跳到这里">${fmtN(c.t)}</span>${c.box?'<span title="有框选">▭</span>':''}<span class="sp"></span>`
    +`<button data-a="edit">编辑</button><button class="del" data-a="del">删除</button></div><div class="cx">${esc(c.text)}</div></div>`;
  $('rlist').innerHTML=cs.length?open.map(item).join('')+(done.length?`<div class="rsec">已解决 ${done.length}</div>`+done.map(item).join(''):'')
    :'<div class="rempty">还没有批注。<br>看到要改的地方，直接在下面写，<br>会自动记下时间；要指画面就先点「框选」。</div>';
  const d=v.duration||0,bar=$('bar');bar.querySelectorAll('.cmk').forEach(x=>x.remove());
  if(d)open.forEach(c=>{const m=document.createElement('i');m.className='cmk';m.style.left=(c.t/d*100)+'%';m.title=fmtN(c.t)+' '+c.text;
    m.addEventListener('pointerdown',e=>{e.stopPropagation();e.preventDefault();goNote(c)});bar.appendChild(m)})}
v.addEventListener('loadedmetadata',()=>renderNotes());
function goNote(c){v.pause();v.currentTime=c.t;if(c.box)BOX.show(c.box);
  document.querySelectorAll('.cm').forEach(x=>x.classList.toggle('on',+x.dataset.id===c.id));poke()}
$('rlist').addEventListener('click',async e=>{const a=e.target.closest('[data-a]'),row=e.target.closest('.cm');if(!a||!row)return;
  const c=(NOTES.comments||[]).find(x=>x.id===+row.dataset.id);if(!c)return;
  if(a.dataset.a==='go')goNote(c);
  else if(a.dataset.a==='res')noteOp('resolve',{id:c.id,resolved:!c.resolved});
  else if(a.dataset.a==='del'){if(confirm('删除这条批注？\n'+c.text.slice(0,80)))noteOp('delete',{id:c.id})}
  else if(a.dataset.a==='edit'){const cx=row.querySelector('.cx');if(row.querySelector('textarea'))return;editing++;
    const ta=document.createElement('textarea');ta.value=c.text;cx.style.display='none';cx.after(ta);ta.focus();
    const close=()=>{ta.remove();cx.style.display='';editing=Math.max(0,editing-1)};
    ta.addEventListener('keydown',async ev=>{ev.stopPropagation();
      if(ev.key==='Enter'&&!ev.shiftKey&&!ev.isComposing&&ev.keyCode!==229){ev.preventDefault();const t=ta.value.trim();if(!t)return;close();if(t!==c.text)await noteOp('edit',{id:c.id,text:t})}
      else if(ev.key==='Escape'){ev.preventDefault();close()}});
    ta.addEventListener('blur',()=>setTimeout(()=>{if(ta.isConnected)close()},150))}});
$('rlist').addEventListener('dblclick',e=>{const row=e.target.closest('.cm');if(row&&e.target.classList.contains('cx')){const b=row.querySelector('[data-a=edit]');if(b)b.click()}});
// 复制全部批注: the same md as the sidecar, without image links (for a session that can't see this Mac)
async function copyText(t){try{await navigator.clipboard.writeText(t);return true}catch(e){}
  const ta=document.createElement('textarea');ta.value=t;ta.style.cssText='position:fixed;left:-9999px';document.body.appendChild(ta);ta.select();
  let ok=false;try{ok=document.execCommand('copy')}catch(e){}ta.remove();return ok}
$('bCopy').onclick=async e=>{e.stopPropagation();let md='';try{md=await (await fetch('/api/local/comments.md?name='+enc(NAME))).text()}catch(x){}
  if(!md){toast('没取到批注');return}const n=(NOTES.comments||[]).length;toast(await copyText(md)?`已复制 ${n} 条批注（Markdown）`:'没复制成功')};
// ticks an agent made in the md come back while the rail is open
setInterval(()=>{if(NOTES.on&&!document.hidden&&noteT==null)loadNotes()},10000);
loadNotes();
init();
</script></body></html>
"""
PAGE = PAGE.replace("__THEME_CSS__", THEME.CSS)
