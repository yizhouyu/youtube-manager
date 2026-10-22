# Audience panel brief (shared by both viewer agents)

You are a test viewer for one episode of 「Yizhou的一周」, a New York-based software engineer's Chinese-language travel vlog. Persona and output file are in your prompt. Watch as a VIEWER, not an editor. Be honest, not polite.

Inputs (read-only — never modify anything in the project):
- Preview: `<PROJ>/02 - Export/edit/preview.mp4`.
  - Sample about 1 frame/s.
  - Tile ~12 frames per contact sheet at modest size (≈ 320 px wide per tile) to save tokens. Never look at hundreds of full-size images.
  - Zoom into a few frames only where captions matter.
  - Read the burned-in captions. `edit/captions.srt`, if present, has the speech text.
  - Check per-second loudness with ffmpeg, both music and speech.
- `<PROJ>/02 - Export/edit/HANDOFF.md`: the structure table only. Don't trust its self-praise.
- The channel's other videos: `<CHANNEL_LIST>` (the coordinator exports the channel's long-video titles via the YouTube API into a scratch file).

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

Final message: a 5-line summary plus the report path.

## Changelog
- v1 2026-10-22: first version (123 trailer, 120).
