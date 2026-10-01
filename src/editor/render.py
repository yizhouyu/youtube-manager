"""Render an EDL into a finished vlog.

    ./venv/bin/python -m src.editor.render "<project>" --preview   # 1080p, edit/preview.mp4
    ./venv/bin/python -m src.editor.render "<project>" --final     # 4K, 02 - Export/<project>.mp4
    ./venv/bin/python -m src.editor.render "<project>" --package   # clean numbered clips for CapCut/剪映

Pipeline: each enabled shot -> its own video-only segment (graded, scaled, overlays burned in)
plus an exact-length PCM wav; segments are cached by content hash so re-rendering after a
small edit only re-encodes the shots that changed. Segment lengths are quantized to whole
frames and audio is kept as PCM until the final mux, so 100+ cuts never drift out of sync.
Then: concat -> music bed (tracks crossfaded, ducked under speech) -> master (linear gain to -14 LUFS,
4x-oversampled limiter, AAC, true peak re-measured on the AAC and corrected in a loop) -> mux.
Also writes captions.srt (timeline-mapped) for YouTube CC.

Progress goes to edit/render_status.json for the review page.
"""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

from . import edl as E
from . import overlays

PRESETS = {
    "preview": {"w": 1920, "h": 1080, "vb": "12M"},
    # Final master: 10-bit HEVC at ~2x the GoPro source bitrate — grading + burned-in text force a
    # re-encode, so over-provision to keep it visually lossless (YouTube re-encodes anyway).
    "final": {"w": 3840, "h": 2160, "vb": "100M", "tenbit": True},
}
SR = 48000


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:12])} ...\n{r.stderr[-1500:]}")
    return r


class Status:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()  # segment workers report progress concurrently

    def set(self, **kw):
        kw.setdefault("updated", time.time())
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(kw, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        if kw.get("step"):
            print(f"[render] {kw['step']}", flush=True)


def _pixfmt(preset):
    """Grade/composite at 10 bits for the final master (less banding in skies and water)."""
    return "yuv420p10le" if preset.get("tenbit") else "yuv420p"


def _venc(preset):
    args = ["-c:v", "hevc_videotoolbox", "-b:v", preset["vb"], "-tag:v", "hvc1", "-g", "60"]
    if preset.get("tenbit"):
        args += ["-profile:v", "main10", "-pix_fmt", "p010le"]
    return args


def frames_of(shot, fps):
    return max(1, round(E.shot_dur(shot) * fps))


def _zoom_filters(z, dur, w, h):
    """Ken Burns: smooth (smoothstep-eased) push/pull toward a focal point. Scale per frame with
    float precision, then crop — avoids zoompan's integer-pixel jitter."""
    a, b = z.get("from", 1.0), z.get("to", 1.2)
    x, y = z.get("x", 0.5), z.get("y", 0.5)
    p = f"min(t/{dur:.3f},1)"
    zz = f"({a}+({b - a})*{p}*{p}*(3-2*{p}))"
    return [f"scale='trunc({w}*{zz}/2)*2':'trunc({h}*{zz}/2)*2':eval=frame:flags=bicubic",
            # crop's iw/ih are fixed at init (the first frame's size), so compute the offset
            # from the same per-frame zoom expression instead
            f"crop={w}:{h}:'(trunc({w}*{zz}/2)*2-{w})*{x}':'(trunc({h}*{zz}/2)*2-{h})*{y}'"]


def is_tts_sfx(fx):
    """A shot `sfx` entry that is really a narration line (a file under edit/tts/, or "tts": true)."""
    return bool(fx.get("tts", fx.get("file", "").replace("\\", "/").startswith("tts/")))


def _tts_chain_on(edl):
    return edl.get("tts_chain", True) is not False


def _sfx_chain(edl, shot, inputs, k, dur, src_label, out_label):
    """Mix a shot's `sfx` ([{file, at, gain}], file relative to edit/) over its audio. TTS lines
    used as sfx are left out here: mix_voiceover places them, processed and level-matched."""
    labels = [f"[{src_label}]"]
    chains = []
    for i, fx in enumerate(shot.get("sfx", [])):
        if _tts_chain_on(edl) and is_tts_sfx(fx):
            continue
        path = os.path.join(E.edit_dir(edl["project"]), fx["file"])
        if not os.path.exists(path):
            continue
        inputs += ["-i", path]
        chains.append(f"[{k}:a]aresample={SR},aformat=channel_layouts=stereo,volume={fx.get('gain', 0.8)},"
                      f"adelay={int(fx.get('at', 0) * 1000)}:all=1[fx{i}]")
        labels.append(f"[fx{i}]")
        k += 1
    if len(labels) == 1:
        return f"[{src_label}]anull[{out_label}]"
    chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first,"
                  f"atrim=0:{dur:.6f}[{out_label}]")
    return ";".join(chains)


def _card_image_path(edl, card):
    return os.path.join(E.edit_dir(edl["project"]), card["image"])


def _render_card(edl, shot, fps_str, preset, n, dur, ov_dir, vpath):
    """A generated card: the playful time card ("两小时后……"), or — with `card.image` — a still
    (.png/.jpg, gentle push-in) or a short animation (.mp4/.mov, e.g. a route map; looped/trimmed to
    the shot length) from the project's edit/ folder. Optional sfx either way."""
    w, h = preset["w"], preset["h"]
    c = shot["card"]
    img = _card_image_path(edl, c) if c.get("image") else None
    anim = bool(img) and os.path.splitext(img)[1].lower() in (".mp4", ".mov", ".m4v")
    if img and not os.path.exists(img):
        raise FileNotFoundError(f"card image not found: {img}")
    png = img or overlays.card(c["text"], c.get("sub", ""), w, h, ov_dir, c.get("bg", "#ffd84d"), c.get("fg", "#1f2937"))
    src = (["-stream_loop", "-1", "-t", f"{dur + 0.2:.3f}", "-i", png] if anim else
           ["-loop", "1", "-framerate", fps_str, "-t", f"{dur + 0.2:.3f}", "-i", png])
    inputs = src
    zoom = c.get("zoom", {"from": 1.0, "to": 1.08}) if not anim else c.get("zoom")
    vf = (_zoom_filters(zoom, dur, w, h) if zoom else []) + [f"fps={fps_str}"]
    if shot.get("fade_in"):
        vf.append(f"fade=t=in:st=0:d={shot['fade_in']}")
    if shot.get("fade_out"):
        vf.append(f"fade=t=out:st={max(0, dur - shot['fade_out']):.3f}:d={shot['fade_out']}")
    chains = [f"[0:v]scale={w}:{h},{','.join(vf)},format={_pixfmt(preset)}[v]"]
    tmpv = vpath + ".part.mp4"
    _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", "[v]", "-frames:v", str(n), "-an", *_venc(preset), tmpv])
    os.replace(tmpv, vpath)
    return vpath


