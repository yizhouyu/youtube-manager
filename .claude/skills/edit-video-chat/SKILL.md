---
name: edit-video-chat
description: Auto-edit a travel vlog from a folder of raw action-cam clips — the agent watches every clip (contact sheets + whisper transcripts), picks and trims shots, writes burned-in Simplified-Chinese subtitles, adds B-roll, title cards, place tags, section-based music, and renders a finished video; the creator fine-tunes on a local review page (toggle/trim/split/reorder shots, edit subtitles) and re-renders in minutes. Use when the creator says to cut / 剪 a trip's footage. Hands off to publish-video-chat once the export exists.
---

# Edit Video (conversational, agent-first)

The agent is the editor. The **EDL** (`<project>/02 - Export/edit/edl.json`, schema in
`src/editor/edl.py`) is the single source of truth: the agent writes it, the review page
edits it, the renderer reads it. Never touch `01 - Unedited/`.

Resolve `REPO` as two levels up from this file and run everything from there.

**Before starting: read [`LESSONS.md`](LESSONS.md)** (everything past edits taught us). **After
publishing: append what this video taught** — new mistakes, creator corrections that generalize,
faster ways of working — and prune lessons the code now enforces.

## Batch mode (the creator is away / reviews later)

Do the whole first cut + QA + thumbnails yourself; don't wait on him. Render the 1080p preview only
for QA, then write `edit/HANDOFF.md` (template in the project template: status, structure with
timestamps, decisions, drops, music, thumbnail links, QA summary, open questions, how to review)
and **keep `edit/preview.mp4`** so the creator can review right away (creator, 2026-09-29); delete
`edit/previews/` and `/tmp/yt-editor/<project>`. Once the creator approves and the final render is
done, delete the preview right away; don't wait for the upload. The EDL stays the source of truth. No final render, no upload. Projects parked in a batch folder (e.g.
`~/Desktop/202512/`): **move the project folder up to `~/Desktop/` BEFORE starting it**, so its
path never changes mid-edit (don't rely on path fallbacks). Track every project in
`sessions/QUEUE.md` (local, gitignored). When he returns, per video: start the raw-footage player
→ re-render the preview → review page → apply his notes → final render → publish.

## One ASR at a time

`src/editor/transcribe.py` takes the machine-wide ASR lock itself. Wrap any other ASR run
(whisper, ad-hoc Qwen checks) with `./venv/bin/python -m src.editor.asrlock -- <command>` so
parallel editors queue instead of loading two models (16 GB Mac). Don't hand-roll the lock.

## Budget (long batches)

`python3 scripts/claude_usage.py --log "<project> start"` before a video and `... "<project> end"`
after it (appends to `sessions/usage_log.tsv`; prints 5-hour + weekly utilization, never the token).
Use the measured per-video delta to decide whether another video fits: if the 5-hour window can't
fit one more, wait for its reset; if the weekly quota is near its end, stop and leave HANDOFF notes.

## 0. Kick off in parallel

As soon as the creator hands over a folder, start these side by side (subagents):
- **Raw-footage player** for the creator, up immediately (it needs no EDL) —
  `./venv/bin/python -m src.editor.footage_player "<project>"` (port 8766): all clips back-to-back
  in capture order at 1×–3×, with the transcript line. Its job is letting the creator preview the
  raw material and grasp the whole trip; marking what the cut used is an optional toggle.
  It shows ONLY proofread captions (`src.editor.captions_clean`: EDL lines where they exist, else
  `edit/glossary.json` fixes + hallucination/filler filtering) — never raw whisper text.
- Transcription + contact sheets (below), music sourcing, and the edit itself.
- **Thumbnails too** — they don't depend on the final cut: run the publish-video-chat thumbnail
  step on raw frames (apply the EDL's color grade so it matches the video) and export both the
  YouTube 16:9 and Bilibili 16:10 files, so packaging is ready when the edit is approved.

- **Research subagent per video** (creator's ask: research freely to make each video better):
  history/context and fun facts about each place, what Chinese viewers search/ask about it
  (Bilibili/小红书 topics), correct spellings of places/dishes/animals. Output with sources to
  `edit/research.md`; use only verified facts for note captions, the 0–8 s hook, chapter names,
  title/description keywords and the comment question.

## 1. Watch the footage (deterministic layer)

- `ffprobe` every clip: duration, `creation_time` (GoPro writes the camera's local clock with
  a `Z` suffix — don't trust it as UTC; sanity-check against daylight in the frames), color
  transfer (HLG/HDR needs tone-mapping first).
- Contact sheet per clip: `fps=1/max(2,dur/12),scale=320:-2,tile=6x2` (no `drawtext` in this
  ffmpeg — label with Pillow, see how `overlays.py` loads fonts). Stack 4 clips per image and
  **look at every one**.
- Transcribe every clip with **Qwen3-ASR-1.7B (MLX)** — benchmarked best for casual Mandarin +
  English names with wind noise (beat whisper large-v3 on proper nouns, Simplified output, no
  hallucinations on silent clips): `asrvenv/bin/python -m src.editor.transcribe "<project>"
  --context "<places, dishes, names seen in frames>"` (~1 s/clip on Apple Silicon; always pass
  --context). Setup once: `uv venv -p 3.12 asrvenv && uv pip install -p asrvenv/bin/python
  mlx-qwen3-asr opencc-python-reimplemented`. Fallback: whisper.cpp large-v3 on Metal with
  `--prompt` + Silero VAD. Re-check for a newer/stronger model now and then — download it and
  benchmark on a few real clips before switching.
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
- **Time cards** for jumps in time/place ("一小时后……", "第二天……"): a shot with `card:
  {text, sub, bg}` and no clip, ~1.9 s, with a sound effect (`sfx`). Never drop in copyrighted meme
  clips (e.g. cartoon "…later" cards) — Content ID; make original cards instead.
- **Music by section** (`music: [{file, start: <shot id>}]`), crossfaded, auto-ducked under
  speech (subtitle intervals). YouTube Audio Library tracks with "no attribution required" are
  the only Content-ID-safe choice; record licenses in `edit/music/LICENSES.md`.
- **Color:** named grades in `grades`; a mild land grade and a red-restoring underwater grade
  (check a before/after frame grid before committing).

Shot `note`s are the card titles the creator reads — plain Chinese descriptions of what's in
the shot ("开场精华：魟鱼"), never internal jargon (round ids, "B-roll", "r2", QA remarks).

## 2b. Make it worth watching (retention → likes, comments, subscribes)

Evidence-based defaults (YouTube Help on retention/intro/chapters/end screens; creator-data posts —
see LESSONS.md for sources). Treat them as the bar every cut must clear:
1. **Hook in 0–8 s:** open cold on the single best moment (reveal, reaction, animal, first bite) and
   land one captioned promise/question line (e.g. "没想到这里…") by ~8 s. No logo, no title card
   > 2 s, no subscribe ask up front. Target ≥ 60–70 % still watching at 30 s.
2. **The opening must pay off the thumbnail + title** — show that promised thing early.
3. **Voice first:** speech clear or subtitled; drop/rescue wind-clipped lines; music ducked under
   speech; integrated ≈ −14 LUFS.
4. **Never > 60 s without a change** in picture or sound (new place, music section, chapter title,
   map, montage); B-roll 2–5 s, talking stretches ≤ 15–25 s; an emotional turn or 弹幕-worthy moment
   every 3–5 min.
5. **Squeeze low-energy footage** (driving, waiting, processing): ≥ 4× timelapse or a 3–6-shot
   montage ≤ 10 s with a bridge caption ("但下一站完全不一样"), or cut it.
6. **Mini-arc per location:** place title → expectation → experience → reaction/verdict. Plant one
   open question in the first 30 s and answer it near the end; save the strongest location for last.
7. **Captions narrate when people don't:** where, what, how much, what surprised us (note style);
   cut to a reaction shot after every reveal / first bite; use contrast (expected vs real).
8. **Engagement asks, placed where they work:** the comment question goes in the **description and
   the pinned comment**, not on screen. On-screen "评论区聊聊 / 你会选A还是B?" captions read stiff; the
   creator asked to drop them. A light 三连/订阅 line right AFTER the emotional peak is fine.
   Draft the comment question plainly, tied to a moment (Bilibili: "选A扣1，选B扣2"), in publish metadata.
9. **Leave the last 15–20 s for the end screen:** calm B-roll + a captioned teaser of the next
   episode, but ONLY if the next episode is from the same trip. For the last episode of a trip,
   point to that region's playlist/合集 instead. No separate outro card.
10. **Chapters = location names** (first at 0:00, ≥ 3, each ≥ 10 s) — written into publish metadata.
11. **Shorts:** note 1–3 self-contained peak moments (≤ 60 s each) in HANDOFF.md for later cut-downs.

## 2c. The creator's review checklist (what he asks for when he reviews)

Distilled from his live reviews of 83 and 84. Check the cut against this list *before* QA, and
have the reviewer check it too. Every item is something he had to ask for by hand.

**Keep more:**
- Keep the fun and the specific: animals doing things (porcupine walking), campgrounds and
  lodging with character (the RV campground), individual exhibits (the carved-animal diorama, the
  beadwork, the market scene, the other hall), and every stretch where he is talking (all the hot-spring
  pools).
- Length is not a constraint (up to ~20 min).
- Don't cut bystanders.

**Pace by motion, not by cutting:**
- Car-window scenery at 2–4×.
- Static shots only a few seconds.
- Shots with change in them (movement, action, reaction, talk, a reveal) can run long.
- Long talks (a keeper or docent) are trimmed to the highlights, not dropped.

**Explain places and people:**
- At the start of a museum or site, a note says what it is and what it exhibits.
- A key person gets a short 2–3-line intro (who they are, why they matter). Skip trivia nobody
  cares about.
- The first mention of any proper noun is bilingual — places, peoples, site terms (e.g. "圣达菲 Santa Fe", "古普韦布洛人 Ancestral Puebloans", "基瓦 kiva", "大房子 great house"). After that, Chinese alone is fine.
- When the day changes, add a day marker. When the order looks odd, a one-line reason (e.g. galleries while waiting for the museum tour).

**Name the food:** every meal gets its dishes named, identified from the frames and menus
(flautas, enchiladas, chile relleno, menudo…), plus the restaurant name when a sign, receipt,
menu or GPS lookup shows it. If it can't be found, leave it out — don't ask the creator for it.
Descriptions may name them too.

**Don't caption or label the obvious (creator, 2026-09-29):** no note captions or arrow labels for
things viewers can plainly see ("一只海鸥在喝水", a "海鸥"/"鹈鹕" arrow, "小朋友离海狮很近",
"关掉音乐，听听海边的声音"). A note or label must add information viewers don't have: a name,
a fact, a number, a correction. No prices unless they're the point of the scene.

**Captions must be what was actually said:**
- Background chatter and PA announcements are NOT captions. Before keeping a quiet line, check its
  level vs his voice and cross-check it with a second ASR.
- If his own line is too quiet to hear, mute the clip rather than caption a guess.
- When picture and speech are about different things (filming X while the docent explains Y),
  just leave it. No explanatory note.

**Look closer:** push in (Ken Burns zoom) on small animals and small exhibits, located on 4K frames.

**Music:**
- Openings must NOT be dark, eerie or harsh ("诡异刺耳"): no dramatic-ambient drones in the hook. Open bright, warm or curious.
- Fresh tracks each episode.
- No vocals, including "oh oh oh" chants.

**Tone:** calm and informative. No dramatic or gimmicky hook questions ("这座桥到底有多高？", "你敢…吗？"). The hook states what the episode covers, and comment questions are asked plainly.

**Decide craft calls yourself** (zoom, speed, trims, B-roll, music, caption wording). Ask him only
about facts only he knows.

**Open questions go into `edit/questions.json`, not a list in chat.** He can't answer "what was the
restaurant called?" before he has watched the footage. Anchor each question to the moment it is
about; it pops up beside the video on both pages (8765 cut / 8766 raw) and his answer is saved
back into the file (poll it; add questions any time, the pages pick them up without a reload):
`./venv/bin/python -m src.editor.questions "<project>" add "问题" --clip GX015467 --clip-t 1.0 [--t <cut s>] [--context "…"]`
(give either anchor; the other is filled from the EDL). `... questions "<project>" list` shows answers.

## 3. Render + review

```bash
./venv/bin/python -m src.editor.render "<project>" --preview   # 1080p → edit/preview.mp4
./venv/bin/python -m src.editor.review_server "<project>"       # http://127.0.0.1:8765
./venv/bin/python -m src.editor.render "<project>" --final     # 4K → 02 - Export/<project>.mp4
./venv/bin/python -m src.editor.render "<project>" --package   # clean numbered clips + SRT for CapCut
```

Segments are cached by content hash, so a re-render after edits only re-encodes changed
shots.

**Keep "showing" shots:** a silent 2–3 s shot where the camera clearly shows something (a sign,
a menu, an animal) earns its place — give it an editor's caption (`subs` entry with
`"kind": "note"`: soft yellow, doesn't duck music, never mixed up with dialogue).
Note captions have no speech to check against, so verify them across several frames (not one
still): counts and species of animals are easy to get wrong (a "second stingray" was actually a
small fish riding along). When unsure, stay generic ("小鱼") rather than guess.

**Viewer-critic pass (part of every QA round):** score each 30 s window 0–2 on Novelty (change
every ~10 s), Clarity (speech/subtitles, where/who/what), Momentum (arc moves or question open),
Payoff (reveal/reaction/animal/laugh), Audio health (ducking, no jumps, same track ≤ 90 s unless
intended), plus Promise for 0–30 s (peak + promise line by 8 s). A window ≤ 4/10 = boredom risk;
> 2 in a row = restructure that section. Put the score table in HANDOFF.md.

**Every video must get better than the last (creator's standing ask):**
- The reviewer doesn't only find faults: every round it also proposes 3–5 concrete *improvement
  ideas* (e.g. re-cut a B-roll run to the music beat, a route/map animation between places, a
  freeze-frame + label on a funny moment, a J-cut so the next place's sound leads the picture,
  a picture-in-picture reaction, a before/after split, animated pop-in captions for key facts).
  The editor applies the best ones and notes why others were skipped.
- **Creator-approved defaults (keep doing these):** the animated route map showing where the
  episode goes (the creator loves it), the city "postcard" title card whose letters are live
  windows onto the day's shots (loved on 91; use for a new city/trip, not every episode), freeze-frame + labels, arrows on landmarks, clock tags
  through golden hour, scale-comparison cards.
- **Outside material is allowed (creator, 2026-09-29, from ep 92):** when an idea needs more
  than the footage has (a historic photo, a map, an official diagram, a short archival clip, a
  fact card), download it and put it in. Prefer public-domain / freely licensed sources
  (Wikimedia Commons, NPS/NASA/Library of Congress, official park maps), keep it short, and
  credit the source on screen or in the description. No other creators' vlog footage or music.
- **Try at least one new technique per video — mandatory.** The creator explicitly wants every
  episode to bring something new. If the renderer can't do it yet, add it as a small
  generic, tested feature (commit + push per the repo rules).
- **Log the experiment** in LESSONS.md → "Experiments": what was tried, on which video, how it
  looked/felt (reviewer + viewer-critic scores), and whether it should become a default.

**Mandatory QA before the creator sees it:** spawn a separate reviewer subagent that watches
the whole preview (dense frame sheets), "listens" (re-transcribes the rendered audio and diffs it
against captions.srt; ebur128 loudness over time for music-over-speech, pops, holes), fixes
what it can directly in the EDL (reload before every write — the creator may be editing), and
re-renders. Round 2+: the reviewer also watches the RAW footage (contact sheets + proofread
transcripts) against the cut and restores missed moments; editor and reviewer iterate until
neither has substantive issues. Then hand the review page (port 8765, plain-language UI) to the creator. Their edits are
saved back to the EDL (with history in `edit/history/`); every recurring correction becomes a
preference in memory.

The final render also writes `edit/captions.srt` (timeline-mapped) for upload as the CC track.
Then continue with the publish-video-chat skill. After publishing: delete `edit/preview.mp4` and
`/tmp/yt-editor/<project>` (the master + EDL are the source of truth), and update LESSONS.md.

Contact sheets: `./venv/bin/python -m src.editor.scan "<project>"` → `edit/scan/sheets/grid_NN.jpg`.
