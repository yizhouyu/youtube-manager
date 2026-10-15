"""How much of a YouTube title a phone shows (creator, 2026-10-15: 「标题…会不会太长」).

    ./venv/bin/python -m src.editor.title_check "标题一" "标题二" …

Width units: a CJK character or full-width punctuation = 2, ASCII = 1 (truncation is by pixel width).
Third-party measurements (no official figure): mobile Home feed shows ~40–50 units, mobile search ~50–60,
desktop ~60–70. So the place name + hook must fit in the first ~40 units (≈ 20 Chinese characters),
and the whole title should stay ≤ ~70 units; everything after that is for search only.
"""
import sys
import unicodedata

PHONE, DESKTOP = 40, 70


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def cut(s, n):
    out, w = "", 0
    for c in s:
        cw = width(c)
        if w + cw > n:
            return out + "…"
        out += c; w += cw
    return out


def report(t):
    w = width(t)
    flag = "OK" if w <= DESKTOP else "LONG"
    return f"[{w:3d} {flag}] phone: {cut(t, PHONE)}\n           full: {t}"


if __name__ == "__main__":
    for t in sys.argv[1:]:
        print(report(t))
