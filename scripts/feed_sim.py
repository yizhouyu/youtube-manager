#!/usr/bin/env python3
"""Feed simulator: put our candidate cover(s) + title(s) among real outlier videos, at feed size.

  scripts/feed_sim.py cover.jpg --title "标题"
  scripts/feed_sim.py A.jpg B.jpg --title "标题一" --title2 "标题二"   # every cover × title pair
Options: --outliers <outliers_*.json> (default: the latest from scripts/outlier_scan.py),
         --n 11 (real videos), --duration 9:41 (our badge; default: our channel's median length).

Writes sessions/growth/feed_sim.html (never the Desktop) and prints its path:
  - left: YouTube Home feed at phone width (cards 360 px wide, title 2 lines max with ellipsis);
  - right: "suggested video" sidebar rows with 168 px thumbnails.
Positions are shuffled on every load (button to reshuffle); ours stay unmarked until you press 「显示我们的」.
Real thumbnails are hot-linked from i.ytimg.com, nothing is downloaded. Our covers are embedded.
Rule (publish-video-chat Step 3): judge every cover at 360 px and 168 px before showing covers to the creator.
"""
import argparse
import base64
import datetime as dt
import glob
import html
import json
import mimetypes
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
GROWTH = os.path.join(ROOT, "sessions", "growth")
OUT = os.path.join(GROWTH, "feed_sim.html")


def latest_outliers():
    files = [f for f in glob.glob(os.path.join(GROWTH, "outliers_*.json"))]
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("channels"):
            return f, d
    sys.exit("no outliers_*.json with reference channels in sessions/growth — run scripts/outlier_scan.py first")


def views_zh(n):
    if n is None:
        return ""
    if n >= 100_000_000:
        return f"{n / 1e8:.1f}亿次观看".replace(".0亿", "亿")
    if n >= 10_000:
        return f"{n / 1e4:.1f}万次观看".replace(".0万", "万")
    return f"{n:,}次观看"


def age_zh(date):
    try:
        days = (dt.date.today() - dt.date.fromisoformat(date)).days
    except (TypeError, ValueError):
        return ""
    if days < 1:
        return "今天"
    if days < 7:
        return f"{days}天前"
    if days < 30:
        return f"{days // 7}周前"
    if days < 365:
        return f"{days // 30}个月前"
    return f"{days // 365}年前"


