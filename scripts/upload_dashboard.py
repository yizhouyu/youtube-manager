#!/usr/bin/env python3
"""Live upload progress page for the creator: ~/Desktop/上传进度.html (auto-refreshes every 5 s).

Reads only local state (chain logs + youtube_ids.json), never the API.
  scripts/upload_dashboard.py 120 121 122          # write once
  scripts/upload_dashboard.py 120 121 122 --loop   # rewrite every 5 s until every episode is done
"""
import glob
import html
import json
import os
import re
import sys
import time

DESK = os.path.expanduser("~/Desktop")
CHAINS = os.path.join(DESK, "youtube-manager/sessions/upload_chains")
OUT = os.path.join(DESK, "上传进度.html")

STEPS = [  # (ids key, label)
    ("long", "YouTube 长视频"),
    ("post_long", "字幕 + 英文标题"),
    ("shorts_done", "2 条 Shorts"),
    ("bili", "B站"),
    ("bili_season", "B站 合集"),
    ("verified", "最后核对"),
]


def project(ep):
    hits = glob.glob(os.path.join(DESK, f"{ep} - *"))
    return hits[0] if hits else None


def ids_of(proj):
    try:
        return json.load(open(os.path.join(proj, "02 - Export/edit/publish_prep/youtube_ids.json")))
    except (OSError, ValueError):
        return {}


def tail(path, n=40000):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - n))
            return f.read().decode("utf-8", "ignore")
    except OSError:
        return ""


def episode(ep):
    proj = project(ep)
    ids = ids_of(proj) if proj else {}
    log = tail(os.path.join(CHAINS, f"ep{ep}pub/chain{ep}.log"))
    done = {k: bool(ids.get(k)) for k, _ in STEPS}
    done["verified"] = "CHAIN DONE" in log
    # the step that is running now = the first one not done; its % comes from the newest progress line
    pct = None
    m = re.findall(r"progress (\d+)%", log)
    if m and not done["long"]:
        pct = int(m[-1])
    title = os.path.basename(proj) if proj else str(ep)
    last = [l for l in log.splitlines() if re.match(r"^20\d\d-\d\d-\d\d ", l)]
    return dict(ep=ep, title=title, done=done, pct=pct, last=(last[-1][11:] if last else "还没开始"),
                at=ids.get("long_at", ""), bv=ids.get("bili", ""), yt=ids.get("long", ""))


def render(eps):
    rows = []
    for e in eps:
        n = sum(e["done"][k] for k, _ in STEPS)
        overall = int(100 * n / len(STEPS))
        if e["pct"] is not None:
            overall = int(100 * (n + e["pct"] / 100) / len(STEPS))
        chips = []
        current = True
        for k, label in STEPS:
            if e["done"][k]:
                chips.append(f'<span class="chip ok">✓ {label}</span>')
            elif current:
                extra = f' {e["pct"]}%' if (k == "long" and e["pct"] is not None) else ""
                chips.append(f'<span class="chip now">… {label}{extra}</span>')
                current = False
            else:
                chips.append(f'<span class="chip">{label}</span>')
        meta = " · ".join(x for x in [
            f'YouTube {e["yt"]}' if e["yt"] else "", f'发布 {e["at"][:16].replace("T", " ")} UTC' if e["at"] else "",
            f'B站 {e["bv"]}' if e["bv"] else ""] if x)
        rows.append(f'''<section><h2>{html.escape(e["title"])}<span class="pc">{overall}%</span></h2>
<div class="bar"><div style="width:{overall}%"></div></div>
<div class="chips">{"".join(chips)}</div>
<p class="meta">{html.escape(meta)}</p><p class="last">最近一步：{html.escape(e["last"][:140])}</p></section>''')
    all_done = all(all(e["done"].values()) for e in eps)
    return f'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{"" if all_done else '<meta http-equiv="refresh" content="5">'}
<title>上传进度</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--mut:#6b7280;--ok:#16a34a;--now:#2563eb;--line:#e5e7eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111318;--card:#1a1d24;--ink:#e8eaf0;--mut:#9aa1ad;--line:#2a2f3a}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"PingFang SC",sans-serif;padding:24px 16px}}
main{{max-width:760px;margin:0 auto}} h1{{font-size:20px;margin:0 0 4px}} .sub{{color:var(--mut);margin:0 0 20px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}}
h2{{font-size:16px;margin:0 0 10px;display:flex;justify-content:space-between}} .pc{{color:var(--now)}}
.bar{{height:10px;background:var(--line);border-radius:6px;overflow:hidden}} .bar div{{height:100%;background:linear-gradient(90deg,#3b82f6,#22c55e);transition:width .6s}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 6px}} .chip{{font-size:13px;padding:2px 9px;border-radius:999px;border:1px solid var(--line);color:var(--mut)}}
.chip.ok{{color:var(--ok);border-color:var(--ok)}} .chip.now{{color:var(--now);border-color:var(--now);font-weight:600}}
.meta,.last{{margin:2px 0;color:var(--mut);font-size:13px}}
</style></head><body><main><h1>上传进度{" · 全部完成 ✓" if all_done else ""}</h1>
<p class="sub">更新于 {time.strftime("%m-%d %H:%M:%S")}{"" if all_done else " · 每 5 秒自动刷新"}</p>
{"".join(rows)}</main></body></html>'''


def main():
    eps = [a for a in sys.argv[1:] if a.isdigit()]
    while True:
        data = [episode(e) for e in eps]
        tmp = OUT + ".tmp"
        open(tmp, "w").write(render(data))
        os.replace(tmp, OUT)
        if "--loop" not in sys.argv or all(all(d["done"].values()) for d in data):
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
