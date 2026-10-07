"""Animated route map on a real OpenStreetMap base, where every leg follows real roads or trails.

Generalised from the ep 96 route map, which the creator approved. Two layers:

* Generic engine: `fetch` / `load` an Overpass extract, then `Projection`, `RoadGraph(osm, mode)`
  with `.path(a, b)`, `simplify`, `offset`, `partial`, `dashed_poly`, `draw_base`, `pin`,
  `flight_arc` and `frames_to_mp4`.
* High-level helper: `render_route(config)` takes a dict or a JSON path and renders the map mp4
  plus a preview jpg. The defaults give the ep 96 look. Keys are listed in `DEFAULTS` and
  `COLORS`, and a full example is in the docstring of `render_route`.

Episode configs (stops, bbox, labels) live in each episode's `edit/maps/route_config.json`.
Relative paths in a config resolve against the config file's folder.

CLI (from the repo root):
    ./venv/bin/python -m src.editor.routemap <config.json> [fetch] [legs] [route] [--out X.mp4] [--preview X.jpg]
`route` is the default. `legs` only prints each leg's distance and roads.
Map data is (c) OpenStreetMap contributors (ODbL); keep the on-screen credit.
"""
import argparse
import copy
import heapq
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HEAVY_FONTS = [os.path.join(_REPO, "assets", "fonts", "heavy.otf"),
               "/System/Library/Fonts/STHeiti Medium.ttc",
               "/System/Library/Fonts/Hiragino Sans GB.ttc",
               "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
SANS_FONTS = ["/System/Library/Fonts/STHeiti Medium.ttc",
              "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/System/Library/Fonts/PingFang.ttc",
              "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"]
CREDIT = "路线示意 · 地图数据 © OpenStreetMap contributors"


def font_path(kind="sans", override=None):
    """First existing font for 'heavy' or 'sans' (an explicit `override` path wins)."""
    for p in ([override] if override else []) + (HEAVY_FONTS if kind == "heavy" else SANS_FONTS):
        if p and os.path.exists(p):
            return p
    return None


@lru_cache(maxsize=None)
def font(path, size):
    if path is None:
        return ImageFont.load_default(size=size)
    return ImageFont.truetype(path, size)


def ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def pop(t):
    """0 to 1 with a small overshoot (sticker pop-in)."""
    t = max(0.0, min(1.0, t))
    return 1 + 2.7 * (t - 1) ** 3 + 1.7 * (t - 1) ** 2


# ── Overpass extract ─────────────────────────────────────────────────────────────────────────
OVERPASS = ("https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter")
USER_AGENT = "vlog-map-script/1.0"  # generic on purpose: never put personal info in requests
MAJOR = ("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
         "secondary_link", "tertiary", "tertiary_link")
MINOR = ("unclassified", "residential", "service", "living_street")
PATHS = ("footway", "path", "pedestrian", "steps", "track", "cycleway", "bridleway")
KINDS = {  # kind -> Overpass way selectors
    "major": ('way["highway"~"^(%s)$"]' % "|".join(MAJOR),),
    "minor": ('way["highway"~"^(%s)$"]' % "|".join(MINOR),),
    "paths": ('way["highway"~"^(%s)$"]' % "|".join(PATHS),),
    "coast": ('way["natural"="coastline"]',),
    "water": ('way["natural"="water"]', 'way["waterway"~"^(river|stream|canal)$"]'),
}
KEEP_TAGS = ("highway", "natural", "waterway", "oneway", "junction", "name", "ref", "access", "foot")


def _bb(b):
    return "(" + ", ".join(str(v) for v in b) + ")"


def fetch(bbox, out_json, kinds=("major", "coast"), coast_bbox=None, around=(), around_radius=600,
          around_kinds=("minor",), retries=6, wait=20):
    """Download OSM ways with Overpass and cache a compact JSON at `out_json`.

    bbox / coast_bbox are (south, west, north, east). Ways of `kinds` come from bbox; the coastline
    from coast_bbox (default bbox) since the sea polygon needs the coast to run past the view.
    `around` is a list of (lat, lon) points (the stops), and ways of `around_kinds` within
    `around_radius` metres of each point are added, so routes can reach car parks and trailheads.
    Busy servers (429/504) are retried with the next mirror."""
    stmts = []
    for k in kinds:
        for sel in KINDS[k]:
            stmts.append(f" {sel}{_bb(coast_bbox or bbox) if k == 'coast' else _bb(bbox)};")
    for la, lo in around:
        for k in around_kinds:
            for sel in KINDS[k]:
                stmts.append(f" {sel}(around:{around_radius},{la},{lo});")
    q = "[out:json][timeout:300][maxsize:536870912];\n(\n" + "\n".join(stmts) + "\n);\nout geom qt;"
    raw = None
    for attempt in range(retries):
        url = OVERPASS[attempt % len(OVERPASS)]
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                     headers={"User-Agent": USER_AGENT})
        try:
            raw = json.load(urllib.request.urlopen(req, timeout=400))
            break
        except Exception as ex:
            print("overpass retry:", url, ex)
            time.sleep(wait)
    if raw is None:
        raise SystemExit("Overpass unavailable")
    els = []
    for e in raw["elements"]:
        if e.get("type") != "way" or not e.get("geometry"):
            continue
        els.append({"type": "way", "id": e["id"],
                    "tags": {k: v for k, v in e.get("tags", {}).items() if k in KEEP_TAGS},
                    "nodes": e.get("nodes", []),
                    "geometry": [{"lat": round(p["lat"], 6), "lon": round(p["lon"], 6)} for p in e["geometry"]]})
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, "w") as f:
        json.dump({"copyright": raw.get("osm3s", {}).get("copyright", "© OpenStreetMap contributors, ODbL"),
                   "timestamp": raw.get("osm3s", {}).get("timestamp_osm_base"), "query": q, "elements": els},
                  f, separators=(",", ":"))
    print("saved", out_json, len(els), "ways")
    return els


