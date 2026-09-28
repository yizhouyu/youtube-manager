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
- **Two ASR models at once thrash a 16 GB Mac** (swap filled; 1 clip/min instead of 1 s/clip when
  two episodes transcribed in parallel). Check `sysctl vm.swapusage` / other `src.editor.transcribe`
  processes first; queue behind the other episode instead of competing.
- **Shared scratchpad:** parallel agents of one session share the scratchpad dir — put your files in
  a per-episode subfolder (`scratchpad/ep84/…`) so logs/frames don't collide.
- **Filming permissions, answered by the creator (don't re-ask):**
  - Outdoor scenery on Native land (tour areas, pueblos) is OK.
  - Tour guides agreed to be filmed, so keep their faces.
  - A two-person, no-drone crew needs no national-park permit.
  - Still open every time: identifiable children and strangers' faces (keep them out of shots and
    thumbnails).
- **Batch cost is mostly fixed, not per raw minute.** Rough-cut cost by episode:
  - 85: ~30% of the 5-hour window, starting from scratch.
  - 86–89: 11–15% each, where the prompt said "reuse the previous episode's build script and
    features, targeted reviewer frames, ≤3 QA rounds, aim ≤15–20%".
  - Always chain each episode from the previous one's `edit/` folder.

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
- **Don't "tidy" by merging adjacent ASR fragments into a sentence** — the extra fragment may be
  phantom ("它们已经走了" + "有点可惜" — the second was never said). Keep only what's clearly
  audible; when polishing a line, never add words the speaker didn't say.
- **Chinese lines get split into crumbs** ("可以来看一 | 看"). Merge ≤3-char / <0.25 s fragments into
  neighbours when contiguous (transcribe.py does this).
- **Food names: use the creator's preferred spelling consistently** (e.g. "Pâté" for both saltfish
  and beef, "Kallaloo soup" not "Kallaloo", "Jerk Duck"). Verify the dish by looking at the frame
  and a web search; never guess.
- Subtitles on screen < 0.7 s are unreadable — merge or extend. Lines hanging 5 s after speech ends
  look broken — trim to the speech.
- **Cross-check with a second model on the lines you keep** (whisper large-v3 with a proper-noun
  prompt, in the background): on ep 84 it fixed "George's grandsons"→Girard's, "erection ball"→
  wrecking ball, "meatwork"→beadwork, and exposed Qwen phantoms ("有 hold 有收藏的", "五块钱…").
- **Glossary keys are plain substring replacements, applied in insertion order** (ep 89: a lone `"的": ""` key stripped every 的 from every line). Short keys ("Oh",
  "there", "看") silently corrupt other lines ("Oh awesome" → " awesome", "看一看" → "一"). Use whole-line
  keys only, longer keys first; re-read every cleaned transcript after editing the glossary (ep 85).
- **A line both models agree on is not a phantom just because it's garbled in one of them** — ep 85's
  glossary dropped "就把这里开放给大家看" and the cut then clipped it mid-word; round-2 QA restored it.

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
- **Match transition style to the video's tone.** Cartoon sunburst cards + boing sfx worked for a
  light beach/food episode but read as childish on a nature/adventure episode — there, use an
  overlay chapter title on the next shot (`title` on the shot: white text + thin yellow rule), no sfx.
  Default to the overlay title; use cartoon cards only for playful content.
- **Time cards for jumps** ("一小时后……", "第二天……") with a light sfx. Never use copyrighted meme
  clips (Content ID); original cards look just as good.
- Note captions are `{"kind": "note"}` with plain text — never a marker character in the text
  itself (a "※" prefix once rendered literally on screen).
- Don't use internal jargon in shot `note`s — they're the creator-facing card titles.
- **Decide folder boundaries from the footage, not the plan** (camera clock is ET in the 202512
  batch, MT+2 h — daylight in the frames confirms it). Ep 84's "Santa Fe" day also held Bandelier;
  keeping it made the episode's strongest ending + thumbnail. Moving raw clips between projects is
  irreversible-ish: the auto-mode classifier blocks it — leave it to the creator and say so.
