---
name: publish-video-chat
description: Publish a finished video to YouTube by just talking to Claude — no web UI (except a thin review page), no SRT required. You (the agent) pre-process the export, watch it via multi-pass frame extraction, design the thumbnail natively, write SEO metadata in the channel's own established style, run sub-agent critics, get one human review, then upload (video + captions + chapters). Generic: point it at any channel and it learns that channel's voice. Use when a creator points at a finished export and wants it published conversationally.
---

# Publish Video (conversational, agent-first)

The "just talk to me" publish flow. **You** (this Claude Code session) are the generator,
the thumbnail designer, AND the QA. You pre-process the export, watch it, design the
thumbnail by looking at frames, write metadata in the channel's voice, critique your own
work with sub-agents, show the human ONE review page, then drive the upload.

**Operating model.** The agent owns the decisions; the human reviews **once** before
publish and gives notes; the human's corrections feed a persistent memory so packaging
**personalizes over time** (see "Self-evolving loop"). Default to acting, not asking —
except where this skill says to confirm (privacy, ambiguous place names).

This skill is **generic**: it adapts to whatever channel it's pointed at by learning that
channel's style. The running example below is a Chinese-first bilingual travel channel —
treat that as *the example*, not a hard requirement.

Resolve the repo root as two levels up from this file:
`REPO="$(cd "$(dirname SKILL.md)/../.." && pwd)"`. Run everything from `$REPO`.

## Prerequisites

- **ffmpeg / ffprobe** on PATH. This build typically has **no `drawtext`** filter — build
  contact sheets **without text labels** and track frame order by filename/folder instead.
- **whisper.cpp** (`whisper-cli`) + a `ggml` model under `$REPO/models/` (for transcript & captions).
- **`./venv/bin/python`** with project deps (`googleapiclient`, `Pillow`, …).
- **`config/token.pickle`** present (YouTube OAuth done; auto-refreshes). For **captions** the
  token needs the **`youtube.force-ssl`** scope — in this setup it already has it. If a caption
  insert fails with an insufficient-scope error, delete `token.pickle` and re-auth once.
- **`npx`** (Node) for **lavish-axi**, the thin HTML review tool (the only "UI" in the loop).

## Folder convention

```
NN - Place Name/
├── 01 - Unedited/        # raw clips — IGNORE. Never read, never touch.
└── 02 - Export/
    ├── NN - Place Name.mov   # the finished cut (often 4K)
    └── thumbnail/            # deliverables get saved HERE
```

- Always work from `02 - Export/`. **Never read `01 - Unedited/`.**
- **Deliverables** live in `02 - Export/`: base image, final thumbnail, `metadata_final.txt`,
  cleaned `captions.srt`, `proposals.md`.
- **Scratch** (extracted frames, contact sheets, raw transcript copies) goes to **`/tmp`** to
  keep project folders clean. The exception is the pre-process artifacts the script writes
  into `02 - Export/` (audio/transcript/scan); those are fine to leave.

## Step 1 — Pre-process (and QA the export)

Run the reusable pre-processor so later review is instant:

```bash
scripts/preprocess_video.sh "NN - Place Name"
```

It finds the export, extracts mono 16k audio, transcribes it (whisper, Chinese) to
`transcript.txt`, and lays a coarse 12-frame contact sheet (`thumbnail/_scan.jpg`). Idempotent.

**This doubles as a QA pass — do it before anything else:**
- `Read thumbnail/_scan.jpg`. If most sampled frames are **dark / "Media Not Found"
  placeholders**, the export is **broken** → ask the human to re-export; do not proceed.
- **Verify the export's CONTENT matches the folder**: duration looks right (`ffprobe`) and a
  glance at the frames is the place the folder names. A mismatched/stale export is common.
- **NEVER delete or rename an export until you've verified it's the correct, intact file.**

## Step 2 — Understand before writing

Read the **transcript** AND look at frames — packaging is only as good as your understanding.
Treat the transcription as the **single upstream artifact**: it feeds captions, chapters, the
description hook, tags, and a **proper-noun glossary**.

- From transcript + frames, build a glossary of every place / restaurant / landmark name.
  Keep a **persistent channel-level vocab** of recurring names (hosts, signature spots, brands)
  and merge it into each video's glossary so spellings stay consistent across the channel.
- **Web-search any uncertain proper noun** to get the correct spelling (ASR mangles mixed-in
  English names). Confirm genuinely ambiguous ones with the human in a short Q&A — this is the
  authoritative glossary for metadata AND caption cleanup.