def load(path_or_obj):
    """OSM elements from a cached extract path, a {"elements": [...]} dict, or a list."""
    obj = path_or_obj
    if isinstance(obj, str):
        with open(obj) as f:
            obj = json.load(f)
    return obj["elements"] if isinstance(obj, dict) else obj


# ── projection ───────────────────────────────────────────────────────────────────────────────
class Projection:
    """Equirectangular lat/lon to pixels (y down), with true aspect at `ref_lat`.

    bbox = (south, west, north, east) is placed into `rect` = (x0, y0, x1, y1), given as fractions
    of the W x H frame. fit="width" puts west/east on x0/x1, fit="height" puts north/south on y0/y1,
    and fit="contain" uses whichever is tighter. `align` = (ax, ay) places the content inside rect
    (0 means left/top). Calling it with (lat, lon) returns (x, y)."""

    def __init__(self, bbox, W, H, rect=(0.05, 0.05, 0.95, 0.95), ref_lat=None, fit="contain", align=(0.5, 0.5)):
        s, w, n, e = bbox
        self.W, self.H = W, H
        self.ref_lat = (s + n) / 2 if ref_lat is None else ref_lat
        c = math.cos(math.radians(self.ref_lat))
        rw, rh = (rect[2] - rect[0]) * W, (rect[3] - rect[1]) * H
        kx_w, kx_h = rw / (e - w), rh / (n - s) * c
        kx = {"width": kx_w, "height": kx_h}.get(fit, min(kx_w, kx_h))
        self.kx, self.ky = kx, kx / c
        self.lon0, self.lat1 = w, n
        self.x0 = rect[0] * W + (rw - (e - w) * kx) * align[0]
        self.y0 = rect[1] * H + (rh - (n - s) * self.ky) * align[1]

    @classmethod
    def around(cls, lat, lon, px_per_deg_lat, cx, cy, W, H):
        """Centre (lat, lon) at pixel (cx, cy) with a given scale (the ep 103 trail-map style)."""
        p = cls.__new__(cls)
        p.W, p.H, p.ref_lat = W, H, lat
        p.ky = px_per_deg_lat
        p.kx = px_per_deg_lat * math.cos(math.radians(lat))
        p.lon0, p.lat1, p.x0, p.y0 = lon, lat, cx, cy
        return p

    def __call__(self, lat, lon):
        return self.x0 + (lon - self.lon0) * self.kx, self.y0 + (self.lat1 - lat) * self.ky

    def inverse(self, x, y):
        return self.lat1 - (y - self.y0) / self.ky, self.lon0 + (x - self.x0) / self.kx

    def view_bbox(self):
        """(south, west, north, east) visible in the frame."""
        s, w = self.inverse(0, self.H)
        n, e = self.inverse(self.W, 0)
        return s, w, n, e


# ── road graph + shortest path ───────────────────────────────────────────────────────────────
DRIVABLE = set(MAJOR) | set(MINOR)
WALKABLE = set(PATHS) | set(MINOR) | {"tertiary", "tertiary_link", "secondary", "secondary_link", "primary",
                                      "primary_link"}


