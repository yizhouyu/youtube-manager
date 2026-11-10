"""Title notes (片头字, EDL note_style "title", creator pick 2026-11-10): even in-frame blur boxes, mask size =
box, subtitle_top agrees with the glyphs, label/year accent parsing, wrap rules, title-style place tags, and
the default style. Run: ./venv/bin/python scripts/test_title_note.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image, ImageDraw  # noqa: E402
from src.editor import overlays as O  # noqa: E402

LONG = "1990年代改霓虹后，南京路被称为“中华灯光第一街”，再加一句很长的话来测试换行"
ACC, FG = O.TITLE_NOTE["accent"], O.TITLE_NOTE["fg"]

# parsing: label before 「：」 -> accent + separator; else the first year-like token -> accent
p = O._title_parse("广播：不要停留，不要拍照", ACC, FG)
assert [c for c, col in p[:2]] == ["广", "播"] and all(col == ACC for _, col in p[:2]) and p[2][0] == O._SEP
assert all(col == FG for _, col in p[3:])
p = O._title_parse("外白渡桥1908年通车", ACC, FG)
assert "".join(c for c, col in p if col == ACC) == "1908年"
assert "".join(c for c, col in O._title_parse("100年前，南京路", ACC, FG) if col == ACC) == "100年前"
assert "".join(c for c, col in O._title_parse("1990年代改霓虹后", ACC, FG) if col == ACC) == "1990年代"
assert not any(col == ACC for _, col in O._title_parse("从1楼一路转到6楼", ACC, FG))
assert not any(c == O._SEP for c, _ in O._title_parse("6:28 太阳出来了", ACC, FG))      # a time, not a label

td = tempfile.mkdtemp()
for w, h in [(1920, 1080), (3840, 2160), (1080, 1920)]:
    for pos in ("top", "bottom"):
        for t in ("东方明珠468米，1994年建成", "广播：不要停留，不要拍照", LONG):
            x, y, bw, bh, _ = O.title_note_box(t, w, h, pos)
            assert all(v % 2 == 0 for v in (x, y, bw, bh)), (w, h, x, y, bw, bh)
            assert 0 <= x and x + bw <= w and 0 <= y and y + bh <= h and bw > 0 and bh > 0, (w, h, pos, x, y, bw, bh)
            m = Image.open(O.title_note_mask(t, w, h, td, pos))
            assert m.size == (bw, bh) and m.mode == "L"
            png = Image.open(O.subtitle(t, w, h, td, "note", pos, "title"))
            assert png.size == (w, h)
            a = png.getchannel("A")
            ab = a.point(lambda v: 255 if v > 200 else 0).getbbox()        # the type itself
            assert ab and (ab[1] < h * 0.3 if pos == "top" else ab[3] > h * 0.6), (pos, ab)
            if pos == "bottom":
                top = O.subtitle_top(t, w, h, "note", "title")
                assert abs(top - ab[1]) < h * 0.01, (top, ab)
            # no hard edge: the plate-less look never reaches near-opaque outside the glyphs' neighbourhood
            assert a.getpixel((max(0, ab[0] - int(h * 0.05)), (ab[1] + ab[3]) // 2)) < 200
    # wrap: the long note breaks into two lines, never inside a number or before closing punctuation
    lines = O._title_lines(ImageDraw.Draw(Image.new("L", (8, 8))), O._title_parse(LONG, ACC, FG), O._face(O.TITLE_NOTE_FONTS, int(O.TITLE_NOTE["size"] * min(w, h))),
                           0, w * 0.5, 1.0)
    assert len(lines) == 2 and lines[1][0][0] not in "，、。；：！？”）"
    assert not (lines[0][-1][0].isdigit() and lines[1][0][0].isdigit())
    for pos in ("tl", "tr"):
        tag = Image.open(O.place_tag("傍晚 5:51", w, h, td, pos, "title"))
        bb = tag.getchannel("A").point(lambda v: 255 if v > 200 else 0).getbbox()
        assert bb and bb[1] < h * 0.15 and ((bb[0] < w * 0.2) if pos == "tl" else (bb[2] > w * 0.8)), (pos, bb)
    # the old pill is unchanged for other styles
    assert O.place_tag("傍晚 5:51", w, h, td) == O.place_tag("傍晚 5:51", w, h, td, "tl", "glass")
assert all(isinstance(p, str) for p in O.TITLE_FONTS)   # title cards keep their own font list
assert O.DEFAULT_NOTE_STYLE == "title" and O.DEFAULT_NOTE_STYLE in O.NOTE_STYLES
print("ok: title notes")