# R3: lifting a quiet speaker must not lift their transients. A shot with gain_db > 0 gets a
# 4x-oversampled limiter whose ceiling sits PEAK_GUARD_PLR dB above the shot's own (post-gain)
# loudness, so boosted lines stop being the peaks that the master limiter has to squash.
PEAK_GUARD_PLR = 12.0


def peak_guard_ceiling(shot_lufs, plr=PEAK_GUARD_PLR):
    """Limiter ceiling (dBFS) for a boosted shot: its loudness + plr, at most -3 dBFS; None when the
    shot is silent (nothing to guard)."""
    if shot_lufs is None or shot_lufs <= -70:
        return None
    return min(-3.0, shot_lufs + plr)


def peak_guard(shot_lufs):
    """Filters for the boosted-shot limiter (alimiter can't go below -24 dBFS: shift around it)."""
    c = peak_guard_ceiling(shot_lufs)
    if c is None:
        return []
    shift = max(0.0, -20.0 - c)
    lim = f"alimiter=limit={10 ** ((c + shift) / 20):.5f}:attack=2:release=60:level=false:latency=1"
    return ([f"volume={shift:.2f}dB"] if shift else []) + ["aresample=192000", lim, f"aresample={SR}"] + \
        ([f"volume={-shift:.2f}dB"] if shift else [])


def _measure_span(inputs, chain, pre_chains=()):
    """Loudness of one shot's audio through `chain` (filtergraph text ending without a label)."""
    graph = ";".join(list(pre_chains) + [f"{chain},ebur128=peak=true:framelog=quiet"])
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *inputs, "-filter_complex", graph, "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    v = re.findall(r"^\s+I:\s+(-?[\d.]+|-inf) LUFS", err, re.M)
    return {"I": float(v[-1]) if v else None}


# Segment cache versions. Video and audio are cached separately, so an audio-only change re-renders
# a few seconds of PCM per shot instead of every shot's picture. Bump the matching one whenever the
# segment output changes without the shot dict changing.
VIDEO_CACHE_VERSION = 9
AUDIO_CACHE_VERSION = 2


def render_segment(edl, shot, fps_str, preset, cache, clean=False):
    """-> (video_path, wav_path) for one shot; each cached by its own content hash."""
    return render_segment_video(edl, shot, fps_str, preset, cache, clean), render_segment_audio(edl, shot, fps_str, cache)


def render_segment_video(edl, shot, fps_str, preset, cache, clean=False):
    """Video-only segment (graded, scaled, overlays burned in), cached by content hash."""
    fps = float(Fraction(fps_str))
    w, h = preset["w"], preset["h"]
    n = frames_of(shot, fps)
    dur = n / fps
    grade = edl.get("grades", {}).get(shot.get("grade", "default"), "")
    brg = {b.get("grade", "default"): edl.get("grades", {}).get(b.get("grade", "default"), "")
           for b in shot.get("broll", [])}
    extra = ["zoomfix"] if shot.get("zoom") else []
    for pp in shot.get("pip", []):  # re-render when a pip file (e.g. a mini-map animation) changes
        if pp.get("file"):
            fp = os.path.join(E.edit_dir(edl["project"]), pp["file"])
            extra.append(os.path.getmtime(fp) if os.path.exists(fp) else "missing")
    if (shot.get("card") or {}).get("image"):  # re-render when the card's image/animation file changes
        ip = _card_image_path(edl, shot["card"])
        extra.append(os.path.getmtime(ip) if os.path.exists(ip) else "missing")
    key = json.dumps([shot, grade, brg, fps_str, preset, clean, VIDEO_CACHE_VERSION, overlays.VERSION] + extra,
                     sort_keys=True, ensure_ascii=False)
    hid = hashlib.sha1(key.encode()).hexdigest()[:12]
    vpath = os.path.join(cache, f"{shot['id']}_{hid}.mp4")
    if os.path.exists(vpath):
        return vpath

    ov_dir = os.path.join(cache, "overlays")
    if shot.get("card"):
        return _render_card(edl, shot, fps_str, preset, n, dur, ov_dir, vpath)
    src = E.clip_path(edl, shot["clip"])
    span = shot["out"] - shot["in"]
    inputs = ["-ss", f"{shot['in']:.3f}", "-t", f"{span + 0.2:.3f}", "-i", src]
    chains, last = [], "v0"
    # jump-cut out skipped spans (pauses / fillers): trim each kept range and concat
    ranges = [(a - shot["in"], b - shot["in"]) for a, b in E.kept_ranges(shot)]
    if len(ranges) > 1:
        m = len(ranges)
        chains.append(f"[0:v]split={m}" + "".join(f"[vs{i}]" for i in range(m)))
        for i, (a, b) in enumerate(ranges):
            chains.append(f"[vs{i}]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[vk{i}]")
        chains.append("".join(f"[vk{i}]" for i in range(m)) + f"concat=n={m}:v=1:a=0[vsrc]")
        vsrc = "[vsrc]"
    else:
        vsrc = "[0:v]"
    vf = [f"scale={w}:{h}:flags=lanczos", f"fps={fps_str}"]
    if shot.get("zoom"):
        vf[1:1] = _zoom_filters(shot["zoom"], dur, w, h)
    if grade:
        vf.append(grade)
    fi, fo = shot.get("fade_in", 0), shot.get("fade_out", 0)
    if fi:
        vf.append(f"fade=t=in:st=0:d={fi}")
    if fo:
        vf.append(f"fade=t=out:st={max(0, dur - fo):.3f}:d={fo}")
    k = E.speed(shot)
    retime = f"setpts=(PTS-STARTPTS)/{k}" if k != 1 else "setpts=PTS-STARTPTS"
    chains.append(f"{vsrc}{retime},{','.join(vf)},format={_pixfmt(preset)}[v0]")

    # B-roll: cut the picture away to another clip while the main shot's audio keeps playing.
    grades = edl.get("grades", {})
    for b in shot.get("broll", []):
        at = E.src_to_local(shot, shot["in"] + b["at"])
        bd = min(b["dur"], dur - at)
        if bd <= 0.1:
            continue
        k = len(inputs) // 6  # every input below is 6 args
        inputs += ["-ss", f"{b['in']:.3f}", "-t", f"{bd + 0.2:.3f}", "-i", E.clip_path(edl, b["clip"])]
        bvf = [f"scale={w}:{h}:flags=lanczos", f"fps={fps_str}"]
        if grades.get(b.get("grade", "default")):
            bvf.append(grades[b.get("grade", "default")])
        chains.append(f"[{k}:v]trim=0:{bd:.3f},setpts=PTS-STARTPTS+{at:.3f}/TB,{','.join(bvf)},format={_pixfmt(preset)}[b{k}]")
        chains.append(f"[{last}][b{k}]overlay=0:0:eof_action=pass:enable='between(t,{at:.3f},{at + bd:.3f})'[vb{k}]")
        last = f"vb{k}"
    base_inputs = len(inputs) // 6

    ovs = []  # (png, t0, t1, fade)
    if not clean:
        if shot.get("title"):
            t = shot["title"]
            td = min(t.get("dur", 3.0), dur)
            ovs.append((overlays.title_card(t["text"], t.get("sub", ""), w, h, ov_dir), 0, td, 0.4))
        if shot.get("tag"):
            ovs.append((overlays.place_tag(shot["tag"], w, h, ov_dir), 0, min(3.0, dur), 0.3))
        for sp in shot.get("spots", []):  # spotlight: dim all but a circle on a hidden subject
            a0, a1 = E.src_to_local(shot, sp["t0"]), min(E.src_to_local(shot, sp["t1"]), dur)
            if a1 - a0 > 0.6:
                png = overlays.spotlight(sp.get("label", ""), sp["x"], sp["y"], sp.get("r", 0.16), w, h, ov_dir,
                                         sp.get("dim", 0.55))
                ovs.append((png, a0, a1, 0.3))
        for m in shot.get("marks", []):
            a0, a1 = E.src_to_local(shot, m["t0"]), min(E.src_to_local(shot, m["t1"]), dur)
            if a1 - a0 > 0.1:
                ovs.append((overlays.arrow(m.get("label", ""), m["x"], m["y"], w, h, ov_dir), a0, a1, 0))
        for s in E.shot_subs(shot):
            ovs.append((overlays.subtitle(s["text"], w, h, ov_dir, s.get("kind", "speech")), s["t0"], min(s["t1"], dur), 0))
    for i, (png, t0, t1, fade) in enumerate(ovs, base_inputs):
        if fade:  # fades in at t0 (frames before it are fully transparent), out at t1
            inputs += ["-loop", "1", "-framerate", fps_str, "-t", f"{t1:.3f}", "-i", png]
            chains.append(f"[{i}:v]format=rgba,fade=t=in:st={t0:.3f}:d={fade}:alpha=1,"
                          f"fade=t=out:st={max(0, t1 - fade):.3f}:d={fade}:alpha=1[o{i}]")
            chains.append(f"[{last}][o{i}]overlay=0:0:eof_action=pass[v{i}]")
        else:
            inputs += ["-i", png]
            chains.append(f"[{last}][{i}:v]overlay=0:0:enable='between(t,{t0:.3f},{t1:.3f})'[v{i}]")
        last = f"v{i}"
    if shot.get("gauge") and not clean:  # animated depth/altitude meter (PNG sequence, panel-sized)
        pat, gx, gy = overlays.gauge_frames(shot["gauge"], dur, w, h, ov_dir)
        gi = base_inputs + len(ovs)
        inputs += ["-framerate", str(overlays.GAUGE_FPS), "-i", pat]
        chains.append(f"[{gi}:v]format=rgba,setpts=PTS-STARTPTS[g{gi}]")
        chains.append(f"[{last}][g{gi}]overlay={gx}:{gy}:eof_action=repeat[vg]")
        last = "vg"
        ovs.append(None)  # keeps the pip input index below in step
    for j, pp in enumerate(shot.get("pip", []) if not clean else []):
        got = _pip_chain(edl, pp, j, dur, fps_str, preset, inputs, base_inputs + len(ovs), last, chains)
        if got:
            last = got
            ovs.append(None)

    tmpv = vpath + ".part.mp4"
    _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", f"[{last}]", "-frames:v", str(n), "-an", *_venc(preset), tmpv])
    os.replace(tmpv, vpath)
    return vpath


