#!/bin/zsh
# Stop every local review/raw page server (frees memory). Comments already saved stay in each project's chat.jsonl.
pkill -f "src.editor.review_server" ; pkill -f "src.editor.footage_player"
osascript -e 'display notification "审片页服务已全部关闭" with title "审片"'
