#!/usr/bin/env python3
"""One-screen status board (≤ 25 lines, Chinese labels) — answers 「小弟在跑吗 / 进度？」 (retro 2026-11-08 #1).
Read-only: ps, lsof, file reads, `orca automations list --json`. No network, no API, never prints secrets.
Usage: venv/bin/python scripts/status.py   (plain python3 works too — stdlib only)
Sections: 重活 (render/ffmpeg/whisper/upload/biliup/chain jobs, episode + elapsed) · 上传链 (last meaningful line of
chain*/run_* logs touched in 24 h; "progress N%" → 上传中 N%) · 渲染队列 (scripts/render_lock.sh lock + wait dir) ·
审片服务器 (review ports 8700–8799 from scripts/review_open.sh) · STATE.md last 5 lines · Orca 自动化."""
import datetime as dt, glob, json, os, re, subprocess, time
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAINS = os.path.join(REPO, "sessions", "upload_chains")
LOCK, WAITDIR = "/tmp/yt-heavy-job.lock", "/tmp/yt-heavy-job.wait"  # keep in sync with scripts/render_lock.sh
W = 110  # max line width
HEAVY = [  # (label, regex on the full command line) — exact script names, never a generic "upload_" (SKILL gotcha 10/16)
    ("上传链", r"(?:^|/)(chain\d{3}[a-z]?\.sh|run_[\w-]+\.sh)\b"),
    ("YT上传长视频", r"upload_long\.py"),
    ("YT上传Shorts", r"upload_shorts\.py"),
    ("B站上传", r"upload_bili(?:_v2)?\.py|(?:^|/)biliup\s"),
    ("渲染", r"src\.editor\.render\b|(?:^|/)render(?:_variant|_thumbnails)?\.py|render_lock\.sh"),
    ("ffmpeg", r"(?:^|/)ffmpeg\s"),
    ("whisper", r"whisper|transcribe_accurate"),
]
SKIP_PROC = re.compile(r"--type=|crashpad|Google Drive|caffeinate|(?:^|/)(?:tail|grep|lsof|ps)\s|scripts/status\.py")


def sh(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def cut(s, n=W):
    lead = s[:len(s) - len(s.lstrip(" "))]
    s = lead + " ".join(s.split())
    return s if len(s) <= n else s[:n - 1] + "…"


def ep_of(s):
    m = re.search(r"ep(\d{3})pub|chain(\d{3})|/(\d{3}) - |run_(\d{3}(?:_\d{3})*)", s)
    return next((g for g in m.groups() if g), "").replace("_", "/") if m else ""


def secs(etime):  # ps etime: [[dd-]hh:]mm:ss
    d, _, rest = etime.strip().rpartition("-")
    parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return (int(d) if d else 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def dur(s):
    s = int(s)
    if s >= 86400:
        return f"{s // 86400}天{s % 86400 // 3600}时"
    if s >= 3600:
        return f"{s // 3600}时{s % 3600 // 60}分"
    return f"{s // 60}分{s % 60}秒" if s >= 60 else f"{s}秒"


def procs():
    out = []
    for line in sh(["ps", "axo", "pid=,etime=,command="]).splitlines():
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(.*)", line)
        if m:
            out.append((int(m.group(1)), secs(m.group(2)), m.group(3)))
    return out


def heavy(ps):
    seen = {}
    for pid, el, cmd in ps:
        if SKIP_PROC.search(cmd):
            continue
        for label, rx in HEAVY:
            m = re.search(rx, cmd)
            if m:
                name = m.group(1) if m.groups() and m.group(1) else label
                key = (label, name, ep_of(cmd))
                n, e = seen.get(key, (0, 0))
                seen[key] = (n + 1, max(e, el))
                break
    return [f"  {lab}{'' if name == lab else ' ' + name} · {('第' + ep + '期') if ep else '?期'} · 已跑 {dur(el)}{f' (×{n})' if n > 1 else ''}"
            for (lab, name, ep), (n, el) in sorted(seen.items(), key=lambda kv: -kv[1][1])]


WARN = re.compile(r"warn|Warning|^\s*$|^\s+warnings\.|NotOpenSSL|FutureWarning|DeprecationWarning", re.I)


def last_meaningful(path):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 65536))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return "读不了"
    for line in reversed(re.split(r"[\r\n]+", text)):
        if WARN.search(line):
            continue
        m = re.search(r"progress\s+(\d+(?:\.\d+)?)\s*%\s*(\S*)", line)
        if m:
            return f"上传中 {m.group(1)}%" + (f"（{m.group(2)}）" if m.group(2) else "")
        return line.strip()
    return "（空）"


