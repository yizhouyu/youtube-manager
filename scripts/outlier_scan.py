#!/usr/bin/env python3
"""Outlier scan: which videos on reference channels beat their own channel's median by >= 3x.

Reads sessions/growth/reference_channels.txt (one channel URL or @handle per line, optional
"lang=zh-CN"), pulls each channel's last ~60 long videos with `yt-dlp --flat-playlist -J`
(no YouTube API quota), and writes:
  sessions/growth/outliers_<date>.md    per-channel outlier tables + cross-channel title patterns
  sessions/growth/outliers_<date>.json  same data, read by scripts/feed_sim.py

Thumbnails are linked (i.ytimg.com), never downloaded or embedded.

  scripts/outlier_scan.py                 # reference channels
  scripts/outlier_scan.py --ours          # + our own channel against our own median
  scripts/outlier_scan.py --ours-only     # only our channel
Options: --n 60 (videos per channel), --mult 3 (outlier threshold), --no-exact-dates.
Run it monthly (publish-video-chat Step 3).
"""
import argparse
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROWTH = os.path.join(ROOT, "sessions", "growth")
CHANNELS_FILE = os.path.join(GROWTH, "reference_channels.txt")
OURS = "@yizhou8888"
OURS_LANG = "zh-CN"
THUMB = "https://i.ytimg.com/vi/{}/hqdefault.jpg"


# ---------------------------------------------------------------- fetch

def channel_url(ref):
    ref = ref.strip().rstrip("/")
    if ref.startswith("@"):
        ref = "https://www.youtube.com/" + ref
    elif not ref.startswith("http"):
        ref = "https://www.youtube.com/@" + ref
    ref = re.sub(r"/(videos|shorts|streams|featured|playlists)$", "", ref)
    return ref


def read_channels(path):
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        lang = next((p.split("=", 1)[1] for p in parts[1:] if p.startswith("lang=")), None)
        out.append((parts[0], lang))
    return out


def ytdlp_json(url, n, extra):
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--no-warnings", "--playlist-end", str(n), *extra, url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError((p.stderr or "no output").strip().splitlines()[-1][:200])
    return json.loads(p.stdout)


def fetch_channel(ref, lang, n):
    """Views + approximate dates come from the default (English) pass; titles from `lang` if set."""
    url = channel_url(ref)
    d = ytdlp_json(url + "/videos", n, ["--extractor-args", "youtubetab:approximate_date"])
    titles = {}
    if lang:
        try:
            dl = ytdlp_json(url + "/videos", n, ["--extractor-args", f"youtube:lang={lang}"])
            titles = {e["id"]: e.get("title") for e in dl.get("entries") or [] if e.get("id")}
        except RuntimeError as e:
            print(f"  ! {ref}: {lang} titles failed ({e}); keeping default titles", file=sys.stderr)
    avatar = next((t["url"] for t in d.get("thumbnails") or []
                   if t.get("width") and t.get("width") == t.get("height")), None)
    if avatar:
        avatar = re.sub(r"=s\d+-", "=s88-", avatar)
    vids = []
    for e in d.get("entries") or []:
        if not e.get("id") or e.get("view_count") is None:
            continue  # upcoming / members-only / hidden counts
        ts = e.get("timestamp")
        vids.append({
            "id": e["id"],
            "title": titles.get(e["id"]) or e.get("title") or "",
            "views": int(e["view_count"]),
            "duration": e.get("duration"),
            "date": dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d") if ts else None,
            "date_exact": False,
            "thumb": THUMB.format(e["id"]),
        })
    return {
        "ref": ref, "url": url, "lang": lang,
        "name": d.get("channel") or d.get("uploader") or ref,
        "handle": d.get("uploader_id") or ref,
        "subs": d.get("channel_follower_count"),
        "avatar": avatar,
        "videos": vids,
    }


def exact_dates(videos):
    """Exact upload dates for a handful of videos (one yt-dlp call, no download)."""
    if not videos:
        return
    cmd = ["yt-dlp", "--skip-download", "--no-warnings", "--ignore-errors",
           "--print", "%(id)s %(upload_date)s",
           *[f"https://www.youtube.com/watch?v={v['id']}" for v in videos]]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60 + 8 * len(videos))
    except subprocess.TimeoutExpired:
        return
    got = dict(l.split(" ", 1) for l in p.stdout.splitlines() if " " in l)
    for v in videos:
        d = got.get(v["id"], "")
        if re.fullmatch(r"\d{8}", d):
            v["date"], v["date_exact"] = f"{d[:4]}-{d[4:6]}-{d[6:]}", True