def dur(sec):
    if not sec:
        return ""
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def pick_real(data, n):
    """Round-robin over channels, most recent outliers first, so the feed is varied and current."""
    pools = []
    for ch in data["channels"]:
        outs = sorted((v for v in ch["videos"] if v.get("outlier")), key=lambda v: v.get("date") or "", reverse=True)
        if outs:
            pools.append([(ch, v) for v in outs])
    picked = []
    while len(picked) < n and any(pools):
        for p in pools:
            if p and len(picked) < n:
                picked.append(p.pop(0))
    return [{
        "ours": False,
        "thumb": v["thumb"],
        "title": v["title"],
        "channel": ch["name"].strip(),
        "avatar": ch.get("avatar"),
        "meta": " · ".join(x for x in (views_zh(v["views"]), age_zh(v.get("date"))) if x),
        "duration": dur(v.get("duration")),
    } for ch, v in picked]


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>首页模拟 · 封面在 feed 里</title>
__FAVICON__
<style>
:root{--bg:#fff;--fg:#0f0f0f;--sub:#606060;--chip:#f2f2f2;--chipfg:#0f0f0f;--line:#e5e5e5;--panel:#f9f9f9}
:root[data-theme="dark"]{--bg:#0f0f0f;--fg:#f1f1f1;--sub:#aaa;--chip:#272727;--chipfg:#f1f1f1;--line:#303030;--panel:#181818}
*{box-sizing:border-box}
body{margin:0;background:var(--panel);color:var(--fg);font-family:Roboto,"PingFang SC","Hiragino Sans GB","Noto Sans SC",Arial,sans-serif}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);background:var(--bg);position:sticky;top:0;z-index:2}
.bar b{font-size:15px;margin-right:8px}
.bar button{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--chip);color:var(--chipfg);border-radius:18px;padding:6px 12px;cursor:pointer}
.bar .hint{font-size:12px;color:var(--sub);flex-basis:100%}
.wrap{display:flex;flex-wrap:wrap;gap:32px;padding:16px;align-items:flex-start;justify-content:center}
.col h2{font-size:13px;font-weight:500;color:var(--sub);margin:0 0 8px}
.phone{width:360px;background:var(--bg);border:1px solid var(--line);border-radius:18px;overflow:hidden}
.chips{display:flex;gap:8px;padding:10px 12px;overflow:hidden}
.chips span{flex:none;font-size:13px;background:var(--chip);color:var(--chipfg);border-radius:8px;padding:5px 11px}
.chips span:first-child{background:var(--fg);color:var(--bg)}
.card{margin-bottom:20px}
.thumb{position:relative;width:360px;height:202px;background:#000;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.badge{position:absolute;right:8px;bottom:8px;background:rgba(0,0,0,.8);color:#fff;font-size:12px;font-weight:500;padding:1px 4px;border-radius:4px}
.info{display:flex;gap:12px;padding:12px 12px 0}
.av{flex:none;width:36px;height:36px;border-radius:50%;background:#888 center/cover;color:#fff;font-size:15px;display:flex;align-items:center;justify-content:center}
.txt{min-width:0}
.t{font-size:14px;line-height:20px;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word;margin:0}
.m{font-size:12px;line-height:18px;color:var(--sub);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.side{width:402px;max-width:100%;background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:12px}
.row{display:flex;gap:8px;margin-bottom:8px}
.row .thumb{width:168px;height:94px;flex:none;border-radius:8px}
.row .badge{right:4px;bottom:4px}
.row .t{font-size:14px;line-height:20px}
.row .m{white-space:normal;margin:0}
.ours-on .ours .thumb{outline:4px solid #ff0033;outline-offset:-4px}
.ours-on .ours .t{color:#ff0033}
@media (max-width:820px){.wrap{gap:20px;padding:12px 16px}}
</style></head>
<body>
<div class="bar"><b>首页模拟</b>
<button id="shuffle">重新洗牌</button><button id="reveal">显示我们的</button><button id="theme">深色 / 浅色</button>
<span class="hint">先别找我们的：扫 2 秒，哪张最先抓住眼睛？手机首页是 360 px 宽，右边相关视频是 168 px。周围是参考频道近期的 outlier（≥3× 自己中位数）。__SRC__</span></div>
<div class="wrap" id="root">
<div class="col"><h2>首页 · 手机宽度 360 px</h2><div class="phone"><div class="chips"><span>全部</span><span>旅行</span><span>Vlog</span><span>美国</span><span>自驾</span><span>美食</span></div><div id="feed"></div></div></div>
<div class="col"><h2>相关视频 · 168 px</h2><div class="side" id="side"></div></div>
</div>
<script>
const OURS = __OURS__, REAL = __REAL__, SIDE_N = __SIDE_N__;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const shuffle = a => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const av = v => v.avatar ? `<div class="av" style="background-image:url('${esc(v.avatar)}')"></div>` : `<div class="av">${esc((v.channel || "?")[0])}</div>`;
const thumb = v => `<div class="thumb"><img src="${esc(v.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer">${v.duration ? `<span class="badge">${esc(v.duration)}</span>` : ""}</div>`;
const card = v => `<div class="card${v.ours ? " ours" : ""}">${thumb(v)}<div class="info">${av(v)}<div class="txt"><p class="t">${esc(v.title)}</p><div class="m">${esc(v.channel)} · ${esc(v.meta)}</div></div></div></div>`;
const row = v => `<div class="row${v.ours ? " ours" : ""}">${thumb(v)}<div class="txt"><p class="t">${esc(v.title)}</p><div class="m">${esc(v.channel)}<br>${esc(v.meta)}</div></div></div>`;
function render() {
  document.getElementById("feed").innerHTML = shuffle(OURS.concat(REAL)).map(card).join("");
  document.getElementById("side").innerHTML = shuffle(OURS.concat(shuffle(REAL).slice(0, SIDE_N))).map(row).join("");
}
render();
document.getElementById("shuffle").onclick = render;
document.getElementById("reveal").onclick = () => document.getElementById("root").classList.toggle("ours-on");
document.getElementById("theme").onclick = () => { const r = document.documentElement; r.dataset.theme = r.dataset.theme === "dark" ? "light" : "dark"; };
if (matchMedia("(prefers-color-scheme: dark)").matches) document.documentElement.dataset.theme = "dark";
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("covers", nargs="+", help="our candidate cover image(s), 16:9")
    ap.add_argument("--title", action="append", default=[], help="our candidate title (repeatable)")
    ap.add_argument("--title2", action="append", default=[])
    ap.add_argument("--title3", action="append", default=[])
    ap.add_argument("--outliers", help="outliers_*.json from scripts/outlier_scan.py (default: latest)")
    ap.add_argument("--n", type=int, default=11, help="real outlier videos around ours (default 11)")
    ap.add_argument("--duration", help="duration badge on our card(s), e.g. 9:41")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    titles = a.title + a.title2 + a.title3
    if not titles:
        ap.error("give at least one --title")
    for c in a.covers:
        if not os.path.isfile(c):
            ap.error(f"cover not found: {c}")
    if a.outliers:
        src, data = a.outliers, json.load(open(a.outliers, encoding="utf-8"))
    else:
        src, data = latest_outliers()

    ours_ch = data.get("ours") or {}
    ours_vids = ours_ch.get("videos") or []
    duration = a.duration or (dur(statistics.median(v["duration"] for v in ours_vids if v.get("duration")))
                              if any(v.get("duration") for v in ours_vids) else "9:41")
    meta = " · ".join(x for x in (views_zh(int(ours_ch["median"])) if ours_ch.get("median") else "", "1天前") if x)
    uris = {c: data_uri(c) for c in a.covers}
    ours = [{"ours": True, "thumb": uris[c], "title": t, "channel": "Yizhou的一周",
             "avatar": ours_ch.get("avatar"), "meta": meta, "duration": duration}
            for c in a.covers for t in titles]
    real = pick_real(data, a.n)
    if len(real) < a.n:
        print(f"note: only {len(real)} outlier videos available", file=sys.stderr)

    try:
        from src.editor.favicon import link
        fav = link("thumb")
    except Exception:
        fav = ""
    js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
    page = (PAGE.replace("__FAVICON__", fav)
            .replace("__SRC__", html.escape(f" 数据：{os.path.basename(src)}（{data.get('date', '')}）。"))
            .replace("__OURS__", js(ours)).replace("__REAL__", js(real))
            .replace("__SIDE_N__", str(max(6, min(len(real), 9)))))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(page)
    print(os.path.abspath(a.out))


if __name__ == "__main__":
    main()