def render_segment_audio(edl, shot, fps_str, cache):
    """Exact-length PCM wav for one shot (its own sound + sfx), cached by content hash."""
    fps = float(Fraction(fps_str))
    dur = frames_of(shot, fps) / fps
    fx_files = [os.path.join(E.edit_dir(edl["project"]), fx["file"]) for fx in shot.get("sfx", [])]
    extra = [os.path.getmtime(f) if os.path.exists(f) else "missing" for f in fx_files]
    key = json.dumps([shot, fps_str, AUDIO_CACHE_VERSION, edl.get("denoise_voice", False), _tts_chain_on(edl)] + extra,
                     sort_keys=True, ensure_ascii=False)
    hid = hashlib.sha1(key.encode()).hexdigest()[:12]
    apath = os.path.join(cache, f"{shot['id']}_a{hid}.wav")
    if os.path.exists(apath):
        return apath
    fi, fo = shot.get("fade_in", 0), shot.get("fade_out", 0)
    if shot.get("card"):
        inputs = ["-f", "lavfi", "-t", f"{dur + 0.2:.3f}", "-i", f"anullsrc=r={SR}:cl=stereo"]
        chains = [f"[0:a]atrim=0:{dur:.6f}[a0]"]
    else:
        span = shot["out"] - shot["in"]
        inputs = ["-ss", f"{shot['in']:.3f}", "-t", f"{span + 0.2:.3f}", "-i", E.clip_path(edl, shot["clip"])]
        chains = []
        ranges = [(a - shot["in"], b - shot["in"]) for a, b in E.kept_ranges(shot)]
        if len(ranges) > 1:  # jump-cut out skipped spans (pauses / fillers)
            m = len(ranges)
            chains.append(f"[0:a]asplit={m}" + "".join(f"[as{i}]" for i in range(m)))
            for i, (a, b) in enumerate(ranges):
                chains.append(f"[as{i}]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,"
                              f"afade=t=in:d=0.012,afade=t=out:st={max(0, b - a - 0.012):.3f}:d=0.012[ak{i}]")
            chains.append("".join(f"[ak{i}]" for i in range(m)) + f"concat=n={m}:v=0:a=1[asrc]")
            asrc = "[asrc]"
        else:
            asrc = "[0:a]"
        gain = E.AUDIO_GAIN.get(shot.get("audio", "voice"), 1.0) if E.speed(shot) <= 1 else 0.0
        gain *= 10 ** (max(-24.0, min(12.0, float(shot.get("gain_db", 0) or 0))) / 20)  # lift a quiet speaker
        af = [f"aresample={SR}", "aformat=channel_layouts=stereo", f"volume={gain}"]
        mode = shot.get("denoise", edl.get("denoise_voice", False))
        if mode == "wind":
            # heavy wind on an action cam: a higher cut + stronger FFT denoise; ambient beds also get
            # tamed (and a touch quieter) so the music carries them instead of the roar
            if shot.get("audio", "voice") == "voice":
                af[2:2] = ["highpass=f=200", "afftdn=nr=24:nf=-28:tn=1", "equalizer=f=3000:t=q:w=1:g=2"]
            elif shot.get("audio") == "ambient":
                af[2:2] = ["highpass=f=250", "afftdn=nr=20:nf=-30:tn=1", "volume=0.6"]
        elif mode and shot.get("audio", "voice") == "voice":
            # boat engines / wind: cut the low rumble, then FFT denoise under the voice
            af[2:2] = ["highpass=f=140", "afftdn=nr=18:nf=-30:tn=1"]
        if float(shot.get("gain_db", 0) or 0) > 0 and gain > 0:
            af += peak_guard(_measure_span(inputs, f"{asrc}asetpts=PTS-STARTPTS,{','.join(af)}", chains)["I"])
        # 12 ms edge fades on every shot: a hard cut on a non-zero sample (wind) clicks after limiting
        af.append(f"afade=t=in:st=0:d={max(fi or 0, EDGE_FADE)}")
        af.append(f"afade=t=out:st={max(0, dur - max(fo or 0, EDGE_FADE)):.3f}:d={max(fo or 0, EDGE_FADE)}")
        af += ["apad", f"atrim=0:{dur:.6f}"]
        chains.append(f"{asrc}asetpts=PTS-STARTPTS,{','.join(af)}[a0]")
    chains.append(_sfx_chain(edl, shot, inputs, 1, dur, "a0", "a"))
    tmpa = apath + ".part.wav"
    _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", "[a]", "-vn", "-c:a", "pcm_s16le", tmpa])
    os.replace(tmpa, apath)
    return apath


