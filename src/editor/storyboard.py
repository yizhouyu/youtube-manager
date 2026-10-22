"""Storyboard sprites for YouTube-style hover previews on the review pages' timelines.

One storyboard = a few JPEG sprite sheets (COLS x ROWS tiles, each tile fits in a BOX px square,
aspect kept) plus `index.json`:
    {"key": "<size>:<mtime_ns>[:norot]", "interval": 1.0, "count": 273, "cols": 10, "rows": 10,
     "w": 160, "h": 90, "sheets": ["sheet-001.jpg", ...], "dur": 272.9, "secs": 17.8}
Tile k shows the frame at k * interval seconds. The key ties it to the source file, so a
re-rendered preview (new size/mtime) regenerates on its own.

Generation is lazy and gentle: one background thread per server, newest request first, and a
cross-process file lock so the raw page and the cut page never run two jobs at once. ffmpeg runs
under `nice -n 15` with one thread, decoding through VideoToolbox (the media engine, ~no CPU);
when keyframes are at least as dense as the tiles it decodes keyframes only. Falls back to
software decoding if VideoToolbox fails.
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import threading
import time

SUB = ".storyboard"
COLS, ROWS = 10, 10           # 100 tiles per sheet (~150 KB): the page only loads what it needs
BOX = 160                     # tile fits in BOX x BOX
MAX_TILES = 1200              # longer sources get a wider interval
LOCK = "/tmp/yt-editor/storyboard.lock"

_cv = threading.Condition()
_queue = []                   # outdir, newest last (LIFO: what he hovers now goes first)
_jobs = {}                    # outdir -> (src, extra, noautorotate)
_failed = {}                  # outdir -> key that failed (don't retry the same file forever)
_thread = None


def stamp(src, extra=""):
    st = os.stat(src)
    return f"{st.st_size}:{st.st_mtime_ns}" + (f":{extra}" if extra else "")


def load(outdir, src, extra=""):
    """The storyboard index if one exists for the current version of `src`, else None."""
    try:
        with open(os.path.join(outdir, "index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        if idx.get("key") == stamp(src, extra) and all(
                os.path.isfile(os.path.join(outdir, s)) for s in idx.get("sheets", [])):
            return idx
    except (OSError, ValueError):
        pass
    return None


def request(src, outdir, noautorotate=False):
    """Index dict (with "ready": True) when the storyboard is there; otherwise queue it and
    return {"ready": False, "state": "queued|running|error"}. Never blocks."""
    extra = "norot" if noautorotate else ""
    try:
        idx = load(outdir, src, extra)
    except OSError:
        return {"ready": False, "state": "error"}
    if idx:
        return dict(idx, ready=True)
    key = stamp(src, extra)
    if _failed.get(outdir) == key:
        return {"ready": False, "state": "error"}
    with _cv:
        state = "running" if _jobs.get(outdir) == "running" else "queued"
        if state == "queued":
            if outdir in _queue:
                _queue.remove(outdir)
            _queue.append(outdir)
            _jobs[outdir] = (src, extra, noautorotate)
            _start()
            _cv.notify()
    return {"ready": False, "state": state}


def _start():
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_worker, name="storyboard", daemon=True)
        _thread.start()


def _worker():
    while True:
        with _cv:
            while not _queue:
                _cv.wait()
            outdir = _queue.pop()
            src, extra, norot = _jobs[outdir]
            _jobs[outdir] = "running"
        try:
            os.makedirs(os.path.dirname(LOCK), exist_ok=True)
            with open(LOCK, "w") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)       # one storyboard job across both servers
                if not load(outdir, src, extra):
                    generate(src, outdir, norot, extra)
        except Exception as e:  # noqa: BLE001 - a bad file must not kill the worker
            print(f"storyboard failed for {src}: {e}", flush=True)
            try:
                _failed[outdir] = stamp(src, extra)
            except OSError:
                pass
        finally:
            with _cv:
                if _jobs.get(outdir) == "running":
                    del _jobs[outdir]


def _probe(src):
    """(duration, average keyframe gap in seconds) from the container; packets only, no decode."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", src],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    dur = float(out)
    pk = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "packet=flags", "-of", "csv=p=0", src],
                        capture_output=True, text=True, timeout=120).stdout
    nk = sum(1 for ln in pk.splitlines() if "K" in ln)
    return dur, (dur / nk if nk else 1e9)


def _ffmpeg(src, tmp, interval, norot, nokey, hw):
    vf = (f"fps=1/{interval:.4f},"
          f"scale={BOX}:{BOX}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
          f"showinfo,tile={COLS}x{ROWS}")
    cmd = ["nice", "-n", "15", "ffmpeg", "-hide_banner", "-nostats", "-y", "-threads", "1",
           *(["-hwaccel", "videotoolbox"] if hw else []),
           *(["-noautorotate"] if norot else []),
           *(["-skip_frame", "nokey"] if nokey else []),
           "-i", src, "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", vf,
           "-q:v", "5", "-threads", "1", os.path.join(tmp, "sheet-%03d.jpg")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    n = len(re.findall(r"Parsed_showinfo.*\sn:\s*\d+", r.stderr))
    return r.returncode == 0 and n > 0, n


def generate(src, outdir, noautorotate=False, extra=""):
    t0 = time.time()
    key = stamp(src, extra)
    dur, kgap = _probe(src)
    interval = max(1.0, round(dur / MAX_TILES, 2))
    nokey = kgap <= interval * 1.25           # every tile has its own keyframe: skip the rest
    tmp = outdir.rstrip("/") + f".tmp{os.getpid()}"
    ok = False
    for hw in (True, False):
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        ok, n = _ffmpeg(src, tmp, interval, noautorotate, nokey or not hw, hw)
        if ok:
            break
    if not ok:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("ffmpeg produced no frames")
    sheets = sorted(f for f in os.listdir(tmp) if f.startswith("sheet-"))
    wh = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                         "-of", "csv=p=0", os.path.join(tmp, sheets[0])],
                        capture_output=True, text=True, timeout=30).stdout.strip().split(",")
    idx = {"key": key, "interval": interval, "count": min(n, len(sheets) * COLS * ROWS),
           "cols": COLS, "rows": ROWS, "w": int(wh[0]) // COLS, "h": int(wh[1]) // ROWS,
           "sheets": sheets, "dur": round(dur, 3), "secs": round(time.time() - t0, 1),
           "nokey": nokey}
    with open(os.path.join(tmp, "index.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f)
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(os.path.dirname(outdir.rstrip("/")), exist_ok=True)
    os.replace(tmp, outdir)
    print(f"storyboard: {os.path.basename(src)} -> {n} tiles in {idx['secs']}s", flush=True)
    return idx


def prune(root, keep, max_keep=3):
    """Drop storyboards in `root` whose name isn't in `keep` (sources gone), keep the newest
    `max_keep` of the rest; never touches subfolders listed in `keep` or `raw`."""
    try:
        names = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and d != "raw"]
    except OSError:
        return
    alive = sorted((d for d in names if d in keep),
                   key=lambda d: os.path.getmtime(os.path.join(root, d)), reverse=True)
    for d in names:
        if d not in alive[:max_keep] and ".tmp" not in d:
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)


SHEET_RE = re.compile(r"sheet-\d{3}\.jpg")
