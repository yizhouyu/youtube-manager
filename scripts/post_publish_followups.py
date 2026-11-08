#!/usr/bin/env python3
"""Post-publish follow-ups for scheduled long videos.

Once a scheduled long video goes public, three things still need doing:
  1. post the channel's pinned-comment question (API),
  2. pin it (browser only: watch page ⋮ → Pin),
  3. set each of its Shorts' "Related video" to the long (browser only: Studio).

State lives in sessions/FOLLOWUPS.json:
  {"items": [{"ep": "118", "long": "<id>", "pin_text": "...", "shorts": ["<id>", ...],
              "comment": null, "pinned": false, "related_done": []}]}
"long" may be "ids:<path to youtube_ids.json>" (resolved to its "long" key, Shorts from "shorts_keys").

Usage:
  scripts/post_publish_followups.py --due      exit 0 if a public long has pending work, else 1 (Orca precheck)
  scripts/post_publish_followups.py --post     post missing comments on public longs, print pending browser tasks
  scripts/post_publish_followups.py --tasks    print pending browser tasks as JSON (no writes)
  scripts/post_publish_followups.py --mark <long> pinned
  scripts/post_publish_followups.py --mark <long> related <short>
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STATE = ROOT / "sessions" / "FOLLOWUPS.json"


def load():
    return json.loads(STATE.read_text())


def save(d):
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1))


def resolve(item):
    """Fill long / shorts from a youtube_ids.json reference once the chain has recorded them."""
    if str(item.get("long", "")).startswith("ids:"):
        p = Path(item["long"][4:])
        if p.exists():
            ids = json.loads(p.read_text())
            if ids.get("long"):
                item["long"] = ids["long"]
                if not item.get("shorts"):
                    item["shorts"] = [ids[k] for k in ids.get("shorts_keys", []) if ids.get(k)]
    return item


def yt():
    from src.auth.youtube_auth import YouTubeAuthenticator
    return YouTubeAuthenticator().get_youtube_service()


def public_set(svc, ids):
    ids = [i for i in ids if i and not i.startswith("ids:")]
    out = set()
    for i in range(0, len(ids), 50):
        for v in svc.videos().list(part="status", id=",".join(ids[i:i + 50])).execute()["items"]:
            if v["status"]["privacyStatus"] == "public":
                out.add(v["id"])
    return out


def pending(d, pub):
    tasks = []
    for it in d["items"]:
        if it["long"] not in pub:
            continue
        if not it.get("comment"):
            tasks.append({"ep": it["ep"], "long": it["long"], "do": "post_comment"})
        elif not it.get("pinned"):
            tasks.append({"ep": it["ep"], "long": it["long"], "do": "pin", "comment": it["comment"],
                          "text": it["pin_text"],
                          "url": f"https://www.youtube.com/watch?v={it['long']}&lc={it['comment']}"})
        for s in it.get("shorts", []):
            if s not in it.get("related_done", []):
                tasks.append({"ep": it["ep"], "long": it["long"], "do": "related", "short": s,
                              "url": f"https://studio.youtube.com/video/{s}/edit"})
    return tasks


def main():
    a = sys.argv[1:]
    d = load()
    d["items"] = [resolve(it) for it in d["items"]]
    save(d)
    if a[:1] == ["--mark"]:
        long, what = a[1], a[2]
        for it in d["items"]:
            if it["long"] == long:
                if what == "pinned":
                    it["pinned"] = True
                elif what == "related":
                    it.setdefault("related_done", []).append(a[3])
        save(d)
        return 0
    svc = yt()
    pub = public_set(svc, [it["long"] for it in d["items"]])
    if a[:1] == ["--post"]:
        ch = svc.channels().list(part="id", mine=True).execute()["items"][0]["id"]
        for it in d["items"]:
            if it["long"] in pub and not it.get("comment"):
                r = svc.commentThreads().insert(part="snippet", body={"snippet": {
                    "channelId": ch, "videoId": it["long"],
                    "topLevelComment": {"snippet": {"textOriginal": it["pin_text"]}}}}).execute()
                it["comment"] = r["id"]
                save(d)
                print(f"posted comment on {it['ep']} {it['long']}")
    tasks = pending(d, pub)
    if a[:1] == ["--due"]:
        return 0 if tasks else 1
    print(json.dumps(tasks, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
