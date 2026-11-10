# YouTube Manager

The toolchain behind the travel-vlog channel 「Yizhou的一周」 (YouTube + Bilibili). It is **agent-first**:
Claude Code (or another coding agent) watches the footage, cuts the episode, makes covers and metadata,
uploads, and does the follow-ups. The creator reviews in a small Mac app (「审片.app」) and approves.

There is no editing software and no web dashboard to click through. The procedure lives in skills
(`.claude/skills/`), and the code here is what those skills call. Background:
[vibe-coding with Claude Code](https://yizhouyu.dev/blog/posts/vibe-coding-with-claude-code/) and
[why the UI was deleted](https://yizhouyu.dev/blog/posts/deleted-the-ui/).

## Quick start

macOS on Apple Silicon. Projects live at `~/Desktop/<NNN> - <Place>/` by default.

```bash
# main env (Python 3.9+)
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
# ASR env (Python 3.12, MLX): Qwen3-ASR for src.editor.transcribe
uv venv -p 3.12 asrvenv && uv pip install -p asrvenv/bin/python mlx-qwen3-asr opencc-python-reimplemented
# external tools
brew install ffmpeg whisper-cpp
```

- `models/` (gitignored): whisper.cpp ggml models (large-v3 / large-v3-turbo) and the Silero VAD model.
- `.tools/` (gitignored, optional): third-party envs/binaries some steps use, e.g. `mlx-audio` for
  `xcheck.py`, `rife` for `interp.py`.
- Credentials, all gitignored, provided by you:
  - `config/client_secrets.json`: Google OAuth desktop client for the YouTube Data API.
  - `config/token.pickle`: written on first auth (captions need the `youtube.force-ssl` scope).
  - `~/.config/biliup/cookies.json`: Bilibili login, made once with `biliup -u ~/.config/biliup/cookies.json login`.
- Optional env vars: `YOUTUBE_API_PROXY` / `YOUTUBE_HTTP_TIMEOUT` (when the Mac needs an explicit proxy for the
  Google API), `YT_EDITOR_JOBS` or `~/.config/yt-editor/jobs` (ffmpeg worker cap).
- 审片.app: `app/build.sh --install` (see [`app/README.md`](app/README.md)).

Then, in Claude Code: "edit this trip" / "publish NNN", pointing at a project folder.

## Episode lifecycle

1. **Footage → project.** `scripts/new_project.sh "NNN - Place"` creates the folder from
   `templates/vlog-project/`; raw clips go in `01 - Unedited/` and are never modified. Multi-episode trips are
   split by a master director (`templates/briefs/trip_brief.md`), one episode director per video, in parallel.
2. **Watch.** `src.editor.scan` (contact sheets the agent looks at), `src.editor.transcribe` (Qwen3-ASR with a
   per-trip `--context`, glossary fixes, Simplified Chinese), `src.editor.captions_clean` (only proofread captions
   reach the creator). Research with sources goes to `edit/research.md`.
3. **Edit.** The whole cut is one JSON file, `02 - Export/edit/edl.json` (`src/editor/edl.py`): shots, trims,
   captions, notes, B-roll, speed, cards, music sections. The agent writes a first-cut script, then tightens
   (`tighten`), lints (`lint`) and renders (`render --preview`): per-shot cached HEVC segments, Pillow overlays,
   music ducked under speech, loudness to −14 LUFS. Extras: route maps on OSM roads (`routemap`), RIFE slow motion
   (`interp`), flight trails, collection counters, tracked arrows, split-flap and photo-print cards.
4. **QA.** Reviewer sub-agents watch frames of the render *and* the raw footage, re-transcribe the audio against the
   captions, check loudness, and restore missed moments (C10/C11). `xcheck` runs a second ASR with speaker labels.
   A viewer + peer-director panel (`.claude/skills/edit-video-chat/audience_panel.md`) runs before 审片.
5. **审片 in the app.** The creator watches the cut and the raw footage, answers timestamped questions, and leaves
   notes in the chat; the agent applies them and re-renders right away. Approval and picks are logged.
6. **Covers and titles.** Covers come from retouched real frames (`src/thumbnail_generator/`), judged at feed size
   (`scripts/feed_sim.py`), exported for YouTube 16:9 and Bilibili 16:10. Titles come from a sub-agent debate and are
   checked for phone width (`src.editor.title_check`). The creator picks in the app's 封面 / 标题 tabs.
7. **Publish** (publish-video-chat, steps P1–P13): 4K final render, zh + en captions, bilingual metadata, scheduled
   YouTube upload of the master (resumable), English localization, regional playlist, Bilibili mirror + 合集, two
   Shorts per long video (`scripts/make_short.py`), Studio chores in the browser. Long upload chains run as Orca
   workers; `scripts/upload_dashboard.py --loop` shows progress.
8. **Follow-ups.** `scripts/episode_audit.py` after every upload chain (fix every ✗);
   `scripts/post_publish_followups.py` once a scheduled long goes public (pinned comment, Shorts' Related video,
   48 h alerts); `scripts/cleanup_previews.py --apply` once the YouTube long is verified (rebuild files are kept);
   `scripts/check_bili_vs_yt.py` for mirror gaps.

## 审片.app

A native Mac app (`app/main.swift` + `src/editor/app_server.py`): episode sidebar with status chips, tabs for
封面 / 素材 (raw footage, `footage_player`) / 成片 (cut, `review_server`) / Shorts (`shorts_page`) / 标题, a chat with
the agent on every video page (notes carry clip + second, optional 框选 box), J/K/L keys, cut↔raw jump, and
「选这个」 / 「审片通过」 picks. It never uploads or calls an agent. Details: [`app/README.md`](app/README.md).
Agents open episodes in it with `scripts/shenpian open <ep> [--tab cut] [--t 83.5] [--background]` (also `status`,
`screenshot`, `quit`; no picks or saves).

The same pages still run in a browser (`scripts/review_open.sh <ep>`; `scripts/review_stop_all.sh`). In both cases
the agent must run a chat listener whose output it can see:

```bash
./venv/bin/python -u -m src.editor.chat "<project>" watch        # prints handed-over notes (CHAT #… / CHAT BATCH …)
./venv/bin/python -m src.editor.chat "<project>" reply "…"       # answer in the panel
```

「评论」 (Shift+Enter) keeps a note pending; 「交给 Agent」 (Enter) hands over it and all pending ones. The page shows
「Agent 在听」 while a watcher heartbeat is fresh.

## Repo layout

```
.claude/skills/
  edit-video-chat/        raw clips -> reviewed cut (SKILL.md, LESSONS.md, audience_panel.md)
  publish-video-chat/     covers, metadata, captions, upload, Bilibili, Shorts, audit
  grow-channel/           weekly growth loop
app/                      审片.app (Swift shell, build.sh, DESIGN.md, icons)
src/
  editor/                 EDL, ASR, scan, render, overlays, review pages, chat, questions, checkpoints, lint, QA tools
  thumbnail_generator/    retouch, editorial / layered covers, polish, per-platform export
  uploader/               resumable YouTube upload + thumbnail + playlist
  auth/  youtube_client/  OAuth service; channel video listing
  analytics/              channel metrics for the packaging loop
scripts/                  Shorts, publish/follow-up/audit, Bilibili, growth, dashboards, cards, tests
templates/
  vlog-project/           new project skeleton (01 - Unedited, 02 - Export/{edit,thumbnail,shorts})
  briefs/                 master-director trip brief, QA brief
examples/                 routemap config example
assets/                   fonts, CTA bell SFX
LESSONS.md                operational lessons (API proxy, upload chains, other agent runtimes)
config/ models/ sessions/ docs/   local only (gitignored or never committed)
```

A project: `01 - Unedited/` (raw, read-only), `02 - Export/edit/` (EDL, scan, captions, cards, maps, music,
HANDOFF.md, questions.json, chat.jsonl, publish_prep/), `02 - Export/thumbnail/`, `02 - Export/shorts/`, and the master.

## Key scripts

Run from the repo root with `./venv/bin/python` (ASR with `asrvenv/bin/python`).

| Command | What it does |
|---|---|
| `-m src.editor.checkpoint "<project>"` | Status table + next step; `done C<n> "note"`, `note "…"` |
| `-m src.editor.scan "<project>"` | Contact sheets + clip metadata |
| `asrvenv/bin/python -m src.editor.transcribe "<project>" --context "…"` | Qwen3-ASR per clip (takes the ASR lock) |
| `-m src.editor.render "<project>" --preview\|--final\|--package` | 1080p preview, 4K master, or clip package |
| `-m src.editor.lint "<project>"` | Pre-render EDL checks (trims, captions, on-screen text) |
| `-m src.editor.xcheck "<project>" clips\|preview` | Second-model caption cross-check with speakers |
| `-m src.editor.routemap <config.json> [fetch] [route]` | Animated route map on real roads |
| `-m src.editor.questions "<project>" add\|list` | Timestamped questions for the creator |
| `-m src.editor.clip_index "<project>"` | One line per raw clip: used where, what was left out |
| `-m src.editor.digits "<project>" [--apply]` | Chinese numerals → digits in captions |
| `-m src.editor.title_check "标题" …` | How much of a title a phone shows |
| `scripts/shenpian open <ep> --tab cut\|status\|screenshot <png>\|quit` | Drive 审片.app for the creator (open / tab / seek only) |
| `scripts/make_short.py <spec.json>` | Vertical Short from source clips |
| `scripts/render_variant.py` | Non-destructive comparison cut (own EDL, SRT, manifest) |
| `scripts/upload_captions.py <id> <srt> [lang]` | Caption track upload |
| `scripts/localize_metadata.py <drafts.json> [--apply]` | Localized titles/descriptions (dry run by default) |
| `scripts/bili_season.py`, `scripts/bili_cover.py` | Bilibili 合集; swap a scheduled cover |
| `scripts/episode_audit.py <ep>\|--all` | Publish audit + drive-ready verdict |
| `scripts/post_publish_followups.py --due\|--alerts` | Pinned comment, Shorts Related video, 48 h alerts |
| `scripts/upload_dashboard.py <eps> --loop` | Live upload page at `sessions/上传进度.html` |
| `scripts/drive_move_dashboard.py <projects> --loop` | Progress page for moving projects to the archive drive |
| `scripts/cleanup_previews.py [--apply]` | Delete previews of verified uploads |
| `scripts/status.py` | One-screen board: heavy jobs, upload chains, render queue, review servers |
| `scripts/outlier_scan.py`, `scripts/feed_sim.py` | Reference-channel outliers; covers in a mock feed |
| `scripts/claude_usage.py [--log "…"]` | Claude plan 5-hour / weekly usage for batch pacing |
| `scripts/splitflap.py`, `scripts/photo_coda.py`, `scripts/tts_voices.py` | Cards; voice audition page |

## Conventions

- **One heavy job at a time.** Renders, bakes, Demucs and whisper batches go through
  `scripts/render_lock.sh <cmd…>` (`PRIO=1|2|3`); ASR goes through `src.editor.asrlock` (one model on the machine).
- **Checkpoints.** Edit steps C0–C14 via `src.editor.checkpoint`; publish steps P1–P13 as checkpoint notes plus
  `sessions/STATE.md`. Any agent resumes from disk without redoing work or uploading twice.
- **EDL is the source of truth.** Change the EDL and re-render; never edit the rendered SRT/MOV. Comparison cuts go
  through `render_variant.py` with a new versioned filename.
- **Never commit `sessions/` or `docs/`.** Channel data, upload chains, growth logs and dashboards stay local.
  Credentials stay in `config/` and `~/.config/`. Uploads are public: no sensitive personal info in metadata.
- **Approvals log.** Picks and 审片通过 from the app append to `sessions/APPROVALS.md` (append-only). Agents act on
  approvals only from that log or the creator's own words.
- Raw footage and the archive drive are read-only.

## Testing

Tests are standalone scripts (no pytest):

```bash
./venv/bin/python scripts/test_app.py                                            # one
for t in scripts/test_*.py; do ./venv/bin/python "$t" || echo "FAIL $t"; done   # all
```

## Agent notes

- Start with [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md) (rules for any editing agent), then
  [`CLAUDE.md`](CLAUDE.md), then the skill for the task and its lessons:
  [`edit-video-chat/SKILL.md`](.claude/skills/edit-video-chat/SKILL.md) +
  [`LESSONS.md`](.claude/skills/edit-video-chat/LESSONS.md),
  [`publish-video-chat/SKILL.md`](.claude/skills/publish-video-chat/SKILL.md),
  [`grow-channel/SKILL.md`](.claude/skills/grow-channel/SKILL.md).
- Skills are experience, not a rulebook: every creator correction becomes a lesson, and each episode tries one new
  technique (logged in the Experiments table of LESSONS.md).
- After a reset, run `checkpoint` for the episode and read its `HANDOFF.md` before acting.
- License: MIT.
