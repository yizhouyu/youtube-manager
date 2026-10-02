"""Render an EDL into a finished vlog.

    ./venv/bin/python -m src.editor.render "<project>" --preview   # 1080p, edit/preview.mp4
    ./venv/bin/python -m src.editor.render "<project>" --final     # 4K, 02 - Export/<project>.mp4
    ./venv/bin/python -m src.editor.render "<project>" --package   # clean numbered clips for CapCut/剪映

Pipeline: each enabled shot -> its own video-only segment (graded, scaled, overlays burned in)
plus a float wav (exact frame-quantized body + 30 ms source handles each side); video and audio
are cached by separate content hashes so re-rendering after a small edit only re-encodes what
changed. Video segments are concatenated; the wavs are overlap-added on the same frame-exact
timeline with equal-power crossfades across each cut, so 100+ cuts never drift out of sync and the
natural sound never drops out at a cut.
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
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import numpy as np

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
    # optional t0/t1 (rendered shot-local s): hold at `from` until t0, reach `to` at t1
    t0, t1 = z.get("t0", 0.0), z.get("t1", dur)
    p = f"clip((t-{t0:.3f})/{max(t1 - t0, 0.05):.3f},0,1)"
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
    if shot.get("tag"):  # cards carry a tag too (e.g. a trip-series day marker on the title/route card)
        td = min(3.0, dur)
        png_tag = overlays.place_tag(shot["tag"], w, h, ov_dir, shot.get("tag_pos", "tl"))
        inputs = inputs + ["-loop", "1", "-framerate", fps_str, "-t", f"{td:.3f}", "-i", png_tag]
        chains[0] = chains[0][:-3] + "[vc]"
        chains.append(f"[1:v]format=rgba,fade=t=in:st=0:d=0.3:alpha=1,"
                      f"fade=t=out:st={max(0, td - 0.3):.3f}:d=0.3:alpha=1[tg]")
        chains.append(f"[vc][tg]overlay=0:0:eof_action=pass,format={_pixfmt(preset)}[v]")
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


# ---- R4: dialogue levelling at render time ----------------------------------------------------------
# On-camera speech varies 5-9 LU between shots (a distant guide vs the creator at arm's length). The
# old dynamic-loudnorm master hid some of that as an AGC; the linear master doesn't. So each voice
# shot's caption-window speech loudness is measured (after its denoise and manual gain_db), and a
# shot further than LEVEL_DEADBAND LU from the episode median is pulled to the edge of that band,
# within LEVEL_MIN..LEVEL_MAX dB. Nothing is written to the EDL; the plan is in render_status.json.
# Opt out: shot "level": false, or EDL "dialogue_level": false.
LEVEL_VERSION = 1
LEVEL_DEADBAND = 3.0      # LU around the median that is left alone (natural variation)
LEVEL_MIN, LEVEL_MAX = -6.0, 8.0
LEVEL_MIN_SPEECH = 1.0    # s of captioned speech needed to measure a shot


def level_corrections(meas, deadband=LEVEL_DEADBAND, lo=LEVEL_MIN, hi=LEVEL_MAX):
    """meas: {shot_id: (lufs, speech_seconds)} -> (median, {shot_id: correction_db}). The median is
    weighted by speech seconds; a shot outside median +- deadband is moved to the band's edge,
    clamped to [lo, hi]. Shots inside the band get 0."""
    pts = sorted((l, w) for l, w in meas.values() if l is not None and w > 0)
    if not pts:
        return None, {}
    half, acc, med = sum(w for _l, w in pts) / 2, 0.0, pts[-1][0]
    for l, w in pts:
        acc += w
        if acc >= half:
            med = l
            break
    out = {}
    for sid, (l, w) in meas.items():
        if l is None or w <= 0:
            continue
        d = l - med
        c = -(d - deadband) if d > deadband else (-(d + deadband) if d < -deadband else 0.0)
        out[sid] = round(max(lo, min(hi, c)), 1)
    return med, out


def _speech_windows_src(shot, exclude_local=()):
    """Caption windows of a shot as SOURCE-time spans clipped to [in, out], skipping notes and
    captions that overlap `exclude_local` (shot-local spans: narration placed over the shot)."""
    wins = []
    for x in shot.get("subs", []):
        if x.get("kind", "speech") != "speech" or x.get("text", "").strip().startswith("※"):
            continue
        a, b = max(x["t0"], shot["in"]), min(x["t1"], shot["out"])
        if b - a < 0.3:
            continue
        la, lb = E.src_to_local(shot, a), E.src_to_local(shot, b)
        if any(la < eb and ea < lb for ea, eb in exclude_local):
            continue
        wins.append((a, b))
    return sorted(wins)


def measure_shot_speech(edl, shot, cache, exclude_local=()):
    """(lufs, speech_seconds) of a voice shot's captioned speech after its clean-up filters and
    manual gain_db (EBU-gated integrated loudness over the concatenated caption windows), or
    (None, seconds) when there is too little. Cached by content."""
    wins = _speech_windows_src(shot, exclude_local)
    secs = sum(b - a for a, b in wins)
    if secs < LEVEL_MIN_SPEECH:
        return None, secs
    manual = max(-24.0, min(12.0, float(shot.get("gain_db", 0) or 0)))
    filt = _shot_filters(edl, shot) + [f"volume={manual}dB"]
    key = json.dumps([shot["clip"], shot["in"], shot["out"], wins, filt, LEVEL_VERSION])
    path = os.path.join(cache, "_level", f"{shot['id']}_{hashlib.sha1(key.encode()).hexdigest()[:12]}.json")
    if os.path.exists(path):
        with open(path) as f:
            r = json.load(f)
        return r["I"], r["secs"]
    t0 = wins[0][0]
    inputs = ["-ss", f"{t0:.3f}", "-t", f"{wins[-1][1] - t0 + 0.2:.3f}", "-i", E.clip_path(edl, shot["clip"])]
    n = len(wins)
    graph = [f"[0:a]{','.join(filt)},asplit={n}" + "".join(f"[w{i}]" for i in range(n))]
    graph += [f"[w{i}]atrim={a - t0:.3f}:{b - t0:.3f},asetpts=PTS-STARTPTS[c{i}]" for i, (a, b) in enumerate(wins)]
    graph.append("".join(f"[c{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1,ebur128=framelog=quiet")
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *inputs, "-filter_complex", ";".join(graph),
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    v = re.findall(r"^\s+I:\s+(-?[\d.]+|-inf) LUFS", err, re.M)
    lufs = float(v[-1]) if v else None
    if lufs is not None and lufs <= -69:
        lufs = None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"I": lufs, "secs": secs}, f)
    return lufs, secs


def plan_dialogue_levels(edl, shots, fps, cache):
    """Set shot["_level_db"] on the voice shots that need levelling (in place). -> summary dict for
    render_status.json, or None when levelling is off."""
    if edl.get("dialogue_level", True) is False:
        return None
    # narration over a shot: its captions are TTS, not this shot's speech
    rows, t = [], 0.0
    for s in shots:
        rows.append((s, t))
        t += frames_of(s, fps) / fps
    starts = {s["id"]: st for s, st in rows}
    tl = dict(edl, shots=shots, _order=[s["id"] for s in edl["shots"]])
    tts = [(t0, t0 + d) for _p, t0, d, _e in voiceover_spans(tl) + tts_sfx_spans(tl)]
    cands = [s for s in shots if s.get("audio", "voice") == "voice" and not s.get("card") and E.speed(s) == 1
             and s.get("level", True) is not False]

    def one(s):
        st = starts[s["id"]]
        excl = [(a - st, b - st) for a, b in tts if a < st + frames_of(s, fps) / fps and b > st]
        return s["id"], measure_shot_speech(edl, s, cache, excl)

    with ThreadPoolExecutor(max_workers=E.jobs(3)) as ex:
        meas = dict(ex.map(one, cands))
    med, corr = level_corrections(meas)
    for s in shots:
        s.pop("_level_db", None)
        if corr.get(s["id"]):
            s["_level_db"] = corr[s["id"]]
    moved = {k: v for k, v in corr.items() if v}
    if med is not None:
        print(f"[level] speech median {med:.1f} LUFS over {len(corr)} shots; levelled {len(moved)}: "
              + ", ".join(f"{k} {v:+.1f}" for k, v in sorted(moved.items())), flush=True)
    return {"median": med, "measured": len(corr), "deadband": LEVEL_DEADBAND,
            "shots": {k: {"I": meas[k][0], "db": v} for k, v in corr.items()}}


# Segment cache versions. Video and audio are cached separately, so an audio-only change re-renders
# a few seconds of PCM per shot instead of every shot's picture. Bump the matching one whenever the
# segment output changes without the shot dict changing.
VIDEO_CACHE_VERSION = 9
AUDIO_CACHE_VERSION = 3


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
    norot = set(edl.get("noautorotate", []))
    used = {shot.get("clip")} | {b.get("clip") for b in shot.get("broll", [])} | {p.get("clip") for p in shot.get("pip", [])}
    if norot & used:  # decoding without the display matrix changes the picture: re-render
        extra.append(["noautorotate", sorted(norot & used)])
    for pp in shot.get("pip", []):  # re-render when a pip file (e.g. a mini-map animation) changes
        if pp.get("file"):
            fp = os.path.join(E.edit_dir(edl["project"]), pp["file"])
            extra.append(os.path.getmtime(fp) if os.path.exists(fp) else "missing")
    if (shot.get("card") or {}).get("image"):  # re-render when the card's image/animation file changes
        ip = _card_image_path(edl, shot["card"])
        extra.append(os.path.getmtime(ip) if os.path.exists(ip) else "missing")
    vshot = {k: v for k, v in shot.items() if k != "_level_db"}   # audio-only field: keep the video cache
    key = json.dumps([vshot, grade, brg, fps_str, preset, clean, VIDEO_CACHE_VERSION, overlays.VERSION] + extra,
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
    inputs = [*E.input_args(edl, shot["clip"]), "-ss", f"{shot['in']:.3f}", "-t", f"{span + 0.2:.3f}", "-i", src]
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
        k = inputs.count("-i")  # index of the input appended below
        inputs += [*E.input_args(edl, b["clip"]), "-ss", f"{b['in']:.3f}", "-t", f"{bd + 0.2:.3f}", "-i",
                   E.clip_path(edl, b["clip"])]
        bvf = [f"scale={w}:{h}:flags=lanczos", f"fps={fps_str}"]
        if grades.get(b.get("grade", "default")):
            bvf.append(grades[b.get("grade", "default")])
        chains.append(f"[{k}:v]trim=0:{bd:.3f},setpts=PTS-STARTPTS+{at:.3f}/TB,{','.join(bvf)},format={_pixfmt(preset)}[b{k}]")
        chains.append(f"[{last}][b{k}]overlay=0:0:eof_action=pass:enable='between(t,{at:.3f},{at + bd:.3f})'[vb{k}]")
        last = f"vb{k}"
    base_inputs = inputs.count("-i")

    ovs = []  # (png, t0, t1, fade)
    if not clean:
        if shot.get("title"):
            t = shot["title"]
            td = min(t.get("dur", 3.0), dur)
            ovs.append((overlays.title_card(t["text"], t.get("sub", ""), w, h, ov_dir), 0, td, 0.4))
        if shot.get("tag"):
            ovs.append((overlays.place_tag(shot["tag"], w, h, ov_dir, shot.get("tag_pos", "tl")), 0, min(3.0, dur), 0.3))
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
            ovs.append((overlays.subtitle(s["text"], w, h, ov_dir, s.get("kind", "speech"), s.get("pos", "bottom")), s["t0"], min(s["t1"], dur), 0))
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


# ---- dialogue / natural-sound track: handles + equal-power crossfades (research R11-lite) ----------
# Every shot's wav carries HANDLE s of real source sound before and after its body (when the source
# has it; cards and muted shots have silent handles). The assembler overlap-adds the shots on the
# timeline with an equal-power (sin/cos) crossfade across each cut, so the ambience bed never drops
# out. The old 12 ms fade-out + 12 ms fade-in left a ~24 ms hole at every cut and skip join.
# Bodies still start exactly on their frame-quantized timeline position: video cuts and sync are
# unchanged, the crossfade just straddles the cut (half before, half after).
XF_CUT = 0.06             # s, crossfade window at a shot cut (HANDLE on each side)
HANDLE = XF_CUT / 2
XF_SKIP = 0.04            # s, crossfade at a `skip` join inside a shot
EDGE_FADE = 0.012         # s, fallback fades where no handle exists on either side
_HS = int(round(HANDLE * SR))


def eq_power(n):
    """(fade_out, fade_in) gain curves of n samples: cos/sin quarter waves, out**2 + in**2 == 1."""
    u = (np.arange(n, dtype=np.float64) + 0.5) / max(n, 1)
    return np.cos(u * np.pi / 2).astype(np.float32), np.sin(u * np.pi / 2).astype(np.float32)


def join_xfade(skip_len, left_len, right_len, d=XF_SKIP):
    """Crossfade length (s) at a skip join: at most `d`, the skipped span (each side reaches d/2 into
    it, so the two extensions never overlap) and either kept piece (fades stay inside it)."""
    return max(0.0, min(d, skip_len, left_len, right_len))


def cut_window(post_a, pre_b, body_a, body_b):
    """Samples (before, after) the cut that the crossfade spans: the incoming shot's pre-handle
    reaches `before` samples back under the outgoing shot, whose post-handle reaches `after`
    samples past the cut. Clamped to half of each body so neighbouring windows never overlap."""
    return min(pre_b, body_a // 2), min(post_a, body_b // 2)


def _read_f32(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def _write_f32(path, x):
    """Write a float32 stereo WAV (WAVE_FORMAT_IEEE_FLOAT)."""
    x = np.ascontiguousarray(x, dtype="<f4")
    data = x.tobytes()
    hdr = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
           struct.pack("<IHHIIHH", 16, 3, 2, SR, SR * 8, 8, 32) + b"data" + struct.pack("<I", len(data)))
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(data)


_SFX_CACHE = {}


def _sfx_audio(path):
    key = (path, os.path.getmtime(path))
    if key not in _SFX_CACHE:
        _SFX_CACHE[key] = _read_f32(path)
    return _SFX_CACHE[key]


def render_segment_audio(edl, shot, fps_str, cache):
    """Float wav for one shot = [HANDLE s pre-handle | body | HANDLE s post-handle] (its own sound +
    sfx), plus `<wav>.json` = {"pre", "post": usable handle samples, "body": body samples}. Cached by
    content hash. The body is exactly the shot's frame-quantized length."""
    fps = float(Fraction(fps_str))
    dur = frames_of(shot, fps) / fps
    fx_files = [os.path.join(E.edit_dir(edl["project"]), fx["file"]) for fx in shot.get("sfx", [])]
    extra = [os.path.getmtime(f) if os.path.exists(f) else "missing" for f in fx_files]
    key = json.dumps([shot, fps_str, AUDIO_CACHE_VERSION, edl.get("denoise_voice", False), _tts_chain_on(edl),
                      XF_CUT, XF_SKIP] + extra, sort_keys=True, ensure_ascii=False)
    hid = hashlib.sha1(key.encode()).hexdigest()[:12]
    apath = os.path.join(cache, f"{shot['id']}_a{hid}.wav")
    if os.path.exists(apath) and os.path.exists(apath + ".json"):
        return apath
    L = int(round(dur * SR))
    fi, fo = float(shot.get("fade_in", 0) or 0), float(shot.get("fade_out", 0) or 0)
    gain = E.AUDIO_GAIN.get(shot.get("audio", "voice"), 1.0) if E.speed(shot) <= 1 else 0.0
    gain *= 10 ** (shot_gain_db(shot) / 20)  # manual lift of a quiet speaker + dialogue levelling (R4)
    if shot.get("card") or gain <= 0:
        out = np.zeros((_HS + L + _HS, 2), np.float32)    # silence, with silent (= usable) handles
        pre = post = _HS
    else:
        out, pre, post = _shot_sound(edl, shot, gain, L)
    if fi:   # explicit fades (from/to black) fade the sound too; no handle across them
        n = min(L, int(round(fi * SR)))
        out[_HS:_HS + n] *= np.linspace(0, 1, n, dtype=np.float32)[:, None]
        out[:_HS] = 0
        pre = 0
    if fo:
        n = min(L, int(round(fo * SR)))
        out[_HS + L - n:_HS + L] *= np.linspace(1, 0, n, dtype=np.float32)[:, None]
        out[_HS + L:] = 0
        post = 0
    for fx in shot.get("sfx", []):   # sound effects (shot-local `at`), cut at the end of the post-handle
        if _tts_chain_on(edl) and is_tts_sfx(fx):
            continue                  # narration lines: mix_voiceover places them
        path = os.path.join(E.edit_dir(edl["project"]), fx["file"])
        if not os.path.exists(path):
            continue
        y = _sfx_audio(path) * float(fx.get("gain", 0.8))
        at = _HS + int(round(float(fx.get("at", 0)) * SR))
        n = max(0, min(len(y), len(out) - at))
        out[at:at + n] += y[:n]
    tmpa = apath + ".part.wav"
    _write_f32(tmpa, out)
    with open(apath + ".json", "w") as f:
        json.dump({"pre": int(pre), "post": int(post), "body": L, "handle": _HS}, f)
    os.replace(tmpa, apath)
    return apath


