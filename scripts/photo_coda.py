"""Photo-print coda (research R8): stills from the trip drop one by one onto a soft paper background
as prints (white border, a handwritten label on the wider bottom edge, slight tilt, soft shadow),
with a gentle Ken Burns on the top print and a slow push-in on the whole stack. Output is a
`card.image` mp4 for the EDL (place it before the end screen, over the music's last phrase).

Animatic first: `--stills` writes full-size PNGs at a few times so they can be checked before
the (slower) encode. Raw clips are only read.

Spec (JSON):
{
  "out": "/abs/…/edit/cards/slideshow.mp4",
  "dur": 9.1,                                   # seconds; prints enter evenly, the last one holds longer
  "hold_last": 1.8,                             # optional: seconds the last print stays on alone
  "prints": [
    {"clip": "/abs/…/DJI_…_0359_D.MP4", "t": 3.0, "vf": "eq=contrast=1.05:saturation=1.10",
     "crop": [0.5, 0.5, 1.0],                   # optional: centre x, y and size (fraction of the frame, 16:9 kept)
     "label": "7 月 3 日 · 摘桃"},
    {"image": "/abs/…/photo.jpg", "label": "…"}  # or a real photo (centre-cropped to 16:9)
  ]
}
Run: ./venv/bin/python scripts/photo_coda.py spec.json [--stills 0.3,2.0,9.0] [--encode]
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 3840, 2160, 30
PAPER = (240, 233, 216)
INK = (62, 52, 42)
HAND_FONTS = [  # handwriting-ish CJK faces shipped as macOS downloadable assets; fall back to STHeiti
    "HanziPen.ttc", "WawaSC-Regular.otf", "Kaiti.ttc"]
FALLBACK = "/System/Library/Fonts/STHeiti Medium.ttc"
PW = int(W * 0.50)            # photo width inside the print
PH = PW * 9 // 16
SIDE, BOTTOM = int(W * 0.014), int(W * 0.05)
ENTER = 0.55                  # seconds for a print to slide in


def find_font():
    roots = ["/System/Library/AssetsV2", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    for name in HAND_FONTS:
        for r in roots:
            for dp, _, fs in os.walk(r):
                if name in fs:
                    return os.path.join(dp, name)
    return FALLBACK


def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def grab(p):
    if p.get("image"):
        im = Image.open(p["image"]).convert("RGB")
    else:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            out = f.name
        vf = "scale=3840:2160:flags=lanczos" + ("," + p["vf"] if p.get("vf") else "")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{p['t']:.3f}", "-i", p["clip"], "-frames:v", "1",
                        "-vf", vf, out], check=True)
        im = Image.open(out).convert("RGB")
        os.remove(out)
    cx, cy, s = p.get("crop", [0.5, 0.5, 1.0])
    iw, ih = im.size
    cw = min(iw, ih * 16 / 9) * s
    ch = cw * 9 / 16
    x0 = min(max(0, cx * iw - cw / 2), iw - cw)
    y0 = min(max(0, cy * ih - ch / 2), ih - ch)
    return im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))


def background():
    bg = Image.new("RGB", (W, H), PAPER)
    rnd = random.Random(7)
    noise = Image.effect_noise((W // 4, H // 4), 18).resize((W, H), Image.BICUBIC)
    bg = Image.blend(bg, Image.merge("RGB", [noise.point(lambda v: 200 + v * 0.2)] * 3), 0.10)
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W * 0.15, -H * 0.25, W * 1.15, H * 1.25], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(H * 0.12))
    dark = Image.new("RGB", (W, H), (205, 194, 172))
    del rnd
    return Image.composite(bg, dark, vig)


class Print:
    def __init__(self, spec, font, angle, dx, dy):
        self.photo = grab(spec)
        self.label = spec.get("label", "")
        self.font = font
        self.angle, self.dx, self.dy = angle, dx, dy
        self._still = None

    def card(self, kb):
        """Unrotated print at Ken Burns zoom kb (1.0 = whole photo)."""
        pw, ph = self.photo.size
        cw, ch = pw / kb, ph / kb
        ph_im = self.photo.crop((int((pw - cw) / 2), int((ph - ch) / 2), int((pw + cw) / 2), int((ph + ch) / 2)))
        ph_im = ph_im.resize((PW, PH), Image.LANCZOS)
        c = Image.new("RGBA", (PW + 2 * SIDE, PH + SIDE + BOTTOM), (252, 251, 247, 255))
        c.paste(ph_im, (SIDE, SIDE))
        if self.label:
            d = ImageDraw.Draw(c)
            f = self.font
            d.text((SIDE + int(W * 0.006), PH + SIDE + BOTTOM * 0.48), self.label, font=f, fill=INK + (235,), anchor="lm")
        return c

    def rendered(self, kb):
        c = self.card(kb).rotate(self.angle, resample=Image.BICUBIC, expand=True)
        a = c.getchannel("A")
        pad = int(H * 0.04)
        sh = Image.new("L", (c.width + 2 * pad, c.height + 2 * pad), 0)
        sh.paste(a.point(lambda v: v * 0.42), (pad, pad))
        sh = sh.filter(ImageFilter.GaussianBlur(H * 0.012))
        return c, sh, pad

    def paste(self, canvas, kb, t_in, alpha=1.0):
        """Draw onto canvas; t_in in [0, 1] = entry progress."""
        c, sh, pad = self.rendered(kb)
        # opaque slide-in from below the frame (a fade would ghost the print underneath through it)
        e = ease_out(t_in)
        x = int(W / 2 + self.dx - c.width / 2)
        y = int(H / 2 + self.dy - c.height / 2 + (1 - e) * H * 0.85)
        a = alpha
        shadow_off = int(H * 0.012 + (1 - e) * H * 0.02)
        black = Image.new("RGBA", sh.size, (30, 22, 12, 255))
        black.putalpha(sh.point(lambda v: int(v * a)))
        canvas.alpha_composite(black, (x - pad + shadow_off, y - pad + shadow_off))
        if a < 1:
            c.putalpha(c.getchannel("A").point(lambda v: int(v * a)))
        canvas.alpha_composite(c, (x, y))


def build(spec):
    font = ImageFont.truetype(find_font(), int(H * 0.040))
    rnd = random.Random(spec.get("seed", 3))
    n = len(spec["prints"])
    angles = spec.get("angles") or [rnd.choice([-1, 1]) * rnd.uniform(1.4, 3.6) for _ in range(n)]
    angles[-1] = spec.get("last_angle", max(-1.5, min(1.5, angles[-1] / 2)))
    offs = [(rnd.uniform(-0.06, 0.06) * W, rnd.uniform(-0.05, 0.04) * H) for _ in range(n)]
    offs[-1] = (0, -0.01 * H)
    prints = [Print(p, font, a, dx, dy) for p, a, (dx, dy) in zip(spec["prints"], angles, offs)]
    dur = spec["dur"]
    hold_last = spec.get("hold_last", 1.8)
    step = (dur - hold_last) / max(1, n - 1)
    starts = [k * step for k in range(n)]
    bg = background().convert("RGBA")
    stack_cache = {}

    def stack_below(k):
        """Canvas with prints 0..k-1 landed (each frozen at its Ken Burns value when covered)."""
        if k not in stack_cache:
            base = bg.copy() if k == 0 else stack_below(k - 1).copy()
            if k > 0:
                kb = 1.0 + 0.045 * min(1.0, (starts[k] - starts[k - 1]) / (step + hold_last))
                prints[k - 1].paste(base, kb, 1.0)
            stack_cache[k] = base
        return stack_cache[k]

    def frame(t):
        k = max(i for i in range(n) if starts[i] <= t + 1e-6)
        canvas = stack_below(k).copy()
        life = (dur - starts[k]) if k == n - 1 else (step + hold_last)
        kb = 1.0 + 0.045 * min(1.0, (t - starts[k]) / life)
        prints[k].paste(canvas, kb, min(1.0, (t - starts[k]) / ENTER))
        z = 1.0 + 0.035 * (t / dur)   # slow push-in on the whole stack
        cw, ch = W / z, H / z
        canvas = canvas.crop((int((W - cw) / 2), int((H - ch) / 2), int((W + cw) / 2), int((H + ch) / 2)))
        return canvas.resize((W, H), Image.BICUBIC).convert("RGB")

    return frame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--stills", default="")
    ap.add_argument("--encode", action="store_true")
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding="utf-8"))
    frame = build(spec)
    out = spec["out"]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if a.stills:
        for t in [float(x) for x in a.stills.split(",")]:
            p = os.path.splitext(out)[0] + f"_still_{t:.2f}.png"
            frame(t).save(p)
            print(p)
    if a.encode:
        n = int(round(spec["dur"] * FPS))
        with tempfile.TemporaryDirectory() as td:
            for k in range(n):
                frame(k / FPS).save(os.path.join(td, f"{k:04d}.png"), compress_level=1)
            subprocess.run(["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i",
                            os.path.join(td, "%04d.png"), "-c:v", "libx264", "-preset", "slow", "-crf", "14",
                            "-pix_fmt", "yuv420p", out], check=True)
        print(out)


if __name__ == "__main__":
    sys.exit(main())
