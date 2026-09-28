"""Render an EDL into a finished vlog.

    ./venv/bin/python -m src.editor.render "<project>" --preview   # 1080p, edit/preview.mp4
    ./venv/bin/python -m src.editor.render "<project>" --final     # 4K, 02 - Export/<project>.mp4
    ./venv/bin/python -m src.editor.render "<project>" --package   # clean numbered clips for CapCut/剪映

Pipeline: each enabled shot -> its own video-only segment (graded, scaled, overlays burned in)
plus an exact-length PCM wav; segments are cached by content hash so re-rendering after a
small edit only re-encodes the shots that changed. Segment lengths are quantized to whole
frames and audio is kept as PCM until the final mux, so 100+ cuts never drift out of sync.
Then: concat -> music bed (tracks crossfaded, ducked under speech) -> loudnorm -14 LUFS -> mux.
Also writes captions.srt (timeline-mapped) for YouTube CC.

Progress goes to edit/render_status.json for the review page.
"""
import argparse
import hashlib
import json
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


def _sfx_chain(edl, shot, inputs, k, dur, src_label, out_label):
    """Mix a shot's `sfx` ([{file, at, gain}], file relative to edit/) over its audio."""
    labels = [f"[{src_label}]"]
    chains = []
    for i, fx in enumerate(shot.get("sfx", [])):
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


def _render_card(edl, shot, fps_str, preset, n, dur, ov_dir, vpath, apath):
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
    inputs = src + ["-f", "lavfi", "-t", f"{dur + 0.2:.3f}", "-i", f"anullsrc=r={SR}:cl=stereo"]
    zoom = c.get("zoom", {"from": 1.0, "to": 1.08}) if not anim else c.get("zoom")
    vf = (_zoom_filters(zoom, dur, w, h) if zoom else []) + [f"fps={fps_str}"]
    if shot.get("fade_in"):
        vf.append(f"fade=t=in:st=0:d={shot['fade_in']}")
    if shot.get("fade_out"):
        vf.append(f"fade=t=out:st={max(0, dur - shot['fade_out']):.3f}:d={shot['fade_out']}")
    chains = [f"[0:v]scale={w}:{h},{','.join(vf)},format={_pixfmt(preset)}[v]",
              f"[1:a]atrim=0:{dur:.6f}[a0]", _sfx_chain(edl, shot, inputs, 2, dur, "a0", "a")]
    tmpv, tmpa = vpath + ".part.mp4", apath + ".part.wav"
    _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", "[v]", "-frames:v", str(n), "-an",
          *_venc(preset), tmpv,
          "-map", "[a]", "-vn", "-c:a", "pcm_s16le", tmpa])
    os.replace(tmpv, vpath)
    os.replace(tmpa, apath)
    return vpath, apath


