"""One ASR model at a time on this machine (a 16 GB Mac can't hold two).

    with asr_lock():            # blocks until the lock is free
        model = load_model(...)

CLI, to wrap any other ASR command (whisper, a one-off Qwen script, ...):

    python -m src.editor.asrlock -- <command> [args...]

The lock is a directory (mkdir is atomic) at /tmp/yt-editor-asr.lock holding the owner's pid.
A lock left by a dead process is taken over. A plain file, or a directory without a pid (hand-made
locks), also counts as held and is cleared only once it is older than STALE_FILE_S.
"""
import contextlib
import os
import subprocess
import sys
import time

LOCK = "/tmp/yt-editor-asr.lock"
STALE_FILE_S = 3 * 3600


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stale():
    if os.path.isfile(LOCK):
        return time.time() - os.path.getmtime(LOCK) > STALE_FILE_S
    try:
        pid = int(open(os.path.join(LOCK, "pid")).read().strip())
    except (OSError, ValueError):
        # a dir without a pid (made by hand with mkdir): stale only when very old
        return os.path.isdir(LOCK) and time.time() - os.path.getmtime(LOCK) > STALE_FILE_S
    return not _alive(pid)


def _clear():
    try:
        if os.path.isfile(LOCK):
            os.remove(LOCK)
        else:
            with contextlib.suppress(OSError):
                os.remove(os.path.join(LOCK, "pid"))
            os.rmdir(LOCK)
    except OSError:
        pass


@contextlib.contextmanager
def asr_lock(poll=10, quiet=False):
    if os.environ.get("YT_ASR_LOCK_HELD") == "1":  # a parent `asrlock --` already holds it
        yield
        return
    waited = False
    while True:
        try:
            os.mkdir(LOCK)
            break
        except FileExistsError:
            if _stale():
                _clear()
                continue
            if not quiet and not waited:
                print("[asr] waiting for the ASR lock …", flush=True)
            waited = True
            time.sleep(poll)
    try:
        with open(os.path.join(LOCK, "pid"), "w") as f:
            f.write(str(os.getpid()))
        yield
    finally:
        _clear()


def main():
    args = sys.argv[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        sys.exit("usage: python -m src.editor.asrlock -- <command> [args...]")
    with asr_lock():
        env = dict(os.environ, YT_ASR_LOCK_HELD="1")  # so a wrapped transcribe.py doesn't deadlock
        sys.exit(subprocess.call(args, env=env))


if __name__ == "__main__":
    main()
