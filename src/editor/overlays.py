"""Full-frame RGBA overlays (subtitles, title cards, place tags) drawn with Pillow.

This ffmpeg build has no drawtext/subtitles filter, so text is pre-rendered to PNGs the
size of the output frame and composited with the `overlay` filter.
"""
import hashlib
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Bump when the look of any overlay changes: invalidates cached PNGs and rendered segments.
VERSION = 7  # 7: clause-aware caption wrap

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SUB_FONTS = ["/System/Library/Fonts/STHeiti Medium.ttc",
             "/System/Library/Fonts/Hiragino Sans GB.ttc",
             "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
TITLE_FONTS = [os.path.join(_REPO, "assets/fonts/heavy.otf")] + SUB_FONTS


_NOTDEF = {}

# 9:16 canvas (EDL "canvas": "9:16"): text stays clear of the YouTube mobile UI -- the bottom ~15 %
# (title / channel / progress bar) and the right-hand button column (~12 % of the width).
V_LEFT, V_RIGHT = 0.06, 0.88        # usable x span (fractions of W)
V_TOP = 0.085                       # tags start here (fraction of H), below the top bar
V_CAPTION_BOTTOM = 0.80             # notes / captions end here: lower third, above the bottom UI
V_LAYOUT = 3                        # bump when a 9:16 layout changes: invalidates portrait PNGs + segments only


def _portrait(w, h):
    return h > w


def _dims(w, h):
    """Size part of an overlay cache key (portrait keys carry V_LAYOUT; landscape keys never change)."""
    return f"{w}x{h}v{V_LAYOUT}" if _portrait(w, h) else f"{w}x{h}"


def _glyph(font, ch):
    m = font.getmask(ch)
    return (m.size, bytes(m))


def _covers(font, path, text):
    """True if `font` has a real glyph for every non-ASCII char in `text` (missing glyphs render
    as the .notdef box, e.g. Vietnamese Cơm Tấm / Phở in STHeiti)."""
    chars = {c for c in text if ord(c) > 127 and not c.isspace()}
    if not chars:
        return True
    key = (path, font.size)
    if key not in _NOTDEF:
        _NOTDEF[key] = _glyph(font, "\U000F0000")   # private-use char -> .notdef
    nd = _NOTDEF[key]
    return all(_glyph(font, c) != nd for c in chars)


def _font(paths, size, text=""):
    """First font in `paths` that loads and (when `text` is given) covers all its characters."""
    first = None
    for p in paths:
        try:
            f = ImageFont.truetype(p, size)
        except Exception:
            continue
        first = first or f
        if not text or _covers(f, p, text):
            return f
    return first or ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    """Wrap a caption. If it needs more than one line, break at clause punctuation (，、；：) first so a
    line never ends mid-word (creator, 2026-10-01: "上 / 课"); fall back to the char wrap per clause."""
    if draw.textlength(text, font=font) <= max_w:
        return [text]
    clauses, cur = [], ""
    for ch in text:
        cur += ch
        if ch in "，、；：,;":
            clauses.append(cur); cur = ""
    if cur:
        clauses.append(cur)
    if len(clauses) > 1 and all(draw.textlength(c, font=font) <= max_w for c in clauses):
        lines, line = [], ""
        for c in clauses:
            if line and draw.textlength(line + c, font=font) > max_w:
                lines.append(line); line = c
            else:
                line += c
        lines.append(line)
        return [l.rstrip("，、；：,;") if i < len(lines) - 1 else l for i, l in enumerate(lines)]
    return _wrap_chars(draw, text, font, max_w)


_NO_START = set("》）」』】〉，。、；：！？…”’)]}.,;:!?%")
_NO_END = set("《（「『【〈“‘([{")


def _wrap_chars(draw, text, font, max_w):
    """Greedy wrap that works for CJK (no spaces) and Latin words alike."""
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > max_w and cur:
            # keep a "（译文）" gloss whole: an English line + its Chinese translation wraps as two
            # lines, not "…City Hall（马上路过" / "帕萨迪纳市政厅）"
            gl = cur.rfind("（")
            if gl > 0 and "）" not in cur[gl:]:
                lines.append(cur[:gl].rstrip()); cur = cur[gl:] + ch
                continue
            # kinsoku: a line never starts with closing punctuation (》）」，。) nor ends with an opening one
            # (《（「): carry the char before it along ("《金刚 / 》和…" read badly on the 9:16 chips)
            if ch in _NO_START and len(cur) > 1:
                lines.append(cur[:-1]); cur = cur[-1] + ch
                continue
            if cur[-1] in _NO_END and len(cur) > 1:
                lines.append(cur[:-1]); cur = cur[-1] + ch
                continue
            # don't split an ASCII word if we can back up to a space
            cut = cur.rfind(" ") if ch.isascii() and ch != " " else -1
            if cut > 0:
                lines.append(cur[:cut]); cur = cur[cut + 1:] + ch
            else:
                lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def _cjk(ch):
    return ord(ch) >= 0x2E80


def _wrap_balanced(draw, text, font, max_w):
    """9:16 caption wrap: the fewest lines that fit, then the most even ones, breaking after clause
    punctuation (or before a "（" gloss) where possible; never inside a Latin word or number, never between a
    number and the CJK unit after it (4000英尺, 1976年), kinsoku as in _wrap_chars. A line-end ，、；： is
    dropped like _wrap does. "\n" in the text forces a break. Narrow portrait chips made the greedy wrap
    split words ("巨 / 浪", "4000英 / 尺")."""
    if "\n" in text:
        return [ln for part in text.split("\n") for ln in _wrap_balanced(draw, part, font, max_w)]
    if draw.textlength(text, font=font) <= max_w:
        return [text]
    n, em = len(text), font.size
    soft = "，、；：,;。！？"
    inside, depth = [False] * (n + 1), 0     # no break inside a short 《title》 / “quote” / （gloss）
    pairs = {"《": "》", "“": "”", "（": "）", "(": ")"}
    stack = []
    for k, ch in enumerate(text):
        if ch in pairs:
            stack.append((k, pairs[ch]))
        elif stack and ch == stack[-1][1]:
            a, _ = stack.pop()
            if k - a <= 12:
                for m in range(a + 1, k + 1):
                    inside[m] = True

    def shown(i, j):
        ln = text[i:j].strip()
        return ln.rstrip("，、；：,;") if j < n else ln

    def brk(j):   # cost of breaking between text[j-1] and text[j]; None = not allowed
        a, b = text[j - 1], text[j]
        if b in _NO_START or a in _NO_END or inside[j]:
            return None
        if a.isalnum() and b.isalnum() and not (_cjk(a) and _cjk(b)):
            if not (_cjk(a) or _cjk(b)) or a.isdigit():
                return None   # inside a Latin word / number, or number + its unit
        if a in soft:
            return 0.0
        if b in "（(" or a in "）)":
            return 1.0
        if a == " " or b == " ":
            return 25.0                      # Latin-CJK seam ("Kalalau 步道"): fine, not ideal
        return 80.0                          # mid-phrase: worse than one more line
    INF = float("inf")
    best = [(INF, 0, -1)] * (n + 1)     # (cost, lines, prev)
    best[0] = (0.0, 0, -1)
    for j in range(1, n + 1):
        bj = 0.0 if j == n else brk(j)
        if bj is None:
            continue
        for i in range(j - 1, -1, -1):
            if best[i][0] == INF:
                continue
            wd = draw.textlength(shown(i, j), font=font)
            if wd > max_w:
                if draw.textlength(text[i:j], font=font) > max_w * 1.6:
                    break
                continue
            slack = (max_w - wd) / em
            c = best[i][0] + bj + 40.0 + slack * slack * (0.1 if j == n else 0.3)
            if c < best[j][0]:
                best[j] = (c, best[i][1] + 1, i)
    if best[n][0] == INF:
        return _wrap_chars(draw, text, font, max_w)
    cuts, j = [], n
    while j > 0:
        i = best[j][2]
        cuts.append((i, j))
        j = i
    return [shown(i, j) for i, j in reversed(cuts)]


def _dotted_parts(text):
    """'可爱岛 · 从海上看群崖' -> ['可爱岛', '从海上看群崖'] (None when there is no middle dot)."""
    if "·" not in text:
        return None
    return [p.strip() for p in text.split("·")]


def _text_dotted(d, xy, text, font, fill, anchor="la", **kw):
    """Draw text whose ' · ' separators get an even gap on both sides (the CJK fonts' · hugs the left).
    Returns the drawn width. Only 'la' / 'lm' anchors."""
    parts = _dotted_parts(text)
    if not parts:
        d.text(xy, text, font=font, fill=fill, anchor=anchor, **kw)
        return d.textlength(text, font=font)
    size = font.size
    gap, r = size * 0.36, max(2, size * 0.075)
    x, y = xy
    bb = d.textbbox((0, 0), "中", font=font, anchor=anchor)
    cy = y + (bb[1] + bb[3]) / 2
    for k, p in enumerate(parts):
        if k:
            x += gap
            d.ellipse([x, cy - r, x + 2 * r, cy + r], fill=fill)
            x += 2 * r + gap
        d.text((x, y), p, font=font, fill=fill, anchor=anchor, **kw)
        x += d.textlength(p, font=font)
    return x - xy[0]


def _len_dotted(d, text, font):
    parts = _dotted_parts(text)
    if not parts:
        return d.textlength(text, font=font)
    size = font.size
    return sum(d.textlength(p, font=font) for p in parts) + (len(parts) - 1) * (size * 0.72 + 2 * max(2, size * 0.075))


def _cached(cache_dir, key, render):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, hashlib.sha1(f"{VERSION}|{key}".encode()).hexdigest()[:16] + ".png")
    if not os.path.exists(path):
        render().save(path)
    return path