- **Card shots (clip "") draw no subtitles/overlays** — put text for map/end cards into the image.
- **A landmark that's only on screen for ~1 s** (the Rio Grande Gorge Bridge in a quick pan) can still
  carry the hook and its payoff: freeze its best frame (card.image, same grade) with the question baked
  in for the hook, and a labelled freeze-frame answer at the end.
- **Sites with photo rules:** Taos Pueblo allows photos for personal use only (commercial use needs
  approval/fees; residents only with permission; no photos inside the chapel). Keep identifiable
  residents out, and list the rule as an open question for the creator (ep 85).
- **The plan is not the record:** ep 87's "Chaco" day opened at Aztec Ruins NM (sign in the first clip), an outlier
  in the same UNESCO listing — it became its own section. Read the first frames of the day before trusting the plan.
- **The plan is not the record (again, ep 88):** the 12/18 plan's Valley of Fires lava field was never filmed; a roadside Trinity Site
  marker was. Don't build a section (or a music cue) from the plan — the "lava" music pick became the cold-open track instead.
- **The plan is not the record (ep 89):** the planned Anapra Road border wall was never filmed. The border part was Chamizal NM + the border highway, and the day ended with a 2:26 PM arrival for the 2:30 last cave entry, not the planned 1:15 slot. Transcripts and signs name the real places; ask the research agent about the ones the plan didn't list.
- **A riddle hook needs a readable answer:** the upside-down Mirror Lake sign was ~110 px in a black 4K frame. The answer became a freeze card with the real 4K crop, plus the same crop flipped vertically (倒影示意). Punching in to 5× on the hook shot made the question readable. Locate tiny far subjects (the Juárez X, ~50 px) on 4K frames and put the zoom focal point ON the subject: with the renderer's zoom it then stays at the same frame fraction, so the arrow position = the subject's raw position.
- **The plan is not the record (ep 90):** the UFO Museum, Los Pollos Hermanos and the Sandia tram were never filmed; a Taiwanese lunch, a road-sign wall and El Paisa were. Research only what's on camera.
- **Don't zoom to "prove" a line the frame can't show** (ep 90: "路灯里面是外星人头" — even the 4K globe was ~60 px and unreadable). Cut the line instead of a punch-in on nothing.
- **Kids at the frame edge slip past QA (ep 92):** two reviewer rounds on 1 fps / 0.5 fps sheets missed a girl facing the camera at the left edge of a
  sea-lion beach shot for 1.5 s. Before handing over, the editor checks every crowded-place shot (beaches, restaurants, hostels) at 2 fps on the
  RAW clip range, and removes people with a punch-in (`zoom` ≥ 1.25 with the focal point away from them) or a `broll` cutaway rather than dropping the shot.
- **Arrows on a panning handheld shot drift off the subject** (a cow on ep 87 moved .48→.44 in 2.5 s): prefer a
  punch-in (`zoom` from ≥1.3) that keeps the subject near the focal point, or keep mark windows ≤ 1.5 s.

## Audio & music