EDGE_FADE = 0.012


def _pip_chain(edl, pp, j, dur, fps_str, preset, inputs, idx, last, chains):
    """Picture-in-picture: a framed inset over the shot for [t0, t1] (shot-local rendered seconds).
    Source is an edit/ file (`file`: .png/.jpg still or .mp4/.mov animation, e.g. a live mini-map)
    or another raw clip (`clip` + `in`, optional `grade`, `speed`) for a second angle / reaction.
    `x`, `y` = top-left of the inset as frame fractions, `w` = width fraction, `aspect` (w/h,
    default 16/9), `border` = white frame in px at 1080p (default 6, 0 = none), `fade` (s).
    Appends one input; returns the new video label, or None if the entry is unusable."""
    w, h = preset["w"], preset["h"]
    t0 = max(0.0, float(pp.get("t0", 0.0)))
    t1 = min(dur, float(pp.get("t1", dur)))
    if t1 - t0 < 0.2:
        return None
    span = t1 - t0
    pw = int(w * float(pp.get("w", 0.3))) // 2 * 2
    ph = int(pw / float(pp.get("aspect", 16 / 9))) // 2 * 2
    b = int(round(float(pp.get("border", 6)) * h / 1080)) // 2 * 2
    fade = float(pp.get("fade", 0.3))
    grade = edl.get("grades", {}).get(pp.get("grade", "default"), "") if pp.get("clip") else ""
    if pp.get("clip"):
        k = max(0.25, float(pp.get("speed", 1.0) or 1.0))
        inputs += ["-ss", f"{float(pp.get('in', 0.0)):.3f}", "-t", f"{span * k + 0.3:.3f}", "-i", E.clip_path(edl, pp["clip"])]
        head = f"[{idx}:v]setpts=(PTS-STARTPTS)/{k},"
    else:
        path = os.path.join(E.edit_dir(edl["project"]), pp["file"])
        if not os.path.exists(path):
            raise FileNotFoundError(f"pip file not found: {path}")
        if os.path.splitext(path)[1].lower() in (".mp4", ".mov", ".m4v"):
            inputs += ["-stream_loop", "-1", "-t", f"{span + 0.3:.3f}", "-i", path]
        else:
            inputs += ["-loop", "1", "-framerate", fps_str, "-t", f"{span + 0.3:.3f}", "-i", path]
        head = f"[{idx}:v]setpts=PTS-STARTPTS,"
    vf = [f"fps={fps_str}", f"trim=0:{span:.3f}", f"scale={pw}:{ph}:flags=lanczos"]
    if grade:
        vf.append(grade)
    if b:
        vf.append(f"pad={pw + 2 * b}:{ph + 2 * b}:{b}:{b}:color=white")
    vf.append("format=rgba")
    if fade:
        vf += [f"fade=t=in:st=0:d={fade}:alpha=1", f"fade=t=out:st={max(0, span - fade):.3f}:d={fade}:alpha=1"]
    vf.append(f"setpts=PTS+{t0:.3f}/TB")
    x = int(w * float(pp.get("x", 0.66)))
    y = int(h * float(pp.get("y", 0.06)))
    chains.append(head + ",".join(vf) + f"[pp{j}]")
    chains.append(f"[{last}][pp{j}]overlay={x}:{y}:eof_action=pass:enable='between(t,{t0:.3f},{t1:.3f})'[vp{j}]")
    return f"vp{j}"


_DUR_CACHE = {}


def _media_dur(path):
    key = (path, os.path.getmtime(path))
    if key not in _DUR_CACHE:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True)
        _DUR_CACHE[key] = float(p.stdout.strip() or 0)
    return _DUR_CACHE[key]


def voiceover_spans(edl):
    """[(path, t0, dur, entry)] for the EDL's `voiceover` entries: a narration/TTS file placed at
    its `start` shot's timeline start + `at` (or the first enabled shot after it, like music). Unlike a
    shot's `sfx`, it may run across shot boundaries. Entries whose start shot and everything after
    it are cut are dropped."""
    rows, _ = E.timeline(edl)
    starts = {s["id"]: st for s, st in rows}
    order = edl.get("_order") or [s["id"] for s in edl["shots"]]
    out = []
    for v in edl.get("voiceover", []):
        path = os.path.join(E.edit_dir(edl["project"]), v["file"])
        if not os.path.exists(path):
            raise FileNotFoundError(f"voiceover file missing: {v['file']}")
        t = None
        if v.get("start") in order:
            t = next((starts[sid] for sid in order[order.index(v["start"]):] if sid in starts), None)
        if t is None:
            continue
        out.append((path, t + float(v.get("at", 0.0)), _media_dur(path), v))
    return out


def tts_sfx_spans(edl):
    """[(path, t0, dur, entry)] for TTS lines used as shot `sfx` (see is_tts_sfx): placed at the
    shot's timeline start + `at`, cut at the shot's end like any sfx. Empty when the TTS chain is off
    (the segment mixes them raw then, as before)."""
    if not _tts_chain_on(edl):
        return []
    rows, _ = E.timeline(edl)
    out = []
    for s, st in rows:
        for fx in s.get("sfx", []):
            if not is_tts_sfx(fx):
                continue
            path = os.path.join(E.edit_dir(edl["project"]), fx["file"])
            if not os.path.exists(path):
                continue
            at = float(fx.get("at", 0.0))
            d = min(_media_dur(path), E.shot_dur(s) - at)
            if d > 0.05:
                out.append((path, st + at, d, fx))
    return out