NOTE_COLOR = (255, 226, 130, 255)


PAPER_NOTE = {"bg": (246, 238, 218, 236), "fg": (28, 40, 70, 255), "bar": (191, 13, 62, 255)}


def _note_paper_layout(d, text, w, h):
    if _portrait(w, h):   # phone-sized chip; the whole chip fits the safe x span
        size = int(w * 0.05)
        f = _font(SUB_FONTS, size, text)
        lines = _wrap_balanced(d, text, f, w * (V_RIGHT - V_LEFT) - size * 1.9)
    else:
        size = int(h * 0.042)
        f = _font(SUB_FONTS, size, text)
        lines = _wrap(d, text, f, w * 0.80)
    lh = int(size * 1.32)
    padx, pady, bar = int(size * 0.62), int(size * 0.34), max(4, int(size * 0.11))
    tw = max(d.textlength(ln, font=f) for ln in lines)
    bw = int(tw + 2 * padx + bar + size * 0.32)
    bh = int(lh * len(lines) - (lh - size) + 2 * pady)
    return size, f, lines, lh, padx, pady, bar, bw, bh


def _note_paper(text, w, h, pos):
    """Editor note as a cream paper chip (navy text, Texas-red bar on the left, soft shadow): creator found
    the yellow notes odd (ep 110 review #32, 2026-10-20); the critic sub-agent picked this over dark/white boxes."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    size, f, lines, lh, padx, pady, bar, bw, bh = _note_paper_layout(d, text, w, h)
    if _portrait(w, h):   # left-aligned with the place tag, in the lower third
        x0 = int(w * V_LEFT)
        y0 = int(h * 0.16) if pos == "top" else int(h * V_CAPTION_BOTTOM) - bh
    else:
        x0 = (w - bw) // 2
        y0 = int(h * 0.06) if pos == "top" else h - int(h * 0.07) - bh
    r = int(size * 0.28)
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0, y0 + int(h * 0.004), x0 + bw, y0 + bh + int(h * 0.004)], radius=r,
                                          fill=(0, 0, 0, 70))
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(h * 0.012)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=r, fill=PAPER_NOTE["bg"])
    bx = x0 + int(size * 0.32)
    d.rounded_rectangle([bx, y0 + int(pady * 0.9), bx + bar, y0 + bh - int(pady * 0.9)], radius=bar // 2,
                        fill=PAPER_NOTE["bar"])
    tx = bx + bar + padx
    y = y0 + pady
    for ln in lines:
        d.text((tx, y - int(size * 0.06)), ln, font=f, fill=PAPER_NOTE["fg"])
        y += lh
    return im


def subtitle(text, w, h, cache_dir, kind="speech", pos="bottom", style="yellow"):
    """kind='speech' (what people say, white) or 'note' (editor's explanatory caption for a
    silent shot — soft yellow, slightly smaller, so viewers can tell it isn't dialogue).
    style='paper' (EDL "note_style"): notes become a cream chip with navy text instead (ep 110)."""
    if kind == "note" and style == "paper":
        return _cached(cache_dir, f"sub|note-paper|{text}|{_dims(w, h)}" + ("|top" if pos == "top" else ""),
                       lambda: _note_paper(text, w, h, pos))

    def render():
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        size, lines, f, cx, y = _caption_layout(d, text, w, h, kind, pos)
        lh = int(size * 1.3)
        for ln in lines:
            d.text((cx, y), ln, font=f, fill=NOTE_COLOR if kind == "note" else "white", anchor="ma",
                   stroke_width=max(2, size // 8), stroke_fill=(0, 0, 0, 230))
            y += lh
        return im
    return _cached(cache_dir, f"sub|{kind}|{text}|{_dims(w, h)}" + ("|top" if pos == "top" else ""), render)


def _caption_layout(d, text, w, h, kind, pos):
    """-> (size, lines, font, centre x, first-line y) of a plain (white speech / yellow note) caption."""
    if _portrait(w, h):
        size = int(w * (0.056 if kind == "note" else 0.062))
        f = _font(SUB_FONTS, size, text)
        lines = _wrap_balanced(d, text, f, w * (V_RIGHT - V_LEFT))
        cx = w * (V_LEFT + V_RIGHT) / 2   # centred in the safe span, clear of the buttons
        bottom = int(h * V_CAPTION_BOTTOM)
        top = int(h * 0.16)
    else:
        size = int(h * (0.046 if kind == "note" else 0.052))
        f = _font(SUB_FONTS, size, text)
        lines = _wrap(d, text, f, w * 0.84)
        cx = w / 2
        bottom = h - int(h * 0.07)
        top = int(h * 0.06)
    # pos="top": a note shown at the top while someone is talking (the bottom holds their words)
    y = top if pos == "top" else bottom - int(size * 1.3) * len(lines)
    return size, lines, f, cx, y


def subtitle_top(text, w, h, kind="speech", style="yellow"):
    """Top y (px) of a bottom caption's first line, as `subtitle` lays it out (same font, wrap and spacing)."""
    d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    if kind == "note" and style == "paper":
        bottom = int(h * V_CAPTION_BOTTOM) if _portrait(w, h) else h - int(h * 0.07)
        return bottom - _note_paper_layout(d, text, w, h)[8]
    return _caption_layout(d, text, w, h, kind, "bottom")[4]


def _title_card_v(text, sub, kicker, w, h, limit=None):
    """9:16 title: an optional letter-spaced Latin kicker, the big title, a short yellow rule and the sub
    line, left-aligned on the safe margin; the block ends at 78 % of H (over the water, below the sky where
    white text vanishes into cloud), or above `limit`."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    probe = ImageDraw.Draw(im)
    x, right = int(w * 0.07), w * (V_RIGHT - 0.01)   # the title sits beside the button column too
    big, small, ks = int(w * 0.165), int(w * 0.052), int(w * 0.033)
    fb = _font(TITLE_FONTS, big, text)
    while big > w * 0.08 and probe.textbbox((x, 0), text, font=fb)[2] > right:
        big = int(big * 0.95)
        fb = _font(TITLE_FONTS, big, text)
    fs = _font(SUB_FONTS, small, sub or "")
    while sub and small > w * 0.03 and x + _len_dotted(probe, sub, fs) > right:
        small = int(small * 0.95)
        fs = _font(SUB_FONTS, small, sub)
    fk = _font(SUB_FONTS, ks, kicker or "")
    track = ks * 0.28                                   # letter spacing for the kicker

    def kick_w():
        return sum(probe.textlength(c, font=fk) for c in kicker) + track * (len(kicker) - 1)
    while kicker and ks > w * 0.02 and kick_w() > right - x:
        ks = int(ks * 0.95)
        fk = _font(SUB_FONTS, ks, kicker)
        track = ks * 0.28
    gap, bar_h = int(w * 0.03), max(4, w // 160)
    # heights from the real ink boxes (heavy CJK faces sit well inside their nominal size)
    bb = probe.textbbox((0, 0), text, font=fb)
    kb = probe.textbbox((0, 0), kicker, font=fk) if kicker else (0, 0, 0, 0)
    sb = probe.textbbox((0, 0), sub, font=fs) if sub else (0, 0, 0, 0)
    block = (kb[3] - kb[1] + gap if kicker else 0) + (bb[3] - bb[1]) + (gap + bar_h + gap + sb[3] - sb[1] if sub else 0)
    end = int(h * 0.78)
    if limit is not None:
        end = min(end, int(limit))
    top = max(int(h * 0.12), end - block)
    lay = []                                            # (kind, x, y_draw, text, font)
    y = top
    if kicker:
        lay.append(("k", x, y - kb[1], kicker, fk))
        y += kb[3] - kb[1] + gap
    lay.append(("t", x, y - bb[1], text, fb))
    y += bb[3] - bb[1]
    bar_y = None
    if sub:
        bar_y = y + gap
        y = bar_y + bar_h + gap
        lay.append(("s", x, y - sb[1], sub, fs))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    off = max(3, w // 300)

    def draw_kicker(dr, x0, y0, fill):
        cx = x0
        for c in kicker:
            dr.text((cx, y0), c, font=fk, fill=fill)
            cx += probe.textlength(c, font=fk) + track
    for kind, lx, ly, t, f in lay:
        if kind == "k":
            draw_kicker(sd, lx + off, ly + off, (0, 0, 0, 190))
        elif kind == "s":
            _text_dotted(sd, (lx + off, ly + off), t, f, (0, 0, 0, 180))
        else:
            sd.text((lx + off, ly + off), t, font=f, fill=(0, 0, 0, 180))
    im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(w * 0.008)))
    d = ImageDraw.Draw(im)
    for kind, lx, ly, t, f in lay:
        if kind == "k":
            draw_kicker(d, lx, ly, (255, 214, 90, 255))
        elif kind == "t":
            d.text((lx, ly), t, font=f, fill="white")
        else:
            _text_dotted(d, (lx, ly), t, f, "white", stroke_width=max(2, small // 18), stroke_fill=(0, 0, 0, 200))
    if bar_y is not None:
        d.rectangle([x, bar_y, x + int(w * 0.09), bar_y + bar_h], fill=(255, 214, 90, 255))
    return im


def title_card(text, sub, w, h, cache_dir, limit=None, kicker=""):
    """Big lower-left title with a soft shadow, e.g. 'Day 1' / '圣约翰岛 St. John'.
    `limit` (px): the title block's ink must end above it, e.g. the top of a two-line caption shown at the
    same time; the block moves up when needed (creator, ep 100 review: title sub-line ran into the caption).
    `kicker`: a small letter-spaced line above the title (9:16 canvas only so far)."""
    if _portrait(w, h):
        return _cached(cache_dir, f"title-v|{text}|{sub}|{kicker}|{_dims(w, h)}" + (f"|lim{int(limit)}" if limit is not None else ""),
                       lambda: _title_card_v(text, sub, kicker, w, h, limit))

    def render():
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        big, small = int(h * 0.12), int(h * 0.045)
        x, y = int(w * 0.07), int(h * 0.58)
        # Shrink to fit: long EN+ZH titles ran off the right edge (ep 100 QA). Keep ink inside 93 % of the width.
        probe = ImageDraw.Draw(im)
        fb = _font(TITLE_FONTS, big, text)
        while big > h * 0.05 and probe.textbbox((x, y), text, font=fb)[2] > w * 0.93:
            big = int(big * 0.94)
            fb = _font(TITLE_FONTS, big, text)
        fs = _font(SUB_FONTS, small, sub or "")
        while sub and small > h * 0.025 and probe.textbbox((x, y), sub, font=fs)[2] > w * 0.93:
            small = int(small * 0.94)
            fs = _font(SUB_FONTS, small, sub or "")
        # Lay out from the glyphs' real ink box — heavy CJK faces run well below the nominal size.
        gap, bar_h = int(h * 0.022), max(3, h // 300)

        def layout(y):
            bottom = probe.textbbox((x, y), text, font=fb)[3]
            bar_y = bottom + gap
            sub_y = bar_y + bar_h + gap
            end = probe.textbbox((x, sub_y), sub, font=fs)[3] if sub else bar_y + bar_h
            return bar_y, sub_y, end
        bar_y, sub_y, end = layout(y)
        if limit is not None and end > limit:  # lift the whole block clear of the caption below it
            y = max(int(h * 0.12), y - (end - int(limit)))
            bar_y, sub_y, end = layout(y)
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.text((x + 4, y + 4), text, font=fb, fill=(0, 0, 0, 170))
        if sub:
            sd.text((x + 3, sub_y + 3), sub, font=fs, fill=(0, 0, 0, 170))
        im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(h * 0.006)))
        d = ImageDraw.Draw(im)
        d.text((x, y), text, font=fb, fill="white")
        if sub:
            d.rectangle([x, bar_y, x + int(w * 0.05), bar_y + bar_h], fill=(255, 214, 90, 255))
            # thin dark outline: the sub line was unreadable over bright rock / sand (ep 86 QA)
            d.text((x, sub_y), sub, font=fs, fill="white", stroke_width=max(2, small // 18),
                   stroke_fill=(0, 0, 0, 200))
        return im
    return _cached(cache_dir, f"title|{text}|{sub}|{w}x{h}" + (f"|lim{int(limit)}" if limit is not None else ""), render)


def place_tag(text, w, h, cache_dir, pos="tl"):
    """Small translucent pill: a location label (top-left), or with pos="tr" top-right, e.g. a
    trip-series day marker on a card whose top-left already holds the card's own title."""
    def render():
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        v = _portrait(w, h)
        size = int(w * 0.046) if v else int(h * 0.042)
        f = _font(SUB_FONTS, size, text)
        pad = size * 0.6
        tw = _len_dotted(d, text, f) if v else d.textlength(text, font=f)
        x, y = (int(w * V_LEFT), int(h * V_TOP)) if v else (int(w * 0.04), int(h * 0.05))
        if pos == "tr":
            x = int(w * (0.94 if v else 0.96) - (tw + pad * 2 + size * 0.7))
        d.rounded_rectangle([x, y, x + tw + pad * 2 + size * 0.7, y + size + pad * 1.4],
                            radius=int(size * 0.5), fill=(0, 0, 0, 120))
        d.ellipse([x + pad, y + pad * 0.7 + size * 0.3, x + pad + size * 0.4, y + pad * 0.7 + size * 0.7],
                  fill=(255, 214, 90, 255))
        # centre the glyphs' real ink on the pill's midline (nominal top sat low, 117 review)
        bb = d.textbbox((0, 0), text, font=f)
        cy = y + (size + pad * 1.4) / 2
        if v:
            _text_dotted(d, (x + pad + size * 0.7, cy - (bb[1] + bb[3]) / 2), text, f, "white")
        else:
            d.text((x + pad + size * 0.7, cy - (bb[1] + bb[3]) / 2), text, font=f, fill="white")
        return im
    return _cached(cache_dir, f"tag2|{text}|{_dims(w, h)}" + (f"|{pos}" if pos != "tl" else ""), render)


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def card(text, sub, w, h, cache_dir, bg="#ffd84d", fg="#1f2937"):
    """Full-frame playful time card ("两小时后……"): sunburst background, tilted heavy text with a
    thick white outline. Original design — no borrowed show branding."""
    def render():
        import math
        base = _hex(bg)
        light = tuple(min(255, int(v + (255 - v) * 0.35)) for v in base)
        im = Image.new("RGBA", (w, h), base + (255,))
        d = ImageDraw.Draw(im)
        cx, cy, r, n = w / 2, h / 2, math.hypot(w, h), 18
        for k in range(0, n * 2, 2):
            a0, a1 = 2 * math.pi * k / (n * 2), 2 * math.pi * (k + 1) / (n * 2)
            d.polygon([(cx, cy), (cx + r * math.cos(a0), cy + r * math.sin(a0)),
                       (cx + r * math.cos(a1), cy + r * math.sin(a1))], fill=light + (255,))
        # soft vignette so the text pops
        vg = Image.new("L", (w, h), 0)
        ImageDraw.Draw(vg).ellipse([-w * 0.2, -h * 0.35, w * 1.2, h * 1.35], fill=255)
        vg = vg.filter(ImageFilter.GaussianBlur(h * 0.12))
        dark = Image.new("RGBA", (w, h), (0, 0, 0, 90))
        im = Image.composite(im, Image.alpha_composite(im, dark), vg)

        size = int(h * 0.15)
        f = _font(TITLE_FONTS, size, text)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((w / 2, h / 2 - (size * 0.35 if sub else 0)), text, font=f, fill=_hex(fg) + (255,),
                anchor="mm", stroke_width=max(4, size // 9), stroke_fill=(255, 255, 255, 255))
        if sub:
            fs = _font(SUB_FONTS, int(h * 0.05), sub)
            ld.text((w / 2, h / 2 + size * 0.75), sub, font=fs, fill=_hex(fg) + (255,), anchor="mm",
                    stroke_width=max(2, h // 250), stroke_fill=(255, 255, 255, 255))
        layer = layer.rotate(-4, resample=Image.BICUBIC, center=(w / 2, h / 2))
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 110), (int(h * 0.008), int(h * 0.012)), layer.split()[3])
        im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(h * 0.006)))
        return Image.alpha_composite(im, layer).convert("RGB")
    return _cached(cache_dir, f"card|{text}|{sub}|{bg}|{fg}|{w}x{h}", render)


def arrow(label, x, y, w, h, cache_dir):
    """A bold labelled arrow whose tip points at (x, y) (0-1 of the frame) — for animals too
    small to see. Tail sits above the target (below it if the target is near the top edge)."""
    def render():
        import math
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        tx, ty = x * w, y * h
        L = h * 0.16
        up = ty > h * 0.3
        ang = math.radians(-60 if up else 60)          # tail up-left (or down-left)
        sx, sy = tx - L * math.cos(ang) * 0.6, ty + L * math.sin(ang)
        gap = h * 0.012                                  # don't cover the animal itself
        ex, ey = tx - gap * math.cos(ang) * 0.6, ty + gap * math.sin(ang)
        lw, head = max(4, h // 110), h * 0.035
        # shaft + head, drawn twice: dark outline then yellow
        a = math.atan2(ey - sy, ex - sx)
        pts = [(ex, ey), (ex - head * math.cos(a - 0.45), ey - head * math.sin(a - 0.45)),
               (ex - head * math.cos(a + 0.45), ey - head * math.sin(a + 0.45))]
        for col, extra in (((0, 0, 0, 200), lw * 0.9), ((255, 214, 90, 255), 0)):
            d.line([(sx, sy), (ex - head * 0.6 * math.cos(a), ey - head * 0.6 * math.sin(a))],
                   fill=col, width=int(lw + extra))
            d.polygon(pts, fill=col, outline=col if extra else None)
            if extra:
                d.line(pts + [pts[0]], fill=col, width=int(extra))
        if label:
            size = int(h * 0.04)
            f = _font(SUB_FONTS, size, label)
            tw = d.textlength(label, font=f)
            bx = min(max(sx - tw / 2 - size * 0.4, 8), w - tw - size - 8)
            by = sy - size * 1.6 if up else sy + size * 0.2
            d.rounded_rectangle([bx, by, bx + tw + size * 0.8, by + size * 1.4], radius=int(size * 0.4),
                                fill=(0, 0, 0, 150))
            d.text((bx + size * 0.4, by + size * 0.15), label, font=f, fill=(255, 214, 90, 255))
        return im
    return _cached(cache_dir, f"arrow|{label}|{x:.3f}|{y:.3f}|{w}x{h}", render)


def spotlight(label, x, y, r, w, h, cache_dir, dim=0.55):
    """Dim the whole frame except a soft-edged circle of radius r (fraction of the frame height)
    centred on (x, y) (0-1 of the frame), with a thin ring and an optional label beside it —
    for an animal hiding behind a fence or in shade that an arrow alone doesn't reveal."""
    def render():
        cx, cy, rr = x * w, y * h, r * h
        mask = Image.new("L", (w, h), int(255 * dim))
        ImageDraw.Draw(mask).ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=0)
        mask = mask.filter(ImageFilter.GaussianBlur(rr * 0.12))
        im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        im.putalpha(mask)
        d = ImageDraw.Draw(im)
        lw = max(3, h // 270)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(255, 214, 90, 230), width=lw)
        if label:
            size = int(h * 0.045)
            f = _font(SUB_FONTS, size, label)
            tw = d.textlength(label, font=f)
            right = cx + rr + size * 0.6 + tw + size < w
            bx = cx + rr + size * 0.5 if right else cx - rr - size * 0.5 - tw - size * 0.8
            bx = min(max(bx, 8), w - tw - size - 8)
            by = min(max(cy - size * 0.7, 8), h - size * 2)
            d.rounded_rectangle([bx, by, bx + tw + size * 0.8, by + size * 1.4], radius=int(size * 0.4),
                                fill=(0, 0, 0, 170))
            d.text((bx + size * 0.4, by + size * 0.15), label, font=f, fill=(255, 214, 90, 255))
        return im
    return _cached(cache_dir, f"spot|{label}|{x:.3f}|{y:.3f}|{r:.3f}|{dim}|{w}x{h}", render)


GAUGE_FPS = 10


def gauge_frames(g, dur, w, h, cache_dir):
    """Animated meter (depth / altitude) for one shot, as a PNG sequence at GAUGE_FPS.

    g = {"from": 0, "to": -80, "max": -230, "label": "深度", "unit": "米", "step": 50,
         "t0": 0, "t1": dur (shot-local s), "fade_in": false, "fade_out": false}
    The value eases from→to between t0 and t1; a vertical track (0 at the top, `max` at the
    bottom, ticks every `step`) fills up to a marker. Returns (pattern, x, y) for an
    image2 input overlaid at (x, y) — the images are only the panel's size, not the frame's.
    """
    import math
    v0, v1 = float(g.get("from", 0)), float(g.get("to", 0))
    vmax = float(g.get("max", v1 or 1)) or 1.0
    t0, t1 = float(g.get("t0", 0)), float(g.get("t1", dur))
    label, unit, step = g.get("label", ""), g.get("unit", ""), float(g.get("step", 50))
    pw, ph = int(w * 0.125), int(h * 0.60)
    x, y = w - int(w * 0.03) - pw, int(h * 0.17)
    n = max(1, int(math.ceil(dur * GAUGE_FPS)))
    key = hashlib.sha1(f"{VERSION}|gauge|{sorted(g.items())}|{dur:.3f}|{w}x{h}".encode()).hexdigest()[:16]
    d_out = os.path.join(cache_dir, f"gauge_{key}")
    pattern = os.path.join(d_out, "%04d.png")
    if os.path.exists(os.path.join(d_out, f"{n - 1:04d}.png")):
        return pattern, x, y
    os.makedirs(d_out, exist_ok=True)
    fl, fv, ft = _font(SUB_FONTS, int(h * 0.030)), _font(TITLE_FONTS, int(h * 0.050)), _font(SUB_FONTS, int(h * 0.020))
    ty0, ty1 = ph * 0.20, ph * 0.94                    # track top (value 0) / bottom (value max)
    tx = pw * 0.30
    yellow, white = (255, 214, 90, 255), (255, 255, 255, 235)

    def ypos(v):
        return ty0 + (ty1 - ty0) * max(0.0, min(1.0, v / vmax))

    for k in range(n):
        t = k / GAUGE_FPS
        u = max(0.0, min(1.0, (t - t0) / max(1e-6, t1 - t0)))
        v = v0 + (v1 - v0) * (0.5 - 0.5 * math.cos(math.pi * u))
        im = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=int(pw * 0.12), fill=(0, 0, 0, 125))
        if label:
            d.text((pw / 2, ph * 0.035), label, font=fl, fill=white, anchor="mt")
        val = f"{round(v):d}".replace("-", "−") + (f" {unit}" if unit else "")
        d.text((pw / 2, ph * 0.09), val, font=fv, fill=yellow, anchor="mt",
               stroke_width=max(2, h // 400), stroke_fill=(0, 0, 0, 220))
        lw = max(4, int(w * 0.004))
        d.line([(tx, ty0), (tx, ty1)], fill=(255, 255, 255, 110), width=lw)
        m = 0.0
        while abs(m) <= abs(vmax) + 1e-6:              # ticks every `step`, labelled
            yy = ypos(m)
            d.line([(tx - lw * 2, yy), (tx + lw * 2, yy)], fill=(255, 255, 255, 170), width=max(2, lw // 2))
            d.text((tx + lw * 3.5, yy), f"{int(m)}".replace("-", "−"), font=ft, fill=(255, 255, 255, 190), anchor="lm")
            m += step if vmax > 0 else -step
        ym = ypos(v)
        d.line([(tx, ty0), (tx, ym)], fill=yellow, width=lw)
        r = lw * 2.4
        d.ellipse([tx - r, ym - r, tx + r, ym + r], fill=yellow, outline=(0, 0, 0, 220), width=max(2, lw // 2))
        a = 1.0
        if g.get("fade_in"):
            a = min(a, t / 0.3)
        if g.get("fade_out"):
            a = min(a, (dur - t) / 0.3)
        if a < 1.0:
            im.putalpha(im.getchannel("A").point(lambda p: int(p * max(0.0, a))))
        im.save(os.path.join(d_out, f"{k:04d}.png"), compress_level=1)
    return pattern, x, y
