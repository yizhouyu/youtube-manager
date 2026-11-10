"""Shorts page for the 「审片」 app: every rendered Short of a project, with its cover and hook text, plus the
same chat box as the other pages (notes carry `ctx = {short, short_t, page: "shorts"}`, 框选 works too).

Mounted on footage_player (`register(app, get_project)`), so it shares that server's chat thread:
    GET /shorts                  the page
    GET /api/shorts              [{name, hook, sub, cover}]
    GET /shorts/video/<name>     02 - Export/shorts/<name>.mp4
    GET /shorts/cover/<name>     02 - Export/shorts/<name>_cover.jpg
Specs (hook text + series label) come from `02 - Export/edit/shorts/<name>.json`. Read-only.
"""
import json
import os
import re

from flask import Response, abort, jsonify, send_file

from . import edl as E
from . import chat as CHAT
from . import theme as THEME
from . import appbridge as AB


def shorts_dir(project):
    return os.path.join(E.project_dir(project), "02 - Export", "shorts")


def list_shorts(project):
    d = shorts_dir(project)
    try:
        names = sorted(f[:-4] for f in os.listdir(d) if f.lower().endswith(".mp4") and not f.startswith("."))
    except OSError:
        return []
    out = []
    for n in names:
        spec = {}
        try:
            with open(os.path.join(E.edit_dir(project), "shorts", n + ".json"), encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError):
            pass
        hook = spec.get("hook") or {}
        out.append({"name": n, "hook": re.sub(r"[{}]", "", hook.get("text") or ""), "sub": hook.get("sub") or "",
                    "cover": os.path.isfile(os.path.join(d, n + "_cover.jpg"))})
    return out


def register(app, get_project):
    def known(name):
        if name not in {s["name"] for s in list_shorts(get_project())}:
            abort(404)

    @app.get("/shorts")
    def shorts_index():
        return Response(PAGE.replace("__TITLE__", os.path.basename(os.path.normpath(get_project()))), mimetype="text/html")

    @app.get("/api/shorts")
    def api_shorts():
        return jsonify(list_shorts(get_project()))

    @app.get("/shorts/video/<name>")
    def shorts_video(name):
        known(name)
        return send_file(os.path.join(shorts_dir(get_project()), name + ".mp4"), mimetype="video/mp4", conditional=True)

    @app.get("/shorts/cover/<name>")
    def shorts_cover(name):
        known(name)
        p = os.path.join(shorts_dir(get_project()), name + "_cover.jpg")
        if not os.path.isfile(p):
            abort(404)
        return send_file(p, mimetype="image/jpeg")


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · Shorts</title>
<style>
__THEME_CSS__
html,body{height:100%}
.app{display:flex;flex-direction:column;height:100vh}
.body{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) clamp(340px,28vw,460px)}
main{overflow:auto;padding:var(--sp-4);display:flex;gap:var(--sp-4);align-items:flex-start;flex-wrap:wrap;align-content:flex-start}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--sh-1);padding:var(--sp-3);
  display:flex;flex-direction:column;gap:var(--sp-2);width:min(100%,calc((100vh - 230px)*9/16 + 2*var(--sp-3)))}
.card.on{border-color:var(--accent-line);box-shadow:0 0 0 3px var(--accent-soft)}
.vw{position:relative;aspect-ratio:9/16;background:var(--stage);border-radius:var(--r);overflow:hidden}
.vw video{width:100%;height:100%;object-fit:contain;display:block}
.nm{display:flex;align-items:center;gap:var(--sp-2);font-size:13px;color:var(--text-3)}
.nm b{color:var(--text);font-weight:600;font-family:var(--mono);font-size:12px}
.hook{font-size:15px;font-weight:600;white-space:pre-line;line-height:1.4}
.sub{font-size:12px;color:var(--text-3)}
.cov{display:flex;gap:var(--sp-2);align-items:center;font-size:12px;color:var(--text-3)}
.cov img{width:54px;aspect-ratio:9/16;object-fit:cover;border-radius:var(--r-xs);background:var(--surface-3);cursor:zoom-in}
.empty{color:var(--text-3);padding:40px}
.rail{display:flex;flex-direction:column;padding:var(--sp-4) var(--sp-4) var(--sp-4) 0;min-height:0}
#chatDock{flex:1;min-height:0;overflow:hidden}
#chatDock #cb{border:0;border-radius:0}
#big{position:fixed;inset:0;background:rgba(10,14,20,.7);display:none;align-items:center;justify-content:center;z-index:50}
#big img{max-height:90vh;max-width:90vw;border-radius:var(--r)}
</style></head><body>
<div class="app">
<header class="hdr"><span class="kind">Shorts</span><span class="sep"></span><span class="pname">__TITLE__</span>
  <span class="meta" id="hmeta"></span><span class="sp"></span>
  <span class="meta"><kbd>空格</kbd> 播放 · <kbd>←</kbd><kbd>→</kbd> 5 秒 · <kbd>J</kbd><kbd>K</kbd><kbd>L</kbd> · <kbd>,</kbd><kbd>.</kbd> 逐帧 · <kbd>C</kbd> 写评论</span></header>
