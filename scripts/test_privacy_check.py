#!/usr/bin/env python3
"""Commit-hook test: real `git commit`s in a throwaway repo, with a made-up word list.

Every fake value is built from pieces, so this file itself passes the check.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="privacy-test-"))
REPO, TERMS = TMP / "repo", TMP / "terms.txt"
ENV = {**os.environ, "PRIVACY_TERMS": str(TERMS), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_EDITOR": "true"}
ENV.update({f"GIT_{w}_{k}": v for w in ("AUTHOR", "COMMITTER")
            for k, v in (("NAME", "T"), ("EMAIL", "1+t@users.noreply.github.com"))})
fails = []


def git(*a, env=None):
    return subprocess.run(["git", *a], cwd=REPO, env={**ENV, **(env or {})}, capture_output=True, text=True)


def attempt(name, blocked, files=None, msg="change", env=None, secret=None, code=None):
    """Commit the files; check it was (not) blocked and that the output doesn't repeat the secret."""
    before = git("rev-parse", "HEAD").stdout
    for p, data in (files or {"a.txt": f"{name}\n"}).items():
        f = REPO / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data if isinstance(data, bytes) else data.encode())
    git("add", "-Af")
    r = git("commit", "-m", msg, env=env)
    made = git("rev-parse", "HEAD").stdout != before
    ok = made != blocked
    if blocked:
        ok = ok and "✋" in r.stderr and (secret is None or secret not in r.stdout + r.stderr)
    print("ok  " if ok else "FAIL", "拦" if blocked else "放", name)
    if not ok:
        fails.append(name)
        print(r.stdout + r.stderr)
    git("reset", "-q", "--hard")
    git("clean", "-fdq")


REPO.mkdir()
git("init", "-q", "-b", "main")
for p in [".githooks", "scripts/privacy_check.py"]:
    src, dst = ROOT / p, REPO / p
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
(REPO / ".gitignore").write_text("venv\n")
(REPO / "venv").symlink_to(ROOT / "venv")
TERMS.write_text("Zed Quux\n测试人名\nre:(?i)\\bfluffy\\b\nallow:ok@" + "allowed.io\n", "utf-8")
git("add", "-A")
git("commit", "-qm", "base")
git("config", "core.hooksPath", ".githooks")

AT = "@"
mail = "someone" + AT + "gmail.com"
blocked = {
    "email": mail,
    "email in JSON": '{"owner": "' + mail + '"}',
    "US phone": "call 212-" + "555-0187",
    "US phone, brackets": "(212) " + "555-0187",
    "US phone, +1": "+1212" + "5550187",
    "China phone": "电话" + " 138" + "1234" + "5678",
    "SSN": "123-45-" + "6789",
    "China ID": "11010519491231" + "002X",
    "card": "4111 1111 " + "1111 1111",
    "home path": "open('/Users/" + "somebody/x')",
    "private doc": "https://docs.google.com/" + "document/d/" + "a1B2" * 8,
    "Google key": "AIza" + "x" * 35,
    "Anthropic key": "sk-" + "ant-" + "a1" * 20,
    "GitHub token": "ghp_" + "a" * 36,
    "cookie": "SESSDATA = '" + "a1b2c3d4e5f6g7" + "'",
    "private key": "-----BEGIN RSA " + "PRIVATE KEY-----",
    "name": "with Zed Quux today",
    "name, spaced and upper-case": "ZED  QUUX",
    "Chinese name": "和测试人名一起",
    "regex word": "our cat Fluffy",
}
for name, text in blocked.items():
    attempt(name, True, {"a.txt": "fine\n" + text + "\n"}, secret=text)
