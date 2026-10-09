"""A lower-left title must not overlap a two-line bottom caption shown at the same time (ep 100 review).
Renders both overlays at 1080p and checks no pixel row holds ink from both in the title's x-range."""
import os
import sys
import tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from PIL import Image  # noqa: E402
from src.editor import overlays as O  # noqa: E402

W, H = 1920, 1080
cap = "我们现在又走回来，走到这里的一块大草地，叫 New Haven Green"
with tempfile.TemporaryDirectory() as td:
    sub = Image.open(O.subtitle(cap, W, H, td)).getchannel("A")
    top = O.subtitle_top(cap, W, H)
    lim = top - int(H * 0.015)
    for limit, should_clear in ((None, False), (lim, True)):
        t = Image.open(O.title_card("纽黑文绿地", "New Haven Green · 1638 年规划的城市中心广场", W, H, td, limit)).getchannel("A")
        both = [y for y in range(H) if any(t.getpixel((x, y)) > 40 and sub.getpixel((x, y)) > 40 for x in range(0, W, 3))]
        assert bool(both) != should_clear, (limit, both[:3])
    assert top < H - 0.07 * H
print("ok")
