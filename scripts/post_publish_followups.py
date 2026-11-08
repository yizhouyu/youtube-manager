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
    if a[:1] == ["--alerts"]:
        found = alerts(svc)
        print("\n".join(found) if found else "no alerts")
        return 0
    if a[:1] == ["--due"]:
        # run the automation on publish days, and on any day with a new alert
        return 0 if tasks or new_alerts(svc) else 1
    print(json.dumps(tasks, ensure_ascii=False, indent=1))
    return 0


ALERTS = ROOT / "sessions" / "ALERTS.md"


def alerts(svc):
    """Exception-only checks (2026-11-08): a new long video far above/below the channel median at 48 h,
    and viewer comments on recent long videos with no reply from the channel. About 15 quota units."""
    import datetime as dt
    import statistics
    ch = svc.channels().list(part="id,contentDetails", mine=True).execute()["items"][0]
    me, up = ch["id"], ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = [i["contentDetails"]["videoId"] for i in svc.playlistItems().list(
        part="contentDetails", playlistId=up, maxResults=50).execute()["items"]]
    vids = svc.videos().list(part="snippet,statistics,contentDetails,status", id=",".join(ids)).execute()["items"]
    now = dt.datetime.now(dt.timezone.utc)

    def age_h(v):
        return (now - dt.datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))).total_seconds() / 3600

    longs = [v for v in vids if v["status"]["privacyStatus"] == "public"
             and "M" in v["contentDetails"]["duration"] and not v["contentDetails"]["duration"].startswith("PT0M")]
    out = []
    older = [int(v["statistics"].get("viewCount", 0)) for v in longs if age_h(v) > 168]
    med = statistics.median(older) if older else 0
    for v in longs:
        h, views = age_h(v), int(v["statistics"].get("viewCount", 0))
        if 40 <= h <= 72 and med:
            if views >= 2 * med:
                out.append(f"🔥 {v['snippet']['title'][:30]} — {views} views at {h:.0f} h (channel median {med:.0f}): double down (Shorts, community post)")
            elif views <= 0.5 * med:
                out.append(f"⚠️ {v['snippet']['title'][:30]} — {views} views at {h:.0f} h (median {med:.0f}): check cover/title")
    for v in sorted(longs, key=age_h)[:10]:
        try:
            th = svc.commentThreads().list(part="snippet,replies", videoId=v["id"], maxResults=50).execute()["items"]
        except Exception:
            continue
        for t in th:
            top = t["snippet"]["topLevelComment"]["snippet"]
            if top.get("authorChannelId", {}).get("value") == me:
                continue
            replied = any(r["snippet"].get("authorChannelId", {}).get("value") == me
                          for r in (t.get("replies") or {}).get("comments", []))
            if not replied:
                out.append(f"💬 unanswered on {v['snippet']['title'][:24]}: 「{top['textOriginal'][:60]}」 https://www.youtube.com/watch?v={v['id']}&lc={t['id']}")
    return out


def new_alerts(svc):
    """True when alerts() finds something not already listed in sessions/ALERTS.md (written by the automation)."""
    seen = ALERTS.read_text() if ALERTS.exists() else ""
    return any(x[:80] not in seen for x in alerts(svc))


if __name__ == "__main__":
    sys.exit(main())