# ---- TTS processing (research R2) ------------------------------------------------------------------
# edge-tts output is 24 kHz mono MP3 with a peak-to-loudness ratio of ~19 dB: the two Yale TTS lines
# were the episode's loudest peaks. Every line goes through a broadcast-VO chain once (decoded to
# float WAV, cached; never MP3 -> MP3), then sits at the episode's on-camera speech loudness instead
# of a fixed +dB. No silence trimming/padding here, so the timing of existing `at` values holds.
TTS_VERSION = 1
TTS_CHAIN = ("aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,"
             "highpass=f=90:p=2,equalizer=f=250:t=q:w=1.2:g=-2,equalizer=f=3500:t=q:w=1.5:g=1.5,"
             "deesser=i=0.3,acompressor=threshold=0.0316:ratio=4:attack=3:release=60:knee=2.8:makeup=4,"
             "aresample=192000,alimiter=limit=0.28:attack=1:release=30:level=false:latency=1,aresample=48000,"
             "aformat=channel_layouts=stereo")
SPEECH_REF_FALLBACK = -21.0   # LUFS: on-camera speech in voice.wav when an episode has too few captions
VO_OFFSET_LU = 0.5            # narration sits this much above the on-camera speech reference


def tts_processed(path, cache_dir):
    """-> (wav_path, integrated_lufs) of `path` through TTS_CHAIN, cached by path + mtime + size."""
    st = os.stat(path)
    hid = hashlib.sha1(json.dumps([os.path.abspath(path), st.st_mtime, st.st_size, TTS_VERSION, TTS_CHAIN])
                       .encode()).hexdigest()[:12]
    os.makedirs(cache_dir, exist_ok=True)
    wav = os.path.join(cache_dir, f"{os.path.splitext(os.path.basename(path))[0]}_{hid}.wav")
    meta = wav + ".json"
    if os.path.exists(wav) and os.path.exists(meta):
        with open(meta) as f:
            return wav, json.load(f)["I"]
    _run(["ffmpeg", "-v", "error", "-y", "-i", path, "-af", TTS_CHAIN, "-c:a", "pcm_f32le", wav + ".part.wav"])
    os.replace(wav + ".part.wav", wav)
    m = _measure(wav)
    with open(meta, "w") as f:
        json.dump(m, f)
    return wav, m["I"]


