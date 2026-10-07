"""`audio_src`: a shot can play an edit/ audio file (same source timeline) instead of the clip's own sound,
e.g. a voice stem with a car-stereo song separated out. Builds a synthetic clip whose sound is a 440 Hz tone
and a replacement wav that is 440 Hz for 1 s then 1000 Hz, renders shot audio with and without the option
(also with a skip), and checks the dominant frequency and that the replacement keeps the clip's timeline.
Run: ./venv/bin/python scripts/test_audio_src.py"""
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import edl as E  # noqa: E402
from src.editor import render  # noqa: E402


def dominant(x, sr=render.SR):
    x = x.mean(1) if x.ndim == 2 else x
    f = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.fft.rfftfreq(len(x), 1 / sr)[np.argmax(f)]


with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "01 - Unedited")
    edit = os.path.join(td, "02 - Export", "edit")
    os.makedirs(src)
    os.makedirs(os.path.join(edit, "stems"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=gray:s=160x90:d=3:r=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    os.path.join(src, "CLIP.MP4")], check=True)
    # replacement on the same timeline: 0-1 s 440 Hz, 1-3 s 1000 Hz
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=44100",
                    "-f", "lavfi", "-i", "sine=frequency=1000:duration=2:sample_rate=44100",
                    "-filter_complex", "[0][1]concat=n=2:v=0:a=1", os.path.join(edit, "stems", "CLIP_vocals.wav")],
                   check=True)
    edl = {"project": td, "source_dir": "01 - Unedited", "grades": {}}

    def body(shot):
        cache = tempfile.mkdtemp(dir=td)
        wav = render.render_segment_audio(edl, shot, "30", cache)
        x = render._read_f32(wav).reshape(-1, 2)
        return x[render._HS:len(x) - render._HS]

    base = {"id": "s1", "clip": "CLIP", "in": 1.5, "out": 2.5, "audio": "voice"}
    assert abs(dominant(body(base)) - 440) < 20, "control: the clip's own 440 Hz tone"
    alt = dict(base, audio_src="stems/CLIP_vocals.wav")
    assert E.audio_path(edl, alt).endswith(os.path.join("edit", "stems", "CLIP_vocals.wav"))
    assert abs(dominant(body(alt)) - 1000) < 20, "audio_src replaces the sound (1000 Hz after 1 s)"
    # same source timeline: a shot over 0.2-0.8 s hears the replacement's first second (440 Hz)
    early = dict(alt, id="s2", **{"in": 0.2, "out": 0.8})
    assert abs(dominant(body(early)) - 440) < 20, "audio_src is read on the clip's timeline"
    # skips still apply: 0.2-2.4 with 0.9-2.2 skipped keeps ~0.7 s of 440 + 0.2 s of 1000
    sk = dict(alt, id="s3", skip=[[0.9, 2.2]], skip_on=True, **{"in": 0.2, "out": 2.4})
    y = body(sk)
    assert abs(len(y) / render.SR - 0.9) < 0.05, len(y) / render.SR
    assert abs(dominant(y[: int(0.5 * render.SR)]) - 440) < 20 and abs(dominant(y[-int(0.15 * render.SR):]) - 1000) < 30
    # a changed replacement file re-renders (cache key follows its mtime)
    cache = tempfile.mkdtemp(dir=td)
    p1 = render.render_segment_audio(edl, alt, "30", cache)
    os.utime(os.path.join(edit, "stems", "CLIP_vocals.wav"), (1, 1))
    p2 = render.render_segment_audio(edl, alt, "30", cache)
    assert p1 != p2, "cache must follow the audio_src file"
print("ok")
