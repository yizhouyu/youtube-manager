"""Transcribe every raw clip with the strongest local ASR we've benchmarked.

    asrvenv/bin/python -m src.editor.transcribe "<project>" [--context "place, dish, name, ..."]

Model: Qwen3-ASR-1.7B on Apple Silicon via MLX (`mlx-qwen3-asr`, Python 3.12 env `asrvenv/`).
Benchmarked 2026-09 on casual Mandarin + English code-switching with wind noise, it beat
whisper large-v3: right proper nouns with a context string (Trunk Bay, Salt Pond Bay,
Kallaloo, 玳瑁 — whisper wrote Trunkville / South Palm Bay / Colorful Soup / 代冒), native
Simplified output, catches English banter, and returns nothing on silent underwater clips
where whisper hallucinates broadcaster sign-offs. Always pass --context: without it place
names degrade badly. (whisper.cpp large-v3 remains the fallback: see the skill.)

Writes <project>/02 - Export/edit/scan/srt/<clip>.srt (raw; proofread later by
captions_clean.py). Lines are cut at punctuation, pauses > 0.6 s, or ~16 characters, and
their text is sliced from the model's own transcript so English word spacing survives
(the package's SRT writer glues English words together).
"""
import argparse
import glob
import os
import subprocess
import tempfile

from . import edl as E

MODEL = "Qwen/Qwen3-ASR-1.7B"
PUNCT = "，。？！、；：,.?!;:…"
MAX_CHARS = 16


def _lines(text, words, gap=0.6):
    """Group word timestamps into subtitle lines; slice each line's text from `text`."""
    pos, spans = 0, []
    for w in words:
        i = text.find(w["text"], pos)
        if i < 0:  # tokenizer/text mismatch: fall back to the token itself
            spans.append((None, None, w)); continue
        spans.append((i, i + len(w["text"]), w)); pos = i + len(w["text"])
    lines, cur = [], []

    def flush():
        if not cur:
            return
        a = next((s for s, _, _ in cur if s is not None), None)
        b = next((e for _, e, _ in reversed(cur) if e is not None), None)
        t = text[a:b] if a is not None else "".join(w["text"] for _, _, w in cur)
        t = t.strip(PUNCT + " ")
        if t:
            lines.append({"t0": cur[0][2]["start"], "t1": cur[-1][2]["end"], "text": t})
        cur.clear()

    for k, (s, e, w) in enumerate(spans):
        if cur and (w["start"] - cur[-1][2]["end"] > gap or
                    sum(len(x[2]["text"]) for x in cur) >= MAX_CHARS):
            flush()
        cur.append((s, e, w))
        nxt = text[e:e + 1] if e is not None else ""
        if nxt and nxt in PUNCT:
            flush()
    flush()
    # fold crumbs ("看", "的地方", zero-length "你") into a neighbour when they're contiguous
    merged = []
    for ln in lines:
        short = len(ln["text"]) <= 3 or ln["t1"] - ln["t0"] < 0.25
        if merged and short and ln["t0"] - merged[-1]["t1"] < 0.4 and len(merged[-1]["text"]) < MAX_CHARS + 4:
            sep = " " if merged[-1]["text"][-1:].isascii() and ln["text"][:1].isascii() else ""
            merged[-1] = {"t0": merged[-1]["t0"], "t1": ln["t1"], "text": merged[-1]["text"] + sep + ln["text"]}
        else:
            merged.append(ln)
    return [m for m in merged if m["t1"] - m["t0"] >= 0.15 or len(m["text"]) > 2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--context", default="", help="proper nouns to bias recognition")
    ap.add_argument("--only", default="", help="comma-separated clip names")
    a = ap.parse_args()
    if not a.context:  # fall back to the project's own list of proper nouns
        cpath = os.path.join(E.edit_dir(a.project), "asr_context.txt")
        if os.path.exists(cpath):
            a.context = " ".join(l.strip() for l in open(cpath, encoding="utf-8") if not l.startswith("#"))

    from .asrlock import asr_lock
    with asr_lock():  # one ASR model at a time on this machine
        from mlx_qwen3_asr import load_model, transcribe
        from opencc import OpenCC
        t2s = OpenCC("t2s").convert
        model = load_model(MODEL)
        model = model[0] if isinstance(model, tuple) else model

        src = os.path.join(E.project_dir(a.project), "01 - Unedited")
        out = os.path.join(E.edit_dir(a.project), "scan", "srt")
        os.makedirs(out, exist_ok=True)
        clips = sorted(os.path.join(src, f) for f in os.listdir(src) if f.upper().endswith(".MP4"))  # phone clips are .mp4
        if a.only:
            clips = [c for c in clips if os.path.basename(c)[:-4] in a.only.split(",")]
        for c in clips:
            name = os.path.basename(c)[:-4]
            with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", c, "-vn", "-ac", "1", "-ar", "16000", f.name],
                               check=True)
                r = transcribe(f.name, model=model, context=a.context, return_timestamps=True)
            lines = _lines(t2s(r.text or ""), [dict(w, text=t2s(w["text"])) for w in (r.segments or [])])
            with open(os.path.join(out, name + ".srt"), "w", encoding="utf-8") as fh:
                fh.write(E.to_srt(lines))
            print(f"{name}: {len(lines)} lines", flush=True)


if __name__ == "__main__":
    main()
