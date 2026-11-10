"""Shared look for the local review pages (footage player, cut review, Shorts, the 审片 app shell) and their
widgets (questions panel, chat box): one CSS-variable palette plus a few base element styles.

    from . import theme
    page = page.replace("__THEME_CSS__", theme.CSS)

Tokens = option B「明亮 · 照片图库」 of app/DESIGN.md (the creator's pick, 2026-11-10): light, following macOS
appearance into dark; the video stage is always black. Every option in DESIGN.md defines the same variable names,
so switching styles = replacing TOKENS + DARK_TOKENS (and FLAVOR). DARK is the dark token set as bare declarations,
scoped to the fullscreen view (video plus chat rail, see chat.py), where a light panel next to the picture would glare.
FLAVOR holds B's few non-token rules for the existing pages (CSS only, no behaviour); appbridge.inject adds it.
"""

TOKENS = r"""
  /* type, radius, layout, motion */
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Helvetica Neue",sans-serif;
  --font-display:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Helvetica Neue",sans-serif;
  --font-num:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Helvetica Neue",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,monospace;
  --fs-xs:11px; --fs-sm:12px; --fs:13px; --fs-md:14px; --fs-lg:16px; --fs-title:20px;
  --r-xs:4px; --r-sm:7px; --r:10px; --r-lg:14px; --r-stage:12px;
  --hdr:52px; --side-w:236px; --rail-w:376px; --track-h:16px;
  --dur-1:120ms; --dur-2:200ms; --ease:cubic-bezier(.2,.8,.2,1);
  /* colour + depth */
  color-scheme:light;
  --bg:#f5f5f7; --bg-side:#ebebee; --bg-bar:#f5f5f7; --bg-rail:#ffffff;
  --surface:#ffffff; --surface-2:#f7f7f9; --surface-3:#ececf0;
  --line:#e5e5ea; --line-2:#d2d2d7;
  --text:#1d1d1f; --text-2:#48484d; --text-3:#86868b; --faint:#aeaeb2;
  --accent:#0071e3; --accent-hover:#0077ed; --accent-soft:#e9f2fd; --accent-line:#a9cdf5; --accent-ring:rgba(0,113,227,.16);
  --on-accent:#ffffff;
  --btn-pri-bg:#0071e3; --btn-pri-ink:#ffffff; --btn-sec-bg:#ffffff; --btn-sec-ink:#1d1d1f; --btn-sec-line:#d2d2d7;
  --sel-bg:#dcdce1; --sel-ink:#1d1d1f;
  --ok:#1a7f45; --ok-soft:#e6f4ea;
  --q:#f5a524; --q-ink:#9a5b00; --q-soft:#fff8eb; --q-line:#f7dca6;
  --danger:#d70015; --danger-soft:#fdecee;
  --st-review:#0062c4; --st-review-bg:#e3eefc; --st-open:#9a5b00; --st-open-bg:#fdf0d5;
  --st-pass:#1a7f45; --st-pass-bg:#e2f3e7; --st-up:#6e6e73; --st-up-bg:transparent;
  --stage:#000000; --stage-ink:rgba(255,255,255,.92); --stage-mute:rgba(255,255,255,.6);
  --box:#ffd60a; --playhead:#1d1d1f;
  --used:#34c759; --unused:#d2d2d7;
  --seg:#e2e2e7; --seg-2:#dadadf; --seg-past:#bdbdc4;
  --sh-1:0 1px 2px rgba(0,0,0,.08),0 0 0 .5px rgba(0,0,0,.06);
  --sh-2:0 8px 28px rgba(0,0,0,.10),0 0 0 .5px rgba(0,0,0,.06);
  --sh-stage:0 10px 30px rgba(0,0,0,.14),0 2px 6px rgba(0,0,0,.08);
"""

DARK_TOKENS = r"""
  color-scheme:dark;
  --bg:#1c1c1e; --bg-side:#232325; --bg-bar:#1c1c1e; --bg-rail:#232325;
  --surface:#2c2c2e; --surface-2:#262628; --surface-3:#3a3a3c;
  --line:#333336; --line-2:#48484a;
  --text:#f5f5f7; --text-2:#c7c7cc; --text-3:#8e8e93; --faint:#636366;
  --accent:#0a84ff; --accent-hover:#3395ff; --accent-soft:rgba(10,132,255,.16); --accent-line:rgba(10,132,255,.5);
  --accent-ring:rgba(10,132,255,.28); --on-accent:#ffffff;
  --btn-pri-bg:#0a84ff; --btn-pri-ink:#ffffff; --btn-sec-bg:#3a3a3c; --btn-sec-ink:#f5f5f7; --btn-sec-line:#48484a;
  --sel-bg:#3a3a3c; --sel-ink:#ffffff;
  --ok:#30d158; --ok-soft:rgba(48,209,88,.14);
  --q:#ffb340; --q-ink:#ffc566; --q-soft:rgba(255,179,64,.10); --q-line:rgba(255,179,64,.32);
  --danger:#ff453a; --danger-soft:rgba(255,69,58,.14);
  --st-review:#4ca2ff; --st-review-bg:rgba(10,132,255,.16); --st-open:#ffc566; --st-open-bg:rgba(255,179,64,.14);
  --st-pass:#30d158; --st-pass-bg:rgba(48,209,88,.14); --st-up:#8e8e93; --st-up-bg:transparent;
  --stage:#000000; --stage-ink:rgba(255,255,255,.92); --stage-mute:rgba(255,255,255,.6);
  --box:#ffd60a; --playhead:#f5f5f7;
  --used:#30d158; --unused:#48484a;
  --seg:#3a3a3c; --seg-2:#333336; --seg-past:#636366;
  --sh-1:0 1px 2px rgba(0,0,0,.4),0 0 0 .5px rgba(255,255,255,.06);
  --sh-2:0 10px 32px rgba(0,0,0,.5),0 0 0 .5px rgba(255,255,255,.08);
  --sh-stage:0 10px 30px rgba(0,0,0,.4);
"""

