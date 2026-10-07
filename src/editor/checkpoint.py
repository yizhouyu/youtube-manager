"""Per-episode checkpoints, so any agent can resume an edit after a reset or a context overflow (creator, 2026-10-07:
「每个重要的步骤做完以后就可以 checkpoint…以后如果有 agent 重新来看，又知道从哪儿开始了」).

    ./venv/bin/python -m src.editor.checkpoint "<project>"                      # status + the next step
    ./venv/bin/python -m src.editor.checkpoint "<project>" done C6 "note"        # mark a step done (with a note)
    ./venv/bin/python -m src.editor.checkpoint "<project>" note "free text"     # add a gotcha / hand-over line

State lives in edit/checkpoint.json; every call rewrites edit/CHECKPOINT.md (human-readable). A step counts as done when
it was marked done OR its evidence exists on disk (so old projects show their real progress). Marking is still wanted:
the note says what was decided and where to look. Resuming agent: run the status command FIRST, read the notes, then
continue at "Next" — never redo a step whose evidence exists.
"""
import argparse
import datetime
import glob
import json
import os

from . import edl as E

# id, title, evidence globs relative to edit/ (any match = evidence), resume hint
STEPS = [
    ("C0", "Brief + skills read, usage logged", [], "read the brief, SKILL.md, LESSONS.md; scripts/claude_usage.py --log '<NNN> start'"),
    ("C1", "Footage watched (all grids + transcripts)", ["scan/watched.txt"], "Read every scan/sheets/grid_*.jpg and scan/srt/*.srt"),
    ("C2", "Research with sources", ["research.md"], "research.md: verified facts + sources"),
    ("C3", "Beat sheet", ["outline.md"], "outline.md: hook/promise, arcs, new technique, end screen"),
    ("C4", "Assets: maps, cards, overlays", ["maps/*.mp4", "cards/*.mp4"], "routemap configs in maps/, cards via scripts/"),
    ("C5", "First-cut EDL", ["edl.json"], "edl.json (from scripts/build_first_cut.py; re-running it overwrites later edits)"),
    ("C6", "Music placed + vocal-checked", ["music/LICENSES.md"], "music entries in the EDL; LICENSES.md; INDEX 'Used in'"),
    ("C7", "Captions cross-checked + proofread", ["scan/.proofread"], "whisper large-v3 vs kept lines; captions_clean --mark-proofread"),
    ("C8", "Questions for the creator", ["questions.json"], "src.editor.questions add ... (facts only he knows)"),
    ("C9", "Preview rendered", ["preview.mp4"], "src.editor.render --preview; check render_status.json audio ok"),
    ("C10", "QA round 1 applied", ["qa/round1.md"], "reviewer: frames + re-transcribe + loudness; apply fixes; re-render"),
    ("C11", "QA round 2 applied (raw restore)", ["qa/round2.md"], "reviewer also watches raw footage and restores missed moments"),
    ("C12", "Thumbnails (3 options, both platforms)", ["../thumbnail/*_bilibili.jpg"], "publish skill step 3; editorial.html; THUMBNAILS.md"),
    ("C13", "HANDOFF.md written", ["HANDOFF.md"], "all template sections filled (status line no longer '<project>')"),
    ("C14", "Cleanup + usage logged", [], "delete edit/previews and /tmp/yt-editor/<project>; usage --log '<NNN> end'"),
]
IDS = [s[0] for s in STEPS]


def _paths(project):
    ed = E.edit_dir(project)
    return ed, os.path.join(ed, "checkpoint.json"), os.path.join(ed, "CHECKPOINT.md")


def load(project):
    _, js, _ = _paths(project)
    if os.path.exists(js):
        with open(js, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "notes": []}


def evidence(project, step_id):
    ed, _, _ = _paths(project)
    globs = next(s[2] for s in STEPS if s[0] == step_id)
    hits = [p for g in globs for p in glob.glob(os.path.join(ed, g))]
    if step_id == "C13":   # the template HANDOFF exists from the start; count it only once filled in
        hits = [p for p in hits if "<project>" not in open(p, encoding="utf-8").read()[:400]]
    return hits


def status(project, state=None):
    """[(id, title, done: bool, how: 'marked'|'evidence'|'', note, hint)] in step order."""
    st = state or load(project)
    out = []
    for sid, title, _, hint in STEPS:
        m = st["done"].get(sid)
        ev = evidence(project, sid)
        how = "marked" if m else ("evidence" if ev else "")
        out.append((sid, title, bool(how), how, (m or {}).get("note", ""), hint))
    return out


def next_step(project, state=None):
    return next((r for r in status(project, state) if not r[2]), None)


def write(project, state):
    ed, js, md = _paths(project)
    os.makedirs(ed, exist_ok=True)
    with open(js, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    rows = status(project, state)
    nx = next((r for r in rows if not r[2]), None)
    lines = [f"# Checkpoints — {os.path.basename(E.project_dir(project))}",
             "", "Resume: run `./venv/bin/python -m src.editor.checkpoint \"<project>\"` first, read the notes, continue at Next.",
             f"Last updated: {datetime.datetime.now():%Y-%m-%d %H:%M}", "",
             f"**Next:** {nx[0]} {nx[1]} — {nx[5]}" if nx else "**Next:** all steps done", "",
             "| Step | Done | Note |", "|---|---|---|"]
    for sid, title, done, how, note, _ in rows:
        when = state["done"].get(sid, {}).get("at", "")
        mark = f"✅ {when}" if how == "marked" else ("◐ evidence on disk" if how == "evidence" else "—")
        lines.append(f"| {sid} {title} | {mark} | {note} |")
    if state["notes"]:
        lines += ["", "## Notes / gotchas"] + [f"- {n['at']}: {n['text']}" for n in state["notes"]]
    with open(md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return md


def mark(project, step_id, note=""):
    if step_id not in IDS:
        raise SystemExit(f"unknown step {step_id}; one of {', '.join(IDS)}")
    st = load(project)
    st["done"][step_id] = {"at": f"{datetime.datetime.now():%Y-%m-%d %H:%M}", "note": note}
    return write(project, st)


def add_note(project, text):
    st = load(project)
    st["notes"].append({"at": f"{datetime.datetime.now():%Y-%m-%d %H:%M}", "text": text})
    return write(project, st)


def main(argv=None):
    ap = argparse.ArgumentParser(description="episode checkpoints")
    ap.add_argument("project")
    ap.add_argument("action", nargs="?", default="status", choices=["status", "done", "note"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args(argv)
    if a.action == "done":
        write_path = mark(a.project, a.args[0], " ".join(a.args[1:]))
    elif a.action == "note":
        write_path = add_note(a.project, " ".join(a.args))
    else:
        write_path = write(a.project, load(a.project))
    print(open(write_path, encoding="utf-8").read())


if __name__ == "__main__":
    main()
