"""Full-frame RGBA overlays (subtitles, title cards, place tags) drawn with Pillow.

This ffmpeg build has no drawtext/subtitles filter, so text is pre-rendered to PNGs the
size of the output frame and composited with the `overlay` filter.
"""
import hashlib
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SUB_FONTS = ["/System/Library/Fonts/STHeiti Medium.ttc",
             "/System/Library/Fonts/Hiragino Sans GB.ttc",
             "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
TITLE_FONTS = [os.path.join(_REPO, "assets/fonts/heavy.otf")] + SUB_FONTS


def _font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    """Greedy wrap that works for CJK (no spaces) and Latin words alike."""
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > max_w and cur:
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
    path = os.path.join(cache_dir, hashlib.sha1(key.encode()).hexdigest()[:16] + ".png")
    if not os.path.exists(path):
        render().save(path)
    return path


def subtitle(text, w, h, cache_dir):
    def render():
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        size = int(h * 0.052)
        f = _font(SUB_FONTS, size)
        lines = _wrap(d, text, f, w * 0.84)
        lh = int(size * 1.3)
        y = h - int(h * 0.07) - lh * len(lines)
        for ln in lines:
            d.text((w / 2, y), ln, font=f, fill="white", anchor="ma",
                   stroke_width=max(2, size // 8), stroke_fill=(0, 0, 0, 230))
            y += lh
        return im
    return _cached(cache_dir, f"sub|{text}|{w}x{h}", render)


def title_card(text, sub, w, h, cache_dir):
    """Big lower-left title with a soft shadow, e.g. 'Day 1' / '圣约翰岛 St. John'."""
    def render():
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        big, small = int(h * 0.12), int(h * 0.045)
        fb, fs = _font(TITLE_FONTS, big), _font(SUB_FONTS, small)
        x, y = int(w * 0.07), int(h * 0.62)
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.text((x + 4, y + 4), text, font=fb, fill=(0, 0, 0, 170))
        if sub:
            sd.text((x + 3, y + big * 1.18 + 3), sub, font=fs, fill=(0, 0, 0, 170))
        im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(h * 0.006)))
        d = ImageDraw.Draw(im)
        d.text((x, y), text, font=fb, fill="white")
        if sub:
            bar_y = y + big * 1.1
            d.rectangle([x, bar_y, x + int(w * 0.05), bar_y + max(3, h // 300)], fill=(255, 214, 90, 255))
            d.text((x, y + big * 1.18), sub, font=fs, fill="white")
        return im
    return _cached(cache_dir, f"title|{text}|{sub}|{w}x{h}", render)


def place_tag(text, w, h, cache_dir):
    """Small translucent pill, top-left: a location label."""
    def render():
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        size = int(h * 0.042)
        f = _font(SUB_FONTS, size)
        pad = size * 0.6
        tw = d.textlength(text, font=f)
        x, y = int(w * 0.04), int(h * 0.05)
        d.rounded_rectangle([x, y, x + tw + pad * 2 + size * 0.7, y + size + pad * 1.4],
                            radius=int(size * 0.5), fill=(0, 0, 0, 120))
        d.ellipse([x + pad, y + pad * 0.7 + size * 0.3, x + pad + size * 0.4, y + pad * 0.7 + size * 0.7],
                  fill=(255, 214, 90, 255))
        d.text((x + pad + size * 0.7, y + pad * 0.7), text, font=f, fill="white")
        return im
    return _cached(cache_dir, f"tag|{text}|{w}x{h}", render)
