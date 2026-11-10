"""make_short segment "denoise": same clean-up filters as the film's shot (render._shot_filters).
Run: ./venv/bin/python scripts/test_short_denoise.py"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import make_short as M  # noqa: E402
from src.editor.render import _shot_filters  # noqa: E402

assert M.denoise_filters(None) == [] and M.denoise_filters(False) == []
for mode in (True, "wind"):
    for audio in ("voice", "ambient"):
        got = M.denoise_filters(mode, audio)
        assert got == _shot_filters({}, {"denoise": mode, "audio": audio})[2:], (mode, audio, got)
assert M.denoise_filters("wind", "voice")[0].startswith("highpass=f=200")
assert M.denoise_filters(True, "ambient") == []   # plain denoise only touches voice shots, as in the film
print("ok")
