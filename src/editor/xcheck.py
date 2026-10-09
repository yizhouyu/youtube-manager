"""Second-model caption cross-check with speaker labels (MOSS-Transcribe-Diarize 0.9B via mlx-audio).

    ./venv/bin/python -m src.editor.xcheck "<project>" clips [GX013234 GX013193:14.5:24 ...]   # raw clips / spans
    ./venv/bin/python -m src.editor.xcheck "<project>" preview [--file edit/preview.mp4]       # rendered talk segments
      options: --force (re-run the model)  --no-run (diff cached JSON only)  --all (print matching captions too)
               --hotwords "Carrollton,Stockyards"  (≤ ~15 names; long lists made MOSS worse in the benchmark)

Why MOSS (benchmark 2026-10-08, sessions/research/2026-10-08/tools.md): on 10 real Texas segments it dropped the
fewest real words (0.6 % deletions vs whisper large-v3 4.6 %, Qwen 1.6 %), had the lowest error once fillers are
ignored, is ~2× faster than whisper, and labels speakers ([S01], [S02]) in the same pass. Qwen3-ASR stays the
primary model (transcribe.py); this is the cross-check SKILL/LESSONS ask for on every kept line.

`clips` with no names = every raw clip that has speech captions in the EDL. A span is CLIP:IN:OUT (source seconds).
`preview` derives the talk segments from the EDL captions on the timeline (merged across small gaps, padded),
cuts them from the rendered preview and checks what the viewer will actually hear.

Writes edit/scan/xcheck/<clip>[_<in>-<out>].json or preview_<t0>-<t1>.json:
    {"source", "span": [a, b], "model", "raw", "segments": [{"start", "end", "speaker", "text"}], "word_times": false}
Times are source-clip seconds (clips) or timeline seconds (preview). MOSS gives phrase-level segments, not word
times; use `src.editor.words` (Qwen) for word boundaries. Speaker labels are per file (S01 in one clip need not be
S01 in the next).

Prints, per caption: the token diff (caption vs MOSS: [-only in caption-] {+only MOSS heard+}), a token error rate,
and `!! speakers S01→S02` when the voice changes inside one caption (two people's lines merged into one cue, or
someone else's words captioned as his). Then MOSS phrases that fall inside a used shot but under no caption
(missed lines, or background people: never caption strangers). Captions are not changed: decide by listening.

Setup (once): uv venv -p 3.12 .tools/mlx-audio && uv pip install -p .tools/mlx-audio/bin/python mlx-audio
sentencepiece jinja2   (or point XCHECK_PYTHON at another interpreter with mlx-audio). Model weights
(OpenMOSS-Team/MOSS-Transcribe-Diarize, 1.8 GB, Apache-2.0, ungated) download on first use.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL = "OpenMOSS-Team/MOSS-Transcribe-Diarize"
PAD = 0.25          # preview talk segments: padding around the captions (s)
MERGE_GAP = 1.0     # merge captions closer than this into one talk segment (s)
MAX_SEG = 45.0      # cap a talk segment's length (s)
MIN_OVERLAP = 0.15  # a MOSS phrase counts for a caption when it overlaps by at least this (s)


# ---------------------------------------------------------------- pure logic (tested without the model)

_SEG_RE = re.compile(r"\[(\d+(?:\.\d+)?)\]\[(S\d+)\](.*?)(?=\[\d+(?:\.\d+)?\]\[S\d+\]|\Z)", re.S)
_END_RE = re.compile(r"\[(\d+(?:\.\d+)?)\]\s*$")


def parse_moss(raw, offset=0.0, duration=None):
    """MOSS output '[0.96][S01]看完了[1.96][2.03][S02]我们…[4.93]' → segments with absolute times.
    The last phrase may lack its end stamp (ends at `duration`); output without any stamps becomes one
    unlabelled segment over the whole span."""
    raw = (raw or "").strip()
    segs = []
    for m in _SEG_RE.finditer(raw):
        start, spk, body = float(m.group(1)), m.group(2), m.group(3)
        e = _END_RE.search(body)
        if e:
            end, body = float(e.group(1)), body[:e.start()]
        else:
            end = duration if duration is not None else start
        body = body.strip()
        if body:
            segs.append({"start": round(offset + start, 2), "end": round(offset + max(end, start), 2),
                         "speaker": spk, "text": body})
    if not segs and raw and "[S" not in raw:
        segs.append({"start": round(offset, 2), "end": round(offset + (duration or 0.0), 2), "speaker": None,
                     "text": raw})
    return segs


try:  # Simplified Chinese for the comparison (the repo venv has OpenCC; the MLX worker doesn't need it)
    from opencc import OpenCC
    _t2s = OpenCC("t2s").convert
except Exception:  # pragma: no cover
    _t2s = lambda s: s  # noqa: E731

_TOK_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[㐀-鿿豈-﫿]")


def tokens(text):
    """Comparison tokens: each Chinese character, each Latin word/number; punctuation, case, spaces ignored."""
    return _TOK_RE.findall(_t2s(text or "").lower())


def _join(toks):
    out = ""
    for t in toks:
        if out and t[0].isascii() and t[0].isalnum() and (out[-1].isascii() and out[-1].isalnum()):
            out += " "
        out += t
    return out


def _ops(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = sm.get_opcodes()
    return ops, sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in ops if op != "equal")


def diff_tokens(ref, hyp, left=(), right=()):
    """(marked string, token error rate, what the model heard) for caption `ref` vs model `hyp`.
    `left` / `right` are a few model tokens just outside the caption window (the time cut between captions is
    only approximate): they are used only where they line up with the caption's own first/last words. Up to 2
    model tokens at either edge may be set aside as bleed from the neighbouring caption; they are shown as ‹…›."""
    a = tokens(ref) if isinstance(ref, str) else list(ref)
    core = tokens(hyp) if isinstance(hyp, str) else list(hyp)
    left, right = list(left), list(right)
    best = None
    for i in range(len(left) + 1):  # take the last i context tokens on the left …
        for j in range(len(right) + 1):  # … and the first j on the right
            for ci in range(min(2, len(core)) + 1):  # or drop up to 2 core tokens that bled in at an edge
                for cj in range(min(2, len(core) - ci) + 1):
                    b = left[len(left) - i:] + core[ci:len(core) - cj] + right[:j]
                    ops, err = _ops(a, b)
                    cost = err + 0.01 * (i + j) + 0.6 * (ci + cj)  # trimming the core needs real evidence
                    if best is None or cost < best[0]:
                        best = (cost, b, ops, err, core[:ci], core[len(core) - cj:])
    _, b, ops, err, cut_l, cut_r = best
    parts = []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            parts.append(_join(a[i1:i2]))
            continue
        if i2 > i1:
            parts.append("[-" + _join(a[i1:i2]) + "-]")
        if j2 > j1:
            parts.append("{+" + _join(b[j1:j2]) + "+}")
    shown = ("‹" + _join(cut_l) + "›" if cut_l else "") + _join(b) + ("‹" + _join(cut_r) + "›" if cut_r else "")
    return "".join(parts), err / max(1, len(a)), shown


def _slice(toks, s, e, lo, hi):
    """Token indices [i, j) of a phrase [s, e] spoken inside [lo, hi] (even speaking rate assumed)."""
    n = len(toks)
    if e - s <= 0.05:
        return 0, n
    i = int(round(n * (max(lo, s) - s) / (e - s)))
    j = int(round(n * (min(hi, e) - s) / (e - s)))
    return max(0, min(i, n)), max(0, min(j, n))


def windows(cap):
    """The caption's audible windows: [t0, t1] minus any `skip` spans it carries (clip mode)."""
    out, cur = [], cap["t0"]
    for a, b in sorted(cap.get("skip", [])):
        a, b = max(a, cap["t0"]), min(b, cap["t1"])
        if b <= a or b <= cur:  # outside this caption, or already covered
            continue
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if cap["t1"] > cur:
        out.append((cur, cap["t1"]))
    return [(a, b) for a, b in out if b - a > 0.05]


