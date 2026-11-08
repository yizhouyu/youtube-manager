#!/usr/bin/env python3
"""Publish audit for one episode (or all Desktop projects): one ✓/✗ line per item, then a drive-ready verdict.
Retro 2026-11-08 #4: after the Codex uploads, 120 was missing captions + English title and nobody noticed.
Run it after every upload chain (whichever agent ran it) and before moving a project to the drive; fix every ✗.

Usage:
  venv/bin/python scripts/episode_audit.py 120                 # episode number → ~/Desktop/120 - *
  venv/bin/python scripts/episode_audit.py "~/Desktop/120 - X" # or a project dir
  venv/bin/python scripts/episode_audit.py --all               # every ~/Desktop/NNN - * with a youtube_ids.json
  add --json for machine output. Exit 0 only when every audited episode is READY FOR DRIVE.

Sources (all read-only): <proj>/02 - Export/edit/publish_prep/youtube_ids.json, sessions/upload_chains/epNNNpub/config.json
(series + Shorts playlist ids), sessions/FOLLOWUPS.json (pinned / Shorts Related video — browser-only, not in the API),
and YouTube Data API list calls: videos, captions (50 units each), playlistItems (videoId filter), commentThreads,
channels(mine). No search.list, no writes.

Status marks: ✓ done · ✗ missing/wrong · … pending (waits on the long going public) · ? unknown (not visible via API/state)
Only all-✓ gives READY FOR DRIVE."""
import contextlib, datetime as dt, glob, json, os, re, sys, warnings
from zoneinfo import ZoneInfo
warnings.filterwarnings("ignore")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
DESKTOP = os.path.expanduser("~/Desktop")
CHAINS = os.path.join(REPO, "sessions", "upload_chains")
FOLLOWUPS = os.path.join(REPO, "sessions", "FOLLOWUPS.json")
SHORTS_PL_NAME = "短视频 | Shorts"
ET, BJ = ZoneInfo("America/New_York"), ZoneInfo("Asia/Shanghai")
OK, BAD, PEND, UNK = "✓", "✗", "…", "?"

_svc, _chan, _pl_by_name = None, None, None
QUOTA = {"hit": False}
QUOTA_MSG = "API quota exhausted — re-run after 03:00 ET"


def is_quota(e):
    """403 quotaExceeded / dailyLimitExceeded / rateLimitExceeded from googleapiclient.HttpError."""
    status = getattr(getattr(e, "resp", None), "status", None)
    text = (getattr(e, "content", b"") or b"")
    text = text.decode("utf-8", "replace") if isinstance(text, bytes) else str(text)
    return status in (403, 429) and bool(re.search(r"quotaExceeded|dailyLimitExceeded|rateLimitExceeded", text + str(e)))


def svc():
    global _svc
    if _svc is None:
        from src.auth.youtube_auth import YouTubeAuthenticator
        with contextlib.redirect_stdout(sys.stderr):  # keep --json clean ("Refreshing expired credentials...")
            _svc = YouTubeAuthenticator().get_youtube_service()
    return _svc


def channel_id():
    global _chan
    if _chan is None:
        _chan = svc().channels().list(part="id", mine=True).execute()["items"][0]["id"]
    return _chan


def playlist_by_name(name):
    global _pl_by_name
    if _pl_by_name is None:
        _pl_by_name, tok = {}, None
        while True:
            r = svc().playlists().list(part="snippet", mine=True, maxResults=50, pageToken=tok).execute()
            _pl_by_name.update({p["snippet"]["title"]: p["id"] for p in r["items"]})
            tok = r.get("nextPageToken")
            if not tok:
                break
    return _pl_by_name.get(name)


def in_playlist(pl, vid):
    r = svc().playlistItems().list(part="id", playlistId=pl, videoId=vid, maxResults=1).execute()
    return bool(r.get("items"))


def et(iso):
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return t.astimezone(ET).strftime("%m-%d %H:%M ET")


def resolve(arg):
    p = os.path.expanduser(arg)
    if os.path.isdir(p):
        return os.path.abspath(p)
    if re.fullmatch(r"\d{1,3}", arg):
        hits = sorted(glob.glob(os.path.join(DESKTOP, f"{int(arg):03d} - *")))
        if hits:
            return hits[0]
    sys.exit(f"找不到项目: {arg}")


