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

Agent control (scripts/shenpian, `shenpian://` URLs handled by the Swift app): open / switch tab / seek / status /
screenshot / quit only. `parse_agent_url` turns a URL into an open request; the shell page reports what it shows to
/api/app/state (GET = the status JSON); server.json next to the ports memory says where this server is. There is no
route here that picks, approves, saves or renders for an agent: those stay the creator's clicks.

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
import urllib.parse
import urllib.request

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import chat as CHAT
from . import checkpoint as CP
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
    return [{"path": p, "name": n, "num": k} for k, n, p in sorted(rows)]   # by number, each section (creator 11/10)


def has_preview(proj):
    return os.path.isfile(os.path.join(edit_dir(proj), "preview.mp4")) or bool(
        glob.glob(os.path.join(edit_dir(proj), "previews", "preview-*.mp4")))


def uploaded(proj):
    try:
        with open(os.path.join(edit_dir(proj), "publish_prep", "youtube_ids.json"), encoding="utf-8") as f:
            return bool(json.load(f).get("long"))
    except (OSError, ValueError, AttributeError):
        return False


# the rough-cut step a 粗剪中 chip names (checkpoint ids, see src/editor/checkpoint.py)
STEP_ZH = {"C0": "准备", "C1": "看素材", "C2": "查资料", "C3": "结构", "C4": "地图字卡", "C5": "初版剪辑",
           "C6": "配乐", "C7": "字幕", "C8": "问题", "C9": "渲染"}


def _preview_mtime(proj):
    fs = [os.path.join(edit_dir(proj), "preview.mp4")] + glob.glob(os.path.join(edit_dir(proj), "previews", "preview-*.mp4"))
    return max((os.path.getmtime(f) for f in fs if os.path.isfile(f)), default=0)


def _creator_notes(proj):
    """[(epoch, status)] of his review comments."""
    out = []
    for m in CHAT.load(proj):
        if m.get("role") == "creator" and CHAT.status(m) != CHAT.DELETED:
            try:
                out.append((time.mktime(time.strptime(m["ts"], "%Y-%m-%d %H:%M:%S")), CHAT.status(m)))
            except (KeyError, ValueError):
                pass
    return out


def status(proj):
    """(key, chip text), creator 2026-11-10 (Q4): 已上传 > 已通过 > 有问题没答 > 改片中 / 精剪待审 / 粗剪待审 (a preview
    exists; 粗剪 until he has left notes) > 粗剪中 · <step> > 待开剪 (just organized)."""
    if uploaded(proj):
        return "up", "已上传"
    if current(proj).get("approve"):
        return "ok", "已通过"
    if any(not q.get("answer") for q in QS.load(proj)):
        return "q", "有问题没答"
    if not current(proj).get("raw"):   # he reviews the footage first, then the cut (creator 11/11)
        return "review", "素材待审"
    pv = _preview_mtime(proj)
    if pv:
        sent = [t for t, st in _creator_notes(proj) if st == CHAT.SENT]   # pending = still reviewing this round
        if any(t > pv for t in sent):
            return "work", "改片中"
        return "review", "精剪待审" if sent else "粗剪待审"
    try:
        rows = CP.status(proj)
    except Exception:
        rows = []
    if any(r[2] for r in rows):
        last = max(i for i, r in enumerate(rows) if r[2])   # the furthest step reached (old projects skip markings)
        nx = next((r for r in rows[last:] if not r[2]), None)
        return "work", "粗剪中" + (f" · {STEP_ZH[nx[0]]}" if nx and nx[0] in STEP_ZH else "")
    return "todo", "待开剪"


TRIP_RX = re.compile(r"^\d{6}")   # a trip's raw dump on the Desktop, e.g. 202611China
VIDEO_EXT = (".mp4", ".mov")


def trips():
    """Desktop trip folders that still hold loose clips, i.e. not split into episodes yet (待整理). Top level only."""
    out = []
    try:
        names = sorted(os.listdir(root()))
    except OSError:
        return out
    for n in names:
        p = os.path.join(root(), n)
        if not TRIP_RX.match(n) or not os.path.isdir(p):
            continue
        try:
            k = sum(1 for f in os.listdir(p) if f.lower().endswith(VIDEO_EXT) and not f.startswith("._"))
        except OSError:
            continue
        if k:
            out.append({"path": p, "name": n, "clips": k})
    return out


def cover_page(proj):
    for f in ("editorial.html", "review.html"):   # same order as scripts/review_open.sh
        if os.path.isfile(os.path.join(thumb_dir(proj), f)):
            return f
    return None


def _vnum(path):
    m = re.search(r"/v(\d+)/", path)
    return int(m[1]) if m else 0


def titles_sim(proj):
    """标题 tab: the feed simulation of the CHOSEN cover × the current title candidates, rebuilt when either changes.
    The cover-stage feed_sim*.html pages showed old candidates and a working title (creator 11/11), so they are not used here."""
    ts = titles(proj) or [{"id": "-", "text": "（标题候选还在出）"}]   # the tab always shows (creator 11/11)
    cs = covers(proj)   # the chosen cover, else the recommended candidate until he picks one
    c = next((x for x in cs if x.get("chosen")), None) or next((x for x in cs if "推荐" in (x.get("tag") or "")), None) \
        or (cs[0] if cs else None)
    img = c and (c.get("img") or c.get("s360"))
    if not img:
        return None
    out = os.path.join(thumb_dir(proj), "titles_sim.html")
    srcs = [os.path.join(thumb_dir(proj), img), os.path.join(thumb_dir(proj), "CHOSEN")] + \
           glob.glob(os.path.join(edit_dir(proj), "publish_prep", "*"))
    newest = max((os.path.getmtime(f) for f in srcs if os.path.exists(f)), default=0)
    key = json.dumps([img, [t["text"] for t in ts]], ensure_ascii=False)
    try:
        fresh = os.path.getmtime(out) >= newest and open(out + ".key", encoding="utf-8").read() == key
    except OSError:
        fresh = False
    if not fresh:
        cmd = [sys.executable, os.path.join(REPO, "scripts", "feed_sim.py"), os.path.join(thumb_dir(proj), img), "--out", out]
        for t in ts:
            cmd += ["--title", t["text"]]
        d = _preview_duration(proj)
        if d:
            cmd += ["--duration", f"{int(d // 60)}:{int(d % 60):02d}"]
        try:
            subprocess.run(cmd, cwd=REPO, capture_output=True, timeout=60, check=True)
            open(out + ".key", "w", encoding="utf-8").write(key)
        except Exception:
            return None
    return "titles_sim.html"


