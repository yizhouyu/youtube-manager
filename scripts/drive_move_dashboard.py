#!/usr/bin/env python3
"""Live progress page for moving finished projects to the external drive: ~/Desktop/搬硬盘进度.html.

  scripts/drive_move_dashboard.py "117 - Big Island & Manta Rays" "118 - Na Pali Coast" ... [--loop]
Copied = bytes already on the drive / project size (measured once at start). Done = local folder gone + drive copy present.
"""
import html
import os
import sys
import time

DESK = os.path.expanduser("~/Desktop")
DRIVE = "/Volumes/YZY's drive/YouTube Channel"
OUT = os.path.join(DESK, "搬硬盘进度.html")


def size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            if f.startswith("._") or f == ".DS_Store":
                continue
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    totals = {n: size(os.path.join(DESK, n)) or size(os.path.join(DRIVE, n)) for n in names}
    while True:
        cards, finished = [], 0
        for n in names:
            local, dst = os.path.join(DESK, n), os.path.join(DRIVE, n)
            got = size(dst) if os.path.isdir(dst) else 0
            if not os.path.isdir(local) and os.path.isdir(dst):
                pct, state = 100, "✓ 已搬完，核对通过，电脑上的副本已删除"
                finished += 1
            elif got == 0:
                pct, state = 0, "排队中"
            elif got >= totals[n]:
                pct, state = 99, "拷贝完成，正在核对文件数、大小和母带校验值…"
            else:
                pct, state = int(100 * got / max(totals[n], 1)), "拷贝中"
            cards.append(f'<section><h2>{html.escape(n)}<span>{pct}%</span></h2>'
                         f'<div class="bar"><div style="width:{pct}%"></div></div>'
                         f'<p>{state} · {got / 1e9:.1f} / {totals[n] / 1e9:.1f} GB</p></section>')
        done = finished == len(names)
        page = f'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{"" if done else '<meta http-equiv="refresh" content="5">'}
<title>搬硬盘进度</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--mut:#6b7280;--line:#e5e7eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111318;--card:#1a1d24;--ink:#e8eaf0;--mut:#9aa1ad;--line:#2a2f3a}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"PingFang SC",sans-serif;padding:24px 16px}}
main{{max-width:760px;margin:0 auto}} h1{{font-size:20px;margin:0 0 4px}} .sub{{color:var(--mut);margin:0 0 20px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}}
h2{{font-size:16px;margin:0 0 10px;display:flex;justify-content:space-between}} p{{margin:8px 0 0;color:var(--mut);font-size:13px}}
.bar{{height:10px;background:var(--line);border-radius:6px;overflow:hidden}} .bar div{{height:100%;background:linear-gradient(90deg,#f59e0b,#22c55e)}}
</style></head><body><main><h1>搬到移动硬盘{" · 全部完成，可以拔硬盘 ✓" if done else ""}</h1>
<p class="sub">更新于 {time.strftime("%m-%d %H:%M:%S")}{"" if done else " · 每 5 秒自动刷新 · 搬完之前别拔硬盘"}</p>{"".join(cards)}</main></body></html>'''
        open(OUT + ".tmp", "w").write(page)
        os.replace(OUT + ".tmp", OUT)
        if done or "--loop" not in sys.argv:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
