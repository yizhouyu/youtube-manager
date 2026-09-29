"""Layered multi-place thumbnails: one hero image with the other places stacked on it.

These replace flat side-by-side collages. The patterns come from a study of multi-place travel covers. Equal
strips have no hierarchy and shrink every panel to ~56 px on a phone. The strong covers instead use:

* ``card``: a tilted, white-bordered photo card (a "polaroid") with a drop shadow. It can carry a small tag.
* ``circle``: a round inset with a white ring, optionally tied to a spot on the hero by a leader line.
* ``cutout``: a subject lifted out of its frame (rembg), with a white sticker outline and a shadow. It can sit
  over the hero or overlap the title.
* ``popout``: a photo card whose subject breaks out past the card's top edge (the cut-out is lined up with
  the photo, so it reads as one object stepping out of the picture).
* ``subject``: the hero's own foreground subject re-pasted above the text, so a big title sits *behind* it.
* ``route``: a dashed road line with pins joining the places in order.
* ``text``: a big calm title (horizontal or vertical) with a soft shadow, no black plate.

The hero also takes ``grade`` (whole frame), ``regions`` ([(box, grade kwargs, feather)] for a split grade such
as cooler sand under a gold sky), ``shade`` (soft darkening boxes for text calm) and ``vignette``.
``clean(img, boxes, protect)`` inpaints small distractions before a frame is used.

A scene is a plain dict, and every coordinate is a fraction of the canvas: ``x`` of W, ``y`` of H, sizes of H.
The same spec therefore renders natively at YouTube 16:9 and Bilibili 16:10. A layer's ``bili`` dict overrides
keys for the 16:10 render, which keeps text inside Bilibili's central 4:3 zone and above the bottom overlays.

    from src.thumbnail_generator.collage import grab
    from src.thumbnail_generator.layered import cutout, render_layered
    hero = grab(clip_a, 3.0, vf)
    dog = cutout(grab(clip_b, 4.5, vf), box=(0.3, 0.4, 0.75, 0.85))
    spec = {"hero": {"img": hero, "cy": 0.55},
            "layers": [{"kind": "card", "img": grab(clip_c, 5.3, vf), "crop": {"cx": 0.63, "zoom": 2.2},
                        "x": 0.80, "y": 0.30, "w": 0.42, "rot": 6, "tag": "9米开心果"},
                       {"kind": "text", "lines": ["白沙"], "x": 0.22, "y": 0.40, "size": 0.30},
                       {"kind": "cutout", "img": dog, "x": 0.55, "y": 0.80, "h": 0.40}]}
    render_layered(spec, out_dir, "E")

Cut-outs need ``rembg`` (``pip install "rembg[cpu]"``; the model downloads on first use). The rest is Pillow.
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .collage import _hx, _panel
from .export import BILIBILI_MAX_BYTES, BILIBILI_SIZE, YOUTUBE_MAX_BYTES, YOUTUBE_SIZE, _save_capped
from .polish import CJK_FONTS

WHITE = (255, 255, 255)
MASTER = (1920, 1080)
FONTS = {
    "heavy": (CJK_FONTS[0], 0),                                   # Noto Sans SC Black (bundled)
    "song": ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),  # Songti SC Black: calm, editorial
    "hei": ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
}
_SESSIONS = {}


def font(name, size):
    path, idx = FONTS.get(name, (name, 0))
    for p, i in ((path, idx), (CJK_FONTS[0], 0)):
        try:
            return ImageFont.truetype(p, size, index=i)
        except OSError:
            continue
    return ImageFont.load_default()


# ---------------------------------------------------------------- cut-outs

def cutout(img, box=None, model="isnet-general-use", erase=(), threshold=12, trim=True, full_frame=False, hard=False):
    """Lift the main subject out of ``img`` and return RGBA.

    ``box``: (x0, y0, x1, y1) fractions to crop first, so the subject fills the model's input.
    ``erase``: boxes (fractions of the crop) whose alpha is cleared, e.g. a bystander the model kept.
    ``threshold``: alpha below this becomes 0, which kills haze. ``trim`` crops to the opaque bounds.
    ``full_frame``: return a transparent canvas the size of ``img`` with the subject at its original spot
    (needed by the ``popout`` layer, which must line the cut-out up with the same photo).
    ``hard``: binarise the alpha at ``threshold`` (then soften 1 px), which drops semi-transparent haze such as
    blowing sand or dust around the subject.
    """
    from rembg import new_session, remove  # lazy: only cut-out users need the dependency
    src_size, origin = img.size, (0, 0)
    if box:
        W, H = img.size
        origin = (round(box[0] * W), round(box[1] * H))
        img = img.crop(origin + (round(box[2] * W), round(box[3] * H)))
    if model not in _SESSIONS:
        _SESSIONS[model] = new_session(model)
    out = remove(img.convert("RGB"), session=_SESSIONS[model]).convert("RGBA")
    a = out.getchannel("A").point(lambda v: 0 if v < threshold else (255 if hard else v))
    if hard:
        a = a.filter(ImageFilter.GaussianBlur(1))
    if erase:
        d = ImageDraw.Draw(a)
        for e in erase:
            d.rectangle((e[0] * out.width, e[1] * out.height, e[2] * out.width, e[3] * out.height), fill=0)
    out.putalpha(a)
    if full_frame:
        canvas = Image.new("RGBA", src_size, (0, 0, 0, 0))
        canvas.alpha_composite(out, origin)
        return canvas
    return out.crop(out.getbbox()) if trim and out.getbbox() else out


def subject_mask(img, model="isnet-general-use", threshold=12):
    """Soft 'L' mask (255 = subject) of ``img`` at its own size, for text-behind-subject."""
    return cutout(img, model=model, threshold=threshold, trim=False).getchannel("A")


def clean(img, boxes, protect=None, radius=9):
    """Remove small distractions (a stray pole, a cart edge, a far-off bystander).

    ``boxes``: (x0, y0, x1, y1) fractions of ``img``, or (x0, y0, x1, y1, dx, dy) to *clone* texture from the
    same-size region shifted by (dx, dy) fractions (a clone stamp: keeps sand/grass/water grain, which plain
    inpainting smears). Plain boxes use OpenCV Telea inpainting; keep those tiny.
    ``protect``: optional 'L' mask (255 = keep), e.g. a subject's cut-out alpha, so a box never eats into it."""
    W, H = img.size
    out = img.convert("RGB")
    keep = protect.resize((W, H)).point(lambda v: 255 if v > 40 else 0) if protect is not None else None
    tele = [b for b in boxes if len(b) == 4]
    for b in (b for b in boxes if len(b) == 6):
        x0, y0, x1, y1 = (round(b[0] * W), round(b[1] * H), round(b[2] * W), round(b[3] * H))
        dx, dy = round(b[4] * W), round(b[5] * H)
        src = out.crop((x0 + dx, y0 + dy, x1 + dx, y1 + dy))
        m = Image.new("L", (x1 - x0, y1 - y0), 0)
        f = max(2, min(x1 - x0, y1 - y0) // 6)
        ImageDraw.Draw(m).rectangle((f, f, m.width - f, m.height - f), fill=255)
        m = m.filter(ImageFilter.GaussianBlur(f / 2))
        if keep is not None:
            m = ImageChops.subtract(m, keep.crop((x0, y0, x1, y1)))
        out.paste(src, (x0, y0), m)
    if tele:
        import cv2  # installed with rembg
        import numpy as np
        m = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(m)
        for b in tele:
            d.rectangle((b[0] * W, b[1] * H, b[2] * W, b[3] * H), fill=255)
        if keep is not None:
            m = ImageChops.subtract(m, keep)
        arr = cv2.inpaint(np.array(out)[:, :, ::-1].copy(), np.array(m), radius, cv2.INPAINT_TELEA)
        out = Image.fromarray(arr[:, :, ::-1].copy())
    return out


# ---------------------------------------------------------------- building blocks

def grade(img, warm=0.0, sat=1.0, bright=1.0, contrast=1.0, pop=False, gamma=1.0, lift=0, denoise=False):
    """Pull a layer into the scene's colour world. ``warm`` > 0 shifts toward gold (fractions, e.g. 0.04).
    ``gamma`` > 1 lifts shadows and mids without clipping highlights (for muddy, underexposed areas).
    ``lift`` (0-255) raises the black point linearly (out = in * (255 - lift) / 255 + lift). Prefer it over a
    strong gamma on crushed, compressed shadows, which posterise. ``denoise`` median-filters first."""
    rgba = img.mode == "RGBA"
    a = img.getchannel("A") if rgba else None
    im = img.convert("RGB")
    if pop:
        im = ImageEnhance.Color(im).enhance(1.08)
        im = ImageEnhance.Contrast(im).enhance(1.06)
        im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=100, threshold=3))
    if denoise:
        im = im.filter(ImageFilter.MedianFilter(3))
    if lift:
        im = im.point([round(v * (255 - lift) / 255 + lift) for v in range(256)] * 3)
    if gamma != 1.0:
        lut = [round(255 * (v / 255) ** (1 / gamma)) for v in range(256)]
        im = im.point(lut * 3)
    if contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    if bright != 1.0:
        im = ImageEnhance.Brightness(im).enhance(bright)
    if sat != 1.0:
        im = ImageEnhance.Color(im).enhance(sat)
    if warm:
        r, g, b = im.split()
        im = Image.merge("RGB", (r.point(lambda v: min(255, int(v * (1 + warm)))), g,
                                 b.point(lambda v: int(v * (1 - warm)))))
    if rgba:
        im = im.convert("RGBA")
        im.putalpha(a)
    return im


