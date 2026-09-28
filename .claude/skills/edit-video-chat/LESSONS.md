# Editing lessons (read before every edit; append after every video)

Hard-won notes from real edits. Each line is something that went wrong or slow once. Keep them
concrete; prune ones that the code now enforces. Newest learnings go at the bottom of each section.

## Workflow & collaboration

- **Kick off in parallel the moment footage arrives:** raw-footage player (for the creator to
  preview the trip — NOT to audit the cut), transcription, contact sheets, music, thumbnails.
  None of them depend on the cut. Thumbnails in particular: start from raw frames graded with the
  EDL's grade.
- **Use subagents for independent work** (page UI, music sourcing, research, QA, publishing), but
  keep ONE writer per file. When a reviewer is editing `edl.json`, route new creator requests to
  that reviewer instead of editing concurrently; always reload the EDL right before writing.
- **The creator reviews mid-stream and fires many small corrections.** Apply each immediately
  (EDL + glossary + re-render), acknowledge in one line, and turn recurring ones into rules here
  or in the creator's preferences.
- **Mandatory multi-round QA before the creator sees a cut:** a reviewer agent watches dense frame
  sheets of the render, "listens" by re-transcribing the rendered audio and diffing against
  `captions.srt`, measures loudness over time, AND watches the raw footage to restore missed
  moments. Iterate editor ↔ reviewer until it says "no further issues". In practice each round
  found real bugs (misaligned captions, speech cut by a fade, jump-cut mid-word, a renderer bug).
- **Agents hit rate limits mid-task.** Before resuming, diff `edl.json` against the pre-round backup
  in `edit/history/` to see what was already done; resume the same agent with that summary.
- **Push often** (feature branch, merge finished work to main). A long session is otherwise one
  crash away from losing work.
- **As soon as the upload is done, delete `edit/preview.mp4` and `/tmp/yt-editor/<project>`**
  (20+ GB of cached segments) — the master and the EDL are the source of truth.

## Speech → subtitles

- **Model choice matters more than prompt tricks.** Qwen3-ASR-1.7B (MLX) with a `--context` list of
  proper nouns beat whisper large-v3 clearly on Mandarin + English names: right place/dish names,
  Simplified output, empty output on silent underwater clips (whisper hallucinated broadcaster
  sign-offs like "请不吝点赞 订阅 转发"). Always pass context (from the itinerary, signs, menus).
  Periodically check for a newer model and benchmark on 5–6 real clips before switching.
- **Put the creator's itinerary / notes into `asr_context.txt` first** — it's the best source of
  proper nouns (boat names, dishes, restaurants, animals seen).
- **Never show the creator un-proofread ASR** — not in the player, not anywhere. The footage player
  shows captions only after `captions_clean --mark-proofread`, i.e. after the agent has read every
  transcript and filled `glossary.json`.
- **Homophones the ASR gets wrong are often the words that matter most:** pet nicknames
  (社牛玳瑁 → 戴帽/代冒/单猫), animals (小驴子 → 小鱼子), place names (Junction → Junkers,
  Trunk Bay → Trunkville, Salt Pond → South Palm), dishes (Kallaloo → Colorful Soup). Cross-check
  against frames and the scene before trusting a line; when two models disagree and the frame
  doesn't settle it, drop the line.
- **ASR invents lines in noisy/silent audio** ("这里都非常多人", "不怕他", "那是泰国" were never said).
  Glossary value `""` drops a known phantom line everywhere.
- **Chinese lines get split into crumbs** ("可以来看一 | 看"). Merge ≤3-char / <0.25 s fragments into
  neighbours when contiguous (transcribe.py does this).
- **Food names: use the creator's preferred spelling consistently** (e.g. "Pâté" for both saltfish
  and beef, "Kallaloo soup" not "Kallaloo", "Jerk Duck"). Verify the dish by looking at the frame
  and a web search; never guess.
- Subtitles on screen < 0.7 s are unreadable — merge or extend. Lines hanging 5 s after speech ends
  look broken — trim to the speech.

## Picking and cutting shots

- **Use a fraction of the footage, by taste.** Drop silent + repetitive clips (sand-only underwater,
  lens covered by a finger, near-duplicate passes). Not every clip needs to appear.
- **Keep short "showing" shots** where the camera clearly shows something (a trail sign, a stamp,
  a menu, an animal) even at 2–3 s — give them an editor's note caption (`kind: "note"`).
- **Note captions have no audio to check against** — verify across several frames. A "second
  stingray" was actually a small fish following the ray. Stay generic when unsure.
- **Repeated subject → keep only distinctive takes** (e.g. many stingray passes: keep two-together,
  approaching, person-waving-next-to-it; ~20 s total for the stretch).
