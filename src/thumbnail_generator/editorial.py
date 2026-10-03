"""Editorial ("travel magazine") cover, the creator's pick from 2026-10-03 (ep 97 G1).

Layout: one retouched landscape photo filling the frame. Over it, a big wide-tracked English place name
(Futura Bold, white, no stroke, soft shadow) and one Chinese line in PingFang SC Semibold saying what or where it is.
Use it when the place name is obscure to Chinese viewers. For a famous name, `en` may be Chinese
(`en_font="zh"`) and the Chinese line becomes the hook.

    from src.thumbnail_generator.editorial import render
    render("frame.jpg", "out.jpg", en="INDIAN HEAD", zh="印第安头 · 纽约州徒步", cx=0.5, top=0.10)

The text block is centred at x = cx·W, with its top at top·H. Keep it on sky or other calm area, never on a face.
"""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .retouch import retouch

W, H = 1280, 720
_PF_CANDIDATES = [
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
FUTURA = "/System/Library/Fonts/Supplemental/Futura.ttc"
HEAVY = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", "heavy.otf")


def _pingfang(size, weight="Semibold"):
    for p in _PF_CANDIDATES:
        if os.path.exists(p):
            for i in range(24):
                try:
                    f = ImageFont.truetype(p, size, index=i)
                except OSError:
                    break
                fam, sty = f.getname()
                if "SC" in fam and sty == weight:
                    return f
    return ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", size)


def _futura(size):
    return ImageFont.truetype(FUTURA, size, index=2)  # Futura Bold


def fit(im, w=W, h=H, cx=0.5, cy=0.5):
    """Cover-crop `im` to w×h, keeping the point (cx, cy) of the overflow."""
    s = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    x, y = int((im.width - w) * cx), int((im.height - h) * cy)
    return im.crop((x, y, x + w, y + h))


def _tracked(d, cx, y, s, font, track):
    w = sum(d.textlength(c, font=font) for c in s) + track * (len(s) - 1)
    x = cx - w / 2
    for c in s:
        d.text((x, y), c, font=font, fill=(255, 255, 255, 255))
        x += d.textlength(c, font=font) + track
    return w


def compose(photo, en, zh, cx=0.5, top=0.10, en_size=None, zh_size=58, track=None, en_font="futura"):
    """photo: an already-retouched PIL image at W×H. Returns the finished cover."""
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    if en_font == "zh":
        size = en_size or 128
        f = _pingfang(size)
        tr = track if track is not None else 8
    else:
        size = en_size or (118 if len(en) <= 12 else max(78, int(118 * 12 / len(en))))
        f = _futura(size)
        tr = track if track is not None else int(size * 0.12)
    while _tracked(ImageDraw.Draw(Image.new("RGBA", (1, 1))), 0, 0, en, f, tr) > W * 0.9 and size > 50:
        size -= 6
        f = _futura(size) if en_font != "zh" else _pingfang(size)
        tr = int(size * 0.12) if en_font != "zh" else tr
    y0 = int(H * top)
    _tracked(d, W * cx, y0, en, f, tr)
    if zh:
        d.text((W * cx, y0 + size + 48), zh, font=_pingfang(zh_size), fill=(255, 255, 255, 255), anchor="mm")
    a = txt.split()[3]
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh.putalpha(a.filter(ImageFilter.GaussianBlur(12)).point(lambda v: int(min(255, v * 0.85))))
    out = photo.convert("RGBA")
    out.alpha_composite(sh)
    out.alpha_composite(txt)
    return out.convert("RGB")


def render(frame_path, out_path, en, zh, cx=0.5, top=0.10, crop=(0.5, 0.5), style="natural", **kw):
    """Retouch the frame ("natural", the creator's pick), crop it to 16:9 and add the type."""
    im = Image.open(frame_path).convert("RGB")
    photo = fit(retouch(im, style), W, H, *crop)
    out = compose(photo, en, zh, cx=cx, top=top, **kw)
    out.save(out_path, quality=92)
    return out_path
