"""Split-panel collage thumbnails: 2-3 places side by side + one short calm line.

For multi-place episodes the main thumbnail is a collage (see publish-video-chat
SKILL.md, Step 3 "Style by episode type"). Each panel is a real frame from the
4K source, graded like the video (pass the EDL grade as an ffmpeg ``-vf``).

Both platform files are composed natively (no padding/cropping of a finished
design): YouTube 16:9 at 1280x720 and Bilibili 16:10 at 1280x800, each with its
own crop of every panel. On Bilibili the text stays inside the central 4:3 zone
and above the bottom ~15% (duration / play-count overlays).

    from src.thumbnail_generator.collage import grab, render_collage
    panels = [dict(img=grab(clip1, 12.0, vf), cx=0.4),
              dict(img=grab(clip2, 4.0, vf), cy=0.6, zoom=1.3)]
    render_collage(panels, [[("圣地亚哥 ", "#FFFFFF"), ("两日游", "#FFD400")]], out_dir, "E")

Pure Pillow + ffmpeg, no new deps.
"""
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from .export import BILIBILI_MAX_BYTES, BILIBILI_SIZE, YOUTUBE_MAX_BYTES, YOUTUBE_SIZE, _save_capped
from .polish import _font

WHITE, YELLOW = (255, 255, 255), (255, 212, 0)