- **People on camera:** keep more of them facing the lens together (e.g. underwater peace signs);
  above-water close-ups with really messy wet hair are out — err strict: when in doubt, cut it.
- **Keep the full arc of an action** (fishing: bite → reeling → landing → showing the catch →
  release), trimming only dead waits — the process is the story; skip tighten on those shots.
- **Translate foreign-language speech in the subtitles** (crew/locals speaking English → Chinese
  subtitle of what they said), and turn creator facts into note captions ("太小了，放生").
- **Tighten speech, but not visual pauses.** VAD-based `tighten` shrinks pauses and cuts fillers;
  disable it (`skip_on: false`) on pans, animals, scenery — the pause is the content. Check every
  jump cut doesn't land mid-word (a reviewer caught one).
- **Fades eat speech** — check the last words of a shot aren't under a `fade_out`.
- **B-roll over talking** when the frame is boring (food close-up, parking lot) — show what the
  speaker describes (the underwater trail signs while explaining the trail).
- **Long process footage (filleting, cooking, driving) → timelapse it** (`speed: 4`, music + a
  note caption) instead of cutting it out or letting it drag.
- **Tiny animals: arrow or zoom, located on real 4K frames.** `marks` draws a labelled arrow;
  guessed positions are wrong (an orca "at the right edge" was mid-frame). Animals move — use short
  mark windows. There are usually MORE of them than a contact sheet shows; look carefully.
- **Ken Burns on distant subjects** the speaker refers to (a donkey 30 m away, cruise ships):
  locate the subject's x/y on a real frame, push to ~1.8–1.9×, verify it stays in frame.
- **Time cards for jumps** ("一小时后……", "第二天……") with a light sfx. Never use copyrighted meme
  clips (Content ID); original cards look just as good.
- Don't use internal jargon in shot `note`s — they're the creator-facing card titles.

## Audio & music

- YouTube Audio Library "no attribution required" tracks are the only claim-safe music. Record
  licenses in `edit/music/LICENSES.md`. A subagent can download them via the creator's logged-in
  Chrome (Studio's download button may 503 — the underlying file URL works).
- Music by section, crossfaded; duck under speech (subtitle intervals). Start around
  `music_volume` 0.33 / `music_duck` 0.06; montage-only stretches can feel too quiet, but the
  creator found 0.42 too loud overall.
- Don't let a track restart from the top at a section boundary unless intended (reviewer caught one).
- Final loudness −14 LUFS integrated, true peak ≤ −1.5 dBTP.
- **Loud engine/wind noise (boats, cars): let music cover it.** Silent travel shots on a boat →
  `audio: mute` (or ambient) and let the music carry; talking shots → denoise/high-pass the voice
  and keep music a bit higher than usual under it.

## Rendering

- The agent's shell is zsh: `for s in "A 1" "B 2"; do set -- $s` doesn't word-split — wrap such
  loops in `bash -c '…'` or use arrays.

- This ffmpeg has no drawtext/subtitles: all text is Pillow PNG overlays. Lay text out from the
  font's real ink box (`textbbox`) — heavy CJK faces overflow their nominal size (title/subtitle
  overlapped once).
- Bump `overlays.VERSION` whenever overlay looks change, or cached PNGs/segments silently persist.
- Per-frame zoom: ffmpeg `crop` evaluates `iw/ih` once — compute the offset from the same per-frame
  zoom expression (the push-in drifted to the top-left before this fix).
- Threads writing the same status file need a lock.
- Final master: 4K HEVC Main10 ~100 Mb/s `.mov`, graded in 10-bit, at `02 - Export/<folder name>.mov`.

## Review surfaces (pages)

- Plain Chinese, no jargon; default view shows only what's needed (keep / trim / subtitle text);
  everything else under "更多设置".
- Must feel like YouTube: controls overlay on hover, `current / total` time, space/K/arrow/F keys that
  also work in fullscreen (capture-phase key handler so native controls don't double-toggle).
- The shot list follows playback (sticky player, active card scrolled into view, pause-follow on
  manual scroll). End the list with a visible "已经到最后一段了" marker, not blank space.
- The "unsaved" flag must compare content, not fire on any input event.
- Every page gets a designed favicon and a descriptive, live tab title.

## Packaging & publishing

- YouTube thumbnails: 16:9, 1280×720+, 50 MB on desktop/API (2 MB only on the mobile app).
  Bilibili covers: 16:10 (≥1146×717), ≤5 MB — export both (`thumbnail_generator/export.py`).
- Thumbnail frames: check eyes/mouth rules on full-res frames; dark snorkel masks hide eyes.
- Keep title claims literally true (the stingrays were at Salt Pond Bay, not Trunk Bay — don't put
  them side by side in a title).
- Never print cookie/token contents to output (redirect verbose CLI logs to a file, grep results).