def _momentary(path):
    """(t, M): EBU momentary loudness every 100 ms (t = end of each 400 ms window)."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "verbose", "-i", path, "-vn", "-af",
                          "ebur128=framelog=verbose", "-f", "null", "-"], capture_output=True, text=True).stderr
    t, m = [], []
    for mt in re.finditer(r"t:\s*([\d.]+)\s+TARGET.*?M:\s*(-?[\d.]+|-inf)", err):
        t.append(float(mt.group(1)))
        m.append(float(mt.group(2)))
    return t, m


def power_mean_lufs(values, floor=-70.0):
    v = [x for x in values if x > floor]
    return 10 * math.log10(sum(10 ** (x / 10) for x in v) / len(v)) if v else None


def speech_reference(edl, voice_wav, exclude=()):
    """On-camera speech loudness of the dialogue track: power mean of momentary loudness inside the
    speech-caption windows (= the dialogue-gated loudness of what people say on camera), skipping
    captions that overlap `exclude` spans (the narration's own captions). Falls back to
    SPEECH_REF_FALLBACK with fewer than 3 usable captions. -> (lufs, n_captions)."""
    wins = [(s["t0"], s["t1"]) for s in E.timeline_subs(edl) if s["kind"] == "speech" and s["t1"] - s["t0"] > 0.8
            and not any(s["t0"] < b and a < s["t1"] for a, b in exclude)]
    if len(wins) < 3:
        return SPEECH_REF_FALLBACK, len(wins)
    t, m = _momentary(voice_wav)
    vals = [mm for tt, mm in zip(t, m) if any(a + 0.4 <= tt <= b for a, b in wins)]
    ref = power_mean_lufs(vals)
    return (ref if ref is not None else SPEECH_REF_FALLBACK), len(wins)


def vo_gain_db(entry, line_lufs, speech_ref, offset=VO_OFFSET_LU):
    """Gain for one processed TTS line: the entry's manual `gain_db` if set, else level-matched to
    the on-camera speech reference + offset (clamped to +-24 dB)."""
    if entry.get("gain_db") is not None:
        return float(entry["gain_db"]), False
    return max(-24.0, min(24.0, speech_ref + offset - line_lufs)), True


def mix_voiceover(edl, voice_wav, total):
    """Mix the `voiceover` layer (and TTS lines used as sfx) into the concatenated dialogue track in
    place. -> a summary dict for render_status.json, or False when there is nothing to mix."""
    vo, fx = voiceover_spans(edl), tts_sfx_spans(edl)
    spans = vo + fx
    if not spans:
        return False
    chain_on = _tts_chain_on(edl)
    info = {"lines": []}
    if chain_on:
        ref, n = speech_reference(edl, voice_wav, exclude=[(t0, t0 + d) for _p, t0, d, _e in spans])
        offset = float(edl.get("vo_offset_lu", VO_OFFSET_LU))
        info.update(speech_ref=round(ref, 1), speech_captions=n, vo_offset_lu=offset)
    args, chain, labels = ["-i", voice_wav], [], ["[0:a]"]
    tts_cache = os.path.join(os.path.dirname(os.path.abspath(voice_wav)), "tts")
    for k, (path, t0, d, entry) in enumerate(spans, 1):
        if chain_on:
            src, line_i = tts_processed(path, tts_cache)
            gain, auto = vo_gain_db(entry, line_i, ref, offset)
            info["lines"].append({"file": entry.get("file"), "t0": round(t0, 2), "line_I": line_i,
                                  "gain_db": round(gain, 2), "auto": auto})
            print(f"[voiceover] {entry.get('file')}: line {line_i:.1f} LUFS -> {gain:+.1f} dB "
                  f"({'auto, speech ref %.1f' % ref if auto else 'manual gain_db'})", flush=True)
        else:  # legacy: raw file, fixed `gain` dB (voiceover) / linear `gain` (sfx is mixed in the segment)
            src, gain = path, float(entry.get("gain", 0.0))
        args += ["-i", src]
        # a TTS sfx is cut at its shot's end (10 ms fade so the cut can't click)
        trim = f"atrim=0:{d:.4f},afade=t=out:st={max(0, d - 0.01):.4f}:d=0.01," if k > len(vo) else ""
        chain.append(f"[{k}:a]aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,{trim}volume={gain:.2f}dB,"
                     f"afade=t=in:d=0.02,adelay={int(round(t0 * 1000))}:all=1[vo{k}]")
        labels.append(f"[vo{k}]")
    chain.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first,atrim=0:{total:.3f}[out]")
    tmp = voice_wav + ".vo.wav"
    _run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex", ";".join(chain), "-map", "[out]",
          "-c:a", "pcm_s16le", tmp])
    os.replace(tmp, voice_wav)
    return info


def _speech_windows(edl, pad=0.35):
    iv = sorted((max(0, s["t0"] - pad), s["t1"] + pad) for s in E.timeline_subs(edl)
                if s["kind"] == "speech")  # editor notes don't duck the music
    # narration ducks the music too, whether or not its caption is on a shot (cards draw no subtitles)
    iv = sorted(iv + [(max(0, t0 - pad), t0 + d + pad) for _p, t0, d, _e in voiceover_spans(edl)])
    merged = []
    for a, b in iv:
        if merged and a <= merged[-1][1] + 0.8:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def music_sections(edl, total):
    """[(path, start, end, entry)]: each music entry starts at its `start` shot (first enabled shot at
    or after it; omitted = right after the previous section) and runs until the next section. `entry`
    is the music dict itself, so a track used twice keeps each use's own `in`/`gain`."""
    rows, _ = E.timeline(edl)
    order = edl.get("_order") or [s["id"] for s in edl["shots"]]
    starts_at = {}
    for s, st in rows:
        starts_at[s["id"]] = st
    secs = []
    for m in edl.get("music", []):
        # "file": null (or "") = a silent "breathing room" section: the previous track fades out
        # and only the shots' own sound plays until the next section fades in
        path = os.path.join(E.edit_dir(edl["project"]), m["file"]) if m.get("file") else None
        if path is not None and not os.path.exists(path):
            # never silently drop a section: a missing track left 20 s of dead air once
            raise FileNotFoundError(f"music track missing: {m['file']}")
        t = None
        if m.get("start") in order:
            for sid in order[order.index(m["start"]):]:
                if sid in starts_at:
                    t = starts_at[sid]; break
        if t is None:
            t = 0.0 if not secs else None
        if t is None:
            continue  # its start shot and everything after it was cut
        secs.append([path, t, m])
    secs.sort(key=lambda x: x[1])
    return [(p, t, secs[i + 1][1] if i + 1 < len(secs) else total, m) for i, (p, t, m) in enumerate(secs)
            if (secs[i + 1][1] if i + 1 < len(secs) else total) - t > 1.0]


_LUFS_CACHE = {}


def _track_lufs(path):
    """Integrated loudness of a music file (cached by path + mtime)."""
    key = (path, os.path.getmtime(path))
    if key not in _LUFS_CACHE:
        p = subprocess.run(["ffmpeg", "-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-"],
                           capture_output=True, text=True)
        vals = re.findall(r"^\s+I:\s+(-?[\d.]+) LUFS", p.stderr, re.M)
        _LUFS_CACHE[key] = float(vals[-1]) if vals else -14.0
    return _LUFS_CACHE[key]


def _track_gain_db(path, entry):
    """Loudness-match every track to -14 LUFS (Audio Library tracks differ by 15+ LU), plus the
    music entry's optional manual "gain" in dB."""
    return max(-20.0, min(12.0, -14.0 - _track_lufs(path))) + float(entry.get("gain", 0.0))


def music_bed(edl, total, workdir, out_wav):
    secs = music_sections(edl, total)
    if not secs:
        _run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo",
              "-t", f"{total:.3f}", out_wav])
        return False
    xf = 2.5
    args, chain, labels = [], [], []
    for k, (path, t0, t1, entry) in enumerate(secs):
        # one shared xf window before each section start: the incoming track fades in over
        # [start - xf, start] while the outgoing one fades out over the same window, equal-power
        # (qsin in / qsin out = sin/cos), so two songs never play at full level together (ep 96 QA).
        # Track time at the start shot stays `in` + xf. Tracks loop if the section is long.
        a0 = max(0.0, t0 - (xf if k else 0))
        d = min(total, t1) - a0
        fades = [] if k == 0 else [f"afade=t=in:st=0:d={xf}:curve=qsin"]
        if k + 1 < len(secs):
            fo = min(xf, d)
            fades.append(f"afade=t=out:st={max(0, d - fo):.3f}:d={fo:.3f}:curve=qsin")
        if path is None:  # silent section
            args += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", f"anullsrc=r={SR}:cl=stereo"]
            gain, t_in = 0.0, 0.0
        else:
            args += ["-stream_loop", "-1", "-i", path]
            # this entry's own "in" (skip a quiet intro / pick a later passage) — looked up per entry,
            # not per file: a reused track played from its first use's `in` (ep 96 QA)
            gain, t_in = _track_gain_db(path, entry), float(entry.get("in", 0.0))
        chain.append(f"[{k}:a]aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     f"volume={gain:.2f}dB,"
                     f"atrim={t_in:.3f}:{t_in + d:.3f},"
                     f"asetpts=PTS-STARTPTS{',' + ','.join(fades) if fades else ''},"
                     f"adelay={int(a0 * 1000)}:all=1[m{k}]")
        labels.append(f"[m{k}]")
    chain.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[mx]")
    cur = "mx"
    base, duck, r = edl.get("music_volume", 0.30), edl.get("music_duck", 0.08), 0.5
    # smooth duck envelope: 1 inside speech windows, linear ramps of r seconds
    terms = [f"clip(min((t-{a:.2f}+{r})/{r},({b:.2f}+{r}-t)/{r}),0,1)" for a, b in _speech_windows(edl)]
    sp = "min(1," + "+".join(terms) + ")" if terms else "0"
    vol = f"{base}-({base - duck})*{sp}"
    # sample-count timestamps: with looped inputs amix can emit frames whose PTS make the
    # per-frame duck expression evaluate to silence at random (seen as whole-bed dead air)
    chain.append(f"[{cur}]atrim=0:{total:.3f},asetpts=N/SR/TB,volume='{vol}':eval=frame,"
                 f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(0, total - 5):.3f}:d=5[out]")
    script = os.path.join(workdir, "music_filter.txt")
    with open(script, "w") as f:
        f.write(";".join(chain))
    _run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex_script", script, "-map", "[out]",
          "-c:a", "pcm_s16le", out_wav])
    return True


def _version_preview(edit, out, keep=3):
    """Hardlink the new preview as previews/preview-<time>.mp4 so a page that is still playing an
    older version keeps streaming it (overwriting one path broke playback mid-watch)."""
    vdir = os.path.join(edit, "previews")
    os.makedirs(vdir, exist_ok=True)
    name = time.strftime("preview-%Y%m%d-%H%M%S.mp4")
    dst = os.path.join(vdir, name)
    try:
        os.link(out, dst)
    except OSError:
        shutil.copy2(out, dst)
    for old in sorted(f for f in os.listdir(vdir) if f.startswith("preview-"))[:-keep]:
        try:
            os.remove(os.path.join(vdir, old))
        except OSError:
            pass
    return name


