"""Thumbnail polish: color grade + vignette + spotlight + punchy text.

A drop-in nicer renderer than the bare compositor — grades the base frame so it
pops, then draws text with a real dual outline + soft drop shadow + optional
banner. Pure Pillow, no new deps (Tier A of the thumbnail-polish playbook).
"""
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageFont

W, H = 1280, 720

# Heaviest reliable CJK face on macOS (Source Han / 思源黑体 not assumed installed).
CJK_FONTS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
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