def chain_logs():
    now = time.time()
    files = set(glob.glob(f"{CHAINS}/ep*/chain*.log") + glob.glob(f"{CHAINS}/ep*/run_*.log") + glob.glob(f"{CHAINS}/run_*.log"))
    recent = sorted((f for f in files if now - os.path.getmtime(f) < 86400), key=os.path.getmtime, reverse=True)
    rows = []
    for f in recent[:5]:
        rel = os.path.relpath(f, CHAINS)
        age = dur(now - os.path.getmtime(f)) + "前"
        rows.append(cut(f"  {rel} · {age} · {last_meaningful(f)}"))
    return rows or ["  24 小时内没有上传链日志"]


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def render_queue(ps):
    cmds = {pid: cmd for pid, _, cmd in ps}
    parts = []
    if os.path.isdir(LOCK):
        pid = open(f"{LOCK}/pid").read().strip() if os.path.exists(f"{LOCK}/pid") else ""
        what = open(f"{LOCK}/cmd").read().strip() if os.path.exists(f"{LOCK}/cmd") else "?"
        el = next((el for p, el, _ in ps if str(p) == pid), None)
        parts.append(f"运行中 {cut(what, 50)}" + (f" · 已跑 {dur(el)}" if el is not None else " · 进程已退出（残留锁）"))
    else:
        parts.append("空闲")
    waiting = []
    for f in sorted(glob.glob(f"{WAITDIR}/*")):
        prio, _, pid = os.path.basename(f).partition(".")
        if alive(pid):
            waiting.append(f"P{prio} {cut(cmds.get(int(pid), ''), 30)}")
    if waiting:
        parts.append(f"排队 {len(waiting)}: " + "; ".join(waiting))
    return cut("  " + " · ".join(parts))


def review_ports():
    try:
        src = open(os.path.join(REPO, "scripts", "review_open.sh"), encoding="utf-8").read()
        known = {int(p) for p in re.findall(r"\b(87\d\d)\b", src)}
    except OSError:
        known = set()
    listen = {}
    for line in sh(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"]).splitlines()[1:]:
        f = line.split()
        m = re.search(r":(\d+)$", f[8]) if len(f) > 8 else None
        if m and 8700 <= int(m.group(1)) <= 8799:  # review_open.sh also derives ports as 8700 + (ep % 50) * 2
            listen[int(m.group(1))] = f[1]
    rows = []
    for port in sorted(listen):
        cmd = sh(["ps", "-o", "command=", "-p", listen[port]]).strip()
        kind = "原片" if "footage_player" in cmd else "审片" if "review_server" in cmd else "其他"
        ep = ep_of(cmd)
        rows.append(f"{port} {kind}{(' ' + ep) if ep else ''}{'' if port in known or kind != '其他' else '?'}")
    return "  " + (" · ".join(rows) if rows else "都没开")


def state_tail():
    try:
        lines = [l for l in open(os.path.join(REPO, "sessions", "STATE.md"), encoding="utf-8").read().splitlines() if l.strip()]
    except OSError:
        return ["  读不到 STATE.md"]
    return [cut("  " + l.lstrip("- ")) for l in lines[-5:]]


def orca():
    out = sh(["orca", "automations", "list", "--json"], timeout=15)
    try:
        autos = json.loads(out)["result"]["automations"]
    except Exception:
        return ["  orca 读不到（没装或没开）"]
    rows = []
    for a in autos[:3]:
        nxt = a.get("nextRunAt")
        when = dt.datetime.fromtimestamp(nxt / 1000).strftime("%m-%d %H:%M") if nxt else "-"
        rows.append(cut(f"  {a.get('name', '?')} · {'开' if a.get('enabled') else '关'} · {a.get('agentId', '')} · 下次 {when}"))
    return rows or ["  没有自动化"]


def main():
    ps = procs()
    h = heavy(ps)
    out = [f"状态 {dt.datetime.now():%m-%d %H:%M}",
           f"【重活】{len(h)} 个" + ("" if h else " — 没有小弟在跑重活")] + h[:4]
    out += ["【上传链 · 24 小时内】"] + chain_logs()
    out += ["【渲染队列】", render_queue(ps), "【审片服务器】", review_ports()]
    out += ["【STATE.md 最后 5 行】"] + state_tail()
    out += ["【Orca 自动化】"] + orca()
    print("\n".join(out[:25]))


if __name__ == "__main__":
    main()
