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


def _cached(cache_dir, key, render):
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, hashlib.sha1(f"{VERSION}|{key}".encode()).hexdigest()[:16] + ".png")
    if not os.path.exists(path):
        render().save(path)
    return path


NOTE_COLOR = (255, 226, 130, 255)


def subtitle(text, w, h, cache_dir, kind="speech"):
    """kind='speech' (what people say, white) or 'note' (editor's explanatory caption for a
    silent shot — soft yellow, slightly smaller, so viewers can tell it isn't dialogue)."""
    def render():
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        size = int(h * (0.046 if kind == "note" else 0.052))
        f = _font(SUB_FONTS, size, text)
        lines = _wrap(d, text, f, w * 0.84)
        lh = int(size * 1.3)
        y = h - int(h * 0.07) - lh * len(lines)
        for ln in lines:
            d.text((w / 2, y), ln, font=f, fill=NOTE_COLOR if kind == "note" else "white", anchor="ma",
                   stroke_width=max(2, size // 8), stroke_fill=(0, 0, 0, 230))
            y += lh
        return im
    return _cached(cache_dir, f"sub|{kind}|{text}|{w}x{h}", render)


def title_card(text, sub, w, h, cache_dir):
    """Big lower-left title with a soft shadow, e.g. 'Day 1' / '圣约翰岛 St. John'."""
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
        bottom = ImageDraw.Draw(im).textbbox((x, y), text, font=fb)[3]
        gap, bar_h = int(h * 0.022), max(3, h // 300)
        bar_y = bottom + gap
        sub_y = bar_y + bar_h + gap
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
    return _cached(cache_dir, f"title|{text}|{sub}|{w}x{h}", render)


def place_tag(text, w, h, cache_dir, pos="tl"):
    """Small translucent pill: a location label (top-left), or with pos="tr" top-right, e.g. a
    trip-series day marker on a card whose top-left already holds the card's own title."""
    def render():
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        size = int(h * 0.042)
        f = _font(SUB_FONTS, size, text)
        pad = size * 0.6
        tw = d.textlength(text, font=f)
        x, y = int(w * 0.04), int(h * 0.05)
        if pos == "tr":
            x = int(w * 0.96 - (tw + pad * 2 + size * 0.7))
        d.rounded_rectangle([x, y, x + tw + pad * 2 + size * 0.7, y + size + pad * 1.4],
                            radius=int(size * 0.5), fill=(0, 0, 0, 120))
        d.ellipse([x + pad, y + pad * 0.7 + size * 0.3, x + pad + size * 0.4, y + pad * 0.7 + size * 0.7],
                  fill=(255, 214, 90, 255))
        d.text((x + pad + size * 0.7, y + pad * 0.7), text, font=f, fill="white")
        return im
    return _cached(cache_dir, f"tag|{text}|{w}x{h}" + (f"|{pos}" if pos != "tl" else ""), render)


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
