"""Swap the cover of one scheduled Bilibili archive, keeping every other field.

usage: bili_cover.py BVID COVER.jpg [--go]   (without --go: dry run, prints payload; no upload)
"""
import base64
import os
import json
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bili_season import session, _ok  # noqa: E402

bvid, cover_path = sys.argv[1], sys.argv[2]
go = "--go" in sys.argv
s, csrf = session("~/.config/biliup/cookies.json")
s.headers["Referer"] = "https://member.bilibili.com/platform/upload/video/frame"

view = _ok(s.get("https://member.bilibili.com/x/vupre/web/archive/view", params={"bvid": bvid}), "view")
a = view["archive"]

if go:
    b64 = base64.b64encode(open(cover_path, "rb").read()).decode()
    up = _ok(s.post("https://member.bilibili.com/x/vu/web/cover/up",
                    data={"cover": "data:image/jpeg;base64," + b64, "csrf": csrf}), "cover/up")
    new_cover = up["url"]
    print("uploaded cover:", new_cover)
else:
    new_cover = "<to be uploaded: %s>" % cover_path

payload = {
    "aid": a["aid"],
    "copyright": a["copyright"],
    "source": a["source"],
    "tid": a["tid"],
    "cover": new_cover,
    "cover43": a.get("cover43") or "",
    "title": a["title"],
    "desc_format_id": a["desc_format_id"],
    "desc": a["desc"],
    "dynamic": a["dynamic"],
    "tag": a["tag"],
    "dtime": a["dtime"],
    "no_reprint": a["no_reprint"],
    "interactive": a["interactive"],
    "mission_id": a["mission_id"],
    "topic_id": a["topic_id"],
    "is_360": a["is_360"],
    "dolby": a["is_dolby"],
    "lossless_music": a["lossless_music"],
    "neutral_mark": a["neutral_mark"],
    "no_disturbance": view["no_disturbance"],
    "act_reserve_create": 1 if view["act_reserve_create"] else 0,
    "up_selection_reply": bool(view["reply"]["up_selection"]),
    "up_close_reply": view["reply"]["state"] != 0,
    "subtitle": {"open": 1 if view["subtitle"]["allow"] else 0, "lan": view["subtitle"]["lan"]},
    "videos": [{"filename": v["filename"], "title": v["title"], "desc": v["desc"], "cid": v["cid"]}
               for v in view["videos"]],
    "csrf": csrf,
}

show = {k: v for k, v in payload.items() if k != "csrf"}
print(json.dumps(show, ensure_ascii=False, indent=1))
print("old cover:", a["cover"])

if not go:
    sys.exit(0)

r = s.post("https://member.bilibili.com/x/vu/web/edit", params={"t": int(time.time() * 1000), "csrf": csrf},
           json=payload)
print("edit ->", r.status_code, json.dumps(r.json(), ensure_ascii=False)[:500])
_ok(r, "edit")
time.sleep(3)
v2 = _ok(s.get("https://member.bilibili.com/x/vupre/web/archive/view", params={"bvid": bvid}), "view after")
a2 = v2["archive"]
checks = {
    "cover changed": a2["cover"] != a["cover"],
    "cover == uploaded": a2["cover"].split("/")[-1] == new_cover.split("/")[-1],
    "dtime same": a2["dtime"] == a["dtime"],
    "title same": a2["title"] == a["title"],
    "desc same": a2["desc"] == a["desc"],
    "tag same": a2["tag"] == a["tag"],
    "tid same": a2["tid"] == a["tid"],
    "videos same": [(x["cid"], x["title"]) for x in v2["videos"]] == [(x["cid"], x["title"]) for x in view["videos"]],
    "in_season": v2["in_season"],
}
print("after: cover", a2["cover"], "dtime", a2["dtime"], "state", a2["state"], a2["state_desc"])
for k, ok in checks.items():
    print(("OK  " if ok else "FAIL"), k)
