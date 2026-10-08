"""Split-flap departure board card (Solari style): rows of character tiles flap through random characters
and land on their text one column after another, over a dimmed background (a still with a slow push-in,
or a raw clip). Writes a `card.image` mp4 for the EDL plus a matching flap-click WAV (use it as the card
shot's `sfx` at 0.0). Good for travel transitions and end screens: the next stop, the travel time, the
next episode.

Animatic first: `--stills` writes full-size PNGs at a few times so they can be checked before the encode.
Raw clips are only read.

Spec (JSON):
{
  "out": "/abs/…/edit/cards/departures.mp4",
  "sfx_out": "/abs/…/edit/sfx/flaps.wav",         # optional: synthesized clicks, one per flap (48 kHz mono)
  "dur": 14.0, "fps": 30, "size": [3840, 2160],
  "bg": {"image": "/abs/frame.jpg"} | {"clip": "/abs/GX….MP4", "t": 1.0, "vf": "eq=…"},
        # + optional "dim": 0.5 (0 = black, 1 = untouched), "blur": 8 (px at 4K), "zoom": [1.0, 1.08],
        #   "crop": [x0, y0, x1, y1] (fractions; keep 16:9) to move a landmark out from behind the board
  "board": {"x": 0.055, "y": 0.09, "tiles": 13, "tile_w": 118, "tile_h": 170,   # px at 4K
            "title": "DEPARTURES", "title_cn": "出发", "clock": "12:20"},
  "rows": [
    {"label": "开往", "label_en": "TO", "text": "SAN ANTONIO", "start": 0.8},
    {"label": "车程", "label_en": "TIME", "text": "约 5 小时", "start": 1.6, "color": [255, 214, 90]}
  ],
  "footer": {"text": "下一集见 →", "start": 6.0},  # optional plain line under the board
  "flips": [6, 12],          # random flips per tile before it lands (min, max); 0 = lands at once
  "flip_time": 0.06,         # seconds per flap
  "col_stagger": 0.05,       # each column starts this much later than the one to its left
  "seed": 7
}
Run: ./venv/bin/python scripts/splitflap.py spec.json [--stills 0.5,2.0,13.5] [--encode]
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
CJK_POOL = "东南西北上下大小中天日月山水火车站路口时分出入开往到达约"
HEAVY = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
         "/System/Library/Fonts/Hiragino Sans GB.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
LATIN_FONTS = ["/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
               "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"]
TILE_BG = (28, 28, 30)
TILE_EDGE = (8, 8, 9)
INK = (238, 236, 228)
LABEL = (200, 198, 190)


def _font(size, index=0, fonts=None):
    for p in fonts or HEAVY:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size, index=index)
            except OSError:
                return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def is_cjk(ch):
    return "⺀" <= ch <= "鿿" or "豈" <= ch <= "﫿"


def ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


# ── schedule: what each tile shows at time t ──────────────────────────────────────────────────

def tile_plan(rows, ntiles, flips=(6, 12), flip_time=0.06, col_stagger=0.05, seed=7):
    """Per tile: {"row", "col", "seq": [chars…, final], "t0": first flap start, "dt"}. Shorter texts are padded
    with blanks (blank tiles never flap). Deterministic for a given seed."""
    rnd = random.Random(seed)
    plan = []
    for r, row in enumerate(rows):
        text = list(row["text"])[:ntiles]
        text += [" "] * (ntiles - len(text))
        cjk_row = any(is_cjk(c) for c in text)
        pool = (CJK_POOL + "".join(c for c in text if is_cjk(c))) if cjk_row else LATIN
        for c, final in enumerate(text):
            if final == " ":
                seq = [" "]
            else:
                n = rnd.randint(flips[0], flips[1]) if flips[1] > 0 else 0
                seq = [rnd.choice(pool) for _ in range(n)] + [final]
            plan.append({"row": r, "col": c, "seq": seq, "t0": row.get("start", 0.0) + c * col_stagger,
                         "dt": flip_time})
    return plan


def tile_state(tile, t):
    """(previous char, current char, flap phase 0..1 or None when at rest)."""
    seq, t0, dt = tile["seq"], tile["t0"], tile["dt"]
    if len(seq) == 1 and seq[0] == " ":
        return " ", " ", None
    if t < t0:
        return " ", " ", None
    k = int((t - t0) / dt)
    if k >= len(seq):
        return seq[-1], seq[-1], None
    prev = seq[k - 1] if k > 0 else " "
    return prev, seq[k], ((t - t0) / dt) - k


def flap_times(plan):
    """Every moment a flap lands (for the click track)."""
    return sorted(tile["t0"] + (k + 1) * tile["dt"] for tile in plan if tile["seq"] != [" "]
                  for k in range(len(tile["seq"])))


# ── drawing ───────────────────────────────────────────────────────────────────────────────────

class Tiles:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.cache = {}
        self.f_lat = _font(int(h * 0.80), fonts=LATIN_FONTS + HEAVY)  # condensed bold: the classic board face
        self.f_cjk = _font(int(h * 0.56))

    def face(self, ch, color=INK):
        key = (ch, color)
        if key in self.cache:
            return self.cache[key]
        w, h = self.w, self.h
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(w * 0.09), fill=TILE_BG + (255,))
        if ch.strip():
            f = self.f_cjk if is_cjk(ch) else self.f_lat
            bb = d.textbbox((0, 0), ch, font=f)
            d.text(((w - (bb[2] - bb[0])) / 2 - bb[0], (h - (bb[3] - bb[1])) / 2 - bb[1]), ch, font=f, fill=color)
        # the hinge: a dark line across the middle + a faint highlight under it
        d.line([0, h // 2, w, h // 2], fill=TILE_EDGE + (255,), width=max(2, h // 60))
        d.line([0, h // 2 + max(2, h // 60), w, h // 2 + max(2, h // 60)], fill=(60, 60, 64, 255), width=1)
        self.cache[key] = im
        return im

    def render(self, prev, cur, phase, color=INK):
        """A tile mid-flap: top shows the new char behind the old top half folding down; then the new
        bottom half unfolds over the old bottom half."""
        if phase is None:
            return self.face(cur, color)
        w, h = self.w, self.h
        a, b = self.face(prev, color), self.face(cur, color)
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        top_new, bot_old = b.crop((0, 0, w, h // 2)), a.crop((0, h // 2, w, h))
        im.paste(top_new, (0, 0))
        im.paste(bot_old, (0, h // 2))
        p = ease(phase)
        if p < 0.5:  # old top half folds down toward the hinge
            fh = max(1, int((h // 2) * (1 - p * 2)))
            flap = a.crop((0, 0, w, h // 2)).resize((w, fh))
            shade = Image.new("RGBA", flap.size, (0, 0, 0, int(110 * p * 2)))
            flap = Image.alpha_composite(flap, shade)
            im.paste(flap, (0, h // 2 - fh), flap)
        else:        # new bottom half unfolds from the hinge
            fh = max(1, int((h // 2) * ((p - 0.5) * 2)))
            flap = b.crop((0, h // 2, w, h)).resize((w, fh))
            shade = Image.new("RGBA", flap.size, (0, 0, 0, int(110 * (1 - (p - 0.5) * 2))))
            flap = Image.alpha_composite(flap, shade)
            im.paste(flap, (0, h // 2), flap)
        return im


def _clip_frame(path, t, vf=None, size=(3840, 2160)):
    chain = ",".join(x for x in [vf, f"scale={size[0]}:{size[1]}"] if x)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", chain,
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True).stdout
    return Image.frombytes("RGB", size, raw)


class Board:
    def __init__(self, spec):
        self.s = spec
        self.W, self.H = spec.get("size", [3840, 2160])
        self.fps = spec.get("fps", 30)
        b = dict({"x": 0.055, "y": 0.09, "tiles": 13, "tile_w": 118, "tile_h": 170}, **spec.get("board", {}))
        self.b = b
        self.rows = spec["rows"]
        self.tiles = Tiles(b["tile_w"], b["tile_h"])
        self.plan = tile_plan(self.rows, b["tiles"], tuple(spec.get("flips", [6, 12])), spec.get("flip_time", 0.06),
                              spec.get("col_stagger", 0.05), spec.get("seed", 7))
        bg = spec.get("bg", {})
        if bg.get("image"):
            base = Image.open(bg["image"]).convert("RGB")
        elif bg.get("clip"):
            base = _clip_frame(bg["clip"], bg.get("t", 0.0), bg.get("vf"), (self.W, self.H))
        else:
            base = Image.new("RGB", (self.W, self.H), (20, 22, 26))
        if bg.get("crop"):  # [x0, y0, x1, y1] fractions: e.g. move a landmark out from behind the board
            cx0, cy0, cx1, cy1 = bg["crop"]
            base = base.crop((int(cx0 * base.width), int(cy0 * base.height), int(cx1 * base.width),
                              int(cy1 * base.height)))
        base = base.resize((self.W, self.H))
        if bg.get("blur"):
            base = base.filter(ImageFilter.GaussianBlur(bg["blur"]))
        dim = bg.get("dim", 0.55)
        base = Image.blend(Image.new("RGB", base.size, (0, 0, 0)), base, dim)
        self.base, self.zoom = base, bg.get("zoom", [1.0, 1.06])
        self.f_label = _font(int(b["tile_h"] * 0.36))
        self.f_label_en = _font(int(b["tile_h"] * 0.22))
        self.f_title = _font(int(b["tile_h"] * 0.42), fonts=LATIN_FONTS + HEAVY)
        self.f_title_cn = _font(int(b["tile_h"] * 0.40))
        self.f_footer = _font(int(b["tile_h"] * 0.40))
        self.label_w = int(b["tile_w"] * 2.6)
        self.gap = int(b["tile_w"] * 0.08)
        self.row_gap = int(b["tile_h"] * 0.32)

    def geometry(self):
        """Board panel rectangle (px) — the end-screen-safe check uses it."""
        b = self.b
        x0, y0 = int(b["x"] * self.W), int(b["y"] * self.H)
        head = int(b["tile_h"] * 0.9)
        w = self.label_w + b["tiles"] * (b["tile_w"] + self.gap) + int(b["tile_w"] * 0.5)
        h = head + len(self.rows) * (b["tile_h"] + self.row_gap) + int(b["tile_h"] * 0.2)
        return x0, y0, x0 + w, y0 + h

    def frame(self, t):
        dur = self.s["dur"]
        z = self.zoom[0] + (self.zoom[1] - self.zoom[0]) * ease(t / dur)
        cw, ch = int(self.W / z), int(self.H / z)
        bg = self.base.crop(((self.W - cw) // 2, (self.H - ch) // 2, (self.W - cw) // 2 + cw,
                             (self.H - ch) // 2 + ch)).resize((self.W, self.H))
        im = bg.convert("RGBA")
        b = self.b
        x0, y0, x1, y1 = self.geometry()
        a_in = ease(t / 0.45)   # board panel fades in
        panel = Image.new("RGBA", im.size, (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel)
        pd.rounded_rectangle([x0 - 40, y0 - 30, x1 + 10, y1 + 10], radius=28, fill=(10, 10, 12, int(205 * a_in)))
        head = int(b["tile_h"] * 0.9)
        gold = (255, 196, 64, int(255 * a_in))
        pd.text((x0, y0), b.get("title", "DEPARTURES"), font=self.f_title, fill=gold)
        if b.get("title_cn"):
            tw = pd.textbbox((0, 0), b.get("title", "DEPARTURES"), font=self.f_title)[2]
            pd.text((x0 + tw + int(b["tile_w"] * 0.4), y0 + int(b["tile_h"] * 0.02)), b["title_cn"],
                    font=self.f_title_cn, fill=gold)
        if b.get("clock"):
            bb = pd.textbbox((0, 0), b["clock"], font=self.f_title)
            pd.text((x1 - (bb[2] - bb[0]) - 30, y0), b["clock"], font=self.f_title, fill=INK + (int(255 * a_in),))
        im = Image.alpha_composite(im, panel)
        d = ImageDraw.Draw(im)
        for r, row in enumerate(self.rows):
            ry = y0 + head + r * (b["tile_h"] + self.row_gap)
            la = ease((t - row.get("start", 0.0) + 0.4) / 0.4) * a_in
            d.text((x0, ry + int(b["tile_h"] * 0.08)), row.get("label", ""), font=self.f_label,
                   fill=LABEL + (int(255 * la),))
            if row.get("label_en"):
                d.text((x0, ry + int(b["tile_h"] * 0.58)), row["label_en"], font=self.f_label_en,
                       fill=(150, 150, 146, int(255 * la)))
        color_of = {r: tuple(row.get("color", INK)) for r, row in enumerate(self.rows)}
        for tile in self.plan:
            prev, cur, ph = tile_state(tile, t)
            if t < tile["t0"] - 0.35 and a_in < 1:
                continue
            img = self.tiles.render(prev, cur, ph, color_of[tile["row"]])
            tx = x0 + self.label_w + tile["col"] * (b["tile_w"] + self.gap)
            ty = y0 + head + tile["row"] * (b["tile_h"] + self.row_gap)
            if a_in < 1:
                img = img.copy()
                img.putalpha(img.getchannel("A").point(lambda v: int(v * a_in)))
            im.alpha_composite(img, (tx, ty))
        f = self.s.get("footer")
        if f and t >= f.get("start", 0.0):
            fa = ease((t - f["start"]) / 0.6)
            d.text((x0, y1 + 60), f["text"], font=self.f_footer, fill=INK + (int(255 * fa),),
                   stroke_width=3, stroke_fill=(0, 0, 0, int(200 * fa)))
        return im.convert("RGB")

    def encode(self, out):
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        n = int(round(self.s["dur"] * self.fps))
        p = subprocess.Popen(["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                              "-s", f"{self.W}x{self.H}", "-framerate", str(self.fps), "-i", "-", "-c:v", "libx264",
                              "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                             stdin=subprocess.PIPE)
        for k in range(n):
            p.stdin.write(self.frame(k / self.fps).tobytes())
        p.stdin.close()
        if p.wait() != 0:
            raise RuntimeError("ffmpeg failed")


def click_track(times, dur, out, sr=48000, seed=3, peak=0.5):
    """One short flap click per landing time: a filtered noise tick + a small low knock, jittered, with a
    density-aware level so a burst of 60 simultaneous flaps doesn't clip. Returns the peak written."""
    rnd = np.random.default_rng(seed)
    y = np.zeros(int(dur * sr) + sr // 10)
    n = int(0.012 * sr)
    env = np.exp(-np.linspace(0, 9, n))
    knock = np.sin(2 * np.pi * 180 * np.arange(n) / sr) * np.exp(-np.linspace(0, 6, n))
    for t in times:
        i = int((t + rnd.uniform(-0.004, 0.004)) * sr)
        if i < 0 or i + n >= len(y):
            continue
        noise = rnd.standard_normal(n)
        noise = np.convolve(noise, [0.5, -0.5], mode="same")  # crude high-pass: a dry "tick"
        y[i:i + n] += 0.25 * noise * env + 0.35 * knock
    m = np.max(np.abs(y)) or 1.0
    y = y / m * peak
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    return float(np.max(np.abs(y)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--stills", default="")
    ap.add_argument("--encode", action="store_true")
    a = ap.parse_args(argv)
    spec = json.load(open(a.spec))
    bd = Board(spec)
    if a.stills:
        base = os.path.splitext(spec["out"])[0]
        for t in [float(x) for x in a.stills.split(",")]:
            p = f"{base}_still_{t:05.2f}.png"
            bd.frame(t).save(p)
            print(p)
    if a.encode:
        bd.encode(spec["out"])
        print(spec["out"])
        if spec.get("sfx_out"):
            click_track(flap_times(bd.plan), spec["dur"], spec["sfx_out"])
            print(spec["sfx_out"])


if __name__ == "__main__":
    main(sys.argv[1:])