def fit(img, w, h, cx=0.5, cy=0.5, zoom=1.0):
    """Crop ``img`` to w:h around (cx, cy) with ``zoom`` >= 1 and resize to (w, h)."""
    return _panel(img, max(1, round(w)), max(1, round(h)), cx=cx, cy=cy, zoom=zoom, pop=False)


def crop_box(size, w, h, cx=0.5, cy=0.5, zoom=1.0):
    """The source rectangle ``fit`` uses (same math as collage._panel)."""
    sw, sh = size
    ch = sh / zoom
    cw = ch * w / h
    if cw > sw:
        cw = sw
        ch = cw * h / w
    x0 = max(0, min(sw * cx - cw / 2, sw - cw))
    y0 = max(0, min(sh * cy - ch / 2, sh - ch))
    return x0, y0, x0 + cw, y0 + ch


def popout_card(img, subject, w, h, crop, border=0.045, outline=6, over=0.6):
    """A photo card whose subject breaks out past the card's top edge.

    ``subject`` is ``cutout(img, ..., full_frame=True)``. The card shows ``img`` cropped by ``crop``. The subject is
    redrawn at exactly the same scale and offset, so inside the card it matches the photo; above the card it
    continues into the scene. ``over`` limits how far up it may extend (a fraction of the card height)."""
    x0, y0, x1, y1 = crop_box(img.size, w, h, **crop)
    photo = fit(img, w, h, **crop)
    card = photo_card(photo, w, h, border=border)
    b = (card.width - round(w)) // 2
    k = w / (x1 - x0)
    up = round(h * over)
    ext = (x0 - (b + outline) / k, y0 - up / k, x1 + (b + outline) / k, y1)   # source region incl. overhang
    sub = subject.crop(tuple(round(v) for v in ext))
    sub = sub.resize((round(sub.width * k), round(sub.height * k)), Image.LANCZOS)
    sub = sticker(sub, outline) if outline else sub
    pad = outline + 2 if outline else 0
    # Draw the cut-out only above the photo's top edge (it covers the white border). Inside the card, the photo
    # itself shows the subject, so the join is seamless and nothing (a rope, a shadow) is doubled.
    edge = up + pad + b + max(2, b // 3)
    a = sub.getchannel("A")
    keep = Image.new("L", sub.size, 0)
    ImageDraw.Draw(keep).rectangle((0, 0, sub.width, edge), fill=255)
    sub.putalpha(ImageChops.multiply(a, keep.filter(ImageFilter.GaussianBlur(1))))
    holder = Image.new("RGBA", (card.width + 2 * pad, card.height + up + 2 * pad), (0, 0, 0, 0))
    holder.alpha_composite(card, (pad, up + pad))
    holder.alpha_composite(sub, (0, 0))
    return holder.crop(holder.getbbox())


def photo_card(img, w, h, border=0.045, color=WHITE, radius=0.0, hairline=0):
    """A photo with a white border (``border`` is a fraction of the short side). Returns RGBA.
    ``hairline`` px of dark edge outside the border, for cards that sit on white sand or snow."""
    b = max(3, round(min(w, h) * border)) + hairline
    card = Image.new("RGBA", (round(w) + 2 * b, round(h) + 2 * b), (0, 0, 0, 0))
    r = round(min(w, h) * radius)
    if hairline:
        ImageDraw.Draw(card).rounded_rectangle((0, 0, card.width - 1, card.height - 1), r, fill=(35, 35, 35, 255))
    ImageDraw.Draw(card).rounded_rectangle((hairline, hairline, card.width - 1 - hairline, card.height - 1 - hairline),
                                           r, fill=color + (255,))
    photo = img.convert("RGBA").resize((round(w), round(h)), Image.LANCZOS)
    if r:
        m = Image.new("L", photo.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, photo.width - 1, photo.height - 1), max(1, r - b), fill=255)
        photo.putalpha(m)
    card.alpha_composite(photo, (b, b))
    return card