attempt("UTF-16 file", True, {"a.txt": ("hi " + mail).encode("utf-16")}, secret=mail)
attempt("inside a binary", True, {"a.bin": b"\0\1\2" + b"padding " + mail.encode() + b"\0"}, secret=mail)
attempt("file name", True, {"notes/Zed Quux.txt": "x\n"})
attempt("Chinese file name", True, {"测试人名.txt": "x\n"})
attempt("sessions/ folder", True, {"sessions/x.md": "x\n"})
attempt("docs/ folder", True, {"docs/x.md": "x\n"})
attempt(".env", True, {".env": "A=1\n"})
attempt("commit message", True, msg="thanks Zed Quux", secret="Zed Quux")
attempt("commit message starting with #", True, msg="# Zed Quux", secret="Zed Quux")
attempt("author email", True, env={"GIT_AUTHOR_EMAIL": mail}, secret=mail)


def photo(gps):
    im, f, ex = Image.new("RGB", (8, 8)), TMP / "p.jpg", Image.Exif()
    if gps:
        ex.get_ifd(0x8825).update({1: "N", 2: (40.0, 1.0, 2.0)})
    im.save(f, exif=ex)
    return f.read_bytes()


attempt("photo with GPS", True, {"p.jpg": photo(True)})
attempt("video with GPS", True, {"v.mp4": b"\0\0\0\x18ftyp" + b"\xa9xyz+40.0-074.0/"})
attempt("broken photo (fails closed)", True, {"p.jpg": b"not a photo"})

attempt("plain text", False)
attempt("photo without GPS", False, {"p.jpg": photo(False)})
attempt("noreply and example emails", False, {"a.txt": f"x{AT}example.com 1+a{AT}users.noreply.github.com git{AT}github.com\n"})
attempt("allowed email", False, {"a.txt": f"ok{AT}allowed.io\n"})
attempt("Co-Authored-By line", False, msg=f"change\n\nCo-Authored-By: Claude <noreply{AT}anthropic.com>")
attempt("numbers that aren't personal", False, {"a.txt": "t=1234567890.12 2026-11-24 1080-1920 0.4111111111111111 id 1731234567890 UTC-05:00 123-45\n"})
attempt("decorators and handles", False, {"a.py": "@property\ndef f(): ...\n# x.com/@someone\n"})

# an old line is not re-flagged, but a new one in the same file is
git("config", "--unset", "core.hooksPath")
(REPO / "old.txt").write_text(mail + "\n")
git("add", "-A")
git("commit", "-qm", "legacy")
git("config", "core.hooksPath", ".githooks")
attempt("edit beside an old line", False, {"old.txt": mail + "\nnew line\n"})
attempt("repeat of an old line", True, {"old.txt": mail + "\nnew line\n" + mail + "\n"}, secret=mail)

# removing personal info must be possible
(REPO / "old.txt").write_text("clean\n")
git("add", "-A")
r = git("commit", "-m", "remove it")
print("ok  " if not r.returncode else "FAIL", "放 removing a personal line")
fails += ["removing"] if r.returncode else []

# commit -a, --amend and a merge all go through the hook
(REPO / "a.txt").write_text("fine\n")
git("add", "-A"), git("commit", "-qm", "ok")
(REPO / "a.txt").write_text(mail + "\n")
for name, args in (("commit -am", ("commit", "-am", "x")), ("commit --amend", ("commit", "-a", "--amend", "-m", "x"))):
    r = git(*args)
    print("ok  " if r.returncode else "FAIL", "拦", name)
    fails += [] if r.returncode else [name]
git("reset", "-q", "--hard")
git("checkout", "-qb", "side")
(REPO / "side.txt").write_text(mail + "\n")
git("add", "-A"), git("commit", "-q", "--no-verify", "-m", "side")
git("checkout", "-q", "main")
r = git("merge", "--no-ff", "-m", "merge", "side")
print("ok  " if r.returncode else "FAIL", "拦 merge")
fails += [] if r.returncode else ["merge"]
git("merge", "--abort"), git("reset", "-q", "--hard")

TERMS.rename(TMP / "gone.txt")
attempt("word list missing (fails closed)", True)

shutil.rmtree(TMP)
print("FAILED: " + ", ".join(fails) if fails else "all passed")
sys.exit(bool(fails))
