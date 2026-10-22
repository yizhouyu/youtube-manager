"""EDL "canvas": "9:16" (a vertical film, ep 118): portrait clips fill the upright frame (their 16:9 `fit` is
ignored, a 3:4 clip is centre-cropped, never stretched), a landscape clip gets the fit sideways (blur by default,
`vfit` crop keeps the band at x), presets are 1080x1920 / 2160x3840, and the portrait overlays stay inside the
YouTube mobile safe zone. 16:9 EDLs are untouched (covered by test_portrait_fit and friends).
Run: ./venv/bin/python scripts/test_vertical_canvas.py"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from src.editor import edl as E  # noqa: E402
from src.editor import overlays as O  # noqa: E402
from src.editor import render  # noqa: E402

assert render.preset_for({}, "preview")["w"] == 1920 and render.preset_for({}, "final")["h"] == 2160
assert render.preset_for({"canvas": "9:16"}, "preview") == {"w": 1080, "h": 1920, "vb": "12M"}
assert (render.preset_for({"canvas": "9:16"}, "final")["w"], render.preset_for({"canvas": "9:16"}, "package")["h"]) == (2160, 3840)

with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "01 - Unedited")
    os.makedirs(src)
    # 90x160 portrait: red top band, blue below, green centre column
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=90x160:d=2:r=30",
                    "-vf", "drawbox=x=0:y=0:w=90:h=53:color=red:t=fill,drawbox=x=40:y=60:w=10:h=100:color=green:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", os.path.join(src, "TALL.MP4")], check=True)
    # 120x160 (3:4) portrait: green 10-px column at the centre, red 10-px strips on the far left/right edges
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=120x160:d=2:r=30",
                    "-vf", "drawbox=x=55:y=0:w=10:h=160:color=green:t=fill,drawbox=x=0:y=0:w=10:h=160:color=red:t=fill,"
                    "drawbox=x=110:y=0:w=10:h=160:color=red:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", os.path.join(src, "FOUR3.MP4")], check=True)
    # 160x90 landscape: green centre column, red left quarter
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=160x90:d=2:r=30",
                    "-vf", "drawbox=x=75:y=0:w=10:h=90:color=green:t=fill,drawbox=x=0:y=0:w=40:h=90:color=red:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", os.path.join(src, "WIDE.MP4")], check=True)
    preset = {"w": 180, "h": 320, "vb": "2M"}

    def frame(edl, shot):
        cache = tempfile.mkdtemp(dir=td)
        v = render.render_segment_video(edl, shot, "30", preset, cache, clean=True)
        png = os.path.join(cache, "f.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", v, "-frames:v", "1", png], check=True)
        im = Image.open(png).convert("RGB")
        assert im.size == (180, 320), im.size
        return im

    base = {"project": td, "source_dir": "01 - Unedited", "grades": {}, "canvas": "9:16"}
    green = lambda p: p[1] > 100 and p[0] < 100 and p[2] < 100  # noqa: E731
    red = lambda p: p[0] > 150 and p[1] < 100  # noqa: E731

    # portrait on 9:16: fills the frame; the 16:9 crop band is ignored (red band still at the top, blue at the bottom)
    im = frame(base, {"id": "s1", "clip": "TALL", "in": 0.0, "out": 1.0, "fit": {"mode": "crop", "y": 0.9}})
    assert red(im.getpixel((20, 20))) and im.getpixel((20, 300))[2] > 150 and green(im.getpixel((90, 250)))
    assert E.fit_of(base, {"clip": "TALL", "fit": "crop"}) is None
    # 3:4 portrait: centre-cropped to 9:16 (the red edge strips are cut away), not squeezed
    im = frame(base, {"id": "s2", "clip": "FOUR3", "in": 0.0, "out": 1.0})
    assert not red(im.getpixel((2, 160))) and not red(im.getpixel((177, 160))) and green(im.getpixel((90, 160)))
    # landscape on 9:16: blur fit sideways: the sharp band sits in the middle, a dimmed blur above and below
    im = frame(base, {"id": "s3", "clip": "WIDE", "in": 0.0, "out": 1.0})
    assert green(im.getpixel((90, 160))) and not green(im.getpixel((90, 10))), (im.getpixel((90, 160)), im.getpixel((90, 10)))
    # vfit crop x=0: fills the frame with the left band (red quarter at the left edge, full height)
    im = frame(base, {"id": "s4", "clip": "WIDE", "in": 0.0, "out": 1.0, "vfit": {"mode": "crop", "x": 0.0}})
    assert red(im.getpixel((10, 10))) and red(im.getpixel((10, 310))), (im.getpixel((10, 10)), im.getpixel((10, 310)))

# portrait overlays: ink inside the safe zone (bottom 15 %, right 12 % stay clear)
W, H = 1080, 1920
with tempfile.TemporaryDirectory() as td:
    long_note = "纳帕利海岸不通公路：只能坐船来，或走11英里的 Kalalau 步道"
    pngs = [O.subtitle(long_note, W, H, td, "note", "bottom", "paper"),
            O.subtitle("我们到啦，这里风好大", W, H, td, "speech"),
            O.place_tag("崖下浮潜 · 上午 10:30", W, H, td),
            O.title_card("纳帕利海岸", "可爱岛 · 从海上看群崖", W, H, td, None, "NĀ PALI COAST · KAUAʻI")]
    for p in pngs:
        a = np.array(Image.open(p).getchannel("A"))
        ys, xs = np.where(a > 60)
        assert ys.max() < H * 0.85 and xs.max() < W * 0.88 and xs.min() > W * 0.04 and ys.min() > H * 0.05, \
            (p, xs.min(), ys.min(), xs.max(), ys.max())
    # the title lifts above a caption shown with it
    top = O.subtitle_top(long_note, W, H, "note", "paper")
    a = np.array(Image.open(O.title_card("纳帕利海岸", "可爱岛", W, H, td, top - 20)).getchannel("A"))
    assert np.where(a > 60)[0].max() < top, "title runs into the caption"
    # balanced wrap: never splits a number from its unit, a short 《title》, or a Latin word
    d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    f = O._font(O.SUB_FONTS, 54, "中")
    for text in ("纳帕利的悬崖最高约4000英尺，约合1200米", "Honopū 海滩：1976年《金刚》和《加勒比海盗4》都在这里取景",
                 long_note, "灰色的是舵鱼（夏威夷名 nenue），常成群在浪涌里吃藻类"):
        lines = O._wrap_balanced(d, text, f, 790)
        assert all(d.textlength(ln, font=f) <= 790 for ln in lines), lines
        joined = "|".join(lines)
        for bad in ("英|尺", "4000|英", "《金刚|", "海盗|4", "Kala|lau", "nen|ue"):
            assert bad not in joined, (bad, lines)
    assert O._wrap_balanced(d, "第一行\n第二行", f, 790) == ["第一行", "第二行"]
print("ok: vertical canvas")
