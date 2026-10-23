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

## Goal and freedom (creator, 2026-10-20)

The goal is videos that viewers love and that grow subscribers, not conformity with this file.
- **Treat this file as experience, not a template.** Try something new each episode, and say what in HANDOFF. 「不要每一个视频剪出来的风格都完全一样」.
- **Brainstorm wide.** Before deciding structure, hooks, openers, cards or Shorts, fan out several sub-agents on the strongest model with different seats. Debate, then pick.
- **His taste rules still hold:**
  - thumbnail taste;
  - captions: Arabic digits, standard Mandarin, exact words, no fillers;
  - no companion names or pet names;
  - best take only;
  - paper-style notes;
  - fast pacing with rare close-ups kept.
- **Write durable lessons back** here or into LESSONS.md.
- **This file is a floor, not a ceiling (creator, 2026-10-22, second time):** 「我不希望…skills…把你的想象力框死了」. Know his taste, then go further on your own. When a section here conflicts with a better idea for *this* video, try the idea and say why in HANDOFF. Sub-agent specs give goals + hard constraints, not recipes, and invite one idea of the agent's own.

## Batch mode (the creator is away / reviews later)

Do the whole first cut + QA + thumbnails yourself; don't wait on him. Render the 1080p preview only
for QA, then write `edit/HANDOFF.md` (template in the project template: status, structure with
timestamps, decisions, drops, music, thumbnail links, QA summary, open questions, how to review)
plus `edit/scan/clip_index.md` (creator, 2026-10-15): run `python -m src.editor.clip_index "<project>"`
(one row per raw clip: used shots → 成片 time, transcript lines left out; no viewing), then fill the last
column for every **未用** clip and every big left-out line: what it shows + why it was dropped. The
rough-cutter already watched everything, so this is its job. The 105 review notes were mostly "keep this unused bit".
and **keep `edit/preview.mp4`** so the creator can review right away (creator, 2026-09-29); delete
`edit/previews/` and `/tmp/yt-editor/<project>`. Once the creator approves and the final render is
done, delete the preview right away; don't wait for the upload. The EDL stays the source of truth. No final render, no upload. Projects parked in a batch folder (e.g.
`~/Desktop/202512/`): **move the project folder up to `~/Desktop/` BEFORE starting it**, so its
path never changes mid-edit (don't rely on path fallbacks). Each episode director's brief states
the episode's promise, the formats (16:9, plus any 9:16 Shorts), the target length range, the style
and tone rules, and the new technique to try. Track every project in
`sessions/QUEUE.md` (local, gitignored). When he returns, per video: start the raw-footage player
→ re-render the preview → review page → apply his notes → final render → publish.

## Checkpoints — mandatory for every episode (creator, 2026-10-07)

「每个重要的步骤做完以后就可以 checkpoint，这样以后如果有 agent 重新来看，又知道从哪儿开始了」. Usage limits and
context overflows cut agents off mid-edit (all five Texas directors stopped at once on 2026-10-07). So every agent
must be resumable from disk alone:
- **Start (and after any reset):** `./venv/bin/python -m src.editor.checkpoint "<project>"` prints the status table
  and **Next**. Read its notes and the HANDOFF, then continue at Next. Never redo a step whose evidence exists.
- **After each step, mark it:** `... checkpoint "<project>" done C<n> "one line: what was decided + where to look"`.
  The steps are C0 brief read → C1 footage watched → C2 research → C3 beat sheet → C4 assets → C5 first-cut EDL →
  C6 music → C7 captions proofread → C8 questions → C9 preview → C10 QA r1 → C11 QA r2 (raw restore) →
  C12 thumbnails → C13 HANDOFF → C14 cleanup. State lives in `edit/checkpoint.json`; `edit/CHECKPOINT.md` is regenerated.
- **Gotchas and half-finished work go in as notes:** `... checkpoint "<project>" note "…"`. Examples: a background
  render still running, which clips were muted and why, a decision that's waiting on the creator.
- Long single steps (QA, a big card) get a note at each sub-milestone, so a resume doesn't start the step over.
- **Master director (multi-episode trips):** keep the trip brief (`sessions/<trip>_brief.md`) and the music pools on
  disk, and add a `sessions/STATE.md` line after each phase: split/staged, directors launched, each episode verified,
  commits. Each resumed director gets one line: "check `checkpoint` status, continue at Next".
- **Publishing** has its own checklist in publish-video-chat (P-steps). Record those in the same file with `note`
  lines ("P4 YouTube uploaded <id>"), and in STATE.md, so an interrupted publish never re-uploads.


**One heavy job at a time (creator, 2026-10-09: the CPU maxed out with three parallel renders).** Renders,
stage renders, sim bakes, Demucs and whisper batches run one at a time machine-wide, ≤2 workers, under
`nice -n 10`, wrapped in `scripts/render_lock.sh <cmd…>` (waits for the lock). Parallel agents are fine;
their heavy compute queues through the lock. Put this rule in every director/QA brief.

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
  `./venv/bin/python -m src.editor.footage_player "<project>"` (port 8765, opened first): all clips back-to-back
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

**Footage from the external drive (creator, 2026-10-22).** Old episodes' masters and raws live on `/Volumes/YZY's drive/YouTube Channel/<NN - name>/`. The drive is usually not connected: ask him to plug it in, and batch the requests.
- The drive is strictly read-only. Never delete, move, rename or write anything on it.
- Copy only the seconds you need into the project.
- Record every copied clip in a source manifest (`edit/SOURCES.md` + JSON). For each clip, give the drive-relative path, file name, size and mtime, in/out, and processing params, so the cut can be rebuilt later from the drive.

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
- **Standard Mandarin, no northern colloquialisms (creator, 2026-10-15: 「不要用北方的这种语言」).** In notes, cards and TTS write 玉米穗 not 棒子, 东西 not 玩意儿, avoid 咋/啥/得劲/倍儿 and 儿化 words. (His own speech captions stay as he said them.)
- **Numbers in Arabic digits (creator, 2026-10-15: 「能用数字的地方，你就用数字」).** In captions, notes and cards
  write years, dates, ages, counts, prices, durations and centuries as digits: 1844年、9月15号、15岁、99年、
  买了4个、72个比索、0.06、19世纪. Keep Chinese only where a digit reads wrong: set phrases (一路、一下、
  一个人 as "someone", 百年老店、四成) and ordinal sequences (第一天、第二道菜). ASR writes numbers in
  Chinese, so run `python -m src.editor.digits "<project>"` (list) / `--apply` before review; it skips
  articles, ranges like 三四个, fractions, clock times and spoken prices (四块九五) — check what it lists.

## 2. Make the cut (judgment layer)

**Plan before you cut:** write a one-page beat sheet in `edit/outline.md` before the EDL. It covers
the 0–8 s hook and promise line, one mini-arc per place, the open question and where it pays off,
this episode's new technique, and the end screen. The reviewer checks the cut against it
(Deedy Das, "Opus video workflow", LinkedIn 2026-09: https://lnkd.in/p/g34Cz6pf).

**Choose the deliverable format before writing the EDL.** It is a creative decision, not an export
checkbox: state whether the footage earns a conventional 16:9 episode, a 9:16 Short, or both. A
small, mostly visual day with no natural narration usually wants a 90–180 s 16:9 micro-documentary
with an optional Short cut-down; do not pad it into a long vlog. A rich day with speech, a process,
or multiple places can earn a longer episode. Record the decision and its reason in the beat sheet.

**Choose narration to match the creator's intent.** No original narration does not by itself mean
the creator wants a silent/observational cut; follow the latest explicit direction, especially when
it corrects an earlier note. If the creator wants an observational film, let picture, location sound
and rhythm carry it. If they ask for informative narration, write location-specific, fact-checked
lines tied to the images rather than generic mood prose. Test the requested voice on a representative
line before generating the full track. Voiceover may frame the real sequence, but must never assert
a fact or event not visible, audible, or sourced.

**When the creator asks for an informative film, don't default to generic vlog narration.** Build a
place-by-place spine: identify where we are, explain one useful verified detail or piece of history,
then return to what the creator actually saw, did, or said there. Keep each fact attached to its
matching shot; cite research in `edit/research.md`; distinguish on-camera claims from independently
verified facts. If generated narration is requested, write and fact-check the complete script first,
test the approved voice on one representative line, then retain the script, voice/model settings,
audio files, captions and sources beside the EDL so the edit can be reproduced later.

Write the EDL (a small build script is fine). Craft rules that make it comfortable to watch:
- **Story:** open on the strongest moment and land the title's promise/question by 8 s; then
  establish the trip and move through clear chronological or thematic place arcs → a slow ending
  shot with a fade. Do not hold a 15–20 s montage by default: the first-8-second promise rule below
  takes precedence; extend the opening only when that specific story earns it.
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
  (fillers) go. Set `skip_on: false` on shots where the pause IS the content (pans, animals). Hand-made skips (retakes, stumbles) survive re-runs (tighten tracks its own spans in `skip_auto`), auto spans never eat a caption's first/last word, and `"tighten": false` on a shot opts it out; `--replace` = old behaviour. Re-check `pip` times on shots whose skips changed.
- **Slow motion on anything that moves → `src.editor.interp`** (RIFE frame interpolation, 2026-10-08), never plain `speed < 1`: 30 fps footage at 0.5× repeats frames and looks steppy (ep 83). `./venv/bin/python -m src.editor.interp "<project>" <clip> <in> <out> --slow 0.5` writes a graded, slowed clip and prints the EDL shot. Check thin fast edges frame by frame.
- **Vertical clips (phone / Pocket held upright) are framed, not stretched** (`fit`, 2026-10-20): default is the sharp portrait over a blurred copy of itself; `"fit": {"mode": "black"}` for dark night footage (a blur of dark footage turns muddy grey); `"fit": {"mode": "crop", "y": 0.4}` fills the width; `"x"` moves the portrait so a second vertical clip can sit beside it as a `pip` (side-by-side diptych). B-roll takes `fit` too. Test: `scripts/test_portrait_fit.py`.
- **A whole film in 9:16** (`"canvas": "9:16"`, ep 118, 2026-10-22): when (nearly) all footage is vertical and the creator wants it, cut it as a vertical film instead of framing portrait clips on a 16:9 blur. Preview 1080×1920, `--final` 2160×3840; portrait clips fill the frame (their 16:9 `fit` is ignored), landscape clips get `vfit` (blur default, `{"mode": "crop", "x": …}`). Overlays switch to the portrait layout (`overlays.V_*`): notes as a left-aligned paper chip ending at 80 % of H, a balanced wrap that breaks at punctuation (`\n` forces a break), tags top-left at 8.5 %, title block over the lower water with an optional `title.kicker` (letter-spaced Latin line), all clear of the YouTube mobile UI (bottom 15 %, right 12 %). Re-aim zooms on the full portrait frame (`x`/`y` are shares of the zoom slack: `(p*z-0.5)/(z-1)` for a subject at frame fraction p). Pips/maps: design for a compact top corner over the sky. Bump `overlays.V_LAYOUT` when a portrait layout changes (landscape caches stay valid). The review page sizes the player from the preview's own aspect. Keep the 16:9 EDL as `edl_16x9.json`. Test: `scripts/test_vertical_canvas.py`. Example: `118 - Na Pali Coast/02 - Export/edit/scripts/make_vertical_edl.py` + `voyage_panel_v.py` + `qa_vertical.py` (safe-zone report + frame sheets).
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
11. **Shorts: two per long video (creator, 2026-10-08).** Their job is to send viewers to the long video. 81–89 Shorts each got about 1.1–1.4k views, but only 2 subscribers between them and almost no lift for the long videos. In HANDOFF.md, propose 2 (plus a backup), each ≤ 60 s:
    - **Cut as open loops:** show the setup and the tension, and stop before the payoff (the ostrich at the window, but not what happens next; the queue, but not the first bite). The payoff must really be in the long video; never fake a cliffhanger.
    - **Make the two different:** one a moment (an animal, a reaction, a reveal), the other a question the long video answers.
    - **Name the series and episode on screen** (「德州 · 第 3 集」).
    - The success number is Related-video clicks, not views.
    Leave ~3 s after the last spoken line of each moment: `scripts/make_short.py`'s CTA (creator,
    2026-10-04) sends viewers to the long video through the Short's bottom-left Related-video link
    (「完整版👇 点左下角的链接」 + an arrow at that link, a bell, and the spoken 「完整版在左下角，点进去看」).
    It never talks over speech, and the build stops if the line can't fit. No 「关注」 pill. Note
    labels sit centred on their dark plate.

### 2b-data. What our own retention curves say (YouTube Analytics, pulled 2026-10-08)
Source: `sessions/research/2026-10-08/retention.md`. The samples are small (11–63 effective viewers per recent curve), but 81–86, 91 and about 70 back-catalogue curves agree on where people leave. These rules **override** the conflicting lines in §2b and §2b+ below. Re-check around 10/20, once 92–99 and the moved-map cuts have curves.
1. **0:08–0:30 is live content only.**
   - After the hook, go straight into the first place's best live moment: someone talking in the moment, an animal, a bite.
   - The route map, the postcard title, title-over-B-roll, a sped-up drive and setup talk ("我们今天参加了一个团…") all move after the first scene, about 0:30–1:00, as the bridge into place 2.
   - The creator loves the map and the postcard, so this is placement, not removal. If one must stay up front, keep it ≤ 3 s.
   - Evidence: 85's map at 0:09 cost −22 pts in 7 s; 86 lost −41 pts in 8 s over the title road plus a 6× drive. The same beats mid-video cost nothing. Recent cuts keep a median 38% at 0:30; the back catalogue keeps 53%.
2. **No drives, speed-ups or logistics before about 1:00.** Mid-video they're harmless.
3. **The hook is live voice plus the moment itself.** A mute 2-s highlight reel bleeds. If a montage stays: ≤ 3 clips, each with live sound or a person in frame. 82 (voice + the fish at 0:00) held 65% at 0:30.
4. **Show a slice of the promised payoff in the first minute.** Viewers scrub forward to it.
5. **End soon after the final payoff.**
   - The like/subscribe line goes in the last seconds or nowhere. On 86, a 三连 line right after the answer lost ~80% of the remaining viewers within 8 s.
   - The outro (recap + teaser + end-screen card) is ≤ 10 s, with the end-screen elements (they need ≥ 5 s) over the last real shot or the themed card.
   - End screens sent 1 view to 81–99.
6. **Keep the freeze-frame question cards; use them as mid-video re-hooks.** They show bumps and never drops.
7. **Mid-video talk length shows no measurable effect.** Spend trimming effort on the first minute.

### 2b+. Craft rules from the 2026-10-01 research (Chinese and English creators, retention, audio)
Sources and evidence: `docs/`-style reports kept locally (zh-creators, en-creators, retention-packaging,
audio). Our own Bilibili data shows 35–48% of viewers leave almost at once. These rules are starting
values to test, not laws.

**Opening and shape**
- **Fast open, slow middle.** The first minute is cut tighter: about 2–3.5 s shots. The middle breathes: a median of 4–5 s, and long holds on vistas are fine. That's how the calm creators (Links, BBG, 星球研究所) do it.
- **Live voice or the thumbnail's moment within 3–5 s.** Then a calm one-line promise, stated as a contrast and not a dramatic question.
- **Optional title beat.** A postcard or title montage is allowed only if it lasts ≤10–12 s. No mute "here's everything we'll do" trailer: that's non-progressive.
- **Show the thing first, explain second.** When a TTS line or caption explains a place, the picture shows that place.

**Inside each place**
- **Mini-arc:** arrive → look → one small turn (a surprise, a verdict, a problem) → an exit line.
- **Cut to one of us** looking or reacting at least every 3–4 scenic shots.
- **One comparison per place** to something Chinese viewers already know (a distance, a height, a famous Chinese landmark or dish). Only when it's accurate.
- **Maps that make a point:** two pins and the straight-line distance or time, not just a route.
- **Breathing room:** after 45–60 s of talk, an 8–15 s music-only or natural-sound break, plus one planned 2–4 s silence or ambience moment per place.
- **Travel between places:** a quiet montage of about 1–1.5 s shots, or stepped speed-ups. Never a flat long fast-forward.

**Ending**
- **End where the hook began:** answer its question or return to its place, then one calm reflective line.
- Time the music to end on its own final hit at the last frame.
- At most one engagement ask, with a reason. Keep the end screen ≤15 s.
- Calm creators often end on a short slideshow of our own photos. Try it once.

**Narration (TTS)**
- **Amount:** at most about 15–20% of runtime, and ≤4 汉字 per second of its picture window (Yunxi at −5% speaks about 4.7–5/s, so leave slack).
- **Placement:** enter ≥0.3 s after a cut, finish ≥0.5 s before the next speech, and leave ≥1.5 s between lines. Lint checks the 字/s and the 0.3 s; the renderer sets the level (see §3 Audio pipeline).
- **Content:** say what the picture can't show, and keep it plain. No 煽情 mood prose.

**Transitions and grade**
- Transitions come from the camera: match cuts on darkness or direction, whip-pans. No plug-in spins, warps or whooshes on static cuts.
- Keep the grade light and consistent.

**Series**
- Name each trip as a series and number its episodes everywhere: titles, covers, end screens, 合集.
- Give each episode a one-line catch-up and foreshadow the next stop.

**Trials (creator, 2026-10-01; log the results in LESSONS)**
- **Rejected:** the letter frame (「亲爱的朋友…」, P.S. cards). He said it feels fake; don't use it.
- **Trying:**
  - a photo-slideshow ending at a trip finale;
  - trip-series day markers (「…· 第 1/3 天」);
  - one plain reflective closing line at a trip finale.

### 2b-style. Borrowed craft from lemo-opuscar + huashu-art-motion (creator, 2026-10-22: 「学到的点也可以运用在以后的视频里」)
Full notes: `~/Desktop/AI Showcase/playbook/references/{lemo-opuscar,huashu-art-motion}.md`. Use them as experience, not a checklist; pick what fits the episode.
- **Judge in this order: sound → rhythm → camera → directing.** Pretty frames are the starting point.
- **Every visible action has a sound** matched to its material (door, splash, footsteps, card snap); cards and maps get foley, not silence.
- **Pauses, not dead air:** a held breath before the key sound/line works, but the creator hears a full music dropout (123 trailer, 1.7 s at −65 dB) as 「断档」. Duck/filter the music or bridge with a real sound; any true silence stays <0.4 s. **≥2 sound-led transitions** (J/L cuts).
- **Cuts on the beat grid** in music-only montages; to speed up, shorten segments instead of a faster track; land the reveal on the downbeat.
- **Reading time:** on-screen text ≥ CJK chars ÷ 4.5 + 1.5 s; captions ≥ max(1.8 s, speech + 0.6 s).
- **One signature move per film** (an opener style, a match cut, a stamp), placed at the emotional peak; the ending echoes the opening.
- **Transitions from the material itself** (ink, paper, water, the trip's own texture) rather than generic wipes; design one frame right before animating it.

## 2b-copyright. Copyright risk in clip audio (creator, 2026-10-08)
Every episode keeps `edit/copyright_risk.md`: one line per shot that has audible music, with its class and what was done.
- **Certain risk → fix it without asking:** recorded music, especially with vocals: car stereos, shop or restaurant speakers, a DJ, arena or PA songs.
  - Mute the shot, or use a Demucs voice stem (`audio_src`) when the speech must stay.
  - Verify with whisper on the stem *and* the mix that no lyrics remain.
- **Street and ambient → keep, just list it:** traffic, crowds, buskers, a street barrel organ, music drifting from somewhere. The creator: 「路上的、街上的声音，不消的话也没关系」.
- **Unclear → flag for the creator** in `questions.json`: staged live performances, or long stretches of a recognisable tune.

## 2c. The creator's review checklist (what he asks for when he reviews)

Distilled from his live reviews of 83 and 84. Check the cut against this list *before* QA, and
have the reviewer check it too. Every item is something he had to ask for by hand.

**From the 111 review (2026-10-20):**
- **A term he says gets its gloss in the caption, in parentheses**, not as a top note: 「这边是 residential dining（住校学生的食堂）」, 「MAI Building（Main Building 主楼）」. Top notes are for facts he didn't say (history, numbers).
- **Don't over-trim the walk.** The pace pass cut too much of his commentary: he restored about 15 short lines (fields and parking lot, the 2nd/3rd floors, the dorm entrance, the March study line, the police, CVS/Wells Fargo, new buildings downtown, the crowd under the bridge). Cut retakes, fillers and dead air, but keep every complete observation he makes.
- **Only caption his own speech.** Background speakers (「很酷吧？」) and unclear staff lines get no caption.
- When a sign's time is when *we* saw it, say so (「下午3:38 我们吃完出门时…」), not as if that's when it happened.
- No on-screen map credit (see the route-map section).

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
- Word order: when locals and signs use the English name (Point Loma, Cabrillo, Arch Rock, Malibu Seafood), put English first: "Point Loma 洛马角". Keep an established Chinese name first when one is standard (约书亚树国家公园, 洛杉矶机场 LAX).
- When the day changes, add a day marker. When the order looks odd, a one-line reason (e.g. galleries while waiting for the museum tour).

**Name the food:** every meal gets its dishes named, identified from the frames and menus
(flautas, enchiladas, chile relleno, menudo…), plus the restaurant name when a sign, receipt,
menu or GPS lookup shows it. If it can't be found, leave it out — don't ask the creator for it.
Descriptions may name them too.
Use plain food words ("美食中心" for a food court, "牛肉" not a guessed cut); no fancy menu prose.

**One spoken sentence = one caption (creator, 2026-10-01).** If a complete sentence is split across two or more caption cues, merge them into one cue, joined with "，". This applies to ASR fragments like "现在我们来到了 Caltech" | "加州理工大学", and to "因为…" | "所以…" | "但是…" chains. A line holds about 28 汉字, and two lines are fine. The renderer wraps at clause commas, so a line never breaks mid-word. Keep genuinely separate sentences (a question and its answer, a new thought) as separate cues.

**Chinese places stay Chinese only (creator, 2026-10-02).** Names of places in China (苏州, 北京, 故宫…) need no English or pinyin gloss. English-first and bilingual naming is for places abroad.

**Subtitles are only what people said (creator, 2026-10-02).** White speech captions carry only the creator's and other people's real speech. TTS narration text and the editor's explanations go in the yellow note style (`kind: "note"`), never as a white speech subtitle.

**When something is said twice, keep the best take (creator, 2026-10-02).** Drop the other take entirely. If the first take's picture is useful, it can serve as B-roll under the kept take, muted.

**English speech gets a Chinese caption (creator, 2026-10-01).** When someone speaks English on camera, caption the Chinese translation only. No English caption line, and no English line with a （中文） gloss: the English subtitle track covers foreign viewers. Navigation or GPS voice prompts get no caption at all.

**Lessons from the 95 live review (creator, 2026-10-02), on top of the rules above:**
- **Fix the ASR, not just the timing.**
  - Check every caption against what was actually said: pronouns (我们 vs 我), homophones (松树→松鼠), and wrong words (但又被他就是被 → 但是因为被).
  - Drop filler-only lines (这么 / 还有什么 / 就是).
  - Cut stumbles out of the *audio* too, keeping only the clean words ("现在变成了是一个一个什么…一个楼" → 现在变成了地震学的楼). Find the cut points by test-joining candidate in/out points and re-transcribing.
- **Keep the unique moments.** He restored every "boring-looking" shot that showed something new: a courtyard, a path down from a building, a toy that jumps when pressed, the lake at a garden entrance, a "these buildings are all called Laboratory" observation. Trim repetition, not novelty.
- **Arrows:** never on subjects viewers can already see (squirrels, their tails). If a moment matters, zoom in slowly instead (a squirrel standing up).
- **Explain names people say.** When the speaker names a person or old name (Millikan), add who it is in a title sub-line. A historic photo of *that same place* (Millikan Library, 1967) is welcome.
- **Outside material must match what's on screen and be familiar to Chinese viewers.**
  - **Original names next to unfamiliar Chinese ones (creator, 2026-10-23, 120):** for films, places, dances, foods and instruments, write the Chinese name followed by the original English or local name, e.g. 《海洋奇缘》Moana, 莱伊 Lāʻie, 科奥劳山脉 Koʻolau Range, 草裙舞 hula. 「有些不太熟悉的中文里可以放它的英语原版名字…除了电影以外…比如地点」. Balance it (#86): common names such as 斐济, 萨摩亚, 夏威夷 stay Chinese-only. Give the original only at the first mention and only when it's genuinely unfamiliar. Keep notes ≤26 chars.
  - **Film/TV references (creator, 2026-10-22, 121):** only titles most Chinese viewers know (Jurassic Park, Moana, Pirates of the Caribbean…). He cut 「1953年《乱世忠魂》…在这个小海湾拍摄」: 「我不知道这个电影是什么…要放那些大家都知道的电影」. If a location's film fame rests on an obscure title, leave it out.
  - A cast photo next to a building looked random.
  - A US TV show most viewers don't know (Parks and Recreation) was cut entirely, line and picture.
  - Prefer references the audience knows; otherwise leave it out.
- **No calendar dates on screen** (12月26日 etc.): not in titles, cards or route maps. A clock tag can stay.
- **Music mood:** nothing eerie or mystical under a calm campus walk. Use light or bright tracks there.
- **Pacing:**
  - Shorten drive-in or approach shots by 1–2 s.
  - Trim the waiting between a setup and its payoff (squirrels: "什么意思呢" → the fight).
  - Hold a little longer on small payoffs (the toy jumping).
- **Quiet mumbling:** if the speech after a good line is too soft to caption, keep the good line, then mute the rest and let the music play.
- **Caption length:** one sentence = one cue, but a cue wider than one line splits at its middle comma into two cues.

**Don't caption or label the obvious (creator, 2026-09-29):** no note captions or arrow labels for
things viewers can plainly see ("一只海鸥在喝水", a "海鸥"/"鹈鹕" arrow, "小朋友离海狮很近",
"关掉音乐，听听海边的声音"). A note or label must add information viewers don't have: a name,
a fact, a number, a correction. No prices unless they're the point of the scene.

**Caption lines must be whole phrases (creator, 2026-09-29):** never split a caption mid-phrase
("…叫 Taste of Hunan" / "的餐厅吃完了午饭", "…看到太平" / "洋的…"). ASR segments often break at
English words or pauses; merge adjacent pieces when the next starts with 的/了/们 or completes a
name, as long as the line fits (~24 CJK chars); otherwise split at a natural clause boundary.

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
Write every note, card and label like a knowledgeable guide explaining calmly, in whole sentences.
Avoid AI-isms: strings of short punchy fragments, stacked numbers, "不是…而是…", dash-heavy lines,
and hype words (绝了 / 太震撼了 / 简直) (Deedy Das, LinkedIn 2026-09).

**Decide craft calls yourself** (zoom, speed, trims, B-roll, music, caption wording). Ask him only
about facts only he knows.

**Open questions go into `edit/questions.json`, not a list in chat.** He can't answer "what was the
restaurant called?" before he has watched the footage. Anchor each question to the moment it is
about; it pops up beside the video on both pages (8765 raw / 8766 cut) and his answer is saved
back into the file (poll it; add questions any time, the pages pick them up without a reload):
`./venv/bin/python -m src.editor.questions "<project>" add "问题" --clip GX015467 --clip-t 1.0 [--t <cut s>] [--context "…"]`
(give either anchor; the other is filled from the EDL). `... questions "<project>" list` shows answers.

## 2d. Note + tag fact-check pass — before the FIRST preview (creator, 2026-10-22: 「以后能不能做到第一遍就改对」)
Every yellow note and place tag gets checked against **the frame on screen at that moment** and
**a source**, before the creator ever sees the cut. Pull a still at each note's start and end and
each tag's first frame, read them, and fix:
1. **Picture match.** The note describes what is visible *while it is on screen*; trim t1 so it ends
   before the picture changes subject. Place tags match the sign/building actually in frame (ep 120:
   the tag said 奥特亚罗瓦 while a TONGA gate was on screen).
2. **What things are.** Name objects from the frame, not from memory (ep 120: "poi with dried fish"
   was wooden tasting sticks; "石像" moai are a concrete-like material per the site).
3. **Precise wording.** Category words must be true (Hawaiʻi/Aotearoa aren't 岛国 → 岛屿文化);
   translations of native terms only if a source agrees on them.
4. **Contested numbers → ranges.** If two sources disagree (70 % vs 80 %, 300 vs 450 mantas), write
   大多 / 几百 instead of picking one. No claim that only a tour operator makes.
5. **Add the interesting why.** Prefer meaning/origin/how-it-formed over a bare label (Kualoa = one of
   Oʻahu's most sacred places; fire-knife dance grew out of the war-club dance).
6. **Length and layout.** ≤ ~26 characters; first mention of a place gets its local name once
   (莫科利伊 Mokoliʻi); no overlap with speech captions or tags (lint).
7. **Sources** for every fact go into `edit/research.md` (URL + one line); unverifiable → leave it out.
Record the pass in HANDOFF ("notes checked: N kept, M fixed"). The independent QA reviewer re-checks a
sample against frames.

## 3. Render + review

```bash
./venv/bin/python -m src.editor.render "<project>" --preview   # 1080p → edit/preview.mp4
./venv/bin/python -m src.editor.review_server "<project>"       # http://127.0.0.1:8766
./venv/bin/python -m src.editor.render "<project>" --final     # 4K → 02 - Export/<project>.mp4
./venv/bin/python -m src.editor.render "<project>" --package   # clean numbered clips + SRT for CapCut
```

After both local review servers are running, open the first-look/raw-footage page (8765) and
then the cut page (8766) in the creator's visible Chrome window on macOS instead of relying on
a browser-automation tab:

```bash
open -a "Google Chrome" "file://<project>/02 - Export/thumbnail/editorial.html" "http://127.0.0.1:8765/" "http://127.0.0.1:8766/"
```

Creator order (2026-10-09): cover/thumbnail page first, then 8765, then 8766. Use the exact port assignments in that episode's `edit/HANDOFF.md` if they override the defaults.
Opening the URLs does not start either server or the chat listener.

**Hover thumbnails (creator, 2026-10-21).** Both pages show a YouTube-style frame preview + time while
hovering/dragging the timeline (8766: the native seek bar and the slim bar under the picture, which also
seeks on click/drag, plus the shot under that time; 8765: the whole-trip bar). Sprites come from
`src/editor/storyboard.py`, made lazily in the background (one job at a time across both servers, nice'd,
VideoToolbox decode — ~15–20 s wall / ~2.5 s CPU for a 5-min 1080p preview) and cached in
`edit/.storyboard/<preview name>/` and `edit/.storyboard/raw/<clip>/`, keyed by file size+mtime, so a
new render regenerates on its own. Until ready the tip shows only the time. Safe to delete the folder.

**Review chat (creator, 2026-10-01).** Both pages have a "和 Agent 聊" box. Its `chat watch` heartbeat
is runtime-neutral and works from Claude Code or Codex; `chat reply` detects the active runtime and
labels replies accordingly (`CHAT_AGENT=claude-code|codex` overrides detection when needed).
- **What it carries:** each message he sends records where he was (raw clip + time, or cut time). The messages are stored in `edit/chat.jsonl`.
- **Prep lazily (creator, 2026-10-15):** read an episode's sheets/clip index only when its 审片 starts, not ahead of time.
- **Brief yourself before every 审片 (creator, 2026-10-15):** the rough cut is often made by another agent, so the agent who chats with him may not know the video. Before opening the pages: read the episode's `HANDOFF.md` (structure table, cards, open questions), then re-run `python -m src.editor.clip_index` (EDL may have changed; reasons are kept) and read `scan/clip_index.md` and skim the rough-cutter's existing `scan/sheets/grid_*.jpg` (already low-res, ~320 px/frame; never regenerate raw sheets), plus a coarse contact sheet of the preview (`ffmpeg -vf fps=1/20,scale=320:-1,tile=6x5`, ~30 frames), and write 5–8 lines to `edit/review_brief.md` (spine, key sections with timestamps, cards, what's unresolved). Then start the chat watcher (`Monitor` on `chat … watch`). Re-read the brief when he asks about a moment.
- **Open all three pages yourself (creator, 2026-10-03; order set 2026-10-08).** When review starts or moves to the next episode, `open` these right away, in this order:
  1. the episode's cover page, `thumbnail/editorial.html` or `review.html`;
  2. the raw page, 8765;
  3. the cut page, 8766.
  
  Before that, confirm `scan/.proofread` exists. Starting servers without opening the pages counts as not done.
- **Two buttons (2026-10-02):** 「评论」 (Shift+Enter) stores a note as pending (`status: "pending"`, tagged 「待交给 Agent」 on the page); Option+Enter is a newline. 「交给 Agent」 (Enter, or Cmd+Enter) hands over the typed note plus all pending notes as one batch. Pending notes never reach `watch`: he is still collecting, so don't act on them (`tail` marks them `[待交]`).
- **Watching:** while he reviews, keep a Monitor running `python -u -m src.editor.chat "<project>" watch`. Re-arm it every 30 min. It prints `CHAT #id [where] text` for a single note and `CHAT BATCH b3 (3 条): #5 [..] a ‖ #6 [..] b ‖ …` for a batch. Treat a batch as one review pass: apply all of it, re-render once, then reply once.
- **Note times are links (creator, 2026-10-15):** clicking 「成片 m:ss」/「原片 …」 on a creator note jumps (2 s lead-in) to the same moment in the preview on screen, mapped through `src/editor/locate.py` (each preview render writes `previews/meta/<preview>.json`; older previews fall back to `edit/history/`). Label shows 「→ 现在 m:ss」, plus 「附近」/「已删，下一段」 when the shot changed. In replies, still give the new 成片 times.
- **Quick phrases (creator, 2026-10-15):** chips above the chat box put a phrase he says often into the box (Enter sends). The list is `QUICK_PHRASES` in `src/editor/chat.py`; add a phrase when he repeats one across reviews.
- **Pending 评论 can be edited/deleted** (编辑 / 删除 on the note) until 「交给 Agent」; deleted notes stay in chat.jsonl as `status: deleted` tombstones and never reach `watch`. After changing chat.py, restart the watcher (an old watcher process announces tombstones).
- **Replying:** answer with `python -m src.editor.chat "<project>" reply "…"`, so he never has to switch back to the terminal.
- **Acting on notes:** apply a note, re-render, then reply with what changed and the 成片 timestamps. **Re-render right away after each note or batch (creator, 2026-10-15: 「我觉得你预览可以直接更新」)** — don't hold changes back to batch them; he checks a fix in the preview right after you say it's done. Say "渲染中" until the new preview is up.


Segments are cached by content hash (video and audio separately), so a re-render after edits
only re-encodes changed shots, and an audio-only change re-renders PCM only.

**Audio pipeline (since 2026-10-01; details and measurements in LESSONS.md → Audio & music):**
- **Master:** measured linear gain to −14 LUFS → 4×-oversampled limiter → AAC (AudioToolbox) →
  the AAC is decoded and measured; too hot a true peak lowers the ceiling, loudness off by > 0.3 LU
  corrects the gain (≤ 4 tries). `edit/render_status.json` → `audio` holds `I`, `TP`, `LRA`,
  `gain_db`, `ceiling_db`, `iterations`, `ok`. **QA reads these instead of re-measuring:** fail if
  `TP` > −1.5 dBTP or |`I` + 14| > 0.5. `"master": "loudnorm"` in the EDL brings back the old chain.
- **TTS / narration:** put the edge-tts output in `edit/tts/` as it comes (MP3), or trimmed as WAV.
  Never re-encode it to MP3, and don't loudnorm it. The renderer runs every `voiceover` line,
  and any `tts/` file used as a shot `sfx`, through a VO chain: high-pass, EQ, de-ess, compressor,
  limiter. It then levels the line to the episode's on-camera speech loudness + 0.5 LU. **Don't
  set `gain` on new lines.** For a manual level use `gain_db` on the entry (absolute dB). To move
  all lines use `vo_offset_lu` on the EDL. Per-line levels are in `render_status.json` →
  `audio.voiceover.lines`. Old EDLs' fixed `gain` values only keep their differences between lines.
- **Dialogue levelling (automatic, render time):** each talking shot's captioned speech is measured. A shot more than 3 LU
  from the episode median is pulled to that band (−6…+8 dB). Nothing is written to the EDL; the plan is in
  `render_status.json` → `audio.dialogue_level`. Your `gain_db` still applies first, as an offset. Opt out with
  `"level": false` on a shot (e.g. a deliberate shout or whisper) or `"dialogue_level": false` on the EDL. Captions must be
  right for this to work: a shot without speech captions isn't measured.
- **Boosted shots** (manual + levelling gain > 0) get an automatic peak limiter 12 dB above their own loudness.
- **Cuts crossfade:** every cut and `skip` join on the dialogue/natural-sound track is a 40–60 ms
  equal-power crossfade, using 30 ms of real source sound past each edit point. There is no more
  dead gap at a cut. Video cuts are unchanged. The handle only exists if the source runs on: GoPro
  clips still need out-points 0.1–0.3 s before the clip end (stop click).
- **Lint** warns about a narration line over 4 字/s of its window or starting < 0.3 s after a cut
  (`"jcut": true` if deliberate), more than 60 s of talk without a ≥ 4 s music/natural-sound break,
  and more than 3 sfx in a minute. Treat these as review prompts, not errors.

**Comparison masters must be isolated.** When the creator asks for a distinct creative version,
never overwrite the original `edl.json`, preview, cards, or master. Write the alternate EDL, then
run `scripts/render_variant.py <project> <variant-edl> --output <destination>.mov`; it symlinks the
protected raw media into a staging project, copies edit assets, renders a 4K master, and copies the
master + captions + exact EDL + manifest + version-scoped dependency assets to the destination.
The tool must preflight every destination before rendering and fail closed if any output exists; use
a new versioned filename for revisions. Never write into `01 - Unedited/` or the source `edit/`
folder. Re-open the delivered EDL against its saved assets as a reproducibility check. A 1080p
preview is only an internal QA proxy.
When the creator asks for a comparison deliverable in 4K, the linked result must be the 4K `.mov`,
not the proxy.

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

**Review panel: a viewer + a peer director, before the creator's 审片** (creator, 2026-10-22: 「让小弟来当观众…写进整个工作流」, then 「一个是 YouTube，一个是你的同行导演」). Run it after the QA reviewer. Two sub-agents work in parallel from `audience_panel.md` (next to this file):
- **The viewer** is a Chinese-speaking YouTube viewer new to the channel. Returns scores, swipe-away and lean-in moments, packaging (title and cover vs. the first 30 s), the questions people would ask in comments, and misleading notes.
- **The peer director (同行导演)** is a fellow travel-vlog editor. Returns raw-footage moments to **add**, giving the clip, the second and where each goes, plus trims, and at least 5 concrete craft ideas: transitions, effects, graphics, music, sound, structure. One bold idea is welcome.

You direct, the panel advises.
- Adopt **additions**, not only cuts.
- Try at least one of the director's craft ideas each round, unless it's clearly wrong for this episode.
- Record decisions and scores in HANDOFF under "Panel round". Keep the reports in `edit/qa/panel_*.md`.
- After every run, improve the brief with what you wanted to know but didn't get, and log the change in its changelog.

First runs: 123, 120, 121 (two viewer seats, v1–v5); 122 (v4).

**Where the panel sits** (creator, 2026-10-22). His workflow:
1. I rough-cut.
2. He reviews which raw clips I kept (footage player) and gives feedback.
3. I update, and he watches the preview right away.

So **both seats run on the rough cut, before he looks at the selection.** The director checks additions, cuts, structure and craft; the viewer checks swipe-away points, clarity, misleading notes and packaging. Apply what you agree with, re-render, and only then hand him the selection. 「我会希望你在一开始就其实有过跟小弟的思考，不用等到我看预览之前」.

- **His selection feedback overrides the panel.** Record any panel suggestion he overrode in HANDOFF under "decided by creator", and tell later panel runs those points are settled.
- **After his feedback:** update and render the preview at once. Don't run the panel again before he watches; do your own objective QA only (levels, typos, notes fact-check §2d). Both 123 viewers scored it 5/10, which led to the opening, pace and wall changes.

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
- **Route maps follow real roads (creator, 2026-10-02, ep 96: 「地图做得非常不错…以后也可以保留」).**
  A straight dashed line between stops doesn't read as driving. He rejected it on 96, and the
  rebuilt map was praised. Every route map from now on:
  - draws a real OpenStreetMap base: an Overpass extract saved to `edit/outside/osm_<place>.json`,
    with coastline/land and a road layer, main roads warm orange;
  - routes each leg as a shortest path on the OSM road graph, respecting one-ways;
  - draws an out-and-back on the same road as two parallel dashed lines, offset to the right of travel;
  - has numbered pins that pop in as each leg arrives, plus the time sub-labels;
  - has **no on-screen credit** (creator, 2026-10-20: 「以后的视频也都不用写」). `CREDIT` defaults to ""; the OSM credit goes in the video description instead (publish-video-chat).

  Don't copy episode scripts any more; use the shared module `src/editor/routemap.py`. Write
  `edit/maps/route_config.json` and run it from the repo:
  `./venv/bin/python -m src.editor.routemap "<ep>/02 - Export/edit/maps/route_config.json" fetch route`
  (`fetch` caches the Overpass extract in the `"osm"` path, so later runs only need `route`; `legs`
  prints each leg's km and roads for a quick check). Its defaults give the ep 96 look; the full
  example is `examples/routemap_malibu.json` (ep 96; its `osm` path points at that episode's extract, so re-run `fetch` for a new place), and the keys are documented in
  `render_route` / `DEFAULTS`.
  - Change only `stops` (cn, sub, lat, lon, `side` up/upright/upleft/down/left/right, `halo` sea
    for labels over water), `bbox` plus `frame`/`fit`, `title`, map `labels` and `spans`.
  - Each leg's `mode` is `drive` (one-way aware), `walk` (trails, footways and steps, ignores
    one-ways) or `straight`. `via` points force a road choice.
  - Optional: `panel` (ep 103-style left list of stops), `flight` (plane arc home, or
    `"style": "arrow"` for an off-map continuation), `colors`, `size`, `dur`.
  - Walk legs need footpaths in the extract. The default `fetch` adds `paths` whenever a leg is walk.
  - The fetch uses a generic User-Agent; never put personal info in it. Coordinates stay in the
    episode config, never in the (public) repo.
  Exception: a multi-day *overview* sketch (e.g. a trip-recap end screen showing which days went where) may keep straight lines. The creator: 「如果只是想要大体上展现我们去了哪里的话，用直线也是 OK 的」.
- **Outside material is allowed (creator, 2026-09-29, from ep 92):** when an idea needs more
  than the footage has (a historic photo, a map, an official diagram, a short archival clip, a
  fact card), download it and put it in. Prefer public-domain / freely licensed sources
  (Wikimedia Commons, NPS/NASA/Library of Congress, official park maps), keep it short, and
  credit the source on screen or in the description. No other creators' vlog footage or music.
  **Bilibili (creator suggestion, 2026-10-01).** It's a good place to *find* references and ideas. Most uploads there are other people's copyrighted work, though: re-uploaded TV and film clips, and other creators' vlogs. Using those risks Content ID claims and takedowns on both platforms.
  - **Allowed:** download from Bilibili only when the uploader clearly licenses reuse (e.g. CC marked), or it's official public-domain or press material, or it's the creator's own upload.
  - **Otherwise:** use Bilibili to identify what to show, then source a licensed equivalent (Wikimedia Commons, official press kits, PD archives).
  - **Update, same day:** the creator allows **short clips (≤ about 5 s)** from Bilibili **or any other site** (YouTube, news sites, archives…) when they add real context, such as a TV show, film, documentary, news or archival moment about what we're showing.
    - Credit the source on screen and in the description.
    - Log every use in `edit/outside/bili/CREDITS.md` so a clip can be swapped if it's claimed.
    - Don't use other travel vloggers' own footage.
    - Download only the segment: `yt-dlp --download-sections "*s-e"`.
  Short video clips may come from YouTube via `yt-dlp` only when the watch page says "Creative
  Commons Attribution": keep them ≤ ~10 s, credit the uploader on screen and in the description,
  and expect that Content ID can still claim a CC re-upload (Deedy Das, LinkedIn 2026-09).
- **Try at least one new technique per video — mandatory.** The creator explicitly wants every
  episode to bring something new. If the renderer can't do it yet, add it as a small
  generic, tested feature (commit + push per the repo rules).
- **TTS voice (creator-approved 2026-10-01):** edge-tts is the approved tool. The default is `zh-CN-YunxiNeural`, `--rate=-5%`. The editor may pick another edge-tts voice when a scene suits it (e.g. a warmer female voice, or a multilingual voice for English-heavy lines; audition with `scripts/tts_voices.py`) and should say why in HANDOFF. Use it as a voiceover layer with the music ducked; leave its level to the renderer (auto-matched to on-camera speech). Write names locals say in English as the TTS should say them (it reads "Nassau" as "NASA"). Keep lines short, factual and place-anchored, and re-transcribe the mix to check them.
- **Generated media is an editorial component, not invented evidence.** Original music, brief TTS,
  and clearly illustrative/motion-graphic transitions are allowed when the creator asks for them;
  real locations, dishes, people, actions, animal behaviour and history still come from the actual
  footage or sourced material. Do not use generative video to fake a travel moment. Keep generated
  audio/visual assets in the project, document their role in HANDOFF.md, and treat them as preview-only
  until the creator accepts them. If a media tool requires an interactive consent flow, do not retry
  or work around it; continue the real-footage cut and report the optional asset as blocked.
- **Animatic before the full render for new motion cards:** render 3–5 keyframe stills first
  (start, mid-build, text fully in, end) and look at them at full size. Encode the `card.image` mp4
  only after those stills pass. Overlaps, black corners and cut-off text are cheap to fix at this
  stage (Deedy Das, LinkedIn 2026-09).
- **Log the experiment** in LESSONS.md → "Experiments": what was tried, on which video, how it
  looked/felt (reviewer + viewer-critic scores), and whether it should become a default.

**Mandatory QA before the creator sees it:** spawn a separate reviewer subagent that watches
the whole preview (dense frame sheets), "listens" (re-transcribes the rendered audio and diffs it
against captions.srt; ebur128 loudness over time for music-over-speech, pops, holes), fixes
what it can directly in the EDL (reload before every write — the creator may be editing), and
re-renders. Round 2+: the reviewer also watches the RAW footage (contact sheets + proofread
transcripts) against the cut and restores missed moments; editor and reviewer iterate until
neither has substantive issues. Then hand the review page (port 8766, plain-language UI) to the creator. Their edits are
saved back to the EDL (with history in `edit/history/`); every recurring correction becomes a
preference in memory.

**Independent strong-model QA, then upgrade passes (since 2026-10-08).**
- **When:** after the director's own QA rounds, run one more QA as a **fresh agent on the strongest model** (brief: `templates/briefs/qa_brief.md`). Before 2026-10-08 the "round 2" was often the director reviewing its own cut, or a cheaper-model reviewer, and both missed real errors.
- **What it must do:**
  - **Full-mix whisper diff:** whisper large-v3 on the rendered talk segments. Also run Demucs on the mix and transcribe its vocal stem, so a song under the speech can't hide.
  - **Second-model cross-check with speaker labels:** run `./venv/bin/python -m src.editor.xcheck "<project>" preview` (MOSS-Transcribe-Diarize). It diffs every caption against what MOSS hears, flags a voice change inside one caption, and lists uncaptioned speech; decide each flag by listening.
  - **Pronouns: 他 / 她 match the person in frame** (100's guide was a woman, but the captions said 他).
  - **Who speaks, judged by pitch and faces.** It was wrong on 104, 108 and 109.
  - **Names checked against official rosters and sources.** Animals, places and dishes were wrong on 102 and 111.
  - **Timers and counts re-measured on full-frame-rate crops.**
  - **A raw-restore pass:** compare the raw footage with the cut and bring back what was dropped by mistake.
  - **The §2b-data opening and ending.**
- **Unreviewed rough cuts that fall behind a newer bar get an "upgrade pass" with the same brief.** It must never undo what the creator or earlier QA decided.

**A permission check refused an action?** (The auto-mode classifier blocked 109's EDL reorder on 2026-10-08.)
- Don't retry or work around it, and don't hand it to another agent.
- Write the planned change and the backup path into HANDOFF and a checkpoint note.
- The creator approves it.

**Prepare publishing before the review.** Draft these in `edit/publish_prep/` while the creator hasn't reviewed yet; they make publishing fast once he says 「可以上传」:
- metadata zh/en, with a critic pass;
- zh/en SRT from the current timeline;
- both Shorts, rendered, with covers.

If the cut changes at review, regenerate them.

The final render also writes `edit/captions.srt` (timeline-mapped) for upload as the CC track.
Then continue with the publish-video-chat skill. After publishing: delete `edit/preview.mp4` and
`/tmp/yt-editor/<project>` (the master + EDL are the source of truth), and update LESSONS.md.

Contact sheets: `./venv/bin/python -m src.editor.scan "<project>"` → `edit/scan/sheets/grid_NN.jpg`.

- **No runtime cap (creator, 2026-10-03: 「成片的长度不需要有限制。你就只要把精彩的都留下就可以」).** Don't cut good moments to hit a target length. Every highlight stays: action, reactions, the creator's real commentary, pretty scenery with something happening. Trim only what is dull or repeated: dead air, retakes, fillers, waiting. This applies to every episode.
- **Keep only the clean take; captions are held to a high standard (creator, 2026-10-03: 「这个以后也要记得，字幕水平要保持高水准」).** Before any episode goes to review, check every kept speech line against the raw transcript and against whisper large-v3 run on the kept audio. If Qwen3-ASR with per-character timestamps is available, use it as well: whisper hides restarts.
  - Cut false starts, half-sentences that get restarted, doubled words (「这个这个」「一一块钱」), and lone fragments before the real line.
  - Test-join every cut and re-transcribe it, so that no word is clipped.
  - Captions must match what remains, word for word: one sentence per caption, no fillers, no other people's background talk.
  - The `lint` retake warning only catches near-identical captions. The full audit is still required.
  - The 100–107 pass on 2026-10-03 cut 93 retakes; that is the bar.
- **No captions for fillers and stray fragments (creator, 2026-10-03, ep 97).**
  - Interjection-only lines get no caption: 嗨, 哇, 哎呀, 天哪, "Oh no no no", "There you go".
  - Neither do odd 1–2 word scraps like 好了你, 拿哎呀, 去吧.
  - Background strangers talking are never captioned.
  - `captions_clean` drops these on the raw page (the INTERJECTION regex and the ≤3-character rule). In the cut, leave them out of `subs`.
  - Keep short lines that mean something: 很大, 好美啊, 哇，好吃.

## Pre-review pass: the creator's review patterns (from his 105–107 notes, 2026-10-15)
Run this on every episode BEFORE he reviews it (an "upgrade pass"); each item is something he asked for at least twice.
1. **Keep his live moments.** He often says 「这个clip可以留着 / 这段可以多留一点」: restore unused or trimmed clips where he talks, reacts, or something is happening (food being made, a vendor, a street detail, transport like a 小巴士). Check `scan/clip_index.md` **未用** rows and long gaps inside kept clips. Processes (food prep, a performance) get their full arc, not a 3 s cut.
2. **Explain what we see — fully.** Museums, murals, monuments, performances, street figures (e.g. organillero): identify each exhibit from labels in frame + sources, then add short yellow notes / TTS in his pauses. Confirm or gently correct his on-camera guesses. Name every dish and shop on screen (shop tag with address via `tag`/`tag_at`, dish names as notes), and put shop names + addresses in the description.
3. **Facts are stated plainly:** no 「资料说」, no hedged citations on screen; unverifiable → leave it out.
4. **Subtitles:** standard Mandarin in notes/cards/TTS (no 北方口语 like 棒子), Arabic digits (`src.editor.digits`), 他/她/它 checked against the picture (president = 她, insects/animals = 它们), filler words like 「然后呢」「又」 removed when they read oddly; re-transcribe clip tails flagged ⚠ in clip_index (ASR stops early under music; English guides go untranscribed — translate guide talk he finds interesting).
5. **His face:** he doesn't want accidental shots of himself (e.g. in crowd/audience shots). Cut or shift those ranges unless he is clearly the subject.
6. **Performances / recorded music:** each show segment ≤ 10 s (Content ID); several short segments are fine.
7. **Structure:** the route map goes right after the opening montage, before the first location; the cover's promise appears within 5 s and the title's hook is under way by 0:30 (analytics 10/15). Drop redundant cards (he cut the 「今天的小票」 receipt card as 多余). Dead air before a line (rain-street B-roll before speech) gets cut.
8. **Tags/labels appear when the subject is on screen** (`tag_at`, `tag_dur`).
9. **Titles/tags/description:** no 第X天; standard Chinese place name first + one nameable hook (search + suggested); no bargain words; description names shops/places with addresses.
10. **Covers:** dynamic multi-place (publish skill "Every cover needs motion"); no insects; no bargain words.
11. **Yellow notes stay long enough and never collide** (109 #10 「停留可以长一点」, 1:23 「字幕重叠」): ≥ 2 s and ~6 汉字/s of on-screen time *after skips* (a skip inside a note's window silently eats it), never under the top-left place tag's first 3 s, never in the same slot as a caption. Run `python -m src.editor.note_hold "<project>"` (stretches inside the shot), then fix what it reports as "shot too short" (split the note across two shots, extend a music-only shot, or trim the text). `src.editor.lint` warns on all three; read its `[lint]` lines after every render.
After the pass: re-render the preview, update HANDOFF ("Pre-review pass" section listing every change with 成片 times), so his review starts from a better cut.