def _preview_duration(proj):
    try:
        with open(os.path.join(edit_dir(proj), "render_status.json"), encoding="utf-8") as f:
            return float(json.load(f).get("duration") or 0)
    except Exception:
        return 0


def _cover_files(proj, v, cid):
    """Relative paths of one candidate's renders: big (YouTube 1280), s360 / s168 (feed sizes), bili."""
    def first(*names):
        return next((r for r in names if os.path.isfile(os.path.join(thumb_dir(proj), r))), None)
    return {"img": first(f"v{v}/{cid}_youtube.jpg", f"v{v}/{cid}.jpg", f"v{v}/{cid}.png", f"v{v}/{cid}_360.jpg",
                         f"{cid}_youtube.jpg", f"{cid}.jpg"),
            "s360": first(f"v{v}/{cid}_360.jpg"), "s168": first(f"v{v}/{cid}_168.jpg"),
            "bili": first(f"v{v}/{cid}_bilibili.jpg", f"{cid}_bilibili.jpg")}


def _covers_json(proj, path):
    v = _vnum(path)
    try:
        with open(path, encoding="utf-8") as f:
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
            out.append(dict({"id": cid, "title": re.sub(r"<[^>]+>", "", c.get("title") or cid), "tag": c.get("tag") or "",
                             "why": re.sub(r"<[^>]+>", "", c.get("why") or ""), "v": v}, **_cover_files(proj, v, cid)))
    return out


def chosen_cover(proj):
    """The id thumbnail/CHOSEN names ("E3 (v4) — ..." or "F6_bridge_dawn (v2) — ..."), resolved against the
    candidates (a short id like E3 matches E3_nanjinglu of that version). None when nothing is chosen."""
    try:
        with open(os.path.join(thumb_dir(proj), "CHOSEN"), encoding="utf-8") as f:
            line = f.readline()
    except OSError:
        return None
    m = re.match(r"\s*([\w.-]+)(?:\s*\(v(\d+)\))?", line)
    if not m:
        return None
    word, v = m[1], int(m[2]) if m[2] else None
    js = sorted(glob.glob(os.path.join(thumb_dir(proj), "v*", "covers.json")), key=_vnum, reverse=True)
    for path in js:
        if v is not None and _vnum(path) != v:
            continue
        for c in _covers_json(proj, path):
            if c["id"] == word or c["id"].startswith(word + "_"):
                return c["id"]
    return word


def covers(proj):
    """Candidates of the newest thumbnail/v<N>/covers.json: [{id, title, tag, why, v, img, s360, s168, bili, chosen}].
    The chosen cover (thumbnail/CHOSEN) is always listed, first, even when it came from an older round."""
    js = sorted(glob.glob(os.path.join(thumb_dir(proj), "v*", "covers.json")), key=_vnum)
    out = _covers_json(proj, js[-1]) if js else []
    ch = chosen_cover(proj)
    if ch and not any(c["id"] == ch for c in out):
        old = next((c for p in reversed(js[:-1]) for c in _covers_json(proj, p) if c["id"] == ch), None)
        if old:
            out.insert(0, old)
    for c in out:
        c["chosen"] = c["id"] == ch
    return sorted(out, key=lambda c: not c["chosen"])


def picks_now(proj):
    """current() with the cover taken from thumbnail/CHOSEN, which the agent also writes (his choices in chat)."""
    cur = current(proj)
    ch = chosen_cover(proj)
    if ch:
        cur["cover"] = ch
    else:
        cur.pop("cover", None)
    return cur


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

PICK_TYPES = ("cover", "title", "short", "raw", "approve")   # raw = 素材审完 (creator 11/11: 素材 → 成片 → 通过)
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
    elif typ == "raw":
        what = f"{ep} 素材审完"
    else:
        what = f"{ep} {typ}: {choice}{extra}"
    if undo:
        btn = {"approve": "已通过 · 撤销", "raw": "素材 ✓ · 撤销"}.get(typ, "已选 · 撤销")
        return f"- {day} · {what} 撤销 — app 点选「{btn}」"
    return f"- {day} · {what} — app 点选「{ {'approve': '审片通过', 'raw': '素材审完'}.get(typ, '选这个')}」"


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
        if typ == "cover":
            active = chosen_cover(proj) == choice
        if undo != active:   # double click / stale page: nothing to do
            return picks_now(proj)
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
                    if os.path.exists(cpath):   # keep what it said (e.g. the agent wrote it from his words in chat)
                        with open(cpath, encoding="utf-8") as f:
                            e["chosen_was"] = f.read()
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
        return picks_now(proj)


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------- agent control (read-only: open / tab / seek)

TAB_KEYS = {"cover": "cover", "raw": "raw", "cut": "cut", "shorts": "shorts", "titles": "titles",
            "封面": "cover", "素材": "raw", "成片": "cut", "标题": "titles", "short": "shorts", "title": "titles"}


def find_project(ep):
    """'126' -> the episode folder under the episodes root; a path (absolute or ~) -> that folder. None if missing."""
    ep = (ep or "").strip()
    if re.fullmatch(r"\d+", ep):
        return next((e["path"] for e in episodes() if e["num"] == int(ep)), None)
    p = os.path.expanduser(ep)
    return os.path.realpath(p) if os.path.isabs(p) and os.path.isdir(p) else None


