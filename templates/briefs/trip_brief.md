# Trip brief template (master director → episode directors)

Copy to `sessions/<trip>_brief.md` (private, not committed) and fill in. Each director gets a short prompt: "read the brief, SKILL.md, LESSONS.md; your episode is X; check `src.editor.checkpoint` status first". Proven on Texas 108–112 (2026-10-07).

## The trip
- **Plan:** `sessions/trip-notes/<trip>.md` (a plan, not a record; verify against the footage).
- **Camera clock:** state the offset you found (GPSU / GPS fixes / daylight / speech), e.g. "GoPro date is exactly one day behind".
- **Travel modes between places**, as the footage shows them.
- **People:** the creator and companion are never named on screen.
- **Episode table:** | Ep | Project folder | Real day(s) | Clips |
- **Already staged per project:** `scan/srt` (Qwen + `asr_context.txt`), `scan/words`, `scan/sheets` + grids, `scan/meta.json`, `scan/gps_times.tsv`. Don't re-run the full ASR.
- **Known ASR / audio traps:** context echo, lyrics from car stereos / PA / shops (mute them or use `audio_src` voice stems), guides' English.

## Series rules
- Series name and an episode pill on the route-map card (「<series> · 第 N/M 集」, `tag_pos: tr`).
- The first episode carries the trip postcard (letters from all episodes) plus an overview map. The others carry the route map only.
- Route maps follow real roads (`src.editor.routemap`).
- **Placement per §2b-data:** maps and postcard go after the first live scene.
- **End:** one teaser line for the next episode, ≤ 10 s. The finale points to the playlist and may use the photo-print coda.
- No calendar dates on screen.

## The creator's standing feedback
Restate the latest requests verbatim, then point to SKILL §2b, §2b-data, §2c and the last bullets. Always included:
- clean takes only, high-standard captions;
- no filler captions;
- no runtime cap;
- bilingual first mentions, dishes named;
- calm tone, no on-screen comment asks;
- fresh music with no vocals;
- one new technique per episode (log it).

## Music
The master fetches disjoint pools: `sessions/<trip>_music.md`, files in `~/Movies/yt-music-library/`. Directors don't use the browser.

## Process and deliverables
1. Usage log (start/end).
2. Watch every grid and transcript.
3. `research.md`, `outline.md`, the EDL.
4. Proofread captions, then `--mark-proofread`.
5. Questions → `questions.json`.
6. Preview, then QA rounds 1–2.
7. Thumbnails (3 editorial options, both platforms).
8. HANDOFF: two open-loop Shorts plus a backup, the comment question, the experiment, lessons.

Checkpoint every step. No final render, upload or commits; list repo code changes for the master to review.

After the directors finish, the master runs **an independent strong-model QA per episode** (template: `qa_brief.md`) and a strict thumbnail review across the series.
