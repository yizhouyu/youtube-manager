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
  - **Bystanders are normal in a vlog; don't cut for "privacy" (creator, 2026-09-28).** Strangers,
    passers-by, police or ambulance scenes and kids in the background all stay if the moment is fun or
    interesting. Don't cut too much. Only real private info stays out: personal names, codes, phone
    or reservation numbers, addresses. Eps 88, 89, 91 and 92 over-cut on this; the 92 police scene
    should have stayed.
- **Next-episode teasers only within the same trip** (creator, review of 83). The last episode of a trip must not tease a different trip, e.g. Alaska → New Mexico. Point to that region's playlist/合集 instead ("全系列都在合集里") or just say thanks + subscribe.
- **Length is not a constraint (creator, 2026-09-28).** Up to ~20 min is fine, and 7 min is "not
  long". Don't drop good, fun or informative moments to hit a runtime. The retention rules (2b) are
  about pacing: trim dead air, timelapse the dull stretches, change something every <60 s. They are
  not about removing content. When unsure, keep the moment and tighten around it. His own words
  on pacing: "别一个一个同样的镜头放太久". Cap *static, unchanging* shots (a few seconds each). A
  shot with change in it (movement, action, reaction, talk, a reveal) may run longer.
  Car-window scenery (driving past things) reads slow at 1×, even when it's pretty. Use 2–4× or
  keep it to a few seconds (creator, review of 83).
- **Batch cost is mostly fixed, not per raw minute.** Rough-cut cost by episode:
  - 85: ~30% of the 5-hour window, starting from scratch.
  - 86–89: 11–15% each, where the prompt said "reuse the previous episode's build script and
    features, targeted reviewer frames, ≤3 QA rounds, aim ≤15–20%".
  - Always chain each episode from the previous one's `edit/` folder.
- **A comparison cut is a creative experiment, not a revision of the first cut.** Render it from a
  separate alternate EDL in an isolated staging project, leave the original EDL/master/assets alone,
  and hand the creator its own 4K master + SRT + EDL. `scripts/render_variant.py` is the standard
  path; a 1080p file is only an internal QA proxy when the requested deliverable is 4K. Preflight
  the master, EDL, SRT, manifest and version-scoped asset directory before rendering; the manifest
  must point only to files actually delivered. Verify by re-opening the delivered EDL and checking
  its references, and test overwrite refusal without touching a real project.
- **Choose long episode vs Short before cutting.** Use the raw material's available story, speech,
  and visual variety — not a default vlog duration. A short, narration-free visual day may be a
  deliberate 90–180 s 16:9 micro-documentary plus a Short, rather than padded into a long episode.
- **Generated music/TTS/illustrative transitions can add authorship without falsifying a trip.** Keep
  the real footage as evidence; use generated media only as a labeled editorial layer, test TTS
  personality on one line first, and do not bypass a media tool's interactive-consent gate.
- **No source narration does not automatically mean “no voiceover.”** Follow the creator's latest
  explicit direction and let later corrections supersede earlier notes. Princeton (101) was first
  described as intentionally without narration, then the creator clarified “101 needs narration”
  and asked for location-specific, informative coverage. For observational work, let image and
  natural sound lead; when informative narration is requested, use verified facts matched to the
  visible place—not generic poetic prose—and preserve the selected script, voice, audio and sources.
- **Informative narration must be geographically and visually anchored.** When requested, explain
  the actual place on screen with verified history/context, then return to the filmed experience;
  avoid mood-only AI prose that could fit any city. Fact-check each line, align it to the relevant
  footage, and retain the script, sources and exact audio settings as project assets for later edits.

- **A camera with an unset clock (DJI Osmo Pocket 3 on the July 2026 California trip, eps 102–104):** every
  filename and `creation_time` says 2001-01-09…11. Clip numbers and clock deltas were still monotonic, so camera
  days mapped 1:1 onto trip days (checked against signs, speech like "今天是七月四号", and the Notion plan); the
  time of day was ~1¾ h off (sunset). Keep the filenames, record the mapping in each HANDOFF, use no clock tags.
  The Pocket 3 has no GPS unless paired with the phone app: random doubles in the `dbgi` debug stream look like
  coordinates but aren't.