def parse_agent_url(url):
    """shenpian://open?ep=126&tab=cut&t=83.5 (or path=<project>, clip=<raw clip> with t on the raw page)
    -> {"action": "open", "path", "tab", "t", "clip"}; shenpian://quit -> {"action": "quit"}. Raises ValueError."""
    u = urllib.parse.urlsplit(url or "")
    if u.scheme != "shenpian":
        raise ValueError("not a shenpian:// URL")
    action = (u.netloc or u.path.strip("/")).lower()
    if action == "quit":
        return {"action": "quit"}
    if action != "open":
        raise ValueError(f"unknown action {action!r} (only open / quit)")
    q = dict(urllib.parse.parse_qsl(u.query))
    want = q.get("path") or q.get("ep")
    if not want:
        raise ValueError("ep= or path= is required")
    proj = find_project(want)
    if not proj:
        raise ValueError(f"no project folder for {want!r}")
    out = {"action": "open", "path": proj, "tab": None, "t": None, "clip": None, "bg": q.get("bg") in ("1", "true")}
    if q.get("tab"):
        out["tab"] = TAB_KEYS.get(q["tab"].strip().lower()) or TAB_KEYS.get(q["tab"].strip())
        if not out["tab"]:
            raise ValueError(f"unknown tab {q['tab']!r} (cover / raw / cut / shorts / titles)")
    if q.get("t") not in (None, ""):
        try:
            out["t"] = round(float(q["t"]), 3)
        except ValueError:
            raise ValueError("t must be seconds") from None
        if not 0 <= out["t"] < 86400:
            raise ValueError("t out of range")
    if q.get("clip"):
        out["clip"] = q["clip"][:200]
    return out


def server_info_path():
    return os.path.join(os.path.dirname(state_path()), "server.json")


APP = {"port": None, "window_id": None, "parent_pid": None}
SHOWN = {}   # what the shell page shows: project, tab, t, clip, dirty, error (it posts this on every change)


def app_state():
    proj = SHOWN.get("project")
    info = episode_info(proj) if proj and os.path.isdir(proj) else {}
    ports = {k: port for k, (_, port) in SERVERS.procs.items()} if proj and SERVERS.proj == proj else {}
    return {"running": True, "pid": os.getpid(), "app_pid": APP["parent_pid"], "port": APP["port"],
            "window_id": APP["window_id"], "project": proj, "name": info.get("name"), "label": info.get("label"),
            "read_only": info.get("ro"), "tab": SHOWN.get("tab"), "t": SHOWN.get("t"), "clip": SHOWN.get("clip"),
            "dirty": bool(SHOWN.get("dirty")), "error": SHOWN.get("error"), "ports": ports, "updated": SHOWN.get("at")}


# ---------------------------------------------------------------- child servers

def port_free(p):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # like the servers themselves (werkzeug): a port the last episode just closed (TIME_WAIT) is free again, so
        # reopening an episode gets its old port back (the pages keep their settings per port); a listener still fails
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
PAGE_TABS = ("cover", "raw", "cut", "shorts", "titles", "none")
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


@app.get("/api/trips")
def api_trips():
    return jsonify(trips())


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
    cv, fs = cover_page(proj), titles_sim(proj)
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
    return jsonify(dict(episode_info(proj), tabs=tabs, notes=notes, token=tok, has_preview=has_preview(proj),
                        covers=[dict(c, **{k: f"/f/{tok}/{c[k]}" if c[k] else None for k in ("img", "s360", "s168", "bili")})
                                for c in covers(proj)],
                        titles=titles(proj), shorts=[s["name"] for s in shorts], picks=picks_now(proj)))


@app.post("/api/pick")
def api_pick():
    body = request.get_json(silent=True) or {}
    proj = _proj_arg()
    try:
        cur = pick(proj, body.get("type"), body.get("choice"), bool(body.get("undo")))
    except ValueError as e:
        return jsonify({"ok": False, "error": "只读文件夹，不能选" if str(e) == "read-only" else "无效的选择"}), 400
    return jsonify({"ok": True, "picks": cur, "chip": status(proj)})


@app.get("/api/app/parse")
def api_app_parse():
    try:
        return jsonify(dict(parse_agent_url(request.args.get("url")), ok=True))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/app/state", methods=["GET", "POST"])
def api_app_state():
    if request.method == "POST":   # the shell page: what it shows now (display state only, nothing is written to disk)
        b = request.get_json(silent=True) or {}
        t = b.get("t")
        SHOWN.update(project=b.get("project") if isinstance(b.get("project"), str) else None,
                     tab=b.get("tab") if b.get("tab") in PAGE_TABS else None,
                     t=round(float(t), 2) if isinstance(t, (int, float)) else None,
                     clip=str(b["clip"])[:200] if b.get("clip") else None, dirty=bool(b.get("dirty")),
                     error=str(b["error"])[:300] if b.get("error") else None, at=time.strftime("%Y-%m-%d %H:%M:%S"))
        return jsonify({"ok": True})
    return jsonify(app_state())


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
/* sidebar toggle (creator 11/10): ⌃⌘S or the button right of the traffic lights; remembered per viewer */
.app{transition:grid-template-columns .2s ease}
.side{overflow:hidden}
html.noside .app{grid-template-columns:0 minmax(0,1fr)}
html.noside .side{border-right:0}
#sidetg{position:fixed;z-index:20;left:82px;top:calc((var(--hdr) - 28px)/2);width:28px;height:28px;padding:0;border:0;background:transparent;
  color:var(--text-3);border-radius:6px;display:grid;place-items:center}
#sidetg:hover{background:rgba(120,120,128,.14);color:var(--text-2)}
html:not(.native) #sidetg{left:12px}
html.noside .top{padding-left:124px}
html.fsmode .app{grid-template-columns:0 minmax(0,1fr)!important}
html.fsmode .side{visibility:hidden;border-right:0}   /* stays a (0-wide) grid item, so the main column keeps its place */
html.fsmode .top,html.fsmode #note,html.fsmode .strip,html.fsmode #sidetg{display:none!important}
html.noside:not(.native) .top{padding-left:52px}
#eps{flex:1;overflow-y:auto;padding:0 var(--sp-2)}
.sec{font-size:var(--fs-xs);font-weight:500;color:var(--text-3);padding:var(--sp-3) var(--sp-3) var(--sp-1)}
.ep{display:grid;grid-template-columns:auto minmax(0,1fr);column-gap:var(--sp-2);align-items:baseline;min-height:34px;padding:7px var(--sp-3);
  border-radius:var(--r-sm);cursor:default;transition:background var(--dur-1) var(--ease)}
