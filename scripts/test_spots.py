"""Spotlight overlay: the circle is clear, the rest dimmed, label drawn. Run: ./venv/bin/python scripts/test_spots.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image  # noqa: E402
from src.editor import overlays  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    p = overlays.spotlight("白狮子", 0.6, 0.5, 0.15, 640, 360, td, dim=0.55)
    a = Image.open(p).getchannel("A")
    assert a.getpixel((384, 180)) < 10, "centre of the circle must stay clear"
    assert abs(a.getpixel((20, 340)) - int(255 * 0.55)) < 6, "outside must be dimmed"
    assert overlays.spotlight("白狮子", 0.6, 0.5, 0.15, 640, 360, td, dim=0.55) == p, "cached"
print("ok")