def circle_card(img, d, ring=0.04, color=WHITE, hairline=0.0):
    """A round inset of diameter ``d`` px with a ring of ``ring``·d. ``img`` should already be square-ish.
    ``hairline`` (fraction of d) adds a thin dark edge outside the ring so it lifts off white backgrounds."""
    d = round(d)
    r = max(3, round(d * ring))
    ss = 3                                                    # supersample for clean edges
    big = Image.new("RGBA", (d * ss, d * ss), (0, 0, 0, 0))
    hl = round(d * hairline * ss)
    if hl:
        ImageDraw.Draw(big).ellipse((0, 0, d * ss - 1, d * ss - 1), fill=(35, 35, 35, 255))
    ImageDraw.Draw(big).ellipse((hl, hl, d * ss - 1 - hl, d * ss - 1 - hl), fill=color + (255,))
    inner = d * ss - 2 * r * ss - 2 * hl
    photo = img.convert("RGB").resize((inner, inner), Image.LANCZOS).convert("RGBA")
    m = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(m).ellipse((0, 0, inner - 1, inner - 1), fill=255)
    photo.putalpha(m)
    big.alpha_composite(photo, (r * ss + hl, r * ss + hl))
    return big.resize((d, d), Image.LANCZOS)


def sticker(rgba, outline=8, color=WHITE):
    """White sticker outline of ``outline`` px around a cut-out's alpha."""
    if outline <= 0:
        return rgba
    pad = outline + 2
    src = Image.new("RGBA", (rgba.width + 2 * pad, rgba.height + 2 * pad), (0, 0, 0, 0))
    src.alpha_composite(rgba, (pad, pad))
    a = src.getchannel("A").point(lambda v: 255 if v > 90 else 0)
    k = 2 * outline + 1
    grow = a.filter(ImageFilter.MaxFilter(k if k <= 25 else 25))
    for _ in range((k - 1) // 24):                             # MaxFilter is capped; repeat for thick outlines
        grow = grow.filter(ImageFilter.MaxFilter(25))
    grow = grow.filter(ImageFilter.GaussianBlur(1.2))
    out = Image.new("RGBA", src.size, color + (0,))
    out.putalpha(grow)
    out.alpha_composite(src)
    return out


def rotated(layer, deg):
    return layer.rotate(deg, resample=Image.BICUBIC, expand=True) if deg else layer


def with_shadow(layer, offset=(0.012, 0.018), blur=0.02, opacity=0.5):
    """Drop shadow under an RGBA layer. Offsets/blur are fractions of the layer's short side.
    Returns (image, (dx, dy)): the padded image and where the layer's top-left sits inside it."""
    s = min(layer.size)
    ox, oy, br = round(s * offset[0]), round(s * offset[1]), max(1, round(s * blur))
    pad = br * 3 + max(abs(ox), abs(oy))
    out = Image.new("RGBA", (layer.width + 2 * pad, layer.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 255))
    sh.putalpha(layer.getchannel("A").point(lambda v: int(v * opacity)))
    out.alpha_composite(sh, (pad + ox, pad + oy))
    out = out.filter(ImageFilter.GaussianBlur(br))
    out.alpha_composite(layer, (pad, pad))
    return out, (pad, pad)


def place(canvas, layer, cx, cy):
    """Alpha-composite ``layer`` centred on (cx, cy) px (partly off-canvas is fine)."""
    x, y = round(cx - layer.width / 2), round(cy - layer.height / 2)
    x0, y0 = max(0, -x), max(0, -y)
    x1, y1 = min(layer.width, canvas.width - x), min(layer.height, canvas.height - y)
    if x1 > x0 and y1 > y0:
        canvas.alpha_composite(layer.crop((x0, y0, x1, y1)), (x + x0, y + y0))
    return (x, y, x + layer.width, y + layer.height)


def pill(text, size, fg=(20, 20, 20), bg=WHITE, fnt="heavy", pad=(0.45, 0.22), alpha=235):
    """A small rounded place tag."""
    f = font(fnt, round(size))
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    px, py = round(size * pad[0]), round(size * pad[1])
    im = Image.new("RGBA", (r - l + 2 * px, b - t + 2 * py), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    dd.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=im.height // 2, fill=_hx(bg) + (alpha,))
    dd.text((px - l, py - t), text, font=f, fill=_hx(fg))
    return im


def text_image(lines, size, fnt="heavy", fill=WHITE, stroke=0, stroke_fill=(0, 0, 0), vertical=False,
               spacing=0.12, align="center", tracking=0.0):
    """Render 1+ lines to a tight RGBA. Each line is a str or a list of (text, colour) segments.
    ``vertical`` stacks characters top-to-bottom (one column per line, right to left)."""
    f = font(fnt, round(size))
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    segs = [[(ln, fill)] if isinstance(ln, str) else ln for ln in lines]
    track = round(size * tracking)
    if vertical:
        cols = []
        for ln in segs:
            chars = [(ch, c) for s, c in ln for ch in s]
            cols.append(chars)
        cw, ch_h = round(size * 1.02), round(size * (1.0 + spacing * 0.5))
        W = len(cols) * cw + (len(cols) - 1) * round(size * spacing * 2) + 2 * stroke
        H = max(len(c) for c in cols) * ch_h + 2 * stroke
        im = Image.new("RGBA", (W + 4, H + 4), (0, 0, 0, 0))
        dd = ImageDraw.Draw(im)
        for i, col in enumerate(cols):
            x = W - (i + 1) * cw - i * round(size * spacing * 2) + stroke
            for j, (ch, c) in enumerate(col):
                l, t, r, b = dd.textbbox((0, 0), ch, font=f)
                dd.text((x + (cw - (r - l)) / 2 - l, stroke + j * ch_h - t + (ch_h - (b - t)) / 2 - size * 0.04), ch,
                        font=f, fill=_hx(c), stroke_width=stroke, stroke_fill=_hx(stroke_fill))
        return im.crop(im.getbbox())

    def seg_w(s):
        return d.textlength(s, font=f) + track * max(0, len(s) - 1)

    widths = [sum(seg_w(s) for s, _ in ln) for ln in segs]
    asc, desc = f.getmetrics()
    lh = asc + desc
    gap = round(size * spacing)
    W = round(max(widths)) + 2 * stroke + 4
    H = lh * len(segs) + gap * (len(segs) - 1) + 2 * stroke + 4
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(im)
    y = stroke
    for ln, w in zip(segs, widths):
        x = stroke + {"center": (W - 2 * stroke - w) / 2, "left": 0, "right": W - 2 * stroke - w}[align]
        for s, c in ln:
            if track:
                for ch in s:
                    dd.text((x, y), ch, font=f, fill=_hx(c), stroke_width=stroke, stroke_fill=_hx(stroke_fill))
                    x += d.textlength(ch, font=f) + track
            else:
                dd.text((x, y), s, font=f, fill=_hx(c), stroke_width=stroke, stroke_fill=_hx(stroke_fill))
                x += d.textlength(s, font=f)
        y += lh + gap
    return im.crop(im.getbbox())


def soft_shadow(layer, blur=0.06, opacity=0.55, offset=(0.0, 0.03), glow=False):
    """Diffuse dark halo behind text so it reads on light and busy areas without a plate.
    Sizes are fractions of the layer height. ``glow`` spreads it (for white text on white sand)."""
    h = layer.height
    br = max(2, round(h * blur))
    pad = br * 3
    out = Image.new("RGBA", (layer.width + 2 * pad, layer.height + 2 * pad), (0, 0, 0, 0))
    a = layer.getchannel("A")
    if glow:
        a = a.filter(ImageFilter.MaxFilter(9))
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 255))
    sh.putalpha(a.point(lambda v: int(v * opacity)))
    out.alpha_composite(sh, (pad + round(h * offset[0]), pad + round(h * offset[1])))
    out = out.filter(ImageFilter.GaussianBlur(br))
    out.alpha_composite(layer, (pad, pad))
    return out


