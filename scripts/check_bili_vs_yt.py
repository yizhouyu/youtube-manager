"""Compare the channel's YouTube long videos with the B站 submissions and list YouTube videos with no B站 match.
Usage: venv/bin/python scripts/check_bili_vs_yt.py [--since 2025-06-01]
- YouTube: search.list(forMine) — the uploads playlist silently misses some videos (2026-10-22: 8 missing, incl. 102/113–115).
- B站: `biliup list` (cookies are never printed). Matching is fuzzy (title+description bigrams); check '<-- ?' rows by eye —
  B站 titles are often rewritten, so a low score is a prompt to look, not proof that something is missing."""
import json, os, re, subprocess, sys, warnings
warnings.filterwarnings("ignore"); sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.auth.youtube_auth import YouTubeAuthenticator

since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else "2025-06-01"
yt = YouTubeAuthenticator().get_youtube_service()
ids, tok = set(), None
while True:
    r = yt.search().list(part="id", forMine=True, type="video", maxResults=50, pageToken=tok).execute()
    ids |= {i["id"]["videoId"] for i in r["items"]}; tok = r.get("nextPageToken")
    if not tok: break
ids, vids = sorted(ids), []
for i in range(0, len(ids), 50):
    vids += yt.videos().list(part="snippet,status,contentDetails", id=",".join(ids[i:i + 50])).execute()["items"]
def secs(x):
    h, m, s = [int(g or 0) for g in re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", x).groups()]; return h * 3600 + m * 60 + s
longs = sorted((v for v in vids if secs(v["contentDetails"]["duration"]) > 60), key=lambda v: v["snippet"]["publishedAt"])

raw = subprocess.run([os.path.expanduser("~/.local/bin/biliup"), "-u", os.path.expanduser("~/.config/biliup/cookies.json"), "list"],
                     capture_output=True, text=True).stdout
raw = re.sub(r"\x1b\[[0-9;]*m", "", raw); B, cur = [], None
for line in raw.splitlines():
    if line.startswith("BV"): p = line.split("\t"); cur = [p[0], p[1], " ".join(p[2:])]; B.append(cur)
    elif cur: cur[2] += " " + line
def grams(s):
    s = re.sub(r"\s+", "", s); return {s[i:i + 2] for i in range(len(s) - 1)} | {w.lower() for w in re.findall(r"[A-Za-z]{3,}", s)}
BB = [(b[0], b[1], grams(b[1] + b[2][:300])) for b in B]
print(f"YouTube long videos: {len(longs)} · B站 submissions: {len(B)} · since {since}")
for v in longs:
    sn = v["snippet"]
    if sn["publishedAt"][:10] < since: continue
    g = grams(sn["title"] + sn["description"][:200]); best = max(BB, key=lambda b: len(g & b[2])); sc = len(g & best[2])
    at = v["status"].get("publishAt", "")[:10]
    print(f"{sn['publishedAt'][:10]} {v['status']['privacyStatus'][:4]} {at:10} {sn['title'][:34]} | {best[0]} {best[1][:24]} {sc}{'  <-- ?' if sc < 15 else ''}")