.ep:hover{background:rgba(0,0,0,.04)}
.ep.on{background:var(--sel-bg);color:var(--sel-ink)}
.ep b{font:500 var(--fs)/18px var(--font-num);font-variant-numeric:tabular-nums;color:var(--text-3);min-width:24px}
.ep .nm{min-width:0;line-height:18px;overflow:hidden;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;word-break:break-word}
.ep .chip{grid-column:2;justify-self:start;margin-top:3px}
.chip{flex:none;display:inline-flex;align-items:center;gap:5px;font-size:var(--fs-xs);line-height:20px;padding:0 8px;border-radius:999px;font-weight:500}
.chip::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor}
.chip.review{color:var(--st-review);background:var(--st-review-bg)}
.chip.q{color:var(--st-open);background:var(--st-open-bg)}
.chip.ok{color:var(--st-pass);background:var(--st-pass-bg)}
.chip.work,.chip.todo{color:var(--st-up);background:rgba(120,120,128,.12)}
.chip.todo::before{background:none;box-shadow:inset 0 0 0 1.5px currentColor}
.chip.up{display:none}   /* the 已完成 section already says so */
.chip.ro::before{display:none}
.chip.ro{color:var(--q-ink);background:var(--q-soft)}
#other{margin:var(--sp-2) var(--sp-3) var(--sp-3);justify-content:flex-start;font-size:var(--fs);color:var(--text-2)}
/* ---- toolbar: episode | centred segmented tabs | 审片通过 */
.mainc{display:flex;flex-direction:column;min-width:0;min-height:0;background:var(--bg)}
.top{height:var(--hdr);display:grid;grid-template-columns:minmax(0,1fr) auto minmax(max-content,1fr);align-items:center;gap:var(--sp-3);padding:0 var(--sp-5);
  background:var(--bg-bar);flex:none}
#ttlw{min-width:0;display:flex;align-items:baseline;gap:10px}
#ttl{min-width:0;flex:0 0 auto;max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:var(--fs-lg)}
#tmeta{flex:1 1 0;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:var(--fs-sm);color:var(--text-3);font-variant-numeric:tabular-nums}
#ttl i{font-style:normal;color:var(--text-3);font-variant-numeric:tabular-nums;margin-right:8px;font-weight:400}
#ttl b{font-weight:600}
#ttl .chip{margin-left:10px;vertical-align:2px}
#tabs{display:flex;gap:2px;padding:3px;border-radius:var(--r-sm);background:var(--surface-3)}
#tabs:empty{display:none}
#tabs button{border:0;background:transparent;color:var(--text-2);height:26px;padding:0 14px;border-radius:5px;font-size:var(--fs);
  transition:background var(--dur-1) var(--ease)}
