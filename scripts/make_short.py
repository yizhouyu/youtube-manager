#!/usr/bin/env python3
"""Render a vertical YouTube Short (1080x1920, 30 fps) from 16:9 source clips, driven by a JSON spec.

    ./venv/bin/python scripts/make_short.py <project>/02 - Export/edit/shorts/<slug>.json [--out out.mp4] [--check]

Output: <project>/02 - Export/shorts/<slug>.mp4 by default (next to thumbnail/), the permanent
archive of every Short's final file -- keep it after upload and list it in that folder's README.md
(file -> YouTube id, publish time, spec). --out or the spec's "output" override it (tests only).

Spec (all times in seconds; segment times and keyframes are SOURCE-clip seconds):

{
  "project": "NN - Trip Name",          # optional: resolves clips to <project>/01 - Unedited/<clip>.MP4
  "output": "/abs/path/short.mp4",      # optional; default <project>/02 - Export/shorts/<spec stem>.mp4
  "style": "punch",                     # punch: heavy captions, {keyword} highlight, pop-in (see below)
                                        # classic (default): the editor's subtitle look, static
  "grades": {"default": "eq=contrast=1.07:saturation=1.2"},   # named ffmpeg color chains (optional)
  "segments": [
    {"clip": "GX015168",                # file stem in the source dir, or an absolute path
     "in": 8.0, "out": 18.0,
     "grade": "default",                # key into grades (optional)
     "audio": "ambient",                # voice (1.0) | ambient (0.35) | mute; "gain_db" adds on top
     "mode": "crop",                    # crop: 9:16 window that follows the subject
                                        # letterbox: whole 16:9 frame over a blurred fill
     "x": [[8.0, 0.26], [12.0, 0.30]],  # crop centre as 0-1 of the source width; a number = static.
                                        # Keyframes are smoothed (no jerky pans); clamped to the frame.
     "y": 0.5, "zoom": 1.0,             # crop: vertical centre (number or keyframes like x; only moves
                                        # when zoom > 1) and extra punch-in (1 = full height)
     "speed": 1.0,                      # >1 = timelapse (audio muted)
     "ramp": [[8.0, 1.0], [10.0, 2.2]], # speed ramp: speed keyframes (source time), linear in between;
                                        # replaces "speed"; the clip's own audio is muted
     "cuts": [[11.2, 12.0]],            # jump cuts: source ranges removed (dead air, a repeated word)
     "jump_zoom": 1.08,                 # with cuts: every other piece is punched in by this factor
     "audio_from": {"clip": "GX015170", "in": 3.2, "audio": "voice", "gain_db": 0,
                    "subs": [{"t0": 3.3, "t1": 5.0, "text": "..."}]},  # voice over B-roll (J/L cut):
                                        # sound from another clip; its subs are in THAT clip's seconds
     "subs": [{"t0": 8.2, "t1": 11.0, "text": "...", "kind": "speech"}]}  # speech | note; "\\n" = line
  ],                                    # break; {word} = keyword highlight (punch style)
  "captions": [{"t0": 0, "t1": null, "text": "...", "style": "headline"}],  # OUTPUT seconds;
                                        # t1 null = to the end; style headline | speech | note
  "hook": {"text": "...\\n一只{...}", "sub": "place · region", "t1": 1.8, "y": 0.16},
                                        # big title that pops in over the first ~1.5-2 s and fades out
                                        # (y = top of the block, 0-1 of H; "size" overrides 118 px)
  "cta": {"text": "关注我 · 带你看更多美国宝藏景点", "button": "关注", "dur": 2.2},
                                        # end overlay: one line + a subscribe-style pill + an arrow that
                                        # bobs toward the channel row; `true` = these defaults. Captions
                                        # still on screen then are lifted above it.
  "loop_xfade": 0.35,                   # last N s dissolve into the first frame, so the loop is seamless
  "music": {"file": "music/track.mp3", "in": 0, "volume": 0.30, "duck": 0.08,
            "match": true,              # loudness-match the track to -14 LUFS first (volume is then
                                        # relative to that; ~0.45 / duck 0.12 is a lively bed)
            "start": 0.0, "fade_in": 0.05, "gain_db": 0},  # output second the music enters
                                        # (natural sound first); file is relative to
                                        # <project>/02 - Export/edit/ or absolute; ducked under speech subs
  "caption_bottom": 0.675,              # where speech/note blocks end (fraction of H); per-sub "y" overrides
  "loudness": {"I": -14, "TP": -1.5},
  "edge_fade": 0.15                     # audio fade at start/end; no video fade, so the Short loops
}

Captions are drawn inside the Shorts safe zone: clear of the top bar, of the right-hand action
buttons and of the bottom title/channel overlay. Speech captions must be what was actually said;
"note" captions are the editor's labels for silent shots (classic: soft yellow; punch: white on a
dark plate, so they never read as dialogue). In punch style {braces} mark keywords, drawn yellow;
the braces are not shown (classic style strips them).

All text is composited into one RGBA overlay track (a PNG sequence whose repeated frames are hard
links), so pop-in, fade and bob animations cost almost nothing.

--check writes full-size frames plus a phone-size contact sheet (with the unsafe zones shaded) and a
1 fps sheet (pace check) to <spec stem>_check/ next to the spec (so the shorts/ archive holds only
final files), to look at before uploading. The report lists every shot's length.
"""
import argparse
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from src.editor import edl as E  # noqa: E402
from src.editor import overlays as O  # noqa: E402

