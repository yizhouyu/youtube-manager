"""Glue between the review pages and the 「审片」 Mac app (app/ + app_server.py).

Two things, both opt-in so the pages behave as before in a browser:

* `inject(page)`: editor keys for any page that sets `window.appHooks` (Q8) plus the cut <-> raw jump (Q7):
    J / K / L     back / pause / forward; pressing L (or J) again goes 1x -> 2x -> 4x; K stops and restores the speed
    , / .         one frame back / forward (paused)
    C             focus the comment box at the current moment (pauses; in fullscreen C keeps its chat meaning)
    R + a button  only inside the app: jump to the same moment on the other page (via the app shell, postMessage)
  Keys never fire while typing in an input. The app shell sends {shenpian: "seek" | "pause"} messages back.
  appHooks = {kind: 'raw'|'cut'|'shorts', video(), rate(), setRate(r), here() -> jump query, seek(msg), btnHost()}

* `read_only(app)`: started with --read-only (projects outside ~/Desktop, e.g. the external drive), the server
  refuses every POST, never writes storyboards or proofread captions, and hides the write buttons.
"""
from flask import jsonify, request

RO = False   # set by read_only(); footage_player checks it before proofreading captions

RO_CSS = """<style>/* read-only (审片 app): nothing on this page can write */
#cbForm,#cbQuick,#bSave,#bPrev,#bFinal,#qcard textarea,.qa-card button{display:none !important}
#roBanner{position:fixed;left:50%;top:8px;transform:translateX(-50%);z-index:9999;padding:3px 12px;border-radius:999px;
  background:var(--q-soft);color:var(--q-ink);border:1px solid var(--q-line);font-size:12px;pointer-events:none}
html.in-app #roBanner{display:none}   /* the app's toolbar says 只读 */
</style><div id="roBanner">只读 · 这个文件夹不会被写入</div>"""


def read_only(app):
    global RO
    RO = True
    from . import storyboard as SB
    SB.READ_ONLY = True

    @app.before_request
    def _no_writes():
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return jsonify({"ok": False, "error": "只读：这个文件夹不会被写入"}), 403

    @app.after_request
    def _banner(resp):
        if resp.mimetype == "text/html" and request.path in ("/", "/shorts"):
            resp.set_data(resp.get_data(as_text=True).replace("</body>", RO_CSS + "</body>", 1))
        return resp


