---
name: publish-video
description: Generate bilingual (Chinese/English) SEO metadata and thumbnail options for a YouTube video, let the user pick/edit them in a visual web page, then upload. Use when the user wants to publish/upload a video to their travel YouTube channel and provides a video file, an SRT transcript, and a base thumbnail image. Generation runs natively in Claude (no Anthropic API key / no claude -p subprocess).
---

# Publish Video

Drive the full publish loop for the YouTube Manager project: **Claude generates the
creative options natively, a thin web page handles visual selection, and a shared
uploader pushes to YouTube.** No Anthropic API key and no `claude -p` subprocess —
*you* (this Claude Code session) are the generator.

## Inputs

Three paths, from the command arguments or by asking the user:
1. **video** — the video file to upload (`.mp4/.mov/...`).
2. **srt** — the subtitle/transcript file (used to understand the content).
3. **base image** — the photo to overlay title text onto for the thumbnail.

If any is missing, ask for it before proceeding. Resolve all three to absolute paths.

## Steps

### 1. Understand the video
- `Read` the SRT file to learn what the video is about (topic, locations, highlights,
  any music credits / links worth preserving).
- `Read` (view) the base image so you can choose thumbnail text **colors that contrast
  with it** and a **text position that does not cover faces or the main subject**.

### 2. Generate the option pool
Produce **5 metadata options** and **5 thumbnail-text options**, each a distinct angle.
Write them into `session.json` (schema below). Because you write the JSON directly,
there are no escaping problems — but never put a raw `"` inside a JSON string value.

**Metadata rules** (this is a Chinese travel channel — default Chinese-first unless the
SRT is clearly English):
- `title`: primary language, ≤70 chars, **keywords first**, engaging words (必看, 攻略,
  完整版, 深度, 实拍, 最新 / Ultimate, Complete Guide, Best). Clickable, not clickbait.
  Use **Simplified Chinese** (简体中文).
- `description`: bilingual. Primary section ~250+ words (keywords in the first 25), then
  a `---` separator, then the secondary language ~150+ words. **Preserve** any music
  credits, timestamps, or links found in the SRT.
- `tags`: 8–12, mixed Chinese + English, most relevant first.
- `hashtags`: 3–5 (first 3 are most visible), bilingual.
- 5 angles: engaging / informative / curiosity / value-or-number-driven / emotional.

**Thumbnail-text rules** (one object per option):
- `main_text`: ≤5 words; for Chinese, ~4–8 punchy characters.
- `subtitle`: optional, short (use `""` if none).
- `text_color` / `outline_color`: hex (`#RRGGBB`), high contrast, chosen to pop against
  the base image you viewed.
- `position`: `"top"`, `"center"`, or `"bottom"` — pick what avoids the subject.
- `font_size_main`: integer, default 120.
- Vary color/style across the 5.

### 3. Create the session and render thumbnails
- Make a session id and dir: `mkdir -p sessions/<id>` (use a timestamp id, e.g. from
  `date +%Y%m%d-%H%M%S`).
- Copy the base image into the session dir (e.g. `sessions/<id>/base.jpg`).
- Write `sessions/<id>/session.json` with **absolute** paths.
- Render: `./venv/bin/python scripts/render_thumbnails.py sessions/<id>`
  (produces `thumb_0.jpg … thumb_4.jpg`).

### 4. Open the review page
- Make sure the web app is running (`curl -s localhost:5001/api/health`); if not, start
  it: `./venv/bin/python start_web.py` (background).
- Open the page for the user: `open http://localhost:5001/review` (it loads the latest
  session automatically).
- Tell the user: pick a thumbnail + a title, fine-tune with the sliders / manual text,
  set privacy (suggest **Unlisted** for a first test), then click **Upload to YouTube**.

### 5. Wait-loop for regenerate / done
Run `./venv/bin/python scripts/wait_for_review.py sessions/<id>` and act on its output:
- `{"event":"regenerate", "action":..., "feedback":...}` → generate a **fresh batch**
  honoring the feedback (e.g. "punchier", "shorter", "emphasize the food"). For
  `regenerate_titles` replace `metadata_options`; for `regenerate_thumbnail_text` replace
  `thumbnail_options`. Rewrite `session.json`, re-run `render_thumbnails.py sessions/<id>`,
  then run `wait_for_review.py` again. (The page polls and refreshes automatically.)
- `{"event":"done", "upload_id":...}` → the user confirmed and the upload is running.
  Report the upload started and stop the loop.
- `{"event":"timeout"}` → if the user is still working, run `wait_for_review.py` again;
  otherwise stop.

## session.json schema

```json
{
  "id": "20260603-235900",
  "video_path": "/abs/path/video.mp4",
  "srt_path": "/abs/path/captions.srt",
  "base_image_path": "/abs/path/sessions/<id>/base.jpg",
  "metadata_options": [
    {"title": "...", "description": "...\n\n---\n\n...", "tags": ["..."], "hashtags": ["#..."]}
  ],
  "thumbnail_options": [
    {"main_text": "震撼故宫", "subtitle": "必看攻略", "text_color": "#FFD700",
     "outline_color": "#000000", "position": "top", "font_size_main": 130}
  ]
}
```

## Notes
- Deterministic edits (sliders, manual thumbnail text) happen entirely in the web app via
  `add_text_to_image` — you don't need to be involved for those.
- The user's **source video is never deleted**; only the upload reads it.
- Costs run on the Claude Code subscription (this session), not a metered API key.
