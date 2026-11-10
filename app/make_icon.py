"""审片 app icon. Several candidate designs on the macOS Big Sur+ icon grid (824 px squircle body centred in a
1024 canvas, soft drop shadow, light-from-above shading). Drawn 4x oversampled with Pillow, then downsampled.

    python app/make_icon.py <out.png>                 # the chosen icon (DEFAULT) as a 1024 px PNG; build.sh uses this
    python app/make_icon.py <out.png> --variant seal  # one candidate
    python app/make_icon.py --all <dir>               # every candidate as <dir>/<name>.png (for icon_options.html)

Candidates:
  seal    「审」 in champagne Songti inside thin viewfinder corners, on warm ink
  paper   the same seal inverted: ink 「审」 and champagne corners on porcelain
  finder  black viewfinder brackets around a champagne play triangle, on porcelain
  film    a filmstrip with a champagne playhead, on graphite
  loupe   a loupe over a dusk skyline frame, on white
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

DEFAULT = "paper"   # creator 2026-11-10: 「logo用B」
SS = 4                       # oversampling
S = 1024 * SS
B0, BS = 100 * SS, 824 * SS  # body origin + size (Apple grid)
SONGTI = "/System/Library/Fonts/Supplemental/Songti.ttc"
GOLD_HI, GOLD_LO = (240, 222, 182), (176, 136, 78)   # champagne (thumbnail accent #C9A96E sits in between)


def px(v):
    return int(round(v * SS))


def squircle(x0, y0, w, h):
    """L mask of the macOS icon shape: a rounded rect whose corners are superellipse arcs (continuous curvature,
    flat sides), corner extent 30% of the side. Antialiased edge."""
    R, n = .30 * w, 2.8
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    dx = np.maximum(np.abs(xx + .5 - (x0 + w / 2)) - (w / 2 - R), 0) / R
    dy = np.maximum(np.abs(yy + .5 - (y0 + h / 2)) - (h / 2 - R), 0) / R
    dist = (1 - (dx ** n + dy ** n) ** (1 / n)) * R          # ~signed distance to the edge, in pixels
    a = np.clip(dist / (1.2 * SS) + .5, 0, 1)
    return Image.fromarray((a * 255).astype(np.uint8))


def vgrad(c_top, c_bot, y0=0, y1=S):
    """Full-canvas RGBA vertical gradient between rows y0..y1 (clamped outside)."""
    t = np.clip((np.arange(S, dtype=np.float32) - y0) / max(1, y1 - y0), 0, 1)[:, None, None]
    ct, cb = np.array(c_top[:3], np.float32), np.array(c_bot[:3], np.float32)
    rgb = np.broadcast_to(ct + (cb - ct) * t, (S, S, 3))
    a = np.full((S, S, 1), 255, np.float32)
    return Image.fromarray(np.concatenate([rgb, a], -1).astype(np.uint8))


def solid(c):
    return Image.new("RGBA", (S, S), tuple(c[:3]) + (255,))


def scale(mask, a):
    return mask.point(lambda v: v * a // 255)


def paint(dst, src, mask):
    layer = src.copy()
    layer.putalpha(ImageChops.multiply(src.getchannel("A"), mask))
    dst.alpha_composite(layer)


def shadow(dst, mask, dy, blur, alpha):
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sh.putalpha(ImageChops.offset(scale(mask, alpha), 0, px(dy)).filter(ImageFilter.GaussianBlur(px(blur))))
    dst.alpha_composite(sh)


def crisp(mask, round_px):
    """Round the corners of a hard shape: blur, re-threshold, then a hairline of antialiasing."""
    m = mask.filter(ImageFilter.GaussianBlur(px(round_px))).point(lambda v: 255 if v > 127 else 0)
    return m.filter(ImageFilter.GaussianBlur(SS * .6))


def base(top, bot, rim_a=60):
    """Drop shadow + gradient squircle body + a light rim fading downward. Returns (img, body_mask)."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    body = squircle(B0, B0, BS, BS)
    shadow(img, body, 8, 10, 70)      # contact
    shadow(img, body, 22, 34, 46)     # ambient
    paint(img, vgrad(top, bot, B0, B0 + BS), body)
    if rim_a:
        rim = ImageChops.subtract(body, inset_body(3))
        fade = vgrad((rim_a,) * 3, (0,) * 3, B0, B0 + BS * .55).getchannel("R")
        paint(img, solid((255, 255, 255)), ImageChops.multiply(rim, fade))
    return img, body