def render_segment(edl, shot, fps_str, preset, cache, clean=False):
    """-> (video_path, wav_path) for one shot; cached by content hash."""
    fps = float(Fraction(fps_str))
    w, h = preset["w"], preset["h"]
    n = frames_of(shot, fps)
    dur = n / fps
    grade = edl.get("grades", {}).get(shot.get("grade", "default"), "")
    brg = {b.get("grade", "default"): edl.get("grades", {}).get(b.get("grade", "default"), "")
           for b in shot.get("broll", [])}
    extra = ["zoomfix"] if shot.get("zoom") else []
    if (shot.get("card") or {}).get("image"):  # re-render when the card's image/animation file changes
        ip = _card_image_path(edl, shot["card"])
        extra.append(os.path.getmtime(ip) if os.path.exists(ip) else "missing")
    key = json.dumps([shot, grade, brg, fps_str, preset, clean, 9, overlays.VERSION] + extra, sort_keys=True, ensure_ascii=False)
    hid = hashlib.sha1(key.encode()).hexdigest()[:12]
    vpath = os.path.join(cache, f"{shot['id']}_{hid}.mp4")
    apath = os.path.join(cache, f"{shot['id']}_{hid}.wav")
    if os.path.exists(vpath) and os.path.exists(apath):
        return vpath, apath

    ov_dir = os.path.join(cache, "overlays")
    if shot.get("card"):
        return _render_card(edl, shot, fps_str, preset, n, dur, ov_dir, vpath, apath)
    src = E.clip_path(edl, shot["clip"])
    span = shot["out"] - shot["in"]
    inputs = ["-ss", f"{shot['in']:.3f}", "-t", f"{span + 0.2:.3f}", "-i", src]
    chains, last = [], "v0"
    # jump-cut out skipped spans (pauses / fillers): trim each kept range and concat
    ranges = [(a - shot["in"], b - shot["in"]) for a, b in E.kept_ranges(shot)]
    if len(ranges) > 1:
        m = len(ranges)
        chains.append(f"[0:v]split={m}" + "".join(f"[vs{i}]" for i in range(m)))
        chains.append(f"[0:a]asplit={m}" + "".join(f"[as{i}]" for i in range(m)))
        for i, (a, b) in enumerate(ranges):
            chains.append(f"[vs{i}]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[vk{i}]")
            chains.append(f"[as{i}]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,"
                          f"afade=t=in:d=0.012,afade=t=out:st={max(0, b - a - 0.012):.3f}:d=0.012[ak{i}]")
        chains.append("".join(f"[vk{i}]" for i in range(m)) + f"concat=n={m}:v=1:a=0[vsrc]")
        chains.append("".join(f"[ak{i}]" for i in range(m)) + f"concat=n={m}:v=0:a=1[asrc]")
        vsrc, asrc = "[vsrc]", "[asrc]"
    else:
        vsrc, asrc = "[0:v]", "[0:a]"
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
        for m in shot.get("marks", []):
            a0, a1 = E.src_to_local(shot, m["t0"]), min(E.src_to_local(shot, m["t1"]), dur)
            if a1 - a0 > 0.1:
                ovs.append((overlays.arrow(m.get("label", ""), m["x"], m["y"], w, h, ov_dir), a0, a1, 0))
        for s in E.shot_subs(shot):
            ovs.append((overlays.subtitle(s["text"], w, h, ov_dir, s.get("kind", "speech")), s["t0"], min(s["t1"], dur), 0))
    for i, (png, t0, t1, fade) in enumerate(ovs, base_inputs):
        if fade:
            inputs += ["-loop", "1", "-framerate", fps_str, "-t", f"{t1:.3f}", "-i", png]
            chains.append(f"[{i}:v]format=rgba,fade=t=in:st=0:d={fade}:alpha=1,"
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
        ovs.append(None)  # keeps the sfx input index below in step

    gain = E.AUDIO_GAIN.get(shot.get("audio", "voice"), 1.0) if E.speed(shot) <= 1 else 0.0
    gain *= 10 ** (max(-24.0, min(12.0, float(shot.get("gain_db", 0) or 0))) / 20)  # lift a quiet speaker
    af = [f"aresample={SR}", "aformat=channel_layouts=stereo", f"volume={gain}"]
    if shot.get("denoise", edl.get("denoise_voice", False)) and shot.get("audio", "voice") == "voice":
        # boat engines / wind: cut the low rumble, then FFT denoise under the voice
        af[2:2] = ["highpass=f=140", "afftdn=nr=18:nf=-30:tn=1"]
    # 12 ms edge fades on every shot: a hard cut on a non-zero sample (wind) clicks after loudnorm
    af.append(f"afade=t=in:st=0:d={max(fi or 0, EDGE_FADE)}")
    af.append(f"afade=t=out:st={max(0, dur - max(fo or 0, EDGE_FADE)):.3f}:d={max(fo or 0, EDGE_FADE)}")
    af += ["apad", f"atrim=0:{dur:.6f}"]
    chains.append(f"{asrc}asetpts=PTS-STARTPTS,{','.join(af)}[a0]")
    k = base_inputs + len(ovs)
    chains.append(_sfx_chain(edl, shot, inputs, k, dur, "a0", "a"))

    tmpv, tmpa = vpath + ".part.mp4", apath + ".part.wav"
    _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", f"[{last}]", "-frames:v", str(n), "-an",
          *_venc(preset), tmpv,
          "-map", "[a]", "-vn", "-c:a", "pcm_s16le", tmpa])
    os.replace(tmpv, vpath)
    os.replace(tmpa, apath)
    return vpath, apath


EDGE_FADE = 0.012


