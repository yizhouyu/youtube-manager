# YouTube Manager — workflow for any editing agent

This repository is the source of truth for editing a creator's travel videos. These instructions apply to Claude Code, Manus, and any other agent asked to edit a project here.

## Before touching a video project

1. Read this file, `README.md`, and `.claude/skills/edit-video-chat/SKILL.md` plus its `LESSONS.md`. If the task includes publishing, also read `.claude/skills/publish-video-chat/SKILL.md` and its lessons.
2. Read the project-specific `AGENTS.md` files, `02 - Export/edit/HANDOFF.md`, `outline.md`, `research.md`, `questions.json`, current EDL and any recent QA notes before deciding what to change.
3. Treat the creator's latest explicit direction as authoritative. A later correction supersedes an older note (e.g. “no original narration” is not automatically “no voiceover”; ask what editorial treatment is wanted only if still ambiguous).
4. State the creative premise and intended deliverable format before editing: full episode, short, micro-documentary, or multiple cuts. Do not force every trip into the same length or format.

## Editorial standards

- Keep the real trip as the evidence. Match places, facts, titles, narration and outside imagery to what is actually on screen; cite factual research and distinguish the creator's recollection from independently verified information.
- Use a clear, immediate opening: reveal the promised moment and state the episode's question/value within the first 8 seconds. Do not keep a 15–20 second montage by rote; only extend it when the specific story demonstrably earns it.
- Give each location/sequence an arc (where we are → useful context or expectation → lived experience → reaction/payoff), but preserve distinctive human moments and valuable information. Tighten repetition and dead air, not for an arbitrary runtime target.
- Informative voiceover should be factual, location-specific and aligned to relevant images—not generic mood prose. For observational edits, let natural sound and visuals lead. Test a chosen voice on one line before generating a full script.
- Treat new motion graphics, archival photos, data cards, AI-generated narration/music and generated visuals as authored assets: verify facts/licence, label illustrative material, credit sources, preserve files and settings, and never fabricate documentary evidence.
- QA is part of the edit: review the rendered images, listen/re-transcribe dialogue against captions, measure audio, compare the cut against the original footage, and leave a reviewable handoff with known limitations.

- **Exhaust every option before saying "can't".** Before reporting that a fact can't be verified or a task is blocked, try every reasonable route: a browser search, other engines, official sites, archives, local data, a subagent. Report what was tried. Persistence is the default.

## Data and version safety

- Never modify, rename or delete `01 - Unedited/` raw media.
- The project's `02 - Export/edit/edl.json` is the canonical source for its existing cut. Do not silently replace it when asked for a comparison or alternative direction.
- Render a distinct cut through `scripts/render_variant.py` with a **new, versioned `.mov` filename**. The tool should refuse overwrites, enforce a 3840×2160 master, and deliver its exact EDL, captions, manifest and version-scoped assets together.
- Make decisions in the EDL, not the rendered SRT or MOV. Re-open the delivered EDL and confirm every referenced media dependency is available before claiming the edit is reproducible.
- Put disposable previews, proxies and render staging under `/tmp`; preserve only the files needed to revise the project later.
- Do not publish, upload, or change account settings merely because a local edit was requested. Publishing is a separate task and follows its own approval/confirmation rules.

## Before handing work back

Report the editorial difference from the prior cut, the runtime and verified output resolution, what QA was actually performed (do not imply checks that were skipped), where the EDL/assets live, and any open questions. Keep the original and comparison version easy to distinguish.