- YouTube Audio Library "no attribution required" tracks are the only claim-safe music. Record
  licenses in `edit/music/LICENSES.md`. **Fetch with ZERO download dialogs (verified 2026-09-28).**
  Never click Studio's Download button: it navigates to the file and Chrome (set to "ask where to
  save") pops a native Save dialog that nobody may be there to dismiss. Instead, in a NEW Studio
  Audio-library tab (claude-in-chrome `javascript_tool`):
  1. Hook `XMLHttpRequest.prototype.open/setRequestHeader/send` to capture the request whose URL
     contains `creator_music/get_tracks` (url, headers, JSON body, response), and add a safety net:
     `navigation.addEventListener('navigate', e => { if (/googlevideo/.test(e.destination.url)) e.preventDefault() })`.
  2. Click a row's **Play** button (preview only — can't download). The page sends get_tracks with
     `mask: {includeStreamingUrl: true}` (128 kbps preview — not what we want).
  3. Replay it with `fetch(url, {method:'POST', headers, credentials:'include', body: JSON.stringify({...body, trackIds:[<id>], mask:{includeDownloadUrl:true}})})`
     → `tracks[0].downloadAudioUrl` = itag 25, 320 kbps. Track ids: `ytmus-library-row` elements'
     `.audioTrack.trackId` (titles/moods/durations are there too); re-press Play if auth expires.
  4. Tool output redacts URL query strings, so make the page `fetch(downloadAudioUrl, {mode:'no-cors', headers:{Range:'bytes=0-1'}})`
     and read the full URL from `read_network_requests(urlPattern='videoplayback')` (the
     redirector.googlevideo.com one), then `curl -L -o <file>.mp3 "<url>"` → HTTP 200, full file.
  5. ffprobe (~320 kbps, right duration); add to `~/Movies/yt-music-library/INDEX.md`.
  (A background tab can't receive typed search text — pick tracks by reading row data, scrolling or
  filtering via the page's own controls with JS.)
- **Shared music library:** every track you fetch also goes to `~/Movies/yt-music-library/`
  (outside the repo — audio isn't ours to redistribute) with a row in its `INDEX.md` (title, artist,
  license, mood, used-in episodes). Check the library first; reuse is fine across episodes that
  aren't back to back, and it keeps working when no browser is available.
- Music by section, crossfaded; duck under speech (subtitle intervals). Start around
  `music_volume` 0.33 / `music_duck` 0.06; montage-only stretches can feel too quiet, but the
  creator found 0.42 too loud overall.
- Don't let a track restart from the top at a section boundary unless intended (reviewer caught one).
- Final loudness −14 LUFS integrated, true peak ≤ −1.5 dBTP.
- **Check every Audio Library track for vocals before placing it** (whisper-cli on the track; the
  library's "mood" tags don't say). Ep 85's "When It Ends" (Cosplay) is a breakup song sung end to end
  and "Sky Is The Limit" (Anno Domini Beats) starts singing at ~27.7 s — QA caught lyrics over the
  finale. Instrumental-only under narration and note captions, or stop the section before the vocals.
- **GoPro clips end with the camera's stop-button click**; in a quiet mix (or after a `gain_db` lift)
  it lands 10–20 dB above its surroundings. Trim out-points ~0.1–0.3 s before the clip end.
- **Synthetic sfx transients beat the limiter:** a white-noise shutter click at gain 0.6 pushed true
  peak to −0.1 dBTP; 0.3 was still audible and measured −1.9. Re-measure true peak after adding sfx.
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
- **Per-frame audio expressions need sample-count timestamps** (`asetpts=N/SR/TB`): after `amix`
  of looped inputs, PTS can jump and the music-duck `volume` expression randomly evaluated to 0 —
  whole stretches of dead air that changed run to run. Always measure per-second loudness of the
  preview (no second below ~−35 dBFS) before handing it over.
- Music entries accept `in` (skip a quiet intro) and `gain` (dB); tracks are auto-matched to −14 LUFS.
- Shots accept `gain_db` (−24..+12) to lift a quiet/distant speaker (a guide ~6 LU under the creator
  needed +8 dB on ep 85) before the final loudnorm.
- **Music timing math:** a section's track fades in 2.5 s BEFORE its start shot, so the track time at
  the start shot = `in` + 2.5 s. Needed for beat-synced cuts; also compute where vocals would land.
- Final master: 4K HEVC Main10 ~100 Mb/s `.mov`, graded in 10-bit, at `02 - Export/<folder name>.mov`.
- **Every shot's audio gets 12 ms edge fades** (renderer default since ep 86): a hard cut on wind noise clicked
  (~2000-unit sample step) even with no stop-button click nearby. Cache key bumped with it.
- **Title-card sub-lines need an outline** on bright rock/sand (ep 86 QA: unreadable at 1:00) — done in `overlays.title_card`.
- **A quiet guide / relayed explanation sinks under the mix:** measure the voice stem per shot and lift with `gain_db`
  (ep 86: guide Q&A +10 dB, the Alien Throne talk +4, the Chaco line +5) — check this in round 1, not round 2.
- **`tighten` rewrites every talking shot's `skip` list** (it drops hand-made skips): keep manual skips in a small merge script and run it after tighten (ep 90's `edit/scripts/merge_manual_skips.py`).
- **Why previews land at −14.9/−15.0 LUFS, not −14 (measured ep 90):** the pre-loudnorm mix is ~−18 LUFS with true peaks ~−2.5 dBTP; raising it 4 dB would break the −1.5 dBTP ceiling, so single-pass dynamic loudnorm stops ~0.9 LU short. The post-limiter is NOT the cause (same −14.9 without it), and a pre-limiter only gained 0.1–0.2 LU. Within ±1 LU; fixing it properly needs speech-peak compression before loudnorm.
- **Reviewers must not write QA remarks into shot `note`s** (ep 90 round 2 appended "| QA2: …" to card titles) — changelogs go in the report / HANDOFF.
- **GoPro clips start with ~40–66 ms of digital silence** (ep 87 QA heard gaps at 1:44/1:48 in the music-free
  section): a shot with audio should never start at `in: 0.0` — use ≥ 0.1. Measured on the cached segment WAVs
  (`/tmp/yt-editor/<project>/seg_*/sNNN_*.wav`); afftdn was NOT the cause (tested on a tone + a real clip).

