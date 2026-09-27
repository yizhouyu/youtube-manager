# edit/ — this video's edit (everything project-specific lives here)

| Path | What | Who writes it |
|---|---|---|
| `edl.json` | The edit: shots, trims, subtitles, B-roll, zoom, music sections (schema: `src/editor/edl.py`) | agent + review page |
| `history/` | Automatic backups of `edl.json` before each save / QA round | review page, reviewer |
| `glossary.json` | ASR fixes `{"heard": "correct"}`; `""` drops a line that was never said | agent (from creator corrections) |
| `asr_context.txt` | Proper nouns fed to the ASR model | agent |
| `scan/` | Raw-footage analysis: `srt/` (ASR), `srt_clean/` (proofread), `sheets/` (contact sheets), `meta.json` | `src.editor.transcribe`, `captions_clean`, `scan` |
| `scripts/` | One-off scripts for THIS video (e.g. the first-cut EDL builder) | agent |
| `music/`, `sfx/` | Tracks + `LICENSES.md` (YouTube Audio Library, no attribution) | agent |
| `preview.mp4`, `captions.srt`, `render_status.json` | Renderer outputs | `src.editor.render` |

The finished master goes one level up: `02 - Export/<project folder name>.mov`, next to `thumbnail/`.