#tabs button:hover{color:var(--text)}
#tabs button.on{background:var(--surface);color:var(--text);font-weight:500;box-shadow:var(--sh-1)}
.top .right{display:flex;justify-content:flex-end;align-items:center;gap:var(--sp-2)}
/* the open page's own header actions (保存 / 导出成片 / 更新预览), relayed by appbridge.py; clicks go back to the page */
#pacts{display:flex;align-items:center;gap:2px}
#pacts:empty{display:none}
#pacts button{height:30px;padding:0 11px;font-size:var(--fs);border-color:transparent;background:transparent;color:var(--text-2);white-space:nowrap}
#pacts button:hover{background:var(--surface-3);color:var(--text)}
#pacts button kbd{font-size:11px;padding:1px 4px;margin-left:6px;color:var(--text-3);border-bottom-width:1px}
#pacts button.dirty{color:var(--accent);background:var(--accent-soft)}
#pacts button.dirty::before{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--danger);margin-right:6px;vertical-align:2px}
#pacts button.pri{border-radius:999px;padding:0 16px;margin-left:4px;background:var(--btn-sec-bg);border-color:var(--btn-sec-line);color:var(--btn-sec-ink);font-weight:500}
#pacts button.pri:hover{background:var(--surface-2)}
#pacts button.danger,#pacts button.danger:hover{background:var(--danger);border-color:var(--danger);color:#fff}
@media (max-width:1180px){.top{padding:0 var(--sp-3);gap:var(--sp-2)}#tabs button{padding:0 10px}#pacts button{padding:0 7px}#pacts kbd{display:none}#tmeta{display:none}}
#approve{border-radius:999px;padding:0 16px;height:30px;background:var(--btn-pri-bg);border-color:var(--btn-pri-bg);color:var(--btn-pri-ink);font-weight:500}
#approve:hover{background:var(--accent-hover)}
#approve.on{background:var(--st-pass-bg);border-color:transparent;color:var(--st-pass)}
#rawok{border-radius:999px;padding:0 12px;height:30px;background:transparent;border-color:transparent;color:var(--st-pass);margin-right:4px}
#rawok:hover{background:var(--st-pass-bg)}
#note{display:none;margin:0 var(--sp-5) var(--sp-2);padding:var(--sp-2) var(--sp-3);border-radius:var(--r-sm);background:var(--q-soft);color:var(--q-ink);font-size:var(--fs)}
/* ---- views */
.views{flex:1;min-height:0;position:relative}
.view{position:absolute;inset:0;display:none;flex-direction:column}
.view.on{display:flex}
.view iframe{flex:1;border:0;width:100%;min-height:0;background:var(--bg)}
.empty{margin:auto;color:var(--text-3);font-size:var(--fs-md);text-align:center;line-height:2}
/* 选这个 strip under the cover / title / Shorts page: a sheet, rows without boxes */
/* 封面 (creator 11/10): only the candidates, big; the chosen one marked; sizes + notes behind ⋯ */
.cgrid{flex:1;overflow:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:var(--sp-5);padding:var(--sp-5);align-content:start}
.cv{position:relative;border-radius:12px;background:var(--bg-rail);border:1px solid var(--line);overflow:hidden}
.cv img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;background:#000}
.cv.on{border-color:var(--st-pass);box-shadow:0 0 0 3px var(--st-pass-bg)}
.cv .badge{position:absolute;top:10px;left:10px;background:var(--st-pass);color:#fff;font-size:var(--fs-xs);font-weight:600;padding:3px 10px;border-radius:999px}
.cv .row{display:flex;align-items:center;gap:var(--sp-2);padding:10px 12px}
.cv .row b{flex:1;min-width:0;font-size:var(--fs-sm);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cv .row .more{width:30px;padding:0;font-size:18px;line-height:28px}
.cv.on .row .pk{color:var(--st-pass)}
.cdet{position:absolute;inset:0;z-index:5;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center}
.cdet>div{background:var(--bg);color:var(--text);border-radius:14px;max-width:min(900px,92%);max-height:88%;overflow:auto;padding:var(--sp-5);box-shadow:0 20px 60px rgba(0,0,0,.35)}
.cdet h3{margin:0 0 var(--sp-3);font-size:var(--fs-md)}
.cdet .sz{display:flex;gap:var(--sp-5);align-items:flex-start;flex-wrap:wrap;margin:var(--sp-3) 0}
.cdet .sz figure{margin:0}.cdet figcaption{font-size:var(--fs-xs);color:var(--text-3);margin-top:4px}
.cdet p{font-size:var(--fs-sm);line-height:1.7;color:var(--text-2);margin:var(--sp-3) 0}
.cdet .acts{display:flex;gap:var(--sp-2);justify-content:flex-end}
.strip{flex:none;display:flex;gap:var(--sp-2);overflow-x:auto;padding:var(--sp-3) var(--sp-5);background:var(--bg-rail);border-top:1px solid var(--line)}
.strip:empty{display:none}
.cand{flex:none;display:flex;gap:var(--sp-3);align-items:center;padding:var(--sp-2);border-radius:var(--r);background:var(--surface-2);max-width:440px}
.cand.on{background:var(--st-pass-bg)}
.cand img{width:96px;aspect-ratio:16/9;object-fit:cover;border-radius:var(--r-xs);background:var(--surface-3)}
.cand .tx{display:flex;flex-direction:column;min-width:0;font-size:var(--fs-sm);color:var(--text-3)}
.cand .tx b{font-size:var(--fs);line-height:1.4;color:var(--text);font-weight:600;max-width:300px;overflow:hidden;
  display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;word-break:break-word}   /* a title must be readable to be picked */
.cand button{flex:none;height:28px;font-size:var(--fs-sm);border-radius:999px;background:var(--btn-sec-bg);border-color:var(--btn-sec-line);color:var(--btn-sec-ink)}
.cand.on button{color:var(--st-pass);border-color:transparent;background:transparent}
body.ro .cand button,body.ro #approve,body.ro #rawok{display:none}
</style></head><body>
<div class="app">
<button id="sidetg" title="显示 / 隐藏边栏（⌃⌘S）"><svg width="18" height="14" viewBox="0 0 18 14" fill="none" stroke="currentColor" stroke-width="1.4"><rect x=".7" y=".7" width="16.6" height="12.6" rx="2.6"/><path d="M6.2 1v12"/></svg></button>
<aside class="side"><div class="lights"></div><div id="eps" class="scroll"></div>
  <button id="other" class="ghost" title="比如外接硬盘上的旧项目（只读）">打开其他文件夹…</button></aside>
<section class="mainc">
  <header class="top"><span id="ttlw"><span id="ttl"></span><span id="tmeta"></span></span><nav id="tabs"></nav>
    <span class="right"><span id="pacts"></span><button id="rawok" hidden title="撤销「素材审完」">素材 ✓</button><button id="approve" hidden title="这一期审片通过（只记下来，不会上传）">审片通过</button></span></header>
  <div id="note"></div>
  <div class="views" id="views"><div class="view on" id="v-none"><div class="empty">左边点一期开始审片</div></div></div>
</section></div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const TABS=[['cover','封面'],['raw','素材'],['cut','成片'],['shorts','Shorts'],['titles','标题']];
let EP=null, cur=null, others=[], ACTS={};   // ACTS: tab -> the page's header {acts, meta} (appbridge.py)
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(r=>r.json());
function chip(e){return e.ro?'<span class="chip ro">只读</span>':(e.chip?`<span class="chip ${e.chip}">${esc(e.chip_text)}</span>`:'')}
function row(e){const n=/^\d+$/.test(e.label)?e.label:'';
  return `<div class="ep${EP&&EP.path===e.path?' on':''}" data-p="${esc(e.path)}" title="${esc(e.path)}"><b>${esc(n)}</b><span class="nm">${esc(n?e.name.replace(/^\d+ - /,''):e.name)}</span>${chip(e)}</div>`}
// 待整理 (creator 2026-11-10): a trip's raw dump not split into episodes yet. The agent does the split; the row only shows it is waiting.
function tripRow(t){return `<div class="ep trip" data-t="${esc(t.name)}" title="${esc(t.path)}"><b></b><span class="nm">${esc(t.name)}</span><span class="chip todo">待整理 · ${t.clips} 个素材</span></div>`}
async function list(){const [eps,trips]=await Promise.all([fetch('/api/episodes').then(r=>r.json()),fetch('/api/trips').then(r=>r.json()).catch(()=>[])]);
  const g=(t,a,f=row)=>a.length?`<div class="sec">${t}</div>`+a.map(f).join(''):'';
  $('eps').innerHTML=g('待整理',trips,tripRow)+g('进行中',eps.filter(e=>e.chip!=='up'))+g('已完成',eps.filter(e=>e.chip==='up'))+g('其他文件夹',others);
  $('eps').querySelectorAll('.ep:not(.trip)').forEach(el=>el.onclick=()=>openEp(el.dataset.p));
  $('eps').querySelectorAll('.ep.trip').forEach(el=>el.onclick=()=>showTrip(el.dataset.t))}
function showTrip(n){if(EP&&dirtyPages()&&!confirm('成片里有修改还没保存，换走会丢掉这些修改。\n还是要换吗？'))return;
  EP=null;cur=null;ACTS={};acts();document.querySelectorAll('.ep').forEach(e=>e.classList.toggle('on',e.dataset.t===n));
  $('ttl').innerHTML=`<b>${esc(n)}</b>`;$('tmeta').textContent='';$('tabs').innerHTML='';$('approve').hidden=true;$('rawok').hidden=true;$('note').style.display='none';
  $('views').innerHTML=`<div class="view on" id="v-none"><div class="empty">这趟的素材还没分期。<br>在对话里跟 agent 说「整理 ${esc(n)}」，分好以后每一期会出现在「进行中」。</div></div>`}
// Opening is one request at a time: quick clicks through the list open only the last one clicked (the server stops the
// previous episode's servers on every open, so overlapping opens could leave the page pointing at stopped servers).
let opening=false, wantOpen=null;
const dirtyPages=()=>Object.values(ACTS).some(a=>(a.acts||[]).some(b=>b.dirty));
async function openEp(p){
  if(EP&&p!==EP.path&&!opening&&dirtyPages()&&!confirm('成片里有修改还没保存，换一期会丢掉这些修改。\n还是要换吗？'))return;
  wantOpen=p;document.querySelectorAll('.ep').forEach(e=>e.classList.toggle('on',e.dataset.p===p));
  $('ttl').innerHTML='<i>启动中…</i>';$('tmeta').textContent='';$('tabs').innerHTML='';$('pacts').innerHTML='';$('approve').hidden=true;$('rawok').hidden=true;$('note').style.display='none';
  $('views').innerHTML='<div class="view on" id="v-none"><div class="empty">启动中…</div></div>';EP=null;cur=null;ACTS={};
  if(opening)return;opening=true;let j;
  try{while(wantOpen){const q=wantOpen;wantOpen=null;j=await post('/api/open',{path:q}).catch(()=>null);
    if(!wantOpen){if(j)showEp(j);else{$('ttl').innerHTML='';$('views').innerHTML='<div class="view on" id="v-none"><div class="empty">这一期打不开（日志在 ~/Library/Logs/审片/）</div></div>'}}}}
  finally{opening=false}}
function showEp(j){EP=j;cur=null;ACTS={};TIME={};acts();
  if(j.ro&&!others.some(o=>o.path===j.path)&&!document.querySelector('.ep[data-p="'+CSS.escape(j.path)+'"]'))others.push(j);
  document.title='审片 · '+j.name;const num=/^\d+$/.test(j.label)?j.label:'';
  $('ttl').innerHTML=(num?`<i>${esc(num)}</i>`:'')+`<b>${esc(num?j.name.replace(/^\d+ - /,''):j.name)}</b>`+(j.ro?'<span class="chip ro" title="这个文件夹不会被写入">只读</span>':'');document.body.classList.toggle('ro',!!j.ro);
  $('note').textContent=(j.notes||[]).join(' ');$('note').style.display=j.notes&&j.notes.length?'block':'none';
  const has={cover:j.tabs.cover||j.covers.length,raw:j.tabs.raw,cut:j.tabs.cut,shorts:j.tabs.shorts,titles:true};
  $('tabs').innerHTML=TABS.map(([k,n],i)=>has[k]?`<button data-k="${k}" title="⌘${i+1}">${n}</button>`:'').join('');
  $('tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>tab(b.dataset.k));
  $('views').innerHTML=TABS.map(([k])=>has[k]?`<div class="view" id="v-${k}">${k==='cover'&&j.covers.length?'<div class="cgrid" id="cgrid"></div>':j.tabs[k]?`<iframe data-src="${esc(j.tabs[k])}" allow="fullscreen; autoplay"></iframe>`:`<div class="empty">${k==='titles'?'还没选封面，选好后这里会把封面和候选标题放进首页里比较':'这一期还没有这个页面，下面可以直接选'}</div>`}${k==='shorts'?'':`<div class="strip" id="s-${k}"></div>`}</div>`:'').join('')
    +'<div class="view" id="v-none"><div class="empty">这一期没有能打开的页面</div></div>';
  strips();list();
  // once there is a preview the work is reviewing the cut, so open on 成片 (creator 11/11); before that, 素材
  // stages: footage first; the cut opens first only once he has marked 素材审完 (creator 11/11)
  const first=(j.has_preview&&(j.picks||{}).raw?['cut','raw']:['raw','cut']).concat(['cover','shorts','titles']).find(k=>has[k]);tab(first||'none')}
function tab(k){if(!EP)return;const v=$('v-'+k);if(!v)return;
  if(cur&&cur!==k){const f=document.querySelector('#v-'+cur+' iframe');if(f&&f.contentWindow)f.contentWindow.postMessage({shenpian:'pause'},'*')}
  cur=k;acts();report();document.querySelectorAll('.view').forEach(x=>x.classList.toggle('on',x===v));
  document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.k===k));
  const f=v.querySelector('iframe');if(f&&!f.getAttribute('src')){delete f.dataset.ready;f.src=f.dataset.src}if(f)setTimeout(()=>f.focus(),50)}
function setSide(shown){document.documentElement.classList.toggle('noside',!shown);
  try{localStorage.setItem('shenpian.side',shown?'1':'0')}catch(e){}
  if(window.webkit&&webkit.messageHandlers&&webkit.messageHandlers.shell)webkit.messageHandlers.shell.postMessage({cmd:'sidebar',shown})}
const toggleSide=()=>setSide(document.documentElement.classList.contains('noside'));
$('sidetg').onclick=toggleSide;
document.addEventListener('keydown',e=>{if(e.key.toLowerCase()==='s'&&e.metaKey&&e.ctrlKey){e.preventDefault();toggleSide()}});
try{if(localStorage.getItem('shenpian.side')==='0')setSide(false)}catch(e){}
// 全屏 from a page (chat.py): the window goes fullscreen (Swift) and the app's own chrome hides, so the page fills it
function pageFs(on){document.documentElement.classList.toggle('fsmode',on);
  if(window.webkit&&webkit.messageHandlers&&webkit.messageHandlers.shell)webkit.messageHandlers.shell.postMessage({cmd:'fullscreen',on})}
window.addEventListener('message',e=>{const d=e.data;if(d&&d.shenpian==='fs')pageFs(!!d.on)});
function fsExited(){if(!document.documentElement.classList.contains('fsmode'))return;document.documentElement.classList.remove('fsmode');
  document.querySelectorAll('.view iframe').forEach(f=>{try{f.contentWindow.postMessage({shenpian:'fsoff'},'*')}catch(e){}})}
window.shell={toggleSide,fsExited,rail:()=>{const f=cur&&frameOf(cur);if(f&&f.contentWindow)f.contentWindow.postMessage({shenpian:'rail'},'*')},tab:n=>{const t=TABS[n-1];if(t)tab(t[0])},openPath:p=>openEp(p),dirty:dirtyPages,agent:agentOpen};   // dirty: the Swift app asks before quitting
// 选这个 / 已选 · 撤销 (Q9): one APPROVALS.md line per click
function cand(type,id,html){const P=EP.picks||{},on=type==='short'?(P.short||[]).includes(id):P[type]===id;
  return `<div class="cand${on?' on':''}">${html}<button data-t="${type}" data-c="${esc(id)}" data-u="${on?1:''}">${on?'已选 · 撤销':'选这个'}</button></div>`}
function coverGrid(){const g=$('cgrid');if(!g)return;const P=EP.picks||{};
  g.innerHTML=EP.covers.map((c,i)=>{const on=P.cover===c.id;
    return `<div class="cv${on?' on':''}">${on?'<span class="badge">✓ 已选</span>':''}${c.img?`<img src="${esc(c.img)}" alt="" data-i="${i}">`:''}
      <div class="row"><b title="${esc(c.title)}">${esc(c.title)}</b><button class="more" data-i="${i}" title="手机首页 / 侧栏 / B站 和说明">⋯</button>
      <button class="pk" data-t="cover" data-c="${esc(c.id)}" data-u="${on?1:''}">${on?'已选 · 撤销':'选这个'}</button></div></div>`}).join('');
  g.querySelectorAll('.more,img').forEach(b=>b.onclick=()=>coverDetail(EP.covers[+b.dataset.i]));
  g.querySelectorAll('.pk').forEach(b=>b.onclick=()=>doPick(b.dataset.t,b.dataset.c,!!b.dataset.u))}
function coverDetail(c){const v=$('v-cover');if(!v||!c)return;const d=document.createElement('div');d.className='cdet';
  const fig=(src,w,cap)=>src?`<figure><img src="${esc(src)}" style="width:${w}px;border-radius:${w<200?4:8}px" alt=""><figcaption>${cap}</figcaption></figure>`:'';
  d.innerHTML=`<div><h3>${esc(c.title)}${c.tag?` <span class="chip review">${esc(c.tag)}</span>`:''}</h3>
    <div class="sz">${fig(c.s360||c.img,360,'手机首页')}${fig(c.s168||c.img,168,'侧栏')}${fig(c.bili,300,'B站')}</div>
    ${c.why?`<p>${esc(c.why)}</p>`:''}<div class="acts">${EP.tabs.cover?'<button class="full">完整对比页</button>':''}<button class="x">关闭</button></div></div>`;
  d.onclick=e=>{if(e.target===d||e.target.classList.contains('x'))d.remove()};
  const f=d.querySelector('.full');if(f)f.onclick=()=>{d.firstElementChild.innerHTML='';d.firstElementChild.style.cssText='width:92%;height:88%;padding:0;overflow:hidden';
    d.firstElementChild.innerHTML=`<iframe src="${esc(EP.tabs.cover)}" style="width:100%;height:100%;border:0"></iframe>`};
  v.appendChild(d)}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){const d=document.querySelector('.cdet');if(d)d.remove()}});