JS = r"""<style>
#abToast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:9999;padding:7px 16px;border-radius:999px;
  background:rgba(20,22,26,.88);color:#fff;font-size:13px;pointer-events:none;opacity:0;transition:opacity .2s}
#abToast.on{opacity:1}
#abJump{height:26px;padding:0 10px;font-size:12px;margin-left:8px;white-space:nowrap}
</style><script>
(function(){
  const inApp=window.top!==window;
  // in the app the page's own header row is hidden (theme.FLAVOR): its meta text and buttons are shown in the app's
  // toolbar instead. A click there comes back as {shenpian:'act', id} and clicks the page's own button.
  const hdr=inApp&&document.querySelector('.hdr');
  if(hdr){let qT=0;
    const shown=el=>getComputedStyle(el).display!=='none';
    const send=()=>{qT=0;const dirty=document.getElementById('dirty');
      const acts=[...hdr.querySelectorAll('button[id]')].filter(shown).map(b=>{const k=b.querySelector('kbd');
        return {id:b.id,label:[...b.childNodes].filter(n=>n!==k).map(n=>n.textContent).join('').trim(),kbd:k?k.textContent.trim():'',
          pri:b.classList.contains('pri'),danger:b.classList.contains('danger'),title:b.title||'',disabled:!!b.disabled,dirty:b.id==='bSave'&&!!dirty&&shown(dirty)}});
      const meta=[...hdr.querySelectorAll('.meta[id]')].map(m=>m.textContent.trim()).filter(Boolean).join('  ·  ');
      parent.postMessage({shenpian:'hdr',acts,meta},'*')};
    const later=()=>{if(!qT)qT=setTimeout(send,60)};
    new MutationObserver(later).observe(hdr,{subtree:true,childList:true,attributes:true,characterData:true});
    new MutationObserver(later).observe(document.body,{attributes:true,attributeFilter:['class']});
    window.addEventListener('message',e=>{const d=e.data;if(!d||d.shenpian!=='act'||e.source!==parent)return;
      const b=document.getElementById(d.id);if(b&&hdr.contains(b)&&b.tagName==='BUTTON'&&!b.disabled)b.click()});
    send()}
  const H=window.appHooks; if(!H) return;
  const typing=t=>t&&(/INPUT|SELECT|TEXTAREA/.test(t.tagName)||t.isContentEditable);
  let tT=0;
  function toast(s){let e=document.getElementById('abToast');if(!e){e=document.createElement('div');e.id='abToast';document.body.appendChild(e)}
    e.textContent=s;e.classList.add('on');clearTimeout(tT);tT=setTimeout(()=>e.classList.remove('on'),2200)}
  window.abToast=toast;
  // J/K/L shuttle: L plays forward (again = faster), J steps backward while paused (again = faster)
  let sh=null;   // {dir:'f'|'b', rate, prev, timer}
  function stop(){if(!sh)return;clearInterval(sh.timer);if(sh.dir==='f')H.setRate(sh.prev);sh=null}
  function fwd(v){if(sh&&sh.dir==='f'){sh.rate=Math.min(4,sh.rate*2)}else{const p=sh?sh.prev:H.rate();stop();sh={dir:'f',rate:1,prev:p}}
    H.setRate(sh.rate);v.play().catch(()=>{});toast('▶ '+sh.rate+'×')}
  function back(v){if(sh&&sh.dir==='b'){sh.rate=Math.min(4,sh.rate*2)}else{const p=sh?sh.prev:H.rate();stop();v.pause();
    sh={dir:'b',rate:1,prev:p,timer:setInterval(()=>{const w=H.video();if(!w||w.currentTime<=0){stop();return}w.currentTime=Math.max(0,w.currentTime-sh.rate*0.1)},100)}}
    toast('◀ '+sh.rate+'×')}
  function step(v,d){stop();v.pause();v.currentTime=Math.max(0,Math.min((v.duration||1e9)-0.01,v.currentTime+d/30))}
  function comment(v){if(window.cbFs&&cbFs.active())return false;
    const box=document.getElementById('cb'),inp=document.getElementById('cbIn');if(!inp)return false;
    stop();v.pause();if(box&&box.classList.contains('min'))document.getElementById('cbHead').click();inp.focus();return true}
  async function jump(){if(!inApp)return;const v=H.video();if(!v)return;stop();v.pause();
    let r=null;try{r=await (await fetch('/api/chat/jump?'+new URLSearchParams(H.here()))).json()}catch(e){}
    if(H.kind==='cut'){if(!r||!r.clip){toast('这里是标题卡，没有原片');return}
      parent.postMessage({shenpian:'jump',to:'raw',clip:r.clip,t:r.clip_t},'*')}
    else{if(!r||r.t==null){toast('这段没用上');return}parent.postMessage({shenpian:'jump',to:'cut',t:r.t},'*')}}
  document.addEventListener('keydown',e=>{
    if(e.metaKey||e.ctrlKey||e.altKey||typing(e.target))return;
    const v=H.video();if(!v)return;const k=e.key.toLowerCase();
    if(k===' '){stop();return}                                     // the page's own play/pause
    if(k==='k'){const was=!!sh;stop();   // after J/L: K = stop (the cut page's own K may have just toggled it back on)
      if(was)v.pause();else if(!e.defaultPrevented)v.paused?v.play().catch(()=>{}):v.pause();e.preventDefault();return}
    if(k==='l')fwd(v);else if(k==='j')back(v);
    else if(e.key===',')step(v,-1);else if(e.key==='.')step(v,1);
    else if(k==='c'){if(!comment(v))return}
    else if(k==='r'&&inApp)jump();
    else return;
    e.preventDefault();e.stopPropagation()},true);
  window.addEventListener('message',e=>{const d=e.data;if(!d||!d.shenpian)return;
    const v=H.video();if(d.shenpian==='pause'){stop();if(v)v.pause()}else if(d.shenpian==='seek'){stop();H.seek(d)}});
  // the app's status (scripts/shenpian status): where the playhead is, sent when it changes (at most once a second)
  if(inApp){let last='';setInterval(()=>{const v=H.video();if(!v)return;let h={};try{h=H.here()||{}}catch(e){}
    const s=JSON.stringify(h);if(s===last)return;last=s;parent.postMessage({shenpian:'time',here:h},'*')},1000)}
  if(inApp&&H.kind!=='shorts'){const host=H.btnHost&&H.btnHost();if(host){const b=document.createElement('button');b.id='abJump';b.type='button';
    b.textContent=H.kind==='cut'?'R 看原片':'R 看成片';b.title=H.kind==='cut'?'跳到这一刻的原片（没用上的部分也看得到）':'跳到成片里的这一刻';
    b.addEventListener('mousedown',e=>e.preventDefault());b.onclick=e=>{e.stopPropagation();jump()};host.appendChild(b)}}
})();
</script>"""


def inject(page):
    """Keys + jump script, theme.FLAVOR, and `html.in-app` when the page sits inside the app shell."""
    from . import theme
    head = ("<script>if(window.top!==window)document.documentElement.classList.add('in-app')</script>"
            f"<style>{theme.FLAVOR}</style></head>")
    return page.replace("</head>", head, 1).replace("</body>", JS + "</body>", 1)
