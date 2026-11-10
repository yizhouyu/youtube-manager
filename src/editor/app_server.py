"""Backend of the 「审片」 Mac app (app/): the shell page (episode sidebar + tabs) and the servers behind it.

    ./venv/bin/python -m src.editor.app_server [--port 0] [--port-file F] [--parent-pid N]

The Swift app (app/Shenpian.swift) starts this, shows `/` in a WKWebView and stops it on quit. It:
  * lists every `~/Desktop/<number> - <name>` with `02 - Export/edit/`, newest first, with one status chip
    (已上传 > 已通过 > 有问题没答 > 待审片), read from files only;
  * opening an episode starts its footage_player (+ review_server when there is an edl.json) as child processes
    on free ports (9100-9399; the last ports per project are reused so the pages' remembered settings stay),
    logs in ~/Library/Logs/审片/; the previous episode's servers (only ones started here) are stopped;
  * tabs 封面 / 素材 / 成片 / Shorts / 标题 are iframes: the cover html and feed_sim html are served from the
    project's thumbnail/ folder (/f/<token>/...), Shorts = footage_player's /shorts page;
  * 「选这个」 / 「审片通过」 (Q9) append one line to sessions/APPROVALS.md, log {type, choice, at} in
    `edit/app_picks.json`, and for covers write thumbnail/CHOSEN like the agent does. A second click undoes
    (a 撤销 line is appended; lines are never deleted). Nothing here uploads or calls an agent.
Folders opened with 「打开其他文件夹…」 (or anywhere outside the episodes root) are read-only: their servers run
with --read-only and every pick is refused.

Env (tests): SHENPIAN_ROOT (episodes root, default ~/Desktop), SHENPIAN_APPROVALS (APPROVALS.md),
SHENPIAN_STATE (ports memory), SHENPIAN_LOGS, SHENPIAN_PORTS ("9100-9399").
"""
import argparse
import atexit
import fcntl
import glob
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import edl as E
from . import questions as QS
from . import theme as THEME
from .shorts_page import list_shorts

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOME = os.path.expanduser("~")
EP_RX = re.compile(r"^(\d+) - .+")


def root():
    return os.path.realpath(os.environ.get("SHENPIAN_ROOT") or os.path.join(HOME, "Desktop"))


def approvals_path():
    return os.environ.get("SHENPIAN_APPROVALS") or os.path.join(HOME, "Desktop", "youtube-manager", "sessions", "APPROVALS.md")


def state_path():
    return os.environ.get("SHENPIAN_STATE") or os.path.join(HOME, "Library", "Application Support", "审片", "ports.json")


def logs_dir():
    d = os.environ.get("SHENPIAN_LOGS") or os.path.join(HOME, "Library", "Logs", "审片")
    os.makedirs(d, exist_ok=True)
    return d


def port_range():
    a, b = (os.environ.get("SHENPIAN_PORTS") or "9100-9399").split("-")
    return range(int(a), int(b) + 1)


# ---------------------------------------------------------------- project files (read only)

def export_dir(proj):
    return os.path.join(proj, "02 - Export")


def edit_dir(proj):
    return os.path.join(export_dir(proj), "edit")


def thumb_dir(proj):
    return os.path.join(export_dir(proj), "thumbnail")


def label(proj):
    """'124' for an episode folder, else the folder name (APPROVALS lines)."""
    name = os.path.basename(os.path.normpath(proj))
    m = EP_RX.match(name)
    return m[1] if m else name


def writable(proj):
    """Only episode folders right under the episodes root may be written; anything else is read-only."""
    p = os.path.realpath(proj)
    return os.path.dirname(p) == root() and bool(EP_RX.match(os.path.basename(p))) and os.path.isdir(edit_dir(p))


def episodes():
    try:
        names = os.listdir(root())
    except OSError:
        return []
    rows = []
    for n in names:
        m = EP_RX.match(n)
        p = os.path.join(root(), n)
        if m and os.path.isdir(edit_dir(p)):
            rows.append((int(m[1]), n, p))
    return [{"path": p, "name": n, "num": k} for k, n, p in sorted(rows, key=lambda r: (-r[0], r[1]))]


