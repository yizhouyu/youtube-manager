# YouTube Manager

An **agent-first** toolkit for publishing a YouTube channel by *talking to an agent* (Claude Code) instead of clicking through a UI. Point it at a finished video export and it watches the footage, transcribes it, designs the thumbnail by *looking* at the frame, writes bilingual (Chinese-first) SEO metadata in your channel's own style, critiques its own work with sub-agents, then uploads, captions, schedules, and playlists it.

> This started as a Flask web app + CLI (see the original write-up: [vibe-coding with Claude Code](https://yizhouyu.dev/blog/posts/vibe-coding-with-claude-code/)). It's since been rebuilt around a single conversational **skill** — the UI was deleted on purpose. A UI can only expose the buttons you thought to build; telling a capable agent what to do, and working directly inside it, doesn't cap what it can do.

## How it works

The whole procedure lives in one skill: **[`.claude/skills/publish-video-chat/SKILL.md`](.claude/skills/publish-video-chat/SKILL.md)**. It's generic — point it at any channel and it learns that channel's voice from its own uploads. The flow:

1. **Pre-process & QA the export** (`scripts/preprocess_video.sh`) — extract frames, transcribe audio, and flag broken / mis-exported files (it looks at pixels, not just filenames).
2. **Understand the video** — read the transcript *and* the frames; build a proper-noun glossary; web-search anything uncertain.
3. **Design the thumbnail** by looking at the image, then polish it (`src/thumbnail_generator/`: `compositor.py` + `polish.py` — color grade, vignette, dual-stroke text). Mobile-legibility self-audit.
4. **Write bilingual SEO metadata** in the channel's learned style, then run **sub-agent critics** (CTR + SEO/accuracy) before a human sees anything.
5. **Accurate captions** (`scripts/transcribe_accurate.sh`: `large-v3-turbo` + a per-video glossary `--prompt` + VAD), cleaned against the glossary, uploaded via `scripts/upload_captions.py`.
6. **Upload, schedule (`publishAt`), and playlist** the video — and feed every human correction back into a persistent memory so the system gets more "you" over time.

## Repo layout

```
.claude/skills/publish-video-chat/   # the skill — the actual procedure
scripts/
  preprocess_video.sh                # frame scan + whisper transcript + export QA
  transcribe_accurate.sh             # large-v3-turbo + glossary --prompt + VAD captions
  upload_captions.py                 # captions.insert
src/
  auth/            # YouTube OAuth2
  youtube_client/  # list channel videos (learn the channel's style)
  uploader/        # resumable upload + thumbnail + playlist (start_upload)
  thumbnail_generator/  # add_text_to_image (Pillow) + compositor + polish
  analytics/       # channel metrics (for the self-evolving packaging loop)
config/            # client_secrets.json + token.pickle (gitignored)
models/            # whisper ggml models (gitignored)
```

## Setup

1. `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
2. **External tools**: `brew install ffmpeg whisper-cpp`, then drop a whisper model in `models/` (e.g. `ggml-large-v3-turbo-q5_0.bin`) + a VAD model (`ggml-silero-vad.bin`).
3. **YouTube auth**: put OAuth2 desktop `client_secrets.json` in `config/`; the first run opens a browser and saves `config/token.pickle`. Captions need the `youtube.force-ssl` scope.
4. **Use it**: in Claude Code, point the `publish-video-chat` skill at a finished export and tell it to publish.

## Notes

- The agent owns the decisions; you review once before publish and give notes — your corrections become memory.
- `src/analytics/` is kept for the self-evolving loop (bias future titles/thumbnails toward what beat the channel's baseline).
- License: MIT.