function strips(){if(!EP)return;const s=(k,h)=>{const e=$('s-'+k);if(e)e.innerHTML=h};
  coverGrid();
  s('titles',EP.titles.map(t=>cand('title',t.text,`<span class="tx"><b title="${esc(t.text)}">${esc(t.text)}</b>${esc(t.id)}</span>`)).join(''));
  // no picks for Shorts: both always go out (creator 11/11: 「shorts 一般我都是直接发两个」)
  document.querySelectorAll('.strip button').forEach(b=>b.onclick=()=>doPick(b.dataset.t,b.dataset.c,!!b.dataset.u));
  // one stage button: 素材审完 → 审片通过 → 已通过 · 撤销; 「素材 ✓」 undoes the first stage
  const P=EP.picks||{},on=!!P.approve,a=$('approve');a.hidden=false;a.classList.toggle('on',on);
  a.textContent=on?'已通过 · 撤销':P.raw?'审片通过':'素材审完';
  a.title=on?'撤销审片通过':P.raw?'这一期审片通过（只记下来，不会上传）':'素材都看完了，接下来审成片（只记下来）';
  $('rawok').hidden=!P.raw||on}
async function doPick(type,choice,undo){const j=await post('/api/pick',{path:EP.path,type,choice,undo});
  if(j.ok){EP.picks=j.picks;strips();list()}else alert(j.error||'没记下来')}
