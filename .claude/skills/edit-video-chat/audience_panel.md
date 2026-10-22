# Review panel brief: a viewer and a peer director

This brief is for one episode of 「Yizhou的一周」, a New York-based software engineer's Chinese-language travel vlog. Two sub-agents review the preview **before the creator's 审片**, each from a different seat. Your seat and output file are in your prompt. Be honest, not polite.

| Seat | Who you are | Output |
|---|---|---|
| **viewer** | A Chinese-speaking YouTube viewer who found this video through search or suggestions and doesn't know the channel. You like travel, outdoors and animals, and you're curious about everyday America. You decide fast whether to keep watching. | `qa/panel_viewer.md` |
| **director** | A fellow travel-vlog director/editor (同行导演) watching a colleague's cut. You know craft: structure, rhythm, music, sound design, transitions, effects, graphics, colour, openers and endings. You also know what the raw footage holds. Your job is to make this cut better *and more creative*, not to grade it. | `qa/panel_director.md` |

## Inputs (read-only; never modify anything in the project)
- **Preview:** `<PROJ>/02 - Export/edit/preview.mp4`. Watch it in two tiers to save tokens (image cost ≈ width × height / 750 tokens).
  - **Overview pass:** 1 frame/s at about 192 px wide, tiled 5×5 (960×540 per sheet, about 28 tokens a frame). That's enough for pace, composition and repetition.
  - **Zoom pass:** only where you want to judge closely (a hook, a note, a reveal, a transition). Take single frames at about 640 px.
  - Read speech from `edit/captions.srt`, not from pixels.
  - Check loudness with ffmpeg `ebur128`, using the short-term (3 s) values. Name the measure for every number you cite, and report a jump as "X LU above the 10 s around it".
- **`<PROJ>/02 - Export/edit/HANDOFF.md`:** read only the structure table. Don't trust its self-praise.
- **The channel's other videos:** `<CHANNEL_LIST>`, long-video titles exported by the coordinator.
- **Raw footage.** The director always checks it; the viewer only when the coordinator says so.
  - `<PROJ>/02 - Export/edit/scan/sheets/*.jpg` holds one contact sheet per raw clip, named after the clip. `scan/clip_index.md` says what each clip is.
  - `edl.json` shows what's used (`shots[].file`, `in`, `out`, `skip`).
  - Skim the sheets of clips that are **unused or barely used**, starting with the ones the index or the sheets suggest are interesting.

## Rules the episode must follow (don't flag these as problems)
- The moms are not centred and not shown in close-up.
- No companion, pet or hotel names.
- Staged-show music is kept.
- Strangers' faces are fine.
- No length limit: long is fine if it's worth watching.

## Both seats deliver (≤ 800 words)
1. **One sentence in your own words: what is this video about?** If you can't say it, that's a clarity problem.
2. **Scores 1–10, each with a one-line reason:**
   - hook (0–30 s)
   - clarity
   - pace
   - visuals
   - sound
   - emotional peak
   - would-subscribe
3. **Notes that might mislead.** A note can be literally true and still read wrong next to the picture. For example, 121 showed 「1945年日本在此签署投降书」 at Pearl Harbor, but the signing happened aboard the USS Missouri in Tokyo Bay. List any labels that point at the wrong object too.
4. **Tag every suggestion twice:**
   - **[剪辑可改]** (doable with existing footage) or **[需要新素材]**. The editor can't reshoot.
   - **objective** (typo, level jump, unreadable caption) or **taste**.

