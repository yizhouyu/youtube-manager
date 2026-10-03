#!/bin/bash
# new_project.sh "<NN - Trip Name>" [parent dir, default ~/Desktop]
# Creates a vlog project folder from templates/vlog-project (01 - Unedited, 02 - Export/{thumbnail,shorts,edit/...}).
set -euo pipefail
NAME="${1:?usage: new_project.sh \"NN - Trip Name\" [parent dir]}"
PARENT="${2:-$HOME/Desktop}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$PARENT/$NAME"
[ -e "$DEST" ] && { echo "[err] already exists: $DEST"; exit 1; }
cp -R "$REPO/templates/vlog-project" "$DEST"
find "$DEST" -name .gitkeep -delete
echo "[ok] $DEST"