def has_preview(proj):
    return os.path.isfile(os.path.join(edit_dir(proj), "preview.mp4")) or bool(
        glob.glob(os.path.join(edit_dir(proj), "previews", "preview-*.mp4")))


def uploaded(proj):
    try:
        with open(os.path.join(edit_dir(proj), "publish_prep", "youtube_ids.json"), encoding="utf-8") as f:
            return bool(json.load(f).get("long"))
    except (OSError, ValueError, AttributeError):
        return False


def status(proj):
    """(key, chip text): 已上传 > 已通过 > 有问题没答 > 待审片 > nothing."""
    if uploaded(proj):
        return "up", "已上传"
    if current(proj).get("approve"):
        return "ok", "已通过"
    if any(not q.get("answer") for q in QS.load(proj)):
        return "q", "有问题没答"
    if has_preview(proj):
        return "review", "待审片"
    return "", ""


def cover_page(proj):
    for f in ("editorial.html", "review.html"):   # same order as scripts/review_open.sh
        if os.path.isfile(os.path.join(thumb_dir(proj), f)):
            return f
    return None


def _vnum(path):
    m = re.search(r"/v(\d+)/", path)
    return int(m[1]) if m else 0


def feed_sim(proj):
    """Newest feed simulation under thumbnail/ (feed_sim.html or v*/feed_sim_v*.html), relative path."""
    fs = glob.glob(os.path.join(thumb_dir(proj), "feed_sim*.html")) + glob.glob(os.path.join(thumb_dir(proj), "*", "feed_sim*.html"))
    if not fs:
        return None
    return os.path.relpath(max(fs, key=os.path.getmtime), thumb_dir(proj))


def covers(proj):
    """Candidates of the newest thumbnail/v<N>/covers.json: [{id, title, tag, img, v}]."""
    js = sorted(glob.glob(os.path.join(thumb_dir(proj), "v*", "covers.json")), key=_vnum)
    if not js:
        return []
    v = _vnum(js[-1])
    try:
        with open(js[-1], encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out, seen = [], set()
    for key in ("new", "covers", "kept", "old", "older"):
        for c in data.get(key) or []:
            cid = isinstance(c, dict) and c.get("id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            img = next((r for r in (f"v{v}/{cid}_360.jpg", f"v{v}/{cid}_youtube.jpg", f"v{v}/{cid}.jpg",
                                    f"{cid}_youtube.jpg", f"{cid}.jpg") if os.path.isfile(os.path.join(thumb_dir(proj), r))), None)
            out.append({"id": cid, "title": re.sub(r"<[^>]+>", "", c.get("title") or cid), "tag": c.get("tag") or "",
                        "img": img, "v": v})
    return out


