"""Glass note layout: even crop boxes inside the frame, subtitle_top agrees with the box, PNGs render
(landscape 1080p/4K and portrait). Run: ./venv/bin/python scripts/test_glass_note.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import overlays as O  # noqa: E402

LONG = "1990年代改霓虹后，南京路被称为“中华灯光第一街”，再加一句很长的话来测试换行"
td = tempfile.mkdtemp()
for w, h in [(1920, 1080), (3840, 2160), (1080, 1920)]:
    for pos in ("top", "bottom"):
        for t in ("东方明珠468米，1994年建成", LONG):
            x, y, bw, bh, r = O.glass_box(t, w, h, pos)
            assert all(v % 2 == 0 for v in (x, y, bw, bh)), (w, h, x, y, bw, bh)
            assert 0 <= x and x + bw <= w and 0 <= y and y + bh <= h, (w, h, pos, x, y, bw, bh)
            assert os.path.exists(O.subtitle(t, w, h, td, "note", pos, "glass"))
            assert os.path.exists(O.glass_mask(t, w, h, td, pos))
            if pos == "bottom":
                assert O.subtitle_top(t, w, h, "note", "glass") == y
assert O.DEFAULT_NOTE_STYLE in O.NOTE_STYLES
print("ok: glass notes")