def hav(a, b):
    """Great-circle metres between (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


class RoadGraph:
    """Directed graph node -> [(node, metres, way name/ref)] built from OSM ways.

    mode="drive": car roads, honours oneway (implied on motorways and roundabouts), skips
    access=private/no. mode="walk": footways, paths, steps, pedestrian streets and ordinary
    roads except motorways/trunks, every edge two-way, skips foot=no and private access."""

    def __init__(self, osm, mode="drive"):
        if mode not in ("drive", "walk"):
            raise ValueError(f"mode must be drive or walk, not {mode!r}")
        self.mode = mode
        g = {}
        for e in load(osm):
            t = e.get("tags", {})
            hw = t.get("highway")
            if not e.get("geometry"):
                continue
            if mode == "drive":
                if hw not in DRIVABLE or t.get("access") in ("private", "no"):
                    continue
                ow = t.get("oneway")
                fwd = ow in ("yes", "true", "1") or (ow is None and (hw == "motorway" or t.get("junction") == "roundabout"))
                rev = ow == "-1"
            else:
                if hw not in WALKABLE or t.get("foot") == "no":
                    continue
                if t.get("access") in ("private", "no") and t.get("foot") not in ("yes", "designated", "permissive"):
                    continue
                fwd = rev = False
            label = t.get("ref") or t.get("name") or hw
            pts = [(round(p["lat"], 6), round(p["lon"], 6)) for p in e["geometry"]]
            for a, b in zip(pts, pts[1:]):
                w = hav(a, b)
                if not rev:
                    g.setdefault(a, []).append((b, w, label))
                    g.setdefault(b, [])
                if not fwd:
                    g.setdefault(b, []).append((a, w, label))
                    g.setdefault(a, [])
        self.g = g

    def dijkstra(self, src):
        dist, prev, q = {src: 0.0}, {}, [(0.0, src)]
        while q:
            dc, n = heapq.heappop(q)
            if dc > dist[n]:
                continue
            for m, w, lab in self.g[n]:
                nd = dc + w
                if nd < dist.get(m, 1e18):
                    dist[m], prev[m] = nd, (n, lab, w)
                    heapq.heappush(q, (nd, m))
        return dist, prev

    def route(self, a, b, snap=250, tries=12):
        """Shortest a to b -> ([(lat, lon), ...] from a to b, metres, {road: metres}).

        Tries the `tries` graph nodes nearest to a as the start, and keeps the first one from
        which a node within `snap` metres of b is reachable. That avoids starting on the wrong
        carriageway of a one-way pair."""
        if not self.g:
            raise ValueError("road graph is empty: check the OSM extract and the mode")
        for sa in sorted(self.g, key=lambda n: hav(n, a))[:tries]:
            dist, prev = self.dijkstra(sa)
            sb = min(dist, key=lambda n: hav(n, b))
            if hav(sb, b) < snap:
                break
        out, roads, n = [sb], {}, sb
        while n != sa:
            n, lab, w = prev[n]
            roads[lab] = roads.get(lab, 0) + w
            out.append(n)
        return [tuple(a)] + out[::-1] + [tuple(b)], dist[sb], roads

    def path(self, a, b, **kw):
        """Shortest path a to b as [(lat, lon), ...], including a and b themselves."""
        return self.route(a, b, **kw)[0]


# ── polyline helpers (pixel space) ───────────────────────────────────────────────────────────
def simplify(pts, tol=5.0):
    """Drop points closer than `tol` to the last kept one (keeps both ends)."""
    out = [pts[0]]
    for p in pts[1:-1]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= tol:
            out.append(p)
    out.append(pts[-1])
    return out


def offset(pts, d):
    """Offset a pixel polyline by d to the right of travel (screen coords, y down), ends kept on the pins.

    An out-and-back on the same road then reads as two parallel lanes."""
    n = len(pts)
    res = []
    for i, (x, y) in enumerate(pts):
        if i in (0, n - 1):
            res.append((x, y))
            continue
        tx, ty = 0.0, 0.0
        for j0, j1 in ((i - 1, i), (i, i + 1)):
            dx, dy = pts[j1][0] - pts[j0][0], pts[j1][1] - pts[j0][1]
            L = math.hypot(dx, dy) or 1
            tx, ty = tx + dx / L, ty + dy / L
        L = math.hypot(tx, ty) or 1
        res.append((x - ty / L * d, y + tx / L * d))
    return res


def partial(pts, frac):
    """Prefix of a polyline covering `frac` of its length -> (points, end point)."""
    seg = [math.hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(pts, pts[1:])]
    L = sum(seg) * max(0.0, min(1.0, frac))
    out, acc = [pts[0]], 0.0
    for (p0, p1), s in zip(zip(pts, pts[1:]), seg):
        if acc + s >= L:
            u = (L - acc) / s if s else 0
            e = (p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u)
            out.append(e)
            return out, e
        out.append(p1)
        acc += s
    return out, pts[-1]


def dashed_poly(d, pts, col, width, dash=46, gap=24):
    """Dashed polyline whose dash phase runs continuously across vertices."""
    run, on = 0.0, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        s = math.hypot(x1 - x0, y1 - y0)
        u = 0.0
        while u < s:
            step = min((dash if on else gap) - run, s - u)
            a = (x0 + (x1 - x0) * u / s, y0 + (y1 - y0) * u / s)
            b = (x0 + (x1 - x0) * (u + step) / s, y0 + (y1 - y0) * (u + step) / s)
            if on:
                d.line([a, b], fill=col, width=width)
            u += step
            run += step
            if run >= (dash if on else gap) - 1e-6:
                run, on = 0.0, not on


# ── base map ─────────────────────────────────────────────────────────────────────────────────
def coast_chains(osm):
    """Stitch natural=coastline ways (land on the left) into chains of (lat, lon)."""
    ways = [[(p["lat"], p["lon"]) for p in e["geometry"]] for e in load(osm)
            if e.get("tags", {}).get("natural") == "coastline" and e.get("geometry")]
    by_start = {w[0]: w for w in ways}
    starts = set(by_start)
    ends = {w[-1] for w in ways}
    chains, used = [], set()
    for w in ways:
        if id(w) in used or (w[0] in ends and w[0] != w[-1]):
            continue  # not a chain head (unless it's a closed ring)
        ch = list(w)
        used.add(id(w))
        while ch[-1] in starts and ch[-1] != ch[0]:
            nxt = by_start[ch[-1]]
            if id(nxt) in used:
                break
            used.add(id(nxt))
            ch += nxt[1:]
        chains.append(ch)
    for w in ways:  # pure rings made of several ways (no head found)
        if id(w) not in used:
            ch = list(w)
            used.add(id(w))
            while ch[-1] != ch[0] and ch[-1] in starts and id(by_start[ch[-1]]) not in used:
                nxt = by_start[ch[-1]]
                used.add(id(nxt))
                ch += nxt[1:]
            chains.append(ch)
    return chains


def sea_polygon(chain, view):
    """Close an open coastline chain into a sea polygon (lat/lon) far outside the `view` bbox.

    The sea is on the right of the coastline's direction. Each end leaves the view through the
    side it lies furthest beyond, and the far box is then walked clockwise from the end back to
    the start."""
    s, w, n, e = view
    hs, ws = n - s, e - w
    S, Wf, N, E = s - 3 * hs - 1, w - 3 * ws - 1, n + 3 * hs + 1, e + 3 * ws + 1
    P = (E - Wf) * 2 + (N - S) * 2

    def exit_side(la, lo):
        out = {"N": (la - n) / hs, "E": (lo - e) / ws, "S": (s - la) / hs, "W": (w - lo) / ws}
        return max(out, key=out.get)

    def foot(la, lo, side):
        return {"N": (N, lo), "E": (la, E), "S": (S, lo), "W": (la, Wf)}[side]

    def pos(la, lo, side):  # clockwise perimeter position from the far box's NW corner
        return {"N": lo - Wf, "E": (E - Wf) + (N - la), "S": (E - Wf) + (N - S) + (E - lo),
                "W": 2 * (E - Wf) + (N - S) + (la - S)}[side]

    (la1, lo1), (la0, lo0) = chain[-1], chain[0]
    se, ss = exit_side(la1, lo1), exit_side(la0, lo0)
    fe, fs = foot(la1, lo1, se), foot(la0, lo0, ss)
    pe, ps = pos(*fe, se), pos(*fs, ss)
    corners = [(E - Wf, (N, E)), ((E - Wf) + (N - S), (S, E)), (2 * (E - Wf) + (N - S), (S, Wf)), (P, (N, Wf))]
    span = (ps - pe) % P
    walk = sorted(((c - pe) % P, ll) for c, ll in corners if 0 < (c - pe) % P < span)
    return list(chain) + [fe] + [ll for _, ll in walk] + [fs]


# highway: (casing width, fill width, fill colour) in draw order; 0 casing = none. Widths are for 4K.
ROAD_STYLES = [
    ("tertiary", 0, 5, (250, 238, 218)),
    ("tertiary_link", 0, 4, (250, 238, 218)),
    ("secondary", 11, 7, (253, 245, 230)),
    ("secondary_link", 8, 5, (253, 245, 230)),
    ("primary", 14, 9, (255, 249, 238)),
    ("primary_link", 9, 6, (255, 249, 238)),
    ("trunk", 16, 11, (252, 226, 180)),
    ("trunk_link", 10, 6, (252, 226, 180)),
    ("motorway_link", 10, 6, (250, 214, 160)),
    ("motorway", 20, 14, (250, 214, 160)),
]
# trail / town walks: minor streets and footpaths drawn too, under the main roads
WALK_STYLES = [
    ("footway", 0, 5, (150, 120, 90)),
    ("path", 0, 5, (150, 120, 90)),
    ("track", 0, 5, (150, 120, 90)),
    ("steps", 0, 5, (150, 120, 90)),
    ("pedestrian", 0, 8, (255, 252, 244)),
    ("service", 0, 4, (250, 238, 218)),
    ("residential", 0, 5, (250, 238, 218)),
    ("living_street", 0, 5, (250, 238, 218)),
    ("unclassified", 0, 5, (250, 238, 218)),
] + ROAD_STYLES

COLORS = {  # ep 96 palette
    "land": (243, 227, 200), "sea": (178, 212, 228), "coast": (120, 160, 185), "water": (178, 212, 228),
    "casing": (214, 188, 150), "route": (200, 40, 30), "halo": (255, 248, 236), "text": (60, 30, 20),
    "subtext": (120, 70, 45), "flight": (40, 90, 200), "pin": (255, 212, 0), "pin_outline": (60, 30, 20),
    "pin_number": (60, 30, 20), "label": (170, 130, 90), "credit": (150, 110, 80),
    "panel": (246, 241, 226, 242), "panel_line": (170, 150, 110), "panel_dot": (200, 40, 30),
    "panel_number": (255, 255, 255),
}


def draw_base(osm, proj, size, colors=None, roads=None, coast_width=8, sea=True):
    """Land/sea/coastline, lakes and rivers, and a cased road layer -> RGB image.

    `roads` is a style table like ROAD_STYLES; `colors` overrides keys of COLORS; `sea` is True
    (close the longest coastline automatically), False, or a list of extra (lat, lon) points that
    close the longest coastline chain into the sea polygon."""
    col = dict(COLORS, **(colors or {}))
    roads = ROAD_STYLES if roads is None else roads
    els = load(osm)
    im = Image.new("RGB", size, col["land"])
    d = ImageDraw.Draw(im)
    chains = coast_chains(els)
    if chains:
        main = max(chains, key=len)
        if sea and main[0] != main[-1]:
            ring = main + [tuple(p) for p in sea] if isinstance(sea, list) else sea_polygon(main, proj.view_bbox())
            d.polygon([proj(la, lo) for la, lo in ring], fill=col["sea"])
        for ch in chains:
            if ch is not main and ch[0] == ch[-1] and len(ch) > 3:
                d.polygon([proj(la, lo) for la, lo in ch], fill=col["land"])  # islands / breakwaters
    for e in els:
        t = e.get("tags", {})
        g = e.get("geometry")
        if t.get("natural") == "water" and g and len(g) > 3 and g[0] == g[-1]:
            d.polygon([proj(p["lat"], p["lon"]) for p in g], fill=col["water"])
        elif t.get("waterway") and g:
            d.line([proj(p["lat"], p["lon"]) for p in g], fill=col["water"],
                   width=8 if t["waterway"] == "river" else 4, joint="curve")
    for ch in chains:
        d.line([proj(la, lo) for la, lo in ch], fill=col["coast"], width=coast_width, joint="curve")
    styles = {hw: (cw, fw, c) for hw, cw, fw, c in roads}
    order = [hw for hw, *_ in roads]
    ways = sorted((e for e in els if e.get("tags", {}).get("highway") in styles and e.get("geometry")),
                  key=lambda e: order.index(e["tags"]["highway"]))
    for casing in (True, False):
        for e in ways:
            cw, fw, c = styles[e["tags"]["highway"]]
            if casing and not cw:
                continue
            pts = [proj(p["lat"], p["lon"]) for p in e["geometry"]]
            d.line(pts, fill=tuple(col["casing"]) if casing else tuple(c), width=cw if casing else fw, joint="curve")
    return im


# ── pins, flight arc ─────────────────────────────────────────────────────────────────────────
def pin(d, x, y, num, cn, sub, side, s, fonts, colors=None, halo=None, scale=1.0):
    """Numbered pin at (x, y) popped to size s (0..1+), with a name and a sub-label.

    fonts = (name font, sub font, number font). side: up, upright, upleft, down, left, right
    ("downland" is accepted as down). halo is the text outline colour (default: land)."""
    col = dict(COLORS, **(colors or {}))
    fc, fe, fn = fonts
    k = scale
    r = 42 * s * k
    d.ellipse([x - r, y - r, x + r, y + r], fill=col["pin"], outline=col["pin_outline"],
              width=max(1, int(10 * s * k)))
    if s > 0.6:
        d.text((x, y + 2 * k), str(num), font=fn, fill=col["pin_number"], anchor="mm")
    if s < 0.95:
        return
    sw = dict(stroke_width=max(1, round(10 * k)), stroke_fill=tuple(halo or col["land"]))
    side = "down" if side == "downland" else side
    pos = {  # side: (name xy, name anchor, sub xy, sub anchor), offsets in 4K px
        "up": ((0, -150), "ms", (0, -72), "ms"),
        "upright": ((56, -150), "ls", (58, -78), "ls"),
        "upleft": ((-56, -150), "rs", (-58, -78), "rs"),
        "down": ((0, 74), "mt", (0, 176), "mt"),
        "right": ((66, -4), "ls", (66, 10), "lt"),
        "left": ((-66, -4), "rs", (-66, 10), "rt"),
    }
    (cx, cy), ca, (sx, sy), sa = pos.get(side, pos["down"])
    d.text((x + cx * k, y + cy * k), cn, font=fc, fill=col["text"], anchor=ca, **sw)
    if sub:
        d.text((x + sx * k, y + sy * k), sub, font=fe, fill=col["subtext"], anchor=sa, **sw)


def flight_arc(d, p, start, end, lift=380, color=None, width=14, style="plane", label=None, label_font=None,
               label_xy=None, label_anchor="rs", halo=None, scale=1.0):
    """Dotted arc start -> end drawn to fraction p (0..1, already eased), bowed up by `lift` px.

    style="plane" puts a plane on the tip (flight home); style="arrow" puts an arrowhead (an
    off-map continuation). The label is shown once p >= 1."""
    if p <= 0:
        return
    color = tuple(color or COLORS["flight"])
    x0, y0 = start
    x1, y1 = end
    pts = []
    for k in range(int(60 * p) + 1):
        u = k / 60
        pts.append((x0 + (x1 - x0) * u, y0 + (y1 - y0) * u - lift * math.sin(math.pi * u)))
    for a, b in zip(pts[::2], pts[1::2]):
        d.line([a, b], fill=color, width=width)
    if pts:
        xe, ye = pts[-1]
        xp, yp = pts[max(0, len(pts) - 3)]
        ang = math.atan2(ye - yp, xe - xp) if len(pts) > 1 else 0
        if style == "arrow":
            shapes = [[(60, 0), (-30, -42), (-30, 42)]]
        else:
            shapes = [[(70, 0), (-50, -14), (-50, 14)],
                      [(15, 0), (-20, -70), (-35, -70), (-10, 0), (-35, 70), (-20, 70)]]
        for shp in shapes:
            d.polygon([(xe + scale * (x * math.cos(ang) - y * math.sin(ang)),
                        ye + scale * (x * math.sin(ang) + y * math.cos(ang))) for x, y in shp], fill=color)
    if p >= 1 and label:
        d.text(label_xy or (x1 + 40 * scale, y1 - 110 * scale), label, font=label_font, fill=color,
               anchor=label_anchor, stroke_width=max(1, round(10 * scale)), stroke_fill=tuple(halo or COLORS["land"]))


# ── video ────────────────────────────────────────────────────────────────────────────────────
def frames_to_mp4(frame_fn, dur, out, fps=30, crf=14, preset="slow"):
    """Render frame_fn(t) for t in [0, dur) to an H.264 mp4 (yuv420p, faststart)."""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        for k in range(int(round(dur * fps))):
            frame_fn(k / fps).convert("RGB").save(os.path.join(td, f"{k:04d}.png"), compress_level=1)
        subprocess.run(["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i",
                        os.path.join(td, "%04d.png"), "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], check=True)


# ── high-level: config -> route map ──────────────────────────────────────────────────────────
DEFAULTS = {
    "osm": None,                 # cached extract (relative to the config file), required
    "out": "route.mp4",
    "preview": "route_last_frame.jpg",
    "preview_size": [1280, 720],
    "size": [3840, 2160], "fps": 30, "dur": 5.0,
    "bbox": None,                # [south, west, north, east] shown on the map, required
    "frame": [0.05, 0.05, 0.95, 0.95],  # where bbox goes, as fractions of the frame (x0, y0, x1, y1)
    "fit": "contain", "align": [0.5, 0.5], "ref_lat": None,
    "mode": "drive",             # default leg mode: drive | walk | straight
    "legs": None,                # per leg: {"mode": ..., "via": [[lat, lon], ...], "offset": px}
    "stops": [],                 # {"cn", "sub", "lat", "lon", "side", "halo"}
    "spans": None,               # per leg [t0, t1] seconds; default spreads legs over the clip
    "first_pin": 0.1, "pin_pop": 0.3,
    "title": None, "sub_title": None,
    "title_xy": [0.06, 0.05], "title_size": 140, "sub_title_size": 64,
    "labels": [],                # {"text", "lat", "lon", "size", "color", "halo": "land"|"sea"|null|[r,g,b]}
    "credit": CREDIT, "credit_size": 44, "credit_halo": "auto",
    "panel": None,               # {"title", "sub", "note", "width"}: left info panel listing the stops
    "flight": None,              # {"span", "to", "lift", "label", "style": "plane"|"arrow", "color", "from"}
    "colors": {},
    "roads": None,               # style table; default ROAD_STYLES (drive) or WALK_STYLES (any walk leg)
    "sea": True,                 # True | False | [[lat, lon], ...] closing points
    "lane_offset": 15, "simplify": 5.0,
    "route_width": 18, "route_halo_width": 34, "dash": 46, "gap": 24, "head_r": 26,
    "name_size": 80, "sub_size": 54, "number_size": 52, "flight_label_size": 80,
    "fonts": {},                 # {"heavy": path, "sans": path}
    "fetch": None,               # {"bbox", "coast_bbox", "kinds", "around_radius", "around_kinds"}
}


def load_config(config):
    """Dict or JSON path -> config with defaults filled in and paths made absolute."""
    base = os.getcwd()
    if isinstance(config, str):
        base = os.path.dirname(os.path.abspath(config))
        with open(config) as f:
            config = json.load(f)
    cfg = copy.deepcopy(DEFAULTS)
    cfg.update(copy.deepcopy(config))
    cfg["_dir"] = config.get("_dir", base)
    for k in ("osm", "out", "preview"):
        if cfg.get(k):
            cfg[k] = os.path.join(cfg["_dir"], os.path.expanduser(cfg[k]))
    cfg["colors"] = {k: tuple(v) for k, v in dict(COLORS, **cfg["colors"]).items()}
    n = max(0, len(cfg["stops"]) - 1)
    legs = cfg["legs"] or [{} for _ in range(n)]
    if len(legs) != n:
        raise ValueError(f"{len(cfg['stops'])} stops need {n} legs, got {len(legs)}")
    cfg["legs"] = [dict({"mode": cfg["mode"]}, **(lg if isinstance(lg, dict) else {"mode": lg})) for lg in legs]
    return cfg


def _halo(cfg, h):
    if h is None:
        return None
    if isinstance(h, str):
        return cfg["colors"][h]
    return tuple(h)


def fetch_config(config):
    """Run the Overpass extract described by the config's "fetch" block (or derived from bbox)."""
    cfg = load_config(config)
    fc = cfg["fetch"] or {}
    s, w, n, e = cfg["bbox"]
    pad_la, pad_lo = (n - s) * 0.2, (e - w) * 0.2
    bbox = fc.get("bbox") or [s - pad_la, w - pad_lo, n + pad_la, e + pad_lo]
    walk = any(lg["mode"] == "walk" for lg in cfg["legs"])
    kinds = fc.get("kinds") or (["major", "minor", "paths", "coast", "water"] if walk else ["major", "coast"])
    around_kinds = fc.get("around_kinds") or (["minor", "paths"] if walk else ["minor"])
    pts = [(st["lat"], st["lon"]) for st in cfg["stops"]]
    return fetch(bbox, cfg["osm"], kinds=kinds, coast_bbox=fc.get("coast_bbox"), around=pts,
                 around_radius=fc.get("around_radius", 600), around_kinds=around_kinds)