<div class="body">
<main id="list"><div class="empty">加载中…</div></main>
<aside class="rail"><div id="chatDock" class="panel"></div></aside>
</div></div>
<div id="big"></div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let shorts=[], act=null;   // act = the Short he is watching (its <video>); notes are pinned to it
function setAct(v){act=v;document.querySelectorAll('.card').forEach(c=>c.classList.toggle('on',c.contains(v)))}
function vid(name){return document.querySelector('.card[data-n="'+CSS.escape(name)+'"] video')}
(async()=>{
  shorts=await (await fetch('/api/shorts')).json();
  $('hmeta').innerHTML=`<b>${shorts.length}</b> 条`;
  if(!shorts.length){$('list').innerHTML='<div class="empty">这一期还没有 Shorts（02 - Export/shorts 里没有 mp4）</div>';return}
  $('list').innerHTML=shorts.map(s=>`<div class="card" data-n="${esc(s.name)}">
    <div class="vw"><video controls playsinline preload="metadata" src="/shorts/video/${encodeURIComponent(s.name)}"></video></div>
    <div class="nm"><b>${esc(s.name)}</b></div>
    ${s.hook?`<div class="hook">${esc(s.hook)}</div>`:''}${s.sub?`<div class="sub">${esc(s.sub)}</div>`:''}
    <div class="cov">${s.cover?`<img src="/shorts/cover/${encodeURIComponent(s.name)}" alt="">封面`:'还没有封面'}</div></div>`).join('');
  document.querySelectorAll('.card video').forEach(v=>{
    v.addEventListener('play',()=>{document.querySelectorAll('.card video').forEach(o=>{if(o!==v)o.pause()});setAct(v)});
    v.addEventListener('pointerdown',()=>setAct(v))});
  document.querySelectorAll('.cov img').forEach(im=>im.onclick=()=>{$('big').innerHTML=`<img src="${im.src}">`;$('big').style.display='flex'});
  $('big').onclick=()=>$('big').style.display='none';
  setAct(document.querySelector('.card video'));
})();
document.addEventListener('keydown',e=>{
  if(e.metaKey||e.ctrlKey||e.altKey||!act||/INPUT|SELECT|TEXTAREA/.test(e.target.tagName))return;
  if(e.key===' ')act.paused?act.play().catch(()=>{}):act.pause();
  else if(e.key==='ArrowLeft')act.currentTime=Math.max(0,act.currentTime-5);
  else if(e.key==='ArrowRight')act.currentTime=Math.min(act.duration||1e9,act.currentTime+5);
  else return;
  e.preventDefault();e.stopPropagation()},true);
document.addEventListener('mouseup',()=>{const a=document.activeElement;if(a&&(a.tagName==='BUTTON'||a.tagName==='VIDEO'))a.blur()});
window.chatCtx=()=>{const c=act&&act.closest('.card');return c?{short:c.dataset.n,short_t:Math.round((act.currentTime||0)*10)/10}:{}};
window.chatVideo=()=>act;
window.chatSeek=async m=>{const c=m.ctx||{};const v=c.short&&vid(c.short);if(!v)return null;
  setAct(v);v.currentTime=Math.max(0,(+c.short_t||0)-1);v.play().catch(()=>{});return {label:'Short '+c.short+' @ '+(+c.short_t||0).toFixed(1)+'s'}};
window.appHooks={kind:'shorts',video:()=>act,rate:()=>act?act.playbackRate:1,setRate:r=>{if(act)act.playbackRate=r},here:()=>({}),seek:()=>{}};
</script></body></html>
"""
PAGE = AB.inject(CHAT.inject(PAGE.replace("__THEME_CSS__", THEME.CSS), "shorts"))
