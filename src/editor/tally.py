"""Collection tally overlay ("图鉴" counter): a running count of the kinds of things met in a section
(animals on a drive-through safari, dishes at a food market, peaks on a hike), built from real crops.

Three assets, all transparent so they ride on the existing `pip` layer (no renderer change):
  * add_<k>.mov  - the k-th item arrives: a round photo pops in (top-right card) with its number, Chinese
                   and English name and an optional one-line fact, a row of n progress dots fills, then
                   the card folds into the badge. PNG-in-MOV keeps the alpha.
  * badge_<k>.png - the small persistent badge between arrivals: "<title> k/n" + the progress dots.
  * grid.mp4     - an optional full-frame recap card: every item's photo and name in a grid.

`attach(shots, events, ...)` writes the pip entries onto the EDL shots of the section: each event is
(shot, source time, item index); the arrival plays on that shot (moved earlier if it would run past the
shot end, so a pip never has to span a cut) and the badge for the current count covers everything else
from the first arrival to the end of the section.

    ./venv/bin/python -m src.editor.tally <spec.json> [--stills]
spec: {"title": "动物图鉴", "out_dir": "cards/tally" (relative to the spec file), "size": [3840, 2160],
       "items": [{"cn": "鸵鸟", "en": "Ostrich", "image": "crops/ostrich.jpg", "fact": "..."}, ...],
       "grid": {"title": "...", "sub": "..."}, "add_dur": 4.0}
Images are square-ish crops (the module centre-crops them to a circle).
"""
import argparse
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter

from . import edl as E
from .routemap import font, font_path

# layout at 4K (scaled by size); the card sits top-right, clear of the top-left place tag
CARD = {"x": 0.635, "y": 0.045, "w": 0.34, "h": 0.215}       # arrival card box (frame fractions)
BADGE = {"x": 0.80, "y": 0.045, "w": 0.175, "h": 0.085}      # small badge box
INK = (255, 255, 255)
ACCENT = (255, 205, 60)
PANEL = (20, 24, 28, 178)
DOT_OFF = (255, 255, 255, 90)


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def pop(t):
    """0 -> 1 with a small overshoot."""
    t = max(0.0, min(1.0, t))
    return 1 + 2.7 * (t - 1) ** 3 + 1.7 * (t - 1) ** 2


