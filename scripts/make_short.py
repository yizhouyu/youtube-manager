#!/usr/bin/env python3
"""Render a vertical YouTube Short (1080x1920, 30 fps) from 16:9 source clips, driven by a JSON spec.

    ./venv/bin/python scripts/make_short.py short.json [--out out.mp4] [--check]

Spec (all times in seconds; segment times and keyframes are SOURCE-clip seconds):

{
  "project": "NN - Trip Name",          # optional: resolves clips to <project>/01 - Unedited/<clip>.MP4
  "output": "/abs/path/short.mp4",      # or --out
  "grades": {"default": "eq=contrast=1.07:saturation=1.2"},   # named ffmpeg color chains (optional)
  "segments": [
    {"clip": "GX015168",                # file stem in the source dir, or an absolute path
     "in": 8.0, "out": 18.0,
     "grade": "default",                # key into grades (optional)
     "audio": "ambient",                # voice (1.0) | ambient (0.35) | mute; "gain_db" adds on top
     "mode": "crop",                    # crop: 9:16 window that follows the subject
                                        # letterbox: whole 16:9 frame over a blurred fill
     "x": [[8.0, 0.26], [12.0, 0.30]],  # crop centre as 0-1 of the source width; a number = static.
                                        # Keyframes are smoothed (no jerky pans); clamped to the frame.
     "y": 0.5, "zoom": 1.0,             # crop: vertical centre and extra punch-in (1 = full height)
     "speed": 1.0,                      # >1 = timelapse (audio muted)
     "subs": [{"t0": 8.2, "t1": 11.0, "text": "……", "kind": "speech"}]}   # speech | note
  ],
  "captions": [{"t0": 0, "t1": null, "text": "阿拉斯加", "style": "headline"}],  # OUTPUT seconds;
                                        # t1 null = to the end; style headline | speech | note
  "music": {"file": "music/track.mp3", "in": 0, "volume": 0.30, "duck": 0.08},  # relative to
                                        # <project>/02 - Export/edit/ or absolute; ducked under speech subs
  "caption_bottom": 0.675,              # where speech/note blocks end (fraction of H); per-sub "y" overrides
  "loudness": {"I": -14, "TP": -1.5},
  "edge_fade": 0.15                     # audio fade at start/end; no video fade, so the Short loops
}

Captions are drawn with the editor's text style (src/editor/overlays.py fonts, stroke, note colour)
and kept inside the Shorts safe zone: clear of the top bar, of the right-hand action buttons and of
the bottom title/channel overlay. Speech captions must be what was actually said; "note" captions
(soft yellow) are the editor's labels for silent shots.

--check writes full-size frames plus a phone-size contact sheet (with the unsafe zones shaded) next
to the output, to look at before uploading.
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

from PIL import Image, ImageDraw  # noqa: E402

from src.editor import edl as E  # noqa: E402
from src.editor import overlays as O  # noqa: E402

W, H, FPS, SR = 1080, 1920, 30, 48000
AUDIO_GAIN = {"voice": 1.0, "ambient": 0.35, "mute": 0.0}
# Shorts safe zone on a 1080x1920 frame (YouTube overlays: top bar, right-hand buttons, bottom
# title / channel / description). Keep text inside it.
SAFE = {"top": 220, "bottom": 480, "right": 150, "left": 60}
CAPTION_BOTTOM = 0.675  # speech / note block ends here (fraction of H), well above the bottom overlay
HEADLINE_TOP = 0.125


def run(cmd, **kw):
    """Run ffmpeg/ffprobe at low priority (the machine is usually busy with other renders)."""
    r = subprocess.run(["nice", "-n", "10", *cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(f"{cmd[0]} failed:\n{r.stderr[-3000:]}")
    return r


def probe(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", path])
    j = json.loads(r.stdout)
    s = j["streams"][0]
    return s["width"], s["height"], float(j["format"]["duration"])


def has_audio(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", path])
    return bool(r.stdout.strip())


# ---------------------------------------------------------------- crop path

def smooth_track(keys, t_in, t_out, speed=1.0, step=0.2, sigma=0.35):
    """Keyframes [(src_t, x)] -> [(local_t, x)] sampled every `step` s, linearly interpolated and then
    Gaussian-smoothed so the virtual camera eases instead of snapping between keyframes."""
    if isinstance(keys, (int, float)):
        return [(0.0, float(keys))]
    keys = sorted((float(t), float(x)) for t, x in keys)

    def lin(t):
        if t <= keys[0][0]:
            return keys[0][1]
        for (a, xa), (b, xb) in zip(keys, keys[1:]):
            if t <= b:
                return xa + (xb - xa) * (t - a) / max(1e-6, b - a)
        return keys[-1][1]

    step = max(step, (t_out - t_in) / 50)  # ffmpeg rejects very long crop expressions (~100+ terms)
    n = max(2, int(math.ceil((t_out - t_in) / step)) + 1)
    ts = [t_in + (t_out - t_in) * i / (n - 1) for i in range(n)]
    raw = [lin(t) for t in ts]
    if len(keys) == 1:
        return [(0.0, raw[0])]
    rad = max(1, int(round(3 * sigma / step)))
    wts = [math.exp(-0.5 * (k * step / sigma) ** 2) for k in range(-rad, rad + 1)]
    out = []
    for i in range(n):
        acc = sw = 0.0
        for k, wk in zip(range(-rad, rad + 1), wts):
            j = min(n - 1, max(0, i + k))
            acc += raw[j] * wk
            sw += wk
        out.append(((ts[i] - t_in) / speed, acc / sw))
    return out


def piecewise_expr(points, lo, hi):
    """Flat (non-nested) ffmpeg expression for a piecewise-linear function of t, clamped to [lo, hi]."""
    pts = [(t, min(hi, max(lo, v))) for t, v in points]
    if len(pts) == 1:
        return f"{pts[0][1]:.1f}"
    terms = []
    for (a, va), (b, vb) in zip(pts, pts[1:]):
        slope = (vb - va) / max(1e-6, b - a)
        terms.append(f"gte(t,{a:.3f})*lt(t,{b:.3f})*({va:.1f}+(t-{a:.3f})*{slope:.3f})")
    terms.append(f"gte(t,{pts[-1][0]:.3f})*{pts[-1][1]:.1f}")
    terms.insert(0, f"lt(t,{pts[0][0]:.3f})*{pts[0][1]:.1f}")
    return "+".join(terms)


# ---------------------------------------------------------------- captions

def caption_png(text, style, cache, bottom=CAPTION_BOTTOM):
    """Full-frame RGBA caption in the editor's style, placed inside the Shorts safe zone.
    headline: heavy face at the top, shrunk to fit one line when it can; speech / note: a block whose
    last line ends at `bottom` (fraction of H) -- raise it when the subject sits low in the frame."""
    def render():
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        max_w = W - SAFE["left"] - SAFE["right"] - 20
        cx = (SAFE["left"] + W - SAFE["right"]) / 2   # centred in the safe zone, clear of the buttons
        if style == "headline":
            size, fill = 84, "white"
            f = O._font(O.TITLE_FONTS, size)
            while size > 58 and d.textlength(text, font=f) > max_w:
                size -= 2
                f = O._font(O.TITLE_FONTS, size)
        else:
            size = 76 if style == "speech" else 72
            f = O._font(O.SUB_FONTS, size)
            fill = O.NOTE_COLOR if style == "note" else "white"
        lines = O._wrap(d, text, f, max_w)
        lh = int(size * 1.28)
        y = int(H * HEADLINE_TOP) if style == "headline" else int(H * bottom) - lh * len(lines)
        y = max(SAFE["top"], y)
        for ln in lines:
            d.text((cx, y), ln, font=f, fill=fill, anchor="ma",
                   stroke_width=max(4, size // 6), stroke_fill=(0, 0, 0, 235))
            y += lh
        assert y <= H - SAFE["bottom"], f"caption runs into the bottom overlay: {text}"
        return im
    return O._cached(cache, f"short|{style}|{text}|{bottom}|{W}x{H}", render)


# ---------------------------------------------------------------- segments

def resolve_clip(spec, clip):
    if os.path.isabs(clip) or os.path.exists(clip):
        return clip
    proj = E.project_dir(spec["project"])
    for ext in (".MP4", ".mp4", ".MOV", ".mov"):
        p = os.path.join(proj, spec.get("source_dir", "01 - Unedited"), clip + ext)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(clip)


def render_segment(spec, seg, idx, work):
    path = resolve_clip(spec, seg["clip"])
    sw, sh, _ = probe(path)
    speed = max(0.25, float(seg.get("speed", 1.0) or 1.0))
    dur = seg["out"] - seg["in"]
    grade = spec.get("grades", {}).get(seg.get("grade", ""), "")
    vf = ["setpts=PTS-STARTPTS"]
    if seg.get("mode", "crop") == "crop":
        zoom = float(seg.get("zoom", 1.0))
        ch = int(round(sh / zoom / 2)) * 2
        cw = int(round(ch * W / H / 2)) * 2
        track = smooth_track(seg.get("x", 0.5), seg["in"], seg["out"], 1.0)
        xs = [(t, x * sw - cw / 2) for t, x in track]
        y = min(sh - ch, max(0, float(seg.get("y", 0.5)) * sh - ch / 2))
        vf.append(f"crop=w={cw}:h={ch}:x='{piecewise_expr(xs, 0, sw - cw)}':y={y:.0f}")
        if grade:
            vf.append(grade)
        vf.append(f"scale={W}:{H}:flags=lanczos")
        chain = f"[0:v]{','.join(vf)}"
    else:  # letterbox over a blurred, darkened fill of the same frame
        g = f",{grade}" if grade else ""
        chain = (f"[0:v]setpts=PTS-STARTPTS{g},split[a][b];"
                 f"[a]scale=-2:{H // 4},crop={W // 4}:{H // 4},boxblur=12:2,eq=brightness=-0.12,"
                 f"scale={W}:{H}[bg];[b]scale={W}:-2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    if speed != 1.0:
        chain += f",setpts=PTS/{speed}"
    chain += f",fps={FPS},setsar=1,format=yuv420p[v]"
    level = AUDIO_GAIN.get(seg.get("audio", "voice"), 1.0) if speed == 1.0 else 0.0
    out_dur = dur / speed
    if has_audio(path) and level > 0:
        achain = (f"[0:a]asetpts=PTS-STARTPTS,aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                  f"volume={level}*{10 ** (float(seg.get('gain_db', 0)) / 20):.4f},"
                  f"afade=t=in:d=0.012,afade=t=out:st={max(0, out_dur - 0.012):.3f}:d=0.012,"
                  f"apad,atrim=0:{out_dur:.3f}[a]")
    else:
        achain = f"anullsrc=r={SR}:cl=stereo,atrim=0:{out_dur:.3f}[a]"
    script = os.path.join(work, f"seg{idx}.txt")
    with open(script, "w") as f:
        f.write(chain + ";" + achain)
    vout, aout = os.path.join(work, f"seg{idx}.mp4"), os.path.join(work, f"seg{idx}.wav")
    # -reinit_filter 0: keep the graph if frame properties change mid-stream (hw -> sw decode fallback)
    tail = ["-reinit_filter", "0", "-ss", f"{seg['in']:.3f}", "-t", f"{dur:.3f}", "-i", path,
            "-filter_complex_script", script,
            "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
            "-frames:v", str(round(out_dur * FPS)), vout, "-map", "[a]", "-c:a", "pcm_s16le", aout]
    try:  # hardware HEVC decode is much faster; retry in software if it fails
        run(["ffmpeg", "-v", "error", "-y", *(["-hwaccel", "videotoolbox"] if sys.platform == "darwin" else []), *tail])
    except RuntimeError:
        run(["ffmpeg", "-v", "error", "-y", *tail])
    return vout, aout, round(out_dur * FPS) / FPS


# ---------------------------------------------------------------- build

def build(spec, out, check=False):
    work = tempfile.mkdtemp(prefix="short_", dir=spec.get("workdir") or None)
    cache = os.path.join(work, "overlays")
    try:
        segs, t, speech, caps = [], 0.0, [], []
        for i, seg in enumerate(spec["segments"]):
            v, a, d = render_segment(spec, seg, i, work)
            k = max(0.25, float(seg.get("speed", 1.0) or 1.0))
            for s in seg.get("subs", []):
                a0, a1 = max(s["t0"], seg["in"]), min(s["t1"], seg["out"])
                if a1 - a0 < 0.3:
                    continue
                o0, o1 = t + (a0 - seg["in"]) / k, t + (a1 - seg["in"]) / k
                kind = s.get("kind", "speech")
                caps.append({"t0": o0, "t1": o1, "text": s["text"], "style": kind, "y": s.get("y")})
                if kind == "speech":
                    speech.append((o0, o1))
            segs.append((v, a, d))
            t += d
        total = t
        for c in spec.get("captions", []):
            caps.append({"t0": c.get("t0", 0), "t1": c.get("t1") if c.get("t1") is not None else total,
                         "text": c["text"], "style": c.get("style", "headline"), "y": c.get("y")})

        # video: concat + caption overlays
        inputs, chain = [], []
        for v, _, _ in segs:
            inputs += ["-i", v]
        n = len(segs)
        chain.append("".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[c0]")
        cur = "c0"
        for j, c in enumerate(caps):
            png = caption_png(c["text"], c["style"], cache, float(c.get("y") or spec.get("caption_bottom", CAPTION_BOTTOM)))
            inputs += ["-i", png]
            chain.append(f"[{cur}][{n + j}:v]overlay=0:0:enable='between(t,{c['t0']:.3f},{c['t1']:.3f})'[c{j + 1}]")
            cur = f"c{j + 1}"
        chain.append(f"[{cur}]format=yuv420p[v]")
        vscript = os.path.join(work, "video.txt")
        with open(vscript, "w") as f:
            f.write(";".join(chain))
        video = os.path.join(work, "video.mp4")
        run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex_script", vscript, "-map", "[v]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
             "-g", str(FPS), "-movflags", "+faststart", video])

        # audio: concat source audio, music bed ducked under speech, loudnorm + limiter
        with open(os.path.join(work, "alist.txt"), "w") as f:
            f.writelines(f"file '{a}'\n" for _, a, _ in segs)
        voice = os.path.join(work, "voice.wav")
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", os.path.join(work, "alist.txt"),
             "-af", f"atrim=0:{total:.3f},apad,atrim=0:{total:.3f}", "-c:a", "pcm_s16le", voice])
        mix = os.path.join(work, "mix.wav")
        m = spec.get("music")
        fade = float(spec.get("edge_fade", 0.15))
        if m and m.get("file"):
            mf = m["file"] if os.path.isabs(m["file"]) else os.path.join(E.edit_dir(spec["project"]), m["file"])
            base, duck, r = float(m.get("volume", 0.30)), float(m.get("duck", 0.08)), 0.35
            terms = [f"clip(min((t-{a:.2f}+{r})/{r},({b:.2f}+{r}-t)/{r}),0,1)" for a, b in speech]
            sp = "min(1," + "+".join(terms) + ")" if terms else "0"
            ms = (f"[1:a]aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                  f"atrim=0:{total:.3f},asetpts=N/SR/TB,volume='{base}-({base - duck})*{sp}':eval=frame[m];"
                  f"[0:a][m]amix=inputs=2:normalize=0:duration=first,"
                  f"afade=t=in:d={fade},afade=t=out:st={max(0, total - fade):.3f}:d={fade}")
            ascript = os.path.join(work, "audio.txt")
            with open(ascript, "w") as f:
                f.write(ms)
            run(["ffmpeg", "-v", "error", "-y", "-i", voice, "-stream_loop", "-1", "-ss", f"{float(m.get('in', 0)):.3f}",
                 "-i", mf, "-filter_complex_script", ascript, "-t", f"{total:.3f}", "-c:a", "pcm_s24le", mix])
        else:
            run(["ffmpeg", "-v", "error", "-y", "-i", voice, "-af",
                 f"afade=t=in:d={fade},afade=t=out:st={max(0, total - fade):.3f}:d={fade}", "-c:a", "pcm_s24le", mix])
        from src.editor.render import _loudnorm
        L = spec.get("loudness", {})
        target = f"I={L.get('I', -14)}:TP={L.get('TP', -1.5)}:LRA=11"
        tmp = out + ".part.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-i", video, "-i", mix, "-filter_complex",
             f"[1:a]{_loudnorm(mix, target)},aresample=192000,"
             f"alimiter=limit=0.79:attack=5:release=50:level=false,aresample={SR},aformat=sample_fmts=s16[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", str(SR),
             "-t", f"{total:.3f}", "-movflags", "+faststart", tmp])
        os.replace(tmp, out)
        report = measure(out)
        report["captions"] = caps
        print(json.dumps(report, ensure_ascii=False, indent=1))
        if check:
            check_frames(out, report["duration"])
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def measure(path):
    w, h, dur = probe(path)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True)
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    I = TP = None
    for ln in tail.splitlines():
        ln = ln.strip()
        if ln.startswith("I:"):
            I = float(ln.split()[1])
        elif ln.startswith("Peak:"):
            TP = float(ln.split()[1])
    return {"output": path, "width": w, "height": h, "duration": round(dur, 2), "lufs": I, "true_peak": TP}


def check_frames(path, dur, n=8):
    """Full-size frames + a phone-size sheet (~360 px wide each, unsafe zones shaded)."""
    d = os.path.splitext(path)[0] + "_check"
    os.makedirs(d, exist_ok=True)
    thumbs = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        fp = os.path.join(d, f"frame_{i:02d}.jpg")
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-q:v", "2", fp])
        im = Image.open(fp).convert("RGBA")
        shade = Image.new("RGBA", im.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        for box in ([0, 0, W, SAFE["top"]], [0, H - SAFE["bottom"], W, H],
                    [W - SAFE["right"], SAFE["top"], W, H - SAFE["bottom"]]):
            sd.rectangle(box, fill=(255, 0, 0, 60))
        thumbs.append(Image.alpha_composite(im, shade).convert("RGB").resize((360, 640), Image.LANCZOS))
    sheet = Image.new("RGB", (360 * 4 + 30, 640 * ((n + 3) // 4) + 10 * ((n + 3) // 4)), "white")
    for i, th in enumerate(thumbs):
        sheet.paste(th, ((i % 4) * 370, (i // 4) * 650))
    sheet.save(os.path.join(d, "phone_sheet.jpg"), quality=88)
    print(f"check frames: {d}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true", help="write full-size + phone-size check frames")
    a = ap.parse_args()
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    out = a.out or spec.get("output")
    if not out:
        sys.exit("no output path (spec 'output' or --out)")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    build(spec, os.path.abspath(out), check=a.check)


if __name__ == "__main__":
    main()
