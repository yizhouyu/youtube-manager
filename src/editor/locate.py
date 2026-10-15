"""Map a review note's time to the same moment in another preview (creator, 2026-10-15: click 「成片 0:59.7」 in the
chat and land on that moment in the NEW preview, even after the cut changed).

Every preview render writes `edit/previews/meta/<preview>.json`: the shot list it was cut from (id, clip, kept
source ranges, speed, start on the timeline, length). A note made on the cut page is anchored to (shot id, source
second) in the preview that was playing; it is then placed on the target preview by the same shot (or the same
clip, or its nearest surviving neighbour). Raw-page notes (clip + clip time) are placed the same way.
Older previews have no meta: their cut is rebuilt from `edit/history/` (the first EDL backup taken after the
render) or, failing that, the current EDL.
"""
import glob
import json
import os
import re
import time

from . import edl as E

NAME_RX = re.compile(r"preview-(\d{8}-\d{6})\.mp4")


def snapshot(edl):
    """[{id, clip, kept, speed, t0, dur}] for the enabled shots, timeline order."""
    out, t = [], 0.0
    for s in E.active_shots(edl):
        d = s.get("_qdur", E.shot_dur(s))
        out.append({"id": s.get("id"), "clip": s.get("clip") or "", "kept": [list(r) for r in E.kept_ranges(s)],
                    "speed": E.speed(s), "t0": round(t, 4), "dur": round(d, 4)})
        t += d
    return out


def write_meta(edit, name, shots):
    d = os.path.join(edit, "previews", "meta")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name.replace(".mp4", ".json")), "w", encoding="utf-8") as f:
        json.dump({"shots": snapshot({"shots": shots})}, f, ensure_ascii=False)
    keep = {f.replace(".mp4", ".json") for f in os.listdir(os.path.join(edit, "previews")) if NAME_RX.fullmatch(f)}
    for f in os.listdir(d):
        if f.endswith(".json") and f not in keep:
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass


def _ts(name):
    m = NAME_RX.fullmatch(name or "")
    return time.mktime(time.strptime(m.group(1), "%Y%m%d-%H%M%S")) if m else None


def previews(edit):
    d = os.path.join(edit, "previews")
    return sorted(f for f in os.listdir(d) if NAME_RX.fullmatch(f)) if os.path.isdir(d) else []


def preview_at(edit, msg_ts):
    """The preview that was newest when a note was written ('YYYY-MM-DD HH:MM:SS')."""
    names = previews(edit)
    try:
        t = time.mktime(time.strptime(msg_ts, "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError):
        return names[-1] if names else None
    before = [n for n in names if _ts(n) <= t]
    return before[-1] if before else (names[0] if names else None)


def shots_for(project, name):
    edit = E.edit_dir(project)
    if name:
        p = os.path.join(edit, "previews", "meta", name.replace(".mp4", ".json"))
        if os.path.isfile(p):
            return json.load(open(p, encoding="utf-8"))["shots"]
        t = _ts(name)
        if t:   # older preview: the first EDL backup made after it holds the cut it was rendered from
            later = sorted((os.path.getmtime(h), h) for h in glob.glob(os.path.join(edit, "history", "edl.*.json"))
                           if os.path.getmtime(h) >= t)
            if later:
                try:
                    return snapshot(json.load(open(later[0][1], encoding="utf-8")))
                except (OSError, ValueError):
                    pass
    return snapshot(E.load(project))


def _src_at(s, off):
    """Seconds into a snapshot shot -> source-clip second."""
    acc = 0.0
    for a, b in s["kept"]:
        L = (b - a) / s["speed"]
        if off <= acc + L or (a, b) == tuple(s["kept"][-1]):
            return a + min(max(off - acc, 0.0), L) * s["speed"]
        acc += L
    return s["kept"][0][0] if s["kept"] else 0.0


def _t_of(s, src):
    """Source second -> timeline second inside snapshot shot `s` (a skipped second snaps to the next kept one)."""
    acc = 0.0
    for a, b in s["kept"]:
        if src < a:
            return s["t0"] + acc
        if src <= b:
            return s["t0"] + acc + (src - a) / s["speed"]
        acc += (b - a) / s["speed"]
    return s["t0"] + max(0.0, s["dur"] - 0.3)


def anchor(shots, cut_t):
    for i, s in enumerate(shots):
        if cut_t < s["t0"] + s["dur"] or i == len(shots) - 1:
            off = max(0.0, cut_t - s["t0"])
            return {"id": s["id"], "clip": s["clip"], "src": _src_at(s, off) if s["clip"] else off,
                    "order": [x["id"] for x in shots], "card": not s["clip"]}
    return None


def place(shots, a):
    """Timeline second for anchor `a` in `shots`, plus how it was found."""
    by_id = {s["id"]: s for s in shots}
    s = by_id.get(a.get("id"))
    if s and (a.get("card") or s["clip"] == a.get("clip")):
        if a.get("card") or not s["clip"]:
            return min(s["t0"] + a["src"], s["t0"] + s["dur"]), "same"
        if s["kept"][0][0] - 1.0 <= a["src"] <= s["kept"][-1][1] + 1.0:
            return _t_of(s, a["src"]), "same"
    if a.get("clip"):   # the same source moment, wherever it lives now
        for s in shots:
            if s["clip"] == a["clip"] and any(x - 0.05 <= a["src"] <= y + 0.05 for x, y in s["kept"]):
                return _t_of(s, a["src"]), "same"
        near = [s for s in shots if s["clip"] == a["clip"]]
        if near:
            s = min(near, key=lambda s: min(abs(a["src"] - x) + abs(a["src"] - y) for x, y in s["kept"]))
            return _t_of(s, a["src"]), "near"
    order = a.get("order") or []
    if a.get("id") in order:   # the shot is gone: the next surviving shot after it
        for sid in order[order.index(a["id"]) + 1:]:
            if sid in by_id:
                return by_id[sid]["t0"], "gone"
    return None, "missing"


def locate(project, msg, target=None):
    """{t, how, preview} for a chat message on the cut page's `target` preview (default: newest)."""
    edit = E.edit_dir(project)
    ctx = msg.get("ctx") or {}
    target = target or (previews(edit) or [None])[-1]
    new = shots_for(project, target)
    if ctx.get("clip"):
        a = {"clip": ctx["clip"], "src": float(ctx.get("clip_t") or 0)}
    elif ctx.get("cut_t") is not None:
        src = ctx.get("preview") or preview_at(edit, msg.get("ts"))
        a = anchor(shots_for(project, src), float(ctx["cut_t"]))
        if a is None:
            return {"t": None, "how": "missing", "preview": target}
        if src == target:
            return {"t": float(ctx["cut_t"]), "how": "same", "preview": target, "clip": a.get("clip"), "clip_t": a["src"]}
    else:
        return {"t": None, "how": "missing", "preview": target}
    t, how = place(new, a)
    return {"t": None if t is None else round(t, 2), "how": how, "preview": target,
            "clip": a.get("clip") or None, "clip_t": round(a["src"], 2) if a.get("clip") else None}