CTX = 2            # model tokens of context kept outside a caption window, each side
SPK_MIN_S = 0.6    # a second speaker must cover at least this long …
SPK_MIN_FRAC = 0.15  # … and this share of the caption to raise a speaker-change flag


def match_caption(cap, segs):
    """(left context, heard tokens, right context, [(speaker, seconds)] in order of appearance)."""
    heard, cover, left, right = [], {}, [], []
    order = []
    for lo, hi in windows(cap):
        for s in sorted(segs, key=lambda x: x["start"]):
            ov = min(hi, s["end"]) - max(lo, s["start"])
            inside = s["start"] >= lo and s["end"] <= hi
            if ov < MIN_OVERLAP and not inside:
                continue
            toks = tokens(s["text"])
            i, j = _slice(toks, s["start"], s["end"], lo, hi)
            if not heard and not left:
                left = toks[max(0, i - CTX):i]
            heard += toks[i:j]
            right = toks[j:j + CTX]
            spk = s.get("speaker")
            if spk:
                if spk not in cover:
                    order.append(spk)
                cover[spk] = cover.get(spk, 0.0) + max(0.0, ov)
    return left, heard, right, [(k, round(cover[k], 2)) for k in order]


def speaker_change(cap, cover):
    dur = sum(b - a for a, b in windows(cap)) or (cap["t1"] - cap["t0"])
    real = [k for k, sec in cover if sec >= SPK_MIN_S and sec >= SPK_MIN_FRAC * dur]
    return real if len(real) > 1 else []