$('approve').onclick=async()=>{const P=EP.picks||{};
  if(P.approve||P.raw){doPick('approve','审片通过',!!P.approve);return}
  await doPick('raw','素材审完',false);if((EP.picks||{}).raw&&$('v-cut'))tab('cut')};
$('rawok').onclick=()=>doPick('raw','素材审完',true);
$('other').onclick=()=>{if(window.webkit&&webkit.messageHandlers&&webkit.messageHandlers.shell)webkit.messageHandlers.shell.postMessage({cmd:'pickFolder'});
  else{const p=prompt('项目文件夹的路径');if(p)openEp(p)}};
// the open page's header (meta text + 保存 / 导出成片 / 更新预览) shown in this toolbar; a click is sent back to the page,
// which clicks its own (hidden) button, so the behaviour (⌘S, the two 导出成片 confirmations, read-only) is the page's own
function frameOf(k){return document.querySelector('#v-'+k+' iframe')}
function acts(){const a=ACTS[cur]||{};$('tmeta').textContent=$('tmeta').title=a.meta||'';
  $('pacts').innerHTML=(a.acts||[]).map(b=>`<button data-id="${esc(b.id)}" class="${b.pri?'pri':''}${b.dirty?' dirty':''}${b.danger?' danger':''}" title="${esc(b.title)}"${b.disabled?' disabled':''}>${esc(b.label)}${b.kbd?`<kbd>${esc(b.kbd)}</kbd>`:''}</button>`).join('');
  $('pacts').querySelectorAll('button').forEach(b=>b.onclick=()=>pageAct(b.dataset.id))}
