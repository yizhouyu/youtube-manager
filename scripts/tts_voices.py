#!/usr/bin/env python3
"""Voice audition page: render the same line in several edge-tts voices and open a page to compare them.

    ./venv/bin/python scripts/tts_voices.py                          # default Chinese / English / French set
    ./venv/bin/python scripts/tts_voices.py --zh "前面是 Nassau Hall。" --out /tmp/voices
    ./venv/bin/python scripts/tts_voices.py --rate=-10% --no-open

edge-tts calls Microsoft's online Edge "Read Aloud" voices (free, no key, needs internet); the text
is sent to Microsoft. `--list` prints every available voice. Output: one mp3 per voice + index.html.
"""
import argparse
import html
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = os.path.join(REPO, "venv", "bin", "edge-tts")

ZH = "这里叫 Commons。直到 1969 年，来这儿吃饭都还得穿西装、打领带。"
EN = "This is Commons, Yale's great dining hall. Until 1969, students had to wear a jacket and tie to eat here."
FR = "Voici Commons, la grande salle à manger de Yale. Jusqu'en 1969, il fallait porter une veste et une cravate pour y manger."

# (group, voice, label, description); the text for each group comes from --zh/--en/--fr
VOICES = [
    ("zh", "zh-CN-YunxiNeural", "云希 Yunxi", "男 · 年轻、自然（频道当前旁白）"),
    ("zh", "zh-CN-YunjianNeural", "云健 Yunjian", "男 · 浑厚、解说感"),
    ("zh", "zh-CN-YunyangNeural", "云扬 Yunyang", "男 · 新闻播音腔"),
    ("zh", "zh-CN-YunxiaNeural", "云夏 Yunxia", "男 · 少年感"),
    ("zh", "zh-CN-XiaoxiaoNeural", "晓晓 Xiaoxiao", "女 · 温暖"),
    ("zh", "zh-CN-XiaoyiNeural", "晓伊 Xiaoyi", "女 · 活泼"),
    ("zh", "zh-TW-HsiaoChenNeural", "曉臻 HsiaoChen", "女 · 台湾口音"),
    ("zh", "zh-TW-YunJheNeural", "雲哲 YunJhe", "男 · 台湾口音"),
    ("zh", "en-US-AndrewMultilingualNeural", "Andrew（多语）读中文", "多语声音：英文名可能更准"),
    ("en", "en-US-AndrewMultilingualNeural", "Andrew", "美式 男 · 多语"),
    ("en", "en-US-BrianMultilingualNeural", "Brian", "美式 男 · 多语"),
    ("en", "en-US-AvaMultilingualNeural", "Ava", "美式 女 · 多语"),
    ("en", "en-US-EmmaMultilingualNeural", "Emma", "美式 女 · 多语"),
    ("en", "en-GB-SoniaNeural", "Sonia", "英式 女"),
    ("en", "en-GB-RyanNeural", "Ryan", "英式 男"),
    ("fr", "fr-FR-VivienneMultilingualNeural", "Vivienne", "法国 女 · 多语"),
    ("fr", "fr-FR-RemyMultilingualNeural", "Rémy", "法国 男 · 多语"),
    ("fr", "fr-FR-DeniseNeural", "Denise", "法国 女"),
    ("fr", "fr-FR-HenriNeural", "Henri", "法国 男"),
    ("fr", "fr-CA-SylvieNeural", "Sylvie", "加拿大法语 女"),
]
GROUPS = {"zh": "中文", "en": "English", "fr": "Français"}

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>旁白声音试听</title>
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#1f2328;--sub:#6b7280;--accent:#c2410c;--line:#e5e1d8}
@media (prefers-color-scheme: dark){:root{--bg:#16181d;--card:#20232a;--ink:#e8e6e1;--sub:#9aa0a8;--accent:#fb923c;--line:#30343c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,"PingFang SC",sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 16px 48px}h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 6px}
.lead,.foot{color:var(--sub)}.line{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:6px 0 12px}
.v{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:10px 0;display:grid;grid-template-columns:1fr auto;gap:6px 12px;align-items:center}
.v.cur{border-color:var(--accent)}.name{font-weight:600}.desc{color:var(--sub);font-size:14px}.id{color:var(--sub);font:12px ui-monospace,Menlo,monospace}
audio{grid-column:1/3;width:100%}button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:6px 12px;cursor:pointer}
</style></head><body><main>
<h1>旁白声音试听</h1>
<p class="lead">同一句话，不同声音。工具：edge-tts（微软 Edge「朗读」神经网络语音，免费，需联网）。语速 __RATE__。</p>
<p><button id="all">▶ 依次全部播放</button></p><div id="list"></div>
<p class="foot">重新生成：<code>./venv/bin/python scripts/tts_voices.py --zh "…" --rate=-5%</code></p>
</main><script>
const D=__DATA__, list=document.getElementById('list'), auds=[];
D.forEach(g=>{const h=document.createElement('h2');h.textContent=g.title;list.appendChild(h);
 const t=document.createElement('div');t.className='line';t.textContent='「'+g.text+'」';list.appendChild(t);
 g.items.forEach(([f,n,d,id])=>{const el=document.createElement('div');el.className='v';
  el.innerHTML=`<div><span class="name"></span><div class="desc"></div></div><span class="id"></span><audio controls preload="auto"></audio>`;
  el.querySelector('.name').textContent=n;el.querySelector('.desc').textContent=d;el.querySelector('.id').textContent=id;
  const a=el.querySelector('audio');a.src=f;list.appendChild(el);auds.push(a);
  a.addEventListener('play',()=>{auds.forEach(x=>{if(x!==a)x.pause()});document.querySelectorAll('.v').forEach(x=>x.classList.remove('cur'));el.classList.add('cur')});});});
document.getElementById('all').onclick=()=>{let i=0;const next=()=>{if(i>=auds.length)return;const a=auds[i++];a.currentTime=0;a.onended=()=>setTimeout(next,700);a.play()};next()};
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zh", default=ZH)
    ap.add_argument("--en", default=EN)
    ap.add_argument("--fr", default=FR)
    ap.add_argument("--rate", default="-5%")
    ap.add_argument("--langs", default="zh,en,fr", help="comma list of groups to render")
    ap.add_argument("--out", default=os.path.join(REPO, "sessions", "tts-voices"))
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--list", action="store_true", help="print all edge-tts voices and exit")
    a = ap.parse_args()
    if a.list:
        sys.exit(subprocess.call([EDGE, "--list-voices"]))
    texts = {"zh": a.zh, "en": a.en, "fr": a.fr}
    langs = [x for x in a.langs.split(",") if x in GROUPS]
    os.makedirs(a.out, exist_ok=True)
    data = []
    for g in langs:
        items = []
        for grp, voice, label, desc in VOICES:
            if grp != g:
                continue
            f = f"{g}-{voice}.mp3"
            r = subprocess.run([EDGE, "--voice", voice, f"--rate={a.rate}", "--text", texts[g],
                                "--write-media", os.path.join(a.out, f)], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"skip {voice}: {r.stderr.strip()[-200:]}", file=sys.stderr)
                continue
            items.append([f, label, desc, voice])
            print("ok", voice)
        data.append({"title": GROUPS[g], "text": texts[g], "items": items})
    page = PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace("__RATE__", html.escape(a.rate))
    out = os.path.join(a.out, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(out)
    if not a.no_open:
        subprocess.call(["open", out])


if __name__ == "__main__":
    main()
