"""Thumbnail polish: color grade + vignette + spotlight + punchy text.

A drop-in nicer renderer than the bare compositor — grades the base frame so it
pops, then draws text with a real dual outline + soft drop shadow + optional
banner. Pure Pillow, no new deps (Tier A of the thumbnail-polish playbook).
"""
import os
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageFont

W, H = 1280, 720

# Heavy "poster" CJK weight (Noto Sans SC Black / 思源黑 Heavy) bundled in the repo —
# this is what gives the lizheng-style poster look; fall back to system faces.
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CJK_FONTS = [
    os.path.join(_REPO, "assets/fonts/heavy.otf"),
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def _font(size):
    for p in CJK_FONTS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fill_1280x720(img):
    img = img.convert("RGB")
    tr, ir = W / H, img.width / img.height
    if ir > tr:
        nw = int(H * ir); img = img.resize((nw, H), Image.LANCZOS)
        l = (nw - W) // 2; img = img.crop((l, 0, l + W, H))
    else:
        nh = int(W / ir); img = img.resize((W, nh), Image.LANCZOS)
        t = (nh - H) // 2; img = img.crop((0, t, W, t + H))
    return img


def grade(img, *, color=1.18, contrast=1.11, brightness=1.02, warmth=8, vignette=0.32):
    img = ImageEnhance.Color(img).enhance(color)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Brightness(img).enhance(brightness)
    r, g, b = img.split()
    r = r.point(lambda v: min(255, int(v + warmth)))
    b = b.point(lambda v: max(0, int(v - warmth * 0.7)))
    img = Image.merge("RGB", (r, g, b))
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
    # vignette: darken toward the edges
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([-W * 0.25, -H * 0.25, W * 1.25, H * 1.25], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(180))
    dark = ImageEnhance.Brightness(img).enhance(1 - vignette)
    img = Image.composite(img, dark, mask)
    return img


def _xy(draw, text, font, sw, pos):
    b = draw.textbbox((0, 0), text, font=font, stroke_width=sw)
    tw, th = b[2] - b[0], b[3] - b[1]
    x = (W - tw) // 2 - b[0]
    if pos == "top":
        y = int(H * 0.07) - b[1]
    elif pos == "bottom":
        y = int(H * 0.74) - b[1]
    else:
        y = (H - th) // 2 - b[1]
    return x, y, tw, th


def add_text(img, main_text, *, color=(255, 255, 255), outline=(0, 0, 0),
             accent=(255, 212, 0), position="top", size=118, banner=False):
    img = img.convert("RGBA")
    font = _font(size)
    d = ImageDraw.Draw(img)
    x, y, tw, th = _xy(d, main_text, font, 12, position)

    # soft drop shadow
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((x + 6, y + 8), main_text, font=font, fill=(0, 0, 0, 170),
                            stroke_width=12, stroke_fill=(0, 0, 0, 170))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(7)))

    d = ImageDraw.Draw(img)
    if banner:
        pad = 36
        d.rounded_rectangle([x - pad, y - pad // 2, x + tw + pad, y + th + pad // 2],
                            radius=24, fill=(0, 0, 0, 140))
    # thick dark outer outline (native), then fill
    d.text((x, y), main_text, font=font, fill=color, stroke_width=12, stroke_fill=outline)
    # thin accent inner edge for a dual-outline feel
    d.text((x, y), main_text, font=font, fill=color, stroke_width=3, stroke_fill=accent)
    return img.convert("RGB")


def render(base_path, out_path, main_text, *, color="#FFFFFF", outline="#000000",
           accent="#FFD400", position="top", size=118, banner=False):
    def hx(s, d):
        s = (s or "").lstrip("#")
        return tuple(int(s[i:i+2], 16) for i in (0, 2, 4)) if len(s) == 6 else d
    img = _fill_1280x720(Image.open(base_path))
    img = grade(img)
    img = add_text(img, main_text, color=hx(color, (255,255,255)), outline=hx(outline, (0,0,0)),
                   accent=hx(accent, (255,212,0)), position=position, size=size, banner=banner)
    img.save(out_path, quality=92)
    return out_path


def _fit_font(lines, max_w, start=170, min_s=70):
    """Largest heavy-font size so the widest line fits max_w."""
    for s in range(start, min_s - 1, -4):
        f = _font(s)
        d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        if all(d.textlength(t, font=f) <= max_w for t, _ in lines):
            return f, s
    return _font(min_s), min_s


def render_poster(base_path, out_path, lines, *, tag=None, promise=None,
                  position="lower", align="center", cap=None, grade_kw=None):
    """lizheng-style poster cover: heavy big title (1-2 lines, yellow=key word /
    white=rest), optional top tag + bottom promise strip, on a graded frame.

    lines: list of (text, hex_color). tag/promise: optional short strings.
    """
    def hx(s, d=(255, 255, 255)):
        s = (s or "").lstrip("#")
        return tuple(int(s[i:i+2], 16) for i in (0, 2, 4)) if len(s) == 6 else d
    lines = [(t, hx(c)) for t, c in lines]
    img = grade(_fill_1280x720(Image.open(base_path)), **(grade_kw or {})).convert("RGBA")

    max_w = int(W * 0.82)
    # smaller cap when there are 2+ lines so the block can't overflow
    start_cap = cap or (150 if len(lines) >= 2 else 168)
    font, size = _fit_font(lines, max_w, start=start_cap, min_s=72)
    gap = int(size * 0.12)
    d = ImageDraw.Draw(img)
    heights = [d.textbbox((0, 0), t, font=font, stroke_width=2)[3] for t, _ in lines]
    block_h = sum(heights) + gap * (len(lines) - 1)
    tag_zone = 130 if tag else 24
    promise_zone = 120 if promise else 36
    if position == "upper":
        y0 = tag_zone
    elif position == "center":
        y0 = (H - block_h) // 2
    else:  # lower — sit just above the promise strip, never overflow
        y0 = H - promise_zone - block_h - 8
    y0 = max(tag_zone, min(y0, H - promise_zone - block_h - 8))

    sw = max(10, size // 9)
    margin = 48
    y = y0
    for (t, col), h in zip(lines, heights):
        tw = d.textlength(t, font=font)
        x = {"left": margin, "right": W - tw - margin}.get(align, (W - tw) // 2)
        # soft shadow
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((x + 5, y + 7), t, font=font, fill=(0, 0, 0, 180),
                                stroke_width=sw, stroke_fill=(0, 0, 0, 180))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(8)))
        d = ImageDraw.Draw(img)
        d.text((x, y), t, font=font, fill=col, stroke_width=sw, stroke_fill=(0, 0, 0))
        y += h + gap

    if tag:
        tf = _font(46)
        tw = d.textlength(tag, font=tf)
        d.rounded_rectangle([40, 40, 40 + tw + 44, 40 + 78], radius=10, fill=(0, 0, 0, 235))
        d.text((62, 52), tag, font=tf, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
    if promise:
        pf = _font(50)
        pw = d.textlength(promise, font=pf)
        bx = (W - pw) // 2
        d.rounded_rectangle([bx - 28, H - 96, bx + pw + 28, H - 24], radius=12, fill=(255, 212, 0, 240))
        d.text((bx, H - 86), promise, font=pf, fill=(20, 20, 20))
    img.convert("RGB").save(out_path, quality=92)
    return out_path
