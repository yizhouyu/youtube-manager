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
"""
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
  font:14px/1.55 var(--font);border:1px solid var(--line);border-radius:var(--r);overflow:hidden}
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
.cbm{display:flex;flex-direction:column;margin:0 0 10px;max-width:90%}
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
    const d=document.createElement('div');d.className='cbm '+m.role;
    const w=document.createElement('span');w.className='w';w.textContent=(m.role==='claude'?'Agent':'我')+' · '+String(m.ts||'').slice(11,16)+(m.ctx&&where(m.ctx)?' · '+where(m.ctx):'');
    const b=document.createElement('div');b.className='bub';b.textContent=m.text;
    d.appendChild(w);d.appendChild(b);list.appendChild(d);if(pinned||m.role==='creator')list.scrollTop=list.scrollHeight;
    if(m.role==='claude'&&box.classList.contains('min'))dot.style.display='inline-block'}
  async function poll(){try{const r=await fetch('/api/chat?after='+last);const ms=await r.json();
    ms.forEach(m=>{if(m.id>last){add(m);last=m.id}})}catch(e){}}
  // is the agent listening? (a `chat watch` heartbeat younger than 8 s)
  const st=document.getElementById('cbStat'), hint=document.getElementById('cbHint'),
        HINT='回车发送 · Shift+回车换行 · 自动带上当前视频位置', OFF='Agent 没在听 · 消息会保留，开了以后会看';
  function showStatus(on){st.classList.add('known');st.classList.toggle('on',on);
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
})();
</script>
"""


def inject(page, kind):
    """kind: 'raw' (footage page) or 'cut' (review page)."""
    return page.replace("</body>", WIDGET.replace("__CHAT_PAGE__", kind) + "</body>", 1)


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