def _speech_windows(edl, pad=0.35):
    iv = sorted((max(0, s["t0"] - pad), s["t1"] + pad) for s in E.timeline_subs(edl)
                if s["kind"] == "speech")  # editor notes don't duck the music
    merged = []
    for a, b in iv:
        if merged and a <= merged[-1][1] + 0.8:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def music_sections(edl, total):
    """[(path, start, end)]: each music entry starts at its `start` shot (first enabled shot at or
    after it; omitted = right after the previous section) and runs until the next section."""
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
        secs.append([path, t])
    secs.sort(key=lambda x: x[1])
    return [(p, t, secs[i + 1][1] if i + 1 < len(secs) else total) for i, (p, t) in enumerate(secs)
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


def _track_gain_db(edl, path):
    """Loudness-match every track to -14 LUFS (Audio Library tracks differ by 15+ LU), plus the
    music entry's optional manual "gain" in dB."""
    extra = next((m.get("gain", 0.0) for m in edl.get("music", [])
                  if m.get("file") and os.path.join(E.edit_dir(edl["project"]), m["file"]) == path), 0.0)
    return max(-20.0, min(12.0, -14.0 - _track_lufs(path))) + extra


def _track_in(edl, path):
    """Optional music entry "in" (s): skip a track's quiet intro."""
    return next((float(m.get("in", 0.0)) for m in edl.get("music", [])
                 if m.get("file") and os.path.join(E.edit_dir(edl["project"]), m["file"]) == path), 0.0)


def music_bed(edl, total, workdir, out_wav):
    secs = music_sections(edl, total)
    if not secs:
        _run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo",
              "-t", f"{total:.3f}", out_wav])
        return False
    xf = 2.5
    args, chain, labels = [], [], []
    for k, (path, t0, t1) in enumerate(secs):
        # each section overlaps the next by xf and crossfades; tracks loop if the section is long
        a0 = max(0.0, t0 - (xf if k else 0))
        d = min(total, t1 + (xf if k + 1 < len(secs) else 0)) - a0
        fades = [] if k == 0 else [f"afade=t=in:st=0:d={xf}"]
        if k + 1 < len(secs):
            fades.append(f"afade=t=out:st={max(0, d - xf):.3f}:d={xf}")
        if path is None:  # silent section
            args += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", f"anullsrc=r={SR}:cl=stereo"]
            gain, t_in = 0.0, 0.0
        else:
            args += ["-stream_loop", "-1", "-i", path]
            gain, t_in = _track_gain_db(edl, path), _track_in(edl, path)
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
        music_bed(dict(edl, shots=shots, _order=[s["id"] for s in edl["shots"]]), total, work, f"{work}/music.wav")
        if mode == "final":
            out = os.path.join(E.project_dir(project), "02 - Export", os.path.basename(E.project_dir(project)) + ".mov")
        else:
            out = os.path.join(edit, "preview.mp4")
        tmp = out + ".part.mp4"
        _run(["ffmpeg", "-v", "error", "-y", "-i", f"{work}/voice.wav", "-i", f"{work}/music.wav",
              "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0:duration=first", "-c:a", "pcm_s24le",
              f"{work}/mix.wav"])
        _run(["ffmpeg", "-v", "error", "-y", "-i", f"{work}/video.mp4", "-i", f"{work}/mix.wav",
              "-filter_complex", f"[1:a]{_loudnorm(f'{work}/mix.wav')},"
              # loudnorm can overshoot its TP target (-1.2 dBTP measured on ep 84): a sample
              # limiter at -2.2 dBFS leaves room for inter-sample + AAC peaks (-> about -2.0 dBTP).
              # Feed AAC s16, not float: straight from the float chain it overshot to +1.4 dBTP (ep 83).
              f"aresample={SR},alimiter=limit=0.78:attack=5:release=50:level=false,aformat=sample_fmts=s16[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
              "-b:a", "320k", "-movflags", "+faststart", "-f", "mov" if out.endswith(".mov") else "mp4", tmp])
        os.replace(tmp, out)
        if mode != "final":
            _version_preview(edit, out)
        with open(os.path.join(edit, "captions.srt"), "w", encoding="utf-8") as f:
            f.write(E.to_srt(E.timeline_subs(dict(edl, shots=shots))))
        status.set(state="done", step=f"完成 {int(total // 60)}:{int(total % 60):02d}", progress=1.0,
                   output=out, mode=mode, duration=total)
        return out
    except Exception as e:
        status.set(state="error", step="渲染失败", error=str(e)[-2000:], progress=0.0, mode=mode)
        raise


def _loudnorm(wav, target="I=-14:TP=-1.5:LRA=11"):
    """Two-pass loudnorm: measure first, then normalize linearly with the measured values.
    Single-pass (dynamic) mode undershot -14 LUFS by ~1 LU on eps 89/90 when the mix had little
    peak headroom. Falls back to single-pass if the measurement can't be parsed."""
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