- **Split one trip across parallel episode directors with `fork` agents** (102–104): the director sorts the clips,
  stages scan + ASR once for all, writes the mapping, then forks one director per later episode with exact clip
  ranges, music pools (no overlap) and "no commits, report code changes". Forks can't spawn sub-agents, so run the
  independent art-director check from the parent afterwards (it overturned 103's pick).

- **Five parallel directors on one trip (Texas 108–112, 2026-10-07).** What worked:
  - The master sorts the clips into days and places, using GPSU and GPS fixes. The GoPro date was exactly one day behind.
  - It stages scan + ASR once in a symlinked folder, moves the clips into the projects, writes one trip brief (`sessions/texas_brief.md`) and fetches disjoint music pools (`sessions/texas_music.md`).
  - Each director gets a short prompt pointing at the brief.

  What hurt:
  - All five hit the usage limit at once. Resume with SendMessage; it keeps their context. The C0–C14 checkpoints are the fallback.
  - The ASR lock queued for 45–90 min. Request word-level dumps for all speech clips once, at the start.
  - WebSearch's shared budget ran out (WebFetch on known official pages still works).
  - Directors' "round 2" was often a self-review. Run an independent strong-model QA on every episode before review.
- **Sonnet reviewers miss things** (111 round 1): QA judgment stays on the strongest model.

- **ffmpeg 9 (Homebrew upgraded it mid-session on 2026-10-08) broke two things.** `-filter_complex_script` is gone (use `-/filter_complex <file>`). Decoding with `-noautorotate` now copies the display matrix into the output, so players rotated DJI segments again; the renderer strips `DISPLAYMATRIX` side data. Run `scripts/test_*.py` after any ffmpeg upgrade. Installs that pull in brew dependents can upgrade shared tools: use `HOMEBREW_NO_AUTO_UPDATE=1`, and prefer isolated venvs.

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
- **Word-level timings already exist; use them when re-timing.** `transcribe.py` calls Qwen3-ASR with
  `return_timestamps=True` (its forced aligner gives per-word start/end) but keeps only grouped SRT lines.
  To re-time a caption, place a skip or split a line at a word boundary, re-run `transcribe()` with
  `return_timestamps=True` on that span (under the ASR lock) instead of guessing from line cues. The
  same data can drive word-by-word Shorts captions (idea from Deedy Das's video-workflow post, LinkedIn
  2026-09: https://lnkd.in/p/g34Cz6pf).

- **Qwen word timestamps (`return_timestamps=True`) make retake/stumble cuts one-step** (108, 112). Since 2026-10-08 `transcribe` saves them to `scan/words/<clip>.json`; `python -m src.editor.words "<project>" <clip> [phrase]` lists words or finds a phrase's span. Cut on word boundaries, then test-join and re-transcribe. Inside a repeated word pair (摆社团摆摊) only one of five candidate joins read clean.
- **whisper large-v3 loops on long music-only stretches** of a mix, and so does whisper-cli with a long `--prompt` on a whole-episode file. For QA re-transcription use per-shot or talk-segment cuts, `-mc 0` and no prompt.
- **都/就-type single-character flips between models:** decide on tight snippets with both models plus the onset sound.
- **Qwen echoes the `--context` list on near-silent stems and music clips** (GX013225 came back as the whole list; 110 stems as 「鸵鸟斑马鸸鹋…」). Drop lines made only of context words.

- **Tool scouting 2026-10-08** (`sessions/research/2026-10-08/tools.md`):
  - **Adopt:** RIFE slow-mo (`src.editor.interp`; SSIM 0.967 vs 0.902 for plain frame repeat). MOSS-Transcribe-Diarize as the second ASR, in place of whisper. vhs for terminal recordings, rendered on an idle machine.
  - **Rejected:** FireRedASR2, SenseVoice, PySceneDetect on raw GoPro takes, auto-editor (it cuts captioned speech), DeepFilterNet (denoised wind still isn't transcribable). Real-ESRGAN only rarely.
  - **whisper large-v3 silently drops words** (「三个 learning center」 vanished). Its low raw error rate flatters it, so it's a weak cross-check.

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
- ~~Kids at the frame edge slip past QA (ep 92):~~ superseded 2026-09-28: bystanders/kids in frame are fine (see "Bystanders are normal").
- **Arrows on a panning handheld shot drift off the subject** (a cow on ep 87 moved .48→.44 in 2.5 s): prefer a
  punch-in (`zoom` from ≥1.3) that keeps the subject near the focal point, or keep mark windows ≤ 1.5 s.
- **Reviewers flag silent `note` captions as "missing VO"** (ep 91 r1 called the hook notes blocking). Tell the reviewer up front that `kind: note` lines are intentional silent captions.
- ~~Check restored/added shots for strangers yourself~~ superseded 2026-09-28: bystanders/kids in frame are fine (see "Bystanders are normal").

- **The plan is not the record (ep 94):** 12/24 had one GoPro clip (the San Diego departure); Cabazon, the outlets, Indian Canyon, Skull Rock, Keys View, "Transmission" (actually near Joshua Tree town, not Palm Springs) and any night sky were never filmed. The best story was an unplanned moment (a cholla segment clinging to his shoe). Also: when the plan's restaurant name can't be verified by research, look for text in the frames — the placemat named it (SUN NONG DAN).
- **Qwen3-ASR echoes the `--context` list on silent clips** (ep 94: a 5 s driving clip came back as 26 "lines" of the proper-noun list). Treat any transcript that reads like the context string as empty.
- **`tighten` can leave a talking shot with `skip_on: false` plus stale spans, and it times long ASR cues, not words** (ep 95: "它俩打架了" sat 3.4 s before the words over a silent chase). On long animal/visual shots re-time captions from a word-level re-transcription, and after any manual skip check the next caption's first word isn't inside the skip (a 3.2–9.1 skip ate "说是").
- **The plan is not the record (ep 96):** the Santa Monica Mountains stamps, El Matador and Pita 'Bu (closed on Saturdays) were never filmed; Westward Beach, Santa Monica Place and the Santa Monica Pier were. A shot that "proves" a hook (a tiny surfer's wipeout) can be unreadable at 1080p even at a 2.4× punch-in: swap the hook beat for one that reads at a glance (a dog racing a man) and put an arrow on the subject before the caption.
- **The plan is not the record (ep 97):** Whiteface, the horse show, the ski jumps, the parade, the concert and Rainbow Falls were never filmed. A park warden's "…Rainbow Falls" in the footage is not proof they went there: ask, and label inferred trail routes 路线示意.
- **A name on a sign in the shot counts as verified (ep 97):** QA round 1 removed "Emma's" from a storefront title although the sign fills that very frame. Restaurant/shop names are out only when no sign, menu or speech shows them.
- **Map numbers must be sourced, not measured on a guessed route (ep 97):** the OSM length of an inferred trail ("单程约 7 公里") was replaced with research's "往返约 16 公里".
- **`broll.at` is measured before the shot's skips** (ep 96: a 1.47 s skip earlier in the shot pushed a plane cut-away onto the wrong sentence). Add the skipped seconds that precede the target word, or put the B-roll before any skip.

- **whisper-cli `-l zh` translates English speech into Chinese** (ep 99: the farm-window dialogue came back as "你需要箱子吗?"). For English lines, re-run the segment with `-l en` before trusting or dropping them.
- **Unlisted tracks in `~/Movies/yt-music-library/`** (a file with no INDEX row) may be leftovers from another agent. Check the parallel episodes' `edit/music/` folders; if nobody uses it, vocal-check it and add the INDEX row (ep 99 used Open and Closed + Cued For Liftoff this way when 5 fresh tracks weren't enough for a 13-min cut).

- **A place name in the ASR context list can overwrite a sign in the frame (ep 100):** "这里还有 Lalibela" was really "Lululemon": the dinner restaurant was in `--context`, so Qwen snapped to it; whisper and the 4K frame (a lululemon sign) disagreed. When a context word appears where the scene doesn't fit, check the frame and the second model before captioning it.

- **Overpass can be down for hours (2026-10-01: 406/timeouts on every mirror at first).** Fallbacks that worked for
  route maps: NPS park boundaries from the NPS Land Resources Division ArcGIS FeatureServer (layer 2,
  `where=UNIT_CODE='SEQU'`, GeoJSON), US county outlines, USGS 3DEP hillshade + EPQS elevations, OSRM road geometry;
  the kumi.systems Overpass mirror answered later in the day. Label straight legs 示意.
- **DJI Pocket 3 clips can carry a −180° display matrix the renderer ignores** (104: 0462 upside down): check
  `ffprobe -show_entries stream_side_data=rotation` and fix with an `hflip,vflip` grade.
  Since 2026-10-02 the EDL takes `"noautorotate": [clip, …]`: those clips are decoded as stored (shots, B-roll, clip
  pips). Use it for DJI clips tagged rotate 90/−90/180 whose stored frame is upright (the Mexico City trip had 9;
  contact sheets show them sideways because ffmpeg applied the bogus matrix). Grab stills with `-noautorotate` too.
- **A shot whose subject sits in the bottom 15 % of the frame fights the subtitle** (102 hook: the jaguar walked along
  the fence bottom). A zoom can't lift it (the crop clamps at the frame edge): pick the moment the subject is
  higher, or split the caption so its words land on the next shot.
- **Note captions over a shot where someone is audibly saying something else confuse viewers** (102: the docent's
  next sentence under an Amur-leopard number note): mute those shots (`audio: mute`) and let the music carry.

- **`tighten` replaces hand-made skips, and its spans can swallow a caption's first or last word** (111). Re-merge the manual spans, clamp auto spans to caption edges, and compute PiP times *after* tighten (111's `tighten_merge.py`; a generic `--keep-manual` is on the to-do list).
- **When you mute a talking shot, say why in its note** (109). Lines muted "for no reason" were real content.
- **Overpass on a 70 km metro box times out at `major` (down to tertiary)** (108). Fetch motorway–secondary for the whole box plus minor roads around the stops. **One-way tags on a drive-through safari road don't chain** (110), so route that leg in `walk` mode.

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
- Final loudness −14 LUFS integrated, true peak ≤ −1.5 dBTP. Since 2026-10-01 the renderer guarantees this by measuring the encoded AAC and correcting in a loop. Read the numbers from `render_status.json` → `audio`; there's no need to re-measure (see "Audio pipeline 2026-10-01" below).
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
- **A track can appear twice in `music` with different `in`s since e897dab (2026-09-28).** Before that, the second use silently replayed the first entry's `in`/`gain` (ep 96 QA: Cafecito at 110 s replayed its 20 s passage). EDLs of 86, 88, 89 and 91–95 reuse tracks, so their next render sounds different from what their QA heard. Also keep the two uses' passages apart: a section plays `in` → `in` + its length + 5 s, so the next use's `in` should start after that (ep 96's second Cafecito overlapped the first by 8 s).
- **Crossfades are equal-power over a 2.5 s window before the start shot (fixed 682f6ae, 2026-09-28).** Before the fix, both songs played at full level for up to 5 s (ep 96 QA). A section's track time at its start shot is unchanged.
- **Some Audio Library tracks open near-silent for ~20 s** (ep 97: Rolling Hills sits ~−30 LUFS until 20 s), so a payoff section sounded empty. Measure the first 30 s of every track and set `in` past a quiet intro.
- **Level fixes can push true peak over −1.5 dBTP** (ep 97: +4 dB on quiet shots moved the loudnorm gain and the opening music peaked at −1.3). Re-measure after any gain change; `"gain": -1.5` on the offending music entry fixed it. *(Since 2026-10-01 the master loop lowers its ceiling by itself. Boosted shots also get a peak guard.)*
- **Two ASR passes of the same model can disagree on short exclamations** (ep 97: 好嘞 vs 好累 between Qwen runs). Prefer the reading two different models share; for one-word interjections, drop them rather than guess.
- **Qwen "oh oh" is NOT a reliable vocal detector for music.** It outputs "oh oh" on most instrumentals (even a waltz) and missed real chants. Listen to suspicious tracks, or ask for a listen at review.
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
- *(Superseded 2026-10-01 by 60 ms equal-power crossfades with source handles. The 12 ms out/in fades left a 24 ms dropout at every cut; they are now only a fallback where neither side has a handle.)* **Every shot's audio gets 12 ms edge fades** (renderer default since ep 86): a hard cut on wind noise clicked
  (~2000-unit sample step) even with no stop-button click nearby. Cache key bumped with it.
