# Audience panel brief (shared by both viewer agents)

You are a test viewer for one episode of 「Yizhou的一周」, a New York-based software engineer's Chinese-language travel vlog. Persona and output file are in your prompt. Watch as a VIEWER, not an editor. Be honest, not polite.

Inputs (read-only — never modify anything in the project):
- Preview: `<PROJ>/02 - Export/edit/preview.mp4`. Watch it in two tiers to save tokens. Image cost ≈ width × height / 750 tokens.
  - **Overview pass:** 1 frame/s, about 192 px wide, tiled 5×5 (960×540 per sheet, about 28 tokens a frame). This is enough to judge pace, composition and repetition.
  - **Zoom pass:** only at moments you want to judge closely (a hook, a note, a reveal), take single frames at about 640 px.
  - Read speech from `edit/captions.srt`, not from pixels.
  - Check per-second loudness with ffmpeg (music and speech).
- `<PROJ>/02 - Export/edit/HANDOFF.md`: the structure table only. Don't trust its self-praise.
- The channel's other videos: `<CHANNEL_LIST>` (the coordinator exports the channel's long-video titles via the YouTube API into a scratch file).

Optional, when the coordinator says so: **raw footage.**
- `<PROJ>/02 - Export/edit/scan/sheets/*.jpg` holds one contact sheet per raw clip, named after the clip.
- `<PROJ>/02 - Export/edit/scan/clip_index.md` lists what each clip is.
- `edl.json` shows which clips and seconds are used (`shots[].file`, `in`, `out`, `skip`).
- Skim the sheets of clips that are **unused or barely used**. You don't need to look at every sheet; prioritise clips the index or sheets suggest are interesting.
- Report up to 8 moments that are in the raw footage but not in the cut and that you'd want in it: clip name, approximate second, what it is, why, and where it would go. This is a viewer's wish list. The director decides.

Rules the episode must follow (don't flag these as problems):
- The moms are not centred or shown in close-up.
- No companion, pet or hotel names.
- Staged-show music is kept.

Deliver your report (≤ 700 words) to `<PROJ>/02 - Export/edit/qa/audience_<persona>.md`:
1. **Scores 1–10, each with a one-line reason:**
   - hook (0–30 s)
   - clarity (where / who / what)
   - pace
   - visuals
   - sound
   - emotional peak
   - would-subscribe / 关注
2. **Swipe-away moments:** timestamps where you'd leave or skip, and why.
3. **Lean-in moments:** timestamps where you leaned in. The B站 persona also writes the 弹幕 they'd send.
4. **What you wanted more of** (or less of), and anything confusing: a caption you couldn't read in time, a missing why, a place you didn't recognise.
5. **Top 5 concrete changes:** cut, trim, hold longer, reorder, add a note, music. Give timestamps.
   - Tag each change **[剪辑可改]** (doable with the footage that exists) or **[需要新素材]**. The editor can't reshoot, so concentrate on [剪辑可改].
   - Tag each issue **objective** (a typo, a level jump, an unreadable caption) or **taste**.
6. **In one sentence, in your own words: what is this video about?** If you can't say, that's a clarity problem.
7. **Packaging.** Read the proposed title(s) in `edit/publish_prep/draft_metadata.md` and look at the recommended cover in `02 - Export/thumbnail/`. Answer two questions:
   - Would you click?
   - Does the first 30 s pay off what the title and cover promise?
8. **Long sequences.** For each long sequence (a show, a drive, a meal, anything over 30 s on one subject), give a keep/trim verdict with the seconds you'd keep and the best moment inside it.
10. **Notes that might mislead.** A note can be literally true and still read wrong next to the picture. Example, 121: 「1945年日本在此签署投降书」 shown at Pearl Harbor, when the signing was on the USS Missouri in Tokyo Bay. List any such note, and any label pointing at the wrong object.
9. **The questions you'd type in the comments.** Practical info, "where is this", "what's that". The editor can answer them with notes.

Measurement rules: name the measure for every loudness number you cite. Use ffmpeg `ebur128` and its short-term (3 s) values. Report a jump as "X LU above the 10 s around it".

Final message: a 5-line summary plus the report path.

## Changelog
- v1 2026-10-22: first version (123 trailer, 120).
- v5 2026-10-22: two-tier viewing (192 px 5×5 overview ≈ 28 tok/frame vs 77 at 320 px 4×3; 640 px zooms only where needed); creator asked to try lower-res frames.
- v4 2026-10-22: optional raw-footage pass — what is in the raw clips but not in the cut that viewers would want (creator idea: 「观众小弟也可以看看哪些是在原片里但不在全片里」).
- v3 2026-10-22 (after 121): explicit ask for misleading notes / wrong-object labels (the 121 YouTube viewer caught one unprompted). Stranger faces are NOT an issue (creator: 「露脸的陌生人应该没问题」) — don't flag them.
- v2 2026-10-22 (after 120): added fixable-vs-new-footage and objective-vs-taste tags, one-sentence summary, packaging check (title/cover vs first 30 s), per-sequence keep/trim verdicts, comment questions, loudness measured as short-term LU vs surroundings (120 reports quoted "−9 LUFS" without saying which measure).
