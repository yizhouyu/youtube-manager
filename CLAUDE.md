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
  outlined text), `compositor.render_option` (the thin wrapper), and `polish.render`
  (color-grade + vignette + dual-stroke text — the nicer renderer).
- **`src/analytics/`** — channel metrics; kept for the self-evolving packaging loop.
- **`scripts/`** — `preprocess_video.sh` (frame scan + whisper transcript + export QA),
  `transcribe_accurate.sh` (large-v3-turbo + glossary `--prompt` + VAD), `upload_captions.py`
  (`captions.insert`).

## Setup / tools

- `python3 -m venv venv && pip install -r requirements.txt` (Python 3.9+ works).
- External: `ffmpeg` + `whisper-cli` (whisper.cpp) with a ggml model in `models/` (gitignored).
- `config/client_secrets.json` (you provide) + `config/token.pickle` (auto).

## Conventions

- Keep the skill **PII-free** so the repo can ship publicly.
- Video projects: `NN - Name/02 - Export/<name>.mov`; never touch `01 - Unedited/`; scratch
  (frames, contact sheets) goes to `/tmp`.
- Every human correction during a publish should become a durable preference/memory.