def score(ch, mult):
    views = [v["views"] for v in ch["videos"]]
    med = statistics.median(views) if views else 0
    ch["median"] = med
    for v in ch["videos"]:
        v["mult"] = round(v["views"] / med, 2) if med else 0.0
        v["outlier"] = bool(med) and v["views"] >= mult * med
    return ch


# ---------------------------------------------------------------- title patterns

CJK = re.compile(r"[\u3400-\u9fff]")
# a lone 一 ("一个学生", "一座城") is an article, not a number; 一天/一晚/一周 still count
CN_NUM = re.compile(r"(?<!第)(?:[二两三四五六七八九十百千万几][一二两三四五六七八九十百千万几]*|[一][一二两三四五六七八九十百千万]+)\s*"
                    r"(天|日游|个|座|次|小时|分钟|年|岁|种|家|条|只|晚|夜|英里|公里|米|万|元|美元|刀|块|国|州|城|站)"
                    r"|(?<![第统唯])一(天|日游|晚|夜|周|小时)")
EN_NUM = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|twelve|hundred|thousand|million)\b", re.I)
QUESTION = re.compile(r"[?？]|为什么|怎么|值得吗|值不值|是什么|多少钱|有多|吗(?=$|[\s｜|，,！!。])|呢(?=$|[\s｜|，,！!。])")
CLAIM = re.compile(r"第一次|首次|头一回|人生第一|第一座|唯一|只有|仅有|全网|史上|最(?![近后终初])"
                   r"|\b(first|only|most|least|best|worst|biggest|largest|smallest|highest|deepest|oldest"
                   r"|cheapest|craziest|never|ever)\b", re.I)
EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u203C]")
TAG_FIRST = re.compile(r"^\s*[【\[（(]")
SEP = re.compile(r"[：:｜|—–,，!！?？【】\[\]()（）]| - ")

PLACES_ZH = """
美国 美國 加州 纽约 紐約 夏威夷 阿拉斯加 德州 佛州 佛罗里达 拉斯维加斯 洛杉矶 洛杉磯 旧金山 舊金山 西雅图 芝加哥 波士顿 华盛顿
费城 迈阿密 奥兰多 圣地亚哥 聖地牙哥 圣地牙哥 黄石 黃石 优胜美地 锡安 布莱斯 大峡谷 死亡谷 大提顿 冰川 落基山 犹他 亚利桑那 科罗拉多 新墨西哥
蒙大拿 怀俄明 内华达 俄勒冈 华盛顿州 奥斯汀 达拉斯 休斯顿 圣安东尼奥 新奥尔良 纳什维尔 丹佛 波特兰 檀香山 欧胡岛 茂宜岛 大岛 可爱岛
墨西哥 墨西哥城 坎昆 加拿大 温哥华 溫哥華 多伦多 蒙特利尔 魁北克 班夫 古巴 秘鲁 巴西 阿根廷 智利 冰岛 挪威 瑞士 法国 法國 巴黎 意大利 义大利 罗马
西班牙 巴塞罗那 葡萄牙 英国 伦敦 倫敦 德国 希腊 土耳其 埃及 摩洛哥 日本 东京 東京 大阪 京都 北海道 冲绳 沖繩 韩国 韓國 首尔 首爾 台湾 台灣 台北
香港 澳门 泰国 泰國 曼谷 普吉 越南 胡志明 河内 新加坡 马来西亚 印尼 峇里岛 巴厘岛 菲律宾 澳洲 澳大利亚 悉尼 新西兰 紐西蘭 新西蘭 大溪地 帕劳
中国 北京 上海 西安 成都 重庆 广州 深圳 杭州 云南 新疆 西藏 伊朗 印度 尼泊尔 蒙古 俄罗斯 迪拜 以色列 约旦
""".split()
PLACES_EN = sorted([p.strip() for p in """
USA, America, Hawaii, Alaska, Texas, Florida, California, New York, NYC, Las Vegas, Los Angeles, San
Francisco, Seattle, Chicago, Boston, Miami, Orlando, San Diego, Yellowstone, Yosemite, Zion, Bryce, Grand
Canyon, Death Valley, Utah, Arizona, Colorado, New Mexico, Austin, Dallas, Houston, San Antonio, Denver,
Portland, Honolulu, Oahu, Maui, Kauai, Kona, Mexico, Mexico City, Cancun, Canada, Vancouver, Toronto, Banff,
Cuba, Peru, Brazil, Argentina, Chile, Iceland, Norway, Switzerland, France, Paris, Italy, Rome, Spain,
Barcelona, Portugal, England, London, Germany, Greece, Turkey, Egypt, Morocco, Japan, Tokyo, Osaka, Kyoto,
Okinawa, Korea, Seoul, Taiwan, Taipei, Hong Kong, Thailand, Bangkok, Phuket, Vietnam, Saigon, Hanoi,
Singapore, Malaysia, Indonesia, Bali, Philippines, Australia, Sydney, New Zealand, Tahiti, Moorea, Palau,
China, Beijing, Shanghai, Iran, India, Nepal, Mongolia, Russia, Dubai, Israel, Jordan, Caribbean, Dominica,
Bahamas, Exuma, Maratua, Lombok
""".replace("\n", " ").split(",")], key=len, reverse=True)
PLACE_SUFFIX = re.compile(r"(国家公园|國家公園|公园|岛|島|州|市|县|镇|村|城|山|湖|河|谷|峡谷|海滩|沙滩|湾|街|大学|博物馆|瀑布|冰川|小镇|古城"
                          r"|National Park|Island|Islands|City|Beach|Bay|Canyon|Lake|Valley|Mountains?|Park|Town|Village"
                          r"|County|Coast|Falls|Glacier)$")


