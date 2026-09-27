---
name: edit-video-chat
description: Auto-edit a travel vlog from a folder of raw action-cam clips — the agent watches every clip (contact sheets + whisper transcripts), picks and trims shots, writes burned-in Simplified-Chinese subtitles, adds B-roll, title cards, place tags, section-based music, and renders a finished video; the creator fine-tunes on a local review page (toggle/trim/split/reorder shots, edit subtitles) and re-renders in minutes. Use when the creator says to cut / 剪 a trip's footage. Hands off to publish-video-chat once the export exists.
---

# Edit Video (conversational, agent-first)

The agent is the editor. The **EDL** (`<project>/02 - Export/edit/edl.json`, schema in
`src/editor/edl.py`) is the single source of truth: the agent writes it, the review page
edits it, the renderer reads it. Never touch `01 - Unedited/`.

Resolve `REPO` as two levels up from this file and run everything from there.

## 0. Kick off in parallel

As soon as the creator hands over a folder, start these side by side (subagents):
- **Raw-footage player** for the creator, up immediately (it needs no EDL) —
  `./venv/bin/python -m src.editor.footage_player "<project>"` (port 8766): all clips back-to-back
  in capture order at 1×–3×, with the transcript line. Its job is letting the creator preview the
  raw material and grasp the whole trip; marking what the cut used is an optional toggle.
  It shows ONLY proofread captions (`src.editor.captions_clean`: EDL lines where they exist, else
  `edit/glossary.json` fixes + hallucination/filler filtering) — never raw whisper text.
- Transcription + contact sheets (below), music sourcing, and the edit itself.

## 1. Watch the footage (deterministic layer)

- `ffprobe` every clip: duration, `creation_time` (GoPro writes the camera's local clock with
  a `Z` suffix — don't trust it as UTC; sanity-check against daylight in the frames), color
  transfer (HLG/HDR needs tone-mapping first).
- Contact sheet per clip: `fps=1/max(2,dur/12),scale=320:-2,tile=6x2` (no `drawtext` in this
  ffmpeg — label with Pillow, see how `overlays.py` loads fonts). Stack 4 clips per image and
  **look at every one**.
- Transcribe each clip with whisper.cpp **on the Apple GPU (Metal, the default — do not pass
  `-ng`)**: `whisper-cli -m models/ggml-large-v3.bin -l zh -osrt --vad --vad-model
  models/ggml-silero-vad.bin -bs 5 -mc 0 --prompt "<place names>"`. ~1–2 s per clip on Apple
  Silicon vs minutes on CPU.
- Treat ASR as a draft: drop hallucinations (broadcaster sign-offs, "字幕by…", lone "好/我"),
  convert to **Simplified Chinese** (OpenCC `t2s`), fix proper nouns from what the frames show
  (signs, menus) + a web search for dishes/places. Never name a dish or place you can't see or
  verify.

## 2. Make the cut (judgment layer)

Write the EDL (a small build script is fine). Craft rules that make it comfortable to watch:
- **Story:** 15–20 s cold open of the best moments over music → a title card → chronological
  sections per island/place (title card + place tags) → a slow ending shot with a fade.
- **Use a fraction of the footage.** Drop clips that are silent + repetitive (sand-only
  underwater, lens covered, near-duplicate selfies); trim talking clips to the speech plus
  ~0.3 s; split long clips to cut dead air.
- **Montages** of ambient shots (`audio: ambient`) at 3–6 s each, music forward.
- **B-roll**: when the creator talks over a boring frame (food close-up, parking lot), cut the
  picture away to a related clip (`broll: [{clip, in, at, dur, grade}]`) while their voice
  continues.
- **Tighten speech**: `./venv/bin/python -m src.editor.tighten "<project>"` runs the Silero VAD
  (whisper fills in 嗯/啊 silently and wind noise defeats loudness-based silence detection) and
  writes `skip` spans: pauses ≥0.55 s shrink to ~0.3 s, isolated voice blips with no subtitle
  (fillers) go. Set `skip_on: false` on shots where the pause IS the content (pans, animals).
- **Ken Burns** (`zoom: {from, to, x, y}`): slow eased push-in toward what the speaker points
  at when it's far away (boats, islands, ships), pull-out on the ending shot.
- **Music by section** (`music: [{file, start: <shot id>}]`), crossfaded, auto-ducked under
  speech (subtitle intervals). YouTube Audio Library tracks with "no attribution required" are
  the only Content-ID-safe choice; record licenses in `edit/music/LICENSES.md`.
- **Color:** named grades in `grades`; a mild land grade and a red-restoring underwater grade
  (check a before/after frame grid before committing).

## 3. Render + review

```bash
./venv/bin/python -m src.editor.render "<project>" --preview   # 1080p → edit/preview.mp4
./venv/bin/python -m src.editor.review_server "<project>"       # http://127.0.0.1:8765
./venv/bin/python -m src.editor.render "<project>" --final     # 4K → 02 - Export/<project>.mp4
./venv/bin/python -m src.editor.render "<project>" --package   # clean numbered clips + SRT for CapCut
```

Segments are cached by content hash, so a re-render after edits only re-encodes changed
shots.

**Mandatory QA before the creator sees it:** spawn a separate reviewer subagent that watches
the whole preview (dense frame sheets), "listens" (re-transcribes the rendered audio and diffs it
against captions.srt; ebur128 loudness over time for music-over-speech, pops, holes), fixes
what it can directly in the EDL (reload before every write — the creator may be editing), and
re-renders. Then hand the review page (port 8765, plain-language UI) to the creator. Their edits are
saved back to the EDL (with history in `edit/history/`); every recurring correction becomes a
preference in memory.

The final render also writes `edit/captions.srt` (timeline-mapped) for upload as the CC track.
Then continue with the publish-video-chat skill.
