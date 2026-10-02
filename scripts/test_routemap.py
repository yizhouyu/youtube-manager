"""Route map engine on a tiny synthetic OSM extract. Run: ./venv/bin/python scripts/test_routemap.py

Layout (lat 40.000-40.005, lon -75.000 to -74.990), land to the north, sea south of lat 39.998:

    D ───── Long Rd ───── E          Long Rd: two-way A-D-E-B detour
    │  ╲                  │          Short St: one-way A -> B
    │    ╲ Shortcut       │          Shortcut: footway D -> B
    A ─── Short St (→) ── B
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import routemap as rm  # noqa: E402

A, B, D, E = (40.0, -75.0), (40.0, -74.99), (40.005, -75.0), (40.005, -74.991)


def way(i, tags, *pts):
    return {"type": "way", "id": i, "tags": tags, "geometry": [{"lat": la, "lon": lo} for la, lo in pts]}


OSM = {"elements": [
    way(1, {"highway": "residential", "name": "Short St", "oneway": "yes"}, A, B),
    way(2, {"highway": "residential", "name": "Long Rd"}, A, D, E, B),
    way(3, {"highway": "footway", "name": "Shortcut"}, D, B),
    way(4, {"highway": "motorway", "name": "Freeway"}, (40.002, -75.0), (40.002, -74.99)),
    way(5, {"natural": "coastline"}, (39.998, -75.02), (39.998, -74.97)),  # land on the left = north
]}

# drive respects the one-way
g = rm.RoadGraph(OSM, "drive")
_, _, roads = g.route(A, B)
assert set(roads) == {"Short St"}, roads
_, _, roads = g.route(B, A)
assert "Short St" not in roads and "Long Rd" in roads, f"drive B->A must avoid the one-way: {roads}"
_, _, roads = g.route(D, B)
assert "Shortcut" not in roads, f"cars can't use a footway: {roads}"
assert g.path(A, B)[0] == A and g.path(A, B)[-1] == B

# walk ignores one-ways, uses footways, skips motorways
w = rm.RoadGraph(OSM, "walk")
_, _, roads = w.route(B, A)
assert set(roads) == {"Short St"}, f"walkers may go against a one-way: {roads}"
_, _, roads = w.route(D, B)
assert set(roads) == {"Shortcut"}, f"walk D->B should take the footway: {roads}"
assert all(lab != "Freeway" for edges in w.g.values() for _, _, lab in edges), "no walking on motorways"

# offset: right of travel in screen coords (y down); out-and-back -> two parallel lanes
line = [(0, 0), (100, 0), (200, 0)]
o = rm.offset(line, 10)
assert o[0] == (0, 0) and o[-1] == (200, 0), "ends stay on the pins"
assert abs(o[1][0] - 100) < 1e-9 and abs(o[1][1] - 10) < 1e-9, o
back = rm.offset(line[::-1], 10)
assert abs(back[1][1] + 10) < 1e-9 and abs(o[1][1] - back[1][1] - 20) < 1e-9, "return lane on the other side"

# partial: prefix by length fraction
L = [(0, 0), (100, 0), (100, 100)]
assert rm.partial(L, 0)[1] == (0, 0)
assert rm.partial(L, 0.5)[1] == (100, 0)
pts, end = rm.partial(L, 0.75)
assert end == (100, 50) and pts == [(0, 0), (100, 0), (100, 50)], (pts, end)
assert rm.partial(L, 1)[1] == (100, 100) and rm.partial(L, 2)[1] == (100, 100)

# simplify keeps both ends and drops near-duplicates
assert rm.simplify([(0, 0), (1, 0), (2, 0), (10, 0), (11, 0)], tol=5) == [(0, 0), (10, 0), (11, 0)]

# projection: fit width puts west/east on the rect edges, north on the top edge
P = rm.Projection((39.99, -75.01, 40.01, -74.98), 640, 360, rect=(0.1, 0.2, 0.9, 1.0), fit="width", align=(0.5, 0))
x0, y0 = P(40.01, -75.01)
x1, _ = P(40.01, -74.98)
assert abs(x0 - 64) < 1e-6 and abs(x1 - 576) < 1e-6 and abs(y0 - 72) < 1e-6
la, lo = P.inverse(*P(40.0, -75.0))
assert abs(la - 40.0) < 1e-9 and abs(lo + 75.0) < 1e-9

# high-level smoke test: walk + drive + straight legs, panel, off-map arrow, small frame, sea fill
with tempfile.TemporaryDirectory() as td:
    cfg = {"osm": OSM, "_dir": td, "size": [640, 360], "dur": 2.0, "bbox": [39.994, -75.004, 40.007, -74.986],
           "stops": [{"cn": "A", "sub": "start", "lat": A[0], "lon": A[1], "side": "up"},
                     {"cn": "B", "sub": "", "lat": B[0], "lon": B[1], "side": "right"},
                     {"cn": "D", "sub": "end", "lat": D[0], "lon": D[1], "side": "left"},
                     {"cn": "E", "sub": "", "lat": E[0], "lon": E[1], "side": "down", "halo": "sea"}],
           "legs": ["drive", {"mode": "walk"}, "straight"], "panel": {"title": "Test", "width": 0.25},
           "flight": {"span": [1.4, 1.8], "to": [0.98, 0.1], "style": "arrow", "label": "onward"}}
    cfg["osm"] = os.path.join(td, "osm.json")
    import json
    json.dump(OSM, open(cfg["osm"], "w"))
    m = rm.RouteMap(cfg, verbose=False)
    assert len(m.legs) == 3 and m.spans[0][0] == 0.3 and m.spans[-1][1] <= 1.3 + 1e-9, m.spans
    col = rm.COLORS
    assert m.base.getpixel((600, 355)) == col["sea"], "south of the coastline is sea"
    assert m.base.getpixel((600, 5)) == col["land"], "north of the coastline is land"
    for t in (0.0, 0.7, 1.9):
        im = m.frame(t)
        assert im.size == (640, 360)
    assert not any(im.convert("RGB").getpixel((x, 180)) == col["land"] for x in range(5, 150, 10)), "panel drawn"
    try:
        rm.load_config({"stops": cfg["stops"], "legs": ["drive"]})
        raise AssertionError("leg count mismatch must raise")
    except ValueError:
        pass
print("ok")