def _shot_filters(edl, shot):
    """Resample + the shot's clean-up filters (denoise / wind), everything before its gain."""
    af = [f"aresample={SR}", "aformat=sample_fmts=flt:channel_layouts=stereo"]
    mode = shot.get("denoise", edl.get("denoise_voice", False))
    if mode == "wind":
        # heavy wind on an action cam: a higher cut + stronger FFT denoise; ambient beds also get
        # tamed (and a touch quieter) so the music carries them instead of the roar
        if shot.get("audio", "voice") == "voice":
            af += ["highpass=f=200", "afftdn=nr=24:nf=-28:tn=1", "equalizer=f=3000:t=q:w=1:g=2"]
        elif shot.get("audio") == "ambient":
            af += ["highpass=f=250", "afftdn=nr=20:nf=-30:tn=1", "volume=0.6"]
    elif mode and shot.get("audio", "voice") == "voice":
        # boat engines / wind: cut the low rumble, then FFT denoise under the voice
        af += ["highpass=f=140", "afftdn=nr=18:nf=-30:tn=1"]
    return af


def shot_gain_db(shot):
    """A shot's total level change: manual `gain_db` (-24..+12) + the render-time dialogue levelling
    (`_level_db`, set by plan_dialogue_levels)."""
    return max(-24.0, min(12.0, float(shot.get("gain_db", 0) or 0))) + float(shot.get("_level_db", 0) or 0)


