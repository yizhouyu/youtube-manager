# 审片.app

A small local Mac app for reviewing an episode: open it, click an episode, review. It replaces opening the
review pages in Chrome. For the human only: nothing in it uploads anything or calls an agent.

## Build / install

    app/build.sh            # -> app/build/审片.app (unsigned, local only)
    app/build.sh --install  # also copies it to ~/Applications/审片.app (keep it in the Dock)

Needs the Command Line Tools (`swiftc`, `sips`, `iconutil`) and the repo venv (Pillow, for the icon).
The app runs the Python code of `~/Desktop/youtube-manager` with its venv (`SHENPIAN_REPO=<repo>` at build or
launch time points it elsewhere, e.g. a worktree).

## How it works

- `main.swift` + `Theme.swift`: one window (native sidebar vibrancy, 52 pt toolbar with the traffic lights),
  a WKWebView, ⌘1–⌘5 in the 显示 menu, and the 「打开其他文件夹…」 folder picker. It starts
  `python -m src.editor.app_server` and stops it on quit.
- `src/editor/app_server.py`: the shell page (episode list + tabs) and everything behind it. Opening an episode
  starts its `footage_player` (and `review_server` when there is an `edl.json`) on free ports 9100–9399; the
  previous episode's servers are stopped (only ones the app started). Logs: `~/Library/Logs/审片/`.
- Look: option B of `DESIGN.md`; tokens in `src/editor/theme.py` (swap `TOKENS`/`DARK_TOKENS`/`FLAVOR` for A/C/D).

## Sidebar

Every `~/Desktop/<N> - <name>` with `02 - Export/edit/`, newest first, with one chip read from files:
已上传 (`publish_prep/youtube_ids.json` has `long`) > 已通过 (「审片通过」 in the app) > 有问题没答
(`questions.json`) > 待审片 (a preview exists). 「打开其他文件夹…」 opens any project folder (e.g. on the
external drive) **read-only**: its servers run with `--read-only` (every POST refused, no storyboards, no caption
proofreading) and pick buttons are hidden.

## Tabs (hidden when empty)

| Tab | Page |
|---|---|
| 封面 ⌘1 | `thumbnail/editorial.html` or `review.html`, plus a 「选这个」 strip from the newest `thumbnail/v*/covers.json` |
| 素材 ⌘2 | the raw-footage page (footage_player) |
| 成片 ⌘3 | the cut review page (review_server); a note says so when there is no `edl.json` |
| Shorts ⌘4 | new page: each `02 - Export/shorts/*.mp4` with its cover and hook/label from `edit/shorts/<name>.json`; same chat (notes carry `ctx.short`) |
| 标题 ⌘5 | newest `thumbnail/**/feed_sim*.html`, plus title candidates from `publish_prep/metadata_final.txt` (or `draft_metadata.md`) |

## On the video pages (also in a browser)

- 框选: drag a rectangle on the picture; it is saved with the next comment as `ctx.box = [x, y, w, h]` (0–1) and
  drawn again when the comment's time is clicked.
- Keys (existing ones unchanged): J / K / L back · pause · forward (L or J again: 1× → 2× → 4×), `,` `.` one
  frame, C comment at this moment (in fullscreen C keeps switching the chat layout).
- R (and a small button), in the app only: 成片 → the same moment in 素材 (unused parts of the clip are shown);
  素材 → the same moment in 成片, or 「这段没用上」.

## Picks (「选这个」 / 「审片通过」)

Each click appends one line to `sessions/APPROVALS.md` (e.g. `- 2026-11-10 · 124 cover: E3_nanjinglu (v4) —
app 点选「选这个」`) and an event `{type, choice, at}` to `edit/app_picks.json`; a cover pick also writes
`thumbnail/CHOSEN`. Clicking 「已选 · 撤销」 appends a 撤销 line (lines are never deleted) and restores CHOSEN.

Tests: `./venv/bin/python scripts/test_app.py`.