- Map the timeline (which place at which timestamp) — you'll reuse it for chapters.

## Step 3 — Design the thumbnail (by looking)

**What the creator actually picks (88–94, 2026-09-29):** a calm, iconic *hero photo that says the
place* (the dunes at sunset, the carrier, the UFO welcome sign, the cove, the sunset tide pools), or
the most *unusual close-up* of the day (the teddy-bear cholla on a shoe beat a generic Joshua tree);
a big place name or 2-line title in clean large type in empty sky; and **1–2 white-bordered tilted
photo cards** (a circle inset with a pointer line is fine). Restraint wins: hero + ≤2 extras, no
clutter. The art director's top pick lost 3 of 7 times, always to the option with the more
distinctive hero or fewer elements — weight those. Never offer equal strips/grids again (not even
as "old" comparison options), and use his face only in a clearly flattering frame.

**Local review pages get a favicon (creator, 2026-09-29):** every HTML page made for the creator
(thumbnail `review.html`, Shorts compare pages, …) includes a clean favicon so its tab is
recognisable: `from src.editor.favicon import link` → put `link("thumb")` (or "short"/"cut"/"raw")
in `<head>`, plus a `<title>` with the episode number and name.

**Options + art director loop (creator, 2026-09-28):**
- Make several options: single-image variants plus a collage for multi-place episodes.
- Then spawn an independent **art-director** sub-agent. It looks at every option at full size and at mobile size, compares it with the channel's best performers, and returns concrete critiques and suggestions.
- Revise and re-show it, and iterate until the art director signs off.
- Record the final pick and the art director's notes in `thumbnail/THUMBNAILS.md`.

**Style by episode type (creator, from 86 on):** if the episode covers several distinct places, the **main** option is a multi-place thumbnail with one short calm line. If it's essentially one place, use a single big image. Always offer both kinds so he can pick.

**Multi-place = layered, never equal strips (creator, 2026-09-28: "三个并排放很不好。应该有一点层次，或者叠上去").** Build it with `src/thumbnail_generator/layered.py`:
- Structure: one dominant hero image (the strongest place, or his normal smile with a subject) fills the frame. One or two other places sit on top of it.
- Ways to layer them:
  - tilted white-bordered photo cards with shadows and small place tags;
  - a ringed circle inset;
  - rembg cut-outs, with a white outline or graded into the scene and given a contact shadow;
  - a big place word set *behind* the hero's subject (the `subject` layer).
- Keep all layers in one colour world.
- Limits:
  - At most 2 insets. Drop any place that is too small to read at 168 px (e.g. a distant landmark) and put it in the title instead.
  - Keep the cut-out's real base/ground so scale still reads.
  - Clean distractions with `clean()` clone boxes, not blur.
- If the creator prefers a single image, the best layered option is usually that image plus one card.
- Never offer equal side-by-side strips (2-up or 3-up) again, not even as an alternative (creator, 2026-09-29: "太丑").
- If the thumbnail uses the creator's face, it must be a flattering frame: natural smile, eyes open, not mid-word, good light, no lens flare, no odd angle. The art director checks this explicitly. If no such frame exists, use a scene-based layout.
- Pattern research and reasons: `sessions/thumbs/research/PATTERNS.md` (local).

**Multi-pass frame extraction** (scratch → `/tmp`):
1. **Coarse** — the 12-frame `_scan.jpg` from Step 1 gives the whole arc.
2. **Dense** — pick the hot windows (best landmarks, faces, golden hour) and re-extract every
   ~1s into per-window folders, one contact sheet each (glob a per-window folder; `tile` sorts
   glob input alphabetically so order stays sane).
3. **Full-res finalists** — pull the 3–5 best at `-q:v 1`, `Read` each, **reject motion blur**.
   Source is usually 4K so quality is not the constraint.

**Choosing the frame:**
- Prefer **face + landmark** (expressive faces lift CTR ~20–30%), but the subject's **eyes
  must be open**, and **do NOT single-cover one person's mouth** with an emoji/pill/title block
  — it looks weird and conspicuous. Pick a **relaxed-mouth** frame, or fall back to a striking
  **no-face landmark** shot.
- The frame must instantly say *which place* this is; calm area (sky/water) for text room.
- **Keep frames real — do NOT switch to AI image generation.** A genuine frame beats synthetic
  "AI slop" for a real channel.

**Render the title text onto the frame** with the shared Pillow compositor (crops to
1280×720, stroked outline). Text: **≤4 words**, big (≥~70px tall), **high contrast** vs the
exact pixels behind it (e.g. yellow-on-dark), top-left safe zone, clear of the duration stamp.

