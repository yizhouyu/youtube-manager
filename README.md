# YouTube Manager

An **agent-first** toolkit for running a travel-vlog channel by *talking to an agent* (Claude Code)
instead of clicking through editing and upload UIs. You hand it a folder of raw action-cam clips,
and it:
- watches and transcribes every clip;
- cuts a story-driven vlog with subtitles, music, zooms, arrows and title cards;
- has sub-agent reviewers QA the cut;
- designs the thumbnail by *looking* at frames;
- writes bilingual (Chinese-first) metadata in your channel's own voice;
- publishes to **YouTube and Bilibili**, with captions, scheduling and regional playlists/合集.

> This started as a Flask web app + CLI (see the original write-up: [vibe-coding with Claude Code](https://yizhouyu.dev/blog/posts/vibe-coding-with-claude-code/)). It has since been rebuilt around conversational **skills**, and the UI was deleted on purpose ([here is why](https://yizhouyu.dev/blog/posts/deleted-the-ui/)). A UI can only expose the buttons you thought to build. An agent you talk to isn't capped that way.

**For any editing agent:** start with [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md), then read the relevant edit/publish skill and its `LESSONS.md`. These repository rules apply regardless of which agent performs the work.

## The two skills

| Skill | What it does |
|---|---|
| [`edit-video-chat`](.claude/skills/edit-video-chat/SKILL.md) | Raw clips → a finished, reviewed cut (EDL-driven, rendered with ffmpeg). |
| [`publish-video-chat`](.claude/skills/publish-video-chat/SKILL.md) | Finished export → thumbnail, metadata, captions, upload/schedule, playlists, Bilibili mirror. |

Both skills learn. [`LESSONS.md`](.claude/skills/edit-video-chat/LESSONS.md) records every creator
correction and every editing experiment, with a table of what worked. Each new video has to be
better than the last.

## Editing (`edit-video-chat`)

The whole edit is one JSON file, `edit/edl.json`. It holds the shots, trims, subtitles, B-roll,
Ken Burns zoom, speed/timelapse, labelled arrows, freeze-frame and title cards, and the music
sections (with ducking and music-free "breathing room"). Agents write it; the renderer turns it
into video.

1. **Transcribe** with [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) on Apple Silicon
   via MLX.
   - It gets a per-trip proper-noun context.
   - A glossary (`{"heard": "correct"}`) fixes known mishearings, and OpenCC converts the text to
     Simplified Chinese.
   - Captions stay hidden until they pass a proofread gate.
2. **Scan**: contact sheets and metadata for every clip (`src/editor/scan.py`). The agent *looks*
   at every sheet.
3. **Build the cut**: the agent writes a first-cut script that emits the EDL, following retention
   rules:
   - a hook in the first 8 s, and a mini-arc per place;
   - no long static shots; dull stretches are timelapsed;
   - one comment question, and an end screen with a teaser for the next episode.
4. **Tighten**: Silero VAD removes dead air and fillers (`src/editor/tighten.py`).
5. **Render** (`src/editor/render.py`):
   - per-shot HEVC segments (VideoToolbox), cached and then concatenated;
   - overlays drawn as Pillow PNGs;
   - music sections crossfaded, loudness-matched, and ducked under speech;
   - two-pass loudnorm to −14 LUFS, plus a limiter;
   - output as a 1080p preview or a 4K 10-bit master.
   - **Alternate comparison cuts** use `scripts/render_variant.py`: it stages a separate project
     with a symlink to protected raw media, copies and delivers version-scoped edit assets, and
     exports a 4K master, SRT, editable source-time EDL, and render manifest. It refuses to
     overwrite existing companion deliverables or write into raw-media/source-edit folders.
6. **QA (mandatory)**: every round, a reviewer sub-agent:
   - watches dense frames of the render *and* the raw footage;
   - re-transcribes the rendered audio and diffs it against the captions;
   - checks loudness and scores each 30 s window as a viewer would;
   - proposes improvements.

   Rounds continue until the reviewer reports no further issues.

Two local pages help the human:
- **Review page** (`src/editor/review_server.py`): play the cut, adjust shots, see what changed.
- **Footage player** (`src/editor/footage_player.py`): watch all raw clips back-to-back at
  1.5×/2×, with proofread captions.

**Batch mode.** Many trips can be rough-cut unattended:
- A "master director" agent dispatches one "episode director" per video, in parallel, as
  sub-agents or Orca workers.
- The master answers the directors' questions. Each director writes a `HANDOFF.md` with open
  questions for the creator's review session.
- `scripts/claude_usage.py` reads the plan's 5-hour and weekly usage, so the batch can pace itself
  and resume after a reset.
- `~/.config/yt-editor/jobs` caps the number of ffmpeg workers live, so parallel episodes don't
  swamp the machine.

## Publishing (`publish-video-chat`)

1. **QA the export** (`scripts/preprocess_video.sh`): extract frames, transcribe, and flag broken
   exports.
2. **Thumbnail** (`src/thumbnail_generator/`):
   - designed by looking at frames, then polished: grade, vignette, dual-stroke text;
   - checked with a mobile-legibility self-audit;
   - exported per platform by `export.py`: YouTube 1280×720, Bilibili 16:10.
3. **Metadata**: bilingual SEO in the channel's learned style. Sub-agent critics (CTR + accuracy)
   check it before a human sees it.
4. **Captions**: uploaded with `scripts/upload_captions.py`.
5. **Upload + schedule** (`publishAt`) via `src/uploader/`. Each travel video goes into its
   **regional playlist** (阿拉斯加 | Alaska, 加州 | California, 美东 | US East Coast, …), so
   viewers can binge a place.
6. **Bilibili mirror**: uploaded and scheduled with [biliup](https://github.com/biliup/biliup-rs).
   `scripts/bili_season.py` then puts it into the matching regional **合集**.
7. **Manual steps**: anything the APIs can't do (Studio location, thumbnail A/B test) goes on a
   manual checklist.

## Repo layout

```
.claude/skills/
  edit-video-chat/      # editing procedure + LESSONS.md (what worked, what didn't)
  publish-video-chat/   # publishing procedure
src/
  editor/               # edl.py (schema), render.py, overlays.py, transcribe.py, scan.py,
                        # tighten.py, captions_clean.py, review_server.py, footage_player.py
  thumbnail_generator/  # compositor + polish + per-platform export
  uploader/             # resumable upload + thumbnail + playlist
  youtube_client/  auth/  analytics/
scripts/
  new_project.sh        # new vlog project from templates/vlog-project
  claude_usage.py       # plan usage (5-hour / weekly) for batch pacing
  render_variant.py     # non-destructive 4K comparison-master renderer
  bili_season.py        # Bilibili 合集 (create + add episodes)
  preprocess_video.sh  transcribe_accurate.sh  upload_captions.py  render_thumbnails.py
templates/vlog-project/ # 01 - Unedited/, 02 - Export/{thumbnail, edit/{glossary, music, sfx, HANDOFF}}
config/  models/  sessions/   # credentials, whisper models, local batch state (all gitignored)
```

A project is a folder `NN - Place/`:
- `01 - Unedited/`: raw clips, never modified.
- `02 - Export/edit/`: everything about this video's edit.
- `02 - Export/thumbnail/`: the thumbnails.
- `02 - Export/NN - Place.mov`: the master.

## Setup

1. Create the main env: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
2. Install the external tools with `brew install ffmpeg whisper-cpp`, then put the whisper and
   Silero VAD models in `models/`.
3. Create the ASR env (Apple Silicon): `python3.12 -m venv asrvenv && asrvenv/bin/pip install mlx-qwen3-asr opencc-python-reimplemented`
4. **YouTube auth**: put an OAuth2 desktop `client_secrets.json` in `config/`. The first run opens
   a browser and saves the token. Captions need the `youtube.force-ssl` scope.
5. **Bilibili (optional)**: install `biliup`, then run
   `biliup -u ~/.config/biliup/cookies.json login` once (QR scan).
6. In Claude Code, say "edit this trip" or "publish this video" and point it at a project folder.

## Notes

- The agent makes the editing decisions. You review once, and your notes become rules, both in
  `LESSONS.md` and in the creator-preference memory the agent keeps.
- Music comes from the YouTube Audio Library (no attribution required). Each project keeps its
  tracks and a `LICENSES.md`.
- A comparison delivery keeps its `.edl.json` as the source of truth, plus an `.srt`,
  `.manifest.json`, and a version-scoped `.assets/` directory when the alternate EDL uses extra
  media. Change subtitle text or timing in the EDL, then render to a new versioned output; never
  treat the rendered SRT as the source file or reuse a version number. The renderer preflights all
  destination paths before starting.
- When approved by the creator, original generated music, brief TTS, and clearly illustrative
  transitions can be used as editorial layers. They must not fabricate the real trip, and an
  alternate version records its generated assets in its manifest.
- `src/analytics/` feeds the packaging loop, which biases future titles and thumbnails toward what
  beat the channel's baseline.
- License: MIT.
