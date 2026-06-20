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
- **Web-search any uncertain proper noun** to get the correct spelling (ASR mangles mixed-in
  English names). Confirm genuinely ambiguous ones with the human in a short Q&A — this is the
  authoritative glossary for metadata AND caption cleanup.
- Map the timeline (which place at which timestamp) — you'll reuse it for chapters.

## Step 3 — Design the thumbnail (by looking)

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

**Polish the look (use `src/thumbnail_generator/polish.py`).** Don't ship a bare frame —
`polish.render(base, out, text, color=…, outline=…, position=…, banner=…)` grades the base
(saturation ~1.18, contrast ~1.11, warmth, unsharp), adds a **vignette** to pull the eye to
center, and draws text with a real **dual outline + soft drop shadow** and a consistent
yellow accent edge (cohesive across the channel). Pass `banner=True` when the frame behind the
text is busy. (Tier B, optional: `mediapipe` selfie-segmentation to blur/darken the background
behind a person. See `docs/thumbnail-polish-playbook.md`.)

**Mobile self-audit (mandatory).** After compositing, downscale the rendered thumbnail to
~10% (~168×94), `Read` it, and **reject** if the face/text/subject isn't instantly legible.
Iterate before the human sees it. Produce **2–3 variants by design** (e.g. face-hero vs
landmark-hero, or different hook) so they're ready to drop into YouTube's native Test & Compare.

## Step 4 — Metadata in the channel's OWN style

**Learn the channel first — don't invent a voice.** Pull recent uploads and read the patterns
(title formats, tag mix, description skeleton, hashtag count). This is what makes the skill
generic: it adapts to whatever channel it's pointed at.

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

**Video location** — ⚠️ **cannot be set via the API.** `recordingDetails.recordingDate` writes
fine, but `locationDescription` is silently dropped (YouTube removed location writes). Don't
waste a call on it — instead **surface the location string** (e.g. "Sarasota, Florida") for the
human to set manually in Studio → Video details → Recording date and location.

```bash
./venv/bin/python - <<'PY'
import sys, time; sys.path.insert(0,'.')
from src.uploader import start_upload, upload_progress
uid = start_upload(
    video_path="<abs .mov>", thumbnail_path="<abs thumbnail.jpg>",
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
2. **LLM cleanup pass** — fix proper nouns using the **confirmed glossary** from Step 2, and
   **double-check every dish/food name** (ASR mangles them). Keep timecodes byte-identical. Save
   `02 - Export/captions.srt`. Don't whack-a-mole individual errors later — re-transcribe.
3. Upload: `./venv/bin/python scripts/upload_captions.py <video_id> "<abs captions.srt>"`.
   Gotchas: needs **`youtube.force-ssl`** scope; a **409** means a same-name track exists →
   `captions.update` (or delete + re-insert); don't crash a re-run.

**Optional chapters** — turn the labeled frame timeline (Step 2) into description chapters
(`00:00 Intro`, `01:32 [地点]`, …; first at `00:00`, ≥3 chapters, each ≥10s).

**A/B Test & Compare** — YouTube's native title/thumbnail test is **Studio-desktop only, not in
the API, and not available on private videos**. You can't trigger it programmatically. So
**produce 2–3 finished thumbnail variants + 2–3 title options** per video (done in Steps 3–4)
and hand them off for the human to load into Studio → video → ⋮ → Test & compare once the video
is public. Feed the winner back into the Step 8 packaging log.

Report the resulting URL (or error).

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

- **Never touch `01 - Unedited/`.** **Never delete the source** (`cleanup=False`).
- **Verify before destroying**: never delete/rename an export until confirmed correct & intact.
- This ffmpeg has **no `drawtext`** — label-free contact sheets, order by filename.
- Source is often **4K**; extract finalists at `-q:v 1`, reject blurry frames.
- Captions need the **`youtube.force-ssl`** scope; handle **409** (existing track) via update.
- **No duplicate hashtags**: the DESCRIPTION already starts with the hashtag line — push it
  **as-is**, don't also prepend `hashtags` (that doubles the line). If metadata changes after
  upload, **re-push the live description** (videos.update snippet) — the uploaded copy is stale.
- **Names**: don't write the creators' names / no by-name self-intro in descriptions or captions.
- Keep this skill **free of personal info** so it can ship with the repo.
