"""Clickable cover picker: one row per episode, click a thumbnail to choose it, "交给 Agent" submits.

    ./venv/bin/python scripts/cover_picker.py --root ~/Desktop --episodes 97-107 --out sessions/thumbs
Each episode's `02 - Export/thumbnail/editorial.html` lists its options. Picks go to <out>/picks.json, and the
submit button also writes <out>/picks.done and prints `PICKS_DONE {...}` (watch for it).
"""
import argparse, json, os, re, html, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
ap = argparse.ArgumentParser()
ap.add_argument("--root", default=os.path.expanduser("~/Desktop"))
ap.add_argument("--episodes", default="97-107", help="inclusive range a-b")
ap.add_argument("--out", default="sessions/thumbs")
ap.add_argument("--port", type=int, default=8771)
A = ap.parse_args()
D = os.path.abspath(A.root)
LO, HI = (int(x) for x in A.episodes.split("-"))
HERE = os.path.abspath(A.out)
os.makedirs(HERE, exist_ok=True)
PICKS = os.path.join(HERE, "picks.json")

def episodes():
    eps = sorted([d for d in os.listdir(D) if re.match(r'\d+ - ', d) and LO <= int(d.split()[0]) <= HI], key=lambda d: int(d.split()[0]))
    out = []
    for ep in eps:
        t = f"{D}/{ep}/02 - Export/thumbnail"
        hp = os.path.join(t, "editorial.html")
        srcs = re.findall(r'<figure class="c"><img src="([^"]+)"', open(hp).read()) if os.path.exists(hp) else []
        if ep.startswith("97"):
            srcs = ["G1_youtube.jpg", "A_youtube.jpg"]
        rec = "G1" if ep.startswith("97") else ""
        md = os.path.join(t, "THUMBNAILS.md")
        if not rec and os.path.exists(md):
            m = re.search(r'## Editorial redo \(2026-10-03\)(.*?)(\n## |\Z)', open(md).read(), re.S)
            r = re.search(r'(?:Recommended|Main|main|推荐)[^\n]*?(H\d)', m.group(1)) if m else None
            rec = r.group(1) if r else ""
        out.append((ep, t, srcs, rec))
    return out

def page():
    picks = json.load(open(PICKS)) if os.path.exists(PICKS) else {}
    secs = []
    for ep, t, srcs, rec in episodes():
        num = ep.split()[0]
        cur = picks.get(num, rec)
        cards = []
        for s in srcs:
            name = s.replace("_youtube.jpg", "").replace(".jpg", "")
            u = "/img?p=" + urllib.parse.quote(os.path.join(t, s))
            tag = "推荐" if name == rec else ("新风格" if name.startswith(("H", "G1")) else "原来的封面")
            cards.append(f'<figure class="c{" on" if name == cur else ""}" data-ep="{num}" data-name="{html.escape(name)}">'
                         f'<img src="{u}"><figcaption><b>{html.escape(name)}</b><span>{tag}</span><i>✓ 已选</i></figcaption>'
                         f'<div class="m"><img src="{u}" style="width:168px"><small>手机尺寸</small></div></figure>')
        secs.append(f'<section><h2>{html.escape(ep)}</h2><div class="g">{"".join(cards)}</div></section>')
    return f'''<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>选封面</title>
<style>:root{{--bg:#f6f4ef;--card:#fff;--ink:#1f2328;--sub:#6b7280;--line:#e5e1d8;--acc:#16a34a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181d;--card:#20232a;--ink:#e8e6e1;--sub:#9aa0a8;--line:#30343c;--acc:#4ade80}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,"PingFang SC",sans-serif}}main{{max-width:1500px;margin:0 auto;padding:24px 16px 90px}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:18px;margin:30px 0 10px}}p{{color:var(--sub);margin:0}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px}}
.c{{margin:0;background:var(--card);border:2px solid var(--line);border-radius:12px;padding:10px;cursor:pointer;transition:border-color .15s}}
.c:hover{{border-color:var(--sub)}}.c.on{{border:3px solid var(--acc)}}.c i{{display:none;margin-left:auto;color:var(--acc);font-style:normal;font-weight:600}}.c.on i{{display:inline}}
.c>img{{width:100%;border-radius:8px;display:block}}figcaption{{display:flex;gap:10px;align-items:baseline;margin:8px 2px 6px}}figcaption span{{color:var(--sub);font-size:14px}}
.m{{display:flex;gap:10px;align-items:flex-end}}.m img{{border-radius:6px}}.m small{{color:var(--sub)}}
#bar{{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;align-items:center;justify-content:center}}
#bar button{{font:inherit;padding:8px 18px;border-radius:8px;border:0;background:var(--acc);color:#fff;cursor:pointer}}#st{{color:var(--sub)}}
@media (max-width:480px){{.g{{grid-template-columns:1fr}}}}</style></head><body><main>
<h1>选封面</h1><p>点一张就选中（绿框）。默认选的是推荐的那张。选好后点下面的「交给 Agent」。</p>{"".join(secs)}</main>
<div id="bar"><span id="st">已自动保存</span><button id="go">交给 Agent</button></div>
<script>
async function save(done){{const picks={{}};document.querySelectorAll('.c.on').forEach(c=>picks[c.dataset.ep]=c.dataset.name);
 const r=await fetch('/pick',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{picks,done}})}});
 document.getElementById('st').textContent=r.ok?(done?'已交给 Agent ✓':'已自动保存'):'保存失败';}}
document.querySelectorAll('.c').forEach(c=>c.onclick=()=>{{document.querySelectorAll('.c[data-ep="'+c.dataset.ep+'"]').forEach(x=>x.classList.remove('on'));c.classList.add('on');save(false)}});
document.getElementById('go').onclick=()=>save(true);
</script></body></html>'''

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/img?p="):
            p = urllib.parse.unquote(self.path[7:])
            if not (p.startswith(D) and "/02 - Export/thumbnail/" in p and p.endswith(".jpg") and os.path.exists(p)):
                self.send_response(404); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.end_headers()
            self.wfile.write(open(p, "rb").read()); return
        b = page().encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        json.dump(body.get("picks", {}), open(PICKS, "w"), ensure_ascii=False, indent=1)
        if body.get("done"):
            open(os.path.join(HERE, "picks.done"), "w").write("1")
            print("PICKS_DONE " + json.dumps(body.get("picks"), ensure_ascii=False), flush=True)
        self.send_response(200); self.end_headers()

print(f"http://127.0.0.1:{A.port}/", flush=True)
HTTPServer(("127.0.0.1", A.port), H).serve_forever()
