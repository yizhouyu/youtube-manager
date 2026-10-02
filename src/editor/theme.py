"""Shared look for the local review pages (footage player 8765, cut review 8766) and their widgets
(questions panel, chat box): one CSS-variable palette plus a few base element styles.

    from . import theme
    page = page.replace("__THEME_CSS__", theme.CSS)

Light only (color-scheme: light): the creator works in macOS light mode and the video stage stays
dark either way. Every colour on the pages and in the widgets comes from these tokens, so a change
here restyles both pages, and a dark block can be added later in one place.
"""

CSS = r"""
:root{
  color-scheme:light;      /* he works in macOS light mode: keep controls/scrollbars light; the stage stays dark */
  --font:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Helvetica Neue",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,monospace;
  --bg:#f5f6f8;            /* page */
  --surface:#ffffff;       /* panels, cards */
  --surface-2:#f8f9fb;     /* quiet fills: inputs, list rows, chat thread */
  --surface-3:#eef0f3;     /* hover / pressed fills, removed shots */
  --line:#e4e7ec;          /* hairlines */
  --line-2:#d0d5dd;        /* control borders */
  --text:#1c2127;
  --text-2:#475467;        /* secondary */
  --text-3:#6b7280;        /* hints, meta */
  --faint:#98a2b3;         /* non-text only */
  --accent:#2563eb;        /* one blue: the primary action, links, the current item */
  --accent-hover:#1d4ed8;
  --accent-soft:#eef4ff;
  --accent-line:#c7d7fe;
  --accent-ring:rgba(37,99,235,.2);
  --used:#22c55e;          /* "used in the cut" green (timeline on the dark stage, clip bars) */
  --unused:#d5d9e0;
  --ok:#067647; --ok-soft:#ecfdf3;
  --danger:#b42318; --danger-soft:#fef3f2;
  --q:#f59e0b; --q-ink:#8a5a00; --q-soft:#fffbeb; --q-line:#fde68a;   /* questions: amber */
  --stage:#0b0d10; --stage-ink:rgba(255,255,255,.92); --stage-mute:rgba(255,255,255,.62);
  --r-xs:6px; --r-sm:8px; --r:10px; --r-lg:12px;
  --sh-1:0 1px 2px rgba(16,24,40,.06);
  --sh-2:0 8px 24px rgba(16,24,40,.10);
  --hdr:52px;              /* page header height */
}
*{box-sizing:border-box}
html{-webkit-font-smoothing:antialiased}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 var(--font)}
button,input,select,textarea{font:inherit;color:inherit}
button{border:1px solid var(--line-2);background:var(--surface);color:var(--text);border-radius:var(--r-sm);
  padding:5px 12px;cursor:pointer;line-height:1.4;transition:background .12s,border-color .12s,box-shadow .12s}
button:hover{background:var(--surface-2);border-color:#b9c0cb}
button:focus-visible{outline:none;box-shadow:0 0 0 3px var(--accent-ring)}
button.pri{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:500}
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
.scroll::-webkit-scrollbar-thumb,.scroll ::-webkit-scrollbar-thumb{background:#d5d9e0;border-radius:10px;border:3px solid transparent;background-clip:content-box}
.scroll::-webkit-scrollbar-thumb:hover,.scroll ::-webkit-scrollbar-thumb:hover{background-color:#b9c0cb}
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