CSS = (":root{" + TOKENS + "}\n"
       "@media (prefers-color-scheme: dark){:root:not([data-theme=\"light\"]){" + DARK_TOKENS + "}}\n"
       ":root[data-theme=\"dark\"]{" + DARK_TOKENS + "}\n") + r"""
/* theme-independent extras used by the new pages (spacing scale, the veil while drawing a 框选 box) */
:root{--sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-5:24px;--box-veil:rgba(0,0,0,.12)}
*{box-sizing:border-box}
html{-webkit-font-smoothing:antialiased}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 var(--font)}
button,input,select,textarea{font:inherit;color:inherit}
button{border:1px solid var(--line-2);background:var(--surface);color:var(--text);border-radius:var(--r-sm);
  padding:5px 12px;cursor:pointer;line-height:1.4;transition:background .12s,border-color .12s,box-shadow .12s}
button:hover{background:var(--surface-2);border-color:var(--faint)}
button:focus-visible{outline:none;box-shadow:0 0 0 3px var(--accent-ring)}
button.pri{background:var(--btn-pri-bg);border-color:var(--btn-pri-bg);color:var(--btn-pri-ink);font-weight:500}
button.pri:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
button.ghost{background:transparent;border-color:transparent;color:var(--text-2)}
button.ghost:hover{background:var(--surface-3);color:var(--text)}
button.outline{background:var(--surface);border-color:var(--accent-line);color:var(--accent);font-weight:500}
button.outline:hover{background:var(--accent-soft);border-color:var(--accent)}
button.danger,button.danger:hover{background:var(--danger);border-color:var(--danger);color:#fff}
button:disabled{opacity:.45;cursor:default}
input,select,textarea{border:1px solid var(--line-2);border-radius:var(--r-xs);background:var(--surface);padding:4px 8px}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-ring)}
input[type=checkbox]{accent-color:var(--accent)}
::placeholder{color:var(--text-3)}
kbd{font:500 12px/1 var(--font);color:var(--text-2);background:var(--surface);border:1px solid var(--line-2);
  border-bottom-width:2px;border-radius:5px;padding:2px 5px;margin:0 1px}
.scroll::-webkit-scrollbar,.scroll ::-webkit-scrollbar{width:10px}
.scroll::-webkit-scrollbar-thumb,.scroll ::-webkit-scrollbar-thumb{background:var(--line-2);border-radius:10px;border:3px solid transparent;background-clip:content-box}
.scroll::-webkit-scrollbar-thumb:hover,.scroll ::-webkit-scrollbar-thumb:hover{background-color:var(--faint)}
/* page header, same on both pages */
.hdr{height:var(--hdr);display:flex;align-items:center;gap:12px;padding:0 16px;background:var(--surface);
  border-bottom:1px solid var(--line);flex:none}
.hdr .kind{font-size:16px;font-weight:600;white-space:nowrap}
.hdr .pname{font-size:16px;font-weight:500;color:var(--text-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.hdr .meta{font-size:13px;color:var(--text-3);white-space:nowrap;font-variant-numeric:tabular-nums;overflow:hidden;text-overflow:ellipsis;min-width:0}
.hdr .meta b{color:var(--text);font-weight:600}
.hdr .sep{width:1px;height:16px;background:var(--line-2);flex:none}
.hdr .sp{flex:1}
/* white panel used for the right rail sections */
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--sh-1)}
.panel-h{display:flex;align-items:center;gap:8px;padding:9px 12px;font-size:13px;font-weight:600;border-bottom:1px solid var(--line)}
.panel-h .n{color:var(--text-3);font-weight:400}
"""

# Same tokens for a dark context. Used as declarations inside a selector, e.g. `.fs{__DARK__}`.
DARK = DARK_TOKENS

# Option B's look on the existing pages beyond tokens (DESIGN.md "What makes B look like B"): CSS only, and only
# selectors the pages already have. `html` in front so it wins over the page's own rules of the same weight.
FLAVOR = r"""
html .hdr{background:var(--bg-bar);border-bottom-color:transparent}
html #bar{background:var(--bg-bar)}
html #stage,html #pv{border-radius:var(--r-stage);box-shadow:var(--sh-stage)}
html #cap span{background:transparent;text-shadow:0 1px 3px rgba(0,0,0,.9),0 0 14px rgba(0,0,0,.55)}
html .tl-row:not(:hover):not(.drag) #tl{height:var(--track-h)}
html .panel{border-color:transparent}
html #chatDock,html #cb{background:var(--bg-rail)}
html #bar .acts-top button.pri,html #cbSend{border-radius:999px}
html #cbQuick button{background:var(--surface-3);border-color:transparent;color:var(--text-2)}
html #cbIn{background:var(--surface-2);border-color:transparent}
html .shot{border-color:transparent}
html .item.cur{background:var(--surface);box-shadow:var(--sh-1)}
/* inside the 审片 app the shell's toolbar names the episode and the page: drop the page's own title (actions stay) */
html.in-app .hdr .kind,html.in-app .hdr .sep,html.in-app .hdr .pname{display:none}
"""