def uncaptioned(segs, caps, ranges):
    """MOSS phrases inside the used (audible) ranges that overlap no caption."""
    out = []
    for s in segs:
        if any(min(c["t1"], s["end"]) - max(c["t0"], s["start"]) > MIN_OVERLAP for c in caps):
            continue
        if any(min(r1, s["end"]) - max(r0, s["start"]) > MIN_OVERLAP for r0, r1 in ranges):
            out.append(s)
    return out


def report(caps, segs, ranges=(), show_all=False, label=""):
    """Lines of the diff report + summary numbers."""
    lines, n_err, n_tok, flagged = [], 0, 0, 0
    for c in caps:
        left, heard, right, cover = match_caption(c, segs)
        marked, ter, used = diff_tokens(c["text"], heard, left, right)
        n = len(tokens(c["text"]))
        n_err += round(ter * n)
        n_tok += n
        change = speaker_change(c, cover)
        if ter > 0 or change or show_all:
            flagged += (ter > 0.2) or bool(change)
            who = " ".join(f"{k}:{sec:.1f}s" for k, sec in cover) or "-"
            head = f"{c.get('where', '')} {c['t0']:7.2f}–{c['t1']:7.2f}  TER {100 * ter:3.0f}%  {who}"
            if change:
                head += "   !! speakers " + "→".join(change) + " inside this caption"
            lines += [head, f"    cap : {c['text']}", f"    moss: {used or '(nothing)'}"]
            if ter > 0:
                lines.append(f"    diff: {marked}")
    extra = uncaptioned(segs, caps, ranges)
    if extra:
        lines.append(f"-- MOSS heard {len(extra)} phrase(s) inside used shots with no caption{label}:")
        lines += [f"    {s['start']:7.2f}–{s['end']:7.2f} {s.get('speaker') or '-'}  {s['text']}" for s in extra]
    summ = {"captions": len(caps), "tokens": n_tok, "ter": n_err / max(1, n_tok), "flagged": flagged,
            "uncaptioned": len(extra)}
    return lines, summ


def is_speech(sub):
    return sub.get("kind", "speech") != "note" and not sub.get("text", "").strip().startswith("※")


def clip_captions(edl, clip):
    """Speech captions of a raw clip in source seconds (one entry per line even when several shots reuse it,
    with that shot's skips) + the source ranges whose raw sound the cut plays (not muted, not a stem)."""
    from . import edl as E
    caps, ranges = [], []
    for s in edl["shots"]:
        if s.get("clip") != clip or not s.get("enabled", True) or s["out"] <= s["in"]:
            continue
        if s.get("audio", "voice") != "mute" and not s.get("audio_src"):  # muted / stem shots: raw speech isn't heard
            ranges += E.kept_ranges(s)
        skips = [list(k) for k in s.get("skip", [])] if s.get("skip_on", True) else []
        for x in s.get("subs", []):
            if not is_speech(x):
                continue
            dup = next((c for c in caps if c["text"] == x["text"] and abs(c["t0"] - x["t0"]) < 0.3), None)
            if dup:
                dup["where"] += "," + s["id"]
                continue
            caps.append({"t0": x["t0"], "t1": x["t1"], "text": x["text"], "where": s["id"], "skip": skips})
    return sorted(caps, key=lambda c: c["t0"]), ranges