class RouteMap:
    """Everything render_route needs, built once: projection, base image, legs, fonts."""

    def __init__(self, config, verbose=True):
        cfg = self.cfg = load_config(config)
        if not cfg["osm"] or not cfg["bbox"]:
            raise ValueError("config needs 'osm' and 'bbox'")
        self.W, self.H = cfg["size"]
        self.k = self.W / 3840  # sizes in the config are for 4K
        self.proj = Projection(cfg["bbox"], self.W, self.H, rect=cfg["frame"], ref_lat=cfg["ref_lat"],
                               fit=cfg["fit"], align=cfg["align"])
        self.osm = load(cfg["osm"])
        self.heavy = font_path("heavy", cfg["fonts"].get("heavy"))
        self.sans = font_path("sans", cfg["fonts"].get("sans"))
        self.graphs = {}
        self.legs = self._legs(verbose)
        self.P = [self.proj(st["lat"], st["lon"]) for st in cfg["stops"]]
        self.spans = self._spans()
        self.base = self._base()

    def F(self, kind, size):
        return font(self.heavy if kind == "heavy" else self.sans, max(1, round(size * self.k)))

    def graph(self, mode):
        if mode not in self.graphs:
            self.graphs[mode] = RoadGraph(self.osm, mode)
        return self.graphs[mode]

    def _legs(self, verbose):
        cfg, out = self.cfg, []
        st = cfg["stops"]
        for i, lg in enumerate(cfg["legs"]):
            a, b = st[i], st[i + 1]
            pts = [(a["lat"], a["lon"])] + [tuple(v) for v in lg.get("via", [])] + [(b["lat"], b["lon"])]
            ll, metres, roads = [pts[0]], 0.0, {}
            for p, q in zip(pts, pts[1:]):
                if lg["mode"] == "straight":
                    seg, m, r = [p, q], hav(p, q), {"straight": hav(p, q)}
                else:
                    seg, m, r = self.graph(lg["mode"]).route(p, q)
                ll += seg[1:]
                metres += m
                for kk, v in r.items():
                    roads[kk] = roads.get(kk, 0) + v
            if verbose:
                top = sorted(roads.items(), key=lambda kv: -kv[1])[:6]
                print(f"{a.get('cn', i + 1)} → {b.get('cn', i + 2)} ({lg['mode']}): {metres / 1000:.1f} km via",
                      ", ".join(f"{kk} {v / 1000:.1f}km" for kk, v in top))
            px = simplify([self.proj(la, lo) for la, lo in ll], cfg["simplify"] * self.k)
            out.append(offset(px, lg.get("offset", cfg["lane_offset"]) * self.k))
        return out

    def _spans(self):
        cfg = self.cfg
        n = len(self.legs)
        if cfg["spans"]:
            return [tuple(s) for s in cfg["spans"]]
        if all("span" in lg for lg in cfg["legs"]):
            return [tuple(lg["span"]) for lg in cfg["legs"]]
        t_end = (cfg["flight"]["span"][0] - 0.1) if cfg["flight"] else cfg["dur"] - 1.0
        t0 = 0.3
        return [(t0 + (t_end - t0) * k / n, t0 + (t_end - t0) * (k + 1) / n) for k in range(n)]

    def _base(self):
        cfg, col, k = self.cfg, self.cfg["colors"], self.k
        roads = cfg["roads"]
        if roads is None:
            roads = WALK_STYLES if any(lg["mode"] == "walk" for lg in cfg["legs"]) else ROAD_STYLES
        roads = [(hw, round(cw * k), max(1, round(fw * k)), tuple(c)) for hw, cw, fw, c in roads]
        im = draw_base(self.osm, self.proj, (self.W, self.H), col, roads, coast_width=max(1, round(8 * k)),
                       sea=cfg["sea"])
        d = ImageDraw.Draw(im)
        for lb in cfg["labels"]:
            h = _halo(cfg, lb.get("halo", "land"))
            sw = dict(stroke_width=max(1, round(lb.get("stroke", 10) * k)), stroke_fill=h) if h else {}
            d.text(self.proj(lb["lat"], lb["lon"]), lb["text"], font=self.F(lb.get("font", "sans"), lb.get("size", 80)),
                   fill=tuple(lb.get("color", col["label"])), anchor=lb.get("anchor", "mm"), **sw)
        sw = dict(stroke_width=max(1, round(10 * k)), stroke_fill=col["land"])
        if cfg["title"] and not cfg["panel"]:
            tx, ty = cfg["title_xy"][0] * self.W, cfg["title_xy"][1] * self.H
            d.text((tx, ty), cfg["title"], font=self.F("heavy", cfg["title_size"]), fill=col["text"], **sw)
            if cfg["sub_title"]:
                d.text((tx + 4 * k, ty + (cfg["title_size"] + 40) * k), cfg["sub_title"],
                       font=self.F("sans", cfg["sub_title_size"]), fill=col["subtext"], **sw)
        if cfg["credit"] and not cfg["panel"]:
            xy = (0.06 * self.W + 6 * k, self.H * 0.955)
            h = cfg["credit_halo"]
            if h == "auto":  # outline in whatever the map shows under the credit
                h = im.getpixel((int(xy[0] + 40 * k), int(xy[1] - 15 * k)))
            d.text(xy, cfg["credit"], font=self.F("sans", cfg["credit_size"]), fill=col["credit"], anchor="ls",
                   stroke_width=max(1, round(6 * k)), stroke_fill=_halo(cfg, h))
        return im

    def _panel(self, im, done):
        """Left info panel (ep 103 style): title block plus the stops reached so far."""
        cfg, col, k, W, H = self.cfg, self.cfg["colors"], self.k, self.W, self.H
        pn = cfg["panel"] if isinstance(cfg["panel"], dict) else {}
        pw = int(pn.get("width", 0.30) * W)
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        a = lambda c: tuple(c[:3]) + (c[3] if len(c) > 3 else 255,)  # noqa: E731
        d.rectangle([0, 0, pw, H], fill=a(col["panel"]))
        d.line([(pw, 0), (pw, H)], fill=a(col["panel_line"]), width=max(1, round(6 * k)))
        x = W * 0.032
        d.text((x, H * 0.06), pn.get("title", cfg["title"] or ""), font=self.F("heavy", 158), fill=a(col["text"]))
        if pn.get("sub", cfg["sub_title"]):
            d.text((x + 6 * k, H * 0.165), pn.get("sub", cfg["sub_title"]), font=self.F("sans", 72),
                   fill=a(col["subtext"]))
        if pn.get("note"):
            d.text((x + 6 * k, H * 0.225), pn["note"], font=self.F("sans", 62), fill=a(col["subtext"]))
        r = 42 * k
        for i, st in enumerate(cfg["stops"]):
            if i > done:
                break
            y = H * 0.33 + i * H * 0.105
            d.ellipse([x, y, x + 2 * r, y + 2 * r], fill=a(col["panel_dot"]))
            d.text((x + r, y + r + 2 * k), str(i + 1), font=self.F("heavy", 50), fill=a(col["panel_number"]), anchor="mm")
            d.text((x + 120 * k, y - 6 * k), st["cn"], font=self.F("heavy", 70), fill=a(col["text"]))
            if st.get("sub"):   # under the name's real ink box (heavy CJK faces run past their nominal size)
                sy = max(y + 76 * k, d.textbbox((x + 120 * k, y - 6 * k), st["cn"], font=self.F("heavy", 70))[3] + 12 * k)
                d.text((x + 122 * k, sy), st["sub"], font=self.F("sans", 50), fill=a(col["subtext"]))
        if cfg["credit"]:
            d.text((x, H * 0.958), cfg["credit"], font=self.F("sans", 40), fill=a(col["credit"]))
        out = im.convert("RGBA")
        out.alpha_composite(lay)
        return out

    def frame(self, t):
        cfg, col, k = self.cfg, self.cfg["colors"], self.k
        im = self.base.copy()
        d = ImageDraw.Draw(im)
        arrive = [cfg["first_pin"]] + [t1 for _, t1 in self.spans]
        prog = [ease((t - t0) / (t1 - t0)) for t0, t1 in self.spans]
        for L, p in zip(self.legs, prog):  # halo under every leg first, so crossings stay clean
            if p > 0:
                poly, _ = partial(L, p)
                if len(poly) > 1:
                    d.line(poly, fill=col["halo"], width=round(cfg["route_halo_width"] * k), joint="curve")
        hr = cfg["head_r"] * k
        for L, p in zip(self.legs, prog):
            if p <= 0:
                continue
            poly, e = partial(L, p)
            dashed_poly(d, poly, col["route"], round(cfg["route_width"] * k), cfg["dash"] * k, cfg["gap"] * k)
            if p < 1:
                d.ellipse([e[0] - hr, e[1] - hr, e[0] + hr, e[1] + hr], fill=col["route"], outline=col["halo"],
                          width=max(1, round(6 * k)))
        fl = cfg["flight"]
        if fl:
            t0, t1 = fl["span"]
            to = fl.get("to", [0.95, 0.30])
            end = self.proj(to["lat"], to["lon"]) if isinstance(to, dict) else (to[0] * self.W, to[1] * self.H)
            style = fl.get("style", "plane")
            color = tuple(fl.get("color", col["flight"] if style == "plane" else col["route"]))
            lxy = fl.get("label_offset")
            flight_arc(d, ease((t - t0) / (t1 - t0)), self.P[fl.get("from", -1)], end, lift=fl.get("lift", 380) * k,
                       color=color, width=round(14 * k), style=style, label=fl.get("label"),
                       label_font=self.F("heavy", cfg["flight_label_size"]),
                       label_xy=(end[0] + lxy[0] * k, end[1] + lxy[1] * k) if lxy else None,
                       label_anchor=fl.get("label_anchor", "rs"), halo=_halo(cfg, fl.get("halo", "land")), scale=k)
        fonts = (self.F("heavy", cfg["name_size"]), self.F("sans", cfg["sub_size"]), self.F("heavy", cfg["number_size"]))
        done = -1
        for i, (st, (x, y)) in enumerate(zip(cfg["stops"], self.P)):
            s = pop((t - arrive[i]) / cfg["pin_pop"])
            if t >= arrive[i] and s > 0.05:
                done = i
                pin(d, x, y, i + 1, st["cn"], st.get("sub", ""), st.get("side", "down"), s, fonts, col,
                    halo=_halo(cfg, st.get("halo", "land")), scale=k)
        if cfg["panel"]:
            im = self._panel(im, done)
        return im