- **Title-card sub-lines need an outline** on bright rock/sand (ep 86 QA: unreadable at 1:00) — done in `overlays.title_card`.
- **A quiet guide / relayed explanation sinks under the mix:** measure the voice stem per shot and lift with `gain_db`
  (ep 86: guide Q&A +10 dB, the Alien Throne talk +4, the Chaco line +5) — check this in round 1, not round 2.
- **`tighten` rewrites every talking shot's `skip` list** (it drops hand-made skips): keep manual skips in a small merge script and run it after tighten (ep 90's `edit/scripts/merge_manual_skips.py`).
- *(Superseded 2026-10-01: the linear master loop lands at −14.0 ±0.2.)* **Why previews land at −14.9/−15.0 LUFS, not −14 (measured ep 90):** the pre-loudnorm mix is ~−18 LUFS with true peaks ~−2.5 dBTP; raising it 4 dB would break the −1.5 dBTP ceiling, so single-pass dynamic loudnorm stops ~0.9 LU short. The post-limiter is NOT the cause (same −14.9 without it), and a pre-limiter only gained 0.1–0.2 LU. Within ±1 LU; fixing it properly needs speech-peak compression before loudnorm.
- **Reviewers must not write QA remarks into shot `note`s** (ep 90 round 2 appended "| QA2: …" to card titles) — changelogs go in the report / HANDOFF.
- **GoPro clips start with ~40–66 ms of digital silence** (ep 87 QA heard gaps at 1:44/1:48 in the music-free
  section): a shot with audio should never start at `in: 0.0` — use ≥ 0.1. Measured on the cached segment WAVs
  (`/tmp/yt-editor/<project>/seg_*/sNNN_*.wav`); afftdn was NOT the cause (tested on a tone + a real clip).

- **Reusing a short track within one episode needs the arithmetic, not a guess (ep 100):** list every section's span and each reuse's `in`; the second use must start after the first use's `in` + span + 5 s AND end before the track does (or it loops back into audio already heard). With 12 sections and 7 fetched tracks three reuses failed both tests; fetching two more tracks was cheaper than fiddling `in`s.

- **A 2:17 track under a 3:27 section loops back to its start** (102 round 1: a 2-s near-silent hole at the loop
  point, caught by the per-second loudness scan). Check every section's span against the track length (+ `in` +
  2.5 s lead) before the first render.

### Audio pipeline 2026-10-01 (research R1, R2, R3, R11-lite; measured on 100 / 102 / 104)
- **The "two-pass linear" loudnorm never ran linear.** ffmpeg only goes linear when the measured TP fits, and on
  our mixes (peak-to-loudness ratio 15–20 dB) it never did. Every master was really an AGC.
  102 and 104 ended at −1.2 / −1.4 dBTP. The new master: linear gain → 4×-oversampled limiter
  (ceiling −2.5 dBFS) → AAC → decode and measure → correct the ceiling or gain (≤ 4 tries).
  Results: 100 −14.2 LUFS / −2.1 dBTP, 102 −14.0 / −1.9, 104 −14.0 / −2.1.