def titles(proj):
    """Title candidates: publish_prep/metadata_final.txt [YouTube title — ...] sections, else the
    '## Title candidates' bullets of publish_prep/draft_metadata.md. [{id, text}]"""
    pp = os.path.join(edit_dir(proj), "publish_prep")
    try:
        with open(os.path.join(pp, "metadata_final.txt"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        out = []
        for i, ln in enumerate(lines):
            m = re.match(r"\[YouTube title\s*[—-]\s*([^\]\(]+)", ln)
            if m:
                text = next((x.strip() for x in lines[i + 1:] if x.strip()), "")
                if text and not text.startswith("["):
                    out.append({"id": m[1].strip(), "text": text})
        if out:
            return out
    except OSError:
        pass
    try:
        with open(os.path.join(pp, "draft_metadata.md"), encoding="utf-8") as f:
            md = f.read()
    except OSError:
        return []
    m = re.search(r"^#+\s*Title candidates\s*$(.*?)(?=^#|\Z)", md, re.M | re.S | re.I)
    out = []
    for ln in (m[1] if m else "").splitlines():
        b = re.match(r"^\s*[-*]\s*([^:：(（]+?)\s*(?:[(（][^)）]*[)）])?\s*[:：]\s*(.+)$", ln)
        if b:
            out.append({"id": b[1].strip(), "text": b[2].strip()})
    return out


# ---------------------------------------------------------------- picks (Q9)

PICK_TYPES = ("cover", "title", "short", "approve")
_pick_lock = threading.Lock()


def picks_path(proj):
    return os.path.join(edit_dir(proj), "app_picks.json")


def load_picks(proj):
    try:
        with open(picks_path(proj), encoding="utf-8") as f:
            ev = json.load(f)
        return ev if isinstance(ev, list) else []
    except (OSError, ValueError):
        return []


def current(proj, events=None):
    """{cover: id, title: id, approve: '审片通过', short: [names]} from the pick log. cover/title/approve keep a
    stack, so undoing the newest pick brings back the one before it; Shorts are a set."""
    stacks, shorts = {}, []
    for e in load_picks(proj) if events is None else events:
        t, c = e.get("type"), e.get("choice")
        if t == "short":
            if c in shorts:
                shorts.remove(c)
            if not e.get("undo"):
                shorts.append(c)
        elif t in PICK_TYPES:
            st = stacks.setdefault(t, [])
            if c in st:
                st.remove(c)
            if not e.get("undo"):
                st.append(c)
    out = {t: st[-1] for t, st in stacks.items() if st}
    if shorts:
        out["short"] = shorts
    return out


def _approval_line(proj, typ, choice, undo, day, extra=""):
    ep = label(proj)
    if typ == "approve":
        what = f"{ep} 审片通过"
    else:
        what = f"{ep} {typ}: {choice}{extra}"
    if undo:
        return f"- {day} · {what} 撤销 — app 点选「{'已通过' if typ == 'approve' else '已选'} · 撤销」"
    return f"- {day} · {what} — app 点选「{'审片通过' if typ == 'approve' else '选这个'}」"


def _append(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        body = f.read()
        f.seek(0, os.SEEK_END)
        f.write(("\n" if body and not body.endswith("\n") else "") + line + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def pick(proj, typ, choice, undo=False, now=None):
    """Record one click. Returns the new current() state. Raises ValueError on a bad request / read-only folder."""
    if typ not in PICK_TYPES or not isinstance(choice, str) or not choice.strip() or len(choice) > 300:
        raise ValueError("bad pick")
    if not writable(proj):
        raise ValueError("read-only")
    choice = choice.strip()
    now = now or time.localtime()
    day, at = time.strftime("%Y-%m-%d", now), time.strftime("%Y-%m-%d %H:%M:%S", now)
    with _pick_lock:
        ev = load_picks(proj)
        cur = current(proj, ev)
        active = choice in cur.get("short", []) if typ == "short" else cur.get(typ) == choice
        if undo != active:   # double click / stale page: nothing to do
            return cur
        e = {"type": typ, "choice": choice, "at": at}
        if undo:
            e["undo"] = True
        extra = ""
        if typ == "cover":
            cv = next((c for c in covers(proj) if c["id"] == choice), None)
            extra = f" (v{cv['v']})" if cv else ""
            cpath = os.path.join(thumb_dir(proj), "CHOSEN")
            if undo:   # put back what CHOSEN said before this pick
                before = next((x.get("chosen_before") for x in reversed(ev)
                               if x.get("type") == "cover" and x.get("choice") == choice and not x.get("undo")), None)
                if before is None:
                    if os.path.exists(cpath):
                        os.remove(cpath)
                else:
                    _write(cpath, before)
            else:
                try:
                    with open(cpath, encoding="utf-8") as f:
                        e["chosen_before"] = f.read()
                except OSError:
                    e["chosen_before"] = None
                _write(cpath, f"{choice}{extra} — {day} creator: app 点选\n")
        ev.append(e)
        _write(picks_path(proj), json.dumps(ev, ensure_ascii=False, indent=1))
        _append(approvals_path(), _approval_line(proj, typ, choice, undo, day, extra))
        return current(proj, ev)


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- child servers

def port_free(p):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", p))
            return True
        except OSError:
            return False


def _load_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def pick_port(proj, kind, taken=()):
    """The port this project/kind had last time if it is free, else the first free one in the range."""
    st = _load_state()
    key = f"{os.path.realpath(proj)}|{kind}"
    rng = port_range()
    want = st.get(key)
    if not (isinstance(want, int) and want in rng and want not in taken and port_free(want)):
        others = set(v for k, v in st.items() if k != key)
        want = next((p for p in rng if p not in taken and p not in others and port_free(p)), None) or \
            next((p for p in rng if p not in taken and port_free(p)), None)
        if want is None:
            raise RuntimeError("没有空闲端口")
    st[key] = want
    try:
        os.makedirs(os.path.dirname(state_path()), exist_ok=True)
        _write(state_path(), json.dumps(st, ensure_ascii=False, indent=1))
    except OSError:
        pass
    return want


def _up(port, path="/"):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


class Servers:
    """The episode currently open: its footage_player (+ review_server). Only processes started here are stopped."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proj, self.procs = None, {}   # kind -> (Popen, port)

    def alive(self):
        return bool(self.procs) and all(p.poll() is None for p, _ in self.procs.values())

    def open(self, proj, ro):
        with self.lock:
            if self.proj == proj and self.alive():
                return {k: port for k, (_, port) in self.procs.items()}, None
            self.stop()
            self.proj = proj
            plan = [("raw", "footage_player")]
            if os.path.isfile(os.path.join(edit_dir(proj), "edl.json")):
                plan.append(("cut", "review_server"))
            taken = []
            for kind, mod in plan:
                port = pick_port(proj, kind, taken)
                taken.append(port)
                log = os.path.join(logs_dir(), f"{os.path.basename(os.path.normpath(proj))}-{kind}.log")
                with open(log, "a", encoding="utf-8") as lf:
                    lf.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} start {mod} :{port}{' (read-only)' if ro else ''}\n")
                    lf.flush()
                    args = [sys.executable, "-m", f"src.editor.{mod}", proj, "--port", str(port)] + (["--read-only"] if ro else [])
                    p = subprocess.Popen(args, cwd=REPO, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                self.procs[kind] = (p, port)
            err = None
            deadline = time.time() + 90
            for kind, (p, port) in self.procs.items():
                while time.time() < deadline and p.poll() is None and not _up(port):
                    time.sleep(0.3)
                if not _up(port):
                    err = f"{'素材' if kind == 'raw' else '成片'}页没有启动起来（日志：~/Library/Logs/审片/）"
            return {k: port for k, (_, port) in self.procs.items()}, err

    def stop(self):
        for p, _ in self.procs.values():
            if p.poll() is None:
                p.terminate()
        for p, _ in self.procs.values():
            try:
                p.wait(timeout=4)
            except subprocess.TimeoutExpired:
                p.kill()
        self.proj, self.procs = None, {}


SERVERS = Servers()


# ---------------------------------------------------------------- app

app = Flask(__name__)
TOKENS = {}   # token -> project path (static routes for cover / feed_sim html)


def token(proj):
    t = hashlib.sha1(os.path.realpath(proj).encode()).hexdigest()[:12]
    TOKENS[t] = os.path.realpath(proj)
    return t


def episode_info(proj):
    st = status(proj)
    return {"path": proj, "name": os.path.basename(os.path.normpath(proj)), "label": label(proj),
            "chip": st[0], "chip_text": st[1], "ro": not writable(proj)}


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.get("/api/episodes")
def api_episodes():
    return jsonify([dict(episode_info(e["path"]), num=e["num"]) for e in episodes()])


def _proj_arg():
    p = (request.get_json(silent=True) or {}).get("path") if request.method == "POST" else request.args.get("path")
    if not isinstance(p, str) or not os.path.isdir(p):
        abort(400)
    return os.path.realpath(p)


@app.post("/api/open")
def api_open():
    proj = _proj_arg()
    ro = not writable(proj)
    try:
        ports, err = SERVERS.open(proj, ro)
    except Exception as e:   # no free port, python missing, ...
        ports, err = {}, str(e)[:200]
    tok = token(proj)
    has_edl = os.path.isfile(os.path.join(edit_dir(proj), "edl.json"))
    cv, fs = cover_page(proj), feed_sim(proj)
    shorts = list_shorts(proj)
    raw, cut = ports.get("raw"), ports.get("cut")
    tabs = {
        "cover": f"/f/{tok}/{cv}" if cv else None,
        "raw": f"http://127.0.0.1:{raw}/" if raw else None,
        "cut": f"http://127.0.0.1:{cut}/" if cut else None,
        "shorts": f"http://127.0.0.1:{raw}/shorts" if raw and shorts else None,
        "titles": f"/f/{tok}/{fs}" if fs else None,
    }
    notes = []
    if not has_edl:
        notes.append("这一期还没有剪辑方案（edl.json），成片页打不开；能看的页面都在上面。")
    if err:
        notes.append(err)
    return jsonify(dict(episode_info(proj), tabs=tabs, notes=notes, token=tok,
                        covers=[dict(c, img=f"/f/{tok}/{c['img']}" if c["img"] else None) for c in covers(proj)],
                        titles=titles(proj), shorts=[s["name"] for s in shorts], picks=current(proj)))


@app.post("/api/pick")
def api_pick():
    body = request.get_json(silent=True) or {}
    proj = _proj_arg()
    try:
        cur = pick(proj, body.get("type"), body.get("choice"), bool(body.get("undo")))
    except ValueError as e:
        return jsonify({"ok": False, "error": "只读文件夹，不能选" if str(e) == "read-only" else "无效的选择"}), 400
    return jsonify({"ok": True, "picks": cur, "chip": status(proj)})


@app.get("/f/<tok>/<path:rel>")
def static_thumb(tok, rel):
    proj = TOKENS.get(tok)
    if not proj:
        abort(404)
    return send_from_directory(thumb_dir(proj), rel, max_age=0)


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>审片</title>
<style>
__THEME_CSS__
html,body{height:100%;overflow:hidden}
body{background:var(--bg)}
html.native body{background:transparent}   /* the Swift window puts the native sidebar vibrancy behind the page */
.app{display:grid;grid-template-columns:var(--side-w) minmax(0,1fr);height:100vh}
/* ---- sidebar: episodes (option B: grey rows, selection = --sel-bg, chips = soft pills with a dot) */
.side{background:var(--bg-side);border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0;font-size:var(--fs)}
html.native .side{background:transparent}
.side .lights{height:var(--hdr);flex:none}   /* the window's traffic lights sit here */
#eps{flex:1;overflow-y:auto;padding:0 var(--sp-2)}
.sec{font-size:var(--fs-xs);font-weight:500;color:var(--text-3);padding:var(--sp-3) var(--sp-3) var(--sp-1)}
.ep{display:flex;align-items:center;gap:var(--sp-2);height:34px;padding:0 var(--sp-3);border-radius:var(--r-sm);cursor:default;
  transition:background var(--dur-1) var(--ease)}
.ep:hover{background:rgba(0,0,0,.04)}
.ep.on{background:var(--sel-bg);color:var(--sel-ink)}
.ep b{font:500 var(--fs) var(--font-num);font-variant-numeric:tabular-nums;color:var(--text-3);min-width:26px;flex:none}
.ep .nm{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chip{flex:none;display:inline-flex;align-items:center;gap:5px;font-size:var(--fs-xs);line-height:20px;padding:0 8px;border-radius:999px;font-weight:500}
.chip::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor}
.chip.review{color:var(--st-review);background:var(--st-review-bg)}
.chip.q{color:var(--st-open);background:var(--st-open-bg)}
.chip.ok{color:var(--st-pass);background:var(--st-pass-bg)}
.chip.up{color:var(--st-up);background:var(--st-up-bg);padding:0;font-weight:400}
.chip.up::before,.chip.ro::before{display:none}
.chip.ro{color:var(--q-ink);background:var(--q-soft)}
#other{margin:var(--sp-2) var(--sp-3) var(--sp-3);justify-content:flex-start;font-size:var(--fs);color:var(--text-2)}
/* ---- toolbar: episode | centred segmented tabs | 审片通过 */
.mainc{display:flex;flex-direction:column;min-width:0;min-height:0;background:var(--bg)}
.top{height:var(--hdr);display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:var(--sp-3);padding:0 var(--sp-5);
  background:var(--bg-bar);flex:none}
#ttl{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:var(--fs-lg)}
#ttl i{font-style:normal;color:var(--text-3);font-variant-numeric:tabular-nums;margin-right:8px;font-weight:400}
#ttl b{font-weight:600}
#tabs{display:flex;gap:2px;padding:3px;border-radius:var(--r-sm);background:var(--surface-3)}
#tabs:empty{display:none}
#tabs button{border:0;background:transparent;color:var(--text-2);height:26px;padding:0 14px;border-radius:5px;font-size:var(--fs);
  transition:background var(--dur-1) var(--ease)}
#tabs button:hover{color:var(--text)}
#tabs button.on{background:var(--surface);color:var(--text);font-weight:500;box-shadow:var(--sh-1)}
.top .right{display:flex;justify-content:flex-end;gap:var(--sp-2)}
#approve{border-radius:999px;padding:0 16px;height:30px;background:var(--btn-pri-bg);border-color:var(--btn-pri-bg);color:var(--btn-pri-ink);font-weight:500}
#approve:hover{background:var(--accent-hover)}
#approve.on{background:var(--st-pass-bg);border-color:transparent;color:var(--st-pass)}
#note{display:none;margin:0 var(--sp-5) var(--sp-2);padding:var(--sp-2) var(--sp-3);border-radius:var(--r-sm);background:var(--q-soft);color:var(--q-ink);font-size:var(--fs)}
/* ---- views */
.views{flex:1;min-height:0;position:relative}
.view{position:absolute;inset:0;display:none;flex-direction:column}
.view.on{display:flex}
.view iframe{flex:1;border:0;width:100%;min-height:0;background:var(--bg)}
.empty{margin:auto;color:var(--text-3);font-size:var(--fs-md);text-align:center;line-height:2}
/* 选这个 strip under the cover / title / Shorts page: a sheet, rows without boxes */
.strip{flex:none;display:flex;gap:var(--sp-2);overflow-x:auto;padding:var(--sp-3) var(--sp-5);background:var(--bg-rail);border-top:1px solid var(--line)}
.strip:empty{display:none}
.cand{flex:none;display:flex;gap:var(--sp-3);align-items:center;padding:var(--sp-2);border-radius:var(--r);background:var(--surface-2);max-width:440px}
.cand.on{background:var(--st-pass-bg)}
.cand img{width:96px;aspect-ratio:16/9;object-fit:cover;border-radius:var(--r-xs);background:var(--surface-3)}
.cand .tx{display:flex;flex-direction:column;min-width:0;font-size:var(--fs-sm);color:var(--text-3)}
.cand .tx b{font-size:var(--fs);color:var(--text);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:260px}
.cand button{flex:none;height:28px;font-size:var(--fs-sm);border-radius:999px;background:var(--btn-sec-bg);border-color:var(--btn-sec-line);color:var(--btn-sec-ink)}
.cand.on button{color:var(--st-pass);border-color:transparent;background:transparent}
body.ro .cand button,body.ro #approve{display:none}
</style></head><body>
<div class="app">
<aside class="side"><div class="lights"></div><div id="eps" class="scroll"></div>
  <button id="other" class="ghost" title="比如外接硬盘上的旧项目（只读）">打开其他文件夹…</button></aside>
<section class="mainc">
  <header class="top"><span id="ttl"></span><nav id="tabs"></nav>
    <span class="right"><button id="approve" hidden title="这一期审片通过（只记下来，不会上传）">审片通过</button></span></header>
  <div id="note"></div>
  <div class="views" id="views"><div class="view on" id="v-none"><div class="empty">左边点一期开始审片</div></div></div>
</section></div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const TABS=[['cover','封面'],['raw','素材'],['cut','成片'],['shorts','Shorts'],['titles','标题']];
let EP=null, cur=null, others=[];
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(r=>r.json());
function chip(e){return e.ro?'<span class="chip ro">只读</span>':(e.chip?`<span class="chip ${e.chip}">${esc(e.chip_text)}</span>`:'')}
function row(e){const n=/^\d+$/.test(e.label)?e.label:'';
  return `<div class="ep${EP&&EP.path===e.path?' on':''}" data-p="${esc(e.path)}" title="${esc(e.path)}"><b>${esc(n)}</b><span class="nm">${esc(n?e.name.replace(/^\d+ - /,''):e.name)}</span>${chip(e)}</div>`}
async function list(){const eps=await (await fetch('/api/episodes')).json();
  const g=(t,a)=>a.length?`<div class="sec">${t}</div>`+a.map(row).join(''):'';
  $('eps').innerHTML=g('进行中',eps.filter(e=>e.chip!=='up'))+g('已完成',eps.filter(e=>e.chip==='up'))+g('其他文件夹',others);
  $('eps').querySelectorAll('.ep').forEach(el=>el.onclick=()=>openEp(el.dataset.p))}
async function openEp(p){
  $('ttl').innerHTML='<i>启动中…</i>';document.querySelectorAll('.ep').forEach(e=>e.classList.toggle('on',e.dataset.p===p));
  const j=await post('/api/open',{path:p});EP=j;cur=null;
  if(j.ro&&!others.some(o=>o.path===j.path)&&!document.querySelector('.ep[data-p="'+CSS.escape(j.path)+'"]'))others.push(j);
  document.title='审片 · '+j.name;const num=/^\d+$/.test(j.label)?j.label:'';
  $('ttl').innerHTML=(num?`<i>${esc(num)}</i>`:'')+`<b>${esc(num?j.name.replace(/^\d+ - /,''):j.name)}</b>`;document.body.classList.toggle('ro',!!j.ro);
  $('note').textContent=(j.notes||[]).join(' ');$('note').style.display=j.notes&&j.notes.length?'block':'none';
  const has={cover:j.tabs.cover||j.covers.length,raw:j.tabs.raw,cut:j.tabs.cut,shorts:j.tabs.shorts,titles:j.tabs.titles||j.titles.length};
  $('tabs').innerHTML=TABS.map(([k,n],i)=>has[k]?`<button data-k="${k}" title="⌘${i+1}">${n}</button>`:'').join('');
  $('tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>tab(b.dataset.k));
  $('views').innerHTML=TABS.map(([k])=>has[k]?`<div class="view" id="v-${k}">${j.tabs[k]?`<iframe data-src="${esc(j.tabs[k])}" allow="fullscreen; autoplay"></iframe>`:'<div class="empty">这一期还没有这个页面，下面可以直接选</div>'}<div class="strip" id="s-${k}"></div></div>`:'').join('')
    +'<div class="view" id="v-none"><div class="empty">这一期没有能打开的页面</div></div>';
  strips();list();
  const first=['raw','cut','cover','shorts','titles'].find(k=>has[k]);tab(first||'none')}
function tab(k){if(!EP)return;const v=$('v-'+k);if(!v)return;
  if(cur&&cur!==k){const f=document.querySelector('#v-'+cur+' iframe');if(f&&f.contentWindow)f.contentWindow.postMessage({shenpian:'pause'},'*')}
  cur=k;document.querySelectorAll('.view').forEach(x=>x.classList.toggle('on',x===v));
  document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.k===k));
  const f=v.querySelector('iframe');if(f&&!f.src)f.src=f.dataset.src;if(f)setTimeout(()=>f.focus(),50)}
window.shell={tab:n=>{const t=TABS[n-1];if(t)tab(t[0])},openPath:p=>openEp(p)};
// 选这个 / 已选 · 撤销 (Q9): one APPROVALS.md line per click
function cand(type,id,html){const P=EP.picks||{},on=type==='short'?(P.short||[]).includes(id):P[type]===id;
  return `<div class="cand${on?' on':''}">${html}<button data-t="${type}" data-c="${esc(id)}" data-u="${on?1:''}">${on?'已选 · 撤销':'选这个'}</button></div>`}
function strips(){if(!EP)return;const s=(k,h)=>{const e=$('s-'+k);if(e)e.innerHTML=h};
  s('cover',EP.covers.map(c=>cand('cover',c.id,`${c.img?`<img src="${esc(c.img)}" alt="">`:''}<span class="tx"><b>${esc(c.title)}</b>${esc(c.id)}${c.tag?' · '+esc(c.tag):''}</span>`)).join(''));
  s('titles',EP.titles.map(t=>cand('title',t.text,`<span class="tx"><b title="${esc(t.text)}">${esc(t.text)}</b>${esc(t.id)}</span>`)).join(''));
  s('shorts',EP.shorts.map(n=>cand('short',n,`<span class="tx"><b>${esc(n)}</b>Short</span>`)).join(''));
  document.querySelectorAll('.strip button').forEach(b=>b.onclick=()=>doPick(b.dataset.t,b.dataset.c,!!b.dataset.u));
  const a=$('approve'),on=!!(EP.picks||{}).approve;a.hidden=false;a.classList.toggle('on',on);a.textContent=on?'已通过 · 撤销':'审片通过'}
async function doPick(type,choice,undo){const j=await post('/api/pick',{path:EP.path,type,choice,undo});
  if(j.ok){EP.picks=j.picks;strips();list()}else alert(j.error||'没记下来')}
$('approve').onclick=()=>doPick('approve','审片通过',!!(EP.picks||{}).approve);
$('other').onclick=()=>{if(window.webkit&&webkit.messageHandlers&&webkit.messageHandlers.shell)webkit.messageHandlers.shell.postMessage({cmd:'pickFolder'});
  else{const p=prompt('项目文件夹的路径');if(p)openEp(p)}};
// Q7: a page asks to jump to the other page at a moment
window.addEventListener('message',e=>{const d=e.data;if(!d||d.shenpian!=='jump'||!EP)return;
  if(!$('v-'+d.to))return;tab(d.to);const f=document.querySelector('#v-'+d.to+' iframe');
  const send=()=>f.contentWindow.postMessage({shenpian:'seek',clip:d.clip,t:d.t},'*');
  if(f.dataset.ready)send();else f.addEventListener('load',()=>{f.dataset.ready=1;setTimeout(send,1500)},{once:true})});
document.addEventListener('load',e=>{if(e.target.tagName==='IFRAME')e.target.dataset.ready=1},true);
// ⌘1–⌘5 also work here when the shell itself has focus (the Swift menu handles them everywhere else)
document.addEventListener('keydown',e=>{if(e.metaKey&&e.key>='1'&&e.key<='5'){e.preventDefault();shell.tab(+e.key)}});
list();setInterval(list,30000);
{const q=new URLSearchParams(location.search);if(q.get('open'))openEp(q.get('open')).then(()=>{if(q.get('tab'))tab(q.get('tab'))})}   // ?open=<path>&tab=cut
</script></body></html>
"""
PAGE = PAGE.replace("__THEME_CSS__", THEME.CSS)


def _shutdown(*_):
    SERVERS.stop()
    os._exit(0)


def main():
    ap = argparse.ArgumentParser(description="Backend of the 审片 Mac app")
    ap.add_argument("--port", type=int, default=0, help="0 = any free port")
    ap.add_argument("--port-file", help="write the chosen port here (the Swift app reads it)")
    ap.add_argument("--parent-pid", type=int, help="exit (and stop the episode servers) when this process is gone")
    a = ap.parse_args()
    atexit.register(SERVERS.stop)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGHUP, _shutdown)
    port = a.port
    if not port:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    if a.parent_pid:
        def watch():
            while True:
                try:
                    os.kill(a.parent_pid, 0)
                except OSError:
                    _shutdown()
                time.sleep(2)
        threading.Thread(target=watch, daemon=True).start()
    if a.port_file:
        _write(a.port_file, str(port))
    print(f"审片 app server: http://127.0.0.1:{port}/", flush=True)
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
