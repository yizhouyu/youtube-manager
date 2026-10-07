"""src.editor.checkpoint: status from evidence + marks, next step, CHECKPOINT.md written.
Run: ./venv/bin/python scripts/test_checkpoint.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import checkpoint as C  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    proj = os.path.join(td, "99 - Test")
    ed = os.path.join(proj, "02 - Export", "edit")
    os.makedirs(ed)
    open(os.path.join(ed, "HANDOFF.md"), "w").write("# Handoff — <project>\n")      # template: not evidence
    assert C.next_step(proj)[0] == "C0"
    C.mark(proj, "C0", "brief read")
    assert C.next_step(proj)[0] == "C1"
    open(os.path.join(ed, "research.md"), "w").write("x")
    open(os.path.join(ed, "edl.json"), "w").write("{}")
    rows = {r[0]: r for r in C.status(proj)}
    assert rows["C2"][2] and rows["C2"][3] == "evidence" and rows["C5"][2]
    assert not rows["C13"][2], "the unfilled HANDOFF template is not evidence"
    assert C.next_step(proj)[0] == "C1", "evidence on later steps does not skip an earlier open one"
    C.mark(proj, "C1", "27 grids")
    C.add_note(proj, "machine is slow")
    md = open(os.path.join(ed, "CHECKPOINT.md"), encoding="utf-8").read()
    assert "**Next:** C3" in md and "27 grids" in md and "machine is slow" in md and "◐ evidence on disk" in md
    open(os.path.join(ed, "HANDOFF.md"), "w").write("# Handoff — 99 - Test\n")
    assert {r[0]: r for r in C.status(proj)}["C13"][2]
    try:
        C.mark(proj, "C99")
        raise AssertionError("unknown id accepted")
    except SystemExit:
        pass
print("ok")
