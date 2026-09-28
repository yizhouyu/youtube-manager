"""Edit Decision List (EDL): the single source of truth for an auto-assembled vlog.

The agent writes it, the review page edits it, the renderer reads it. Plain JSON at
`<project>/02 - Export/edit/edl.json`:

{
  "project": "NN - Trip Name",                  # project folder name (under ~/Desktop)
  "source_dir": "01 - Unedited",               # where the raw clips live (never modified)
  "output": {"width": 3840, "height": 2160, "fps": "30000/1001"},
  "grades": {"default": "<ffmpeg vf chain>", "underwater": "..."},   # named color grades
  "music": [{"file": "music/track.mp3", "start": "s001", "in": 0, "gain": 0}],  # "in" skips a quiet
                                               # intro (s), "gain" in dB; a track per section, starting at
                                               # that shot; loops, crossfades into the next
  "music_volume": 0.30,                        # music gain when nobody is talking
  "music_duck": 0.08,                          # music gain under speech (subtitle intervals)
  "denoise_voice": false,                      # highpass + FFT denoise on voice shots (boats, wind);
                                               # per-shot "denoise": true/false overrides
  "shots": [
    {"id": "c01", "card": {"text": "两小时后……", "sub": "", "bg": "#ffd84d"}, "clip": "",
     "in": 0, "out": 2.2, "enabled": true, "sfx": [...]},   # generated time card, no source clip;
                                               # card.image = "maps/route.mp4" (or .png) in edit/ replaces
                                               # the sunburst (route maps, diagrams); card.zoom optional
    {
      "id": "s001",                            # stable id (never reused)
      "clip": "GX015929",                      # file stem inside source_dir (.MP4)
      "in": 0.9, "out": 10.5,                  # seconds in the SOURCE clip
      "enabled": true,                         # false = cut from the video (kept for undo)
      "grade": "default",                      # key into grades
      "audio": "voice",                        # voice (1.0) | ambient (0.35) | mute
      "gain_db": 0,                            # optional per-shot level (dB, -24..+12): lift a quiet/distant
                                               # speaker (e.g. a guide) before the final loudnorm
      "fade_in": 0, "fade_out": 0,             # seconds (video+audio)
      "title": {"text": "Day 1", "sub": "圣约翰岛 St. John", "dur": 3.0},   # optional card at shot start
      "tag": "Mongoose Junction",              # optional small place label, top-left, first 3 s
      "subs": [{"t0": 0.96, "t1": 4.4, "text": "..."}],                     # SOURCE-clip seconds;
                                               # "kind": "note" = editor's caption on a silent shot
      "broll": [{"clip": "GX0001", "in": 2.0, "at": 5.0, "dur": 3.0, "grade": "default"}],
                                               # cut the picture away at shot-local `at` s for
                                               # `dur` s while this shot's audio keeps playing
      "skip": [[3.1, 3.7]], "skip_on": true,   # source spans jump-cut out (pauses / 嗯啊);
                                               # skip_on=false restores them
      "sfx": [{"file": "sfx/whoosh.mp3", "at": 0.0, "gain": 0.8}],   # sound effects (shot-local s)
      "speed": 4,                              # timelapse factor (audio muted when > 1)
      "marks": [{"t0": 3.0, "t1": 5.0, "x": 0.8, "y": 0.5, "label": "虎鲸"}],  # labelled arrows
                                               # pointing at (x, y) during [t0, t1] (source s)
      "zoom": {"from": 1.0, "to": 1.3, "x": 0.5, "y": 0.5},   # Ken Burns push/pull toward
                                               # focal point (x, y as 0-1 of the frame)
      "note": "why this shot"                  # agent's rationale, shown in review
    }
  ]
}

Subtitle times are in source-clip seconds, so trimming a shot's in/out automatically drops
or clips the captions that fall outside it.
"""
import json
import os

AUDIO_GAIN = {"voice": 1.0, "ambient": 0.35, "mute": 0.0}


