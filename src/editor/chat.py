"""Chat box on the review pages ("和 Agent 聊"): the creator types notes while watching, the agent answers in place.

Messages live in `02 - Export/edit/chat.jsonl` (one JSON per line), shared by both pages of a project.
Each creator message carries where he was: the raw clip + time (footage page) or the cut time (review page).

    python -m src.editor.chat "<project>" watch            # stream new creator messages, one line each (for Monitor);
                                                           # while it runs it keeps a heartbeat in edit/chat.listening
    python -m src.editor.chat "<project>" reply "text"     # post Claude's answer
    python -m src.editor.chat "<project>" tail [N]         # print the last N messages

Pages: register(app, get_project) adds GET/POST /api/chat and GET /api/chat/status; inject(page) adds the
widget before </body>. The widget shows 「Agent 在听」 while a `watch` heartbeat is fresh (< 8 s old).
A page sets `window.chatCtx = () => ({clip, clip_t} | {cut_t})` so messages carry the current position.

Fullscreen with the chat: a page marks the element to make fullscreen with `data-fsroot` (it holds the
video and the rail) and its rail with `data-fsrail`, and calls `cbFs.toggle()` for its fullscreen button / F
key. In fullscreen the root turns dark and gets class `fs` plus `fs-rail` (chat in a column on the right) or
`fs-float` (video full width, chat in a draggable translucent panel; `fs-min` = folded to a bubble with the
listening dot and an unread count). C switches rail/float; the choice and the panel position are remembered.
The page hides whatever else is inside its root under `.fs`; a `cbfs` window event fires on every change (for the
page's own fullscreen icon). `cbFs.sim(true)` fakes fullscreen for screenshots.
"""
from . import theme
import fcntl
import json
import os
import signal
import sys
import time

from . import edl as E


def path(project):
    return os.path.join(E.edit_dir(project), "chat.jsonl")


LISTEN_FRESH = 8.0   # s: a heartbeat older than this means nobody is listening


def heartbeat_path(project):
    return os.path.join(E.edit_dir(project), "chat.listening")


def beat(project, since):
    """Line 1: now (epoch s), line 2: when this watcher started. Written atomically."""
    p = heartbeat_path(project)
    with open(p + ".tmp", "w") as f:
        f.write(f"{time.time():.1f}\n{since:.1f}\n")
    os.replace(p + ".tmp", p)


def listening(project):
    try:
        with open(heartbeat_path(project)) as f:
            parts = f.read().split()
        last = float(parts[0])
        since = float(parts[1]) if len(parts) > 1 else None
    except (OSError, ValueError, IndexError):
        return {"listening": False, "since": None}
    live = time.time() - last < LISTEN_FRESH
    return {"listening": live, "since": since if live else None, "last": last}


