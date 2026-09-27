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
    "final": {"w": 3840, "h": 2160, "vb": "45M"},
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
            f"crop={w}:{h}:'(iw-{w})*{x}':'(ih-{h})*{y}'"]


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


def _render_card(edl, shot, fps_str, preset, n, dur, ov_dir, vpath, apath):
    """A generated time card ("两小时后……"): still image with a gentle push-in + optional sfx."""
    w, h = preset["w"], preset["h"]
    c = shot["card"]
    png = overlays.card(c["text"], c.get("sub", ""), w, h, ov_dir, c.get("bg", "#ffd84d"), c.get("fg", "#1f2937"))
    inputs = ["-loop", "1", "-framerate", fps_str, "-t", f"{dur + 0.2:.3f}", "-i", png,
              "-f", "lavfi", "-t", f"{dur + 0.2:.3f}", "-i", f"anullsrc=r={SR}:cl=stereo"]
    vf = _zoom_filters({"from": 1.0, "to": 1.08}, dur, w, h) + [f"fps={fps_str}"]
    if shot.get("fade_in"):
        vf.append(f"fade=t=in:st=0:d={shot['fade_in']}")
    if shot.get("fade_out"):
        vf.append(f"fade=t=out:st={max(0, dur - shot['fade_out']):.3f}:d={shot['fade_out']}")
    chains = [f"[0:v]scale={w}:{h},{','.join(vf)},format=yuv420p[v]",
              f"[1:a]atrim=0:{dur:.6f}[a0]", _sfx_chain(edl, shot, inputs, 2, dur, "a0", "a")]
    tmpv, tmpa = vpath + ".part.mp4", apath + ".part.wav"
    _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", "[v]", "-frames:v", str(n), "-an",
          "-c:v", "hevc_videotoolbox", "-b:v", preset["vb"], "-tag:v", "hvc1", "-g", "60", tmpv,
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
    key = json.dumps([shot, grade, brg, fps_str, preset, clean, 6, overlays.VERSION], sort_keys=True, ensure_ascii=False)
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
    chains.append(f"{vsrc}setpts=PTS-STARTPTS,{','.join(vf)},format=yuv420p[v0]")

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
        chains.append(f"[{k}:v]trim=0:{bd:.3f},setpts=PTS-STARTPTS+{at:.3f}/TB,{','.join(bvf)},format=yuv420p[b{k}]")
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

    gain = E.AUDIO_GAIN.get(shot.get("audio", "voice"), 1.0)
    af = [f"aresample={SR}", "aformat=channel_layouts=stereo", f"volume={gain}"]
    if fi:
        af.append(f"afade=t=in:st=0:d={fi}")
    if fo:
        af.append(f"afade=t=out:st={max(0, dur - fo):.3f}:d={fo}")
    af += ["apad", f"atrim=0:{dur:.6f}"]
    chains.append(f"{asrc}asetpts=PTS-STARTPTS,{','.join(af)}[a0]")
    k = base_inputs + len(ovs)
    chains.append(_sfx_chain(edl, shot, inputs, k, dur, "a0", "a"))

    tmpv, tmpa = vpath + ".part.mp4", apath + ".part.wav"
    _run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains),
          "-map", f"[{last}]", "-frames:v", str(n), "-an",
          "-c:v", "hevc_videotoolbox", "-b:v", preset["vb"], "-tag:v", "hvc1", "-g", "60", tmpv,
          "-map", "[a]", "-vn", "-c:a", "pcm_s16le", tmpa])
    os.replace(tmpv, vpath)
    os.replace(tmpa, apath)
    return vpath, apath


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
        path = os.path.join(E.edit_dir(edl["project"]), m["file"])
        if not os.path.exists(path):
            continue
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
        args += ["-stream_loop", "-1", "-i", path]
        fades = [] if k == 0 else [f"afade=t=in:st=0:d={xf}"]
        if k + 1 < len(secs):
            fades.append(f"afade=t=out:st={max(0, d - xf):.3f}:d={xf}")
        chain.append(f"[{k}:a]aresample={SR},aformat=channel_layouts=stereo,atrim=0:{d:.3f},"
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
    chain.append(f"[{cur}]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume='{vol}':eval=frame,"
                 f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(0, total - 5):.3f}:d=5[out]")
    script = os.path.join(workdir, "music_filter.txt")
    with open(script, "w") as f:
        f.write(";".join(chain))
    _run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex_script", script, "-map", "[out]",
          "-c:a", "pcm_s16le", out_wav])
    return True


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

        with ThreadPoolExecutor(max_workers=3) as ex:
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
            out = os.path.join(E.project_dir(project), "02 - Export", os.path.basename(E.project_dir(project)) + ".mp4")
        else:
            out = os.path.join(edit, "preview.mp4")
        tmp = out + ".part.mp4"
        _run(["ffmpeg", "-v", "error", "-y", "-i", f"{work}/video.mp4", "-i", f"{work}/voice.wav",
              "-i", f"{work}/music.wav", "-filter_complex",
              "[1:a][2:a]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5:LRA=11,"
              f"aresample={SR}[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
              "-b:a", "320k", "-movflags", "+faststart", tmp])
        os.replace(tmp, out)
        with open(os.path.join(edit, "captions.srt"), "w", encoding="utf-8") as f:
            f.write(E.to_srt(E.timeline_subs(dict(edl, shots=shots))))
        status.set(state="done", step=f"完成 {int(total // 60)}:{int(total % 60):02d}", progress=1.0,
                   output=out, mode=mode, duration=total)
        return out
    except Exception as e:
        status.set(state="error", step="渲染失败", error=str(e)[-2000:], progress=0.0, mode=mode)
        raise


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
