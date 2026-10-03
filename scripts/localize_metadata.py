#!/usr/bin/env python
"""Add localized (translated) titles/descriptions to existing YouTube videos.

Viewers whose YouTube UI is in that language see the localized metadata; everyone
else keeps seeing the default-language title and description. The video's own
title, description, tags, category, privacy and schedule are left untouched.

Usage:
    python scripts/localize_metadata.py <drafts.json> [--lang en] [--default-lang zh-CN]
                                        [--before before.json] [--apply]

drafts.json maps video id -> {"title": ..., "description": ...}.

Without --apply it is a dry run: it reads every video, checks the drafts
(title <= 100 chars, description <= 5000, no '<' or '>', chapter timestamps
identical to the default description) and prints what it would write.
With --apply it writes each video once (videos.update, ~50 quota units each),
then re-reads all videos and checks the default-language snippet is unchanged.

--before saves the full pre-update snippet + localizations of every video, for restoring.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.auth.youtube_auth import YouTubeAuthenticator  # noqa: E402

SNIPPET_FIELDS = ("title", "description", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")
TIMESTAMP = re.compile(r"^(\d{1,2}:\d{2}(?::\d{2})?) ", re.M)


def fetch(svc, ids):
    items = {}
    for i in range(0, len(ids), 50):
        r = svc.videos().list(part="snippet,localizations,status", id=",".join(ids[i:i + 50])).execute()
        items.update({it["id"]: it for it in r.get("items", [])})
    return items


def check_draft(vid, draft, snippet):
    problems = []
    if not draft.get("title") or len(draft["title"]) > 100:
        problems.append(f"title length {len(draft.get('title') or '')}")
    if len(draft.get("description", "")) > 5000:
        problems.append(f"description length {len(draft['description'])}")
    if any(c in draft["title"] + draft.get("description", "") for c in "<>"):
        problems.append("contains < or >")
    orig_ts = TIMESTAMP.findall(snippet.get("description", ""))
    new_ts = TIMESTAMP.findall(draft.get("description", ""))
    if orig_ts != new_ts:
        problems.append(f"chapter timestamps differ: {orig_ts} vs {new_ts}")
    return problems


def build_body(item, lang, draft, default_lang):
    s = item["snippet"]
    snippet = {k: s[k] for k in SNIPPET_FIELDS if k in s}
    if not snippet.get("defaultLanguage"):
        snippet["defaultLanguage"] = default_lang
    locs = dict(item.get("localizations", {}))
    locs[lang] = {"title": draft["title"], "description": draft["description"]}
    return {"id": item["id"], "snippet": snippet, "localizations": locs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("drafts")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--default-lang", default="zh-CN", help="set only when the video has no defaultLanguage")
    ap.add_argument("--before", help="save pre-update state here (skipped if the file exists)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    drafts = json.load(open(a.drafts, encoding="utf-8"))
    ids = list(drafts)
    svc = YouTubeAuthenticator().get_youtube_service()
    before = fetch(svc, ids)
    missing = [v for v in ids if v not in before]
    if missing:
        sys.exit(f"videos not found: {missing}")

    if a.before and not os.path.exists(a.before):
        json.dump({v: {"snippet": before[v]["snippet"], "localizations": before[v].get("localizations", {}),
                       "status": before[v]["status"]} for v in ids},
                  open(a.before, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("saved before-state to", a.before)

    bad = {v: p for v in ids if (p := check_draft(v, drafts[v], before[v]["snippet"]))}
    if bad:
        for v, p in bad.items():
            print("DRAFT PROBLEM", v, "; ".join(p))
        sys.exit(1)

    if not a.apply:
        for v in ids:
            print(f"[dry run] {v}  {drafts[v]['title']}")
        return

    written, failed = [], {}
    for v in ids:
        body = build_body(before[v], a.lang, drafts[v], a.default_lang)
        try:
            svc.videos().update(part="snippet,localizations", body=body).execute()
            written.append(v)
            print("updated", v)
        except Exception as e:  # one attempt per video; report and move on
            failed[v] = str(e)[:300]
            print("FAILED", v, failed[v])

    after = fetch(svc, written)
    for v in written:
        b, n = before[v]["snippet"], after[v]["snippet"]
        diffs = [k for k in ("title", "description", "tags", "categoryId", "defaultAudioLanguage")
                 if b.get(k) != n.get(k)]
        loc = after[v].get("localizations", {}).get(a.lang)
        ok_loc = loc == {"title": drafts[v]["title"], "description": drafts[v]["description"]}
        status_same = before[v]["status"].get("privacyStatus") == after[v]["status"].get("privacyStatus") and \
            before[v]["status"].get("publishAt") == after[v]["status"].get("publishAt")
        print(f"verify {v}: localization {'OK' if ok_loc else 'MISMATCH'}; "
              f"default snippet {'unchanged' if not diffs else 'CHANGED ' + str(diffs)}; "
              f"privacy/schedule {'unchanged' if status_same else 'CHANGED'}")
    print(f"\n{len(written)} updated, {len(failed)} failed; quota ~{50 * (len(written) + len(failed)) + 2 * ((len(ids) + 49) // 50)} units")


if __name__ == "__main__":
    main()
