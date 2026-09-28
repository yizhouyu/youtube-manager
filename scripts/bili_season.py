#!/usr/bin/env python3
"""Put Bilibili videos into a 合集 (UGC season), creating it if needed.

    ./venv/bin/python scripts/bili_season.py --list
    ./venv/bin/python scripts/bili_season.py --season "阿拉斯加" --desc "一句话介绍" BV1xxx [BV1yyy ...]

Uses biliup's login file (default ~/.config/biliup/cookies.json) against the creative-center
web API; cookies are never printed. A new season takes the newest video's cover. Episodes are
added in publish order. A video can belong to only one 合集 on Bilibili.
"""
import argparse
import json
import os
import time

import requests

API = "https://member.bilibili.com/x2/creative/web"


def session(cookie_file):
    c = json.load(open(os.path.expanduser(cookie_file)))
    ck = {x["name"]: x["value"] for x in c["cookie_info"]["cookies"]}
    s = requests.Session()
    s.cookies.update(ck)
    s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                      "Referer": "https://member.bilibili.com/platform/upload-manager/ugc-season",
                      "Origin": "https://member.bilibili.com"})
    return s, ck["bili_jct"]


def _ok(r, what):
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"{what}: {j.get('code')} {j.get('message')}")
    return j.get("data")


def seasons(s):
    d = _ok(s.get(f"{API}/seasons", params={"pn": 1, "ps": 50}), "list seasons")
    return {x["season"]["title"]: x["season"]["id"] for x in (d.get("seasons") or [])}


def video(s, bvid):
    j = s.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid}).json()
    if j.get("code") == 0:
        d = j["data"]
        return {"aid": d["aid"], "cid": d["cid"], "title": d["title"], "pic": d["pic"], "pubdate": d["pubdate"]}
    # Scheduled / still-in-审核 videos 404 on the public API; the creator-center view has them.
    d = _ok(s.get("https://member.bilibili.com/x/vupre/web/archive/view", params={"bvid": bvid}),
            f"creator view {bvid}")
    a = d["archive"]
    return {"aid": a["aid"], "cid": d["videos"][0]["cid"], "title": a["title"], "pic": a["cover"],
            "pubdate": a.get("dtime") or a.get("ptime") or int(time.time())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bvids", nargs="*")
    ap.add_argument("--season")
    ap.add_argument("--desc", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--cookies", default="~/.config/biliup/cookies.json")
    a = ap.parse_args()
    s, csrf = session(a.cookies)
    have = seasons(s)
    if a.list or not a.season:
        for t, i in have.items():
            print(i, t)
        return
    vids = sorted((video(s, b) for b in a.bvids), key=lambda v: v["pubdate"])
    sid = have.get(a.season)
    if not sid:
        sid = _ok(s.post(f"{API}/season/add", data={"title": a.season, "desc": a.desc or a.season,
                                                    "cover": vids[-1]["pic"], "season_price": 0, "csrf": csrf}),
                  "create season")
        time.sleep(1.5)
    d = _ok(s.get(f"{API}/season", params={"id": sid}), "season detail")
    section = d["sections"]["sections"][0]["id"]
    eps = [{"title": v["title"], "cid": v["cid"], "aid": v["aid"], "charging_pay": 0,
            "member_first": 0, "limited_free": False} for v in vids]
    _ok(s.post(f"{API}/season/section/episodes/add", params={"csrf": csrf},
               json={"sectionId": section, "episodes": eps, "csrf": csrf}), "add episodes")
    print(f"{a.season} ({sid}): added {len(eps)}")


if __name__ == "__main__":
    main()
