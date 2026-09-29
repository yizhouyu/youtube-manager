"""Timestamped questions for the creator, answered while he watches.

Facts only the creator knows ("what was the dinner restaurant called?") are best answered at the
moment he sees that footage. Questions live in `<project>/02 - Export/edit/questions.json`:

    [{"id": "q1",
      "where": "cut" | "raw",                  # where it was asked (display uses the anchors below)
      "t": 216.9,                              # cut seconds  -> pops up on the review page (8765)
      "clip": "GX015467", "clip_t": 1.0,       # raw anchor   -> pops up in the footage player (8766)
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
    q = {"where": where}
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
    """Copies of the questions with a missing anchor filled from the current EDL (not saved),
    so a question asked on one page also pops up at the same moment on the other."""
    need = [q for q in qs if (q.get("t") is None) != (q.get("clip") is None)]
    edl = _edl(project) if need else None
    if not edl:
        return qs
    out = []
    for q in qs:
        q = dict(q)
        try:
            if q.get("t") is None and q.get("clip"):
                q["t"] = clip_to_cut(edl, q["clip"], float(q.get("clip_t") or 0))
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
# Styles fall back across the two pages' CSS variable names.

CSS = r"""
.qa{--qa-acc:var(--acc,var(--accent,#2563eb));--qa-mut:var(--mut,var(--mute,#6b7280));--qa-line:var(--line,#e2e5e9);
  font-size:13.5px;line-height:1.45;color:var(--text,var(--ink,#1c2127))}
.qa-card{background:#fffbeb;border:1px solid #f5d77a;border-radius:10px;padding:10px 12px;margin-bottom:10px;
  box-shadow:0 2px 10px rgba(180,130,0,.12);animation:qaIn .25s ease}
@keyframes qaIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
.qa-card[hidden]{display:none}
.qa-meta{color:#8a6100;font-size:12px;font-variant-numeric:tabular-nums;margin-bottom:3px}
.qa-q{font-weight:600;font-size:15px;margin-bottom:3px}
.qa-ctx{color:var(--qa-mut);font-size:12.5px;margin-bottom:4px}
.qa-card textarea{width:100%;box-sizing:border-box;font:inherit;font-size:14px;border:1px solid #e8d9a8;border-radius:7px;
  padding:6px 8px;margin-top:4px;resize:vertical;min-height:52px;background:#fff}
.qa-card textarea:focus{outline:2px solid #fde68a;border-color:#d4a72c}
.qa-row{display:flex;gap:8px;align-items:center;margin-top:6px}
.qa button{font:inherit;font-size:13px;border:1px solid var(--qa-line);background:#fff;border-radius:7px;padding:3px 11px;cursor:pointer;color:inherit}
.qa button.pri{background:var(--qa-acc);border-color:var(--qa-acc);color:#fff}
.qa button:disabled{opacity:.5;cursor:default}
.qa-hint{color:var(--qa-mut);font-size:12px;margin-left:auto}
.qa-err{color:#b42318;font-size:12.5px}
.qa-err:not(:empty){margin-top:4px}
.qa-okmsg{display:none;color:#067647;font-weight:600;margin-top:6px}
.qa-card.ok .qa-okmsg{display:block}
.qa-card.ok textarea,.qa-card.ok .qa-row{display:none}
.qa-head{display:flex;align-items:center;gap:8px;padding:2px 2px 6px;font-size:13px}
.qa-head b{cursor:pointer;user-select:none;white-space:nowrap}
.qa-n{color:var(--qa-mut);white-space:nowrap}
.qa-sp{flex:1}
.qa-tog{display:inline-flex;align-items:center;gap:4px;color:var(--qa-mut);cursor:pointer;user-select:none;white-space:nowrap}
.qa.fold .qa-list{display:none}
.qa-item{display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:baseline;padding:5px 8px;border-radius:7px;
  cursor:pointer;border:1px solid transparent}
.qa-item:hover{background:rgba(37,99,235,.06)}
.qa-item.on{border-color:#f5d77a;background:#fffbeb}
.qa-t{color:var(--qa-acc);font-variant-numeric:tabular-nums;font-size:12.5px;white-space:nowrap}
.qa-tx{min-width:0}
.qa-ans{display:block;color:var(--qa-mut);font-size:12.5px}
.qa-st{font-size:12px;color:#b54708;white-space:nowrap}
.qa-item.done .qa-st{color:#067647}
.qa-item.done .qa-tx{color:var(--qa-mut)}
"""

JS = r"""
function initQuestions(cfg){
  const root=cfg.root, W0=1.5, W1=8;           // pop up from 1.5 s before to 8 s after the question time
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const ls=(k,v)=>{try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}};
  let Q=[], mt=null, shown=null, forced=null, forcedAt=0, okId=null, okUntil=0, prevPos=null, autoPause=ls('qa_pause')==='1';
  const dismissed=new Set(), drafts={};
  root.classList.add('qa'); if(ls('qa_fold')==='1') root.classList.add('fold');
  root.innerHTML=`<div class="qa-card" hidden></div>
    <div class="qa-head"><b title="点击收起/展开列表">❓ 问你的问题</b><span class="qa-n"></span><span class="qa-sp"></span>
      <label class="qa-tog" title="播放到问题的时间点时自动暂停"><input type="checkbox"> 到问题时暂停</label></div>
    <div class="qa-list"></div>`;
  const card=root.querySelector('.qa-card'), list=root.querySelector('.qa-list'), tog=root.querySelector('.qa-tog input');
  tog.checked=autoPause; tog.onchange=()=>{autoPause=tog.checked; ls('qa_pause',autoPause?'1':'0')};
  root.querySelector('.qa-head b').onclick=()=>{root.classList.toggle('fold'); ls('qa_fold',root.classList.contains('fold')?'1':'0')};
  const items=()=>Q.map(q=>({q,p:cfg.pos(q)})).filter(x=>x.p!=null&&isFinite(x.p)).sort((a,b)=>a.p-b.p);
  const inWin=(p,pos)=>pos!=null&&pos>=p-W0&&pos<=p+W1;
  const byId=id=>Q.find(q=>q.id===id);

  function renderList(){
    const it=items(), open=it.filter(x=>!x.q.answer).length;
    document.body.classList.toggle('hasq',it.length>0);
    root.querySelector('.qa-n').textContent=it.length?(open?`${open} 个待回答`:'都答完了 ✓'):'';
    list.innerHTML=it.map(({q,p})=>`<div class="qa-item${q.answer?' done':''}${q.id===shown?' on':''}" data-id="${esc(q.id)}" title="点击跳到这里">
      <span class="qa-t">⏱ ${esc(cfg.label(q,p))}</span>
      <span class="qa-tx">${esc(q.text)}${q.answer?`<span class="qa-ans">答：${esc(q.answer)}</span>`:''}</span>
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
    card.innerHTML=`<div class="qa-meta">❓ 想问你 · ⏱ ${esc(cfg.label(q,cfg.pos(q)))}</div>
      <div class="qa-q">${esc(q.text)}</div>${q.context?`<div class="qa-ctx">${esc(q.context)}</div>`:''}
      <textarea rows="2" placeholder="在这里写回答，回车提交（Shift+回车换行）"></textarea>
      <div class="qa-row"><button class="pri qa-sub">提交</button><button class="qa-skip">跳过</button>
        <span class="qa-hint">视频不会停，边看边写</span></div>
      <div class="qa-err"></div><div class="qa-okmsg">已记录 ✓</div>`;
    const ta=card.querySelector('textarea');
    ta.value=drafts[q.id]??(q.answer||'');
    ta.oninput=()=>{drafts[q.id]=ta.value};
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
