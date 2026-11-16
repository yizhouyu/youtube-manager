"""批注 on 本地视频 (creator 2026-11-16): notes he leaves while watching a video in the local player, for the session
that made that video to pick up later (「address comments」). Not an agent chat: nothing is announced to anyone.

Storage (nothing is ever written anywhere else; the video files are never touched):
  * master: ~/Movies/审片播放器/.comments/<video name>.json — {video, on, next, comments: [{id, t, box, text,
    resolved, created, updated}], md, md_mtime}. `t` is the media time in seconds (independent of the playback speed),
    `box` = [x, y, w, h] as 0–1 of the frame (the 框选 feature of chat.py). `on` = the 批注 rail is shown for it.
  * sidecar, when the copy came from somewhere (local_player remembers the original's path; for copies made before
    that, a Spotlight file with the same name and size): next to the ORIGINAL, `<stem>.comments.md` plus
    `<stem>.comments/c<id>.jpg` (the frame at that moment, ~1280 wide, the box drawn in yellow). Rewritten on every
    add / edit / resolve / delete. If the original is gone or its folder isn't writable, only the master is kept and
    the rail says so.
  * the md is for agents: `- [ ] [01:23.4] text（框选 x,y,w,h） [画面](<stem.comments/c3.jpg>) <!-- id:3 -->` under
    「待处理」, `- [x] …` under 「已解决」. An agent marks one done by ticking its box; the app reads the ticks back
    (md -> json, the resolved flag only) the next time the comments are read, then rewrites the md. Text, time and box
    always come from the json.

    python -m src.editor.local_comments <video name or path>   # same as scripts/shenpian comments
"""
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time

from . import local_player as LP
from .chat import clean_box

FRAME_W = 1280
ITEM_RX = re.compile(r"^\s*[-*]\s+\[([ xX])\].*?<!--\s*id:(\d+)\s*-->\s*$", re.M)
_not_found = set()   # names Spotlight found no original for (this process)


def store_dir():
    d = os.path.join(LP.folder(), ".comments")
    os.makedirs(d, exist_ok=True)
    return d


def store_path(name):
    return os.path.join(store_dir(), name + ".json")


