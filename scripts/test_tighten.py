"""Unit test for tighten.merge_skips (no audio needed): hand-made skips survive, autos clamp to captions."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.editor.tighten import merge_skips  # noqa: E402

shot = {"in": 0, "out": 20, "subs": [{"t0": 2.0, "t1": 5.0, "text": "a"}, {"t0": 9.0, "t1": 12.0, "text": "b"}],
        "skip": [[6.0, 7.5]]}                       # a hand-made retake cut, no skip_auto yet
sk, auto = merge_skips(shot, [[5.2, 6.4], [7.8, 9.3], [12.5, 13.5]])
assert [6.0, 7.5] in sk, sk                          # manual kept
assert [5.2, 6.4] not in sk                          # auto overlapping a manual span dropped
assert [7.8, 8.92] in sk, sk                         # auto that would eat caption b's first word is clamped
assert [12.5, 13.5] in sk and auto == [[7.8, 8.92], [12.5, 13.5]]
# second run: previous autos are recognised and replaced, the manual span stays
shot["skip"], shot["skip_auto"] = sk, auto
sk2, auto2 = merge_skips(shot, [[14.0, 15.0]])
assert sk2 == [[6.0, 7.5], [14.0, 15.0]] and auto2 == [[14.0, 15.0]], sk2
# --replace drops manual spans
assert merge_skips(shot, [[14.0, 15.0]], replace=True)[0] == [[14.0, 15.0]]
print("ok")