def timeline_captions(edl):
    """Speech captions on the rendered timeline (seconds) + the timeline ranges of shots with speech."""
    from . import edl as E
    rows, _ = E.timeline(edl)
    caps, ranges = [], []
    for shot, start in rows:
        subs = [x for x in E.shot_subs(shot) if x.get("kind", "speech") == "speech"]
        if subs and shot.get("audio", "voice") != "mute":
            ranges.append((start, start + E.shot_dur(shot)))
        for x in subs:
            caps.append({"t0": round(start + x["t0"], 3), "t1": round(start + x["t1"], 3), "text": x["text"],
                         "where": f"{shot['id']} @{int(start + x['t0']) // 60}:{int(start + x['t0']) % 60:02d}"})
    return sorted(caps, key=lambda c: c["t0"]), ranges


def talk_segments(caps, total=None, pad=PAD, gap=MERGE_GAP, max_len=MAX_SEG):
    """Merge caption windows into padded talk segments to cut from the preview."""
    segs = []
    for c in caps:
        a, b = max(0.0, c["t0"] - pad), c["t1"] + pad
        if total is not None:
            b = min(b, total)
        if segs and a - segs[-1][1] <= gap and b - segs[-1][0] <= max_len:
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in segs]


# ---------------------------------------------------------------- model run (worker in the MLX env)

def mlx_python():
    p = os.environ.get("XCHECK_PYTHON") or os.path.join(REPO, ".tools", "mlx-audio", "bin", "python")
    return p if os.path.exists(p) else None


def _worker(job_path):
    """Runs inside the MLX interpreter: load MOSS once, transcribe every job item, write raw text."""
    from mlx_audio.stt.utils import load_model
    jobs = json.load(open(job_path))
    model = load_model(jobs["model"])
    for it in jobs["items"]:
        t = time.time()
        r = model.generate(it["wav"], max_tokens=it["max_tokens"], hotwords=it.get("hotwords") or None)
        it["raw"], it["secs"] = r.text, round(time.time() - t, 2)
        print(f"[xcheck] {os.path.basename(it['out'])}: {it['secs']} s", flush=True)
    json.dump(jobs, open(job_path, "w"), ensure_ascii=False)


