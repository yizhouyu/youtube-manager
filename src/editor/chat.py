"""Chat box on the review pages ("和 Agent 聊"): the creator types notes while watching, the agent answers in place.

Messages live in `02 - Export/edit/chat.jsonl` (one JSON per line), shared by both pages of a project.
Each creator message carries where he was: the raw clip + time (footage page) or the cut time (review page).

Two ways to send (creator, 2026-10-02: he likes to batch notes while watching):
  「评论」 (Shift+Enter)      -> stored with `status: "pending"`; shown as 「待交给 Agent」; does NOT wake the agent.
  「交给 Agent」 (Enter)      -> the typed note (if any) plus every pending note become `status: "sent"` with one
                                 `batch` number (max+1); the watcher announces them together.
Messages without `status` (older ones, Agent replies, posts from an old page) count as sent.

    python -m src.editor.chat "<project>" watch            # stream handed-over creator messages (for Monitor):
                                                           #   CHAT #5 [where] text                 (one message)
                                                           #   CHAT BATCH b3 (3 条): #5 [..] a ‖ #6 [..] b ‖ ...
                                                           # pending notes print nothing until handed over;
                                                           # while it runs it keeps a heartbeat in edit/chat.listening
    python -m src.editor.chat "<project>" reply "text"     # post Claude's answer
    python -m src.editor.chat "<project>" tail [N]         # print the last N messages

Pages: register(app, get_project) adds GET/POST /api/chat and GET /api/chat/status; inject(page) adds the
widget before </body>. The widget shows 「Agent 在听」 while a `watch` heartbeat is fresh (< 8 s old).
POST /api/chat takes `mode`: "comment" (pending), "handoff" (text optional; hands over all pending), or none
(an old page: sent at once). /api/chat/status also lists the `pending` ids, so a page sees notes handed over
from the other page turn ✓.
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


PENDING, SENT = "pending", "sent"


def status(m):
    """'pending' = a 评论 not handed over yet; anything else (incl. messages without the field) = 'sent'."""
    return PENDING if m.get("status") == PENDING else SENT


def load(project):
    try:
        with open(path(project), encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)   # never read half of a rewrite (handoff / react)
            return [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return []


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _new(ms, role, text, ctx=None, st=None):
    # max id + 1, so deleted lines never cause reuse
    msg = {"id": max([m.get("id", 0) for m in ms] or [0]) + 1, "role": role, "text": text.strip(), "ts": _now()}
    if ctx:
        msg["ctx"] = ctx
    if st:
        msg["status"] = st
    if role == "claude":  # which agent wrote it (more than one session can reach a project's chat)
        msg["by"] = os.environ.get("CHAT_SENDER") or f"pid {os.getppid()} · {os.path.basename(os.getcwd())}"
    return msg


def post(project, role, text, ctx=None, status=None):
    """Append one message. status=PENDING for a 「评论」 draft; None = sent (Agent replies, old pages)."""
    p = path(project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        msg = _new([json.loads(l) for l in f if l.strip()], role, text, ctx, status)
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)
    return msg


def _rewrite(project, fn):
    """Locked read-modify-write of the whole file. fn(msgs) edits the list in place and returns
    (changed, result); the file is rewritten only when changed."""
    p = path(project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        ms = [json.loads(l) for l in f if l.strip()]
        changed, res = fn(ms)
        if changed:
            f.seek(0); f.truncate()
            f.write("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in ms))
            f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
    return res


def _set_react(project, msg_id, target):
    """Turn message msg_id into a reaction to `target` (rewrites that one line)."""
    def fn(ms):
        for m in ms:
            if m.get("id") == msg_id:
                m["react_to"] = target
        return True, None
    _rewrite(project, fn)


def pending_ids(ms):
    return [m["id"] for m in ms if m.get("role") == "creator" and status(m) == PENDING]


def handoff(project, text="", ctx=None):
    """「交给 Agent」: every pending creator note, plus `text` as a new note if given, becomes one batch.
    Returns {"batch": n | None, "ids": [...], "count": k, "message": the new note | None}."""
    text = (text or "").strip()

    def fn(ms):
        ids = pending_ids(ms)
        if not ids and not text:
            return False, {"batch": None, "ids": [], "count": 0, "message": None}
        b = max([m["batch"] for m in ms if isinstance(m.get("batch"), int)] or [0]) + 1
        ts = _now()
        for m in ms:
            if m["id"] in ids:
                m.update(status=SENT, batch=b, sent_ts=ts)
        new = None
        if text:
            new = _new(ms, "creator", text, ctx, SENT)
            new["batch"] = b
            ms.append(new)
            ids.append(new["id"])
        return True, {"batch": b, "ids": ids, "count": len(ids), "message": new}
    return _rewrite(project, fn)


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
        project = get_project()
        return jsonify(dict(listening(project), pending=pending_ids(load(project))))

    @app.post("/api/chat")
    def api_chat_post():
        body = request.get_json(silent=True) or {}
        text, ctx, mode = body.get("text") or "", body.get("ctx") or {}, body.get("mode")
        if not isinstance(text, str) or len(text) > 4000 or not isinstance(ctx, dict):
            return jsonify({"ok": False}), 400
        page = body.get("page")
        if page in ("raw", "cut"):
            ctx["page"] = page
        if mode == "handoff":   # text optional: hand over whatever is pending
            return jsonify(dict(handoff(get_project(), text, ctx), ok=True))
        if not text.strip():
            return jsonify({"ok": False}), 400
        st = PENDING if mode == "comment" else None   # no mode = an old page: sent at once
        return jsonify({"ok": True, "message": post(get_project(), "creator", text, ctx, st)})


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
.cbm .w{font-size:11px;color:var(--text-3);margin:0 4px 3px;font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:5px;flex-wrap:wrap}
/* 「评论」 drafts wait for 「交给 Agent」: dashed bubble + a calm amber pill; handed-over notes get a small ✓ */
.cbm .w .pend{font-size:10.5px;line-height:16px;padding:0 7px;border-radius:999px;background:var(--q-soft);color:var(--q-ink);white-space:nowrap}
.cbm .w .sent{color:var(--ok);font-size:11px;line-height:1}
.cbm.pending .bub{background:transparent;border:1px dashed var(--accent-line)}
#cbForm{display:flex;flex-direction:column;gap:6px;padding:8px 8px 6px;border-top:1px solid var(--line);flex:none}
#cbIn{width:100%;resize:none;min-height:36px;max-height:110px;border:1px solid var(--line-2);border-radius:var(--r-sm);
  padding:7px 10px;font:inherit;line-height:1.45;background:var(--surface);overflow-y:auto}
#cbRow{display:flex;align-items:center;gap:6px}
#cbKeys{flex:1;min-width:0;font-size:11px;line-height:1.35;color:var(--text-3)}
#cbKeys b{font-weight:500;color:var(--text-2)}
#cbKeys span{white-space:nowrap}
#cbKeys.flash{color:var(--ok);font-weight:500}
#cbNote,#cbSend{height:30px;padding:0 12px;flex:none;white-space:nowrap;display:inline-flex;align-items:center;gap:6px}
#cbSend .n{display:none;min-width:18px;height:18px;padding:0 5px;border-radius:999px;background:rgba(255,255,255,.24);
  font:600 11px/18px var(--font);text-align:center;font-variant-numeric:tabular-nums}
#cbSend.has .n{display:inline-block}
#cbHint{font-size:11px;color:var(--text-3);padding:0 12px 7px;flex:none}
#cbHint:empty{display:none}
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
  <form id="cbForm"><textarea id="cbIn" rows="1" placeholder="边看边写意见…（自动带上当前位置）"></textarea>
   <div id="cbRow"><span id="cbKeys"></span>
    <button id="cbNote" type="button" title="先存着，不叫 Agent（Shift+回车）">评论</button>
    <button id="cbSend" type="submit" class="pri" title="连同待交的评论一起交给 Agent">交给 Agent<span class="n"></span></button></div></form>
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
    const w=document.createElement('span');w.className='w';
    const wt=document.createElement('span');wt.textContent=(m.id?'#'+m.id+' · ':'')+(m.role==='claude'?'Agent':'我')+' · '+String(m.ts||'').slice(11,16)+(m.ctx&&where(m.ctx)?' · '+where(m.ctx):'');w.appendChild(wt);
    const b=document.createElement('div');b.className='bub';b.textContent=m.text;
    d.appendChild(w);d.appendChild(b);list.appendChild(d);
    if(m.role==='creator'){if(m.status==='pending'){d.classList.add('pending');const p=document.createElement('span');p.className='pend';p.textContent='待交给 Agent';w.appendChild(p);pend.add(m.id)}
      else markSent(d)}   // no status (older messages) = sent
    if(pinned||m.role==='creator')list.scrollTop=list.scrollHeight;
    if(m.role==='claude'&&box.classList.contains('min'))dot.style.display='inline-block';
    if(m.role==='claude'&&loaded&&FS.hidden())FS.unread()}
  let loaded=false;   // the first poll is history, not news
  const pend=new Set(), sendBtn=document.getElementById('cbSend');
  function markSent(d){d.classList.remove('pending');const p=d.querySelector('.w .pend');if(p)p.remove();
    if(!d.querySelector('.w .sent')){const s=document.createElement('span');s.className='sent';s.textContent='✓';s.title='已交给 Agent';d.querySelector('.w').appendChild(s)}}
  function setSent(id){pend.delete(id);const d=list.querySelector('.cbm.creator[data-mid="'+id+'"]');if(d)markSent(d)}
  function count(){const n=pend.size;sendBtn.classList.toggle('has',n>0);sendBtn.querySelector('.n').textContent=n;
    sendBtn.title=n?`连同 ${n} 条待交的评论一起交给 Agent（回车）`:`交给 Agent（回车）`}
  async function poll(){try{const r=await fetch('/api/chat?after='+last);const ms=await r.json();
    ms.forEach(m=>{if(m.id>last){add(m);last=m.id}});count();loaded=true}catch(e){}}
  // is the agent listening? (a `chat watch` heartbeat younger than 8 s)
  const st=document.getElementById('cbStat'), hint=document.getElementById('cbHint'),
        OFF='Agent 没在听 · 消息会保留，开了以后会看';
  let flashT=0;
  function showStatus(on){FS.listening(on);st.classList.add('known');st.classList.toggle('on',on);
    st.lastChild.textContent=on?'Agent 在听':'Agent 没在听';st.title=on?'Agent 在听，交给它的消息马上会看到':OFF;
    hint.textContent=on?'':OFF;hint.classList.toggle('off',!on)}
  async function status(){try{const j=await (await fetch('/api/chat/status',{cache:'no-store'})).json();showStatus(!!j.listening);
    if(Array.isArray(j.pending)){const sp=new Set(j.pending);[...pend].forEach(id=>{if(!sp.has(id))setSent(id)});count()}}catch(e){}}  // handed over elsewhere (the other page)
  const MOD=/Mac|iPhone|iPad/.test(navigator.platform)?'⌘':'Ctrl+', keys=document.getElementById('cbKeys'),
        KEYS=`<span><b>回车</b> 交给 Agent ·</span> <span><b>Shift+回车</b> 评论</span>`;
  function flash(t){keys.textContent=t;keys.classList.add('flash');const my=flashT=Date.now();   // the confirmation sits where the key hint was
    setTimeout(()=>{if(flashT===my){keys.innerHTML=KEYS;keys.classList.remove('flash')}},3500)}
  keys.innerHTML=KEYS;
  keys.title='评论：先存着，不叫 Agent；交给 Agent：连同所有待交的评论一起交过去。Option+回车换行，自动带上当前视频位置。';
  const grow=()=>{inp.style.height='auto';inp.style.height=Math.min(110,inp.scrollHeight+2)+'px'};
  const ctxNow=()=>{try{return (window.chatCtx&&window.chatCtx())||{}}catch(e){return {}}};
  let busy=false;
  async function postChat(mode){if(busy)return;const t=inp.value.trim();
    if(mode==='comment'&&!t)return;
    if(mode==='handoff'&&!t&&!pend.size){flash('没有待交的评论');return}
    busy=true;inp.value='';grow();
    try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t,ctx:ctxNow(),page:PAGE,mode})});
      const j=await r.json();if(!r.ok||!j.ok)throw 0;
      if(mode==='handoff'){(j.ids||[]).forEach(setSent);flash(`已交给 Agent（${j.count} 条）`)}
    }catch(e){if(!inp.value)inp.value=t;grow();flash('没发出去，再试一次')}
    busy=false;await poll()}
  document.getElementById('cbForm').onsubmit=e=>{e.preventDefault();postChat('handoff')};
  document.getElementById('cbNote').onclick=()=>postChat('comment');
  [sendBtn,document.getElementById('cbNote')].forEach(b=>b.addEventListener('mousedown',e=>e.preventDefault()));  // keep focus in the box, so Space never re-presses a button
  inp.addEventListener('input',grow);
  inp.addEventListener('keydown',e=>{e.stopPropagation();
    if(e.key==='Enter'&&!e.isComposing&&e.keyCode!==229){
      if(e.altKey)return;  // Option+Enter: newline
      e.preventDefault();postChat(e.shiftKey?'comment':'handoff')}
    else if(e.key==='Escape')inp.blur()});
  inp.addEventListener('keyup',e=>e.stopPropagation());
  count();poll();status();setInterval(()=>{poll();status()},2000);

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


def _line(m):
    return f"#{m['id']} {_where(m.get('ctx'))}{m['text']}".replace("\n", " ⏎ ")


def announce(ms, seen):
    """Watcher output for creator messages that are handed over (sent) and not in `seen` (updated in place).
    A batch of several notes is one line; pending notes print nothing."""
    out, batches = [], {}
    for m in ms:
        if m.get("role") != "creator" or status(m) != SENT or m["id"] in seen:
            continue
        seen.add(m["id"])
        if isinstance(m.get("batch"), int):
            batches.setdefault(m["batch"], []).append(m)
        else:
            out.append((m["id"], f"CHAT {_line(m)}"))
    for b, g in batches.items():
        if len(g) == 1:
            out.append((g[0]["id"], f"CHAT {_line(g[0])}"))
        else:
            out.append((max(m["id"] for m in g), f"CHAT BATCH b{b} ({len(g)} 条): " + " ‖ ".join(_line(m) for m in g)))
    return [line for _, line in sorted(out)]


def watch(project):
    """Stream handed-over creator messages; keep the heartbeat fresh while running, remove it on exit."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # run the finally on kill / Monitor stop
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))
    since = time.time()
    seen = set()
    announce(load(project), seen)   # history is not news; pending notes stay unseen until handed over
    try:
        while True:
            beat(project, since)
            for line in announce(load(project), seen):
                print(line, flush=True)
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
            tag = "[待交] " if m["role"] == "creator" and status(m) == PENDING else (f"[b{m['batch']}] " if m.get("batch") else "")
            print(f"#{m['id']} {m['role']} {m['ts']} {tag}{_where(m.get('ctx'))}{m['text']}")
    elif cmd == "watch":
        watch(project)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