def _shot_sound(edl, shot, gain, L):
    """The shot's own sound: one decode of the source span plus handles, through the shot's filters
    (denoise, gain, R3 peak guard), then the kept ranges joined with equal-power crossfades."""
    t0 = max(0.0, shot["in"] - HANDLE)
    src_pre = int(round((shot["in"] - t0) * SR))           # handle samples that exist before `in`
    span = shot["out"] - shot["in"]
    inputs = ["-ss", f"{t0:.4f}", "-t", f"{span + 2 * HANDLE + 0.3:.4f}", "-i", E.clip_path(edl, shot["clip"])]
    af = _shot_filters(edl, shot) + [f"volume={gain}"]
    if shot_gain_db(shot) > 0:
        af += peak_guard(_measure_span(inputs, f"[0:a]asetpts=PTS-STARTPTS,{','.join(af)}")["I"])
    raw = subprocess.run(["ffmpeg", "-v", "error", *inputs, "-af", ",".join(af), "-f", "f32le", "-ac", "2", "-"],
                         capture_output=True)
    if raw.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {shot['id']} audio:\n{raw.stderr.decode()[-1500:]}")
    reg = np.frombuffer(raw.stdout, np.float32).reshape(-1, 2)
    idx = lambda t: src_pre + int(round((t - shot["in"]) * SR))   # noqa: E731  source s -> region sample

    def take(a, b):   # region samples [a, b), zero-padded past either end
        y = np.zeros((b - a, 2), np.float32)
        lo, hi = max(a, 0), min(b, len(reg))
        if hi > lo:
            y[lo - a:hi - a] = reg[lo:hi]
        return y

    ranges = E.kept_ranges(shot)
    if E.speed(shot) != 1:   # slow motion keeps 1x sound (as before): play the kept ranges, pad/trim
        body = np.concatenate([take(idx(a), idx(b)) for a, b in ranges])[:L]
        body = np.concatenate([body, np.zeros((L - len(body), 2), np.float32)])
        return np.concatenate([np.zeros((_HS, 2), np.float32), body, np.zeros((_HS, 2), np.float32)]), 0, 0
    # crossfade length at each join (s) -> extension of each piece into the skipped span on each side
    xf = [join_xfade(ranges[i + 1][0] - ranges[i][1], ranges[i][1] - ranges[i][0],
                     ranges[i + 1][1] - ranges[i + 1][0]) for i in range(len(ranges) - 1)]
    ext = [int(round(d * SR / 2)) for d in xf]
    cores = [idx(b) - idx(a) for a, b in ranges]
    cores[-1] += L - sum(cores)   # body = exactly L samples: the last piece runs on (or stops) in the source
    out = np.zeros((_HS + L + _HS, 2), np.float32)
    pos = _HS
    for i, (a, _b) in enumerate(ranges):
        s0 = idx(a)
        left = ext[i - 1] if i else _HS           # first piece: its left extension is the pre-handle
        right = ext[i] if i < len(ranges) - 1 else _HS
        y = take(s0 - left, s0 + cores[i] + right)
        if i:
            y[:2 * left] *= eq_power(2 * left)[1][:, None]
        if i < len(ranges) - 1:
            y[len(y) - 2 * right:] *= eq_power(2 * right)[0][:, None]
        out[pos - left:pos - left + len(y)] += y
        pos += cores[i]
    pre = min(_HS, src_pre)
    post = int(max(0, min(_HS, len(reg) - (idx(ranges[-1][0]) + cores[-1]))))
    out[:_HS - pre] = 0
    out[_HS + L + post:] = 0
    return out, pre, post