- **ffmpeg's native `aac` overshoots badly on limited music.** On 102 it went +1.7 to +4.4 dB over the ceiling,
  and lowering the ceiling made it *worse*. AudioToolbox `aac_at` stays within about +0.4 dB and is sample-aligned.
  The renderer uses `aac_at` when it's available. If you ever see TP chaos, check the encoder first.
- **The linear master keeps the edit's own balance, and that cuts both ways.** LRA rose (102: 8.7 → 12.6) because the AGC
  no longer lifts quiet passages. 102's quietest captioned lines (a distant guide) are about 3 LU quieter than under the old AGC.
  Level uneven speech per shot with `gain_db` (R4 below). Don't count on the master to do it.
- **TTS:** the edge-tts output keeps a peak-to-loudness ratio of about 19 dB. The VO chain (high-pass, EQ, de-ess,
  4:1 compressor, limiter) brings it to about 11. The level is the **median caption loudness** of the
  episode's on-camera speech (+0.5 LU). The power mean is dominated by loud lines: after the master limiter
  it left narration 2.5–5.7 LU above the median line. The old fixed `+4.5 dB` made 102's lines the loudest voice
  in the video (+4.4 LU over the median line). They are now −0.1. Re-transcribed: identical to before.
- **Cuts:** the dialogue track is overlap-added with 60 ms equal-power crossfades using 30 ms of real source sound past
  each edit point. In 100, digital silence at 59 of 65 cuts with sound on both sides went to 0. In 104, < −60 dBFS
  dips at skip joins went from 18 to 2. The remaining dips match the same statistic 0.15 s away from any cut.
- **Peak guard (R3)** has an adaptive ceiling (shot loudness + 12 dB), not a fixed −9 dBFS. Boosted shots range from −41
  LUFS (102) to −14 LUFS (95 s063), and one fixed ceiling is wrong for one end or the other.
- Video and audio segments have separate caches. An audio change re-renders only PCM: about 30 s for a 12-minute episode.
- **Lint now warns** about narration over 4 字/s or < 0.3 s after a cut, 60 s of talk with no ≥ 4 s break, and > 3 sfx per minute.
  On 95–104: 100 has a 163 s talk run (3:54–6:37), 95 one of 127 s, and 102's Cat Haven line runs 5.0 字/s.

- **R4 dialogue levelling (render time, not in the EDL):** each voice shot's caption-window speech is measured after
  denoise + manual `gain_db`. Shots more than 3 LU from the speech-time-weighted median move to the band edge
  (−6…+8 dB). Captions under narration are skipped. On 102 it took the linear master's LRA from 12.6 to 8.4,
  and the quietest 10% of lines from −23.5 to −20.5 (original AGC'd preview: −20.7). **A ±2 LU band flattened 100 to
  LRA 6.0**, which is too flat for a vlog. The band is ±3 (100: 8.4 → 7.0).
- **The linear master changes the music/speech balance on talk-quiet episodes.** On 102, music-only stretches went from +1.7
  to about +3 LU above the median spoken line, because the old AGC used to pull montages down. Levelling doesn't fix that;
  R6 (music level relative to speech) would. Until then, lower `music_volume` if the montage music feels loud.

### Audio follow-ups (research 2026-10-01, not done yet, in priority order)
1. *(R4 dialogue levelling: done at render time, see below.)*
2. **R5 duck shape.** Today's duck ramps are symmetric, linear in amplitude, 0.5 s. Replace them with dB-domain ramps that
   reach the duck 0.1 s before the first word (0.25 s attack), hold 0.4 s, and release over 1.1 s. In gaps < 3 s, rise only
   halfway. Render the envelope as audio and `amultiply`, which also removes the per-frame-expression bug class.
3. **R6 adaptive duck depth + music level.** Put the music about 15 LU under each speech window's own loudness (clamped to
   8–22 dB), and keep `music_duck` as a floor. Do it together with R5. Also tie the un-ducked `music_volume` to the
   episode's median speech level: the linear master left 102's music-only stretches about 3 LU over its median line.
4. **R7 music endings + R10a no raw loop.** Back-time the last track (`"end": "natural"`) so it ends on its own final hit.
   Stop fading 5 s from mid-song, and button sections on a bar line. Extend a short track with a bar-aligned internal edit,
   never `-stream_loop`.
5. **R8 beat grid.** Write `edit/music/.analysis/<file>.json` (librosa, or the `exp/beats.py` fallback). Snap a section's
   `in` so a downbeat lands on its start shot when confidence is ≥ 0.5.
6. **R9 montage cuts on beats.** Proposals, or `--apply`, for ±0.25 s out-point moves on speechless shots inside music
   sections. Report the "% of montage cuts on beat" in QA. Do it after R8.
7. **R10b/c silence as a tool.** Lint ≥ 1 music-free stretch of ≥ 4 s per 3–4 min. Music stops (not ducks) for
   reveals, and doesn't come back under a punchline.
8. **R11 full: J/L-cuts.** Add `audio_lead` / `audio_tail` per shot. The handle and overlap-add machinery exists now, so only
   the per-shot handle length and a lint against speech in the handle are missing.
9. **R12 ambience beds + nat pops.** One continuous location bed under a montage, J-cut 0.5–1.5 s ahead.
10. **R13 SFX:** add `align: peak`, `level_lu`, `duck_music`. Lint: the same file > 2× per episode, an sfx over speech,
    a whoosh on a static cut.