W, H, FPS, SR = 1080, 1920, 30, 48000
AUDIO_GAIN = {"voice": 1.0, "ambient": 0.35, "mute": 0.0}
# Shorts safe zone on a 1080x1920 frame (YouTube overlays: top bar, right-hand buttons, bottom
# title / channel / description). Keep text inside it.
SAFE = {"top": 220, "bottom": 480, "right": 150, "left": 60}
CAPTION_BOTTOM = 0.675  # speech / note block ends here (fraction of H), well above the bottom overlay
HEADLINE_TOP = 0.125
HILITE = (255, 212, 0, 255)       # keyword yellow (the covers use the same)
CTA_TEXT = "关注我 · 带你看更多美国宝藏景点"
CTA_BUTTON = "关注"
CTA_RED = (255, 0, 51, 255)


def run(cmd, **kw):
    """Run ffmpeg/ffprobe at low priority (the machine is usually busy with other renders)."""
    r = subprocess.run(["nice", "-n", "10", *cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(f"{cmd[0]} failed:\n{r.stderr[-3000:]}")
    return r


def probe(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", path])
    j = json.loads(r.stdout)
    s = j["streams"][0]
    return s["width"], s["height"], float(j["format"]["duration"])


def has_audio(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", path])
    return bool(r.stdout.strip())


# ---------------------------------------------------------------- crop path

def smooth_track(keys, t_in, t_out, speed=1.0, step=0.2, sigma=0.35):
    """Keyframes [(src_t, x)] -> [(local_t, x)] sampled every `step` s, linearly interpolated and then
    Gaussian-smoothed so the virtual camera eases instead of snapping between keyframes."""
    if isinstance(keys, (int, float)):
        return [(0.0, float(keys))]
    keys = sorted((float(t), float(x)) for t, x in keys)

    def lin(t):
        if t <= keys[0][0]:
            return keys[0][1]
        for (a, xa), (b, xb) in zip(keys, keys[1:]):
            if t <= b:
                return xa + (xb - xa) * (t - a) / max(1e-6, b - a)
        return keys[-1][1]

    step = max(step, (t_out - t_in) / 50)  # ffmpeg rejects very long crop expressions (~100+ terms)
    n = max(2, int(math.ceil((t_out - t_in) / step)) + 1)
    ts = [t_in + (t_out - t_in) * i / (n - 1) for i in range(n)]
    raw = [lin(t) for t in ts]
    if len(keys) == 1:
        return [(0.0, raw[0])]
    rad = max(1, int(round(3 * sigma / step)))
    wts = [math.exp(-0.5 * (k * step / sigma) ** 2) for k in range(-rad, rad + 1)]
    out = []
    for i in range(n):
        acc = sw = 0.0
        for k, wk in zip(range(-rad, rad + 1), wts):
            j = min(n - 1, max(0, i + k))
            acc += raw[j] * wk
            sw += wk
        out.append(((ts[i] - t_in) / speed, acc / sw))
    return out


def piecewise_expr(points, lo, hi, prec=1, var="t"):
    """Flat (non-nested) ffmpeg expression for a piecewise-linear function of `var`, clamped to [lo, hi]."""
    pts = [(t, min(hi, max(lo, v))) for t, v in points]
    if len(pts) == 1:
        return f"{pts[0][1]:.{prec}f}"
    terms = []
    for (a, va), (b, vb) in zip(pts, pts[1:]):
        slope = (vb - va) / max(1e-6, b - a)
        terms.append(f"gte({var},{a:.4f})*lt({var},{b:.4f})*({va:.{prec}f}+({var}-{a:.4f})*{slope:.5f})")
    terms.append(f"gte({var},{pts[-1][0]:.4f})*{pts[-1][1]:.{prec}f}")
    terms.insert(0, f"lt({var},{pts[0][0]:.4f})*{pts[0][1]:.{prec}f}")
    return "+".join(terms)


# ---------------------------------------------------------------- time map (speed / ramp)

class TimeMap:
    """Source seconds -> output seconds from the segment start, for a constant speed or a ramp."""

    def __init__(self, seg):
        self.t_in, self.t_out = float(seg["in"]), float(seg["out"])
        dur = self.t_out - self.t_in
        ramp = seg.get("ramp")
        if ramp:
            keys = sorted((float(t), max(0.25, float(s))) for t, s in ramp)

            def spd(t):
                if t <= keys[0][0]:
                    return keys[0][1]
                for (a, sa), (b, sb) in zip(keys, keys[1:]):
                    if t <= b:
                        return sa + (sb - sa) * (t - a) / max(1e-6, b - a)
                return keys[-1][1]
            n = max(2, min(40, int(math.ceil(dur / 0.1))))
            src = [self.t_in + dur * i / n for i in range(n + 1)]
            out = [0.0]
            for a, b in zip(src, src[1:]):  # trapezoid on 1/speed
                out.append(out[-1] + (b - a) * 0.5 * (1 / spd(a) + 1 / spd(b)))
            self.pts = [(s - self.t_in, o) for s, o in zip(src, out)]
            self.ramped = True
        else:
            k = max(0.25, float(seg.get("speed", 1.0) or 1.0))
            self.pts = [(0.0, 0.0), (dur, dur / k)]
            self.ramped = k != 1.0
        self.out_dur = self.pts[-1][1]

    def __call__(self, t_src):
        x = min(max(t_src - self.t_in, 0.0), self.pts[-1][0])
        for (a, oa), (b, ob) in zip(self.pts, self.pts[1:]):
            if x <= b:
                return oa + (ob - oa) * (x - a) / max(1e-9, b - a)
        return self.pts[-1][1]

    def setpts(self):
        """setpts filter (applied after PTS-STARTPTS) that retimes the segment."""
        if len(self.pts) == 2:
            k = self.pts[1][0] / max(1e-9, self.pts[1][1])
            return f"setpts=PTS/{k:.6f}"
        return f"setpts='({piecewise_expr(self.pts, 0, 1e6, prec=5, var='T')})/TB'"


# ---------------------------------------------------------------- text

def _parse_marked(text):
    """'a{bc}d' -> [('a', False), ('b', True), ('c', True), ('d', False)] (braces removed)."""
    out, hl = [], False
    for ch in text:
        if ch == "{":
            hl = True
        elif ch == "}":
            hl = False
        else:
            out.append((ch, hl))
    return out


_NO_LINE_START = set("，。、！？；：,.!?;:)）」』”’…·")


def _wrap_marked(d, chars, font, max_w, balance=True):
    """Greedy wrap of [(ch, hl)] (CJK per character, Latin words kept whole), no punctuation at a
    line start, then re-wrapped to even line lengths so a short orphan never dangles."""
    def greedy(limit):
        lines, cur = [], []
        for c in chars:
            s = "".join(x[0] for x in cur)
            if cur and d.textlength(s + c[0], font=font) > limit:
                if c[0] in _NO_LINE_START:        # keep punctuation on the line it closes
                    cur.append(c)
                    lines.append(cur)
                    cur = []
                    continue
                cut = s.rfind(" ") if c[0].isascii() and c[0] != " " else -1
                if c[1] and cur[-1][1]:            # never split a {keyword}: break before it
                    k = len(cur)
                    while k > 0 and cur[k - 1][1]:
                        k -= 1
                    if k > 0:
                        lines.append(cur[:k])
                        cur = cur[k:] + [c]
                        continue
                if cut > 0:
                    lines.append(cur[:cut])
                    cur = cur[cut + 1:] + [c]
                else:
                    lines.append(cur)
                    cur = [c]
            else:
                cur.append(c)
        if cur:
            lines.append(cur)
        return lines
    lines = greedy(max_w)
    if balance and len(lines) > 1:
        total = d.textlength("".join(c[0] for c in chars), font=font)
        target = total / len(lines) * 1.04
        for extra in (0, 0.04, 0.08, 0.12, 0.2):
            alt = greedy(min(max_w, target * (1 + extra)))
            if len(alt) == len(lines):
                return alt
    return lines


def _runs(line):
    runs, cur, flag = [], "", None
    for ch, h in line:
        if flag is None or h == flag:
            cur += ch
        else:
            runs.append((cur, flag))
            cur = ch
        flag = h
    if cur:
        runs.append((cur, flag))
    return runs


def _draw_marked_line(d, x0, y, line, font, stroke, fill=(255, 255, 255, 255), hl=HILITE,
                      stroke_fill=(0, 0, 0, 240)):
    x = x0
    for s, h in _runs(line):
        d.text((x, y), s, font=font, fill=hl if h else fill, stroke_width=stroke, stroke_fill=stroke_fill)
        x += d.textlength(s, font=font)


def _line_w(d, line, font):
    return d.textlength("".join(c[0] for c in line), font=font)


def _shadow(im, radius=10, alpha=150, offset=(0, 6)):
    """Soft drop shadow under everything opaque in `im` (full-frame RGBA)."""
    a = im.getchannel("A").point(lambda v: v * alpha // 255)
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh.putalpha(a)
    sh = sh.filter(ImageFilter.GaussianBlur(radius))
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(sh, offset, sh)
    return Image.alpha_composite(out, im)


def caption_png(text, style, cache, bottom=CAPTION_BOTTOM):
    """Classic full-frame RGBA caption in the editor's style, placed inside the Shorts safe zone.
    headline: heavy face at the top, shrunk to fit one line when it can; speech / note: a block whose
    last line ends at `bottom` (fraction of H) -- raise it when the subject sits low in the frame."""
    def render():
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        max_w = W - SAFE["left"] - SAFE["right"] - 20
        cx = (SAFE["left"] + W - SAFE["right"]) / 2   # centred in the safe zone, clear of the buttons
        if style == "headline":
            size, fill = 84, "white"
            f = O._font(O.TITLE_FONTS, size)
            while size > 58 and max(d.textlength(p, font=f) for p in text.split("\n")) > max_w:
                size -= 2
                f = O._font(O.TITLE_FONTS, size)
        else:
            size = 76 if style == "speech" else 72
            f = O._font(O.SUB_FONTS, size)
            fill = O.NOTE_COLOR if style == "note" else "white"
        lines = [ln for part in text.split("\n") for ln in O._wrap(d, part, f, max_w)]  # "\n" = manual break
        lh = int(size * 1.28)
        y = int(H * HEADLINE_TOP) if style == "headline" else int(H * bottom) - lh * len(lines)
        y = max(SAFE["top"], y)
        for ln in lines:
            d.text((cx, y), ln, font=f, fill=fill, anchor="ma",
                   stroke_width=max(4, size // 6), stroke_fill=(0, 0, 0, 235))
            y += lh
        assert y <= H - SAFE["bottom"], f"caption runs into the bottom overlay: {text}"
        return im
    return O._cached(cache, f"short|{style}|{text}|{bottom}|{W}x{H}", render)


def punch_caption_png(text, style, cache, bottom=CAPTION_BOTTOM):
    """Punch style: heavy face, thick stroke + soft shadow, {keyword} in yellow. speech = bare text;
    note = the same on a dark rounded plate (so a label never reads as dialogue)."""
    def render():
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        max_w = W - SAFE["left"] - SAFE["right"] - 40
        cx = (SAFE["left"] + W - SAFE["right"]) / 2
        size = 84 if style == "speech" else 68

        def lay(sz):
            ft = O._font(O.TITLE_FONTS, sz)
            return ft, [ln for part in text.split("\n") for ln in _wrap_marked(d, _parse_marked(part), ft, max_w)]
        f, lines = lay(size)
        while size > 56 and len(lines) > 3:
            size -= 4
            f, lines = lay(size)
        stroke = max(6, size // 9)
        lh = int(size * 1.24)
        y = max(SAFE["top"], int(H * bottom) - lh * len(lines))
        if style == "note":
            pw = max(_line_w(d, ln, f) for ln in lines) + 60
            plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(plate).rounded_rectangle(
                [cx - pw / 2, y - 20, cx + pw / 2, y + lh * len(lines) + 2], radius=26, fill=(12, 14, 20, 155))
            im = Image.alpha_composite(im, plate)
            d = ImageDraw.Draw(im)
            stroke = max(3, size // 16)
        for ln in lines:
            _draw_marked_line(d, cx - _line_w(d, ln, f) / 2, y, ln, f, stroke)
            y += lh
        assert y <= H - SAFE["bottom"] + 10, f"caption runs into the bottom overlay: {text}"
        return _shadow(im, 8, 130, (0, 5))
    return O._cached(cache, f"punch|{style}|{text}|{bottom}|{W}x{H}", render)


def hook_png(hook, cache):
    """First-seconds hook: big heavy title (keywords yellow) with an optional sub line on a
    translucent pill, plus a soft top scrim as a separate layer (it must not scale with the
    title's pop). y = top of the title block (fraction of H). Returns (title png, scrim png)."""
    text, sub = hook["text"], hook.get("sub", "")
    top = float(hook.get("y", 0.16))

    def render(part):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        max_w = W - SAFE["left"] - SAFE["right"] - 10
        cx = (SAFE["left"] + W - SAFE["right"]) / 2
        parts = [_parse_marked(p) for p in text.split("\n")]
        size = int(hook.get("size", 118))
        f = O._font(O.TITLE_FONTS, size)
        while size > 84 and any(_line_w(d, p, f) > max_w for p in parts):   # each manual line on one line
            size -= 4
            f = O._font(O.TITLE_FONTS, size)
        lines = [ln for p in parts for ln in _wrap_marked(d, p, f, max_w)]
        lh = int(size * 1.2)
        y0 = max(SAFE["top"], int(H * top))
        block_h = lh * len(lines) + (100 if sub else 0)
        scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # gentle top-down darkening behind the title
        sd = ImageDraw.Draw(scrim)
        y_end = y0 + block_h + 160
        for yy in range(0, y_end, 4):
            a = int(115 * min(1.0, (y_end - yy) / (y_end * 0.55)))
            sd.rectangle([0, yy, W, yy + 4], fill=(0, 0, 0, a))
        if part == "scrim":
            return scrim
        y = y0
        for ln in lines:
            _draw_marked_line(d, cx - _line_w(d, ln, f) / 2, y, ln, f, max(8, size // 10))
            y += lh
        if sub:
            fs = O._font(O.TITLE_FONTS, 44)
            sw = d.textlength(sub, font=fs) + 64
            y += 22
            d.rounded_rectangle([cx - sw / 2, y, cx + sw / 2, y + 74], radius=37, fill=(0, 0, 0, 150))
            d.text((cx, y + 37), sub, font=fs, fill=(255, 255, 255, 255), anchor="mm")
        return _shadow(im, 10, 140, (0, 6))
    key = f"{json.dumps(hook, ensure_ascii=False, sort_keys=True)}|{W}x{H}"
    return (O._cached(cache, f"hook|{key}", lambda: render("title")),
            O._cached(cache, f"hook_scrim|{key}", lambda: render("scrim")))


def cta_layout(cta):
    """Geometry shared by the CTA pieces and the caption lift: (top y of the CTA block, pill box)."""
    y_text = H - SAFE["bottom"] - 250
    pill = (W / 2 - 170, y_text + 104, W / 2 + 170, y_text + 214)
    return y_text - 30, pill


def cta_pngs(cta, cache):
    """CTA end overlay: soft bottom scrim, one line of text, a red subscribe-style pill, and a
    separate arrow layer (animated) pointing down-left at the channel name / subscribe button."""
    text, button = cta.get("text", CTA_TEXT), cta.get("button", CTA_BUTTON)
    top, pill = cta_layout(cta)

    def render_main():
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sc = ImageDraw.Draw(im)
        y_s = int(top - 120)
        for yy in range(y_s, H, 4):   # bottom scrim so the white line reads on sand / sky
            a = int(150 * min(1.0, (yy - y_s) / 260))
            sc.rectangle([0, yy, W, yy + 4], fill=(0, 0, 0, a))
        d = ImageDraw.Draw(im)
        size = 64
        max_w = W - 2 * SAFE["left"]   # full width: the right-hand buttons sit higher than this line
        f = O._font(O.TITLE_FONTS, size)
        chars = _parse_marked(text)
        while _line_w(d, chars, f) > max_w and size > 40:
            size -= 2
            f = O._font(O.TITLE_FONTS, size)
        _draw_marked_line(d, W / 2 - _line_w(d, chars, f) / 2, top + 30, chars, f, 6)
        x0, y0, x1, y1 = pill
        d.rounded_rectangle([x0, y0, x1, y1], radius=(y1 - y0) / 2, fill=CTA_RED)
        fb = O._font(O.TITLE_FONTS, 58)
        d.text(((x0 + x1) / 2, (y0 + y1) / 2 + 2), f"＋ {button}", font=fb, fill=(255, 255, 255, 255), anchor="mm")
        return _shadow(im, 8, 120, (0, 5))

    def render_arrow():
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = pill
        sx, sy = x0 - 24, (y0 + y1) / 2 + 12          # from the pill's left side ...
        ex, ey = 200, H - SAFE["bottom"] + 60          # ... down-left toward the channel row
        col = (255, 255, 255, 255)
        ang = math.atan2(ey - sy, ex - sx)
        hl, hw = 46, 30
        bx, by = ex - hl * math.cos(ang), ey - hl * math.sin(ang)
        d.line([(sx, sy), (bx, by)], fill=col, width=14)
        px, py = -math.sin(ang), math.cos(ang)
        d.polygon([(ex, ey), (bx + hw * px, by + hw * py), (bx - hw * px, by - hw * py)], fill=col)
        return _shadow(im, 6, 160, (0, 4))

    key = json.dumps(cta, ensure_ascii=False, sort_keys=True)
    return (O._cached(cache, f"cta|{key}|{W}x{H}", render_main),
            O._cached(cache, f"cta_arrow|{key}|{W}x{H}", render_arrow))


# ---------------------------------------------------------------- overlay track

def _ease_out_back(x, s=1.7):
    x = min(1.0, max(0.0, x)) - 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


def layer_state(anim, lt, dur, fade_out=0.0):
    """(scale, alpha, dx, dy) of a layer `lt` seconds after it appears (it lasts `dur`; the last
    `fade_out` seconds fade to transparent)."""
    s, a, dx, dy = 1.0, 1.0, 0, 0
    k = lt * FPS
    if anim in ("pop", "hook", "hook_scrim"):
        if anim == "hook" and k < 6:   # opaque from frame 0 (the feed's first impression), scale pop
            s = 0.9 + 0.1 * _ease_out_back(k / 6, 2.4)
        elif anim == "pop" and k < 4:
            s = 0.86 + 0.14 * _ease_out_back(k / 4)
            a = min(1.0, (k + 1) / 4 * 1.4)
        if anim in ("hook", "hook_scrim"):
            left = (dur - lt) * FPS
            if left < 5:
                a = max(0.0, left / 5)
                dy = -int((5 - left) * 6)
    elif anim == "rise":
        if k < 8:
            dy = int(60 * (1 - _ease_out_back(k / 8, 1.2)))
            a = min(1.0, (k + 1) / 6)
    elif anim == "bob":
        a = min(1.0, max(0.0, (k - 3) / 6))
        ph = math.sin(2 * math.pi * lt / 0.8)
        dx, dy = int(-10 * ph), int(10 * ph)
    if fade_out > 0 and dur - lt < fade_out:
        a *= max(0.0, (dur - lt) / fade_out)
    return round(s, 3), round(a, 2), dx, dy


def _transform(img, bbox, pivot, state):
    s, a, dx, dy = state
    if (s, a, dx, dy) == (1.0, 1.0, 0, 0):
        return img
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if bbox is None or a <= 0:
        return out
    tile = img.crop(bbox)
    if s != 1.0:
        tile = tile.resize((max(1, int(tile.width * s)), max(1, int(tile.height * s))), Image.BILINEAR)
    if a < 1.0:
        tile.putalpha(tile.getchannel("A").point(lambda v: int(v * a)))
    px, py = pivot
    x = int(px + (bbox[0] - px) * s) + dx
    y = int(py + (bbox[1] - py) * s) + dy
    sx, sy = max(0, -x), max(0, -y)
    tile = tile.crop((sx, sy, min(tile.width, W - x), min(tile.height, H - y)))
    out.alpha_composite(tile, (max(0, x), max(0, y)))
    return out


def build_overlay_track(layers, total, folder):
    """Render every overlay layer into one RGBA PNG sequence (frame i = time i/FPS). A frame whose set
    of (layer, state) repeats one already written is a hard link, so long holds cost nothing."""
    os.makedirs(folder, exist_ok=True)
    n = int(round(total * FPS))
    imgs = []
    for L in layers:
        im = Image.open(L["png"]).convert("RGBA")
        bb = im.getbbox()
        pivot = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2) if bb else (W / 2, H / 2)
        imgs.append((im, bb, pivot))
    blank = os.path.join(folder, "blank.png")
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(blank, compress_level=1)
    written = {(): blank}
    for f in range(n):
        t = f / FPS   # same test as overlay's enable='between(t,t0,t1)' on the frame's timestamp
        key = tuple((i, layer_state(L.get("anim"), t - L["t0"], L["t1"] - L["t0"], L.get("fade_out", 0)))
                    for i, L in enumerate(layers) if L["t0"] - 1e-6 <= t <= L["t1"] + 1e-6)
        path = os.path.join(folder, f"{f:05d}.png")
        if key in written:
            os.link(written[key], path)
            continue
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for i, st in key:
            im, bb, pivot = imgs[i]
            frame.alpha_composite(_transform(im, bb, pivot, st))
        frame.save(path, compress_level=1)
        written[key] = path
    return os.path.join(folder, "%05d.png"), n


# ---------------------------------------------------------------- segments

def default_output(project, stem):
    """<project>/02 - Export/shorts/<stem>.mp4 -- the kept archive copy (never delete after upload)."""
    return os.path.join(E.project_dir(project), "02 - Export", "shorts", stem + ".mp4")


def resolve_clip(spec, clip):
    if os.path.isabs(clip) or os.path.exists(clip):
        return clip
    proj = E.project_dir(spec["project"])
    for ext in (".MP4", ".mp4", ".MOV", ".mov"):
        p = os.path.join(proj, spec.get("source_dir", "01 - Unedited"), clip + ext)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(clip)


def expand_segments(segments):
    """Jump cuts: a segment with "cuts" becomes several pieces (same crop/grade keyframes, which are
    in source time); every other piece is punched in by "jump_zoom" so the jump reads as a cut."""
    out = []
    for seg in segments:
        cuts = sorted(seg.get("cuts", []))
        if not cuts:
            out.append(seg)
            continue
        edges, t = [], float(seg["in"])
        for a, b in cuts:
            if a > t:
                edges.append((t, float(a)))
            t = max(t, float(b))
        if t < seg["out"]:
            edges.append((t, float(seg["out"])))
        af = seg.get("audio_from")
        for k, (a, b) in enumerate(edges):
            p = copy.deepcopy(seg)
            p.pop("cuts", None)
            p["in"], p["out"] = a, b
            if k % 2 and seg.get("jump_zoom"):
                p["zoom"] = float(seg.get("zoom", 1.0)) * float(seg["jump_zoom"])
            if af:  # the borrowed audio keeps running in step with the picture
                p["audio_from"] = dict(af, **{"in": float(af["in"]) + (a - float(seg["in"]))})
            out.append(p)
    return out


def render_segment(spec, seg, idx, work):
    path = resolve_clip(spec, seg["clip"])
    sw, sh, _ = probe(path)
    tm = TimeMap(seg)
    dur = seg["out"] - seg["in"]
    grade = spec.get("grades", {}).get(seg.get("grade", ""), "")
    vf = ["setpts=PTS-STARTPTS"]
    if seg.get("mode", "crop") == "crop":
        zoom = float(seg.get("zoom", 1.0))
        ch = int(round(sh / zoom / 2)) * 2
        cw = int(round(ch * W / H / 2)) * 2
        track = smooth_track(seg.get("x", 0.5), seg["in"], seg["out"], 1.0)
        xs = [(t, x * sw - cw / 2) for t, x in track]
        ys = [(t, y * sh - ch / 2) for t, y in smooth_track(seg.get("y", 0.5), seg["in"], seg["out"], 1.0)]
        vf.append(f"crop=w={cw}:h={ch}:x='{piecewise_expr(xs, 0, sw - cw)}':y='{piecewise_expr(ys, 0, sh - ch)}'")
        if grade:
            vf.append(grade)
        vf.append(f"scale={W}:{H}:flags=lanczos")
        chain = f"[0:v]{','.join(vf)}"
    else:  # letterbox over a blurred, darkened fill of the same frame
        g = f",{grade}" if grade else ""
        chain = (f"[0:v]setpts=PTS-STARTPTS{g},split[a][b];"
                 f"[a]scale=-2:{H // 4},crop={W // 4}:{H // 4},boxblur=12:2,eq=brightness=-0.12,"
                 f"scale={W}:{H}[bg];[b]scale={W}:-2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    if tm.ramped:
        chain += "," + tm.setpts()
    chain += f",fps={FPS},setsar=1,format=yuv420p[v]"
    out_dur = tm.out_dur
    nfr = round(out_dur * FPS)
    af = seg.get("audio_from")
    level = 0.0 if tm.ramped else AUDIO_GAIN.get(seg.get("audio", "voice"), 1.0)
    gain_db = float(seg.get("gain_db", 0))
    a_path, extra_in = path, []
    if af:   # voice over B-roll: the sound comes from another clip, at normal speed
        a_path = resolve_clip(spec, af["clip"])
        level = AUDIO_GAIN.get(af.get("audio", "voice"), 1.0)
        gain_db = float(af.get("gain_db", 0))
        extra_in = ["-ss", f"{float(af['in']):.3f}", "-t", f"{out_dur + 0.1:.3f}", "-i", a_path]
    ain = "1:a" if extra_in else "0:a"
    if has_audio(a_path) and level > 0:
        achain = (f"[{ain}]asetpts=PTS-STARTPTS,aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                  f"volume={level}*{10 ** (gain_db / 20):.4f},"
                  f"afade=t=in:d=0.012,afade=t=out:st={max(0, out_dur - 0.012):.3f}:d=0.012,"
                  f"apad,atrim=0:{out_dur:.3f}[a]")
    else:
        achain = f"anullsrc=r={SR}:cl=stereo,atrim=0:{out_dur:.3f}[a]"
    script = os.path.join(work, f"seg{idx}.txt")
    with open(script, "w") as f:
        f.write(chain + ";" + achain)
    vout, aout = os.path.join(work, f"seg{idx}.mp4"), os.path.join(work, f"seg{idx}.wav")
    # -reinit_filter 0: keep the graph if frame properties change mid-stream (hw -> sw decode fallback)
    tail = ["-reinit_filter", "0", "-ss", f"{seg['in']:.3f}", "-t", f"{dur:.3f}", "-i", path, *extra_in,
            "-filter_complex_script", script,
            "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
            "-frames:v", str(nfr), vout, "-map", "[a]", "-c:a", "pcm_s16le", aout]
    try:  # hardware HEVC decode is much faster; retry in software if it fails
        run(["ffmpeg", "-v", "error", "-y", *(["-hwaccel", "videotoolbox"] if sys.platform == "darwin" else []), *tail])
    except RuntimeError:
        run(["ffmpeg", "-v", "error", "-y", *tail])
    return vout, aout, nfr / FPS, tm


# ---------------------------------------------------------------- build

def build(spec, out, check=False, check_dir=None):
    work = tempfile.mkdtemp(prefix="short_", dir=spec.get("workdir") or None)
    cache = os.path.join(work, "overlays")
    punch = spec.get("style", "classic") == "punch"
    try:
        segs, t, speech, caps = [], 0.0, [], []
        for i, seg in enumerate(expand_segments(spec["segments"])):
            v, a, d, tm = render_segment(spec, seg, i, work)
            af = seg.get("audio_from") or {}
            subs = [(s, seg["in"], seg["out"], tm) for s in seg.get("subs", [])]
            for s in af.get("subs", []):   # borrowed-clip seconds -> output seconds (audio runs at 1x)
                off = float(af["in"]) - seg["in"]
                subs.append((dict(s, t0=s["t0"] - off, t1=s["t1"] - off), seg["in"], seg["in"] + d, None))
            for s, lo, hi, m in subs:
                a0, a1 = max(s["t0"], lo), min(s["t1"], hi)
                if a1 - a0 < 0.3:
                    continue
                o0, o1 = (t + m(a0), t + m(a1)) if m else (t + a0 - lo, t + a1 - lo)
                kind = s.get("kind", "speech")
                caps.append({"t0": o0, "t1": o1, "text": s["text"], "style": kind, "y": s.get("y")})
                if kind == "speech":
                    speech.append((o0, o1))
            segs.append((v, a, d))
            t += d
        total = t
        for c in spec.get("captions", []):
            caps.append({"t0": c.get("t0", 0), "t1": c.get("t1") if c.get("t1") is not None else total,
                         "text": c["text"], "style": c.get("style", "headline"), "y": c.get("y")})

        # overlay track: captions, hook, CTA
        cta = spec.get("cta")
        cta = {} if cta is True else (cta or None)
        cta_t0 = cta_top = None
        if cta is not None:
            cta_t0 = max(0.0, total - float(cta.get("dur", 2.2)))
            cta_top = cta_layout(cta)[0] / H
        layers = []
        for c in caps:
            bottom = float(c.get("y") or spec.get("caption_bottom", CAPTION_BOTTOM))
            if cta_t0 is not None and c["style"] != "headline" and c["t1"] > cta_t0 + 0.05:
                bottom = min(bottom, cta_top - 0.01)   # keep the payoff line readable above the CTA
            if punch and c["style"] != "headline":
                png = punch_caption_png(c["text"], c["style"], cache, bottom)
            else:
                png = caption_png(c["text"].replace("{", "").replace("}", ""), c["style"], cache, bottom)
            layers.append({"t0": c["t0"], "t1": c["t1"], "png": png, "anim": "pop" if punch else None})
        hook = spec.get("hook")
        if hook:
            title, scrim = hook_png(hook, cache)
            h0, h1 = float(hook.get("t0", 0)), float(hook.get("t1", 1.8))
            layers.insert(0, {"t0": h0, "t1": h1, "png": scrim, "anim": "hook_scrim"})
            layers.append({"t0": h0, "t1": h1, "png": title, "anim": "hook"})
        if cta is not None:
            main, arrow = cta_pngs(cta, cache)
            # with a loop dissolve the CTA fades out with it, so the last frame is the clean first one
            xf_ = float(spec.get("loop_xfade", 0) or 0)
            end, fo = (total, xf_) if xf_ > 0 else (total + 1, 0)
            layers.append({"t0": cta_t0, "t1": end, "png": main, "anim": "rise", "fade_out": fo})
            layers.append({"t0": cta_t0 + 0.15, "t1": end, "png": arrow, "anim": "bob", "fade_out": fo})
        pattern, _ = build_overlay_track(layers, total, os.path.join(work, "track"))

        # video: concat (+ loop dissolve) + the overlay track
        inputs, chain = [], []
        for v, _, _ in segs:
            inputs += ["-i", v]
        n = len(segs)
        chain.append("".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[c0]")
        cur = "c0"
        xf = float(spec.get("loop_xfade", 0) or 0)
        if xf > 0:   # the last xf seconds dissolve into a still of frame 0 -> the loop restart is invisible
            nx, ntot = int(round(xf * FPS)), int(round(total * FPS))
            ramp = f"min(1,N/{max(1, nx - 1)})"
            chain += ["[c0]split=3[lm][lt][lh]",
                      f"[lm]trim=end_frame={ntot - nx},setpts=PTS-STARTPTS[lmm]",
                      f"[lt]trim=start_frame={ntot - nx}:end_frame={ntot},setpts=PTS-STARTPTS[ltt]",
                      f"[lh]trim=end_frame=1,loop=loop={nx - 1}:size=1:start=0,setpts=N/{FPS}/TB[lhh]",
                      f"[ltt][lhh]blend=all_expr='A*(1-{ramp})+B*{ramp}':shortest=1[lx]",
                      "[lmm][lx]concat=n=2:v=1:a=0[c1]"]
            cur = "c1"
        inputs += ["-framerate", str(FPS), "-i", pattern]
        chain.append(f"[{n}:v]format=rgba,setpts=PTS-STARTPTS[ov]")
        chain.append(f"[{cur}][ov]overlay=0:0:eof_action=pass,format=yuv420p[v]")
        vscript = os.path.join(work, "video.txt")
        with open(vscript, "w") as f:
            f.write(";".join(chain))
        video = os.path.join(work, "video.mp4")
        run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", vscript, "-map", "[v]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
             "-g", str(FPS), "-movflags", "+faststart", video])

        # audio: concat source audio, music bed ducked under speech, loudnorm + limiter
        with open(os.path.join(work, "alist.txt"), "w") as f:
            f.writelines(f"file '{a}'\n" for _, a, _ in segs)
        voice = os.path.join(work, "voice.wav")
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", os.path.join(work, "alist.txt"),
             "-af", f"atrim=0:{total:.3f},apad,atrim=0:{total:.3f}", "-c:a", "pcm_s16le", voice])
        mix = os.path.join(work, "mix.wav")
        m = spec.get("music")
        fade = float(spec.get("edge_fade", 0.15))
        if m and m.get("file"):
            mf = m["file"] if os.path.isabs(m["file"]) else os.path.join(E.edit_dir(spec["project"]), m["file"])
            base, duck, r = float(m.get("volume", 0.30)), float(m.get("duck", 0.08)), 0.35
            terms = [f"clip(min((t-{a:.2f}+{r})/{r},({b:.2f}+{r}-t)/{r}),0,1)" for a, b in speech]
            sp = "min(1," + "+".join(terms) + ")" if terms else "0"
            pre = ""
            if m.get("match"):   # Audio Library tracks differ by 15+ LU; level them before `volume`
                from src.editor.render import _track_gain_db
                pre = f"volume={_track_gain_db(mf, {'gain': m.get('gain_db', 0)}):.2f}dB,"
            m_start, m_fade = float(m.get("start", 0) or 0), float(m.get("fade_in", 0) or 0)
            ms_ = int(m_start * 1000)
            enter = f",adelay={ms_}|{ms_}" if ms_ > 0 else ""
            fin = f",afade=t=in:st={m_start:.3f}:d={m_fade:.3f}" if m_fade > 0 else ""
            ms = (f"[1:a]aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,{pre}"
                  f"atrim=0:{max(0.1, total - m_start):.3f},asetpts=N/SR/TB{enter}{fin},apad,atrim=0:{total:.3f},"
                  f"volume='{base}-({base - duck})*{sp}':eval=frame[m];"
                  f"[0:a][m]amix=inputs=2:normalize=0:duration=first,"
                  f"afade=t=in:d={fade},afade=t=out:st={max(0, total - fade):.3f}:d={fade}")
            ascript = os.path.join(work, "audio.txt")
            with open(ascript, "w") as f:
                f.write(ms)
            run(["ffmpeg", "-v", "error", "-y", "-i", voice, "-stream_loop", "-1", "-ss", f"{float(m.get('in', 0)):.3f}",
                 "-i", mf, "-filter_complex_script", ascript, "-t", f"{total:.3f}", "-c:a", "pcm_s24le", mix])
        else:
            run(["ffmpeg", "-v", "error", "-y", "-i", voice, "-af",
                 f"afade=t=in:d={fade},afade=t=out:st={max(0, total - fade):.3f}:d={fade}", "-c:a", "pcm_s24le", mix])
        from src.editor.render import _loudnorm
        L = spec.get("loudness", {})
        target = f"I={L.get('I', -14)}:TP={L.get('TP', -1.5)}:LRA=11"
        tmp = out + ".part.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-i", video, "-i", mix, "-filter_complex",
             f"[1:a]{_loudnorm(mix, target)},aresample=192000,"
             f"alimiter=limit=0.79:attack=5:release=50:level=false,aresample={SR},aformat=sample_fmts=s16[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", str(SR),
             "-t", f"{total:.3f}", "-movflags", "+faststart", tmp])
        os.replace(tmp, out)
        report = measure(out)
        report["shots"] = [round(d, 2) for _, _, d in segs]
        report["longest_shot"] = max(report["shots"])
        if report["longest_shot"] > 3.5:
            report["pace_warning"] = "a shot runs > 3.5 s: cut, punch in or ramp it (target 1-2.5 s)"
        report["captions"] = caps
        print(json.dumps(report, ensure_ascii=False, indent=1))
        if check:
            check_frames(out, report["duration"], d=check_dir)
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def measure(path):
    w, h, dur = probe(path)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True)
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    I = TP = None
    for ln in tail.splitlines():
        ln = ln.strip()
        if ln.startswith("I:"):
            I = float(ln.split()[1])
        elif ln.startswith("Peak:"):
            TP = float(ln.split()[1])
    return {"output": path, "width": w, "height": h, "duration": round(dur, 2), "lufs": I, "true_peak": TP}


def check_frames(path, dur, n=8, d=None):
    """Full-size frames + a phone-size sheet (~360 px wide each, unsafe zones shaded) + a 1 fps sheet."""
    d = d or os.path.splitext(path)[0] + "_check"
    os.makedirs(d, exist_ok=True)
    thumbs = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        fp = os.path.join(d, f"frame_{i:02d}.jpg")
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-q:v", "2", fp])
        im = Image.open(fp).convert("RGBA")
        shade = Image.new("RGBA", im.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        for box in ([0, 0, W, SAFE["top"]], [0, H - SAFE["bottom"], W, H],
                    [W - SAFE["right"], SAFE["top"], W, H - SAFE["bottom"]]):
            sd.rectangle(box, fill=(255, 0, 0, 60))
        thumbs.append(Image.alpha_composite(im, shade).convert("RGB").resize((360, 640), Image.LANCZOS))
    sheet = Image.new("RGB", (360 * 4 + 30, 640 * ((n + 3) // 4) + 10 * ((n + 3) // 4)), "white")
    for i, th in enumerate(thumbs):
        sheet.paste(th, ((i % 4) * 370, (i // 4) * 650))
    sheet.save(os.path.join(d, "phone_sheet.jpg"), quality=88)
    rows = max(1, math.ceil(dur / 8))
    run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", f"fps=1,scale=216:384,tile=8x{rows}",
         "-frames:v", "1", os.path.join(d, "sheet_1fps.jpg")])
    print(f"check frames: {d}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true", help="write full-size + phone-size check frames")
    a = ap.parse_args()
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    stem = os.path.splitext(os.path.basename(a.spec))[0]
    out = a.out or spec.get("output")
    if not out:
        if not spec.get("project"):
            sys.exit("no output path (spec 'project', spec 'output' or --out)")
        out = default_output(spec["project"], stem)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    check_dir = os.path.join(os.path.dirname(os.path.abspath(a.spec)), stem + "_check")
    build(spec, os.path.abspath(out), check=a.check, check_dir=check_dir)


if __name__ == "__main__":
    main()