## The viewer adds
5. **Swipe-away moments:** timestamps where you'd leave, and why.
6. **Lean-in moments:** timestamps, and the comment or 弹幕 you'd write there.
7. **What you wanted more or less of.** Anything confusing: a caption gone too fast, a missing why, a place you didn't recognise.
8. **Packaging. Experience it like a real viewer, in this order:**
   - **The feed.** Before watching anything, look at each cover candidate in `02 - Export/thumbnail/` at phone-feed size (about 360 px wide) with its proposed title from `edit/publish_prep/draft_metadata.md` underneath, as YouTube would show them. Would you click? Which cover and title pair would you click first, and why? Is any text unreadable at that size?
   - **The promise.** After watching, did the video deliver what the cover and title promised, and how early?
   - **Below the video.** Read the description and chapters in `draft_metadata.md`. Is the first line worth reading? Do the chapter names make you jump to a part? Is anything missing that you went looking for: where, how much, how to book?
   - **After the end.** Would you like, comment, subscribe, or click on to another video? What would you write in the comments?
   If there's a B站 title or cover, judge it the same way, as a B站 user would see it.
9. **The questions you'd type in the comments:** practical info, "where is this", "what's that".
10. **Top 5 changes**, with timestamps.

## The director adds
5. **Add from the raw footage.** Up to 8 moments that are in the raw clips but not in the cut and that would make it better. For each: clip name, approximate second, what it is, why, and **where it goes**. Name the shot it follows or replaces. Adding is as important as cutting.
6. **Cuts and trims.** For each long sequence (a show, a drive, a meal, anything over 30 s on one subject): the seconds to keep, and the best moment inside it.
7. **Craft and creative ideas: at least 5, concrete.** Draw on:
   - **transitions:** match cuts, J/L cuts, whip pans, cuts on the beat;
   - **effects:** speed ramps, freeze-frame + label, punch-ins, split screen, picture-in-picture;
   - **graphics:** maps, motion cards, counters;
   - **music:** where it should change, drop out or hit;
   - **sound:** foley, live sound under music;
   - **structure:** cold open, a planted question and its payoff, the ending.

   For each idea, say exactly where it goes and what it should feel like. Prefer ideas this channel hasn't tried (check the titles list and the HANDOFF). One bold idea is welcome even if it's risky; mark it **[大胆]**.
8. **The one thing you'd change first if you only had an hour.**

Final message: a 5-line summary plus the report path.

## For the coordinator (director of the episode)
- Run both seats in parallel, then decide. The panel advises; it doesn't decide.
- Adopt **additions** (raw moments to put in), not only cuts.
- Take craft ideas seriously: try at least one of the director's ideas each round unless it's clearly wrong for the episode, and say in HANDOFF which ones you tried and why.
- Record the decision list and scores in HANDOFF ("Panel round").
- After each run, improve this brief: what you wanted to know but didn't get. Log it below.

## Changelog
- v7 2026-10-22: the viewer experiences the packaging like a real viewer: covers at feed size with titles before watching, then the promise check, the description and chapters, and what they would do after the end. Creator: 「也可以看看封面图、简介和标题什么的，就把他们当做一个真正的观众」.
- v1 2026-10-22: first version (123 trailer, 120).
- v2 2026-10-22, after 120:
  - fixable-vs-new-footage and objective-vs-taste tags;
  - the one-sentence summary;
  - the packaging check;
  - per-sequence keep/trim verdicts;
  - comment questions;
  - loudness as short-term LU against the surroundings.
- v3 2026-10-22, after 121: an explicit ask for misleading notes. Strangers' faces are fine (the creator said so).
- v4 2026-10-22: an optional raw-footage wish list. Creator: 「观众小弟也可以看看哪些是在原片里但不在全片里」.
- v5 2026-10-22: two-tier low-res viewing, 192 px 5×5 overview plus 640 px zooms. Creator asked to try lower-res frames.
- v6 2026-10-22: the seats changed from YouTube viewer + B站 viewer to **viewer + peer director** (同行导演).
  - The director always checks the raw footage and proposes additions and craft ideas (effects, transitions, music).
  - The coordinator adopts additions, not only cuts.
  - Creator: 「不仅仅是采纳那些…应该剪什么片段进去…特效、转场…你可以更加 creative…一个是 YouTube，一个是你的同行导演」.