def opener(title):
    """'tag' (series tag like 【EP12】 first), 'place' (place name first), or 'hook'."""
    t = title.strip()
    if TAG_FIRST.match(t):
        return "tag"
    first = SEP.split(t, 1)[0].strip()
    short = len(first) <= 12 if CJK.search(first) else len(first.split()) <= 4
    if any(t.startswith(p) for p in PLACES_ZH):
        return "place"
    if any(re.match(re.escape(p) + r"\b", t) for p in PLACES_EN):
        return "place"
    if short and not CLAIM.search(first) and PLACE_SUFFIX.search(re.sub(r"['’]s$", "", first)):
        return "place"
    return "hook"


def features(title):
    zh = len(CJK.findall(title)) >= 3
    return {
        "zh": zh,
        "number": bool(re.search(r"\d", title) or CN_NUM.search(title) or EN_NUM.search(title)),
        "question": bool(QUESTION.search(title)),
        "claim": bool(CLAIM.search(title)),
        "emoji": bool(EMOJI.search(title)),
        "opener": opener(title),
        "length": len(title),
    }


PATTERNS = [
    ("number", "Has a number (digits, 3天, two…)"),
    ("question", "Is a question (?, 吗, 为什么, 值得吗…)"),
    ("claim", "First-time / only / most claim (第一次, 唯一, 最…, first, only, best…)"),
    ("emoji", "Contains an emoji"),
    ("opener:place", "Place name first"),
    ("opener:hook", "Hook first (not a place, not a series tag)"),
    ("opener:tag", "Series tag first (【EP12】, [Vlog]…)"),
]


def has(f, key):
    if key.startswith("opener:"):
        return f["opener"] == key.split(":", 1)[1]
    return f[key]


