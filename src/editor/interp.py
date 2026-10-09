"""Smooth slow motion with RIFE frame interpolation, baked into a card mp4 the EDL can play.

    ./venv/bin/python -m src.editor.interp "<project>" <clip> <in> <out> [--slow 0.5|0.25] [--grade <name>]
                                         [--height 2160] [--model rife-v4.6] [--force]

Plain `speed: 0.5` on a 30 fps action-cam clip just repeats frames (15 distinct frames a second):
the ep 83 bear pass looked steppy. This tool synthesizes the in-between frames with RIFE
(rife-ncnn-vulkan, Metal via MoltenVK), so 0.5x / 0.25x keep the full frame rate.
Benchmark 2026-10-08 (sessions/research/2026-10-08/tools.md): held-out frames on the ostrich clip,
RIFE SSIM 0.967 vs ffmpeg minterpolate 0.951, frame blend 0.922, plain repeat 0.902.
Known weak spot: thin, fast occluders (a window edge sweeping through the frame) can vanish or
ghost; check the result frame by frame before using it.

Output: <edit>/interp/<clip>_<in>-<out>_x<factor>.mp4 (silent, graded, already slowed, source fps) and
a ready-to-paste EDL shot that plays it as a `card.image` (the renderer needs no change):
    {"id": "...", "clip": "", "in": 0, "out": <dur>, "card": {"image": "interp/....mp4"}, "audio": "mute"}
Put the natural sound back with a `broll`-free neighbouring shot or let the music carry it.

Setup (once): download the macOS build from https://github.com/nihui/rife-ncnn-vulkan/releases
(rife-ncnn-vulkan-20221029-macos.zip) and unzip it into <repo>/.tools/rife/, or set RIFE_BIN.
Speed on an M5 under heavy load: ~10 output frames/s at 1080p, ~6 s per new frame at 4K.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import tempfile

from . import edl as E

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rife_bin():
    if os.environ.get("RIFE_BIN"):
        return os.environ["RIFE_BIN"]
    hits = sorted(glob.glob(os.path.join(REPO, ".tools", "rife", "*", "rife-ncnn-vulkan")))
    return hits[-1] if hits else None


def frames_out(n_in, factor):
    """RIFE's -n N*f ends on (f-1) copies of the last frame; we keep only the real span."""
    return (n_in - 1) * factor + 1


def rife_cmd(binary, src_dir, dst_dir, n_in, factor, model="rife-v4.6", uhd=False):
    model_dir = model if os.path.isabs(model) else os.path.join(os.path.dirname(binary), model)
    cmd = [binary, "-i", src_dir, "-o", dst_dir, "-m", model_dir, "-n", str(n_in * factor), "-f", "%08d.png"]
    return cmd + (["-u"] if uhd else [])


def src_fps(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout
    return parse_rate(r)


def parse_rate(ffprobe_out):
    """First non-empty rate line (GoPro files print it more than once)."""
    lines = [x.strip().strip(",") for x in ffprobe_out.splitlines() if x.strip().strip(",")]
    return lines[0] if lines else "30000/1001"


def interpolate(src, t_in, t_out, factor, out, height=2160, grade="", in_args=(), model="rife-v4.6",
                binary=None, work=None):
    """Slow [t_in, t_out] of `src` down by `factor` (2 or 4) with RIFE; write a silent mp4 at the
    source frame rate to `out`. Returns (out, duration_s)."""
    binary = binary or rife_bin()
    if not binary or not os.path.exists(binary):
        raise SystemExit("rife-ncnn-vulkan not found: see the setup note in src/editor/interp.py (or set RIFE_BIN)")
    fps = src_fps(src)
    work = work or tempfile.mkdtemp(prefix="interp_")
    a, b = os.path.join(work, "in"), os.path.join(work, "out")
    os.makedirs(a, exist_ok=True)
    os.makedirs(b, exist_ok=True)
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *in_args, "-ss", f"{t_in:.3f}", "-t", f"{t_out - t_in:.3f}",
                        "-i", src, "-vf", f"scale=-2:{height}:flags=lanczos", "-fps_mode", "passthrough",
                        os.path.join(a, "%08d.png")], check=True)
        n = len(os.listdir(a))
        if n < 2:
            raise SystemExit(f"only {n} frame(s) in {t_in}-{t_out}")
        subprocess.run(rife_cmd(binary, a, b, n, factor, model, uhd=height >= 2160), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        keep = frames_out(n, factor)
        vf = ",".join(x for x in [grade, "format=yuv420p"] if x)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        tmp = out + ".part.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", fps, "-i", os.path.join(b, "%08d.png"),
                        "-frames:v", str(keep), "-vf", vf, "-c:v", "libx264", "-crf", "12", "-preset", "medium",
                        "-an", tmp], check=True)
        os.replace(tmp, out)
        num, den = (fps.split("/") + ["1"])[:2]
        return out, keep * float(den) / float(num)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("project")
    ap.add_argument("clip")
    ap.add_argument("t_in", type=float)
    ap.add_argument("t_out", type=float)
    ap.add_argument("--slow", type=float, default=0.5, choices=[0.5, 0.25], help="playback speed (0.5 = 2x frames)")
    ap.add_argument("--grade", default="default", help="EDL grade name baked into the card ('' = none)")
    ap.add_argument("--height", type=int, default=2160, help="1080 for a quick draft, 2160 for the 4K master")
    ap.add_argument("--model", default="rife-v4.6")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    edl = E.load(a.project)
    factor = round(1 / a.slow)
    rel = os.path.join("interp", f"{a.clip}_{a.t_in:g}-{a.t_out:g}_x{factor}.mp4")
    out = os.path.join(E.edit_dir(a.project), rel)
    if os.path.exists(out) and not a.force:
        print(f"exists: {out} (use --force to rebuild)")
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                           capture_output=True, text=True)
        dur = float(r.stdout.strip() or 0)
    else:
        grade = edl.get("grades", {}).get(a.grade, "") if a.grade else ""
        _, dur = interpolate(E.clip_path(edl, a.clip), a.t_in, a.t_out, factor, out, a.height, grade,
                             E.input_args(edl, a.clip), a.model)
        print(f"wrote {out} ({dur:.2f} s)")
    shot = {"id": f"slow_{a.clip}", "clip": "", "in": 0, "out": round(dur, 3), "card": {"image": rel},
            "audio": "mute", "note": "慢动作"}
    print(json.dumps(shot, ensure_ascii=False))


if __name__ == "__main__":
    main()
