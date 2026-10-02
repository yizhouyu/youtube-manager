"""Timestamped questions for the creator, answered while he watches.

Facts only the creator knows ("what was the dinner restaurant called?") are best answered at the
moment he sees that footage. Questions live in `<project>/02 - Export/edit/questions.json`:

    [{"id": "q1",
      "where": "cut" | "raw",                  # where it was asked (display uses the anchors below)
      "t": 216.9,                              # cut seconds  -> pops up on the review page (8766)
      "clip": "GX015467", "clip_t": 1.0,       # raw anchor   -> pops up in the footage player (8765)
      "text": "晚饭这家墨西哥餐厅叫什么？",
      "context": "optional short note",
      "answer": null, "answered_at": null}]

A question with both anchors shows in both players. Both pages poll the file, so questions added
while the creator is watching appear without a reload; his answers are written back here.

    # add one (t is computed from the raw anchor via the EDL when --t is omitted)
    ./venv/bin/python -m src.editor.questions "<project>" add "问题" --clip GX015467 --clip-t 1.0
    ./venv/bin/python -m src.editor.questions "<project>" add "问题" --t 124.4   # clip/clip_t from EDL
    ./venv/bin/python -m src.editor.questions "<project>" list
"""
import argparse
import contextlib
import fcntl
import json
import os
import threading
from datetime import datetime

from . import edl as E

_lock = threading.Lock()


