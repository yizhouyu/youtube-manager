"""Vertical clips are framed, not stretched: by default the sharp portrait sits centred over a blurred copy
(`fit` blur), `"fit": "crop"` fills the width, `"fit": "stretch"` is the old behaviour; B-roll follows the same
rule. Builds a synthetic 90x160 clip (top third red, rest blue, a green centre column) and checks pixels.
Run: ./venv/bin/python scripts/test_portrait_fit.py"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image  # noqa: E402
from src.editor import render  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "01 - Unedited")
    os.makedirs(src)
    # 90x160 portrait: red top band (0-53), blue below, green 10-px column in the middle
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=90x160:d=2:r=30",
                    "-vf", "drawbox=x=0:y=0:w=90:h=53:color=red:t=fill,drawbox=x=40:y=60:w=10:h=100:color=green:t=fill",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", os.path.join(src, "TALL.MP4")], check=True)
    preset = {"w": 320, "h": 180, "vb": "2M"}

    def frame(edl, shot):
        cache = tempfile.mkdtemp(dir=td)
        v = render.render_segment_video(edl, shot, "30", preset, cache, clean=True)
        png = os.path.join(cache, "f.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", v, "-frames:v", "1", png], check=True)
        im = Image.open(png).convert("RGB")
        assert im.size == (320, 180), im.size
        return im

    base = {"project": td, "source_dir": "01 - Unedited", "grades": {}}
    green = lambda p: p[1] > 100 and p[0] < 100 and p[2] < 100  # noqa: E731

    # blur (default): the centre column stays sharp and green; the far sides are a dimmed blur, never green
    im = frame(base, {"id": "s1", "clip": "TALL", "in": 0.0, "out": 1.0})
    assert green(im.getpixel((160, 150))), im.getpixel((160, 150))
    side, sharp = im.getpixel((10, 150)), im.getpixel((130, 150))
    assert not green(side) and side[2] < sharp[2] - 30, (side, sharp)   # dimmed blur beside the sharp portrait

    # crop: fills the width; with y=0 the red top band is at the top across the whole frame
    im = frame(base, {"id": "s2", "clip": "TALL", "in": 0.0, "out": 1.0, "fit": {"mode": "crop", "y": 0.0}})
    assert im.getpixel((10, 10))[0] > 150 and im.getpixel((310, 10))[0] > 150, (im.getpixel((10, 10)), im.getpixel((310, 10)))

    # stretch: the old behaviour, the green column becomes ~36 px wide in the middle
    im = frame(base, {"id": "s3", "clip": "TALL", "in": 0.0, "out": 1.0, "fit": "stretch"})
    assert green(im.getpixel((150, 150))) and green(im.getpixel((170, 150)))

    # black: pillarbox, sides pure black; x=0.25 moves the portrait left (its column lands near x=80)
    im = frame(base, {"id": "s5", "clip": "TALL", "in": 0.0, "out": 1.0, "fit": "black"})
    assert max(im.getpixel((10, 150))) < 20 and green(im.getpixel((160, 150)))
    im = frame(base, {"id": "s6", "clip": "TALL", "in": 0.0, "out": 1.0, "fit": {"mode": "blur", "x": 0.25}})
    assert green(im.getpixel((80, 150))) and not green(im.getpixel((160, 150))), (im.getpixel((80, 150)), im.getpixel((160, 150)))

    # B-roll of a vertical clip over a vertical shot is framed the same way
    im = frame(base, {"id": "s4", "clip": "TALL", "in": 0.0, "out": 1.0,
                      "broll": [{"clip": "TALL", "in": 0.0, "at": 0.0, "dur": 1.0}]})
    assert green(im.getpixel((160, 150))) and not green(im.getpixel((10, 150)))
print("ok: portrait fit")
