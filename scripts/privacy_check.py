#!/usr/bin/env python3
"""Block commits that contain personal information (called by .githooks/).

  privacy_check.py staged          added lines, file names and media metadata in the index
  privacy_check.py message <file>  a commit message
  privacy_check.py tree            every tracked file, as a baseline

This repo is public, so the personal words (names, addresses, emails) are NOT here. They live in
~/.config/youtube-manager/privacy_terms.txt, one per line:
  some text          blocked anywhere, ignoring case, spaces and full-width forms
  re:<regex>         blocked when the regex matches
  allow:<text>       a false positive: this exact match is fine
Found values are printed masked, so a log or transcript never repeats them (file names are shown). Exit: 0 clean, 1 blocked,
2 the check could not run (also stops the commit).
"""
import io
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path

TERMS = Path(os.environ.get("PRIVACY_TERMS", "~/.config/youtube-manager/privacy_terms.txt")).expanduser()

PATTERNS = [
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
    ("US phone", r"(?<![\w.-])(?:\+?1[-. ])?(?:\([2-9]\d{2}\) ?|[2-9]\d{2}[-. ])[2-9]\d{2}[-. ]\d{4}(?![\w-]|\.\d)"),
    ("US phone", r"(?<!\w)\+1[2-9]\d{2}[2-9]\d{6}(?!\d)"),
    ("China phone", r"(?<![\w.])(?:\+?86[- ]?)?1[3-9]\d[- ]?\d{4}[- ]?\d{4}(?![\w.]\d|\w)"),
    ("SSN", r"(?<![\w.-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\w-])"),
    ("China ID", r"(?<!\w)\d{17}[\dXx](?!\w)"),
    ("card number", r"(?<![\w.-])[3-6]\d{3}[- ]?\d{4}[- ]?\d{4}[- ]?\d{1,7}(?![\w-]|\.\d)"),
    ("street address", r"(?i)\b\d{1,5} (?:[NSEW]\.? |north |south |east |west )?(?:\d{1,3}(?:st|nd|rd|th)|[A-Z][a-z]+) (?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln)\b\.?,? *(?:apt|unit|suite|#)"),
    ("home folder path", r"/Users/(?!(?:you|me|user|username|name|Shared|runner)\b)[A-Za-z0-9._-]+"),
    ("private document link", r"(?:docs|drive)\.google\.com/(?:document|spreadsheets|presentation|file|drive)/[\w/?=.-]*[\w-]{20,}|docs\.qq\.com/\w+/\w{8,}|notion\.(?:so|site)/\S*[0-9a-f]{32}"),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("API key or token", r"AIza[\w-]{35}|GOCSPX-[\w-]{20,}|ya29\.[\w-]{20,}|1//0[\w-]{30,}|sk-(?:ant-|proj-)?[\w-]{24,}|gh[pousr]_\w{36}|github_pat_\w{40,}|xox[abpr]-[\w-]{10,}|AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{30,}"),
    ("cookie or secret value", r"(?i)\b(?:SESSDATA|bili_jct|client_secret|refresh_token|access_token|api_key|password)\b[\"']?\s*[:=]\s*[\"'](?!your|xxx|<|\$|\{|test|example)[^\s\"']{12,}[\"']"),
]
PATTERNS = [(n, re.compile(p)) for n, p in PATTERNS]

OK_EMAIL = re.compile(r"(?i)(?:@(?:[\w-]+\.)*example\.(?:com|org|net)|@users\.noreply\.github\.com|^noreply@[\w.-]+|^git@[\w.-]+)$")
PRIVATE_PATHS = re.compile(
    r"^(?:sessions|docs)/|(?:^|/)(?:\.env|cookies?(?:\.\w+)?\.(?:json|txt)|token\.(?:json|pickle)|client_secrets?\.json|"
    r"credentials\.json|privacy_terms\.txt|id_(?:rsa|ed25519))$|\.(?:pem|p12|pickle)$")
IMAGE = re.compile(r"(?i)\.(?:jpe?g|png|tiff?|webp|heic)$")
VIDEO = re.compile(r"(?i)\.(?:mp4|mov|m4v|360|insv)$")


def git(*a, check=True):
    r = subprocess.run(["git", *a], capture_output=True)
    if check and r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip())
    return r.stdout


def luhn(s):
    d = [int(c) for c in re.sub(r"\D", "", s)]
    if not 13 <= len(d) <= 19:
        return False
    return sum(x if i % 2 == 0 else sum(divmod(x * 2, 10)) for i, x in enumerate(reversed(d))) % 10 == 0


def china_id(s):
    w = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    return s[6:8] in ("19", "20") and "10X98765432"[sum(int(a) * b for a, b in zip(s, w)) % 11] == s[17].upper()


def squash(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s)).casefold()


def load_terms():
    if not TERMS.is_file():
        raise RuntimeError(f"找不到个人信息词表 {TERMS}")
    words, regexes, allow = [], [], set()
    for line in TERMS.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("re:"):
            regexes.append(re.compile(line[3:]))
        elif line.startswith("allow:"):
            allow.add(line[6:].strip())
        else:
            words.append(squash(line))
    if not words and not regexes:
        raise RuntimeError(f"个人信息词表是空的：{TERMS}")
    return words, regexes, allow