def inset_body(d):
    """The body squircle shrunk by d px (1x units): for rims and edges without slow morphology filters."""
    return squircle(B0 + px(d), B0 + px(d), BS - 2 * px(d), BS - 2 * px(d))


def disc(cx, cy, r):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).ellipse([px(cx - r), px(cy - r), px(cx + r), px(cy + r)], fill=255)
    return m


def gold(y0, y1):
    return vgrad(GOLD_HI, GOLD_LO, px(y0), px(y1))


def brackets(inset, length, width):
    """L mask with four viewfinder corner marks inside the body (round caps)."""
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    a, b = 100 + inset, 924 - inset
    r = width / 2
    for x, y, sx, sy in [(a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)]:
        xs = sorted([x - sx * r, x + sx * length])
        ys = sorted([y - sy * r, y + sy * length])
        d.rounded_rectangle([px(xs[0]), px(y - r), px(xs[1]), px(y + r)], px(r), fill=255)
        d.rounded_rectangle([px(x - r), px(ys[0]), px(x + r), px(ys[1])], px(r), fill=255)
    return m


def glyph(ch, index, size, cx, cy):
    f = ImageFont.truetype(SONGTI, px(size), index=index)
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    l, t, r, b = d.textbbox((0, 0), ch, font=f)
    d.text((px(cx) - (l + r) / 2, px(cy) - (t + b) / 2), ch, font=f, fill=255)
    return m


# ------------------------------------------------------------------ candidates
def v_seal():
    img, body = base((48, 45, 41), (16, 15, 14))
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse([px(272), px(262), px(752), px(742)], fill=70)
    paint(img, solid((201, 169, 110)), ImageChops.multiply(glow.filter(ImageFilter.GaussianBlur(px(120))), body))
    paint(img, gold(200, 830), scale(brackets(118, 92, 12), 210))
    g = glyph("审", 0, 446, 512, 516)
    shadow(img, g, 5, 9, 140)
    paint(img, gold(300, 740), g)
    return img


def v_paper():
    img, body = base((255, 255, 254), (236, 233, 226), rim_a=0)
    paint(img, solid((0, 0, 0)), scale(ImageChops.subtract(body, inset_body(2)), 30))
    paint(img, gold(200, 830), brackets(118, 92, 14))
    g = glyph("审", 0, 470, 512, 518)
    shadow(img, g, 4, 8, 60)
    paint(img, vgrad((52, 50, 48), (18, 17, 16), px(300), px(740)), g)
    return img


def v_finder():
    img, body = base((255, 255, 255), (230, 228, 223), rim_a=0)
    edge = ImageChops.subtract(body, inset_body(2))
    paint(img, solid((0, 0, 0)), scale(edge, 30))
    paint(img, solid((26, 26, 28)), brackets(150, 150, 42))
    tri = Image.new("L", (S, S), 0)
    cx, cy, h = 530, 512, 300
    ImageDraw.Draw(tri).polygon([(px(cx - h * .43), px(cy - h / 2)), (px(cx - h * .43), px(cy + h / 2)),
                                 (px(cx + h * .50), px(cy))], fill=255)
    tri = crisp(tri, 14)
    shadow(img, tri, 8, 14, 80)
    paint(img, gold(cy - h / 2, cy + h / 2), tri)
    return img


