"""Split-flap board: tiles flap then land on their text, blanks never flap, the panel stays clear of the
lower-right end-screen area, the click track has one click per landing and doesn't clip, and a short encode
works. Run: ./venv/bin/python scripts/test_splitflap.py"""
import os
import subprocess
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(__file__))
import splitflap as sf  # noqa: E402

rows = [{"label": "开往", "label_en": "TO", "text": "SAN ANTONIO", "start": 0.5},
        {"label": "车程", "text": "约 5 小时", "start": 1.0}]
plan = sf.tile_plan(rows, 12, flips=(4, 6), flip_time=0.05, col_stagger=0.04, seed=1)
assert len(plan) == 24
assert plan == sf.tile_plan(rows, 12, flips=(4, 6), flip_time=0.05, col_stagger=0.04, seed=1), "deterministic"
first = plan[0]
assert first["seq"][-1] == "S" and 5 <= len(first["seq"]) <= 7
assert sf.tile_state(first, 0.0) == (" ", " ", None), "blank before its start"
prev, cur, ph = sf.tile_state(first, 0.5 + 0.075)
assert ph is not None and 0 < ph < 1, "mid-flap"
assert sf.tile_state(first, 5.0) == ("S", "S", None), "landed"
blank = [t for t in plan if t["row"] == 0 and t["col"] == 11][0]
assert blank["seq"] == [" "] and sf.tile_state(blank, 3.0)[2] is None, "padding never flaps"
cjk = [t for t in plan if t["row"] == 1 and t["col"] == 0][0]
assert cjk["seq"][-1] == "约" and all(sf.is_cjk(c) for c in cjk["seq"]), "CJK rows flap through CJK chars"
times = sf.flap_times(plan)
assert len(times) == sum(len(t["seq"]) for t in plan if t["seq"] != [" "])
last_landing = max(t["t0"] + len(t["seq"]) * t["dt"] for t in plan)
assert abs(times[-1] - last_landing) < 1e-9

spec = {"dur": 1.5, "fps": 10, "size": [960, 540], "rows": rows,
        "board": {"x": 0.05, "y": 0.08, "tiles": 12, "tile_w": 30, "tile_h": 44}, "flips": [2, 3],
        "flip_time": 0.05, "bg": {"dim": 0.5}}
bd = sf.Board(spec)
x0, y0, x1, y1 = bd.geometry()
assert x1 < 0.70 * 960 and y1 < 0.62 * 540, "board must leave the lower-right end-screen area clear"
f = bd.frame(1.4)
assert f.size == (960, 540)
assert f.getpixel((900, 500)) == bd.frame(0.0).getpixel((900, 500)), "lower right untouched by the board"
with tempfile.TemporaryDirectory() as td:
    out, wav = os.path.join(td, "b.mp4"), os.path.join(td, "c.wav")
    bd.encode(out)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                               capture_output=True, text=True).stdout)
    assert abs(dur - 1.5) < 0.15, dur
    peak = sf.click_track(sf.flap_times(bd.plan), 1.5, wav)
    assert 0.3 < peak <= 0.5 + 1e-6
    with wave.open(wav) as w:
        assert w.getframerate() == 48000 and w.getnframes() > 1.5 * 48000
print("ok")
