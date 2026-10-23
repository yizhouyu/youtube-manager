#!/bin/zsh
# Open one episode's review pages (raw + cut) in a NEW browser window; start their local servers if needed.
# Usage: scripts/review_open.sh <episode number>   (works offline — everything is local)
# Port map: 120 → 8767/8768, 121 → 8769/8770, 122 → 8771/8772, 123 → 8773 (view-only cut page, no raw page)
R="$HOME/Desktop/youtube-manager"; cd "$R" || exit 1
ep="$1"; proj=$(ls -d "$HOME/Desktop/$ep - "* 2>/dev/null | head -1)
[ -z "$proj" ] && { osascript -e "display alert \"找不到第 $ep 期的项目文件夹\""; exit 1; }
case "$ep" in
  120) raw=8767; cut=8768;; 121) raw=8769; cut=8770;; 122) raw=8771; cut=8772;; 123) raw=""; cut=8773;;
  *) raw=$((8700 + (ep % 50) * 2)); cut=$((raw + 1));;
esac
up() { curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$1/"; }
# one episode at a time: stop the other episodes' review servers (comments are already saved on disk)
for p in 8765 8766 8767 8768 8769 8770 8771 8772 8773; do
  [ "$p" = "$raw" ] || [ "$p" = "$cut" ] && continue
  pids=$(lsof -ti tcp:$p -sTCP:LISTEN 2>/dev/null); [ -n "$pids" ] && kill $pids 2>/dev/null
done
start() {  # start <port> <module>
  up "$1" && return
  nohup ./venv/bin/python -m "src.editor.$2" "$proj" --port "$1" > "/tmp/review_$1.log" 2>&1 &
}
[ -n "$raw" ] && start "$raw" footage_player
start "$cut" review_server
for i in {1..60}; do { [ -z "$raw" ] || up "$raw"; } && up "$cut" && break; sleep 0.5; done
urls=(); [ -n "$raw" ] && urls+=("http://127.0.0.1:$raw/"); urls+=("http://127.0.0.1:$cut/")
[ -n "$NOOPEN" ] && { echo "would open: ${urls[*]}"; exit 0; }
if [ -d "/Applications/Google Chrome.app" ]; then
  open -na "Google Chrome" --args --new-window "${urls[@]}"
else
  open "${urls[@]}"
fi