def load_json(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None


def audit(proj):
    name = os.path.basename(proj)
    ep = name[:3]
    edit = os.path.join(proj, "02 - Export", "edit")
    ids = load_json(os.path.join(edit, "publish_prep", "youtube_ids.json")) or {}
    cfg = load_json(os.path.join(CHAINS, f"ep{ep}pub", "config.json")) or {}
    if not cfg.get("playlist"):  # pre-config chains (≤119) hard-code it: PLAYLIST = "PL…"   # 夏威夷 | Hawaii (…)
        try:
            src = open(os.path.join(CHAINS, f"ep{ep}pub", "upload_long.py"), encoding="utf-8").read()
            m = re.search(r'^PLAYLIST\s*=\s*"(PL[\w-]+)"\s*(?:#\s*([^(\n]*))?', src, re.M)
            if m:
                cfg = dict(cfg, playlist=m.group(1), playlist_name=(m.group(2) or m.group(1)).strip())
        except OSError:
            pass
    fu = next((it for it in (load_json(FOLLOWUPS) or {}).get("items", []) if str(it.get("ep")) == ep), None)
    rows = []

    def add(key, label, status, detail=""):
        rows.append({"key": key, "label": label, "status": status, "detail": detail})

    def api_part():
        long = ids.get("long")
        skeys = [k for k in ids.get("shorts_keys", []) if ids.get(k)]
        shorts = [ids[k] for k in skeys]
        vids = {}
        if long or shorts:
            r = svc().videos().list(part="snippet,status,contentDetails,localizations", id=",".join([long] + shorts if long else shorts)).execute()
            vids = {v["id"]: v for v in r["items"]}
        lv = vids.get(long)
        public = bool(lv and lv["status"]["privacyStatus"] == "public")

        # --- long video
        if not long:
            plan = ids.get("long_at_plan")
            add("long", "长视频", BAD, "ids 里还没有 long id（上传中？）" + (f" 计划 {et(plan)}" if plan else ""))
        elif not lv:
            add("long", "长视频", BAD, f"{long} 在 YouTube 上找不到")
        else:
            st, cd = lv["status"], lv["contentDetails"]
            processed = st.get("uploadStatus") == "processed" and cd.get("duration") not in (None, "P0D")
            priv, at = st["privacyStatus"], st.get("publishAt")
            if not processed:
                add("long", "长视频", BAD, f"{long} 未处理完 ({st.get('uploadStatus')}, {cd.get('duration')})")
            elif priv == "public":
                add("long", "长视频", OK, f"{long} public")
            elif priv == "private" and at:
                mism = f"，但 ids long_at={ids.get('long_at')}" if ids.get("long_at") and ids["long_at"] != at else ""
                add("long", "长视频", BAD if mism else OK, f"{long} scheduled publishAt {at} ({et(at)}){mism}")
            else:
                add("long", "长视频", BAD, f"{long} {priv}，没有 publishAt")

        if lv:
            th = lv["snippet"].get("thumbnails", {})
            add("thumb", "自定义封面", OK if ("maxres" in th or "standard" in th) else BAD,
                "" if ("maxres" in th or "standard" in th) else "API 只有默认尺寸")
            caps = svc().captions().list(part="snippet", videoId=long).execute()["items"]
            langs = {c["snippet"]["language"] for c in caps if c["snippet"].get("trackKind") != "asr"}
            zh = bool(langs & {"zh-CN", "zh-Hans", "zh"})
            add("captions", "字幕 zh-CN + en", OK if zh and "en" in langs else BAD, ", ".join(sorted(langs)) or "无字幕轨")
            en = (lv.get("localizations") or {}).get("en") or {}
            miss = [f for f in ("title", "description") if not (en.get(f) or "").strip()]
            add("loc_en", "英文本地化", BAD if miss else OK, ("缺 " + "/".join(miss)) if miss else en["title"][:60])
            pl = cfg.get("playlist")
            if pl:
                add("playlist", "系列播放列表", OK if in_playlist(pl, long) else BAD, cfg.get("playlist_name", pl))
            else:
                add("playlist", "系列播放列表", UNK, f"ep{ep}pub 里没有系列播放列表 id，不知道是哪个系列")
        else:
            for k, lab in (("thumb", "自定义封面"), ("captions", "字幕 zh-CN + en"), ("loc_en", "英文本地化"), ("playlist", "系列播放列表")):
                add(k, lab, BAD, "长视频还没上传")

        # --- Shorts
        found = [s for s in shorts if s in vids]
        add("shorts", "2 条 Shorts", OK if len(found) == 2 else BAD,
            ", ".join(found) if found else "ids 里没有 Shorts")
        spl = cfg.get("shorts_playlist") or (playlist_by_name(SHORTS_PL_NAME) if found else None)
        if found and spl:
            inpl = [s for s in found if in_playlist(spl, s)]
            add("shorts_pl", f"Shorts 在「{SHORTS_PL_NAME}」", OK if len(inpl) == len(found) == 2 else BAD, f"{len(inpl)}/{len(found)}")
        else:
            add("shorts_pl", f"Shorts 在「{SHORTS_PL_NAME}」", BAD, "没有 Shorts" if not found else "找不到 Shorts 播放列表")
        if found and long:
            linked = [s for s in found if long in vids[s]["snippet"].get("description", "")]
            add("shorts_link", "Shorts 简介链接长视频", OK if len(linked) == len(found) == 2 else BAD, f"{len(linked)}/{len(found)}")
        else:
            add("shorts_link", "Shorts 简介链接长视频", BAD, "没有 Shorts 或长视频")

        # Shorts "Related video" — Studio only; FOLLOWUPS.json tracks it
        if not found:
            add("related", "Shorts 相关视频", BAD, "没有 Shorts")
        elif fu is None:
            add("related", "Shorts 相关视频", UNK, "FOLLOWUPS.json 没有这一期（浏览器才看得到）")
        else:
            done = [s for s in found if s in (fu.get("related_done") or [])]
            if len(done) == len(found) == 2:
                add("related", "Shorts 相关视频", OK, "2/2 (FOLLOWUPS)")
            elif not public:
                add("related", "Shorts 相关视频", PEND, f"pending (long not public yet) {len(done)}/{len(found)}")
            else:
                add("related", "Shorts 相关视频", BAD, f"{len(done)}/{len(found)} (FOLLOWUPS)")

        # --- channel comment on the long + pinned
        if not lv:
            add("comment", "频道评论", BAD, "长视频还没上传")
            add("pinned", "评论置顶", BAD, "长视频还没上传")
        else:
            mine, err = None, None
            try:
                r = svc().commentThreads().list(part="snippet", videoId=long, maxResults=100, textFormat="plainText").execute()
                for t in r.get("items", []):
                    a = t["snippet"]["topLevelComment"]["snippet"].get("authorChannelId", {}).get("value")
                    if a == channel_id():
                        mine = t["id"]
                        break
            except Exception as e:  # comments on a private/scheduled video can 403
                err = getattr(getattr(e, "resp", None), "status", None) or type(e).__name__
            if mine:
                add("comment", "频道评论", OK, mine)
            elif not public:
                add("comment", "频道评论", PEND, "pending (long not public yet)")
            else:
                add("comment", "频道评论", BAD, f"没有频道自己的顶层评论{f' (API {err})' if err else ''}")
            if fu and fu.get("pinned"):
                add("pinned", "评论置顶", OK, "FOLLOWUPS pinned")
            elif not public:
                add("pinned", "评论置顶", PEND, "pending (long not public yet)")
            elif fu:
                add("pinned", "评论置顶", BAD, "FOLLOWUPS pinned=false")
            else:
                add("pinned", "评论置顶", UNK, "unknown (browser)")

    if QUOTA["hit"]:
        add("api", QUOTA_MSG, BAD)
    else:
        try:
            api_part()
        except Exception as e:
            if not is_quota(e):
                raise
            QUOTA["hit"] = True  # no retries: every later episode skips the API too
            add("api", QUOTA_MSG, BAD)

    # --- B站
    bv, dtime = ids.get("bili"), ids.get("bili_dtime")
    if bv and dtime:
        t = dt.datetime.fromtimestamp(int(dtime), BJ).strftime("%m-%d %H:%M 北京")
        add("bili", "B站 BV + dtime", OK, f"{bv} dtime {t}")
    else:
        add("bili", "B站 BV + dtime", BAD, f"bili={bv or '-'} dtime={dtime or '-'}")
    add("bili_season", "B站 合集", OK if ids.get("bili_season") else BAD, ids.get("bili_season") or "未记录")

    # --- local
    left = [p for p in ("preview.mp4", "previews") if os.path.lexists(os.path.join(edit, p))]
    add("preview", "预览已删", BAD if left else OK, ("还在: " + ", ".join(left)) if left else "")
    sha = ids.get("master_sha256")
    add("master_sha", "母版 sha256", OK if sha else BAD, (sha[:12] + "…") if sha else "ids 里没有 master_sha256")

    notdone = [r["label"] for r in rows if r["status"] != OK]
    return {"ep": ep, "project": proj, "ready": not notdone, "items": rows,
            "verdict": "READY FOR DRIVE" if not notdone else "NOT DONE: " + ", ".join(notdone)}


def main():
    a = sys.argv[1:]
    as_json = "--json" in a
    args = [x for x in a if not x.startswith("--")]
    if "--all" in a:
        projs = [p for p in sorted(glob.glob(os.path.join(DESKTOP, "*")))
                 if re.match(r"^\d{3} - ", os.path.basename(p)) and os.path.isfile(os.path.join(p, "02 - Export", "edit", "publish_prep", "youtube_ids.json"))]
    elif args:
        projs = [resolve(x) for x in args]
    else:
        sys.exit(__doc__)
    res = [audit(p) for p in projs]
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for i, r in enumerate(res):
            if i:
                print()
            print(f"== {os.path.basename(r['project'])}")
            for it in r["items"]:
                print(f" {it['status']} {it['label']}" + (f" — {it['detail']}" if it["detail"] else ""))
            print(r["verdict"])
    return 0 if res and all(r["ready"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