def grab(video, t, vf=None):
    """One full-resolution frame of ``video`` at ``t`` seconds, optionally through an ffmpeg filter."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f.png")
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", video, "-frames:v", "1"]
        subprocess.run(cmd + (["-vf", vf] if vf else []) + [p], check=True)
        return Image.open(p).convert("RGB")


def _panel(src, pw, ph, cx=0.5, cy=0.5, zoom=1.0, pop=True, bright=1.0, sat=1.0, warm=0, **_):
    """Crop ``src`` to the panel aspect around (cx, cy) (fractions of the frame), ``zoom`` >= 1 tightens.
    ``bright``/``sat`` are multipliers and ``warm`` shifts red up / blue down (0-255 scale), per panel,
    so a flat grey panel can be matched to a saturated neighbour."""
    ch = src.height / zoom
    cw = ch * pw / ph
    if cw > src.width:
        cw = src.width
        ch = cw * ph / pw
    x0 = max(0, min(src.width * cx - cw / 2, src.width - cw))
    y0 = max(0, min(src.height * cy - ch / 2, src.height - ch))
    p = src.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch))).resize((pw, ph), Image.LANCZOS)
    if pop:
        p = ImageEnhance.Color(p).enhance(1.08)
        p = ImageEnhance.Contrast(p).enhance(1.08)
        p = p.filter(ImageFilter.UnsharpMask(radius=2, percent=110, threshold=3))
    if bright != 1.0:
        p = ImageEnhance.Brightness(p).enhance(bright)
    if sat != 1.0:
        p = ImageEnhance.Color(p).enhance(sat)
    if warm:
        r, g, b = p.split()
        p = Image.merge("RGB", (r.point(lambda v: min(255, v + warm)), g, b.point(lambda v: max(0, v - warm * 0.7))))
    return p


def compose(panels, size, divider=None, divider_color=WHITE, shade=0.45):
    """Vertical split panels (width by ``weight``, default equal) with thin dividers.

    ``shade`` darkens the bottom ~40% smoothly so the text line has a calmer bed (0 = off).
    """
    W, H = size
    div = divider if divider is not None else max(4, W // 240)
    weights = [p.get("weight", 1.0) for p in panels]
    free = W - div * (len(panels) - 1)
    widths = [round(free * w / sum(weights)) for w in weights]
    widths[-1] = free - sum(widths[:-1])
    canvas = Image.new("RGB", size, divider_color)
    x = 0
    for p, w in zip(panels, widths):
        canvas.paste(_panel(p["img"], w, H, **p), (x, 0))
        x += w + div
    if shade:
        grad = Image.linear_gradient("L").resize(size).point(lambda v: max(0, v - 150) * 255 // 105)
        canvas = Image.composite(ImageEnhance.Brightness(canvas).enhance(1 - shade), canvas, grad)
    return canvas


def _hx(c):
    if isinstance(c, str):
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(c)


def draw_lines(img, lines, *, bottom, max_w, size, x_center=None, x_range=None, plate_alpha=150, min_size=60):
    """Centered heavy-font lines (each a list of (text, color) segments, stroked, soft shadow),
    on one rounded plate hugging the block (<=~60% black). ``bottom`` = y where the block ends;
    ``x_range`` = (lo, hi) keeps the whole plate inside that horizontal span.
    Returns (image, text box, font size)."""
    W, _ = img.size
    xc = W / 2 if x_center is None else x_center
    d = ImageDraw.Draw(img)
    while True:
        f = _font(size)
        sw = max(6, size // 9)
        widths = [sum(d.textlength(s, font=f) for s, _ in ln) for ln in lines]
        if max(widths) + 2 * sw <= max_w or size <= min_size:
            break
        size -= 4
    bbs = [d.textbbox((0, 0), "".join(s for s, _ in ln), font=f, stroke_width=sw) for ln in lines]
    gap = int(size * 0.14)
    block_h = sum(b[3] - b[1] for b in bbs) + gap * (len(lines) - 1)
    top = bottom - block_h
    pad_x, pad_y = int(size * 0.26), int(size * 0.14)
    if x_range:
        half = max(widths) / 2 + pad_x
        xc = min(max(xc, x_range[0] + half), x_range[1] - half)
    box = (int(xc - max(widths) / 2 - pad_x), top - pad_y, int(xc + max(widths) / 2 + pad_x), bottom + pad_y)
    img = img.convert("RGBA")
    if plate_alpha:
        plate = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(plate).rounded_rectangle(box, radius=int(size * 0.16), fill=(0, 0, 0, plate_alpha))
        img = Image.alpha_composite(img, plate)
    pos, y = [], top
    for ln, w, bb in zip(lines, widths, bbs):
        pos.append((xc - w / 2, y - bb[1]))
        y += bb[3] - bb[1] + gap
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)
    for ln, (x, y) in zip(lines, pos):
        for s, _ in ln:
            ds.text((x + size // 26, y + size // 20), s, font=f, fill=(0, 0, 0, 200),
                    stroke_width=sw, stroke_fill=(0, 0, 0, 200))
            x += ds.textlength(s, font=f)
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(max(2, size // 20))))
    d = ImageDraw.Draw(img)
    for ln, (x, y) in zip(lines, pos):
        for s, c in ln:
            d.text((x, y), s, font=f, fill=_hx(c), stroke_width=sw, stroke_fill=(0, 0, 0))
            x += d.textlength(s, font=f)
    return img.convert("RGB"), box, size


def render_collage(panels, lines, out_dir, name, *, text_bottom=0.84, font=0.145, max_text_w=0.80, text_x=0.5,
                   bili_text_bottom=0.80, plate_alpha=150, shade=0.45, divider_color=WHITE, bili_panels=None):
    """Write ``<name>.jpg`` (1920x1080 master), ``<name>_youtube.jpg`` (1280x720) and
    ``<name>_bilibili.jpg`` (1280x800, own crops, text inside the 4:3 centre and above the
    bottom overlays).

    panels: list of dicts ``img`` (PIL frame), optional ``cx``/``cy`` (crop centre as fractions),
    ``zoom`` (>=1), ``weight`` (relative panel width), ``pop`` (light colour/contrast lift).
    ``bili_panels`` optionally overrides per-panel crop keys for the 16:10 file (same order).
    lines: 1-2 lines, each a list of (text, color) segments. ``font`` is the size as a fraction of H.
    ``text_x`` is the text centre as a fraction of W (e.g. 0.67 to keep the line off panel 1's subject);
    ``max_text_w`` caps the text width (fraction of W). Bilibili keeps the text centred in its 4:3 zone.
    Returns {"master", "youtube", "bilibili", "boxes": {...}, "sizes": {...}}.
    """
    os.makedirs(out_dir, exist_ok=True)
    out = {"boxes": {}, "sizes": {}}
    for key, size, bottom, maxw in (("master", (1920, 1080), text_bottom, max_text_w),
                                    ("bilibili", BILIBILI_SIZE, bili_text_bottom, None)):
        W, H = size
        ps = panels
        if key == "bilibili" and bili_panels:
            ps = [{**p, **(o or {})} for p, o in zip(panels, bili_panels)]
        img = compose(ps, size, divider_color=divider_color, shade=shade)
        # Bilibili: keep the text inside the central 4:3 zone (width H*4/3)
        mw = int((H * 4 / 3 if maxw is None else W * maxw) * (0.94 if maxw is None else 1))
        img, box, fs = draw_lines(img, lines, bottom=int(H * bottom), max_w=mw, size=int(H * font),
                                  x_center=W * text_x, plate_alpha=plate_alpha,
                                  x_range=None if key == "master" else ((W - H * 4 / 3) / 2, (W + H * 4 / 3) / 2))
        out["boxes"][key], out["sizes"][key] = box, fs
        if key == "master":
            p = os.path.join(out_dir, f"{name}.jpg")
            img.save(p, quality=95)
            out["master"] = p
            yt = img.resize(YOUTUBE_SIZE, Image.LANCZOS)
            out["youtube"] = os.path.join(out_dir, f"{name}_youtube.jpg")
            _save_capped(yt, out["youtube"], YOUTUBE_MAX_BYTES)
        else:
            out["bilibili"] = os.path.join(out_dir, f"{name}_bilibili.jpg")
            _save_capped(img, out["bilibili"], BILIBILI_MAX_BYTES)
    return out


def phone_preview(path, width=320):
    """Downscaled copy (``<path stem>_phone<width>.jpg`` next to a temp dir) for the mobile check."""
    im = Image.open(path)
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    p = os.path.join(tempfile.gettempdir(), os.path.basename(path).rsplit(".", 1)[0] + f"_phone{width}.jpg")
    im.save(p, quality=92)
    return p