def run_model(items, hotwords=None, model=MODEL):
    """items: [{"src", "a", "b", "out", "source", "offset"}]; cuts 16 kHz mono audio, runs MOSS under the
    machine-wide ASR lock, writes each item's JSON. Returns the written paths."""
    from .asrlock import asr_lock
    py = mlx_python()
    if not py:
        raise SystemExit("MLX env not found: see the setup note in src/editor/xcheck.py (or set XCHECK_PYTHON)")
    with tempfile.TemporaryDirectory() as td:
        for k, it in enumerate(items):
            it["wav"] = os.path.join(td, f"{k}.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{it['a']:.3f}", "-to", f"{it['b']:.3f}",
                            "-i", it["src"], "-vn", "-ac", "1", "-ar", "16000", it["wav"]], check=True)
            it["max_tokens"] = int(256 + 35 * (it["b"] - it["a"]))
            it["hotwords"] = hotwords
        job = os.path.join(td, "job.json")
        json.dump({"model": model, "items": items}, open(job, "w"), ensure_ascii=False)
        with asr_lock():
            subprocess.run([py, os.path.abspath(__file__), "--worker", job], check=True,
                           env=dict(os.environ, YT_ASR_LOCK_HELD="1"))
        done = json.load(open(job))["items"]
    for it in done:
        os.makedirs(os.path.dirname(it["out"]), exist_ok=True)
        rec = {"source": it["source"], "span": [it["a"], it["b"]], "model": model, "raw": it["raw"],
               "segments": parse_moss(it["raw"], it["offset"], it["b"] - it["a"]), "word_times": False,
               "secs": it["secs"], "src_mtime": it.get("src_mtime"), "hotwords": hotwords,
               "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        json.dump(rec, open(it["out"], "w"), ensure_ascii=False, indent=1)
    return [it["out"] for it in done]


def _probe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float((r.stdout.strip().splitlines() or ["0"])[0])


def _fresh(path, mtime=None):
    if not os.path.exists(path):
        return False
    return mtime is None or json.load(open(path)).get("src_mtime") == mtime


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("project")
    ap.add_argument("mode", choices=["clips", "preview"])
    ap.add_argument("items", nargs="*", help="clips mode: CLIP or CLIP:IN:OUT")
    ap.add_argument("--file", help="preview mode: the rendered file (default edit/preview.mp4)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-run", action="store_true", help="only diff what is already saved")
    ap.add_argument("--all", action="store_true", help="print captions that match too")
    ap.add_argument("--hotwords", default="")
    a = ap.parse_args(argv)
    from . import edl as E
    edl = E.load(a.project)
    xdir = os.path.join(E.edit_dir(a.project), "scan", "xcheck")
    hot = [h.strip() for h in a.hotwords.split(",") if h.strip()] or None
    jobs, plan = [], []  # plan: (json path, captions, ranges, title)

    if a.mode == "clips":
        names = a.items or sorted({s["clip"] for s in edl["shots"] if s.get("clip") and any(is_speech(x) for x in s.get("subs", []))})
        for item in names:
            parts = item.split(":")
            clip = parts[0]
            src = E.clip_path(edl, clip)
            caps, ranges = clip_captions(edl, clip)
            if len(parts) == 3:
                lo, hi = float(parts[1]), float(parts[2])
                tag = f"{clip}_{lo:g}-{hi:g}"
                caps = [c for c in caps if c["t1"] > lo and c["t0"] < hi]
                ranges = [(max(r0, lo), min(r1, hi)) for r0, r1 in ranges if r1 > lo and r0 < hi]
            else:
                lo, hi, tag = 0.0, _probe_dur(src), clip
            out = os.path.join(xdir, tag + ".json")
            plan.append((out, caps, ranges, f"{clip} ({lo:g}–{hi:g} s)"))
            if not a.no_run and (a.force or not _fresh(out)):
                jobs.append({"src": src, "a": lo, "b": hi, "out": out, "source": clip, "offset": lo})
    else:
        src = a.file or os.path.join(E.edit_dir(a.project), "preview.mp4")
        if not os.path.exists(src):
            raise SystemExit(f"no rendered file: {src}")
        mtime = os.path.getmtime(src)
        caps, ranges = timeline_captions(edl)
        for lo, hi in talk_segments(caps, _probe_dur(src)):
            out = os.path.join(xdir, f"preview_{lo:.2f}-{hi:.2f}.json")
            sc = [c for c in caps if c["t1"] > lo and c["t0"] < hi]
            sr = [(max(r0, lo), min(r1, hi)) for r0, r1 in ranges if r1 > lo and r0 < hi]
            plan.append((out, sc, sr, f"preview {int(lo) // 60}:{int(lo) % 60:02d}–{int(hi) // 60}:{int(hi) % 60:02d}"))
            if not a.no_run and (a.force or not _fresh(out, mtime)):
                jobs.append({"src": src, "a": lo, "b": hi, "out": out, "source": os.path.basename(src),
                             "offset": lo, "src_mtime": mtime})

    if jobs:
        print(f"[xcheck] running MOSS on {len(jobs)} item(s), {sum(j['b'] - j['a'] for j in jobs):.0f} s of audio", flush=True)
        run_model(jobs, hot)
    tot = {"captions": 0, "tokens": 0, "err": 0, "flagged": 0, "uncaptioned": 0}
    for out, caps, ranges, title in plan:
        if not os.path.exists(out):
            print(f"== {title}: no saved MOSS result (run without --no-run)")
            continue
        segs = json.load(open(out))["segments"]
        lines, s = report(caps, segs, ranges, a.all)
        print(f"== {title}: {s['captions']} captions, TER {100 * s['ter']:.1f}%, {s['flagged']} flagged, "
              f"{s['uncaptioned']} uncaptioned phrase(s)  [{os.path.relpath(out, E.edit_dir(a.project))}]")
        for ln in lines:
            print(ln)
        for k in ("captions", "tokens", "flagged", "uncaptioned"):
            tot[k] += s[k]
        tot["err"] += round(s["ter"] * s["tokens"])
    if len(plan) > 1:
        print(f"== TOTAL: {tot['captions']} captions, TER {100 * tot['err'] / max(1, tot['tokens']):.1f}%, "
              f"{tot['flagged']} flagged (TER > 20 % or a speaker change), {tot['uncaptioned']} uncaptioned phrase(s)")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        _worker(sys.argv[2])
    else:
        main()
