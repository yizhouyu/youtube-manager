# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

An **agent-first** YouTube publishing toolkit. There is no web UI and no CLI — the
procedure is a **skill** the agent runs conversationally:
**[`.claude/skills/publish-video-chat/SKILL.md`](.claude/skills/publish-video-chat/SKILL.md)**.
That skill is the source of truth for *how* to publish; this file just describes the code it
leans on. (The repo used to be a Flask app + CLI + Anthropic-API generation; that was all
removed — the agent now does the generating, looking, and listening itself.)

## Code the skill uses

- **`src/auth/youtube_auth.py`** — `YouTubeAuthenticator().get_youtube_service()`; OAuth2,
  token persisted to `config/token.pickle` (auto-refresh). Captions need the
  `youtube.force-ssl` scope.
- **`src/youtube_client/client.py`** — `YouTubeClient(svc).get_all_channel_videos()` to learn
  a channel's existing title/tag/description style.
- **`src/uploader/uploader.py`** — `start_upload(...)`: resumable upload + custom thumbnail +
  playlist; poll `upload_progress[uid]`. Sets category 19, `defaultLanguage=zh-CN`. Note:
  `locationDescription` is NOT settable via the API (set it manually in Studio); the
  hashtag prepend can duplicate the description's hashtag line — push DESCRIPTION as-is.
- **`src/thumbnail_generator/`** — `generator.add_text_to_image` (pure Pillow, 1280×720 crop +
  outlined text), `compositor.render_option` (the thin wrapper), `polish.render`
  (color-grade + vignette + dual-stroke text — the nicer renderer), `collage.py` (frame grab +
  split panels, legacy) and `layered.py` (multi-place thumbnails: hero + tilted cards / circle
  insets / rembg cut-outs / text behind the subject / route line; native 16:9 + Bilibili 16:10).
- **`src/analytics/`** — channel metrics; kept for the self-evolving packaging loop.
- **`scripts/`** — `preprocess_video.sh` (frame scan + whisper transcript + export QA),
  `transcribe_accurate.sh` (large-v3-turbo + glossary `--prompt` + VAD), `upload_captions.py`
  (`captions.insert`).

## Editing (before publishing)

Raw footage → finished vlog is the **edit-video-chat** skill
([`.claude/skills/edit-video-chat/SKILL.md`](.claude/skills/edit-video-chat/SKILL.md)), built on
`src/editor/`:
- **`edl.py`** — the EDL schema (`<project>/02 - Export/edit/edl.json`) + timeline/subtitle helpers.
- **`render.py`** — `-m src.editor.render "<project>" --preview|--final|--package`: per-shot
  cached segments (grade, B-roll, burned-in subs/titles/tags), frame-exact concat, section
  music ducked under speech, mastering loop to −14 LUFS / ≤ −1.5 dBTP (see render skill), timeline `captions.srt`.
- **`overlays.py`** — Pillow-rendered subtitle / title card / place-tag PNGs (no `drawtext` here).
- **`review_server.py`** — `-m src.editor.review_server "<project>"`: local page to toggle, trim,
  split, reorder shots and edit subtitles, then re-render.

## Setup / tools

- `python3 -m venv venv && pip install -r requirements.txt` (Python 3.9+ works).
- External: `ffmpeg` + `whisper-cli` (whisper.cpp) with a ggml model in `models/` (gitignored).
- `config/client_secrets.json` (you provide) + `config/token.pickle` (auto).

## Conventions

- Keep the skill **PII-free** so the repo can ship publicly.
- Video projects: `NN - Name/02 - Export/<name>.mov`; never touch `01 - Unedited/`; scratch
  (frames, contact sheets) goes to `/tmp`.
- Every human correction during a publish should become a durable preference/memory.