def render(project, mode):
    edl = E.load(project)
    from .lint import check as _lint
    errors, warns = _lint(edl)
    for m in warns:
        print("[lint] " + m, flush=True)
    if errors:
        raise SystemExit("EDL errors (fix before rendering):\n" + "\n".join(errors))
    edit = E.edit_dir(project)
    status = Status(os.path.join(edit, "render_status.json"))
    fps_str = edl.get("output", {}).get("fps", "30000/1001")
    fps = float(Fraction(fps_str))
    preset = PRESETS["final" if mode == "final" else "preview"]
    if mode == "package":
        preset = PRESETS["final"]
    cache = os.path.join("/tmp/yt-editor", os.path.basename(E.project_dir(project)),
                         f"seg_{preset['w']}{'_clean' if mode == 'package' else ''}")
    os.makedirs(cache, exist_ok=True)
    shots = E.active_shots(edl)
    try:
        status.set(state="running", step=f"渲染镜头 0/{len(shots)}", progress=0.0, mode=mode)
        done = [0]

        def job(s):
            r = render_segment(edl, s, fps_str, preset, cache, clean=(mode == "package"))
            done[0] += 1
            status.set(state="running", step=f"渲染镜头 {done[0]}/{len(shots)}",
                       progress=0.8 * done[0] / len(shots), mode=mode)
            return r

        with ThreadPoolExecutor(max_workers=E.jobs(3)) as ex:
            segs = list(ex.map(job, shots))

        if mode == "package":
            pkg = os.path.join(edit, "package")
            shutil.rmtree(pkg, ignore_errors=True)
            os.makedirs(pkg)
            for i, ((v, a), s) in enumerate(zip(segs, shots), 1):
                _run(["ffmpeg", "-v", "error", "-y", "-i", v, "-i", a, "-c:v", "copy", "-c:a", "aac",
                      "-b:a", "256k", os.path.join(pkg, f"{i:03d}_{s['clip']}.mp4")])
            with open(os.path.join(pkg, "captions.srt"), "w", encoding="utf-8") as f:
                f.write(E.to_srt(E.timeline_subs(edl)))
            status.set(state="done", step="素材包已导出", progress=1.0, output=pkg, mode=mode)
            return pkg

        # timeline math uses frame-quantized durations, same as the segments
        for s in shots:
            s["_qdur"] = frames_of(s, fps) / fps
        total = sum(s["_qdur"] for s in shots)
        work = os.path.join(cache, "_mix")
        os.makedirs(work, exist_ok=True)
        with open(os.path.join(work, "v.txt"), "w") as f:
            f.writelines(f"file '{v}'\n" for v, _ in segs)
        with open(os.path.join(work, "a.txt"), "w") as f:
            f.writelines(f"file '{a}'\n" for _, a in segs)
        status.set(state="running", step="拼接", progress=0.82, mode=mode)
        _run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{work}/v.txt",
              "-c", "copy", f"{work}/video.mp4"])
        _run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{work}/a.txt",
              "-c", "pcm_s16le", f"{work}/voice.wav"])
        status.set(state="running", step="配乐 + 混音", progress=0.88, mode=mode)
        vo_info = mix_voiceover(dict(edl, shots=shots, _order=[s["id"] for s in edl["shots"]]), f"{work}/voice.wav", total)
        music_bed(dict(edl, shots=shots, _order=[s["id"] for s in edl["shots"]]), total, work, f"{work}/music.wav")
        if mode == "final":
            out = os.path.join(E.project_dir(project), "02 - Export", os.path.basename(E.project_dir(project)) + ".mov")
        else:
            out = os.path.join(edit, "preview.mp4")
        tmp = out + ".part.mp4"
        _run(["ffmpeg", "-v", "error", "-y", "-i", f"{work}/voice.wav", "-i", f"{work}/music.wav",
              "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0:duration=first", "-c:a", "pcm_f32le",
              f"{work}/mix.wav"])
        status.set(state="running", step="母带（响度 + 真峰值）", progress=0.94, mode=mode)
        if edl.get("master") == "loudnorm":  # legacy chain (dynamic loudnorm + blind limiter), kept as a fallback
            master = _master_loudnorm(f"{work}/mix.wav", f"{work}/master.m4a")
        else:
            master = _master(f"{work}/mix.wav", f"{work}/master.m4a")
        _run(["ffmpeg", "-v", "error", "-y", "-i", f"{work}/video.mp4", "-i", f"{work}/master.m4a",
              "-map", "0:v", "-map", "1:a", "-c", "copy", "-movflags", "+faststart",
              "-f", "mov" if out.endswith(".mov") else "mp4", tmp])
        os.replace(tmp, out)
        if mode != "final":
            _version_preview(edit, out)
        with open(os.path.join(edit, "captions.srt"), "w", encoding="utf-8") as f:
            f.write(E.to_srt(E.timeline_subs(dict(edl, shots=shots))))
        status.set(state="done", step=f"完成 {int(total // 60)}:{int(total % 60):02d}", progress=1.0,
                   output=out, mode=mode, duration=total, audio=dict(master, voiceover=vo_info or None))
        return out
    except Exception as e:
        status.set(state="error", step="渲染失败", error=str(e)[-2000:], progress=0.0, mode=mode)
        raise


# ---- mastering ----------------------------------------------------------------------------------
# Measured linear gain to -14 LUFS, a 4x-oversampled lookahead limiter, AAC encode, then the true
# peak of the *decoded AAC* is measured and the loop corrects the ceiling / gain (research R1,
# 2026-10-01). The old two-pass loudnorm never ran linear on our material (TP never fitted), so it
# fell back to dynamic mode: an AGC that reshaped every mix, and AAC overshoot left 102/104 at
# -1.2 / -1.4 dBTP.
MASTER_I = -14.0          # LUFS, integrated
MASTER_TP = -1.5          # dBTP, measured on the decoded AAC
MASTER_I_TOL = 0.3        # LU
MASTER_CEIL0 = -2.5       # dBFS limiter ceiling (at 4x oversampling): first guess
MASTER_CEIL_MIN = -6.0    # never squash harder than this
MASTER_MARGIN = 0.2       # extra dB taken off the ceiling on top of the measured TP excess
MASTER_ITERS = 4