def dashed_path(draw, pts, width, dash, gap, fill):
    """Dashes along a polyline (px points)."""
    carry, on = 0.0, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if not seg:
            continue
        ux, uy = (x1 - x0) / seg, (y1 - y0) / seg
        pos = 0.0
        while pos < seg:
            step = min((dash if on else gap) - carry, seg - pos)
            if on:
                draw.line((x0 + ux * pos, y0 + uy * pos, x0 + ux * (pos + step), y0 + uy * (pos + step)),
                          fill=fill, width=width)
            pos += step
            carry += step
            if carry >= (dash if on else gap) - 1e-6:
                carry, on = 0.0, not on


def smooth(pts, n=24):
    """Catmull-Rom through ``pts`` (px) for a relaxed road-like curve."""
    if len(pts) < 3:
        return pts
    p = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for i in range(1, len(p) - 2):
        for k in range(n):
            t = k / n
            out.append(tuple(0.5 * ((2 * p[i][j]) + (-p[i - 1][j] + p[i + 1][j]) * t +
                                    (2 * p[i - 1][j] - 5 * p[i][j] + 4 * p[i + 1][j] - p[i + 2][j]) * t * t +
                                    (-p[i - 1][j] + 3 * p[i][j] - 3 * p[i + 1][j] + p[i + 2][j]) * t ** 3)
                     for j in (0, 1)))
    out.append(pts[-1])
    return out