def render_route(config, out=None, preview=None, verbose=True):
    """Render the route map mp4 (and a preview jpg of the last frame) from a config dict or JSON path.

    Example config (ep 96 look; sizes are 4K pixels and scale with "size"):
      {"osm": "../outside/osm_malibu.json",
       "bbox": [33.9, -118.86, 34.08, -118.36], "frame": [0.08, 0.30, 0.88, 1.0], "fit": "width",
       "align": [0.5, 0.0], "ref_lat": 34.0,
       "title": "南加州最后一天",
       "stops": [{"cn": "马里布海鲜", "sub": "午饭 · 下午 2:23", "lat": 34.03382, "lon": -118.73511, "side": "up"},
                 ...],
       "mode": "drive", "legs": [{"mode": "drive"}, {"mode": "walk", "via": [[lat, lon]]}, ...],
       "spans": [[0.3, 0.95], ...],
       "labels": [{"text": "太平洋", "lat": 33.935, "lon": -118.66, "size": 110, "color": [90, 130, 160], "halo": null}],
       "flight": {"span": [3.35, 4.35], "to": [0.95, 0.30], "label": "飞回纽约 EWR"},
       "panel": null, "colors": {"route": [200, 40, 30]}, "size": [3840, 2160], "dur": 5.0,
       "out": "route.mp4", "preview": "route_last_frame.jpg",
       "fetch": {"bbox": [...], "coast_bbox": [...], "kinds": ["major", "coast"]}}
    Returns (mp4 path, preview path)."""
    rm = RouteMap(config, verbose=verbose)
    cfg = rm.cfg
    out = os.path.abspath(out) if out else cfg["out"]
    preview = os.path.abspath(preview) if preview else cfg["preview"]
    frames_to_mp4(rm.frame, cfg["dur"], out, fps=cfg["fps"])
    if preview:
        os.makedirs(os.path.dirname(preview), exist_ok=True)
        rm.frame(cfg["dur"] - 0.05).convert("RGB").resize(tuple(cfg["preview_size"]), Image.LANCZOS).save(
            preview, quality=88)
    print("wrote", out, "and", preview)
    return out, preview


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m src.editor.routemap", description=__doc__.split("\n")[0])
    ap.add_argument("config", help="route_config.json")
    ap.add_argument("actions", nargs="*", help="fetch | legs | route (default: route)")
    ap.add_argument("--out", help="override the config's mp4 path")
    ap.add_argument("--preview", help="override the config's preview jpg path")
    a = ap.parse_args(argv)
    bad = [x for x in a.actions if x not in ("fetch", "legs", "route")]
    if bad:
        ap.error(f"unknown action(s): {', '.join(bad)}")
    for act in a.actions or ["route"]:
        if act == "fetch":
            fetch_config(a.config)
        elif act == "legs":
            RouteMap(a.config)
        else:
            render_route(a.config, out=a.out, preview=a.preview)
        print("ok", act)


if __name__ == "__main__":
    main(sys.argv[1:])