def _aac():
    """AudioToolbox AAC when this ffmpeg has it (macOS), else ffmpeg's native encoder. On 102's
    limited montage music the native encoder overshot the limiter ceiling by +1.7 to +4.4 dB (true
    peak up to +2.3 dBTP from a -2.5 dBFS ceiling) and lowering the ceiling made it worse; aac_at
    stayed within +0.4 dB on the same audio, sample-aligned (no extra delay)."""
    if not hasattr(_aac, "codec"):
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        _aac.codec = ["-c:a", "aac_at" if re.search(r"^\s*A\S*\s+aac_at\s", enc, re.M) else "aac", "-b:a", "320k"]
    return _aac.codec


def _measure(path):
    """{'I', 'TP', 'LRA'} of an audio/video file (EBU R128, true peak at 4x oversampling)."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn", "-af",
                          "ebur128=peak=true:framelog=quiet", "-f", "null", "-"],
                         capture_output=True, text=True).stderr

    def last(pat):
        v = re.findall(pat, err, re.M)
        if not v:
            raise RuntimeError(f"ebur128 measurement failed for {path}:\n{err[-800:]}")
        return float(v[-1])
    return {"I": last(r"^\s+I:\s+(-?[\d.]+|-inf) LUFS"), "TP": last(r"^\s+Peak:\s+(-?[\d.]+|-inf) dBFS"),
            "LRA": last(r"^\s+LRA:\s+(-?[\d.]+) LU")}


def master_step(gain, ceil, I, TP, slope=1.0, target=MASTER_I, tp_max=MASTER_TP, tol=MASTER_I_TOL):
    """One correction of the mastering loop -> (gain_db, ceil_db, done).
    TP over the limit: lower the ceiling by the excess + MASTER_MARGIN (AAC overshoot was bigger than
    the margin we left). Loudness off by more than `tol`: move the gain by the error (the limiter ate
    some loudness, or the lower ceiling did), divided by `slope` = measured LU per dB of gain (1 for a
    linear chain, less once the limiter is working hard). Both can happen in one step."""
    done = True
    if TP > tp_max:
        ceil = max(MASTER_CEIL_MIN, ceil - (TP - tp_max) - MASTER_MARGIN)
        done = False
    if abs(I - target) > tol:
        gain += (target - I) / min(1.0, max(0.25, slope))
        done = False
    return round(gain, 2), round(ceil, 2), done


def master_slope(attempts):
    """LU of output loudness per dB of gain, from the last two attempts (1.0 until there are two)."""
    if len(attempts) < 2 or attempts[-1]["gain"] == attempts[-2]["gain"]:
        return 1.0
    a, b = attempts[-2], attempts[-1]
    return (b["I"] - a["I"]) / (b["gain"] - a["gain"])


def master_pick(attempts, target=MASTER_I, tp_max=MASTER_TP):
    """Best attempt when the loop ran out of iterations: one that meets the TP limit and is closest to
    the target loudness; if none does, the one with the lowest TP."""
    ok = [a for a in attempts if a["TP"] <= tp_max]
    if ok:
        return min(ok, key=lambda a: abs(a["I"] - target))
    return min(attempts, key=lambda a: a["TP"])


def _master_af(gain, ceil):
    lim = 10 ** (ceil / 20)
    # stays float into the encoder (Apple Digital Masters); latency=1 keeps A/V sync sample-exact
    return (f"volume={gain:.2f}dB,aresample=192000,"
            f"alimiter=limit={lim:.5f}:attack=1:release=80:level=false:latency=1,aresample={SR}")


def _master(mix_wav, out_m4a, codec=None):
    """Master `mix_wav` into `out_m4a` (AAC). Returns the stats written to render_status.json."""
    codec = codec or _aac()
    m0 = _measure(mix_wav)
    gain, ceil = round(MASTER_I - m0["I"], 2), MASTER_CEIL0
    attempts = []
    for it in range(1, MASTER_ITERS + 1):
        path = f"{out_m4a}.try{it}.m4a"
        _run(["ffmpeg", "-v", "error", "-y", "-i", mix_wav, "-af", _master_af(gain, ceil), "-vn", *codec, path])
        m = _measure(path)
        attempts.append(dict(m, gain=gain, ceil=ceil, path=path, iter=it))
        print(f"[master] try {it}: gain {gain:+.2f} dB, ceiling {ceil:.2f} dBFS -> "
              f"I {m['I']:.1f} LUFS, TP {m['TP']:.1f} dBTP, LRA {m['LRA']:.1f}", flush=True)
        gain, ceil, done = master_step(gain, ceil, m["I"], m["TP"], master_slope(attempts))
        if done:
            break
    best = attempts[-1] if done else master_pick(attempts)
    os.replace(best["path"], out_m4a)
    for a in attempts:
        if os.path.exists(a["path"]):
            os.remove(a["path"])
    ok = best["TP"] <= MASTER_TP and abs(best["I"] - MASTER_I) <= 0.5
    return {"I": best["I"], "TP": best["TP"], "LRA": best["LRA"], "gain_db": best["gain"],
            "ceiling_db": best["ceil"], "iterations": len(attempts), "mix_I": m0["I"], "mix_TP": m0["TP"],
            "mix_LRA": m0["LRA"], "method": "linear+tp-loop", "codec": codec[1], "ok": ok}


def _master_loudnorm(mix_wav, out_m4a, codec=("-c:a", "aac", "-b:a", "320k")):
    """Legacy master (`"master": "loudnorm"` in the EDL): two-pass loudnorm (dynamic in practice)
    + a sample limiter at -2 dBFS, 4x oversampled."""
    _run(["ffmpeg", "-v", "error", "-y", "-i", mix_wav, "-af",
          f"{_loudnorm(mix_wav)},aresample=192000,alimiter=limit=0.79:attack=5:release=50:level=false,"
          f"aresample={SR},aformat=sample_fmts=s16", "-vn", *codec, out_m4a])
    m = _measure(out_m4a)
    return {"I": m["I"], "TP": m["TP"], "LRA": m["LRA"], "iterations": 1, "method": "loudnorm",
            "ok": m["TP"] <= MASTER_TP and abs(m["I"] - MASTER_I) <= 0.5}


def _loudnorm(wav, target="I=-14:TP=-1.5:LRA=11"):
    """Two-pass loudnorm filter string (legacy master only). Note: ffmpeg only runs the 2nd pass
    linearly when the measured TP fits, which it never did on our mixes, so this is dynamic (AGC)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", wav, "-af",
                        f"loudnorm={target}:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    try:
        m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
        return (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                f":offset={m['target_offset']}:linear=true")
    except (ValueError, KeyError):
        return f"loudnorm={target}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--preview", action="store_const", dest="mode", const="preview")
    g.add_argument("--final", action="store_const", dest="mode", const="final")
    g.add_argument("--package", action="store_const", dest="mode", const="package")
    a = ap.parse_args()
    out = render(a.project, a.mode or "preview")
    print(out)


if __name__ == "__main__":
    sys.exit(main())