def v_film():
    img, body = base((60, 60, 64), (21, 21, 24))
    band = Image.new("L", (S, S), 0)
    ImageDraw.Draw(band).rectangle([0, px(332), S, px(692)], fill=255)
    band = ImageChops.multiply(band, body)
    shadow(img, band, 6, 16, 150)
    paint(img, solid((12, 12, 13)), band)
    holes = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(holes)
    for i in range(-1, 13):
        x = 118 + i * 76
        for y in (350, 648):
            d.rounded_rectangle([px(x), px(y), px(x + 40), px(y + 26)], px(7), fill=255)
    paint(img, solid((72, 72, 78)), ImageChops.multiply(holes, body))
    frames = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(frames)
    for x in (90, 380, 670):
        d.rounded_rectangle([px(x), px(394), px(x + 264), px(630)], px(14), fill=255)
    frames = ImageChops.multiply(frames, body)
    paint(img, vgrad((86, 98, 140), (238, 168, 120), px(394), px(630)), frames)
    mid = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mid).rounded_rectangle([px(380), px(394), px(644), px(630)], px(14), fill=255)
    paint(img, vgrad((116, 130, 178), (255, 196, 140), px(394), px(630)), mid)
    paint(img, solid((10, 10, 12)), scale(ImageChops.subtract(frames, mid), 120))
    ph = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(ph)
    x = 560
    d.rectangle([px(x - 8), px(250), px(x + 8), px(792)], fill=255)
    d.polygon([(px(x - 40), px(200)), (px(x + 40), px(200)), (px(x + 40), px(246)), (px(x), px(282)),
               (px(x - 40), px(246))], fill=255)
    ph = crisp(ph, 4)
    shadow(img, ph, 6, 10, 160)
    paint(img, gold(200, 792), ph)
    return img


def v_loupe():
    img, body = base((255, 255, 255), (232, 231, 228), rim_a=0)
    edge = ImageChops.subtract(body, inset_body(2))
    paint(img, solid((0, 0, 0)), scale(edge, 30))
    fx0, fy0, fx1, fy1 = 196, 262, 764, 582
    fr = Image.new("L", (S, S), 0)
    ImageDraw.Draw(fr).rounded_rectangle([px(fx0), px(fy0), px(fx1), px(fy1)], px(30), fill=255)
    shadow(img, fr, 10, 22, 70)
    paint(img, vgrad((92, 110, 160), (246, 176, 128), px(fy0), px(fy1 - 50)), fr)
    sky = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(sky)
    for x, w, h in [(214, 40, 70), (258, 30, 110), (296, 46, 60), (350, 26, 150), (382, 36, 90), (430, 54, 50),
                    (500, 30, 120), (540, 44, 80), (600, 38, 100), (650, 60, 56), (716, 40, 76)]:
        d.rectangle([px(x), px(fy1 - h), px(x + w), px(fy1)], fill=255)
    d.rectangle([px(360), px(fy1 - 236), px(366), px(fy1 - 150)], fill=255)
    d.ellipse([px(349), px(fy1 - 200), px(377), px(fy1 - 172)], fill=255)
    paint(img, solid((38, 36, 46)), ImageChops.multiply(sky, fr))
    cx, cy, r = 648, 600, 150
    lens = disc(cx, cy, r)
    handle = Image.new("L", (S, S), 0)
    e0, e1 = r * .66, r * 1.34
    hd = ImageDraw.Draw(handle)
    hd.line([(px(cx + e0), px(cy + e0)), (px(cx + e1), px(cy + e1))], fill=255, width=px(60))
    hd.ellipse([px(cx + e1 - 30), px(cy + e1 - 30), px(cx + e1 + 30), px(cy + e1 + 30)], fill=255)
    ring = ImageChops.subtract(disc(cx, cy, r + 26), lens)
    shadow(img, ImageChops.lighter(ImageChops.lighter(lens, handle), ring), 14, 24, 110)
    paint(img, solid((26, 26, 28)), handle)
    paint(img, solid((255, 238, 214)), scale(lens, 64))
    hl = Image.new("L", (S, S), 0)
    ImageDraw.Draw(hl).ellipse([px(cx - r * .74), px(cy - r * .82), px(cx + r * .1), px(cy - r * .22)], fill=255)
    paint(img, solid((255, 255, 255)), scale(ImageChops.multiply(hl.filter(ImageFilter.GaussianBlur(px(18))), lens), 150))
    paint(img, solid((26, 26, 28)), ring)
    paint(img, gold(cy - r, cy + r), ImageChops.subtract(lens, disc(cx, cy, r - 8)))
    return img


VARIANTS = {"seal": v_seal, "paper": v_paper, "finder": v_finder, "film": v_film, "loupe": v_loupe}


def render(name):
    return VARIANTS[name]().resize((1024, 1024), Image.LANCZOS)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--all"]:
        out = Path(args[1])
        out.mkdir(parents=True, exist_ok=True)
        for n in VARIANTS:
            render(n).save(out / f"{n}.png")
            print(out / f"{n}.png")
    else:
        render(args[args.index("--variant") + 1] if "--variant" in args else DEFAULT).save(args[0])