@contextlib.contextmanager
def _locked():
    """One writer at a time, across processes (the app's server and `shenpian comments`)."""
    with open(os.path.join(store_dir(), ".lock"), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _write(path, text):
    d, b = os.path.split(path)
    tmp = os.path.join(d, "." + b + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def load(name):
    try:
        with open(store_path(name), encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    d.setdefault("video", name)
    d.setdefault("on", False)
    d.setdefault("next", 1)
    d.setdefault("comments", [])
    return d


def _save(name, d):
    _write(store_path(name), json.dumps(d, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- where the original is

def _spotlight(name):
    """A file elsewhere with this name (minus a ' (2)' suffix) and the same size as the copy: exactly one, or None."""
    if os.environ.get("SHENPIAN_NO_SPOTLIGHT") == "1":
        return None
    copy = LP.safe_path(name)
    if not copy:
        return None
    base = re.sub(r" \(\d+\)(\.[^.]+)$", r"\1", name)
    size = os.path.getsize(copy)
    try:   # by exact size (Spotlight's name matching is unreliable for CJK names), then the exact file name
        out = subprocess.run(["mdfind", f"kMDItemFSSize == {size}"], capture_output=True, text=True, timeout=8).stdout.splitlines()
    except Exception:
        return None
    hits = [p for p in out if os.path.basename(p) == base and os.path.isfile(p)
            and os.path.dirname(os.path.realpath(p)) != LP.folder() and os.path.getsize(p) == size]
    return hits[0] if len(hits) == 1 else None


def origin(name):
    """(path of the original this copy came from or None, guessed?)."""
    o = (LP.load_state().get("orig") or {}).get(name)
    if isinstance(o, str):
        o = {"path": o, "guessed": False}
    if o:
        return o["path"], bool(o.get("guessed"))
    if name in _not_found:
        return None, False
    p = _spotlight(name)
    if not p:
        _not_found.add(name)
        return None, False
    LP.remember_orig(name, os.path.realpath(p), guessed=True)
    return os.path.realpath(p), True


def sidecar(name):
    """{ok, orig, guessed, md, frames, why}: where the md + frames go, or why they can't (only the app store then)."""
    orig, guessed = origin(name)
    out = {"ok": False, "orig": orig, "guessed": guessed, "md": None, "frames": None, "why": None}
    if not orig:
        out["why"] = "不知道原文件在哪，批注只存在 app 里（把原文件再拖进来一次就能连上）"
        return out
    if not os.path.isfile(orig):
        out["why"] = "原文件不在原来的地方了，批注只存在 app 里"
        return out
    d = os.path.dirname(orig)
    if os.path.realpath(d) == LP.folder():
        out["why"] = "这个视频就在播放器文件夹里，批注只存在 app 里"
        return out
    stem = os.path.splitext(os.path.basename(orig))[0]
    md, frames = os.path.join(d, stem + ".comments.md"), os.path.join(d, stem + ".comments")
    if not os.access(d, os.W_OK):
        out["why"] = "原文件所在的文件夹不能写，批注只存在 app 里"
        return out
    if os.path.islink(md) or (os.path.exists(md) and not os.path.isfile(md)) or os.path.islink(frames) \
            or (os.path.exists(frames) and not os.path.isdir(frames)):
        out["why"] = "原文件旁边已有同名的别的东西，没写，批注只存在 app 里"
        return out
    out.update(ok=True, md=md, frames=frames)
    return out


# ---------------------------------------------------------------- markdown

def fmt_t(t):
    k = int(round((t or 0) * 10))
    return f"{k // 600:02d}:{k % 600 / 10:04.1f}"


def _line(c, link=None):
    text = re.sub(r"\s*\n\s*", " / ", (c.get("text") or "").strip())
    box = c.get("box")
    b = f"（框选 {box[0]:.2f},{box[1]:.2f},{box[2]:.2f},{box[3]:.2f}）" if box else ""
    lk = f" [画面](<{link}>)" if link else ""
    return f"- [{'x' if c.get('resolved') else ' '}] [{fmt_t(c.get('t'))}] {text}{b}{lk} <!-- id:{c['id']} -->"


def markdown(name, d=None, images="rel", sc=None):
    """The md: images "rel" (sidecar, links relative to it), "abs" (terminal), None (clipboard: no links)."""
    d = d or load(name)
    sc = sc or sidecar(name)
    cs = sorted(d["comments"], key=lambda c: (c.get("t") or 0, c["id"]))
    todo, done = [c for c in cs if not c.get("resolved")], [c for c in cs if c.get("resolved")]

    def link(c):
        if not images or not sc.get("ok"):
            return None
        f = os.path.join(sc["frames"], f"c{c['id']}.jpg")
        if not os.path.isfile(f):
            return None
        return f if images == "abs" else os.path.basename(sc["frames"]) + "/" + os.path.basename(f)

    dur = d.get("dur") or LP.load_state()["pos"].get(name, {}).get("dur") or 0
    head = [f"# 批注 · {name}", "",
            f"- 视频：{os.path.join(LP.folder(), name)}（审片.app「本地视频」里的拷贝）",
            f"- 原文件：{sc.get('orig') or '（不知道）'}" + ("（按文件名 + 大小找到的）" if sc.get("guessed") else ""),
            f"- 时长：{fmt_t(dur) if dur else '（还不知道）'}",
            f"- 更新：{d.get('updated') or time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 待处理 {len(todo)} 条 · 已解决 {len(done)} 条", "",
            "审片.app 里写的批注。时间是视频本身的时间（与播放速度无关）；框选 = 画面里的 x,y,宽,高（0–1，从左上角算）。"
            "处理好一条，就把它开头的 `- [ ]` 改成 `- [x]`（只改勾选框，其他内容 app 会重写；app 下次打开会把勾读回去）。", ""]
    body = ["## 待处理", ""] + ([_line(c, link(c)) for c in todo] or ["（没有）"]) + \
           ["", "## 已解决", ""] + ([_line(c, link(c)) for c in done] or ["（没有）"])
    return "\n".join(head + body) + "\n"


def _frame(src, c, out):
    """The frame at c.t, ~1280 wide, its box drawn: a hidden temp file renamed into place. False if ffmpeg fails."""
    ff = shutil.which("ffmpeg") or next((p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg") if os.path.exists(p)), None)
    if not ff or not src:
        return False
    vf = f"scale='min({FRAME_W},iw)':-2"
    if c.get("box"):
        x, y, w, h = c["box"]
        vf += f",drawbox=x=iw*{x}:y=ih*{y}:w=iw*{w}:h=ih*{h}:color=0xFFD60A:t=5"
    tmp = os.path.join(os.path.dirname(out), "." + os.path.basename(out))
    try:
        subprocess.run([ff, "-nostdin", "-loglevel", "error", "-y", "-ss", f"{max(0, c.get('t') or 0):.3f}", "-i", src,
                        "-frames:v", "1", "-vf", vf, "-q:v", "3", "-f", "image2", tmp], check=True, timeout=60,
                       stdin=subprocess.DEVNULL, capture_output=True)
        os.replace(tmp, out)
        return True
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return False


def write_sidecar(name, d, sc=None):
    """Bring <stem>.comments.md + its frames in line with the json (frames only for comments whose time/box changed)."""
    sc = sc or sidecar(name)
    if not sc["ok"]:
        return sc
    if not d["comments"] and not os.path.exists(sc["md"]):
        return sc   # nothing written yet and nothing to write
    os.makedirs(sc["frames"], exist_ok=True)
    src = LP.safe_path(name) or sc["orig"]
    keep = set()
    for c in d["comments"]:
        f = os.path.join(sc["frames"], f"c{c['id']}.jpg")
        keep.add(os.path.basename(f))
        key = json.dumps([c.get("t"), c.get("box")])
        if c.get("frame_key") != key or not os.path.isfile(f):
            if _frame(src, c, f):
                c["frame_key"] = key
    for f in os.listdir(sc["frames"]):   # frames of deleted comments (only our own c<id>.jpg files)
        if re.fullmatch(r"c\d+\.jpg", f) and f not in keep:
            with contextlib.suppress(OSError):
                os.remove(os.path.join(sc["frames"], f))
    _write(sc["md"], markdown(name, d, "rel", sc))
    d["md"], d["md_mtime"] = sc["md"], os.stat(sc["md"]).st_mtime
    return sc


def read_back(d):
    """Ticks an agent (or he) changed in the md since the app last wrote it -> the json's resolved flags. Changed?"""
    md = d.get("md")
    if not md or not os.path.isfile(md) or os.path.islink(md):
        return False
    mt = os.stat(md).st_mtime
    if mt == d.get("md_mtime"):
        return False
    try:
        with open(md, encoding="utf-8") as f:
            ticks = {int(m[2]): m[1] in "xX" for m in ITEM_RX.finditer(f.read())}
    except (OSError, ValueError):
        return False
    d["md_mtime"] = mt
    changed = False
    for c in d["comments"]:
        if c["id"] in ticks and ticks[c["id"]] != bool(c.get("resolved")):
            c["resolved"], c["updated"], c["resolved_via"] = ticks[c["id"]], time.strftime("%Y-%m-%d %H:%M:%S"), "md"
            changed = True
    return changed


# ---------------------------------------------------------------- read / change

def view(name, d, sc):
    return {"name": name, "on": bool(d.get("on")), "comments": sorted(d["comments"], key=lambda c: (c.get("t") or 0, c["id"])),
            "sidecar": {k: sc.get(k) for k in ("ok", "orig", "guessed", "md", "why")}}


def get(name):
    """The comments of `name` (ticks from the md read back first)."""
    with _locked():
        d, sc = load(name), sidecar(name)
        seen = d.get("md_mtime")
        if read_back(d):
            d["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            with contextlib.suppress(OSError):
                write_sidecar(name, d, sc)
            _save(name, d)
        elif d.get("md_mtime") != seen:
            _save(name, d)   # an md edit without tick changes: remember this version, leave the file as it is
        return view(name, d, sc)


def change(name, op, b):
    """op: add {t, text, box?, dur?} | edit {id, text} | resolve {id, resolved} | delete {id} | toggle {on}.
    Raises ValueError on a bad request."""
    with _locked():
        d = load(name)
        read_back(d)   # an agent's ticks first, so this write doesn't undo them
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        num = lambda x, hi: isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= hi   # noqa: E731
        text = b.get("text")
        if op in ("add", "edit") and (not isinstance(text, str) or not text.strip() or len(text) > 4000):
            raise ValueError("批注不能是空的")
        c = None
        if op in ("edit", "resolve", "delete"):
            c = next((x for x in d["comments"] if x["id"] == b.get("id")), None)
            if not c:
                raise ValueError("没有这条批注")
        if op == "toggle":
            d["on"] = bool(b.get("on"))
            _save(name, d)
            return view(name, d, sidecar(name))
        if op == "add":
            if not num(b.get("t"), 1e6):
                raise ValueError("时间不对")
            c = {"id": d["next"], "t": round(float(b["t"]), 2), "text": text.strip(), "resolved": False, "created": now, "updated": now}
            c.update(clean_box({"box": b.get("box")}) if b.get("box") is not None else {})
            d["next"] += 1
            d["comments"].append(c)
            if num(b.get("dur"), 1e6):
                d["dur"] = round(float(b["dur"]), 1)
        elif op == "edit":
            c.update(text=text.strip(), updated=now)
        elif op == "resolve":
            c.update(resolved=bool(b.get("resolved")), updated=now, resolved_via="app")
        elif op == "delete":
            d["comments"].remove(c)
        else:
            raise ValueError("bad op")
        d["on"], d["updated"] = True, now
        sc = sidecar(name)
        try:
            write_sidecar(name, d, sc)
        except OSError as e:   # e.g. the drive went away: the app store still has it
            sc = dict(sc, ok=False, why=f"没写成原文件旁边的 md（{e.strerror or e}），批注只存在 app 里")
        _save(name, d)
        return view(name, d, sc)


def resolve_name(arg):
    """A video of the folder from its name, its copy's path, or the original's path. None if none matches."""
    if LP.known(arg):
        return arg
    p = os.path.realpath(os.path.expanduser(arg or ""))
    if os.path.dirname(p) == LP.folder() and LP.known(os.path.basename(p)):
        return os.path.basename(p)
    for n, o in (LP.load_state().get("orig") or {}).items():
        if (o.get("path") if isinstance(o, dict) else o) == p and LP.known(n):
            return n
    n = os.path.basename(p)
    if os.path.isfile(p) and LP.safe_path(n) and os.path.getsize(LP.safe_path(n)) == os.path.getsize(p):
        return n
    return None


def main(argv=None):
    a = (argv if argv is not None else sys.argv[1:])
    if len(a) != 1:
        sys.exit("usage: python -m src.editor.local_comments <video name or path>")
    name = resolve_name(a[0])
    if not name:   # not a video of the player: maybe there's a sidecar next to it anyway
        p = os.path.realpath(os.path.expanduser(a[0]))
        md = os.path.join(os.path.dirname(p), os.path.splitext(os.path.basename(p))[0] + ".comments.md")
        if os.path.isfile(md):
            sys.stdout.write(open(md, encoding="utf-8").read())
            return
        sys.exit(f"没有这个视频的批注：{a[0]}")
    get(name)   # reads ticks back first
    sys.stdout.write(markdown(name, images="abs"))


if __name__ == "__main__":
    main()
