"""`src.editor.tally`: collection-tally overlay assets + EDL wiring.
Renders a 3-item tally at 640x360 from solid-colour "photos", checks the badge/arrival frames are transparent
outside the card and opaque inside, that the arrival MOV keeps its alpha, and that attach() puts arrivals and
badges on the right shots without gaps/overlaps (and moves an arrival that would run past its shot end).
Run: ./venv/bin/python scripts/test_tally.py"""
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import tally as T  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    items = []
    for i, col in enumerate(["red", "green", "blue"]):
        p = os.path.join(td, f"c{i}.png")
        Image.new("RGB", (200, 160), col).save(p)
        items.append({"cn": f"动物{i + 1}", "en": f"Animal {i + 1}", "image": f"c{i}.png", "fact": "一句话"})
    spec = {"title": "图鉴", "out_dir": "out", "size": [640, 360], "add_dur": 2.0, "items": items,
            "grid": {"title": "三种", "dur": 1.5}}
    sp = os.path.join(td, "spec.json")
    json.dump(spec, open(sp, "w"), ensure_ascii=False)
    files = T.render_assets(sp)
    out = os.path.join(td, "out")
    for k in (1, 2, 3):
        assert os.path.exists(os.path.join(out, f"badge_{k}.png")) and os.path.exists(os.path.join(out, f"add_{k}.mov"))
    assert os.path.exists(os.path.join(out, "grid.mp4"))

    tl = T.Tally(spec, td)
    b = tl.badge(2)
    assert b.size == (640, 360) and b.mode == "RGBA"
    assert b.getpixel((20, 300))[3] == 0, "badge frame is transparent away from the badge"
    bx, by, bw, bh = tl.box(T.BADGE)
    assert b.getpixel((bx + bw - 4, by + bh // 2))[3] > 100, "badge panel is drawn"
    mid = tl.add_frame(1, 1.0, 2.0)
    cx, cy, cw, ch = tl.box(T.CARD)
    px = mid.getpixel((int(cx + ch * 0.10 + ch * 0.40), int(cy + ch / 2)))
    assert px[3] > 200 and px[1] > px[0] and px[1] > px[2], f"item 2's (green) photo is in the card: {px}"
    assert mid.getpixel((20, 300))[3] == 0
    end = tl.add_frame(1, 2.0, 2.0)
    assert list(end.getdata()) == list(tl.badge(2).getdata()), "an arrival ends on the badge for its count"
    assert tl.badge(0).getbbox() is None

    # the MOV keeps alpha: a corner pixel decodes as fully transparent
    png = os.path.join(td, "f.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.0", "-i", os.path.join(out, "add_1.mov"), "-frames:v", "1",
                    png], check=True)
    f = Image.open(png)
    assert f.mode == "RGBA" and f.getpixel((5, 350))[3] == 0

    # attach: three shots of 3 s; arrivals at s1 0.5, s2 2.5 (too late: moved to 1.0), s3 none
    shots = [{"id": f"s{i}", "clip": "X", "in": 0.0, "out": 3.0} for i in (1, 2, 3)]
    wins = T.attach(shots, [(shots[0], 0.5, 0), (shots[1], 2.5, 1)], out_dir="out", add_dur=2.0, sfx="sfx/ding.wav")
    assert wins == [("s1", 0.5, 2.5, 1), ("s2", 1.0, 3.0, 2)], wins
    p1 = [(p["file"], p["t0"], p["t1"]) for p in shots[0]["pip"]]
    assert p1 == [("out/add_1.mov", 0.5, 2.5), ("out/badge_1.png", 2.5, 3.0)], p1
    p2 = [(p["file"], p["t0"], p["t1"]) for p in shots[1]["pip"]]
    assert p2 == [("out/badge_1.png", 0.0, 1.0), ("out/add_2.mov", 1.0, 3.0)], p2
    assert [(p["file"], p["t0"], p["t1"]) for p in shots[2]["pip"]] == [("out/badge_2.png", 0.0, 3.0)]
    assert all(p["fade"] == 0 and p["w"] == 1.0 for s in shots for p in s["pip"])
    assert [x["at"] for x in shots[0]["sfx"]] == [0.62]
    # re-attaching replaces, never duplicates
    T.attach(shots, [(shots[0], 0.5, 0), (shots[1], 2.5, 1)], out_dir="out", add_dur=2.0, sfx="sfx/ding.wav")
    assert len(shots[0]["pip"]) == 2 and len(shots[0]["sfx"]) == 1
print("ok")
