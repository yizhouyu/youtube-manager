"""Tags: top-right position, and a `tag` drawn on a card shot. Run: ./venv/bin/python scripts/test_card_tag.py"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image  # noqa: E402
from src.editor import overlays, render  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    tl = Image.open(overlays.place_tag("红杉 & 国王峡谷 · 第 1/3 天", 640, 360, td)).getchannel("A")
    tr = Image.open(overlays.place_tag("红杉 & 国王峡谷 · 第 1/3 天", 640, 360, td, "tr")).getchannel("A")
    assert tl.getpixel((30, 25)) > 0 and tl.getpixel((610, 25)) == 0, "default pill is top-left"
    assert tr.getpixel((610, 25)) > 0 and tr.getpixel((30, 25)) == 0, "tr pill is top-right"

    preset = {"w": 640, "h": 360, "vb": "2M"}
    base = {"id": "c1", "clip": "", "in": 0, "out": 2.0, "card": {"text": "测试", "bg": "#ffffff"}}
    frames = {}
    for name, extra in (("plain", {}), ("tagged", {"tag": "第 1/3 天", "tag_pos": "tr"})):
        v = os.path.join(td, f"{name}.mp4")
        render._render_card({"project": td}, {**base, **extra}, "30", preset, 60, 2.0, td, v)
        png = os.path.join(td, f"{name}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.0", "-i", v, "-frames:v", "1", png], check=True)
        frames[name] = Image.open(png).convert("L")
    # the pill is dark on a white card: the top-right corner must be darker with the tag than without
    box = (int(640 * 0.80), int(360 * 0.06), int(640 * 0.95), int(360 * 0.10))
    mean = lambda im: sum(im.crop(box).getdata()) / ((box[2] - box[0]) * (box[3] - box[1]))  # noqa: E731
    assert mean(frames["tagged"]) < mean(frames["plain"]) - 20, (mean(frames["tagged"]), mean(frames["plain"]))
print("ok")
