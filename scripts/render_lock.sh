#!/bin/bash
# Run a heavy job (render / bake / Demucs / whisper) only when no other heavy job is running.
# Usage: scripts/render_lock.sh <command> [args...]
# Waits for the machine-wide lock (a directory, atomic mkdir), runs the command, releases on exit.
# A lock left by a dead process (pid file gone stale) is cleared automatically.
LOCK=/tmp/yt-heavy-job.lock
while ! mkdir "$LOCK" 2>/dev/null; do
  pid=$(cat "$LOCK/pid" 2>/dev/null)
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then rm -rf "$LOCK"; continue; fi
  sleep 15
done
echo $$ > "$LOCK/pid"
echo "$*" > "$LOCK/cmd"
trap 'rm -rf "$LOCK"' EXIT INT TERM
"$@"
