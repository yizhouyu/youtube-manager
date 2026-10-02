"""Test the EDL `voiceover` layer (src/editor/render.py): placement across a shot boundary, the
first-enabled-shot fallback, mixing into the dialogue track, and music ducking under it.

    ./venv/bin/python scripts/test_voiceover.py
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import render as R  # noqa: E402
from src.editor.lint import check  # noqa: E402

SR = 48000


def tone(path, dur, f=440.0):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={f}:d={dur}:r={SR}", "-ac", "2", path],
                   check=True)


def rms(path, t0, t1):
    """RMS in 16-bit sample units (the dialogue track is float since the R11 assembler)."""
    a = R._read_f32(path).astype(float) * 32768
    seg = a[int(t0 * SR):int(t1 * SR)]
    return float(np.sqrt((seg ** 2).mean())) if len(seg) else 0.0


def main():
    with tempfile.TemporaryDirectory() as td:
        proj = os.path.join(td, "VO test")
        edit = os.path.join(proj, "02 - Export", "edit")
        os.makedirs(os.path.join(edit, "tts"))
        tone(os.path.join(edit, "tts", "line.wav"), 3.0)
        card = lambda i, d, on=True: {"id": i, "clip": "", "card": {"text": "x"}, "in": 0, "out": d, "enabled": on}  # noqa: E731
        edl = {"project": proj, "shots": [card("c1", 2.0), card("c2", 2.0, on=False), card("c3", 4.0)],
               "voiceover": [{"file": "tts/line.wav", "start": "c1", "at": 1.0, "gain": -6},
                             {"file": "tts/line.wav", "start": "c2", "at": 0.5}]}
        assert not check(edl)[0], check(edl)
        spans = R.voiceover_spans(edl)
        # c1 at 0 + 1.0 (runs over the c1|c3 cut at 2.0); c2 is cut -> falls through to c3 at 2.0 + 0.5
        assert [(round(t, 3), round(d, 2), e.get("gain")) for _p, t, d, e in spans] == [(1.0, 3.0, -6), (2.5, 3.0, None)], spans
        assert R._speech_windows(edl)[0][0] < 1.0 and R._speech_windows(edl)[-1][1] > 5.5  # music ducks under it
        # a TTS line placed as a shot sfx, captioned as a note (white subtitles = real speech only), ducks too;
        # the window is cut at the shot's end like the sfx itself
        sfx_edl = {"project": proj, "shots": [dict(card("c1", 2.0), subs=[{"t0": 0.5, "t1": 1.8, "text": "n", "kind": "note"}],
                                                   sfx=[{"file": "tts/line.wav", "at": 0.5}]), card("c3", 4.0)]}
        assert [[round(a, 2), round(b, 2)] for a, b in R._speech_windows(sfx_edl)] == [[0.15, 2.35]], R._speech_windows(sfx_edl)
        voice = os.path.join(td, "voice.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo", "-t", "6",
                        "-c:a", "pcm_s16le", voice], check=True)
        info = R.mix_voiceover(edl, voice, 6.0)
        assert info and all(x["auto"] for x in info["lines"]), info  # legacy `gain` no longer sets the level
        assert rms(voice, 0.0, 0.9) < 1, "silence before the line"
        assert rms(voice, 1.2, 2.4) > 1000, "first line audible, across the shot cut"
        assert rms(voice, 2.7, 3.9) > rms(voice, 1.2, 2.4) * 1.5, "two lines overlap there"
        bad = dict(edl, voiceover=[{"file": "tts/line.wav", "start": "nope"}])
        assert check(bad)[0], "lint must flag a missing start shot"
    print("voiceover tests passed")


if __name__ == "__main__":
    main()