def load(project):
    try:
        with open(path(project), encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return []


def post(project, role, text, ctx=None):
    p = path(project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        n = max([json.loads(l).get("id", 0) for l in f if l.strip()] or [0])  # max id, so deleted lines never cause reuse
        msg = {"id": n + 1, "role": role, "text": text.strip(), "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        if ctx:
            msg["ctx"] = ctx
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)
    return msg


def _set_react(project, msg_id, target):
    """Turn message msg_id into a reaction to `target` (rewrites that one line)."""
    p = path(project)
    with open(p, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        lines = f.read().splitlines()
        out = []
        for l in lines:
            if l.strip():
                m = json.loads(l)
                if m.get("id") == msg_id:
                    m["react_to"] = target
                l = json.dumps(m, ensure_ascii=False)
            out.append(l)
        f.seek(0); f.truncate(); f.write("\n".join(out) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def _where(ctx):
    if not ctx:
        return ""
    if ctx.get("clip"):
        return f"[原片 {ctx['clip']} @ {ctx.get('clip_t', 0):.1f}s] "
    if ctx.get("cut_t") is not None:
        t = ctx["cut_t"]
        return f"[成片 {int(t // 60)}:{t % 60:04.1f}] "
    return ""


def register(app, get_project):
    from flask import jsonify, request

    @app.get("/api/chat")
    def api_chat():
        after = request.args.get("after", type=int, default=0)
        return jsonify([m for m in load(get_project()) if m["id"] > after])

    @app.get("/api/chat/status")
    def api_chat_status():
        return jsonify(listening(get_project()))

    @app.post("/api/chat")
    def api_chat_post():
        body = request.get_json(silent=True) or {}
        text, ctx = body.get("text", ""), body.get("ctx") or {}
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            return jsonify({"ok": False}), 400
        page = body.get("page")
        if page in ("raw", "cut"):
            ctx["page"] = page
        return jsonify({"ok": True, "message": post(get_project(), "creator", text, ctx)})


WIDGET = r"""
<style>
/* Chat box. Docks into the page's #chatDock (a sidebar slot) when there is one, else floats bottom-right.
   Colours come from theme.py tokens, so it matches the page around it. */
#cb{display:flex;flex-direction:column;min-height:0;background:var(--surface);color:var(--text);
  font:15px/1.6 var(--font);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
#cb.float{position:fixed;right:16px;bottom:16px;width:340px;height:420px;max-width:calc(100vw - 32px);z-index:9999;box-shadow:var(--sh-2)}
#cb.docked{height:100%}
#cb.min{height:auto}
#cb.min #cbBody{display:none}
#cbHead{display:flex;align-items:center;gap:8px;padding:9px 8px 9px 12px;cursor:pointer;user-select:none;flex:none;
  border-bottom:1px solid var(--line)}
#cb.min #cbHead{border-bottom-color:transparent}
#cbHead .ic{width:22px;height:22px;border-radius:7px;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;flex:none}
#cbHead b{font-weight:600;font-size:14px}
#cbDot{width:7px;height:7px;border-radius:50%;background:var(--accent);display:none;margin-left:-2px}
#cbHead .sp{flex:1}
#cbStat{display:none;align-items:center;gap:5px;font-size:12px;font-weight:400;color:var(--text-3);padding:1px 8px 1px 7px;border-radius:999px;
  background:var(--surface-3);white-space:nowrap}
#cbStat.known{display:inline-flex}
#cbStat i{width:6px;height:6px;border-radius:50%;background:var(--faint);flex:none}
#cbStat.on{background:var(--ok-soft);color:var(--ok)}
#cbStat.on i{background:var(--used);box-shadow:0 0 0 3px rgba(34,197,94,.18)}
#cbHint.off{color:var(--text-2)}
#cbTog{border:0;background:transparent;color:var(--text-3);width:26px;height:26px;padding:0;border-radius:7px;display:grid;place-items:center}
#cbTog:hover{background:var(--surface-3);color:var(--text)}
#cbTog svg{transition:transform .15s}
#cb.min #cbTog svg{transform:rotate(180deg)}
#cbBody{display:flex;flex-direction:column;flex:1;min-height:0}
#cbList{flex:1;min-height:0;overflow-y:auto;padding:10px 12px 4px;background:var(--surface-2)}
#cbEmpty{color:var(--text-3);font-size:12px;text-align:center;padding:18px 8px}
.cbm{display:flex;flex-direction:column;margin:0 0 10px;max-width:90%;position:relative}
.cbm .react{align-self:flex-end;margin-top:-8px;margin-right:6px;font-size:13px;line-height:1;padding:3px 6px;border-radius:999px;background:var(--surface);border:1px solid var(--line);box-shadow:var(--sh-1)}
.cbm .bub{padding:7px 11px;border-radius:12px;white-space:pre-wrap;word-break:break-word}
.cbm.creator{margin-left:auto;align-items:flex-end}
.cbm.creator .bub{background:var(--accent-soft);color:#1b3a7a;border-bottom-right-radius:4px}
.cbm.claude .bub{background:var(--surface);border:1px solid var(--line);border-bottom-left-radius:4px}
.cbm .w{font-size:11px;color:var(--text-3);margin:0 4px 3px;font-variant-numeric:tabular-nums}
#cbForm{display:flex;gap:6px;align-items:flex-end;padding:8px 8px 4px;border-top:1px solid var(--line);flex:none}
#cbIn{flex:1;resize:none;min-height:36px;max-height:110px;border:1px solid var(--line-2);border-radius:var(--r-sm);
  padding:7px 10px;font:inherit;line-height:1.45;background:var(--surface);overflow-y:auto}
#cbSend{height:36px;padding:0 14px;flex:none}
#cbHint{font-size:11px;color:var(--text-3);padding:0 12px 7px;flex:none}
/* ---- fullscreen: video + chat (see module doc) */
.fsbar,#cbBubble{display:none}
[data-fsroot].fs{__DARK__}
[data-fsroot].fs{position:fixed;inset:0;z-index:1000;width:100vw;height:100vh;margin:0;padding:0;background:var(--stage);
  display:grid;grid-template-columns:minmax(0,1fr) clamp(320px,22vw,420px);gap:0;overflow:hidden}
[data-fsroot].fs [data-fsrail]{position:relative;top:auto;height:100vh;max-height:none;min-height:0;display:flex;flex-direction:column;gap:10px;
  padding:8px 12px 12px;background:#111418;border-left:1px solid #20252c;color:var(--text)}
[data-fsroot].fs #chatDock{flex:1 1 auto;min-height:160px;height:auto}
[data-fsroot].fs #chatDock.min{flex:none;min-height:0}
[data-fsroot].fs .cbm.creator .bub{color:#dbe7ff}
[data-fsroot].fs .fsbar{display:flex;align-items:center;gap:4px;height:30px;flex:none;color:var(--text-3);font-size:12px;user-select:none}
.fsbar .grip{display:none;width:18px;height:24px;place-items:center;color:var(--text-3);cursor:grab}
.fsbar .fst{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.fsbar .sp{flex:1}
.fsbar .fsb{border:0;background:transparent;color:var(--text-2);height:26px;padding:0 8px;font-size:12px;border-radius:7px;
  display:inline-flex;align-items:center;gap:5px;white-space:nowrap}
.fsbar .fsb:hover{background:var(--surface-3);color:var(--text)}
.fsbar .fsb kbd{font:500 10px/14px var(--font);padding:0 4px;margin:0;background:transparent;color:var(--text-3);border:1px solid rgba(255,255,255,.22);border-radius:4px}
.fsbar .fsb[data-a=min]{display:none}
/* float: the video gets the whole screen, the rail becomes a translucent panel */
[data-fsroot].fs.fs-float{grid-template-columns:minmax(0,1fr)}
[data-fsroot].fs.fs-float [data-fsrail]{position:absolute;right:var(--fsr,20px);bottom:var(--fsb,164px);width:var(--fsw,min(350px,calc(100vw - 32px)));
  height:var(--fsh,min(560px,calc(100vh - 200px)));padding:4px 10px 10px;z-index:20;border:1px solid rgba(255,255,255,.12);border-radius:14px;
  background:rgba(16,18,22,.66);-webkit-backdrop-filter:blur(18px) saturate(1.3);backdrop-filter:blur(18px) saturate(1.3);
  box-shadow:0 14px 44px rgba(0,0,0,.5);--surface:rgba(255,255,255,.05);--surface-2:rgba(0,0,0,.18);--line:rgba(255,255,255,.10)}
/* float panel: drag the left edge, top edge or top-left corner to resize */
.fsrz{display:none;position:absolute;z-index:3}
[data-fsroot].fs.fs-float .fsrz{display:block}
.fsrz.l{left:-5px;top:12px;bottom:12px;width:10px;cursor:ew-resize}
.fsrz.t{top:-5px;left:12px;right:12px;height:10px;cursor:ns-resize}
.fsrz.tl{left:-6px;top:-6px;width:16px;height:16px;cursor:nwse-resize}
[data-fsroot].fs.fs-float [data-fsrail] #cbForm textarea{background:rgba(0,0,0,.25)}
[data-fsroot].fs.fs-float #cbList{-webkit-mask-image:linear-gradient(to bottom,transparent,#000 22px);mask-image:linear-gradient(to bottom,transparent,#000 22px)}
[data-fsroot].fs.fs-float .fsbar{cursor:grab}
[data-fsroot].fs.fs-float .fsbar.drag{cursor:grabbing}
[data-fsroot].fs.fs-float .fsbar .grip{display:grid}
[data-fsroot].fs.fs-float .fsbar .fsb[data-a=min]{display:inline-flex}
[data-fsroot].fs.fs-min [data-fsrail]{display:none}
[data-fsroot].fs.fs-min #cbBubble{display:grid;place-items:center;position:absolute;right:var(--fsr,20px);bottom:var(--fsb,164px);z-index:20;
  width:52px;height:52px;padding:0;border-radius:50%;border:1px solid rgba(255,255,255,.16);color:#fff;cursor:pointer;
  background:rgba(16,18,22,.7);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);box-shadow:0 8px 24px rgba(0,0,0,.45)}
#cbBubble:hover{background:rgba(40,44,52,.85)}
#cbBubble .st{position:absolute;right:3px;bottom:3px;width:12px;height:12px;border-radius:50%;background:#6b7280;border:2px solid #15181c}
#cbBubble.on .st{background:var(--used)}
#cbBubble .badge{position:absolute;top:-4px;right:-4px;min-width:20px;height:20px;padding:0 5px;border-radius:999px;background:var(--accent);
  color:#fff;font:600 11px/20px var(--font);text-align:center;display:none}
#cbBubble.unread .badge{display:block}
#cbBubble.q{border-color:var(--q);box-shadow:0 0 0 3px rgba(245,158,11,.35),0 8px 24px rgba(0,0,0,.45)}
#cbQHint{display:none;position:absolute;top:16px;left:50%;transform:translateX(-50%);z-index:21;background:var(--q-soft);color:var(--q-ink);
  border:1px solid var(--q-line);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);background:rgba(40,28,4,.82);
  font-size:13px;font-weight:500;padding:5px 14px;border-radius:999px;pointer-events:none;white-space:nowrap}
[data-fsroot].fs.fs-min.fs-q #cbQHint{display:block}
#cbBubble.q::after{content:'?';position:absolute;top:-5px;left:-5px;width:20px;height:20px;border-radius:50%;background:var(--q);color:#1c1300;
  font:700 12px/20px var(--font);text-align:center}
</style>
<section id="cb" aria-label="和 Agent 聊">
 <div id="cbHead" title="收起 / 展开">
  <span class="ic"><svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M2.5 3.5h11v7.5H7l-3 2.5V11H2.5z"/></svg></span>
  <b>和 Agent 聊</b><span id="cbDot"></span><span id="cbStat"><i></i><span></span></span><span class="sp"></span>
  <button id="cbTog" type="button" tabindex="-1" aria-label="收起/展开"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 6l4 4 4-4"/></svg></button>
 </div>
 <div id="cbBody"><div id="cbList" class="scroll"><div id="cbEmpty">还没有消息。边看边写意见，Agent 会在这里回复。</div></div>
  <form id="cbForm"><textarea id="cbIn" rows="1" placeholder="边看边写意见…"></textarea><button id="cbSend" class="pri">发送</button></form>
  <div id="cbHint"></div></div>
</section>
<script>
(function(){
  const PAGE='__CHAT_PAGE__', box=document.getElementById('cb'), list=document.getElementById('cbList'),
        inp=document.getElementById('cbIn'), dot=document.getElementById('cbDot'), dock=document.getElementById('chatDock');
  if(dock){dock.appendChild(box);box.classList.add('docked')}else box.classList.add('float');
  const FS=fullscreenChat();
  let last=0, pinned=true;   // keep the thread scrolled to the newest message unless he scrolled up
  let userAt=0;               // only his own scrolling unpins (layout changes also fire scroll events)
  ['wheel','pointerdown','touchstart','keydown'].forEach(ev=>list.addEventListener(ev,()=>{userAt=Date.now()},{passive:true}));
  list.addEventListener('scroll',()=>{if(Date.now()-userAt<1500)pinned=list.scrollHeight-list.scrollTop-list.clientHeight<24},{passive:true});
  new ResizeObserver(()=>{if(pinned)list.scrollTop=list.scrollHeight}).observe(list);
  const setMin=m=>{box.classList.toggle('min',m);if(dock)dock.classList.toggle('min',m);if(!m){dot.style.display='none';list.scrollTop=list.scrollHeight}};
  try{if(localStorage.getItem('cb_min')==='1')setMin(true)}catch(e){}
  document.getElementById('cbHead').onclick=()=>{setMin(!box.classList.contains('min'));
    try{localStorage.setItem('cb_min',box.classList.contains('min')?'1':'0')}catch(e){}};
  const where=c=>!c?'':c.clip?`原片 ${c.clip} @ ${(+c.clip_t||0).toFixed(1)}s`:(c.cut_t!=null?`成片 ${Math.floor(c.cut_t/60)}:${(c.cut_t%60).toFixed(1).padStart(4,'0')}`:'');
  function add(m){const e=document.getElementById('cbEmpty');if(e)e.remove();
    if(m.react_to){const t=list.querySelector('[data-mid="'+m.react_to+'"]');
      if(t){let r=t.querySelector('.react');if(!r){r=document.createElement('span');r.className='react';t.appendChild(r)}r.textContent=m.text}return}
    const d=document.createElement('div');d.className='cbm '+m.role;d.dataset.mid=m.id;
    const w=document.createElement('span');w.className='w';w.textContent=(m.role==='claude'?'Agent':'我')+' · '+String(m.ts||'').slice(11,16)+(m.ctx&&where(m.ctx)?' · '+where(m.ctx):'');
    const b=document.createElement('div');b.className='bub';b.textContent=m.text;
    d.appendChild(w);d.appendChild(b);list.appendChild(d);if(pinned||m.role==='creator')list.scrollTop=list.scrollHeight;
    if(m.role==='claude'&&box.classList.contains('min'))dot.style.display='inline-block';
    if(m.role==='claude'&&loaded&&FS.hidden())FS.unread()}
  let loaded=false;   // the first poll is history, not news
  async function poll(){try{const r=await fetch('/api/chat?after='+last);const ms=await r.json();
    ms.forEach(m=>{if(m.id>last){add(m);last=m.id}});loaded=true}catch(e){}}
  // is the agent listening? (a `chat watch` heartbeat younger than 8 s)
  const st=document.getElementById('cbStat'), hint=document.getElementById('cbHint'),
        HINT='回车发送 · Shift+回车换行 · 自动带上当前视频位置', OFF='Agent 没在听 · 消息会保留，开了以后会看';
  function showStatus(on){FS.listening(on);st.classList.add('known');st.classList.toggle('on',on);
    st.lastChild.textContent=on?'Agent 在听':'Agent 没在听';st.title=on?'Agent 在听，发消息马上会看到':OFF;
    hint.textContent=on?HINT:OFF+' · 回车发送';hint.classList.toggle('off',!on)}
  hint.textContent=HINT;
  async function status(){try{const j=await (await fetch('/api/chat/status',{cache:'no-store'})).json();showStatus(!!j.listening)}catch(e){}}
  const grow=()=>{inp.style.height='auto';inp.style.height=Math.min(110,inp.scrollHeight+2)+'px'};
  async function send(){const t=inp.value.trim();if(!t)return;inp.value='';grow();
    let ctx={};try{ctx=(window.chatCtx&&window.chatCtx())||{}}catch(e){}
    await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t,ctx,page:PAGE})});poll()}
  document.getElementById('cbForm').onsubmit=e=>{e.preventDefault();send()};
  inp.addEventListener('input',grow);
  inp.addEventListener('keydown',e=>{e.stopPropagation();if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault();send()}
    else if(e.key==='Escape')inp.blur()});
  inp.addEventListener('keyup',e=>e.stopPropagation());
  poll();status();setInterval(()=>{poll();status()},2000);

  function fullscreenChat(){
    const root=document.querySelector('[data-fsroot]'), rail=root&&root.querySelector('[data-fsrail]');
    const noop={hidden:()=>false,unread(){},listening(){}};
    window.cbFs={toggle(){},sim(){},active:()=>false};
    if(!root||!rail)return noop;
    const ls=(k,v)=>{try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}};
    const S={on:false,mode:ls('cb_fs_mode')==='float'?'float':'rail',min:ls('cb_fs_min')==='1',n:0,pos:null};
    try{S.pos=JSON.parse(ls('cb_fs_pos')||'null')}catch(e){}
    const bar=document.createElement('div');bar.className='fsbar';
    bar.innerHTML='<span class="grip" title="拖动"><svg width="10" height="14" viewBox="0 0 10 14" fill="currentColor"><circle cx="2.5" cy="2.5" r="1.3"/><circle cx="7.5" cy="2.5" r="1.3"/><circle cx="2.5" cy="7" r="1.3"/><circle cx="7.5" cy="7" r="1.3"/><circle cx="2.5" cy="11.5" r="1.3"/><circle cx="7.5" cy="11.5" r="1.3"/></svg></span>'
      +'<span class="fst">全屏</span><span class="sp"></span>'
      +'<button type="button" class="fsb" data-a="mode"></button>'
      +'<button type="button" class="fsb" data-a="min" title="收成小气泡">收起</button>';
    rail.prepend(bar);
    const bub=document.createElement('button');bub.type='button';bub.id='cbBubble';bub.title='展开聊天（C）';
    bub.innerHTML='<svg width="22" height="22" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M2.5 3.5h11v7.5H7l-3 2.5V11H2.5z"/></svg><i class="st"></i><b class="badge"></b>';
    root.appendChild(bub);
    const qh=document.createElement('div');qh.id='cbQHint';qh.textContent='有个问题想问你 · 点右下角的气泡回答';root.appendChild(qh);
    const modeBtn=bar.querySelector('[data-a=mode]');
    function place(){   // keep the floating panel / bubble inside the screen
      if(!S.pos){root.style.removeProperty('--fsr');root.style.removeProperty('--fsb');return}
      const W=root.clientWidth||innerWidth,H=root.clientHeight||innerHeight,w=S.min?52:rail.offsetWidth||360,h=S.min?52:rail.offsetHeight||540;
      const r=Math.max(8,Math.min(W-w-8,S.pos.r)),b=Math.max(8,Math.min(H-h-8,S.pos.b));
      root.style.setProperty('--fsr',r+'px');root.style.setProperty('--fsb',b+'px')}
    function apply(){
      const fl=S.on&&S.mode==='float';
      root.classList.toggle('fs',S.on);root.classList.toggle('fs-rail',S.on&&!fl);root.classList.toggle('fs-float',fl);
      root.classList.toggle('fs-min',fl&&S.min);
      modeBtn.innerHTML=(S.mode==='float'?'放到右边':'悬浮')+' <kbd>C</kbd>';
      modeBtn.title=S.mode==='float'?'聊天放回右边一栏（C）':'视频铺满，聊天悬浮在画面上（C）';
      bar.querySelector('.fst').textContent=fl?'':'全屏 · 聊天';
      if(fl)requestAnimationFrame(place);
      if(!(fl&&S.min)){S.n=0;bub.classList.remove('unread')}
      window.dispatchEvent(new CustomEvent('cbfs',{detail:{on:S.on,mode:S.mode,min:S.min}}))}
    function setMode(m){S.mode=m;ls('cb_fs_mode',m);if(m==='rail'){S.min=false;ls('cb_fs_min','0')}apply()}
    function setMinF(m){S.min=m;ls('cb_fs_min',m?'1':'0');apply()}
    function toggle(){
      if(document.fullscreenElement){document.exitFullscreen().catch(()=>{});return}
      if(S.on){S.on=false;apply();return}   // simulated
      const rq=root.requestFullscreen||root.webkitRequestFullscreen;if(rq)Promise.resolve(rq.call(root)).catch(()=>{})}
    document.addEventListener('fullscreenchange',()=>{S.on=document.fullscreenElement===root;apply()});
    bar.addEventListener('click',e=>{const b=e.target.closest('.fsb');if(!b)return;const a=b.dataset.a;
      if(a==='mode')setMode(S.mode==='float'?'rail':'float');else if(a==='min')setMinF(true)});
    bub.onclick=()=>setMinF(false);
    // drag the floating panel by its top bar
    let drag=null;
    bar.addEventListener('pointerdown',e=>{if(!(S.on&&S.mode==='float')||e.target.closest('.fsb'))return;
      const rr=root.getBoundingClientRect(),pr=rail.getBoundingClientRect();
      drag={x:e.clientX,y:e.clientY,r:rr.right-pr.right,b:rr.bottom-pr.bottom};bar.setPointerCapture(e.pointerId);bar.classList.add('drag');e.preventDefault()});
    bar.addEventListener('pointermove',e=>{if(!drag)return;S.pos={r:drag.r-(e.clientX-drag.x),b:drag.b-(e.clientY-drag.y)};place()});
    const end=()=>{if(!drag)return;drag=null;bar.classList.remove('drag');ls('cb_fs_pos',JSON.stringify(S.pos))};
    bar.addEventListener('pointerup',end);bar.addEventListener('pointercancel',end);
    window.addEventListener('resize',()=>{if(S.on&&S.mode==='float')place()});
    // resize the floating panel: it is anchored bottom-right, so dragging the left/top edges grows it
    let rz=null;
    try{const z=JSON.parse(ls('cb_fs_size')||'null');if(z){root.style.setProperty('--fsw',z.w+'px');root.style.setProperty('--fsh',z.h+'px')}}catch(e){}
    ['l','t','tl'].forEach(d=>{const h=document.createElement('div');h.className='fsrz '+d;rail.appendChild(h);
      h.addEventListener('pointerdown',e=>{if(!(S.on&&S.mode==='float'))return;rz={d,x:e.clientX,y:e.clientY,w:rail.offsetWidth,h:rail.offsetHeight};
        h.setPointerCapture(e.pointerId);e.preventDefault();e.stopPropagation()});
      h.addEventListener('pointermove',e=>{if(!rz)return;const W=root.clientWidth,H=root.clientHeight;
        if(rz.d!=='t')root.style.setProperty('--fsw',Math.max(260,Math.min(W*0.7,rz.w-(e.clientX-rz.x)))+'px');
        if(rz.d!=='l')root.style.setProperty('--fsh',Math.max(220,Math.min(H-40,rz.h-(e.clientY-rz.y)))+'px')});
      const done=()=>{if(!rz)return;rz=null;ls('cb_fs_size',JSON.stringify({w:rail.offsetWidth,h:rail.offsetHeight}));place()};
      h.addEventListener('pointerup',done);h.addEventListener('pointercancel',done)});
    // C: rail <-> float (only in fullscreen, never while typing)
    document.addEventListener('keydown',e=>{
      if(!S.on||e.metaKey||e.ctrlKey||e.altKey||(e.key!=='c'&&e.key!=='C'))return;
      const t=e.target;if(t&&(/INPUT|SELECT|TEXTAREA/.test(t.tagName)||t.isContentEditable))return;
      e.preventDefault();e.stopPropagation();
      if(S.mode==='float'&&S.min)setMinF(false);else setMode(S.mode==='float'?'rail':'float')},true);
    // a question popping up while the chat is folded: mark the bubble
    setInterval(()=>{const q=!!rail.querySelector('.qa-card:not([hidden])');bub.classList.toggle('q',q);root.classList.toggle('fs-q',q)},400);
    window.cbFs={toggle,active:()=>S.on,sim(on){S.on=!!on;apply()},mode:m=>m?setMode(m):S.mode,fold:setMinF};
    apply();
    return {hidden:()=>S.on&&S.mode==='float'&&S.min,
      unread(){S.n++;const b=bub.querySelector('.badge');b.textContent=S.n>9?'9+':S.n;bub.classList.add('unread')},
      listening(on){bub.classList.toggle('on',on);bub.title=(on?'Agent 在听':'Agent 没在听')+' · 展开聊天（C）'}};
  }
})();
</script>
"""


def inject(page, kind):
    """kind: 'raw' (footage page) or 'cut' (review page)."""
    return page.replace("</body>", WIDGET.replace("__CHAT_PAGE__", kind).replace("__DARK__", theme.DARK) + "</body>", 1)


def watch(project):
    """Stream new creator messages; keep the heartbeat fresh while running, remove it on exit."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # run the finally on kill / Monitor stop
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))
    since = time.time()
    seen = len(load(project))
    try:
        while True:
            beat(project, since)
            ms = load(project)
            for m in ms[seen:]:
                if m["role"] == "creator":
                    print(f"CHAT #{m['id']} {_where(m.get('ctx'))}{m['text']}".replace("\n", " ⏎ "), flush=True)
            seen = len(ms)
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.remove(heartbeat_path(project))
        except OSError:
            pass


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    project, cmd = sys.argv[1], sys.argv[2]
    if cmd == "reply":
        print(post(project, "claude", " ".join(sys.argv[3:])))
    elif cmd == "react":  # react <id> [emoji]: a small badge on the creator's message, e.g. 👍 = received
        mid = int(sys.argv[3]); emoji = sys.argv[4] if len(sys.argv) > 4 else "👍"
        m = post(project, "claude", emoji)
        _set_react(project, m["id"], mid)
        print(m)
    elif cmd == "tail":
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        for m in load(project)[-n:]:
            print(f"#{m['id']} {m['role']} {m['ts']} {_where(m.get('ctx'))}{m['text']}")
    elif cmd == "watch":
        watch(project)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
