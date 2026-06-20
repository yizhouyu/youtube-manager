#!/bin/bash
# preprocess_video.sh "<project folder>"
#
# Pre-processes a finished vlog so a later review is fast: extracts the audio and
# transcribes it (whisper.cpp, Chinese), and lays down a coarse contact sheet of
# frames. Writes into the folder's "02 - Export/" dir:
#   - audio_16k.wav       (mono 16k, whisper input)
#   - transcript.txt      (auto transcript — has ASR errors, infer proper nouns)
#   - thumbnail/scan/*    (12 evenly-spaced frames)
#   - thumbnail/_scan.jpg (contact sheet to eyeball the whole arc)
#
# Idempotent: skips audio/transcript if already present. Ignores "01 - Unedited".
# Requires: ffmpeg, ffprobe, whisper-cli (brew install whisper-cpp) + a ggml model.
set -euo pipefail

DIR="${1:?usage: preprocess_video.sh \"<project folder>\"}"
EXP="$DIR/02 - Export"
MODEL="$(cd "$(dirname "$0")/.." && pwd)/models/ggml-small.bin"

V="$(find "$EXP" -maxdepth 1 \( -iname '*.mov' -o -iname '*.mp4' \) 2>/dev/null | head -1)"
if [ -z "$V" ]; then echo "[skip] no export video in: $DIR"; exit 0; fi
if [ ! -f "$MODEL" ]; then echo "[err] whisper model not found: $MODEL"; exit 1; fi

echo "[preprocess] $DIR"
cd "$EXP"

# 1) audio
if [ ! -f audio_16k.wav ]; then
  echo "  - extracting audio"
  ffmpeg -nostdin -loglevel error -i "$V" -ac 1 -ar 16000 -vn audio_16k.wav -y
fi

# 2) transcript
if [ ! -f transcript.txt ]; then
  echo "  - transcribing (whisper, zh)"
  whisper-cli -m "$MODEL" -f audio_16k.wav -l zh -otxt -of transcript >/dev/null 2>&1
fi

# 3) coarse frame scan
DUR="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$V")"
mkdir -p thumbnail/scan
N=12
for i in $(seq 1 $N); do
  T="$(awk "BEGIN{printf \"%.1f\", 15 + ($DUR-30)*($i-1)/($N-1)}")"
  ffmpeg -nostdin -loglevel error -ss "$T" -i "$V" -frames:v 1 -q:v 2 \
    "thumbnail/scan/$(printf %02d "$i")_t${T%.*}s.jpg" -y
done
ffmpeg -nostdin -loglevel error -pattern_type glob -i "thumbnail/scan/*.jpg" \
  -filter_complex "scale=420:-1,tile=4x3:padding=6:margin=6" -frames:v 1 thumbnail/_scan.jpg -y

echo "[done] $DIR  (dur ${DUR%.*}s, transcript $(wc -m < transcript.txt | tr -d ' ') chars)"