def assemble_dialogue(seg_wavs, starts, total, out_wav):
    """Overlap-add the shots' wavs onto the timeline: body i starts at round(starts[i] * SR), and each
    cut gets an equal-power crossfade across the handles the two sides have (cut_window). Where
    neither side has one (e.g. both at a clip boundary), fall back to EDGE_FADE out/in fades.
    -> [(cut_time_s, crossfade_samples)] for QA."""
    N = int(round(total * SR))
    out = np.zeros((N, 2), np.float32)
    meta = []
    for p in seg_wavs:
        with open(p + ".json") as f:
            meta.append(json.load(f))
    b0 = [int(round(t * SR)) for t in starts] + [N]
    body = [b0[i + 1] - b0[i] for i in range(len(seg_wavs))]
    # (before, after) window of each cut i (between shot i-1 and i)
    win = [(0, 0)] + [cut_window(meta[i - 1]["post"], meta[i]["pre"], body[i - 1], body[i])
                      for i in range(1, len(seg_wavs))]
    win.append((0, 0))
    report = []
    edge = int(round(EDGE_FADE * SR))
    for i, p in enumerate(seg_wavs):
        x = _read_f32(p)
        h = meta[i]["handle"]
        bef_l, aft_l = win[i]            # window at this shot's start
        bef_r, aft_r = win[i + 1]        # window at this shot's end
        a = h - bef_l                    # first sample used (in this wav)
        e = h + body[i] + aft_r          # one past the last sample used
        y = x[a:e].copy()
        if len(y) < e - a:
            y = np.concatenate([y, np.zeros((e - a - len(y), 2), np.float32)])
        n_in, n_out = bef_l + aft_l, bef_r + aft_r
        if i and n_in:
            y[:n_in] *= eq_power(n_in)[1][:, None]
        elif n_in == 0:                   # no handles at this cut (or the very start): short fade-in
            y[:edge] *= np.linspace(0, 1, min(edge, len(y)), dtype=np.float32)[:, None]
        if i + 1 < len(seg_wavs) and n_out:
            y[len(y) - n_out:] *= eq_power(n_out)[0][:, None]
        elif n_out == 0:
            k = min(edge, len(y))
            y[len(y) - k:] *= np.linspace(1, 0, k, dtype=np.float32)[:, None]
        t = b0[i] - bef_l
        lo, hi = max(t, 0), min(t + len(y), N)
        out[lo:hi] += y[lo - t:hi - t]
        if i:
            report.append((b0[i] / SR, n_in))
    _write_f32(out_wav, out)
    return report




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
        inputs += [*E.input_args(edl, pp["clip"]), "-ss", f"{float(pp.get('in', 0.0)):.3f}", "-t",
                   f"{span * k + 0.3:.3f}", "-i", E.clip_path(edl, pp["clip"])]
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
    """Median on-camera speech loudness of the dialogue track: each speech caption's loudness (power
    mean of the momentary loudness inside it), then the median over captions. Captions that overlap
    `exclude` spans (the narration's own captions) are skipped. Falls back to SPEECH_REF_FALLBACK
    with fewer than 3 usable captions. -> (lufs, n_captions)."""
    wins = [(s["t0"], s["t1"]) for s in E.timeline_subs(edl) if s["kind"] == "speech" and s["t1"] - s["t0"] > 0.8
            and not any(s["t0"] < b and a < s["t1"] for a, b in exclude)]
    if len(wins) < 3:
        return SPEECH_REF_FALLBACK, len(wins)
    t, m = _momentary(voice_wav)
    per = []
    for a, b in wins:
        v = power_mean_lufs([mm for tt, mm in zip(t, m) if a + 0.4 <= tt <= b])
        if v is not None:
            per.append(v)
    if len(per) < 3:
        return SPEECH_REF_FALLBACK, len(per)
    per.sort()
    return (per[len(per) // 2] + per[(len(per) - 1) // 2]) / 2, len(per)


def vo_gain_db(entry, line_lufs, speech_ref, offset=VO_OFFSET_LU, trim=0.0):
    """Gain for one processed TTS line: the entry's manual `gain_db` if set, else level-matched to
    the on-camera speech reference + offset + trim (clamped to +-24 dB)."""
    if entry.get("gain_db") is not None:
        return float(entry["gain_db"]), False
    return max(-24.0, min(24.0, speech_ref + offset + trim - line_lufs)), True


def legacy_trims(gains_db):
    """Per-line trims from the pre-auto fixed gains: each line's difference from the episode's
    median gain. The common part (e.g. +4.5 dB on every line, which only compensated the files'
    -18 LUFS level) is replaced by auto levelling; a deliberate difference between lines (98's
    gorge line +6 vs +1.6 over loud rapids) is kept."""
    vals = sorted(g for g in gains_db if g is not None)
    if not vals:
        return [0.0 for _ in gains_db]
    med = (vals[len(vals) // 2] + vals[(len(vals) - 1) // 2]) / 2
    return [0.0 if g is None else g - med for g in gains_db]


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
    # legacy fixed gains -> relative trims (voiceover: dB; TTS sfx: linear)
    trims = legacy_trims([float(e["gain"]) if isinstance(e.get("gain"), (int, float)) else None for *_x, e in vo]) + \
        legacy_trims([20 * math.log10(max(1e-3, float(e["gain"]))) if isinstance(e.get("gain"), (int, float)) else None
                      for *_x, e in fx])
    for k, (path, t0, d, entry) in enumerate(spans, 1):
        if chain_on:
            src, line_i = tts_processed(path, tts_cache)
            gain, auto = vo_gain_db(entry, line_i, ref, offset, trims[k - 1])
            info["lines"].append({"file": entry.get("file"), "t0": round(t0, 2), "line_I": line_i,
                                  "gain_db": round(gain, 2), "auto": auto, "trim_db": round(trims[k - 1], 2)})
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
          "-c:a", "pcm_f32le", tmp])
    os.replace(tmp, voice_wav)
    return info


def _speech_windows(edl, pad=0.35):
    iv = sorted((max(0, s["t0"] - pad), s["t1"] + pad) for s in E.timeline_subs(edl)
                if s["kind"] == "speech")  # editor notes don't duck the music
    # narration ducks the music too, whether or not its caption is on a shot (cards draw no subtitles)
    iv = sorted(iv + [(max(0, t0 - pad), t0 + d + pad) for _p, t0, d, _e in voiceover_spans(edl)])
    # ...and so do TTS lines placed as a shot's sfx: their caption is a note (white subtitles carry
    # real speech only), so without this the music would play at full level under them
    rows, _ = E.timeline(edl)
    for s, st in rows:
        for fx in s.get("sfx", []):
            path = os.path.join(E.edit_dir(edl["project"]), fx.get("file", ""))
            if is_tts_sfx(fx) and os.path.exists(path):
                at = float(fx.get("at", 0.0))
                d = min(_media_dur(path), E.shot_dur(s) - at)
                if d > 0.05:
                    iv.append((max(0, st + at - pad), st + at + d + pad))
    iv.sort()
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
        level_info = None
        if mode != "package":
            status.set(state="running", step="对白响度", progress=0.0, mode=mode)
            level_info = plan_dialogue_levels(edl, shots, fps, cache)
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
                with open(a + ".json") as f:
                    m = json.load(f)
                h0 = m["handle"]  # the clip gets the body only (the handles are for the crossfades)
                _run(["ffmpeg", "-v", "error", "-y", "-i", v, "-i", a, "-map", "0:v", "-map", "[a]",
                      "-filter_complex", f"[1:a]atrim=start_sample={h0}:end_sample={h0 + m['body']}[a]",
                      "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", os.path.join(pkg, f"{i:03d}_{s['clip']}.mp4")])
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
        status.set(state="running", step="拼接", progress=0.82, mode=mode)
        _run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{work}/v.txt",
              "-c", "copy", f"{work}/video.mp4"])
        starts, t = [], 0.0
        for s in shots:
            starts.append(t)
            t += s["_qdur"]
        xfades = assemble_dialogue([a for _, a in segs], starts, total, f"{work}/voice.wav")
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
                   output=out, mode=mode, duration=total,
                   audio=dict(master, voiceover=vo_info or None, dialogue_level=level_info, cuts=len(xfades),
                              cuts_crossfaded=sum(1 for _t, n in xfades if n >= 0.02 * SR)))
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
