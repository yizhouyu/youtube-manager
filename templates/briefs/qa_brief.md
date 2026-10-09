# Upgrade / independent QA brief (template)

Used on 2026-10-08 for the independent QA of 108–112 and the upgrade passes on 100–107. Copy it to `sessions/` and adjust the episode-specific notes. The reviewer must be a **fresh agent on the strongest model**: directors' self-reviews and cheaper-model reviewers missed real errors. They missed:
- a wrong animal name;
- lines put in the wrong speaker's mouth;
- car-stereo lyrics still audible;
- a mis-measured timer;
- a song under dialogue.

Your job: bring ONE episode up to the current bar **without undoing anything the creator or earlier QA decided**. Read the episode's HANDOFF, `qa/` notes and `edit/history/` to learn what was decided and why, before changing anything.

Read first:
- `.claude/skills/edit-video-chat/SKILL.md` (all, esp. §Checkpoints, §2b incl. item 11, §2c, the last bullets on clean takes and filler captions);
- `LESSONS.md` (all; the Experiments table);
- the episode's `edit/HANDOFF.md`, `outline.md`, `research.md`, `qa/*`, `questions.json`;
- `sessions/QUEUE.md` (its row).

## Steps (checkpoint each one: `./venv/bin/python -m src.editor.checkpoint "<project>" note "UPG: …"`)
1. **Checkpoint baseline:** run the checkpoint status, then mark C0–C14 that are evidently done (one-line notes). Back up `edl.json` to `edit/history/edl-pre-upgrade.json`.
2. **Listen:** re-transcribe the current `edit/preview.mp4` talk segments with whisper large-v3, under `./venv/bin/python -m src.editor.asrlock -- …`; whisper loops on long music-only stretches, so do talk segments. Diff against the captions.
   - Check for: wrong words, pronouns (who is speaking), homophones, filler/interjection captions, leftover false starts or retakes, clipped words, music over speech, lyrics or recognisable songs in clip audio (Content ID).
   - Test-join and re-transcribe any cut you change.
3. **Watch:** dense frame sheets (≤2 s/frame in talky parts) of the whole preview.
   - Every note, card, tag and map: collisions, legibility, accuracy vs `research.md` (re-verify any shaky fact with a source), bilingual first mentions, no calendar dates, calm tone, dishes named.
4. **Raw restore:** compare every raw clip's contact sheet + proofread transcript (`edit/scan/`) with the cut. Restore unique moments and real commentary that were dropped (no runtime cap). Trim only dull or repeated material.
5. **Viewer-critic table** per 30 s. Any window ≤ 5/10 gets a concrete fix (a better cut, a breathing-room beat, a J-cut, a short sourced note).
5b. **Opening and ending per SKILL §2b-data (our retention data, 2026-10-08):**
   - Clear 0:08–0:30 of map, postcard, title B-roll, speed-ups and setup talk. Move them after the first scene (≈0:30–1:00), and keep them, don't delete.
   - No drives or speed-ups before 1:00.
   - The hook is live voice plus the moment.
   - A slice of the payoff lands in the first minute.
   - Any 三连/订阅 line goes in the last seconds or is dropped.
   - The outro is ≤ 10 s, with end-screen elements over the last shot or card.
   - Re-time the music sections and the end-screen space after moving beats, and check the route-map tag pill still fits.
   - Log the before/after times in HANDOFF.
6. **One improvement technique** that makes this episode better, if a weak spot calls for it: from the Experiments table, or new. Not decoration for its own sake; log it in HANDOFF.
7. **Shorts:** in HANDOFF, list TWO open-loop Shorts plus a backup, with clip times, per SKILL §2b item 11:
   - setup and tension, stopping before the payoff (which is really in the long video);
   - one is a moment, the other a question;
   - series and episode named on screen.
8. **Re-render** `--preview`, re-verify the changed spots, check `render_status.json` audio (|I+14| ≤ 0.5, TP ≤ −1.5).
9. **Wrap up:**
   - Update HANDOFF: status line, length, structure times, a QA section with the score table, and a "what changed in the upgrade pass" list.
   - Write `edit/qa/upgrade.md`.
   - Mark the checkpoints.
   - Keep `edit/preview.mp4`; delete `edit/previews/` and `/tmp/yt-editor/<project>`.

## Rules
- **Don't touch:**
  - any `01 - Unedited`;
  - other episodes;
  - the claude-in-chrome browser.
- **No git commits, no final render, no upload.** Repo code changes only if generic and tested (`scripts/test_*.py`); list them in your report.
- **The creator's open questions in `questions.json`:** leave them unless the footage answers them; then answer in the file and say so.
- **Thumbnails:** don't redo them. If one is clearly wrong after your changes, say so in the report.
- **Usage limits:**
  - **If you stop for a limit, the next agent resumes from your checkpoint notes.** Write them as you go: done / in flight (job + output path) / next action.
  - **Memory pressure:** if `sessions/sysmon.log` shows memory pressure, wait before rendering.
- **Report back** in English: what you found, what you changed, the new length, the Shorts picks, anything for the creator.
- **If a permission check (the auto-mode classifier) refuses an action** (it blocked 109's EDL reorder on 10/8): do NOT retry it or work around it.
  - Record the planned change and the EDL backup path in HANDOFF, plus a checkpoint note.
  - Finish everything else, then report it. The creator approves it later.
- **Known catches from the 10/8 independent QAs:** a wrong animal name (无尾蝠 → 游离尾蝠), an English line credited to the wrong speaker, a hook line credited to the wrong person (check by pitch), and background-song lyrics still audible under speech. Check for all four.
