"""Chat box on the review pages: the creator types notes while watching, Claude answers in place.

Messages live in `02 - Export/edit/chat.jsonl` (one JSON per line), shared by both pages of a project.
Each creator message carries where he was: the raw clip + time (footage page) or the cut time (review page).

    python -m src.editor.chat "<project>" watch            # stream new creator messages, one line each (for Monitor)
    python -m src.editor.chat "<project>" reply "text"     # post Claude's answer
    python -m src.editor.chat "<project>" tail [N]         # print the last N messages

Pages: register(app, get_project) adds GET/POST /api/chat; inject(page) adds the widget before </body>.
A page sets `window.chatCtx = () => ({clip, clip_t} | {cut_t})` so messages carry the current position.
"""
import fcntl
import json
import os
import sys
import time

from . import edl as E


def path(project):
    return os.path.join(E.edit_dir(project), "chat.jsonl")


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
        n = sum(1 for l in f if l.strip())
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
#cb{position:fixed;right:16px;bottom:16px;width:340px;max-width:calc(100vw - 32px);z-index:9999;
  font:13.5px/1.45 -apple-system,"PingFang SC",sans-serif;color:#1c2127;background:#fff;border:1px solid #d9dde3;
  border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.18);display:flex;flex-direction:column;overflow:hidden}
#cb.min #cbBody{display:none}
#cbHead{padding:8px 12px;background:#1f2937;color:#fff;cursor:pointer;display:flex;justify-content:space-between;align-items:center}
#cbHead b{font-weight:600}#cbDot{width:8px;height:8px;border-radius:50%;background:#f59e0b;display:none;margin-left:6px}
#cbList{height:300px;overflow-y:auto;padding:10px;background:#f7f8fa}
.cbm{margin:0 0 8px;max-width:88%;padding:7px 10px;border-radius:10px;white-space:pre-wrap;word-break:break-word}
.cbm.creator{margin-left:auto;background:#dbeafe}.cbm.claude{background:#fff;border:1px solid #e5e7eb}
.cbm .w{display:block;font-size:11px;color:#6b7280;margin-bottom:2px}
#cbForm{display:flex;gap:6px;padding:8px;border-top:1px solid #e5e7eb;background:#fff}
#cbIn{flex:1;resize:none;height:38px;border:1px solid #d1d5db;border-radius:8px;padding:6px 8px;font:inherit}
#cbSend{border:0;background:#2563eb;color:#fff;border-radius:8px;padding:0 12px;font:inherit;cursor:pointer}
#cbHint{font-size:11px;color:#6b7280;padding:0 10px 6px;background:#fff}
</style>
<div id="cb"><div id="cbHead"><span><b>和 Claude 聊</b><span id="cbDot"></span></span><span id="cbTog">—</span></div>
<div id="cbBody"><div id="cbList"></div>
<form id="cbForm"><textarea id="cbIn" placeholder="边看边写意见，回车发送（Shift+回车换行）"></textarea><button id="cbSend">发送</button></form>
<div id="cbHint">发送时会自动带上当前的视频位置</div></div></div>
<script>
(function(){
  const PAGE='__CHAT_PAGE__', box=document.getElementById('cb'), list=document.getElementById('cbList'),
        inp=document.getElementById('cbIn'), dot=document.getElementById('cbDot');
  let last=0;
  try{if(localStorage.getItem('cb_min')==='1')box.classList.add('min')}catch(e){}
  document.getElementById('cbHead').onclick=()=>{box.classList.toggle('min');dot.style.display='none';
    try{localStorage.setItem('cb_min',box.classList.contains('min')?'1':'0')}catch(e){}};
  const where=c=>!c?'':c.clip?`原片 ${c.clip} @ ${(+c.clip_t||0).toFixed(1)}s`:(c.cut_t!=null?`成片 ${Math.floor(c.cut_t/60)}:${(c.cut_t%60).toFixed(1).padStart(4,'0')}`:'');
  function add(m){const d=document.createElement('div');d.className='cbm '+m.role;
    const w=document.createElement('span');w.className='w';w.textContent=(m.role==='claude'?'Claude':'我')+' · '+m.ts.slice(11,16)+(m.ctx?' · '+where(m.ctx):'');
    d.appendChild(w);d.appendChild(document.createTextNode(m.text));list.appendChild(d);list.scrollTop=list.scrollHeight;
    if(m.role==='claude'&&box.classList.contains('min'))dot.style.display='inline-block'}
  async function poll(){try{const r=await fetch('/api/chat?after='+last);const ms=await r.json();
    ms.forEach(m=>{add(m);last=Math.max(last,m.id)})}catch(e){}}
  async function send(){const t=inp.value.trim();if(!t)return;inp.value='';
    let ctx={};try{ctx=(window.chatCtx&&window.chatCtx())||{}}catch(e){}
    await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t,ctx,page:PAGE})});poll()}
  document.getElementById('cbForm').onsubmit=e=>{e.preventDefault();send()};
  inp.addEventListener('keydown',e=>{e.stopPropagation();if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send()}});
  inp.addEventListener('keyup',e=>e.stopPropagation());
  poll();setInterval(poll,2000);
})();
</script>
"""


def inject(page, kind):
    """kind: 'raw' (footage page) or 'cut' (review page)."""
    return page.replace("</body>", WIDGET.replace("__CHAT_PAGE__", kind) + "</body>", 1)


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
        seen = len(load(project))
        while True:
            ms = load(project)
            for m in ms[seen:]:
                if m["role"] == "creator":
                    print(f"CHAT #{m['id']} {_where(m.get('ctx'))}{m['text']}".replace("\n", " ⏎ "), flush=True)
            seen = len(ms)
            time.sleep(2)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