```bash
./venv/bin/python - <<'PY'
import sys; sys.path.insert(0,'.')
from src.thumbnail_generator.compositor import render_option
render_option("<abs base.jpg>",
    {"main_text":"震撼故宫","subtitle":"必看攻略","text_color":"#FFD700",
     "outline_color":"#000000","position":"top","font_size_main":130},
    "<abs 02 - Export/thumbnail/thumbnail.jpg>")
PY
```

**Polish the look — poster style (`src/thumbnail_generator/polish.py`).** Don't ship a bare
frame. Prefer **`polish.render_poster(base, out, lines, tag=…, promise=…, position=…)`** — the
lizheng-style cover: grades the base (saturation/contrast/warmth/unsharp + **vignette**), then
sets a **big heavy-weight title** (bundled `assets/fonts/heavy.otf` = Noto Sans SC Black) as
1–2 lines where **yellow carries the punchy keyword and white the rest**, plus an optional
**top tag** (小黑标签, e.g. `阿拉斯加 Katmai`) and a **bottom promise strip** (黄条 one-line
content promise). `position` (`upper`/`center`/`lower`) is chosen to clear the subject/face.
Title and promise must not restate each other; the title creates the click, the promise says
why it's worth it. (`polish.render(...)` is the simpler single-line variant.) (Tier B, optional: `mediapipe` selfie-segmentation to blur/darken the background
behind a person. See `docs/thumbnail-polish-playbook.md`.)

**Deterministic layout protocol.** Don't eyeball-nudge forever — reason in bounding boxes.
Mark the `face`, `main_title`, `secondary_text` rectangles; **text (incl. its stroke/shadow)
must NOT intersect any face box, and never cover eyes/mouth/key expression.** Use only
localized backing that hugs the text (a small rounded plate at ≤~70% black) — never a full-
width black bar across the frame, never a glassy card. Colors: high-contrast yellow / white /
black, heavy sans, every big word stroked. Title ≤ ~12 chars; title and the on-image hook must
not restate each other.

**Mobile self-audit (mandatory).** After compositing, downscale the rendered thumbnail to
~10% (~168×94) — and also eyeball it at ~25% — `Read` it, and **reject** if the face/text isn't
instantly legible or any text touches a face. Iterate before the human sees it.

**Always have a sub-agent look at the rendered thumbnail before the human does.** Spawn a
vision sub-agent that FAILs the image if any glyph/stroke/shadow touches the subject's
face/eyes/mouth or the hero object, or if text is illegible / runs off-frame; it returns a
concrete fix (new `position`/`align`). Re-render and re-check until it passes. (For tricky
placement, first ask a sub-agent where the subject sits and which region is empty, then render
into that region.) This caught a title printed across the David statue and across a bear — the
first poster pass *looked* fine to me; the reviewer caught it. Produce **2–3 variants by design** (e.g. face-hero vs
landmark-hero, or different hook) so they're ready to drop into YouTube's native Test & Compare.

**Export per platform (always, for the chosen design).** YouTube and Bilibili want different
aspects, so every final thumbnail becomes two files via `src/thumbnail_generator/export.py`:
```bash
./venv/bin/python -c "import sys; sys.path.insert(0,'.'); from src.thumbnail_generator.export import export_for_platforms as e; print(e('<abs thumbnail.jpg>', '<abs 02 - Export/thumbnail>', 'thumbnail'))"
```
→ `thumbnail_youtube.jpg` (1280×720, JPEG stepped down to ≤1.9 MB) and `thumbnail_bilibili.jpg`
(1280×800 16:10, ≤4.8 MB; default `bilibili_mode="pad"` extends top/bottom with a blurred edge so
no text is cropped; `"crop"` centre-crops the sides instead). Specs (checked 2026-09):
| | YouTube | Bilibili 封面 |
|---|---|---|
| Aspect / size | 16:9; min width 640 (up to 3840×2160 accepted) | **16:10**; recommended ≥1146×717, min 960×600 |
| Max file | **2 MB via mobile app**; 50 MB desktop Studio & Data API | 5 MB |
| Formats | JPG, PNG | JPEG, PNG |

