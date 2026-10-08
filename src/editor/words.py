"""Word-level timestamps for exact retake / stumble cuts.

    ./venv/bin/python -m src.editor.words "<project>" GX013234            # every word with its time
    ./venv/bin/python -m src.editor.words "<project>" GX013234 "八秒钟"    # where a phrase starts/ends

Reads edit/scan/words/<clip>.json, written by `src.editor.transcribe` (Qwen3-ASR word timestamps).
Clips transcribed before 2026-10-08 have no word file: re-run `transcribe --only <clip>`.
Cut on word boundaries, then always test-join and re-transcribe (LESSONS: Speech → subtitles).
"""
import json
import os
import sys

from . import edl as E


def load(project, clip):
    p = os.path.join(E.edit_dir(project), "scan", "words", clip + ".json")
    if not os.path.exists(p):
        raise SystemExit(f"no word file {p}: run `asrvenv/bin/python -m src.editor.transcribe \"{project}\" --only {clip}`")
    with open(p, encoding="utf-8") as f:
        return json.load(f)["words"]


def find(words, phrase):
    """Smallest word spans (t0, t1) whose concatenated text contains `phrase` (spaces ignored)."""
    target = phrase.replace(" ", "")
    hits = []
    for i in range(len(words)):
        acc = ""
        for j in range(i, len(words)):
            acc += words[j]["w"].replace(" ", "")
            if target in acc:
                hits.append((i, j))
                break
            if len(acc) > len(target) + 8:
                break
    # keep only minimal spans (drop any span that contains another hit)
    hits = [h for h in hits if not any(o != h and h[0] <= o[0] and o[1] <= h[1] for o in hits)]
    return [(words[i]["t0"], words[j]["t1"]) for i, j in hits]


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if len(a) < 2:
        raise SystemExit(__doc__)
    words = load(a[0], a[1])
    if len(a) > 2:
        for t0, t1 in find(words, a[2]):
            print(f"{t0:8.3f} {t1:8.3f}  {a[2]}")
    else:
        for w in words:
            print(f"{w['t0']:8.3f} {w['t1']:8.3f}  {w['w']}")


if __name__ == "__main__":
    main()
