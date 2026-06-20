#!/usr/bin/env python
"""Re-split an SRT into short, readable caption lines.

Whisper emits segments that are often too long for a readable caption line (we've
seen 20s cues). This merges then re-splits at sentence/clause punctuation into
chunks of <= MAXLEN characters, distributing each source cue's time window
proportionally by character count. Borrowed from the "断句：先合并再重切" idea in
sunyuzheng/lizheng-video-production.

Usage: python scripts/resplit_srt.py <in.srt> [out.srt] [maxlen=16]
(in-place if no out path given)
"""
import sys, re

PUNCT = "。！？!?；;，,、… "   # split preference, strongest first handled by regex below


def parse_srt(text):
    blocks = re.split(r"\n\s*\n", text.strip())
    cues = []
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        tc = next((l for l in lines if "-->" in l), None)
        if not tc:
            continue
        idx = lines.index(tc)
        txt = " ".join(lines[idx + 1:]).strip()
        m = re.match(r"(\d\d:\d\d:\d\d,\d\d\d)\s*-->\s*(\d\d:\d\d:\d\d,\d\d\d)", tc)
        if not m:
            continue
        cues.append((to_ms(m.group(1)), to_ms(m.group(2)), txt))
    return cues


def to_ms(t):
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def to_tc(ms):
    ms = max(0, int(ms)); h = ms // 3600000; ms %= 3600000
    m = ms // 60000; ms %= 60000; s = ms // 1000; ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def split_text(txt, maxlen):
    """Split into <=maxlen chunks, preferring punctuation boundaries."""
    txt = txt.strip()
    if len(txt) <= maxlen:
        return [txt] if txt else []
    parts, cur = [], ""
    # tokenize keeping punctuation attached to the preceding clause
    tokens = re.findall(r"[^。！？!?；;，,、…\s]+[。！？!?；;，,、…]?|\s+", txt)
    for tok in tokens:
        if tok.isspace():
            continue
        if len(cur) + len(tok) <= maxlen:
            cur += tok
        else:
            if cur:
                parts.append(cur)
            # token itself too long -> hard wrap
            while len(tok) > maxlen:
                parts.append(tok[:maxlen]); tok = tok[maxlen:]
            cur = tok
    if cur:
        parts.append(cur)
    return [p.strip("，、 ") for p in parts if p.strip("，、 ")]


def resplit(cues, maxlen):
    out = []
    for start, end, txt in cues:
        chunks = split_text(txt, maxlen)
        if len(chunks) <= 1:
            out.append((start, end, txt)); continue
        total = sum(len(c) for c in chunks) or 1
        t = start; span = end - start
        for i, c in enumerate(chunks):
            dur = round(span * len(c) / total)
            cs = t
            ce = end if i == len(chunks) - 1 else min(end, t + dur)
            out.append((cs, ce, c)); t = ce
    return out


def main():
    if len(sys.argv) < 2:
        print("usage: resplit_srt.py <in.srt> [out.srt] [maxlen]", file=sys.stderr); sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].isdigit() else inp
    maxlen = int(next((a for a in sys.argv[2:] if a.isdigit()), 16))
    cues = resplit(parse_srt(open(inp, encoding="utf-8").read()), maxlen)
    with open(out, "w", encoding="utf-8") as f:
        for i, (s, e, t) in enumerate(cues, 1):
            f.write(f"{i}\n{to_tc(s)} --> {to_tc(e)}\n{t}\n\n")
    print(f"resplit -> {out}: {len(cues)} cues (<= {maxlen} chars)")


if __name__ == "__main__":
    main()