Sources: [YouTube Help 72431](https://support.google.com/youtube/answer/72431),
[Data API thumbnails.set](https://developers.google.com/youtube/v3/docs/thumbnails/set), Bilibili
Open Platform 封面上传 spec (mirrored at [bilibili.apifox.cn](https://bilibili.apifox.cn/api-23705555);
the official help center has no public cover page). Third-party/creator guides only: some B站 feeds
show a **4:3 centre crop** and every card overlays duration (bottom-right) and play/弹幕 counts
(bottom-left) — so keep the title inside the central 4:3 zone and off the bottom ~15% corners.

## Step 4 — Metadata in the channel's OWN style

**Learn the channel first — don't invent a voice.** Pull recent uploads and read the patterns
(title formats, tag mix, description skeleton, hashtag count). This is what makes the skill
generic: it adapts to whatever channel it's pointed at. Also pull the channel's
**top-performing titles** (sort by `viewCount`) and benchmark new titles against what actually
*won* on this channel, not just what's recent.

```bash
./venv/bin/python - <<'PY'
import sys; sys.path.insert(0, '.')
from src.auth.youtube_auth import YouTubeAuthenticator
from src.youtube_client.client import YouTubeClient
import json
svc = YouTubeAuthenticator().get_youtube_service()
vids = YouTubeClient(svc).get_all_channel_videos()
vids.sort(key=lambda v: v.get('publishedAt',''), reverse=True)
for v in vids[:15]:
    print(json.dumps({'title':v['title'],'tags':v.get('tags',[]),
                      'desc':(v.get('description','') or '')[:240]}, ensure_ascii=False))
PY
```

Reuse what you see. **Example channel** (Chinese-first bilingual travel) patterns:
- **Titles** — Chinese-first; a curiosity hook (`…有多震撼?` / `…值得吗?`) or a
  `[地点]+攻略/一日游+完整版/必看` guide format, English proper nouns kept inline. Power words:
  攻略, 完整版, 必看, 震撼, 实拍, 深度.
- **Tags** — ~12, mixed Chinese + English, proper nouns first then generic.
- **Description** — first line 3–5 hashtags, then a hook, a `你好！欢迎…` intro, then a 📍
  route list with 1️⃣2️⃣ markers. Preserve music credits / links. Note if it continues a series.

**Goal = max discoverability.** Draft **3 options** (engaging / informative / curiosity), each
with `title`, bilingual `description` (Chinese with keywords up front, `---`, then English),
`tags` (8–12 mixed), `hashtags` (3–5). Keep the title hook and the thumbnail text **distinct**
(curiosity gap), not repetitive. Write the working draft to `02 - Export/proposals.md`.

## Step 5 — Critique with sub-agents

Before the human sees anything, **propose then adversarially improve**. Spawn sub-agent critics:
- a **CTR critic** — attacks the thumbnail + title packaging (legible at mobile scale? face
  expression? hook strong? text/title redundant?).
- an **SEO / accuracy critic** — attacks discoverability and correctness (keywords up front?
  proper nouns spelled right vs the glossary? tags on-channel? claims match the footage?).

Fold their notes back in, then finalize `metadata_final.txt`.

## Step 6 — Human review (ONE page)

Build **one** HTML review page and open it with lavish-axi (the only UI). Show the **finished,
text-on-image thumbnails** (never bare base images) plus all metadata; the human approves or
gives notes.

1. Write `review.html` into a folder with its image assets; reference assets by **relative**
   paths (lavish serves the file's own dir). Copy rendered thumbnails next to it.
2. `npx -y lavish-axi review.html` (opens browser).
3. `npx -y lavish-axi poll review.html` as a **background task**; wait, never kill it (feedback
   persists across re-runs). The page's submit calls `window.lavish.queuePrompt(...)` then
   `sendQueuedPrompts()`; the poll returns that text. Apply it.
4. Continue the loop with `--agent-reply "<msg>"`; `npx -y lavish-axi end review.html` when done.

## Step 7 — Publish

**Always ask privacy each time** (`public` / `unlisted` / `private`, or scheduled `publish_at`
ISO time — suggest `unlisted`/`private` for a first self-check). Set recording date (default to
footage capture date), category, and `defaultLanguage`.

**Playlist** — add the video to the right playlist. List the channel's playlists, match one by
name (e.g. a travel playlist), pass its id as `playlist_id` to `start_upload`, and for
already-uploaded videos add them with `playlistItems().insert`:
```bash
svc.playlists().list(part="snippet,contentDetails", mine=True, maxResults=50)   # find the id by title
```
Viewers browse by place, so a travel video goes into its **regional playlist**
(the old catch-all "旅行 | Traveling" was deleted on 2026-09-28):
- **Its regional playlist:** a state, region or city ("阿拉斯加 | Alaska", "加州 | California",
  "美东 | US East Coast", …). The local map is in `sessions/playlists.json`. If the place is new,
  create a regional playlist named "中文 | English", public, with a one-line bilingual
  description, then add the video to it.

Keep each playlist in chronological order. Newly created playlists can 404 for a few seconds, so
retry the first insert.

**End screen (creator's standard, Studio only; the API can't set it):** every long video gets a
**Subscribe element + a Video element set to "Best for viewer"**, both over the last ~20 s
(e.g. 7:11–7:31 on a 7:31 video). The edit already reserves 15–20 s of calm B-roll/end card for it.
Add it in Studio right after upload (scheduled videos accept it): Editor → End screen + → Apply template → **"1 video, 1 subscribe"** (the default template; its video element is "Best for viewer"), save. Shorts can't have end screens.

**A/B test right after upload (creator, 2026-09-29):** if browser access is available, set it up in
Studio immediately (Details → thumbnail/title "A/B Testing" → "Thumbnail only" or "Title only";
avoid the combined mode, which confounds). Default: thumbnail-only, the creator's pick vs 1–2
alternates; title-only on a few episodes. Save the page afterwards. No browser → add a MANUAL_TODO line.
Heads-up: several Chrome instances may be connected; make sure the Studio page shows the main
channel before changing anything.

**Location = the city (creator, 2026-09-29):** set Studio's video location to the city/town
(e.g. "San Diego, California", "Albuquerque, New Mexico", "Carlsbad, New Mexico"), not a park,
landmark or venue.

**Video location** — ⚠️ **cannot be set via the API.** `recordingDetails.recordingDate` writes
fine, but `locationDescription` is silently dropped (YouTube removed location writes). Don't
waste a call on it — instead **surface the location string** (e.g. "Sarasota, Florida") for the
human to set manually in Studio → Video details → Recording date and location.

```bash
./venv/bin/python - <<'PY'
import sys, time; sys.path.insert(0,'.')
from src.uploader import start_upload, upload_progress
uid = start_upload(
    video_path="<abs .mov>", thumbnail_path="<abs thumbnail_youtube.jpg>",
    title="<chosen>", description="<chosen>", tags=[...], hashtags=[...],
    privacy_status="unlisted",          # ALWAYS confirm with human; or public/private
    publish_at=None,                    # ISO8601 for scheduled
    recording_date="2025-11-29",        # YYYY-MM-DD from footage (location is NOT API-settable)
    playlist_id="<travel playlist id>", # add to the channel's playlist
    cleanup=False,                      # NEVER delete the source
)
while upload_progress[uid]["status"] not in ("completed","error"):
    p = upload_progress[uid]; print(p["status"], p.get("progress"), p.get("stage")); time.sleep(5)
print(upload_progress[uid].get("video_url") or upload_progress[uid].get("error"))
PY
```

**Captions** (after the video exists, so its `videoId` is known). **Accuracy matters** — the
`small` model is too error-prone (it mangled dish names: hushpuppies→"conch fritters",
"土豆+洋葱圈"→"火腿通心粉"). Use a strong model and ground the cleanup in the glossary:
1. Write a per-video `02 - Export/glossary.txt` (proper nouns: places, dishes, brands), then
   run **`scripts/transcribe_accurate.sh "NN - Name"`** — it uses **`ggml-large-v3-turbo`** +
   the glossary as `--prompt` (`--carry-initial-prompt`) + **VAD** (kills hallucinated
   repetition) and writes `captions_raw.srt`. (You can't ingest audio directly, so model +
   glossary is the lever; for hard segments, optionally cross-validate a second model. Run with
   `-ng`/CPU — Metal can crash on exit cleanup.)
2. **LLM cleanup pass — be CONSERVATIVE** (result-certainty: once a model is free to rewrite,
   it "fixes" correct lines into wrong ones). Only change **high-confidence** proper-noun /
   dish-name / obvious-garble errors against the **confirmed glossary**; do NOT freely reword.
   Enforce **whole-transcript entity consistency** (a name heard two ways → unify everywhere).
   **Prefer under-correcting to mis-correcting** — leave a clumsy-but-correct line alone, and
   never invent content (we once "fixed" 很穷的 into a marmot we never saw). Keep timecodes
   byte-identical. Save `02 - Export/captions.srt`. Don't whack-a-mole individual errors — re-transcribe.
   Optionally re-split over-long cues into short readable lines with `scripts/resplit_srt.py`
   (≤~16 chars) — but make it **word-boundary aware** so it never breaks an English proper noun
   (e.g. "Beluga Point"); the naive char-wrap will, so verify before uploading.
3. Upload: `./venv/bin/python scripts/upload_captions.py <video_id> "<abs captions.srt>"`.
   Gotchas: needs **`youtube.force-ssl`** scope; a **409** means a same-name track exists →
   `captions.update` (or delete + re-insert); don't crash a re-run.

**Chapters (do this).** Add description chapters with accurate timestamps read from
`captions.srt` (match each route landmark to where it's first mentioned + that cue's start
time). YouTube rules: first chapter `00:00`, ≥3 chapters, each ≥10s, ascending; titles short
and concrete (`01:32 Ca'd'Zan 海景豪宅`). A wrong timestamp is worse than none.

**A/B Test & Compare** — YouTube's native title/thumbnail test is **Studio-desktop only, not in
the API, and not available on private videos**. You can't trigger it programmatically. So
**produce 2–3 finished thumbnail variants + 2–3 title options** per video (done in Steps 3–4)
and hand them off for the human to load into Studio → video → ⋮ → Test & compare once the video
is public. Feed the winner back into the Step 8 packaging log.

Report the resulting URL (or error).

## Step 7.5 — Mirror to Bilibili (optional; reuse everything)

**When:** ONLY as a mirror of a video you just prepared for YouTube — never start from Bilibili.
The creator says "顺手也传 B 站 / mirror to Bilibili". Reuse the finished assets; add nothing new.

**Tool & auth:** `~/.local/bin/biliup` (biliup-cli, Rust CLI). Cookies at
`~/.config/biliup/cookies.json` (kept OUT of the repo). Global `-u <file>` goes BEFORE the
subcommand. Login is the human's one-time job: `biliup -u ~/.config/biliup/cookies.json login`
(QR scan with the Bilibili app). Cookies last ~30 days → `biliup -u … renew`; if that fails,
ask the human to re-scan. There is **no official individual upload API** — biliup wraps the
web/app creator endpoints (inherent ToS risk; keep it human-paced, one video at a time).

**Field mapping (YouTube → Bilibili), all reused:**
- **video** = the finished export `02 - Export/<NN - Name>.mov`. ⚠️ the file is named the FULL
  project name (e.g. `74 - Alaska Glacier.mov`), not a short name — resolve the exact path with
  `find … -print0` and quote it (the path has spaces). A space-truncated `ls` will mislead you.
- **--cover** = `02 - Export/thumbnail/thumbnail_bilibili.jpg` (16:10 export from Step 3; make it now if missing).
- **--title** = the Chinese title from `metadata_final.txt` (B站 title ≤80 chars).
- **--desc** = Chinese-first, compressed to ~200–250 chars from the DESCRIPTION block: keep the
  hook + 📍 route; DROP the English half and the YouTube-specific "订阅/开小铃铛" line (B站 →
  "点赞关注/三连"). B站 tags are a separate field, so no leading `#hashtag` line in the desc.
- **--tag** = ≤10, comma-separated; reuse the channel-standard set
  (`美食,旅游,旅行VLOG,风景,美国,自然,户外,旅游攻略,公路,生活记录`) mixed with this video's place
  names; drop YouTube-only tags.
- **--tid 250** (出行) · **--copyright 1** (自制) · **--no-reprint 1** — the channel's confirmed
  defaults. If unsure of a partition, copy it from an existing video:
  `biliup -u … show <an existing travel BV>` → read `tid`.
- **--line txa** — fast overseas upload line (creator is in the US; ~1.7 MB/s, ~1GB ≈ 10 min).

**Privacy/timing — ASK the human** (don't assume): mirror **public now**, **scheduled**
(`--dtime <10-digit ts, ≥4h ahead>`, e.g. to match the YouTube cadence), or a **self-only test**
(`--is-only-self 1`). Default to asking before a first public mirror.

**Command** (run in the background — uploads take minutes):
```bash
~/.local/bin/biliup -u ~/.config/biliup/cookies.json upload \
  "$HOME/Desktop/NN - Name/02 - Export/NN - Name.mov" \
  --title "…" --desc "…" --tag "…" \
  --cover "$HOME/Desktop/NN - Name/02 - Export/thumbnail/thumbnail_bilibili.jpg" \
  --tid 250 --copyright 1 --no-reprint 1 --line txa
  # add --dtime <ts> to schedule, or --is-only-self 1 for a self-only test
```
Success prints a `bvid`; a fresh submission shows `state -30 审核中` (normal — it goes live after
review). Verify with `biliup -u … show <BV>`. Record the BVID next to the YouTube id in Step 8.

**合集 (season):** put every video into its regional 合集, the same grouping as the YouTube
playlists (阿拉斯加, 加州, 美东, 美国西南：亚利桑那·犹他·拉斯维加斯, …). biliup can't do this, so
use the script:
- `./venv/bin/python scripts/bili_season.py --list`
- `./venv/bin/python scripts/bili_season.py --season "<name>" --desc "<one line>" <BV…>`
- If biliup's submit fails with code 21566 (投稿过于频繁) after the upload, re-run with `--submit web`; nothing was created by the failed attempt.
- Change the cover of an already-submitted (even scheduled) video: `./venv/bin/python scripts/bili_cover.py <BV> <cover.jpg>` (dry run) then add `--go`. It re-sends every field unchanged except the cover, keeps dtime and 合集, and triggers a re-审核 (复核中). Don't edit title/desc this way unless needed — each edit re-queues review.

If the 合集 doesn't exist yet, the script creates it. A video can be in only one 合集.

**Proven recipe (verified 2026-06-20 — mirrored 70–77 in one go). Do it exactly this way:**
- **Drive it from a tiny Python script, NOT a raw shell command.** The Chinese `--desc` is
  multi-line; inlining it in bash mangles quoting/newlines. Use `subprocess.run([...])` with a
  **list of args** (no shell), one dict per video. (Template: a `JOBS=[dict(folder,dtime,title,
  tags,desc)]` loop that resolves paths, runs biliup, regexes the `bvid` out of stdout.)
- **Resolve the export path robustly** — it's `02 - Export/<NN - Full Name>.mov` (full project
  name). In Python: `max(glob('02 - Export/*.mov' + '*.MOV'), key=getsize)` after dropping any
  `*temp*` path. NEVER hand-type a short name; a space-truncated `ls`/`awk` *will* lie to you
  (that cost a failed first attempt: `Glacier.mov` ≠ `74 - Alaska Glacier.mov`).
- **Cover** — `02 - Export/thumbnail/thumbnail_bilibili.jpg`; for older videos find the source
  (`thumbnail.jpg`, or a PNG at the export root `<NN - Name> - thumbnail.png`) and run
  `export_for_platforms` on it first. Find it, don't assume.
- **Metadata source** — read `02 - Export/metadata_final.txt`: TITLE, the **Chinese** half of
  DESCRIPTION (everything before the `---` English separator), and TAGS. **If it's missing**
  (older already-published videos like 70), **fetch the live snippet from YouTube** via
  `YouTubeClient(svc).get_all_channel_videos()`, match the video, and mirror its title/desc/tags.
- **Compress the desc** to ~200–250 chars: keep the hook + the `📍 路线` list; DROP the English
  half, the leading `#hashtag` line, and "订阅/开小铃铛" (→ "点赞关注"). **Tags ≤10**, comma-separated;
  drop ones that are risky (long, apostrophes) if a submit ever 400s.
- **Scheduled `--dtime`** = 10-digit Unix ts, **≥4h ahead** and within ~15 days. Compute ET 14:00
  with `date -j -f "%Y-%m-%dT%H:%M:%S%z" "2026-06-21T14:00:00-0400" +%s` (summer = EDT `-0400`;
  winter = EST `-0500`). For a video whose YouTube is **already live**, mirror **public now**
  (omit `--dtime`); for the future-scheduled ones, match the YouTube `publishAt`.
- **Confirmed channel defaults (locked):** `--tid 250` (出行) · `--copyright 1` · `--no-reprint 1`
  · `--line txa` (US→B站, ~1.7 MB/s; a 3GB file ≈ 28 min). Run uploads **sequentially** (one
  Python loop), not many in parallel — parallel splits bandwidth and risks rate-control.
- **biliup canNOT edit or delete a 稿件** (only `login/renew/upload/append/show/list`). So
  **never re-upload a duplicate**: `biliup -u … list` first to check it isn't already mirrored,
  and if visibility/time needs changing after submit, the human does it in 创作中心. (A self-only
  `--is-only-self 1` test 稿 can't be flipped to public via CLI — delete it in the app and
  re-upload scheduled, which is what we did for 74.)
- **Verify** each: `biliup -u … show <BV>` → check `tid 250`, `is_only_self`, `dtime`, `cover`,
  `state_desc 审核中`. Login check / dup check: `biliup -u … list`. Cookie ~30d → `renew`.

**Schedule slot:** unless told otherwise, schedule in the next free 09:00 / 21:00 creator-local slot, 12 h after the latest scheduled video. Keep the list of slots in `sessions/QUEUE.md`. Use the same time on YouTube (`publishAt`) and Bilibili (`--dtime`).

## Step 7.9 — Clean up review renders
Once both uploads are verified, delete this episode's review renders:
- `02 - Export/edit/preview.mp4`
- `02 - Export/edit/previews/`
- `/tmp/yt-editor/<project>/`

Keep the `.mov` master, the EDL and the thumbnails.

## Step 8 — Self-evolving loop

After publishing, append a record to a **persistent packaging log** (a JSON/MD in `$REPO`):
`{title pattern, thumbnail formula, CTR, retention shape, impressions}`.

**Before packaging the next video**, read past records + pull recent analytics (youtube-manager
already has analytics modules — `src/analytics/`) and **bias title/thumbnail toward whatever
beat the channel's own baseline** (which hooks/power words/formulas won; face-hero vs
landmark-hero). A few days post-publish, pull the new video's CTR + retention curve, name the
earliest retention cliff with a probable cause, and write one concrete lesson back into the log.
The loop **proposes**; the human stays the gate. Human corrections during review also feed this
memory so the skill personalizes over time.

## Gotchas
- **YouTube Data API quota is 10,000 units/day** (resets 00:00 PT = 03:00 ET); no increase is
  requested (the audit form isn't worth it for a personal uploader). Budget before a batch:
  `videos.insert` measured at ~100 on 2026-09-29 (4 uploads + post-steps = 2,421 units; the docs
  still say 1,600, so check Cloud Console → Quotas when planning a big batch), `thumbnails.set` /
  `playlistItems.insert|update` / `videos.update` = 50, list calls = 1. Never bulk-reorder playlists via the API (50 per move);
  insert new items at the right position instead. Studio-only steps (location, related video)
  cost nothing. When `quotaExceeded` hits, finish the Bilibili side, write the remaining YouTube
  steps into the session state, and resume after the reset.

- **Never touch `01 - Unedited/`.** **Never delete the source** (`cleanup=False`).
- **Verify before destroying**: never delete/rename an export until confirmed correct & intact.
- This ffmpeg has **no `drawtext`** — label-free contact sheets, order by filename.
- Source is often **4K**; extract finalists at `-q:v 1`, reject blurry frames.
- Captions need the **`youtube.force-ssl`** scope; handle **409** (existing track) via update.
- **No duplicate hashtags**: the DESCRIPTION already starts with the hashtag line — push it
  **as-is**, don't also prepend `hashtags` (that doubles the line). If metadata changes after
  upload, **re-push the live description** (videos.update snippet) — the uploaded copy is stale.
- **Names**: don't write the creators' names / no by-name self-intro in descriptions or captions.
- **Transient TLS / SSL upload failures.** On some networks (corporate proxy / VPN doing TLS
  inspection) an upload can die mid-chunk or on a post-step with `SSL: CERTIFICATE_VERIFY_FAILED
  … self signed certificate in certificate chain`. The uploader now treats SSL errors as
  **recoverable** (retries chunks) and wraps the post-upload steps (recording details, thumbnail,
  playlist) in retries — and it records `video_id` the instant the video lands, so a later flaky
  step can't hide it. **Recovery if a publish still ends `error`/`completed`-with-`warnings`:** the
  video is very likely **already live** — DO NOT re-upload (that dupes it). First list the channel's
  recent uploads to find it by title, grab its id, then finish only the missing steps via API
  (`videos().update` snippet for title/desc, `thumbnails().set`, `playlistItems().insert`) with a
  small retry loop. A `maxres`/custom thumbnail absent + not-in-playlist tells you what still needs doing.
- **macOS has no `timeout(1)`** by default — don't wrap commands in `timeout`; run long jobs as
  background tasks instead. (`gtimeout` exists only if coreutils is installed.)
- **A "video N" export may cover more than day N.** Watch the frames/transcript before trusting the
  folder name for the title — e.g. a "USVI 1" cut spanned two days; don't claim a day-count (or
  "攻略") the footage doesn't support. Confirm scope from content, not the filename.
- Keep this skill **free of personal info** so it can ship with the repo.

## Manual to-dos checklist (always)

Anything the APIs can't do goes into `sessions/MANUAL_TODO.md` (local, gitignored) as a new section
at the top for this episode, with checkboxes and clickable links: Studio location string,
Test & compare thumbnail/title variants (once public), Bilibili 审核/live check, and anything else
left for the creator. Never leave these only in the chat reply.