@contextlib.contextmanager
def _locked(project):
    """Serialize read-modify-write across threads AND processes (both servers + the CLI)."""
    d = os.path.join("/tmp/yt-editor", os.path.basename(os.path.normpath(E.project_dir(project))))
    os.makedirs(d, exist_ok=True)
    with _lock, open(os.path.join(d, "questions.lock"), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def path(project):
    return os.path.join(E.edit_dir(project), "questions.json")


def mtime(project):
    try:
        return str(os.stat(path(project)).st_mtime_ns)
    except OSError:
        return ""


def load(project):
    try:
        with open(path(project), encoding="utf-8") as f:
            qs = json.load(f)
    except (OSError, ValueError):
        return []
    return [q for q in qs if isinstance(q, dict) and q.get("id")] if isinstance(qs, list) else []


def save(project, qs):
    os.makedirs(E.edit_dir(project), exist_ok=True)
    tmp = path(project) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(qs, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path(project))


def _edl(project):
    try:
        return E.load(project)
    except (OSError, ValueError):
        return None


def clip_to_cut(edl, clip, clip_t):
    """Raw (clip, seconds) -> cut seconds, or None if that moment isn't in the cut.
    First enabled shot whose kept ranges contain it wins; b-roll inserts count too."""
    rows, _ = E.timeline(edl)
    for s, st in rows:
        if s.get("clip") == clip and not s.get("card"):
            for a, b in E.kept_ranges(s):
                if a - 0.05 <= clip_t <= b + 0.05:
                    return round(st + E.src_to_local(s, clip_t), 2)
    for s, st in rows:
        for b in s.get("broll") or []:
            a = float(b.get("in", 0))
            if b.get("clip") == clip and a <= clip_t <= a + float(b.get("dur", 0)):
                return round(st + float(b.get("at", 0)) + clip_t - a, 2)
    return None


def cut_to_clip(edl, t):
    """Cut seconds -> (clip, clip seconds) of the shot playing then (b-roll ignored), or None."""
    rows, _ = E.timeline(edl)
    for s, st in rows:
        d = E.shot_dur(s)
        if st <= t < st + d or (s is rows[-1][0] and t <= st + d):
            if s.get("card") or not s.get("clip"):
                return None
            local, k = (t - st) * E.speed(s), 0.0
            for a, b in E.kept_ranges(s):
                if local <= k + (b - a):
                    return s["clip"], round(a + local - k, 2)
                k += b - a
            return s["clip"], round(s["out"], 2)
    return None


def shot_at(edl, t):
    """Cut seconds -> (shot id, seconds into that shot), or None."""
    rows, _ = E.timeline(edl)
    for s, st in rows:
        if st <= t < st + E.shot_dur(s) or (s is rows[-1][0] and t <= st + E.shot_dur(s)):
            return s.get("id"), round(t - st, 2)
    return None


def shot_to_cut(edl, sid, shot_t):
    """(shot id, seconds into it) -> cut seconds, or None if that shot is gone/disabled."""
    rows, _ = E.timeline(edl)
    for s, st in rows:
        if s.get("id") == sid:
            return round(st + min(float(shot_t or 0), E.shot_dur(s)), 2)
    return None


def _next_id(qs):
    n = 0
    for q in qs:
        s = str(q.get("id", ""))
        if s.startswith("q") and s[1:].isdigit():
            n = max(n, int(s[1:]))
    return f"q{n + 1}"


def add(project, text, t=None, clip=None, clip_t=None, context=None, where=None):
    """Append a question. Missing anchors are filled from the EDL when possible:
    t from (clip, clip_t), or (clip, clip_t) from t."""
    if t is None and clip is None:
        raise ValueError("need t (cut seconds) or clip + clip_t (raw)")
    where = where or ("cut" if t is not None else "raw")
    edl = _edl(project)
    if clip is not None and clip_t is None:
        clip_t = 0.0
    if edl:
        if t is None:
            t = clip_to_cut(edl, clip, float(clip_t))
        elif clip is None:
            hit = cut_to_clip(edl, float(t))
            if hit:
                clip, clip_t = hit
    # a card/map moment has no raw anchor: pin it to its shot so later edits don't strand it
    sid = shot_at(edl, float(t)) if (edl and clip is None and t is not None) else None
    q = {"where": where}
    if sid:
        q["shot"], q["shot_t"] = sid
    if t is not None:
        q["t"] = round(float(t), 2)
    if clip is not None:
        q["clip"], q["clip_t"] = clip, round(float(clip_t), 2)
    q.update(text=text, context=context or "", answer=None, answered_at=None)
    with _locked(project):
        qs = load(project)
        q = {"id": _next_id(qs), **q}
        qs.append(q)
        save(project, qs)
    return q


def answer(project, qid, text):
    """Record (or with empty text, clear) the creator's answer. Returns the question or None."""
    text = (text or "").strip()
    with _locked(project):
        qs = load(project)
        for q in qs:
            if q.get("id") == qid:
                q["answer"] = text or None
                q["answered_at"] = datetime.now().isoformat(timespec="seconds") if text else None
                save(project, qs)
                return q
    return None


def with_anchors(project, qs):
    """Copies of the questions with the cut time re-derived from the current EDL (not saved), so
    a question follows its moment after edits shift the cut, and one asked on one page also pops
    up at the same moment on the other. Anchor priority: shot > raw clip > the stored cut time."""
    edl = _edl(project) if qs else None
    if not edl:
        return qs
    out = []
    for q in qs:
        q = dict(q)
        try:
            t = None
            if q.get("shot"):
                t = shot_to_cut(edl, q["shot"], q.get("shot_t"))
            if t is None and q.get("clip"):
                t = clip_to_cut(edl, q["clip"], float(q.get("clip_t") or 0))
            if t is not None:
                q["t"] = t
            elif q.get("clip") is None and q.get("t") is not None:
                hit = cut_to_clip(edl, float(q["t"]))
                if hit:
                    q["clip"], q["clip_t"] = hit
        except (KeyError, TypeError, ValueError):
            pass
        out.append(q)
    return out


def register(app, get_project):
    """Add GET /api/questions and POST /api/answer to a Flask app."""
    from flask import jsonify, request

    @app.get("/api/questions")
    def api_questions():
        p = get_project()
        try:  # filled-in anchors follow the EDL, so an EDL change counts as a change too
            em = str(os.stat(E.edl_path(p)).st_mtime_ns)
        except OSError:
            em = ""
        return jsonify({"mtime": mtime(p) + ":" + em, "questions": with_anchors(p, load(p))})

    @app.post("/api/answer")
    def api_answer():
        body = request.get_json(silent=True) or {}
        qid, text = body.get("id"), body.get("answer", "")
        if not isinstance(qid, str) or not isinstance(text, str) or len(text) > 4000:
            return jsonify({"ok": False, "error": "格式错误"}), 400
        q = answer(get_project(), qid, text)
        if q is None:
            return jsonify({"ok": False, "error": "找不到这个问题"}), 404
        return jsonify({"ok": True, "question": q})


# ---------------------------------------------------------------- page assets
# Shared by review_server (cut) and footage_player (raw). Each page calls initQuestions(cfg):
#   root        element the panel renders into (pop-up card + toggle + list)
#   pos(q)      question position on THIS page's timeline (seconds), or null = not shown here
#   now()       current playback position on the same timeline, or null
#   playing() / pause() / seek(pos)
#   label(q,p)  timestamp text;  markers(items) / onTick(pos, activeQ)  optional page hooks
#   card        optional element for the pop-up card (default: top of root);  count(open, total) optional hook
# Colours come from the shared theme tokens (theme.py).

CSS = r"""
.qa{font-size:14px;line-height:1.55;color:var(--text)}
.qa-card{background:var(--q-soft);border:1px solid var(--q-line);border-left:3px solid var(--q);border-radius:var(--r);
  padding:10px 12px 11px;margin-bottom:10px;animation:qaIn .25s ease}
@keyframes qaIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
.qa-card[hidden]{display:none}
.qa-meta{display:flex;align-items:center;gap:8px;color:var(--q-ink);font-size:12px;font-weight:500;font-variant-numeric:tabular-nums;margin:-2px -4px 3px 0}
.qa-meta span{flex:1}
.qa .qa-skip{border:0;background:transparent;color:var(--q-ink);font-size:12px;padding:1px 8px;opacity:.8}
.qa .qa-skip:hover{background:rgba(245,158,11,.14);opacity:1}
.qa-q{font-weight:600;font-size:15px;line-height:1.6;margin-bottom:4px}
.qa-ctx{color:var(--text-2);font-size:12px;margin-bottom:4px}
.qa-card textarea{flex:1;min-width:0;font:inherit;font-size:14px;line-height:1.45;border:1px solid var(--q-line);border-radius:var(--r-sm);
  padding:7px 9px;resize:none;height:36px;max-height:120px;background:var(--surface);overflow-y:auto}
.qa-card textarea:focus{border-color:var(--q);box-shadow:0 0 0 3px rgba(242,164,12,.18)}
.qa-row{display:flex;gap:6px;align-items:flex-end;margin-top:8px}
.qa-row .qa-sub{height:36px;padding:0 14px;flex:none}
.qa button{font-size:13px;padding:3px 12px}
.qa-hint{color:var(--text-3);font-size:12px;margin-left:auto}
.qa-err{color:var(--danger);font-size:12px}
.qa-err:not(:empty){margin-top:4px}
.qa-okmsg{display:none;color:var(--ok);font-weight:600;margin-top:6px}
.qa-card.ok .qa-okmsg{display:block}
.qa-card.ok textarea,.qa-card.ok .qa-row{display:none}
.qa-head{display:flex;align-items:center;gap:8px;padding:2px 2px 6px;font-size:13px}
.qa-head b{cursor:pointer;user-select:none;white-space:nowrap;font-weight:600;display:inline-flex;align-items:center;gap:6px}
.qa-head b::before{content:'';width:7px;height:7px;border-radius:50%;background:var(--q)}
.qa-n{color:var(--text-3);white-space:nowrap;font-size:12px}
.qa-sp{flex:1}
.qa-tog{display:inline-flex;align-items:center;gap:4px;color:var(--text-2);font-size:12px;cursor:pointer;user-select:none;white-space:nowrap}
.qa.fold .qa-list{display:none}
.qa-item{display:flex;flex-direction:column;gap:1px;padding:6px 8px;border-radius:var(--r-sm);
  cursor:pointer;border:1px solid transparent}
.qa-item:hover{background:var(--surface-2)}
.qa-item.on{border-color:var(--q-line);background:var(--q-soft)}
.qa-t{color:var(--accent);font-variant-numeric:tabular-nums;font-size:12px;white-space:nowrap;display:inline-flex;align-items:center;gap:6px}
.qa-t::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--q);flex:none}
.qa-item.done .qa-t::before{background:var(--used)}
.qa-tx{min-width:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.qa-item.on .qa-tx{-webkit-line-clamp:unset}
.qa-ans{color:var(--text-2);font-size:12px}
.qa-st{display:none}
.qa-item.done .qa-tx{color:var(--text-2)}
"""

JS = r"""
function initQuestions(cfg){
  const root=cfg.root, W0=1.5, W1=8;           // pop up from 1.5 s before to 8 s after the question time
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const ls=(k,v)=>{try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}};
  let Q=[], mt=null, shown=null, forced=null, forcedAt=0, okId=null, okUntil=0, prevPos=null, autoPause=ls('qa_pause')==='1';
  const dismissed=new Set(), drafts={};
  root.classList.add('qa'); if(ls('qa_fold')==='1') root.classList.add('fold');
  root.innerHTML=`${cfg.card?'':'<div class="qa-card" hidden></div>'}
    <div class="qa-head"><b title="点击收起/展开列表">问你的问题</b><span class="qa-n"></span><span class="qa-sp"></span>
      <label class="qa-tog" title="播放到问题的时间点时自动暂停"><input type="checkbox"> 到问题时暂停</label></div>
    <div class="qa-list"></div>`;
  if(cfg.card){cfg.card.classList.add('qa'); cfg.card.innerHTML='<div class="qa-card" hidden></div>'}
  const card=(cfg.card||root).querySelector('.qa-card'), list=root.querySelector('.qa-list'), tog=root.querySelector('.qa-tog input');
  tog.checked=autoPause; tog.onchange=()=>{autoPause=tog.checked; ls('qa_pause',autoPause?'1':'0')};
  root.querySelector('.qa-head b').onclick=()=>{root.classList.toggle('fold'); ls('qa_fold',root.classList.contains('fold')?'1':'0')};
  const items=()=>Q.map(q=>({q,p:cfg.pos(q)})).filter(x=>x.p!=null&&isFinite(x.p)).sort((a,b)=>a.p-b.p);
  const inWin=(p,pos)=>pos!=null&&pos>=p-W0&&pos<=p+W1;
  const byId=id=>Q.find(q=>q.id===id);

  function renderList(){
    const it=items(), open=it.filter(x=>!x.q.answer).length;
    document.body.classList.toggle('hasq',it.length>0);
    root.querySelector('.qa-n').textContent=it.length?(open?`${open} 个待回答`:'都答完了 ✓'):'';
    cfg.count&&cfg.count(open,it.length);
    list.innerHTML=it.map(({q,p})=>`<div class="qa-item${q.answer?' done':''}${q.id===shown?' on':''}" data-id="${esc(q.id)}" title="${q.answer?'已回答':'未回答'} · 点击跳到这里">
      <span class="qa-t">${esc(cfg.label(q,p))}</span>
      <span class="qa-tx">${esc(q.text)}</span>${q.answer?`<span class="qa-ans">答：${esc(q.answer)}</span>`:''}
      <span class="qa-st">${q.answer?'✓ 已回答':'未回答'}</span></div>`).join('');
    cfg.markers&&cfg.markers(it);
  }
  list.onclick=e=>{const el=e.target.closest('.qa-item'); if(el) jump(el.dataset.id)};
  function jump(id){
    const x=items().find(x=>x.q.id===id); if(!x) return;
    forced=id; forcedAt=Date.now(); dismissed.delete(id); cfg.seek(Math.max(0,x.p-1)); tick();
  }

  function renderCard(q){
    shown=q?q.id:null; card.classList.remove('ok');
    list.querySelectorAll('.qa-item').forEach(e=>e.classList.toggle('on',e.dataset.id===shown));
    if(!q){card.hidden=true; card.innerHTML=''; return}
    card.innerHTML=`<div class="qa-meta"><span>想问你 · ${esc(cfg.label(q,cfg.pos(q)))}</span><button class="qa-skip" title="先不回答，过了这段就收起">跳过</button></div>
      <div class="qa-q">${esc(q.text)}</div>${q.context?`<div class="qa-ctx">${esc(q.context)}</div>`:''}
      <div class="qa-row"><textarea rows="1" placeholder="写回答，回车提交" title="回车提交，Shift+回车换行；视频不会停，边看边写"></textarea>
        <button class="pri qa-sub">提交</button></div>
      <div class="qa-err"></div><div class="qa-okmsg">已记录 ✓</div>`;
    const ta=card.querySelector('textarea');
    ta.value=drafts[q.id]??(q.answer||'');
    const grow=()=>{ta.style.height='auto'; ta.style.height=Math.min(120,ta.scrollHeight+2)+'px'};
    ta.oninput=()=>{drafts[q.id]=ta.value; grow()}; if(ta.value) setTimeout(grow,0);
    ta.onkeydown=e=>{
      e.stopPropagation();
      if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault(); submit()}
      else if(e.key==='Escape') ta.blur();
    };
    card.querySelector('.qa-sub').onclick=submit;
    card.querySelector('.qa-skip').onclick=()=>{dismissed.add(q.id); if(forced===q.id) forced=null; ta.blur(); renderCard(null); tick()};
    card.hidden=false;
  }
  async function submit(){
    const id=shown, ta=card.querySelector('textarea'), btn=card.querySelector('.qa-sub'), er=card.querySelector('.qa-err');
    if(!id||!ta) return; const txt=ta.value.trim(); if(!txt){ta.focus(); return}
    btn.disabled=true; er.textContent='';
    try{
      const r=await fetch('/api/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,answer:txt})});
      const j=await r.json(); if(!j.ok) throw new Error(j.error||r.status);
      const q=byId(id); if(q){q.answer=j.question.answer; q.answered_at=j.question.answered_at}
      delete drafts[id]; ta.blur(); if(forced===id) forced=null;
      card.classList.add('ok'); okId=id; okUntil=Date.now()+1600; renderList();
    }catch(e){er.textContent='没保存上：'+(e.message||e)+'（回答还在框里，可以再点提交）'; btn.disabled=false}
  }

  function pick(pos){
    if(okId&&Date.now()<okUntil&&byId(okId)) return byId(okId);
    okId=null;
    const ta=card.querySelector('textarea');
    // never yank a card he is typing into
    if(shown&&byId(shown)&&ta&&(document.activeElement===ta||(drafts[shown]||'').trim())) return byId(shown);
    const it=items();
    if(forced){const x=it.find(x=>x.q.id===forced);
      if(x&&(inWin(x.p,pos)||Date.now()-forcedAt<3000)) return x.q; forced=null}
    const c=it.filter(x=>!x.q.answer&&!dismissed.has(x.q.id)&&inWin(x.p,pos));
    return c.length?c[c.length-1].q:null;
  }
  function tick(){
    const pos=cfg.now();
    if(pos!=null){
      if(autoPause&&cfg.playing()&&prevPos!=null&&pos>prevPos&&pos-prevPos<2.5)
        for(const x of items()) if(!x.q.answer&&!dismissed.has(x.q.id)&&prevPos<x.p&&x.p<=pos){cfg.pause(); break}
      prevPos=pos;
      for(const id of [...dismissed]){const x=items().find(x=>x.q.id===id); if(!x||!inWin(x.p,pos)) dismissed.delete(id)}
    }
    const q=pick(pos), id=q?q.id:null;
    if(id!==shown||(q&&card.classList.contains('ok')&&okId!==id)) renderCard(q);
    cfg.onTick&&cfg.onTick(pos,q);
  }
  async function poll(){
    try{
      const j=await (await fetch('/api/questions',{cache:'no-store'})).json();
      if(j.mtime===mt) return; mt=j.mtime; Q=Array.isArray(j.questions)?j.questions:[];
      if(shown&&!byId(shown)) renderCard(null);
      renderList(); tick();
    }catch(e){}
  }
  poll(); setInterval(poll,4000); setInterval(tick,200);
  return {jump, items, poll};
}
"""


def inject(page):
    """Insert the shared CSS/JS into a page that has __QA_CSS__ / __QA_JS__ placeholders."""
    return page.replace("__QA_CSS__", CSS).replace("__QA_JS__", JS)


def main():
    ap = argparse.ArgumentParser(description="Timestamped questions for the creator")
    ap.add_argument("project")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("text")
    a.add_argument("--t", type=float, help="cut seconds")
    a.add_argument("--clip", help="raw clip stem, e.g. GX015467")
    a.add_argument("--clip-t", type=float, help="seconds inside the raw clip")
    a.add_argument("--context", default="")
    sub.add_parser("list")
    args = ap.parse_args()
    project = os.path.abspath(E.project_dir(args.project))
    if args.cmd == "add":
        q = add(project, args.text, t=args.t, clip=args.clip, clip_t=args.clip_t, context=args.context)
        print(json.dumps(q, ensure_ascii=False))
    else:
        for q in load(project):
            where = []
            if q.get("t") is not None:
                where.append(f"cut {int(q['t'] // 60)}:{q['t'] % 60:04.1f}")
            if q.get("clip"):
                where.append(f"{q['clip']}@{q.get('clip_t', 0)}")
            print(f"{q['id']} [{' | '.join(where)}] {q['text']}  →  {q.get('answer') or '（未回答）'}")


if __name__ == "__main__":
    main()