## Review surfaces (pages)

- Plain Chinese, no jargon; default view shows only what's needed (keep / trim / subtitle text);
  everything else under "更多设置".
- Must feel like YouTube: controls overlay on hover, `current / total` time, space/K/arrow/F keys that
  also work in fullscreen (capture-phase key handler so native controls don't double-toggle).
  Browsers "click" a focused button on Space **keyup**: stop buttons taking focus on mousedown and
  swallow Space keyup too — otherwise Space after clicking fullscreen exits fullscreen.
  With a native `<video controls>`, KEEP its fullscreen button (the creator dislikes it removed);
  on `fullscreenchange` blur the focused element so Space reaches the page, and when the key
  target IS the <video>, let the browser handle Space.
- Click on the picture = play/pause with a big centered ▶ while paused (YouTube feel); exclude the
  native control bar (bottom ~20% / 44 px). Browser automation's clicks/keys often don't reach a
  background Chrome window — verify page logic with dispatched events and ask the creator to try.
- **Never overwrite the file a page is playing.** Each preview render is also hardlinked to
  `edit/previews/preview-<time>.mp4`; the page plays a version, polls for a newer one, swaps
  quietly (keeping position) when paused, and only offers a "新预览已生成" button while playing.
  Release the old <video> (`removeAttribute('src'); load()`) before swapping or the new one stalls.
  Automation tabs are often `visibilityState: hidden`: Chrome defers media loading and drops
  synthetic input there — don't mistake that for a page bug.
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

## Sources behind the retention rules (research 2026-09-28)

YouTube Help — audience retention / intro metric: https://support.google.com/youtube/answer/9314415 ·
chapters: https://support.google.com/youtube/answer/9884579 · end screens:
https://support.google.com/youtube/answer/6388789 · related-video/Shorts guide:
https://blog.youtube/creator-and-artist-stories/youtube-related-videos-traffic-guide/ · retention
benchmarks: https://humbleandbrag.com/blog/youtube-audience-retention-benchmarks · audio quality vs
credibility: https://dornsife.usc.edu/news/stories/norbert-schwarz-research-links-sound-quality-belief/ ·
Bilibili practice (secondary): https://www.huasheng.ai/insights/bilibili-video-best-practices/ ·
storytelling: https://1of10.com/blog/storytelling-techniques-top-youtubers-use-to-keep-viewers-hooked/
Travel-vlog-specific data is scarce; treat numbers as targets, and learn from the channel's own
analytics (retention graphs) once available.

## Experiments (one or more new techniques per video — keep what works)

| Video | Technique | Result | Default from now on? |
|---|---|---|---|
| 81 | Original sunburst time cards + cartoon sfx | Liked on a light beach/food episode | Only for playful content |
| 82 | Same cards on a nature episode | "太幼稚" — replaced by overlay chapter titles | No → overlay titles default |
| 82 | Labelled arrows on tiny animals (orcas, bear, eagle) | Clear; must be located on 4K frames first | Yes, with Ken Burns |
| 82 | 4× timelapse of a long process (filleting) + note caption | Turned a dull 90 s into ~12 s | Yes for long processes |
| 84 | Animated route map card (`card.image` = Pillow-drawn 4K frames → mp4: dashed line drawing ABQ → Santa Fe → Bandelier → Ojo Caliente, inset of the whole state) after the opening title + a still recap with a "下一集" teaser as the end card | Reads in ~4 s, gives the day a shape and a calm end-screen background; reviewer-scored windows around it 8–9/10 | Yes for multi-stop days (script: 84's `edit/scripts/make_route_map.py`) |
| 84 | Limiter after loudnorm (true peak −1.2 → −1.9 dBTP) | Meets the −1.5 dBTP spec with no audible change | Yes (renderer default now) |
| 83 | Slow-motion reveal (`speed: 0.5`) on the bear's closest pass | Steppy: 30 fps source at 0.5× = 15 fps, fast pan, fence mesh strobed; reviewer 0/2 for looks | No — slow-mo without frame interpolation only on near-static shots (frame-to-frame change < ~5) |
| 85 | Freeze-frame + label cards: the shot's last frame (same grade) as `card.image` with Pillow-drawn name boxes + leader lines to the subject and a soft shutter click (`sfx`, gain 0.3); used 3×: "who are these statues" (Oppenheimer / Groves), "whose Nobel medal" (Reines 1995, read off the plaque), and the answer to the hook question on a bridge that's only in frame for 1 s (script: 85's `edit/scripts/make_freeze_frames.py`) | Reads instantly, labels land on the right subject when located on 4K frames; reviewers found no issues in 3 rounds; windows with a freeze scored 9–10/10 | Yes, for "who/what is that" beats and hook answers; ≤ 1 per ~45 s, keep the click quiet |
| 85 | J-cut into a new place with existing features: the arriving shot starts with 1.3 s of `broll` from the drive, so its first line ("我们先来到这里") is heard over the road | Smooth, no reviewer complaints; the chapter title appears over the B-roll (acceptable) | Yes at place changes that open on speech |
| 85 | Beat-synced drive montage: tempo from onset-envelope autocorrelation (numpy in asrvenv; 105 BPM), each shot 4 beats long, frame-rounded so cuts land within ±13 ms (round 2 fixed a +53 ms drift from 69- vs 68-frame shots) | Tighter, livelier 9 s drive; 1:00 window 10/10 | Yes for montages ≥ 3 shots; compute track time with the 2.5 s crossfade lead |
| 83 | Real-time punch-in "answer" beat: hard cut from the wide shot to a 1.25× static zoom on the same action, with the note answering the cold-open question ("这只黑熊，最后离我们有多近？" → "答案：隔着一道围栏，就在眼前") | Smooth and emphatic; reviewer 2/2; finale window 10/10 | Yes as the payoff beat for a hook question (the question must be one the footage can verify) |
| 86 | Ambient-only "breathing room": a music entry with `"file": null` (new renderer feature) drops the music for ~10 s at the widest stone-forest vista (3 silent shots, natural wind lifted +6 dB, one note "这里安静得，只剩下风声"), right after ~45 s of the guide talking; the next track fades back in on the next reveal | Reviewer r1: "resets the ear"; window scored 9/10; needs the stop-button clicks trimmed (a +6 dB lift exposed one) and ≥ 6 s length for the 2.5 s crossfades | Yes, once per video at the most striking silent vista, ≤ 12 s |
| 86 | Speed ramp on the drive in: same clip split into 1× (a "哇塞") → 6× (20 s of dirt two-track, note caption) → 1× (the guide's car ahead) | Reads as one continuous drive, 3 s instead of 23 s; no reviewer complaints | Yes for long approaches (driving/walking) with a real start and end beat |
| 87 | Animated then/now reconstruction card (`card.image` = mp4 built with ffmpeg alpha fades from Pillow layers, no renderer change): Pueblo Bonito's back wall today → translucent dashed "ghost" tiers build up floor by floor to the 4–5 stories the park panel states, labelled 现在 / 一千年前（示意）, then a picture-in-picture of the park panel's own reconstruction painting (perspective-corrected with `Image.QUAD`) as the source; placed right after the creator says "最高可能有四五层" (script: 87's `edit/scripts/make_freeze_frames.py`) | Round-1 reviewer: honest (示意 + source shown), PiP legible; window 2:30 scored 10/10; idea: J-cut it under the spoken line | Yes for ruins/rebuilt things with a verifiable original size; always label 示意 and show the source |
| 88 | Scale-comparison card (`card.image` mp4, no renderer change): the 30-ft "World's Largest Pistachio" frame gets a 0–30 ft ruler ("30 英尺 ≈ 9 米"), then five 1.75 m person silhouettes stack up beside it one by one, drawn to the statue's own pixel height, labelled 示意 + the sourced build year (script: 88's `edit/scripts/make_cards.py`) | Reads in ~2 s, turns a dull roadside statue into a "哦!" beat; round-1 reviewer: facts backed by research, only fix was a card zoom cropping the text (keep card zoom ≤ 1.04 when text sits near an edge) | Yes for big/tall things with a sourced size; the silhouettes must be scaled on the object's ground line in a located 4K frame |
| 88 | Local-time clock tags (`tag: "下午 4:38"` from camera clock − 2 h) on each golden-hour/sunset shot, instead of a timelapse | Gives the "last hour before sunset" a visible countdown with zero renderer work; reviewer verified the times | Yes for sunset/golden-hour runs |
| 89 | Animated depth gauge (new renderer feature `gauge`: a right-edge meter panel whose value eases from→to across a shot, PNG sequence at 10 fps; chained over the Natural Entrance descent 0 → −20 → −70 → −150 → −200 → −230 m, landing on −230 as the Big Room title appears, held in the elevator) | Turned ~15 s of dark, shaky descent into a countdown with a destination; round-1 reviewer "clear and believable"; windows around it 10 and 8/10. Only endpoints are facts (NPS 229–230 m) — the in-between values are interpolated | Yes for descents/ascents (caves, mines, towers, dives, elevators, altitude drives) |
| 90 | Series-finale recap montage (`card.image` mp4, no renderer change): one 3-beat shot per episode 84→90 from the other projects' raw clips (their grades), labelled with the episode number, place and date, cut on Purple Desire's beat (136 BPM, frame-rounded; music `in` chosen so the card starts on a beat), last shot holds 6 beats with "8 天 · 7 集 · 完" + the 三连 line; followed by an animated whole-series route map (legs drawn episode by episode, list of 84–90) and the end card | Reads as a proper finale; round-2 window 3:30 scored 10/10; reviewers found no issues with it. Cost: ~2 min to render, no new code | Yes for every series finale (script: 90's `edit/scripts/make_cards.py` `recap()` + `maps()`) |
| 90 | Periodic-table chapter card "[Al 13] buquerque" (original design, Pillow + alpha-fade layers) and a green sci-fi "1947 档案解密" HUD card (scan lines, corner brackets, a sliding scan bar via ffmpeg overlay `y=mod(t*H/2,H)`, three dated facts fading in) | Both read instantly; windows around them 9–10/10; the HUD turned a spoken "据说有外星人" into three sourced facts | Yes as themed cards when the place has a strong pop-culture identity; keep facts from research.md only |
| 92 | Natural-sound-first cold open (no renderer change): the first music entry is `"file": null`, the first track starts on shot 3 at 5.3 s, so its 2.5 s fade-in leaves ~2.8 s of pure waves + sea lions before the music swells in under the question line | Both reviewers: natural sound clearly audible (RMS −36…−10 dB), smooth swell, no clicks; 0:00 window 9/10 | Yes for animal/nature openings with strong ambient sound; keep the silent-music stretch ≤ 3 s and lift the ambience (`gain_db` +8) |
| 92 | "Spot the difference" species card (`card.image` mp4 built with Pillow, no renderer change): real 4K crops from the same day (sea lion at La Jolla Cove vs harbor seals at Children's Pool) fade in side by side, then 3 sourced difference rows (耳朵/上岸/声音) pop in with a small overshoot, 1.3 s apart; set up by the creator's own confusion ("这也是海狮，不是海豹") and followed by the comment question | Reviewers: facts match research, readable, no overlap; 2:00 window 10/10. Doubles as thumbnail D | Yes whenever two look-alike subjects appear in one video (animals, dishes, buildings); script: 92's `edit/scripts/make_cards.py` `spot()` |