def pattern_table(videos, channels=None):
    """Rows: pattern | outliers zh | others zh | outliers en | others en [| channels where outliers use it more].

    Pooled shares let one channel with many outliers dominate, so with `channels` an extra column
    counts, per channel (>= 2 outliers), whether its outliers use the pattern more or less than its other videos."""
    groups = {}
    for v in videos:
        f = features(v["title"])
        groups.setdefault(("zh" if f["zh"] else "en", v["outlier"]), []).append(f)
    cols = [("zh", True), ("zh", False), ("en", True), ("en", False)]

    def cell(key, col):
        fs = groups.get(col, [])
        if not fs:
            return "–"
        k = sum(has(f, key) for f in fs)
        return f"{round(100 * k / len(fs))}% ({k}/{len(fs)})"

    def med_len(col):
        fs = groups.get(col, [])
        return str(int(statistics.median(f["length"] for f in fs))) if fs else "–"

    def per_channel(test):
        more = less = same = 0
        for ch in channels:
            o = [features(v["title"]) for v in ch["videos"] if v["outlier"]]
            r = [features(v["title"]) for v in ch["videos"] if not v["outlier"]]
            if len(o) < 2 or len(r) < 5:
                continue
            a, b = test(o), test(r)
            more, less, same = more + (a > b + 0.05), less + (a < b - 0.05), same + (abs(a - b) <= 0.05)
        return f"{more} more · {less} less · {same} same"

    head = ["Pattern", "Outliers, Chinese titles", "Others, Chinese titles", "Outliers, English titles", "Others, English titles"]
    if channels:
        head.append("Per channel: outliers vs others")
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for key, label in PATTERNS:
        extra = [per_channel(lambda fs, k=key: sum(has(f, k) for f in fs) / len(fs))] if channels else []
        lines.append(f"| {label} | " + " | ".join([cell(key, c) for c in cols] + extra) + " |")
    extra = [per_channel(lambda fs: statistics.median(f["length"] for f in fs) / 100)] if channels else []
    lines.append("| Median title length (characters) | " + " | ".join([med_len(c) for c in cols] + extra) + " |")
    return "\n".join(lines), groups


# ---------------------------------------------------------------- report

def esc(s):
    return s.replace("|", "\\|").replace("\n", " ")


def fmt_n(n):
    return f"{n:,}" if isinstance(n, int) else (f"{int(n):,}" if n else "?")


def age_days(v):
    try:
        return (dt.date.today() - dt.date.fromisoformat(v["date"])).days
    except (TypeError, ValueError):
        return 999


def d_str(v):
    return (v["date"] or "?") + ("" if v["date_exact"] else " ~")


def channel_section(ch, mult, ours=False):
    outs = sorted((v for v in ch["videos"] if v["outlier"]), key=lambda v: -v["mult"])
    dates = [v["date"] for v in ch["videos"] if v["date"]]
    span = f"{min(dates)} to {max(dates)}" if dates else "dates unknown"
    lines = [f"### {ch['name']} ({ch['handle']})" + (" — our channel" if ours else ""),
             f"{ch['url']} · {fmt_n(ch['subs'])} subs · {len(ch['videos'])} long videos ({span}) · "
             f"median {fmt_n(ch['median'])} views · {len(outs)} at ≥{mult:g}×", ""]
    if outs:
        lines += ["| Title | Views | × median | Uploaded | Thumbnail |", "|---|---:|---:|---|---|"]
        for v in outs:
            date = d_str(v)
            lines.append(f"| [{esc(v['title'])}](https://www.youtube.com/watch?v={v['id']}) | {fmt_n(v['views'])} | "
                         f"{v['mult']:.1f}× | {date} | [hqdefault]({v['thumb']}) |")
    else:
        lines.append(f"No video at ≥{mult:g}× the median.")
    if ours:
        near = sorted((v for v in ch["videos"] if not v["outlier"] and v["mult"] >= 2), key=lambda v: -v["mult"])
        if near:
            lines += ["", f"Near-outliers (2–{mult:g}×):", ""]
            lines += [f"- {v['mult']:.1f}× · {fmt_n(v['views'])} · {d_str(v)} · {esc(v['title'])}" for v in near]
        low = sorted((v for v in ch["videos"] if age_days(v) >= 14), key=lambda v: v["mult"])[:5]
        lines += ["", "Lowest 5 (× median, videos at least 14 days old):", ""]
        lines += [f"- {v['mult']:.2f}× · {fmt_n(v['views'])} · {d_str(v)} · {esc(v['title'])}" for v in low]
    return "\n".join(lines)


