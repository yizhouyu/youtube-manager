"""`noautorotate`: a clip whose display matrix says rotate 90 but whose stored frame is upright renders upright.
Builds a synthetic 320x180 clip tagged rotate=90, renders it as a shot and as B-roll with and without the
option, and checks which way the left half's colour ends up. Run: ./venv/bin/python scripts/test_noautorotate.py"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image  # noqa: E402
from src.editor import render  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "01 - Unedited")
    os.makedirs(src)
    plain = os.path.join(td, "plain.mp4")
    # left half red, right half blue (stored upright)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=160x180:d=2:r=30", "-f", "lavfi",
                    "-i", "color=blue:s=160x180:d=2:r=30", "-filter_complex", "hstack", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", plain], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation", "90", "-i", plain, "-c", "copy",
                    os.path.join(src, "ROT.MP4")], check=True)
    preset = {"w": 320, "h": 180, "vb": "2M"}

    def left_is_red(edl, shot):
        cache = tempfile.mkdtemp(dir=td)
        v = render.render_segment_video(edl, shot, "30", preset, cache, clean=True)
        png = os.path.join(cache, "f.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", v, "-frames:v", "1", png], check=True)
        im = Image.open(png).convert("RGB")
        red = lambda xy: im.getpixel(xy)[0] > im.getpixel(xy)[2]  # noqa: E731
        return red((40, 20)) and red((40, 160)) and not red((280, 20)) and not red((280, 160))

    base = {"project": td, "source_dir": "01 - Unedited", "grades": {}}
    shot = {"id": "s1", "clip": "ROT", "in": 0.0, "out": 1.0}
    assert not left_is_red(base, shot), "control: the display matrix rotates the picture by default"
    assert left_is_red({**base, "noautorotate": ["ROT"]}, shot), "noautorotate keeps the stored frame"
    # B-roll over a black card-less shot of the same clip: the overlay must also be decoded unrotated
    broll = {"id": "s2", "clip": "ROT", "in": 0.0, "out": 1.0, "broll": [{"clip": "ROT", "in": 0.0, "at": 0.0, "dur": 1.0}]}
    assert left_is_red({**base, "noautorotate": ["ROT"]}, broll), "B-roll honours noautorotate"
print("ok")
