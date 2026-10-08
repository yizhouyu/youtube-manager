"""Pip layering: a full-frame pip covers the captions by default; with "under_subs": true the captions
are drawn on top of it. Run: ./venv/bin/python scripts/test_pip_under_subs.py"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image  # noqa: E402
from src.editor import render  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "01 - Unedited"))
    os.makedirs(os.path.join(td, "02 - Export", "edit"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=3",
                    "-pix_fmt", "yuv420p", os.path.join(td, "01 - Unedited", "X.MP4")], check=True)
    Image.new("RGB", (640, 360), (200, 0, 0)).save(os.path.join(td, "02 - Export", "edit", "red.png"))
    edl = {"project": td, "source_dir": "01 - Unedited", "grades": {}}
    preset = {"w": 640, "h": 360, "vb": "2M"}
    lum = {}
    for name, under in (("over", False), ("under", True)):
        shot = {"id": f"s_{name}", "clip": "X", "in": 0.1, "out": 2.5, "audio": "mute",
                "subs": [{"t0": 0.1, "t1": 2.5, "text": "字幕测试字幕测试"}],
                "pip": [{"file": "red.png", "t0": 0, "t1": 2.4, "x": 0, "y": 0, "w": 1.0, "border": 0,
                         "fade": 0, "under_subs": under}]}
        cache = os.path.join(td, "cache_" + name)
        os.makedirs(cache)
        v = render.render_segment_video(edl, shot, "30", preset, cache)
        png = os.path.join(td, name + ".png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.2", "-i", v, "-frames:v", "1", png], check=True)
        im = Image.open(png).convert("RGB")
        # bright (white caption) pixels in the bottom band
        band = im.crop((0, int(360 * 0.75), 640, 360)).getdata()
        lum[name] = sum(1 for r, g, b in band if r > 200 and g > 200 and b > 200)
        assert im.getpixel((320, 100))[0] > 150 and im.getpixel((320, 100))[1] < 80, "pip must cover the frame"
    assert lum["over"] < 20, lum
    assert lum["under"] > 100, lum
print("ok", lum)