def project_dir(project):
    """Resolve a project given as a path or a bare folder name. Projects get moved (e.g. from
    ~/Desktop/202512/ up to ~/Desktop/ once edited), so fall back to finding a folder with the same
    name on the Desktop or one level below it."""
    p = os.path.expanduser(project)
    if os.path.isdir(p):
        return p
    name = os.path.basename(os.path.normpath(p))
    desk = os.path.expanduser("~/Desktop")
    cand = os.path.join(desk, name)
    if os.path.isdir(cand):
        return cand
    for sub in sorted(os.listdir(desk)) if os.path.isdir(desk) else []:
        c = os.path.join(desk, sub, name)
        if os.path.isdir(c):
            return c
    return os.path.join(desk, project)


def edit_dir(project):
    return os.path.join(project_dir(project), "02 - Export", "edit")


def edl_path(project):
    return os.path.join(edit_dir(project), "edl.json")


def load(project):
    with open(edl_path(project), encoding="utf-8") as f:
        return json.load(f)


def save(project, edl):
    os.makedirs(edit_dir(project), exist_ok=True)
    tmp = edl_path(project) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(edl, f, ensure_ascii=False, indent=1)
    os.replace(tmp, edl_path(project))


def clip_path(edl, clip):
    return os.path.join(project_dir(edl["project"]), edl.get("source_dir", "01 - Unedited"), clip + ".MP4")


def active_shots(edl):
    return [s for s in edl["shots"] if s.get("enabled", True) and s["out"] > s["in"]]


def kept_ranges(shot):
    """Source ranges that survive inside [in, out] after removing `skip` spans (pauses, fillers).
    `skip_on: false` restores them without losing the detected spans."""
    rs, cur = [], shot["in"]
    for a, b in sorted(shot.get("skip", []) if shot.get("skip_on", True) else []):
        a, b = max(a, shot["in"]), min(b, shot["out"])
        if b - a <= 0.02 or a < cur:
            continue
        rs.append((cur, a)); cur = b
    rs.append((cur, shot["out"]))
    return [(a, b) for a, b in rs if b - a > 0.02]


def speed(shot):
    """Playback speed factor (timelapse). >1 speeds up; audio is muted for sped-up shots."""
    return max(0.25, float(shot.get("speed", 1.0) or 1.0))


def shot_dur(shot):
    if "_qdur" in shot:  # frame-quantized length, set by the renderer for exact timeline math
        return shot["_qdur"]
    return sum(b - a for a, b in kept_ranges(shot)) / speed(shot)


def src_to_local(shot, t):
    """Source-clip time -> time inside the rendered shot (skipped spans collapse)."""
    acc, k = 0.0, speed(shot)
    for a, b in kept_ranges(shot):
        if t <= b:
            return (acc + max(0.0, t - a)) / k
        acc += b - a
    return acc / k


def shot_subs(shot):
    """Subtitles of a shot, clipped to [in, out] and mapped to shot-local time."""
    out = []
    for s in shot.get("subs", []):
        t0, t1 = max(s["t0"], shot["in"]), min(s["t1"], shot["out"])
        l0, l1 = src_to_local(shot, t0), src_to_local(shot, t1)
        text, kind = s["text"].strip(), s.get("kind", "speech")
        if text.startswith("※"):  # legacy marker for an editor note: never render the symbol
            text, kind = text.lstrip("※ ").strip(), "note"
        if l1 - l0 >= 0.3 and text:
            out.append({"t0": l0, "t1": l1, "text": text, "kind": kind})
    return out


def timeline(edl):
    """[(shot, start_on_timeline)] for enabled shots, plus total duration."""
    t, rows = 0.0, []
    for s in active_shots(edl):
        rows.append((s, t))
        t += shot_dur(s)
    return rows, t


def timeline_subs(edl):
    rows, _ = timeline(edl)
    return [{"t0": st + x["t0"], "t1": st + x["t1"], "text": x["text"], "kind": x["kind"]}
            for s, st in rows for x in shot_subs(s)]


def _ts(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(subs):
    return "\n".join(f"{i}\n{_ts(s['t0'])} --> {_ts(s['t1'])}\n{s['text']}\n"
                     for i, s in enumerate(subs, 1))