def vignette(img, strength=0.3, center=(0.5, 0.5)):
    W, H = img.size
    m = Image.new("L", (W, H), 0)
    cx, cy = center[0] * W, center[1] * H
    ImageDraw.Draw(m).ellipse((cx - W * 0.75, cy - H * 0.8, cx + W * 0.75, cy + H * 0.8), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(W // 8))
    return Image.composite(img, ImageEnhance.Brightness(img).enhance(1 - strength), m)


def shade(img, box, strength=0.35, feather=0.15):
    """Darken a soft region (box in fractions) for text calm; ``feather`` is a fraction of H."""
    W, H = img.size
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rectangle((box[0] * W, box[1] * H, box[2] * W, box[3] * H), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(1, feather * H)))
    return Image.composite(ImageEnhance.Brightness(img).enhance(1 - strength), img, m)


# ---------------------------------------------------------------- scene

def _v(layer, key, default=None, bili=False):
    if bili and key in layer.get("bili", {}):
        return layer["bili"][key]
    return layer.get(key, default)


def compose(spec, size, bili=False):
    """Render ``spec`` at ``size`` = (W, H). See the module docstring for the layer kinds."""
    W, H = size
    world = spec.get("world", {})
    hero = spec["hero"]
    hk = {k: _v(hero, k, d, bili) for k, d in (("cx", 0.5), ("cy", 0.5), ("zoom", 1.0))}
    src = hero["img"]
    if hero.get("clean"):
        src = clean(src, hero["clean"], protect=hero.get("protect"))
    base = fit(src, W, H, **hk)
    base = grade(base, **{**world, **hero.get("grade", {})})
    for box, kw, *feather in _v(hero, "regions", [], bili):   # e.g. cool the sand, keep the sky gold
        m = Image.new("L", (W, H), 0)
        ImageDraw.Draw(m).rectangle((box[0] * W, box[1] * H, box[2] * W, box[3] * H), fill=255)
        m = m.filter(ImageFilter.GaussianBlur(max(1, (feather[0] if feather else 0.08) * H)))
        base = Image.composite(grade(base, **kw), base, m)
    for s in _v(hero, "shade", [], bili):
        base = shade(base, s[:4], *s[4:])
    if _v(hero, "vignette", 0, bili):
        base = vignette(base, _v(hero, "vignette", 0, bili))
    canvas = base.convert("RGBA")
    hero_mask = None
    boxes = {}
    for i, L in enumerate(spec.get("layers", [])):
        g = lambda k, d=None: _v(L, k, d, bili)  # noqa: E731
        kind = L["kind"]
        if kind == "subject":                                  # hero foreground over whatever came before
            if hero_mask is None or hero_mask.size != (W, H):
                hero_mask = subject_mask(base, model=L.get("model", "isnet-general-use"))
                if L.get("mask_box"):
                    keep = Image.new("L", (W, H), 0)
                    b = g("mask_box")
                    ImageDraw.Draw(keep).rectangle((b[0] * W, b[1] * H, b[2] * W, b[3] * H), fill=255)
                    hero_mask = ImageChops.multiply(hero_mask, keep)
            top = base.convert("RGBA")
            top.putalpha(hero_mask)
            canvas.alpha_composite(top)
            continue
        if kind in ("card", "circle"):
            h = g("h", 0.36) * H
            if kind == "card":
                w = g("w", 0.5) * H
                photo = fit(L["img"], w, h, **{**{"cx": 0.5, "cy": 0.5, "zoom": 1.0}, **g("crop", {})})
                photo = grade(photo, **{**world, **L.get("grade", {})})
                lay = photo_card(photo, w, h, border=g("border", 0.045), radius=g("radius", 0.0),
                                 hairline=round(g("hairline", 0.0) * H))
            else:
                photo = fit(L["img"], h, h, **{**{"cx": 0.5, "cy": 0.5, "zoom": 1.0}, **g("crop", {})})
                photo = grade(photo, **{**world, **L.get("grade", {})})
                lay = circle_card(photo, h, ring=g("ring", 0.04), hairline=g("hairline", 0.0))
            if g("tag"):
                t = pill(g("tag"), g("tag_size", 0.07) * H, fg=g("tag_fg", (25, 25, 25)), bg=g("tag_bg", WHITE))
                pad_top = round(t.height * g("tag_overlap", 0.55))    # how far the tag rides up over the card
                holder = Image.new("RGBA", (max(lay.width, t.width), lay.height + t.height - pad_top), (0, 0, 0, 0))
                holder.alpha_composite(lay, ((holder.width - lay.width) // 2, 0))
                tx = {"center": (holder.width - t.width) // 2, "left": round(lay.width * 0.06),
                      "right": holder.width - t.width - round(lay.width * 0.06)}[g("tag_align", "center")]
                holder.alpha_composite(t, (tx, lay.height - pad_top))
                lay = holder
            lay = rotated(lay, g("rot", 0))
            lay, _ = with_shadow(lay, opacity=g("shadow", 0.5), blur=g("shadow_blur", 0.02))
            boxes[i] = place(canvas, lay, g("x") * W, g("y") * H)
            if g("leader"):                                     # thin line from the inset to a hero point
                lx, ly = g("leader")
                d = ImageDraw.Draw(canvas)
                lw = max(3, round(H * g("leader_w", 0.006)))
                sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                ImageDraw.Draw(sh).line((g("x") * W, g("y") * H + lw * 0.4, lx * W, ly * H + lw * 0.4),
                                        fill=(0, 0, 0, 110), width=lw + 2)
                canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(lw * 0.4)))
                d = ImageDraw.Draw(canvas)
                d.line((g("x") * W, g("y") * H, lx * W, ly * H), fill=WHITE + (240,), width=lw)
                rr = max(H * 0.012, lw * 1.4)
                d.ellipse((lx * W - rr, ly * H - rr, lx * W + rr, ly * H + rr), fill=WHITE + (255,),
                          outline=(0, 0, 0, 90), width=max(1, lw // 4))
                canvas.alpha_composite(lay, (boxes[i][0], boxes[i][1]))   # keep the inset above its own line
        elif kind == "popout":
            w, h = g("w", 0.4) * H, g("h", 0.4) * H
            src = grade(L["img"], **{**world, **L.get("grade", {})})
            subj = grade(L["subject"], **{**world, **L.get("grade", {})})
            lay = popout_card(src, subj, w, h, {**{"cx": 0.5, "cy": 0.5, "zoom": 1.0}, **g("crop", {})},
                              border=g("border", 0.045), outline=round(g("outline", 0.006) * H), over=g("over", 0.6))
            lay = rotated(lay, g("rot", 0))
            lay, _ = with_shadow(lay, opacity=g("shadow", 0.5))
            boxes[i] = place(canvas, lay, g("x") * W, g("y") * H)
        elif kind == "cutout":
            c = L["img"]
            h = g("h", 0.5) * H
            c = c.resize((max(1, round(c.width * h / c.height)), round(h)), Image.LANCZOS)
            c = grade(c, **{**world, **L.get("grade", {})})
            if g("flip"):
                c = c.transpose(Image.FLIP_LEFT_RIGHT)
            c = sticker(c, round(g("outline", 0.008) * H), color=_hx(g("outline_color", WHITE)))
            c = rotated(c, g("rot", 0))
            if g("contact", 0):                                 # soft ground shadow so it stands on the scene
                cs = Image.new("RGBA", (c.width, c.height + round(c.height * 0.12)), (0, 0, 0, 0))
                e = Image.new("L", cs.size, 0)
                ew, eh = c.width * g("contact_w", 0.85), c.height * 0.09
                ImageDraw.Draw(e).ellipse(((cs.width - ew) / 2, c.height - eh * 0.9, (cs.width + ew) / 2, c.height + eh * 0.4),
                                          fill=round(255 * g("contact", 0)))
                cs.putalpha(e.filter(ImageFilter.GaussianBlur(max(2, eh * 0.45))))
                cs.alpha_composite(c, (0, 0))
                c = cs
            c, _ = with_shadow(c, offset=g("shadow_offset", (0.01, 0.02)), opacity=g("shadow", 0.45))
            boxes[i] = place(canvas, c, g("x") * W, g("y") * H)
        elif kind == "route":
            pts = [(x * W, y * H) for x, y in g("pts")]
            pts = smooth(pts) if g("smooth", True) else pts
            lw = max(3, round(g("width", 0.011) * H))
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            dashed_path(d, pts, lw + round(lw * 0.9), lw * 3.2, lw * 1.6, (0, 0, 0, 90))
            dashed_path(d, pts, lw, lw * 3.2, lw * 1.6, _hx(g("color", WHITE)) + (255,))
            for (x, y) in g("pins", []):
                r = lw * 1.5
                d.ellipse((x * W - r, y * H - r, x * W + r, y * H + r), fill=_hx(g("pin_color", g("color", WHITE))),
                          outline=(0, 0, 0, 120), width=max(1, lw // 4))
            canvas.alpha_composite(lay.filter(ImageFilter.GaussianBlur(0.6)))
        elif kind == "text":
            t = text_image(g("lines"), g("size", 0.2) * H, fnt=g("font", "heavy"), fill=_hx(g("color", WHITE)),
                           stroke=round(g("stroke", 0) * H), stroke_fill=_hx(g("stroke_fill", (0, 0, 0))),
                           vertical=g("vertical", False), spacing=g("spacing", 0.12), align=g("align", "center"),
                           tracking=g("tracking", 0.0))
            if g("rot"):
                t = rotated(t, g("rot"))
            if g("halo", 0.55):
                t = soft_shadow(t, blur=g("halo_blur", 0.07), opacity=g("halo", 0.55), glow=g("glow", False))
            ax, ay = g("anchor", (0.5, 0.5))
            cx, cy = g("x") * W + (0.5 - ax) * t.width, g("y") * H + (0.5 - ay) * t.height
            boxes[i] = place(canvas, t, cx, cy)
        elif kind == "image":                                   # free RGBA overlay (e.g. a pre-built sticker)
            im = L["img"]
            h = g("h", 0.2) * H
            im = rotated(im.resize((round(im.width * h / im.height), round(h)), Image.LANCZOS), g("rot", 0))
            boxes[i] = place(canvas, im, g("x") * W, g("y") * H)
        else:
            raise ValueError(f"unknown layer kind {kind!r}")
    return canvas.convert("RGB"), boxes


def render_layered(spec, out_dir, name):
    """Write ``<name>.jpg`` (1920x1080 master), ``<name>_youtube.jpg`` (1280x720) and ``<name>_bilibili.jpg``
    (1280x800, rendered natively with each layer's ``bili`` overrides). Returns the paths and layer boxes."""
    os.makedirs(out_dir, exist_ok=True)
    master, boxes = compose(spec, MASTER)
    out = {"master": os.path.join(out_dir, f"{name}.jpg"), "boxes": {"master": boxes}}
    master.save(out["master"], quality=95)
    out["youtube"] = os.path.join(out_dir, f"{name}_youtube.jpg")
    _save_capped(master.resize(YOUTUBE_SIZE, Image.LANCZOS), out["youtube"], YOUTUBE_MAX_BYTES)
    bili, bboxes = compose(spec, BILIBILI_SIZE, bili=True)
    out["bilibili"] = os.path.join(out_dir, f"{name}_bilibili.jpg")
    _save_capped(bili, out["bilibili"], BILIBILI_MAX_BYTES)
    out["boxes"]["bilibili"] = bboxes
    return out


def bili_safe_zone(size=BILIBILI_SIZE):
    """(x0, y0, x1, y1) px of Bilibili's central 4:3 crop, minus the bottom ~15 % overlay band."""
    W, H = size
    return ((W - H * 4 / 3) / 2, 0, (W + H * 4 / 3) / 2, H * 0.85)


def review_sheet(paths, out, widths=(320, 168)):
    """One image showing each file at full width 640 and at phone widths, for the art-director check."""
    ims = [Image.open(p).convert("RGB") for p in paths]
    rows = []
    for im in ims:
        big = im.resize((640, round(im.height * 640 / im.width)), Image.LANCZOS)
        smalls = [im.resize((w, round(im.height * w / im.width)), Image.LANCZOS) for w in widths]
        row = Image.new("RGB", (640 + sum(widths) + 30 * len(widths), big.height + 20), (235, 235, 235))
        row.paste(big, (0, 10))
        x = 640 + 30
        for s in smalls:
            row.paste(s, (x, 10))
            x += s.width + 30
        rows.append(row)
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)), (235, 235, 235))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    sheet.save(out, quality=90)
    return out