11. **R14 remaining VO lints:** audio longer than its window − 0.5 s, narration over on-camera speech, < 1.5 s between lines.
12. **R15 PCM audio in the final `.mov`.** Verify with one private YouTube upload first.

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
| 91 | City "postcard" title card (`card.image` mp4, pure ffmpeg, no renderer change): vintage "Greetings from SAN DIEGO" with airmail border + postmark; each Impact block letter is a live window onto a different shot of the day (carrier, tall ship, El Prado, Lily Pond, tower, tacos, Gaslamp, the seafood pot) via per-letter Pillow masks + `alphamerge`, letters fade in left→right (script: 91's `edit/scripts/make_cards.py postcard`; crops must be even-sized for yuv420) | Reads instantly as "new trip, new city" and previews the whole day in 4 s; reviewers: renders cleanly, 0:00 window 9/10 | Yes as the opener of a new trip/city (first episode of a series). **Creator loved it (2026-09-29).** |
| 91 | Day/night split card (`card.image` mp4): the Old Town arrival (4:05 PM) and the dinner arrival (5:30 PM) side by side, the night half wipes in, clock labels + "冬天的圣地亚哥，天黑得好早"; plus food "macro + sizzle": a 1.5→2.3× punch-in on the adobada trompo and a synthesised sizzle sfx (band-passed noise + tremolo, gain 0.35) under the hook/pot shots | Split: a time jump in 3.6 s, windows around it 9/10. Sizzle: subtle, no peak issue (−2.1 dBTP) | Split: yes for same-place/time-of-day contrasts. Sizzle: fine for food beats; keep it quiet |
| 93 | Blueprint line-draw reveal (`card.image` mp4, Pillow only, no renderer change): FIND_EDGES on the graded 4K Geisel Library frame, masked to the building's box, drawn as white lines on a blueprint grid from bottom to top with a scan line, plus a dimension line and architect/year labels; cross-fades to the real frame at 2.9 s, then a myth-check line ("网传《盗梦空间》参考过它？剧组从没证实过") | Reads as "how it was designed" in ~3 s; round-1 window 1:00 scored 10/10, no reviewer issues. Edges pick up foreground trees too; mask tightly | Yes for striking buildings (architecture episodes); script: 93's `edit/scripts/make_cards.py` `blueprint()` |
| 93 | Tilt card as a transition (The Fallen Star): push-in to the house, "平台 5° / 房子 10°" labels, then the whole frame rotates 15° (scale-up ≥ 1.46 so no black corners at 16:9) and hard-cuts to the next place | Playful, matches the subject; reviewers had no complaints. First render showed black corners at a 1.35 scale-up | Yes when the subject itself is tilted/rotated; keep the spin ≤ 1.2 s |
| 93 | "Why" diagram answering the cold-open question (old lighthouse 1855–1891): drawn cliff profile, the beam swallowed by a low cloud, the 1891 lighthouse down by the water, inset of today's real lens shot; the hook's note asks "只亮了 35 年——为什么？" | Gives the episode one open loop; round-1 window 3:30 scored 10/10. Labels must fade out when the inset pops in (they overlapped once) | Yes when the footage has a sourced "why" (history, geology); pair with a hook question. The golden-hour colour ramp was NOT possible: grades are static per shot and a split-shot ramp would step |
| 94 | "Christmas in the desert" title (`card.image` mp4, Pillow only, no renderer change): fairy-light garlands as quadratic curves between the Joshua tree's crown clusters (located on a 4K frame), bulbs switch on along the string and twinkle (per-bulb sine + blurred glow layer), ornaments, title fades in on the sky | Reads instantly as "holiday + desert"; reviewers: renders cleanly, 0:00 window 11/12 with promise. Bulbs need ≥ 36 px cores at 4K or they vanish at 1080p | Yes for holiday episodes; any seasonal decoration drawn onto a located landmark |
| 94 | Rock-shape outline reveal (`card.image` mp4, Pillow only): eased push-in 1→2.4× on Heart Rock, then a parametric heart fitted to the boulder's located 4K bbox draws itself from the notch (pink glow + leading dot), label pops in; the 三连 line is baked into the same card because cards draw no subtitles | Both reviewers: outline sits on the rock; window 2:30 9/10. Fit the shape to the bbox of the real object, and put the push-in target so the object stays centred | Yes for named rocks/"looks-like" landmarks (Skull Rock, faces, animals in rock) |
| 94 | Weather-contrast cut with no rain footage: a neutral "grey" grade + a sourced storm note on the only 12/24 clip, hard cut to the blue-sky 12/25 title | Cheap, clear day change; no reviewer complaints | Yes when a day's weather flips; source the weather fact (news) |
| 95 | Equation-chalkboard title for a university (`card.image` mp4, Pillow only): noise-textured board + erased-chalk smudges + wood frame; "Caltech" (Chalkduster) and "加州理工学院" (HanziPen SC) write on left→right behind a moving mask with a chalk dot at the front, doodled equations/atom, then two sourced facts in yellow chalk (script: 95's `edit/scripts/make_cards.py chalk`) | Reads instantly as "campus / science"; reviewers had no issues with it. Chalkduster lacks ² (draw superscripts by hand); a shutter sfx on it spiked true peak to −0.6 dBTP — no sfx on calm cards | Yes for schools/science places; keep facts from research.md |
| 95 | Museum wall-label cards (`card.image` mp4): eased push-in on the painting's freeze, then an off-white label (Georgia caps/italic + Songti, drop shadow, red rule) slides up beside it — artist, dates, EN/中文 title, then the fact. The Blue Boy label answers the cold-open question ("1921 年 72.8 万美元，当时最贵"); the Pinkie label carries the comment question | Both reviewers: clean and legible; window with the answer 8/10. Size text for 1080p (≥ 66 px Songti at 4K) — the first version was too small | Yes for art/museum pieces and any object with a "label" worth of facts; pairs well with a hook question |
| 95 | Rain-garden "macro" run: 3 punch-ins (1.2–1.8×) with a `macro` grade (saturation 1.3 + `vignette=PI/5`), shots cut on whole beats of a 120 BPM track (`in` chosen so track time at the first shot = in + 2.5 s lands on a beat) | Short (~9 s) and pretty; round 1 made one shot a talking shot (he was speaking under it), which broke the beat grid but kept a fun line. GoPro wide punch-ins read as "detail", not true macro | Maybe — worth it when there are ≥ 3 silent detail shots |
| 95 | Food reveal with a hit (`card.image` mp4 + `sfx/hit.wav` synthesized: pitch-dropping sine thump + noise transient): push-in on the live shot → freeze card: dimmed plate, at 0.35 s hit + white flash + 1.25× snap-zoom + a gold ring bursting from the dish, then label and the 三连 line | Punchy without being cartoonish; hit at gain 0.6 stayed under the limiter (−1.9 dBTP overall). Reviewer: the handheld pull-back vs the digital push-in right before it is "acceptable" | Yes for the one hero dish of an episode; one per video |
| 96 | Sunset countdown timelapse (`card.image` mp4, pure ffmpeg, no renderer change): 110 s of the sun dropping into the sea at 13× (`setpts`), a golden-hour grade that ramps frame by frame (`eq=…:eval=frame` with `min(t/T,1)` on saturation / contrast / `gamma_r` / `gamma_b`), a live "当地时间 下午 4:52:53 → 4:54:37" clock (Pillow PNGs at 10 fps, overlaid) computed from the clip's camera time, ending on a pill "官方日落时间：下午 4:55" (research) and a 1.8 s held frame; followed by a music-off breathing room | The "grade ramp" that LESSONS said static grades can't do works inside a card: the colour warms continuously with no stepping. Reviewers: clean, windows around it 10/10; the camera clock matched the sourced sunset within ~20 s | Yes for any sunset/sunrise/golden-hour clip ≥ 60 s; script: 96's `edit/scripts/make_cards.py sunset` |
| 96 | Passport-page trip stats (`card.image` mp4, Pillow only): a guilloche passport page, 13 ink stamps (one per episode 84–96, circle / rectangle / octagon, worn-ink mask, random tilt) thud in 0.19 s apart with a synthesized stamp sfx (`sfx/stamp.wav`, low sine drop + paper noise) on each landing, then counters roll up (15 天 · 13 集 · 3 个州 · 4 座国家公园 · 约 2000 英里), then the whole-trip comment question in a bar | Reads as a real "trip summary" in ~6 s; reviewers: text fits, thuds land within ±1 frame once the sfx were set to the landing (the stamp lands 0.12 s after it appears). QA caught a wrong count (3 → 4 national parks: a drive-through park from another episode) — check every stat against all episodes' HANDOFFs | Yes for series finales; script: 96's `make_cards.py passport` + `stamp_sfx` |
| 96 | Plane-window end screen (`card.image` mp4, ffmpeg overlay): a drawn cabin wall with a superellipse window (bevel rings, pulled-down shade, glass glint) cut out as an alpha hole; the day's last sunset plays through it with a slow sideways drift; "LAX → EWR · 晚上 10:55 · 回家", "谢谢你，陪我们走完这趟旅程", "订阅一下，下一趟旅行见 →" on the right; the lower right stays empty for YouTube's end-screen elements (18 s) | Calm, clearly an ending, no next-episode teaser needed; reviewers: no issues, end window scored low on novelty by design | Yes for the last episode of a trip (a teaser end card otherwise) |
| 99 | Then/now wipe with a public-domain archival photo (`card.image` mp4, Pillow only): a c.1900–1910 Library of Congress / Detroit Publishing Co. glass negative of the steamer *Horicon* at the Lake George dock, border cropped, sepia-toned; a white slider with a round handle wipes right→left to today's frame of the same dock, labels 约 1900–1910 / 今天, one sourced fact bar, the credit on the card (script: 99's `edit/scripts/make_cards.py thennow`) | Reads in ~4 s and gives a silent 50 s stop a story; a research sub-agent found + downloaded the TIFF/JPG with the rights line in one pass | Yes when a place has a PD photo from roughly the same spot; credit on screen + in the description |
| 99 | Farm-stand receipt that prints line by line (`card.image` mp4): thermal-paper strip grows out of a printer slot over a blurred frame of the store, one line per 0.42 s, total in red, then a worn-ink stamp thuds in; titled 示意 with the sources (audio, scale, the farm's 2024 page) | A natural end-of-day summary for any shopping/market/farm stop; only verified numbers (a 4K crop of the scale read 6.92 lb) | Yes for purchases/markets; never invent line items |
| 99 | Vintage fruit-crate-label end screen: cream label, red/green rings and banner, drawn cherries; the day's footage plays in the oval window; thank-you + playlist line upper right, lower right clear for end-screen elements | Calm, clearly an ending, themed to the episode (like 96's plane window) | Yes for trip finales; theme the frame to the last episode |
| 98 | Live river mini-map as a picture-in-picture inset (new renderer feature `pip`: framed still/animation/second clip over a shot for [t0, t1], white border, alpha fades): the real OSM river line (put-in → take-out), a red dot easing from mile a to b and an "约 X 英里 / 17" header, shown top-right for ~5 s at each chapter (launch, lunch, gorge ×2, float, railroad bridge, take-out). Miles are anchored on verified landmarks (the rail trestle, the take-out) and interpolated by moving time, labelled 约 · 位置按时间估算 | Turns a long run of same-looking POV rapids into a journey with visible progress, without cutting away from the action; pips cost ~1 min to render (Pillow → 1000×800 mp4) | Pending review — yes for any long single-route day (rivers, hikes, drives, boat trips) |
| 98 | Real-data explainer card: 11 days of USGS 15-min river-flow data (public domain) drawn as a self-drawing line, the dam-release pulses on Tue/Thu/Sat/Sun ticked, "我们这天" boxed — answers "why are there rapids in July?" with the day's own data | Research found the gauge; one Pillow card, no renderer change | Pending review — yes when a public dataset explains the place (tides, flow, snow depth, crowds) |
| 98 | Archival cutaway from outside material: a public-domain Winslow Homer watercolour of Hudson log drivers (1891–92, NGA) dissolving into an 1897 NY State log-jam photo, 3 sourced lines, credits on screen, placed right after the rapids ("一百多年前，这段激流上漂的是木头") | Calm history beat between the rapids and the floating; outside material rule from ep 92 | Pending review |
| 97 | Mirror Lake reflection title (`card.image` mp4, numpy + Pillow, no renderer change): the live beach shot is cut at the located far shoreline; below it the same picture is mirrored with a per-row perspective ripple (wavelength and amplitude grow toward the viewer) that calms from "stirred" to glassy over 2 s; the title letters stand on the waterline so the lake reflects them; the water "rises" to the waterline at the start (script: 97's `edit/scripts/make_cards.py mirror`) | Reads instantly as "镜湖" and as a new-trip opener; 0:00 window 12/12 in round 1. 4K numpy remap costs ~3.5 min per 4.6 s card on a busy Mac. Keep sub-lines clear of the mirrored text | Yes for any lake/water town opener; the name-explains-itself idea generalizes |
| 97 | Archival then → now timeline card: a 1932 PD photo → a real 1980 Miracle on Ice photo (CC BY 2.0, credit on screen) → a wipe with a light edge to today's frame, with a 1932–1980–今天 timeline bar and sourced lines (incl. "中国第一次参加冬奥会"); plus a 1902 LoC photochrom aside after the beach | Window 1:00 scored 10/10; reviewers checked every fact against research.md. Label the "now" tick 今天, not the filming year, when a fact changed since (4 twice-hosts since Cortina 2026) | Yes whenever a place has datable history and freely licensed photos (Commons API gives licence + credit) |
| 97 | Clock route maps on OpenStreetMap trail geometry (Overpass `out geom` → chained ways → dashed route drawn along real trails with a running clock panel), split into an "up" leg at the trailhead and a "back" leg that stops at 6:35 PM "还剩约 1 小时" right before his "走了七个小时" | Gives a 7-hour hike a shape; windows around both maps 9–10/10. The route taken must be confirmed or labelled 示意 | Yes for hikes/walks: default route maps should use OSM geometry now (script: 97's `make_cards.py maps`) |
| 100 | "From above" claim-check card (`card.image` mp4, Pillow only): the guide's spoken "从天上看像一个十字" — the ground shot pushes in and dissolves into a real public-domain aerial photo (USDA NAIP via USGS The National Map `exportImage`, bbox from OSM), rotated so the lawn is level; the academic axis (Sterling ↔ William L. Harkness Hall) and the residential axis (Berkeley College N ↔ S) draw themselves, labelled, then it dissolves back to the next ground shot. Framed "导游说" because research couldn't source the name's origin | QA r1: 9:00 window 10/10; labels needed ≥ 64 px heavy sub-lines at 4K to read at 1080p. Features must be located on a gridded crop of the photo first | Yes whenever someone makes a spatial claim (shape, layout, "from the air") the footage can't show |
| 100 | Real-map route cards drawn from OpenStreetMap (Overpass JSON → buildings/streets/greens rendered in Pillow; day 1 red, day 2 blue on a zoomed campus map, both days on the end screen with the map fading into paper for end-screen space) | Reads as a real place, not a sketch; QA had no issues | Yes: better than hand-drawn schematic maps for city walks |
| 100 | Archival picture-in-picture over the live shot (`pip` with a white-bordered still + baked caption strip): a 1749 Yale College engraving (NYPL, PD) over Old Campus, a 1930 LOC photo of Sterling while the guide's "church" story plays | Cheap and informative; a side-angle archival photo can't be match-dissolved, a PiP works | Yes when the archival angle doesn't match the live one |
| 95/96 v2 | Short edge-tts context lines with no renderer change: each sentence generated separately (numbers/foreign names written in Chinese so Yunxi reads them right: 一九一九, 杜梅茨), edge silence trimmed, `loudnorm I=-18`, placed as the shot's `sfx` plus a caption at the same source time so the SRT carries it. **Since 2026-10-02 that caption is `kind: "note"`** (white = real speech only); the renderer ducks the music under every `tts/` sfx by itself. 95: founder + 120 acres over the garden map, right before her "有这么大"; 96: the Point Dume name typo over the drive down. A sentence can't cross a cut (sfx is per shot): fit each line in one shot, adjusting the drive's speed. Whisper hears the lines word for word (homophones aside) | Pending creator review (voice choice) | Yes for 1–2 facts per episode the footage can't show; keep the creator's own explanation and put TTS only where she isn't talking |
| 95/96 v2 | Thumbnail "sticker" dual outline (two centre-anchored text layers: thick white outer stroke + halo, then thin black stroke) with one red/orange accent word, spotlight via hero `regions` + `shade`, one subject + a small location pill | Art director 8/10 sign-off on both mains. A white inner stroke on white text bloats the glyphs into blobs: inner stroke must contrast with the fill | **NO: creator 10/1, "太丑了、太粗了".** Rejected; use the 94-G treatment (clean heavy type, thin dark stroke 0.012–0.015, soft halo, white + one yellow accent) |
| 99 v2 | "果园图鉴" specimen tags (no renderer change): a small cream field-guide label (`pip` of a 6 s Pillow mp4, top of frame, ~4.5 s) right after each FIRST taste of a new fruit, No.1–5 / 5: round real 4K crop of the fruit, CN/EN/Latin name, one sourced fact only where it adds something, and a red ink stamp with our OWN on-camera verdict (甜/酸/涩/像果酱) landing 0.6 s in with a synthesized two-note marimba sting (`sfx`, gain 0.3) | Turns five repeated "pick → taste" beats into a collection with a visible count; reads at 1080p with ≥ 56 px text at 4K on a 1240-px label. Check each tag frame for faces under it (one had to move off a cap). Script: 99's `make_fieldguide.py` | Pending review — yes for any "tasting several kinds" day (fruit, dumplings, beers, cheeses) |
| 100 v2 | Narration via the new EDL `voiceover` layer (commit 0bd1474): one edge-tts line (Yunxi, −5 %, +4.5 dB) runs from the postcard into the route map; a second over a new 8 s push-in card on the empty hall. Cards draw no subtitles, so the captions are baked into the card mp4s with `overlays.subtitle` and also put as subs on the card shots (they only feed captions.srt) | No cutting at shot ends (a shot `sfx` is trimmed there); music ducks under the line automatically | Pending review |
| 100 v2 | Aerial claim-check card as a full-frame `pip` (w 1.0, border 0) over the guide's own talk instead of a separate mute card, held on its last labelled frame (`tpad` clone) for the whole "横竖…左右…" explanation, back to him for the punchline | Shorter, the picture matches the words; pip can't loop, so pad the mp4 to the span | Yes when a card illustrates what someone is saying |
| 97 v2 | Trip-opener postcard "Greetings from the ADIRONDACKS" (91's per-letter `alphamerge`, 11 letters = 11 shots of both days, per-letter crop centre so a narrow I/S still shows its subject) placed right after a live-voice cold open and before the route map, 3.0 s; the earlier mirror-lake title moved after his first beach line. Director's analytics asked for live voice by 3–5 s and a title by ~10 s: the hook now opens on his own overlook line (lake behind him) instead of three mute notes | Title at 0:11 (was 0:55 to the day card), first voice at 0.3 s (was 30 s). Stills checked before the encode; the 0.3 s frame shows the empty letter shadows (as on 91) | Yes for new trips: live line → 2 notes → postcard (≤ 3 s) → map |
| 98 v2 | Cutting a same-angle POV run (life-jacket rapids 3:42 → 1:41, 8 distinctive takes) instead of decorating it, plus two sourced TTS lines on the `voiceover` layer (why summer rafting exists; the gorge's class-IV stretches). Over loud whitewater the TTS needed +6 dB and the shot's ambience −6 dB before whisper could transcribe it from the mix | 12:58 → 8:52 with every card, inset and payoff kept; no 30 s stretch without a beat. Check a TTS line over noise by ASR-ing the rendered mix, not the clean mp3 | Yes: cut POV runs to the takes that differ; TTS over loud action needs a level check |
| 102 | **Spotlight** (`spots`, new renderer feature d66b964): the frame dims to 55 % except a soft circle with a yellow ring + label on an animal in shade or behind wire (lioness, caracals, tiger, white tiger) | Finds the animal at a glance without a punch-in that would blur a 1080p DJI frame; fades 0.3 s. Place the circle on frames from the actual moment (one ring sat on a cage post until re-aimed) | Pending review — yes for zoo/sanctuary fences and wildlife in shade |
| 102 | Docent-claim check: a guide's wrong number is captioned as "导游说：…" and followed by a note with the sourced figure (cheetah: "72 mph in 10 s" → 0–60 mph in < 3 s) | Keeps the guide's voice and the fun, without repeating an error as fact | Yes whenever a guide/sign states something research contradicts |
| 102 | Trip postcard spanning three episodes: the letters of "SEQUOIA" show shots from all three days (peaches, pupusas, Sherman, Tunnel Log, Roaring River Falls), in the first episode only | Previews the whole trip in 3 s; 103/104 skip the postcard and use only the route map | Yes: one postcard per trip, in its first episode |
| 103 | Tree-ring timeline card: a sequoia cross-section grows ring by ring, dated rings light up (2,300–2,700 years ago, 221 BC, 618, 1879, 1890, 2026), labelled 示意 / 年龄为估算 with the NPS source | Turns "the biggest tree" into "how old is it" with Chinese-history anchors | Pending review — yes for old trees / long-lived things with a sourced age |
| 104 | Terrain cross-section card from public-domain USGS EPQS elevations (60 points across the canyon, river 669 m → peak 3,042 m), hillshade inset shows the line, vertical stretch labelled 示意 | Makes "deeper than the Grand Canyon" visible with real data | Pending review — yes for canyons, passes, climbs |
| 102–104 | **Letter frame (research R9) — rejected before it was built (creator, 2026-10-01):** a 「亲爱的朋友…」 greeting on the trip postcard, 「第二封/第三封」 openers, a 「P.S. …回信告诉我」 card at the finale. He said "亲爱的朋友" feels fake | Never rendered; nothing to remove | **No.** Don't frame episodes as letters or turn the comment ask into a P.S. Comment questions stay in the description / pinned comment (§2b.8) |
| 102–104 | Trip-series day marker instead: 「红杉 & 国王峡谷 · 第 N/3 天」 as a `tag` pill, top-right (`"tag_pos": "tr"`, new), first 3 s of each episode's route-map card; cards can now carry a `tag` (renderer change, `scripts/test_card_tag.py`). One field to remove: clear 左上角地名 on the review page | Small, calm, readable at 1080p; it doesn't touch the cards' own titles (top-left). 102 spans days 1–2, so its tag says 第 1/3 天 at the opening and the existing 第二天 title card covers day 2 | Pending review — yes for multi-episode trips if he likes it |
| 104 | Trip-finale coda: (a) a 3.4 s hold on the last SF night frame (gentle push-in) with one plain closing line as a note (「这三天，从桃园、大猫到巨杉林，最后开进了国王峡谷」, no question); (b) a 9.1 s **photo-print slideshow** (R8): 6 graded 4K video stills from all three days drop in as white-bordered prints with handwritten date/place labels (HanziPen SC), slight tilt, Ken Burns on the top print, slow push on the stack (`scripts/photo_coda.py`, generic, `--stills` animatic first); then the 14 s end screen. The last track is back-timed (`in` = 95.44) so the slideshow sits on its last-but-one phrase (dip at 136.0 s) and the end screen gets the final phrase + its natural ending | Animatic caught one real problem: an alpha **fade-in made the incoming print translucent**, ghosting the print below (two labels overlapping). Prints now slide in opaque from below the frame. No photo exports exist for this trip (only DJI clips), so the "photos" are video frames; the windshield afterglow shot needed a crop above the dashboard | Pending review — for trip finales. Ask him for phone photos next time (R8 wants real stills) |
| 95 | **Live review via the page chat (2026-10-02):** about 45 notes in one sitting, mostly captions (ASR words, pronouns, fillers, long cues), takes (keep the best), restored unique shots, no obvious arrows, no dates, outside material that confused (cast photo, an unfamiliar US show), and music mood. Raw-page captions regenerate from `scan/srt` + the EDL, so fix the *raw* srt, not `srt_clean`. Stumble cuts were verified by re-transcribing the joined audio. | All folded into SKILL §2c "Lessons from the 95 live review". |
| 108 | **8-second ride ring timer** (`cards/timer.mp4`, the episode's `make_cards.py` `ring_timer()`, no renderer change): a real bull ride punched in 2×, a top-right ring fills toward the 8 s qualified-ride line from the gate opening and **freezes red when the rider is thrown (≈3.7 s, measured on 10 fps crops)**, then one sourced bar (about a third of pro rides reach 8 s); sets up his own line about the 8 seconds | Reviewer 10/10 for that window; turns a 7 s ride he can't explain on camera into a rule + a result | Pending review — yes for any timed feat (rides, holds, sprints, dives); reuse `ring_timer()` |
| 109 | **Split-flap departure board end screen** (`scripts/splitflap.py`, generic, JSON spec, `--stills` animatic, synthesized flap clicks): rows flap to FROM DALLAS / TO SAN ANTONIO / 约 5 小时 / 下一集 … over the bus-window view, series line under it, lower right kept free | Reads instantly as "departure → next stop"; animatic caught thin Latin glyphs (→ DIN Condensed Bold) and the board hiding the landmark | Pending review — default candidate for any episode that ends on a bus/train/flight hand-off |
| 110 | **Collection tally 动物图鉴 1→13** (`src/editor/tally.py`, via `pip` PNG-in-MOV alpha): each species' first good appearance pops a card (real 4K round crop, No.k/13, CN/EN name, one sourced fact, soft chime), which folds into a riding 「动物图鉴 k/13」 badge; a recap grid closes the section. Plus **voice-stem rescue**: shot field `audio_src` plays a gated Demucs vocal stem so in-car reactions survive without the car-stereo song | Safari windows 9–10/10: 7 min of "another animal" gets a count and a destination. Stems: clean while the song is instrumental; the stem keeps the singer while he sings → ASR the stems and mute those spans | Pending review — tally for any collect-them day (animals, dishes, landmarks); stems whenever music under speech is a Content-ID risk |
| 111 | **Queue clock inset** (`cards/queue_*.mp4` via `pip`): analog clock + digital time + 已经排了 X + a 排队 → 进门 → 点餐 → 开吃 bar, animating between the four Franklin shots' own clip times (labelled 按镜头时间) | A 90-minute wait reads in 35 s with no waiting footage; legible, no caption/face overlap | Pending review — yes for any wait (queues, ferries, lifts, timed tours) |
| 112 | **Speech-synced reveal strip** (transparent 3840×760 PNG-in-MOV via `pip`, w 1.0, border 0): six empty slots; each real floor seal (cropped from his own 4K footage, perspective-squared) pops in on the word he says it, CN/EN name + years; all six glow on "Six Flags" with a one-line origin pill | 1:00 window 10/10; keeps his live talk on screen while adding the information | Pending review — yes whenever someone lists N things the camera can show |
