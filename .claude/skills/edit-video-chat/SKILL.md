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

## 3. Render + review

```bash
./venv/bin/python -m src.editor.render "<project>" --preview   # 1080p → edit/preview.mp4
./venv/bin/python -m src.editor.review_server "<project>"       # http://127.0.0.1:8766
./venv/bin/python -m src.editor.render "<project>" --final     # 4K → 02 - Export/<project>.mp4
./venv/bin/python -m src.editor.render "<project>" --package   # clean numbered clips + SRT for CapCut
```

**Review chat (creator, 2026-10-01).** Both pages have a "和 Claude 聊" box.
- **What it carries:** each message he sends records where he was (raw clip + time, or cut time). The messages are stored in `edit/chat.jsonl`.
- **Open all three pages yourself (creator, 2026-10-03).** When review starts or moves to the next episode, `open` these right away:
  1. the raw page, 8765;
  2. the cut page, 8766;
  3. the episode's cover page, `thumbnail/editorial.html` or `review.html`.
  
  Before that, confirm `scan/.proofread` exists. Starting servers without opening the pages counts as not done.
- **Two buttons (2026-10-02):** 「评论」 (Shift+Enter) stores a note as pending (`status: "pending"`, tagged 「待交给 Agent」 on the page); Option+Enter is a newline. 「交给 Agent」 (Enter, or Cmd+Enter) hands over the typed note plus all pending notes as one batch. Pending notes never reach `watch`: he is still collecting, so don't act on them (`tail` marks them `[待交]`).
- **Watching:** while he reviews, keep a Monitor running `python -u -m src.editor.chat "<project>" watch`. Re-arm it every 30 min. It prints `CHAT #id [where] text` for a single note and `CHAT BATCH b3 (3 条): #5 [..] a ‖ #6 [..] b ‖ …` for a batch. Treat a batch as one review pass: apply all of it, re-render once, then reply once.
- **Replying:** answer with `python -m src.editor.chat "<project>" reply "…"`, so he never has to switch back to the terminal.
- **Acting on notes:** apply a note, re-render, then reply with what changed and the 成片 timestamps.


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
  - carries the credit 「路线示意 · 地图数据 © OpenStreetMap contributors」.

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

