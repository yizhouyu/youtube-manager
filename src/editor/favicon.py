"""Small inline SVG favicons for the local review pages, so the creator can tell the tabs apart.

    from src.editor.favicon import link
    html = html.replace("</head>", link("cut") + "</head>")

Kinds: "raw" (footage player), "cut" (review page), "thumb" (thumbnail picker), "short" (Shorts).
"""
from urllib.parse import quote

_BASE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
         '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
         '<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>'
         '<rect x="2" y="2" width="60" height="60" rx="16" fill="url(#g)"/>{glyph}</svg>')

_KINDS = {
    # film strip: raw footage
    "raw": ("#3b82f6", "#1e3a8a",
            '<rect x="14" y="18" width="36" height="28" rx="4" fill="#fff"/>'
            '<g fill="#1e3a8a"><rect x="17" y="21" width="4" height="4" rx="1"/><rect x="17" y="30" width="4" height="4" rx="1"/>'
            '<rect x="17" y="39" width="4" height="4" rx="1"/><rect x="43" y="21" width="4" height="4" rx="1"/>'
            '<rect x="43" y="30" width="4" height="4" rx="1"/><rect x="43" y="39" width="4" height="4" rx="1"/></g>'),
    # play button: the cut
    "cut": ("#f43f5e", "#9f1239",
            '<circle cx="32" cy="32" r="17" fill="#fff"/><path d="M28 23 L42 32 L28 41 Z" fill="#be123c"/>'),
    # photo cards: thumbnail picker
    "thumb": ("#f59e0b", "#b45309",
              '<rect x="15" y="20" width="26" height="20" rx="3" fill="#fff" transform="rotate(-10 28 30)"/>'
              '<rect x="23" y="24" width="26" height="20" rx="3" fill="#fff" stroke="#b45309" stroke-width="2"/>'
              '<path d="M26 41 L33 33 L38 38 L41 35 L46 41 Z" fill="#b45309"/><circle cx="41" cy="29" r="2.5" fill="#b45309"/>'),
    # vertical phone: Shorts
    "short": ("#a855f7", "#6b21a8",
              '<rect x="22" y="12" width="20" height="40" rx="5" fill="#fff"/>'
              '<path d="M29 26 L37 32 L29 38 Z" fill="#6b21a8"/>'),
}


def svg(kind):
    a, b, glyph = _KINDS[kind]
    return _BASE.format(a=a, b=b, glyph=glyph)


def link(kind):
    return f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{quote(svg(kind))}">'
