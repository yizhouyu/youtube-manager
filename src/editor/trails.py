"""Flight trails: every small dark flyer (bats, birds) against the sky leaves a fading line, baked into an mp4.

    ./venv/bin/python -m src.editor.trails "<project>" <clip> <in> <out> [--decay 0.975 | --decay 0.95:0.99]
                                         [--preroll 2.0] [--grade <name>] [--height 2160] [--force]

Made for 111's bats (「它们都是排队飞出来了」: the lanes become visible). Plain frame stacking
(`negate,lagfun,negate`) also smears everything the hand-held camera moves (trees, lamp posts), so
this tool only accumulates *flyers*: a black-hat filter picks small dark specks, a sky mask (bright,
smooth, after a wide blur) drops leaves and the bridge, and the trail buffer is shifted with the camera
each frame (phase correlation) so static things never streak. The current frame is then darkened
toward the flyers' own colour wherever the buffer is set.

--sky-min lowers the sky brightness floor for dusk skies; --thick dilates each flyer (4K: ~5) so the
lines still read at phone size. --decay is the per-frame fade (0.975 ≈ a 2-3 s tail at 30 fps); "a:b" ramps it linearly over the
clip, so lanes pile up toward the end. --preroll accumulates that many seconds before <in> so the
first frame already has trails (a Short's hook must never open on bare specks).

Output: <edit>/trails/<clip>_<in>-<out>.mp4 (silent, graded, real time, source fps), playable as a
segment clip in make_short specs or as a `card.image` shot in the EDL.
"""
import argparse
import os
import subprocess

import cv2
import numpy as np

from . import edl as E
from .interp import parse_rate


def _probe(src):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate", "-of", "csv=p=0", src],
                       capture_output=True, text=True, check=True).stdout
    line = next(x for x in r.splitlines() if x.strip())
    w, h, rate = line.strip().strip(",").split(",")[:3]
    return int(w), int(h), parse_rate(rate)


def flyer_map(gray, k, sky_min=120, thick=0):
    """0-1 map of small dark specks over sky (`gray` float32 0-255)."""
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, ker)
    small = cv2.resize(gray, None, fx=0.125, fy=0.125, interpolation=cv2.INTER_AREA)
    closed = cv2.morphologyEx(small, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mean = cv2.GaussianBlur(closed, (0, 0), 3)
    var = cv2.GaussianBlur((small - cv2.GaussianBlur(small, (0, 0), 2)) ** 2, (0, 0), 3)
    sky = ((mean > sky_min) & (var < 60)).astype(np.uint8)
    sky = cv2.erode(sky, np.ones((5, 5), np.uint8))
    sky = cv2.resize(cv2.GaussianBlur(sky.astype(np.float32), (0, 0), 1.5), gray.shape[::-1])
    fm = np.clip((bh - 10.0) / 25.0, 0, 1) * sky
    if thick:
        fm = cv2.dilate(fm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thick, thick)))
    return fm


def render(src, t_in, t_out, out, decay=(0.975, 0.975), preroll=2.0, grade="", height=2160, in_args=(),
           sky_min=120, thick=0):
    w0, h0, rate = _probe(src)
    num, den = (rate.split("/") + ["1"])[:2]
    fps = float(num) / float(den)
    h = height
    w = int(round(w0 * h / h0 / 2)) * 2
    start = max(0.0, t_in - preroll)
    n_pre = int(round((t_in - start) * fps))
    n = int(round((t_out - start) * fps))
    k = max(9, int(round(21 * h / 2160)) | 1)
    dec = ["ffmpeg", "-v", "error", *in_args, "-ss", f"{start:.3f}", "-i", src, "-frames:v", str(n),
           "-vf", f"scale={w}:{h}:flags=lanczos", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".part.mp4"
    vf = ",".join(x for x in [grade, "format=yuv420p"] if x)
    enc = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", rate,
           "-i", "-", "-vf", vf, "-c:v", "libx264", "-crf", "13", "-preset", "medium", "-an", tmp]
    pd = subprocess.Popen(["nice", "-n", "10", *dec], stdout=subprocess.PIPE)
    pe = subprocess.Popen(["nice", "-n", "10", *enc], stdin=subprocess.PIPE)
    buf = np.zeros((h, w), np.float32)
    ink = np.zeros(3, np.float32)        # running flyer colour (BGR)
    prev_small = None
    sc = 0.25
    i = written = 0
    try:
        while i < n:
            raw = pd.stdout.read(w * h * 3)
            if len(raw) < w * h * 3:
                break
            f = np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(np.float32)
            gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
            if prev_small is not None:
                (dx, dy), _ = cv2.phaseCorrelate(prev_small, small, cv2.createHanningWindow(small.shape[::-1], cv2.CV_32F))
                m = np.float32([[1, 0, dx / sc], [0, 1, dy / sc]])
                buf = cv2.warpAffine(buf, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
            prev_small = small
            fm = flyer_map(gray, k, sky_min, thick)
            if fm.max() > 0:
                sel = fm > 0.5
                if sel.sum() > 20:
                    ink = 0.9 * ink + 0.1 * f[sel].mean(axis=0) if ink.any() else f[sel].mean(axis=0)
            u = i / max(1, n - 1)
            d = decay[0] + (decay[1] - decay[0]) * u
            buf = np.maximum(buf * d, fm)
            if i >= n_pre:
                a = np.clip(buf * 1.1, 0, 0.95)[..., None]
                col = ink if ink.any() else np.float32([40, 38, 36])
                o = f * (1 - a) + col * a
                pe.stdin.write(np.clip(o, 0, 255).astype(np.uint8).tobytes())
                written += 1
            i += 1
    finally:
        pe.stdin.close()
        pe.wait()
        pd.stdout.close()
        pd.wait()
    if pe.returncode:
        raise SystemExit("encode failed")
    os.replace(tmp, out)
    return out, written / fps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("project")
    ap.add_argument("clip")
    ap.add_argument("t_in", type=float)
    ap.add_argument("t_out", type=float)
    ap.add_argument("--decay", default="0.975", help="per-frame fade, or a:b to ramp it over the clip")
    ap.add_argument("--preroll", type=float, default=2.0, help="seconds accumulated before <in>")
    ap.add_argument("--grade", default="default", help="EDL grade name ('' = none)")
    ap.add_argument("--height", type=int, default=2160)
    ap.add_argument("--sky-min", type=float, default=120, help="sky brightness floor (lower it at dusk)")
    ap.add_argument("--thick", type=int, default=0, help="dilate each flyer by this many px (thicker lines)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    edl = E.load(a.project)
    d = [float(x) for x in a.decay.split(":")]
    out = os.path.join(E.edit_dir(a.project), "trails", f"{a.clip}_{a.t_in:g}-{a.t_out:g}.mp4")
    if os.path.exists(out) and not a.force:
        print(f"exists: {out} (use --force to rebuild)")
        return
    grade = edl.get("grades", {}).get(a.grade, "") if a.grade else ""
    _, dur = render(E.clip_path(edl, a.clip), a.t_in, a.t_out, out, (d[0], d[-1]), a.preroll, grade, a.height,
                    E.input_args(edl, a.clip), a.sky_min, a.thick)
    print(f"wrote {out} ({dur:.2f} s)")


if __name__ == "__main__":
    main()