def scan(text, terms):
    """Names and masked values of everything personal in one line."""
    words, regexes, allow = terms
    text = unicodedata.normalize("NFKC", text)
    out = []
    for name, rx in PATTERNS:
        for m in rx.finditer(text):
            v = m.group(0)
            if v in allow or (name == "email" and OK_EMAIL.search(v)):
                continue
            if (name == "card number" and not luhn(v)) or (name == "China ID" and not china_id(v)):
                continue
            out.append((name, v))
    out += [("private term", m.group(0)) for rx in regexes for m in rx.finditer(text) if m.group(0) not in allow]
    flat = squash(text)
    out += [("private term", w) for w in words if w in flat and w not in allow]
    return [(n, mask(v)) for n, v in dict.fromkeys(out)]


def mask(v):
    return v[0] + "*" * min(len(v) - 1, 8)


def decode(blob):
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return blob.decode("utf-16", "replace")
    if b"\0" in blob:  # binary: only its readable strings, or font and image noise looks like emails
        return "\n".join(m.decode() for m in re.findall(rb"[\x20-\x7e]{12,}", blob))
    return blob.decode("utf-8", "replace")


def media(path, blob):
    """GPS positions left in a photo or video."""
    if IMAGE.search(path):
        if b"GPSLatitude=" in blob or b"<exif:GPSLatitude" in blob:
            return [("photo GPS", "XMP")]
        try:
            from PIL import Image
        except ImportError:
            raise RuntimeError("没有 Pillow，查不了图片里的定位（用 venv/bin/python 运行）")
        try:
            if Image.open(io.BytesIO(blob)).getexif().get_ifd(0x8825):
                return [("photo GPS", "EXIF")]
        except Exception as e:
            raise RuntimeError(f"读不了图片 {path}：{type(e).__name__}")
    if VIDEO.search(path) and re.search(rb"\xa9xyz|com\.apple\.quicktime\.location", blob):
        return [("video GPS", "metadata")]
    return []


def scan_file(path, new, old, terms):
    found = [("file name", *f) for f in scan(path, terms)]
    if PRIVATE_PATHS.search(path):
        found.append(("file name", "private file", path.split("/")[0] + "/…" if "/" in path else path))
    found += [("metadata", *f) for f in media(path, new)]
    seen = Counter(decode(old).splitlines())
    for i, line in enumerate(decode(new).splitlines(), 1):
        if seen[line]:
            seen[line] -= 1
            continue
        found += [(f"line {i}", *f) for f in scan(line, terms)]
    return found


def staged(terms):
    has_head = not subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], capture_output=True).returncode
    base = "HEAD" if has_head else git("hash-object", "-t", "tree", "/dev/null").decode().strip()
    out = {}
    raw = git("diff", "--cached", "--name-status", "--no-renames", "-z", "--diff-filter=ACMT", base).decode().split("\0")
    for status, path in zip(raw[::2], raw[1::2]):
        old = git("show", f"HEAD:{path}") if status != "A" else b""
        f = scan_file(path, git("show", f":{path}"), old, terms)
        if f:
            out[path] = f
    for who in ("AUTHOR", "COMMITTER"):
        email = re.search(r"<(.*?)>", git("var", f"GIT_{who}_IDENT").decode()).group(1)
        if not OK_EMAIL.search(email):
            out.setdefault("git " + who.lower(), []).append(("identity", "email", mask(email)))
    return out


def tree(terms):
    files = [p for p in git("ls-files", "-z").decode().split("\0") if p]
    return {p: f for p in files if (f := scan_file(p, git("show", f":{p}"), b"", terms))}


def message(path, terms):
    f = []
    for i, line in enumerate(Path(path).read_text("utf-8", "replace").splitlines(), 1):
        if line.startswith(("# ------------------------ >8", "# Please enter the commit message")):
            break  # git's own template and diff below here; `-m "# …"` lines above are kept
        f += [(f"line {i}", *x) for x in scan(line, terms)]
    return {"commit message": f} if f else {}


def main(argv):
    try:
        terms = load_terms()
        if argv[:1] == ["message"] and len(argv) == 2:
            found = message(argv[1], terms)
        elif argv == ["staged"]:
            found = staged(terms)
        elif argv == ["tree"]:
            found = tree(terms)
        else:
            print(__doc__)
            return 2
    except Exception as e:
        print(f"✋ 个人信息检查没能运行，提交已停下：{e}", file=sys.stderr)
        return 2
    if not found:
        return 0
    print("✋ 发现个人信息，已拦下：", file=sys.stderr)
    for path, items in found.items():
        for where, name, value in items:
            print(f"  {path}  {where}  [{name}] {value}", file=sys.stderr)
    print(f"改掉再提交。确实是误报，请本人在 {TERMS} 里加一行 allow:<原文>。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