def circle_photo(path, d):
    """The image centre-cropped to a d x d circle with a white ring (RGBA)."""
    im = Image.open(path).convert("RGB")
    s = min(im.size)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2))
    im = im.resize((d, d), Image.LANCZOS)
    m = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(m).ellipse([0, 0, d * 4 - 1, d * 4 - 1], fill=255)
    m = m.resize((d, d), Image.LANCZOS)
    out = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    out.paste(im, (0, 0), m)
    ring = Image.new("RGBA", (d * 4, d * 4), (0, 0, 0, 0))
    rw = max(4, d // 22) * 4
    ImageDraw.Draw(ring).ellipse([rw // 2, rw // 2, d * 4 - rw // 2, d * 4 - rw // 2], outline=INK + (255,), width=rw)
    out.alpha_composite(ring.resize((d, d), Image.LANCZOS))
    return out


class Tally:
    def __init__(self, spec, base_dir="."):
        self.spec = spec
        self.base = base_dir
        self.W, self.H = spec.get("size", [3840, 2160])
        self.k = self.W / 3840
        self.items = spec["items"]
        self.n = len(self.items)
        self.title = spec.get("title", "图鉴")
        self.heavy = font_path("heavy")
        self.sans = font_path("sans")
        self._photos = {}

    def F(self, kind, size):
        return font(self.heavy if kind == "heavy" else self.sans, max(8, round(size * self.k)))

    def photo(self, i, d):
        key = (i, d)
        if key not in self._photos:
            self._photos[key] = circle_photo(os.path.join(self.base, self.items[i]["image"]), d)
        return self._photos[key]

    def box(self, b):
        return (round(b["x"] * self.W), round(b["y"] * self.H), round(b["w"] * self.W), round(b["h"] * self.H))

    # ── pieces ────────────────────────────────────────────────────────────────────────────────
    def dots(self, d, x, y, w, filled, highlight=None, a=1.0):
        """n progress dots across width w starting at (x, y centre); `filled` of them lit."""
        n = self.n
        step = w / n
        r = min(step * 0.32, 16 * self.k)
        for i in range(n):
            cx = x + step * (i + 0.5)
            if i < filled:
                col = ACCENT if i == highlight else INK
                d.ellipse([cx - r, y - r, cx + r, y + r], fill=col + (round(255 * a),))
            else:
                d.ellipse([cx - r, y - r, cx + r, y + r], outline=DOT_OFF[:3] + (round(DOT_OFF[3] * a),),
                          width=max(2, round(3 * self.k)))

    def badge(self, count, a=1.0):
        """RGBA frame with only the badge (count items so far)."""
        im = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        if count <= 0 or a <= 0:
            return im
        x, y, w, h = self.box(BADGE)
        lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.rounded_rectangle([x, y, x + w, y + h], radius=round(h * 0.28), fill=PANEL[:3] + (round(PANEL[3] * a),))
        pd = round(h * 0.70)
        ph = self.photo(count - 1, pd)
        if a < 1:
            ph = ph.copy()
            ph.putalpha(ph.getchannel("A").point(lambda v: round(v * a)))
        lay.alpha_composite(ph, (x + round(h * 0.15), y + round(h * 0.15)))
        tx = x + round(h * 0.15) + pd + round(22 * self.k)
        d.text((tx, y + h * 0.30), f"{self.title}", font=self.F("sans", 48), fill=INK + (round(230 * a),), anchor="lm")
        d.text((x + w - round(26 * self.k), y + h * 0.30), f"{count}/{self.n}", font=self.F("heavy", 56),
               fill=ACCENT + (round(255 * a),), anchor="rm")
        self.dots(d, tx, y + h * 0.72, x + w - round(26 * self.k) - tx, count, a=a)
        im.alpha_composite(lay)
        return im

    def add_frame(self, i, t, dur):
        """Frame at t of item i's arrival (item index i -> count i+1)."""
        k, it = self.k, self.items[i]
        im = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        fold0 = dur - 0.7                                   # card folds into the badge over the last 0.7 s
        a_in = ease(t / 0.25)
        fold = ease((t - fold0) / 0.55)
        if fold >= 1:
            return self.badge(i + 1)
        x, y, w, h = self.box(CARD)
        bx, by, bw, bh = self.box(BADGE)
        # the panel shrinks from the card box to the badge box while folding
        lx, ly = x + (bx - x) * fold, y + (by - y) * fold
        lw, lh = w + (bw - w) * fold, h + (bh - h) * fold
        lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.rounded_rectangle([lx, ly, lx + lw, ly + lh], radius=round(min(lh, h) * 0.18),
                            fill=PANEL[:3] + (round(PANEL[3] * a_in),))
        a_txt = a_in * (1 - ease((t - fold0) / 0.3))
        pd = round(h * 0.80)
        s = pop((t - 0.1) / 0.45)
        if s > 0.02 and fold < 0.6:
            dd = max(2, round(pd * s * (1 - fold)))
            ph = self.photo(i, pd).resize((dd, dd), Image.LANCZOS)
            if a_txt < 1:
                ph.putalpha(ph.getchannel("A").point(lambda v: round(v * max(0.0, a_txt))))
            cx, cy = x + h * 0.10 + pd / 2, y + h / 2
            # a soft glow behind the new photo for the first half second
            g = ease(1 - (t - 0.3) / 0.6) if t > 0.3 else ease(t / 0.3)
            if g > 0:
                glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
                gr = pd * 0.62
                ImageDraw.Draw(glow).ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=ACCENT + (round(150 * g),))
                lay.alpha_composite(glow.filter(ImageFilter.GaussianBlur(28 * k)))
            lay.alpha_composite(ph, (round(cx - dd / 2), round(cy - dd / 2)))
        if a_txt > 0:
            A = lambda c, f=1.0: c + (round(255 * max(0.0, a_txt) * f),)  # noqa: E731
            tx = x + h * 0.10 + pd + 44 * k
            d.text((tx, y + h * 0.17), f"No.{i + 1}", font=self.F("heavy", 46), fill=A(ACCENT), anchor="lm")
            d.text((x + w - 40 * k, y + h * 0.17), f"{self.title} {i + 1}/{self.n}", font=self.F("sans", 40),
                   fill=A(INK, 0.85), anchor="rm")
            d.text((tx, y + h * 0.40), it["cn"], font=self.F("heavy", 96), fill=A(INK), anchor="lm")
            name_w = d.textlength(it["cn"], font=self.F("heavy", 96))
            if it.get("en"):
                d.text((tx + name_w + 26 * k, y + h * 0.43), it["en"], font=self.F("sans", 52),
                       fill=A(INK, 0.85), anchor="lm")
            if it.get("fact"):
                d.text((tx, y + h * 0.63), it["fact"], font=self.F("sans", 56), fill=A(INK, 0.95), anchor="lm")
            lit = i + (1 if t > 0.35 else 0)
            self.dots(d, tx, y + h * 0.85, x + w - 40 * k - tx, lit, highlight=i, a=max(0.0, a_txt))
        im.alpha_composite(lay)
        if fold > 0:   # the badge fades in under the folding card
            im = Image.alpha_composite(self.badge(i + 1, a=fold), im)
        return im

    def grid_frame(self, t, dur, bg=None):
        """Full-frame recap: every item's photo + name pops in, row by row."""
        k = self.k
        im = (bg.copy().convert("RGBA") if bg is not None else Image.new("RGBA", (self.W, self.H), (24, 28, 30, 255)))
        lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.rectangle([0, 0, self.W, self.H], fill=(12, 14, 16, round(170 * ease(t / 0.4))))
        g = self.spec.get("grid", {})
        a0 = ease(t / 0.4)
        d.text((self.W / 2, self.H * 0.10), g.get("title", f"{self.title}：{self.n} 种"), font=self.F("heavy", 120),
               fill=INK + (round(255 * a0),), anchor="mm")
        if g.get("sub"):
            d.text((self.W / 2, self.H * 0.175), g["sub"], font=self.F("sans", 60), fill=ACCENT + (round(255 * a0),),
                   anchor="mm")
        cols = min(6, self.n)
        rows = math.ceil(self.n / cols)
        cw, rh = self.W * 0.84 / cols, self.H * 0.70 / rows
        pd = round(min(cw, rh) * 0.66)
        step = min(0.18, max(0.05, (dur - 1.6) / max(1, self.n)))
        for i, it in enumerate(self.items):
            r, c = divmod(i, cols)
            n_in_row = min(cols, self.n - r * cols)
            x0 = self.W / 2 - n_in_row * cw / 2
            cx = x0 + cw * (c + 0.5)
            cy = self.H * 0.24 + rh * r + pd / 2
            s = pop((t - 0.4 - i * step) / 0.4)
            if s <= 0.02:
                continue
            dd = max(2, round(pd * s))
            lay.alpha_composite(self.photo(i, pd).resize((dd, dd), Image.LANCZOS), (round(cx - dd / 2), round(cy - dd / 2)))
            a = ease((t - 0.5 - i * step) / 0.3)
            d.text((cx, cy + pd / 2 + 52 * k), it["cn"], font=self.F("heavy", 62), fill=INK + (round(255 * a),), anchor="mm")
            if it.get("en"):
                d.text((cx, cy + pd / 2 + 118 * k), it["en"], font=self.F("sans", 40), fill=INK + (round(200 * a),),
                       anchor="mm")
        im.alpha_composite(lay)
        return im


# ── encoding ─────────────────────────────────────────────────────────────────────────────────
def frames_to_video(frame_fn, dur, out, size, fps=30, alpha=True):
    """Pipe RGBA frames to ffmpeg: PNG-in-MOV with alpha (pip overlays) or an opaque H.264 mp4."""
    n = max(1, round(dur * fps))
    W, H = size
    if alpha:
        enc = ["-c:v", "png", "-pix_fmt", "rgba"]
    else:
        enc = ["-c:v", "libx264", "-crf", "14", "-preset", "slow", "-pix_fmt", "yuv420p"]
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                          "-r", str(fps), "-i", "-", *enc, out], stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(frame_fn(i / fps).convert("RGBA").tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg failed writing {out}")
    return out


def render_assets(spec_path, stills=False, only=None):
    """Writes badge_<k>.png, add_<k>.mov (k = 1..n) and grid.mp4 (if spec has "grid") into out_dir.
    With stills=True writes preview PNGs only (animatic: start / pop / hold / fold frames)."""
    spec = json.load(open(spec_path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(spec_path))
    T = Tally(spec, base)
    out = os.path.join(base, spec.get("out_dir", "tally"))
    os.makedirs(out, exist_ok=True)
    dur = float(spec.get("add_dur", 4.0))
    written = []
    for i in range(T.n):
        if only is not None and i not in only:
            continue
        if stills:
            for t in (0.15, 0.5, 2.0, dur - 0.35):
                p = os.path.join(out, f"still_add{i + 1}_{t:.2f}.png")
                T.add_frame(i, t, dur).save(p)
                written.append(p)
            continue
        p = os.path.join(out, f"badge_{i + 1}.png")
        T.badge(i + 1).save(p)
        written.append(p)
        written.append(frames_to_video(lambda t, i=i: T.add_frame(i, t, dur), dur,
                                       os.path.join(out, f"add_{i + 1}.mov"), (T.W, T.H)))
    if spec.get("grid") and only is None:
        g = spec["grid"]
        gd = float(g.get("dur", 6.0))
        bg = Image.open(os.path.join(base, g["bg"])).convert("RGB").resize((T.W, T.H)) if g.get("bg") else None
        if stills:
            for t in (0.5, 1.5, gd - 0.2):
                p = os.path.join(out, f"still_grid_{t:.2f}.png")
                T.grid_frame(t, gd, bg).convert("RGB").save(p)
                written.append(p)
        else:
            written.append(frames_to_video(lambda t: T.grid_frame(t, gd, bg), gd, os.path.join(out, "grid.mp4"),
                                           (T.W, T.H), alpha=False))
    return written


# ── EDL wiring ───────────────────────────────────────────────────────────────────────────────
def attach(shots, events, out_dir="cards/tally", add_dur=4.0, sfx=None, sfx_gain=0.3, sfx_at=0.12, min_badge=0.4):
    """Put the tally on a run of consecutive EDL shots (the section, in timeline order).

    events: [(shot, src_t, item_index)] in arrival order (item_index 0..n-1, one event per item).
    Each arrival plays `add_<k>.mov` on its shot from local(src_t) (moved earlier so it ends inside the
    shot); the badge for the current count fills every other span from the first arrival to the end of
    the section. Existing tally pips/sfx (file under out_dir) are replaced. Returns the arrival windows
    as [(shot id, local t0, local t1, k)]."""
    ids = [id(s) for s in shots]
    tag = out_dir.rstrip("/") + "/"
    for s in shots:
        s["pip"] = [p for p in s.get("pip", []) if not str(p.get("file", "")).startswith(tag)]
        if sfx:
            s["sfx"] = [f for f in s.get("sfx", []) if f.get("_tally") is None]
        if not s["pip"]:
            s.pop("pip")
        if "sfx" in s and not s["sfx"]:
            s.pop("sfx")
    adds = {}
    for shot, src_t, idx in events:
        if id(shot) not in ids:
            raise ValueError("tally event on a shot outside the section")
        dur = E.shot_dur(shot)
        a = max(0.0, min(E.src_to_local(shot, src_t), dur - add_dur))
        adds.setdefault(id(shot), []).append((round(a, 3), round(min(dur, a + add_dur), 3), idx + 1))
    out, count, started = [], 0, False
    full = {"x": 0.0, "y": 0.0, "w": 1.0, "aspect": 16 / 9, "border": 0}
    for s in shots:
        dur = E.shot_dur(s)
        mine = sorted(adds.get(id(s), []))
        t, pips = 0.0, []
        for a, b, k in mine:
            if started and count and a - t >= min_badge:
                pips.append(dict(full, file=f"{tag}badge_{count}.png", t0=round(t, 3), t1=a, fade=0))
            pips.append(dict(full, file=f"{tag}add_{k}.mov", t0=a, t1=b, fade=0))
            out.append((s.get("id"), a, b, k))
            if sfx:
                s.setdefault("sfx", []).append({"file": sfx, "at": round(a + sfx_at, 3), "gain": sfx_gain, "_tally": k})
            started, count, t = True, k, b
        if started and count and dur - t >= min_badge:
            pips.append(dict(full, file=f"{tag}badge_{count}.png", t0=round(t, 3), t1=round(dur, 3), fade=0))
        if pips:
            s["pip"] = s.get("pip", []) + pips
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--stills", action="store_true", help="animatic stills only")
    ap.add_argument("--only", default="", help="comma-separated item numbers (1-based)")
    a = ap.parse_args(argv)
    only = {int(x) - 1 for x in a.only.split(",") if x} or None
    for p in render_assets(a.spec, stills=a.stills, only=only):
        print(p)


if __name__ == "__main__":
    sys.exit(main())
