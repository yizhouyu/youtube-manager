"""RIFE slow motion (src/editor/interp.py): frame count, duration, a true in-between frame, and that the
baked mp4 plays as a card shot. Skips (exit 0) when the rife-ncnn-vulkan binary isn't installed.
Run: ./venv/bin/python scripts/test_interp.py"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image  # noqa: E402
from src.editor import interp, render  # noqa: E402

assert interp.frames_out(10, 2) == 19 and interp.frames_out(10, 4) == 37
assert interp.parse_rate("30000/1001\n\n30000/1001\n") == "30000/1001"  # GoPro: printed twice
assert interp.parse_rate("") == "30000/1001"
cmd = interp.rife_cmd("/x/rife-ncnn-vulkan", "a", "b", 10, 4, uhd=True)
assert cmd[cmd.index("-n") + 1] == "40" and cmd[-1] == "-u" and cmd[cmd.index("-m") + 1] == "/x/rife-v4.6"

if not interp.rife_bin():
    print("skip: rife-ncnn-vulkan not installed (see src/editor/interp.py)")
    sys.exit(0)


def box_x(png):
    """x centre of the white box on black."""
    im = Image.open(png).convert("L")
    xs = [x for x in range(im.width) for y in range(0, im.height, 4) if im.getpixel((x, y)) > 128]
    return sum(xs) / len(xs)


with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "src.mp4")
    # a 40x40 white box moving 8 px per frame at 30 fps, 1 s
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=320x180:r=30:d=1",
                    "-f", "lavfi", "-i", "color=white:s=40x40:r=30:d=1",
                    "-filter_complex", "[0][1]overlay=x='20+8*n':y=70", "-c:v", "libx264", "-crf", "1",
                    "-pix_fmt", "yuv420p", src], check=True)
    out = os.path.join(td, "slow.mp4")
    _, dur = interp.interpolate(src, 0.0, 1.0, 2, out, height=180, work=os.path.join(td, "w"))
    n = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames", "-of", "csv=p=0", out], capture_output=True, text=True).stdout)
    assert n == interp.frames_out(30, 2) == 59, n
    assert abs(dur - 59 / 30) < 0.02, dur
    # frames 10, 11, 12 of the output: 10 and 12 are real (box moved 8 px), 11 is synthesized half-way
    xs = []
    for k in (10, 11, 12):
        png = os.path.join(td, f"f{k}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", out, "-vf", f"select=eq(n\\,{k})", "-frames:v", "1",
                        png], check=True)
        xs.append(box_x(png))
    assert abs(xs[2] - xs[0] - 8) < 1.5, xs
    assert abs(xs[1] - (xs[0] + xs[2]) / 2) < 1.5, f"in-between frame not half-way: {xs}"
    # the baked mp4 renders as a card.image shot
    os.makedirs(os.path.join(td, "02 - Export", "edit", "interp"), exist_ok=True)
    os.replace(out, os.path.join(td, "02 - Export", "edit", "interp", "slow.mp4"))
    v = os.path.join(td, "card.mp4")
    shot = {"id": "s1", "clip": "", "in": 0, "out": round(dur, 3), "card": {"image": "interp/slow.mp4"}}
    render._render_card({"project": td}, shot, "30000/1001", {"w": 320, "h": 180, "vb": "1M"}, 59, dur, td, v)
    assert os.path.getsize(v) > 0
print("ok")