def write_report(refs, ours, failed, mult, n, out_md):
    today = dt.date.today().isoformat()
    L = [f"# Outlier scan, {today}", "",
         f"Made by `scripts/outlier_scan.py` (yt-dlp `--flat-playlist`, no API quota). Each channel's last ~{n} long "
         f"videos (the /videos tab, so no Shorts or lives); an **outlier** is a video with ≥{mult:g}× that channel's median views.",
         "Dates marked `~` are yt-dlp's approximate dates (from \"3 weeks ago\" text); the rest are exact. "
         "Thumbnails are links only. Older videos have had longer to collect views, so a channel's oldest videos "
         "are slightly favoured.", ""]
    if failed:
        L += ["Failed (skipped): " + ", ".join(f"`{r}` ({e})" for r, e in failed), ""]
    if refs:
        allv = [v for ch in refs for v in ch["videos"]]
        outs = [dict(v, channel=ch["name"]) for ch in refs for v in ch["videos"] if v["outlier"]]
        table, _ = pattern_table(allv, refs)
        L += ["## Cross-channel title patterns (reference channels)", "",
              f"{len(refs)} channels, {len(allv)} videos, {len(outs)} outliers. Each cell: share of titles with the pattern. "
              "The last column counts channels (with ≥2 outliers) whose outliers use the pattern more / less than "
              "their other videos (±5 points = same), so one prolific channel can't dominate. "
              "Pattern detection is regex-based (see `features()` in the script), so treat small differences as noise.", "",
              table, "",
              "### Top 15 outliers across channels", "",
              "| × median | Views | Channel | Title | Opener |", "|---:|---:|---|---|---|"]
        for v in sorted(outs, key=lambda v: -v["mult"])[:15]:
            L.append(f"| {v['mult']:.1f}× | {fmt_n(v['views'])} | {esc(v['channel'])} | {esc(v['title'])} | {features(v['title'])['opener']} |")
        L += ["", "## Per channel", ""]
        for ch in sorted(refs, key=lambda c: c["subs"] or 0):
            L += [channel_section(ch, mult), ""]
    if ours:
        table, _ = pattern_table(ours["videos"])
        L += ["## Our channel against our own median (`--ours`)", "", channel_section(ours, mult, ours=True), "",
              "Title patterns, our outliers vs our other videos:", "", table, ""]
    L += [f"Last updated: {today}"]
    open(out_md, "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--channels", default=CHANNELS_FILE)
    ap.add_argument("--n", type=int, default=60, help="videos per channel (default 60)")
    ap.add_argument("--mult", type=float, default=3.0, help="outlier threshold, × channel median (default 3)")
    ap.add_argument("--ours", action="store_true", help=f"also scan our channel ({OURS})")
    ap.add_argument("--ours-only", action="store_true", help="scan only our channel")
    ap.add_argument("--no-exact-dates", action="store_true", help="skip the per-outlier exact upload-date lookup")
    ap.add_argument("--out", help="output .md path (default sessions/growth/outliers_<date>.md)")
    a = ap.parse_args()

    os.makedirs(GROWTH, exist_ok=True)
    today = dt.date.today().isoformat()
    out_md = a.out or os.path.join(GROWTH, f"outliers_{today}{'_ours' if a.ours_only else ''}.md")
    refs, failed, ours = [], [], None
    todo = [] if a.ours_only else read_channels(a.channels)
    for ref, lang in todo:
        print(f"· {ref}", file=sys.stderr)
        try:
            refs.append(score(fetch_channel(ref, lang, a.n), a.mult))
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            print(f"  ! {ref}: {e}", file=sys.stderr)
            failed.append((ref, str(e)[:80]))
    if a.ours or a.ours_only:
        print(f"· {OURS} (ours)", file=sys.stderr)
        ours = score(fetch_channel(OURS, OURS_LANG, a.n), a.mult)
    if not a.no_exact_dates:
        for ch in refs + ([ours] if ours else []):
            exact_dates([v for v in ch["videos"] if v["outlier"]])

    write_report(refs, ours, failed, a.mult, a.n, out_md)
    data = {"date": today, "mult": a.mult, "n": a.n, "channels": refs, "ours": ours, "failed": failed}
    out_json = os.path.splitext(out_md)[0] + ".json"
    json.dump(data, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for ch in refs + ([ours] if ours else []):
        k = sum(v["outlier"] for v in ch["videos"])
        print(f"  {ch['name'][:28]:28} median {fmt_n(ch['median']):>10}  outliers {k}", file=sys.stderr)
    print(out_md)


if __name__ == "__main__":
    main()