function pageAct(id){const f=frameOf(cur);if(!f||!f.contentWindow)return;f.contentWindow.postMessage({shenpian:'act',id},'*');f.focus()}
window.addEventListener('message',e=>{const d=e.data;if(!d||d.shenpian!=='hdr')return;
  const k=TABS.map(t=>t[0]).find(k=>{const f=frameOf(k);return f&&f.contentWindow===e.source});if(!k)return;
  ACTS[k]={acts:Array.isArray(d.acts)?d.acts:[],meta:String(d.meta||'')};if(k===cur)acts();report()});
// seek the page of tab k (cut: t = seconds of the cut; raw: clip + t), once its page has loaded
function seekIn(k,m){const f=frameOf(k);if(!f)return;const send=()=>f.contentWindow.postMessage({shenpian:'seek',clip:m.clip,t:m.t},'*');
  if(f.dataset.ready)send();else f.addEventListener('load',()=>setTimeout(send,1500),{once:true})}
// Q7: a page asks to jump to the other page at a moment
window.addEventListener('message',e=>{const d=e.data;if(!d||d.shenpian!=='jump'||!EP)return;
  if(!$('v-'+d.to))return;tab(d.to);seekIn(d.to,d)});
// what is on screen -> /api/app/state (scripts/shenpian status): episode, tab, the playhead each page reports
let TIME={}, agentErr=null, repT=0;
window.addEventListener('message',e=>{const d=e.data;if(!d||d.shenpian!=='time')return;
  const k=TABS.map(t=>t[0]).find(k=>{const f=frameOf(k);return f&&f.contentWindow===e.source});if(k){TIME[k]=d.here||{};if(k===cur)report()}});
function report(){if(repT)return;repT=setTimeout(()=>{repT=0;const h=TIME[cur]||{};
  post('/api/app/state',{project:EP&&EP.path,tab:EP?cur:null,t:h.cut_t!=null?h.cut_t:(h.clip_t!=null?h.clip_t:null),clip:h.clip||null,dirty:dirtyPages(),error:agentErr}).catch(()=>{})},300)}
// agent control (the Swift app forwards shenpian://open?... here): open / tab / seek only — never a pick, save or render
async function agentOpen(url){agentErr=null;let r;
  try{r=await (await fetch('/api/app/parse?url='+encodeURIComponent(url))).json()}catch(e){r={ok:false,error:String(e)}}
  if(!r.ok){agentErr=r.error||'bad url';report();return r}
  if(r.action!=='open')return r;
  if(!EP||EP.path!==r.path){
    if(EP&&dirtyPages()){agentErr='成片有修改还没保存：没有换期（等他保存）';report();return {ok:false,error:agentErr}}
    await openEp(r.path)}
  if(r.tab){if(!$('v-'+r.tab)){agentErr='这一期没有 '+r.tab+' 页';report();return {ok:false,error:agentErr}}tab(r.tab)}
  if(r.t!=null)seekIn(cur,{t:r.t,clip:r.clip});
  report();return {ok:true}}
// ready = its page has loaded (an iframe without src also fires load, for about:blank: that one doesn't count)
document.addEventListener('load',e=>{if(e.target.tagName==='IFRAME'&&e.target.getAttribute('src'))e.target.dataset.ready=1},true);
// ⌘1–⌘5 also work here when the shell itself has focus (the Swift menu handles them everywhere else)
document.addEventListener('keydown',e=>{if(e.metaKey&&e.key>='1'&&e.key<='5'){e.preventDefault();shell.tab(+e.key)}
  else if(e.metaKey&&e.key==='s'){e.preventDefault();if((ACTS[cur]&&ACTS[cur].acts||[]).some(a=>a.id==='bSave'))pageAct('bSave')}});
list();setInterval(list,30000);
{const q=new URLSearchParams(location.search);if(q.get('open'))openEp(q.get('open')).then(()=>{if(q.get('tab'))tab(q.get('tab'));
  if(q.get('t'))seekIn(cur,{t:+q.get('t'),clip:q.get('clip')||undefined})})}   // ?open=<path>&tab=cut&t=83.5
</script></body></html>
"""
PAGE = PAGE.replace("__THEME_CSS__", THEME.CSS)


def _drop_server_info():
    try:
        with open(server_info_path(), encoding="utf-8") as f:
            if json.load(f).get("pid") == os.getpid():
                os.remove(server_info_path())
    except (OSError, ValueError):
        pass


def _shutdown(*_):
    SERVERS.stop()
    _drop_server_info()
    os._exit(0)


def main():
    # Launched from Finder/Dock the PATH is /usr/bin:/bin only: renders need ffmpeg/ffprobe from Homebrew (creator 11/11:
    # 「生成预览失败：No such file or directory: 'ffprobe'」). The episode servers and renders inherit this.
    path = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join([d for d in ("/opt/homebrew/bin", "/usr/local/bin") if d not in path] + path)
    ap = argparse.ArgumentParser(description="Backend of the 审片 Mac app")
    ap.add_argument("--port", type=int, default=0, help="0 = any free port")
    ap.add_argument("--port-file", help="write the chosen port here (the Swift app reads it)")
    ap.add_argument("--parent-pid", type=int, help="exit (and stop the episode servers) when this process is gone")
    ap.add_argument("--window-id", type=int, help="the app window's id (status / screenshots for scripts/shenpian)")
    a = ap.parse_args()
    atexit.register(SERVERS.stop)
    atexit.register(_drop_server_info)
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
    APP.update(port=port, window_id=a.window_id, parent_pid=a.parent_pid)
    if a.parent_pid:   # the app's server (not a test run): tell scripts/shenpian where to find it
        try:
            os.makedirs(os.path.dirname(server_info_path()), exist_ok=True)
            _write(server_info_path(), json.dumps({"pid": os.getpid(), "port": port, "app_pid": a.parent_pid,
                                                   "window_id": a.window_id}))
        except OSError:
            pass
    print(f"审片 app server: http://127.0.0.1:{port}/", flush=True)
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
