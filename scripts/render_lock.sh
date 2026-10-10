#!/bin/bash
# Run a heavy job (render / bake / Demucs / whisper) only when no other heavy job is running.
# Usage: [PRIO=1|2|3] scripts/render_lock.sh <command> [args...]
# PRIO 1 = most important (default 2). A waiting job never takes the lock while a more important
# job is waiting. Lock = atomic mkdir; a lock or wait marker left by a dead process is cleared.
LOCK=/tmp/yt-heavy-job.lock
WAITDIR=/tmp/yt-heavy-job.wait
PRIO=${PRIO:-2}
mkdir -p "$WAITDIR"
ME="$WAITDIR/$PRIO.$$"
touch "$ME"
cleanup() { rm -f "$ME"; [ "$(cat "$LOCK/pid" 2>/dev/null)" = "$$" ] && rm -rf "$LOCK"; }
trap cleanup EXIT INT TERM
higher_waiting() {
  for f in "$WAITDIR"/*; do
    [ -e "$f" ] || continue
    b=$(basename "$f"); p=${b%%.*}; pid=${b#*.}
    kill -0 "$pid" 2>/dev/null || { rm -f "$f"; continue; }
    [ "$p" -lt "$PRIO" ] && return 0
  done
  return 1
}
while :; do
  if [ -d "$LOCK" ]; then
    pid=$(cat "$LOCK/pid" 2>/dev/null)
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then rm -rf "$LOCK"; fi
  fi
  if ! higher_waiting && mkdir "$LOCK" 2>/dev/null; then break; fi
  sleep 15
done
echo $$ > "$LOCK/pid"; echo "P$PRIO $*" > "$LOCK/cmd"; rm -f "$ME"
"$@"
