#!/bin/bash
# transcribe_accurate.sh "<project folder>"
#
# High-accuracy transcription for captions. Three accuracy levers on top of a strong model:
#   1. large-v3-turbo model (NOT small)
#   2. --prompt glossary priming  — reads "02 - Export/glossary.txt" (proper nouns: places,
#      dishes, brands) and feeds it as the initial prompt so the model spells names right.
#   3. --vad  — Voice Activity Detection kills hallucinated repetition in music/silence.
# Also -mc 0 (no prior-context bleed) + beam search to cut loops.
# Writes "02 - Export/captions_raw.srt" (still needs a frame-grounded LLM cleanup pass).
set -euo pipefail
DIR="${1:?usage: transcribe_accurate.sh \"<project folder>\"}"
# Resolve a bare project name: try cwd first, then ~/Desktop (projects live there).
# Without this, running from the repo dir makes "NN - Name" resolve under the repo
# (not the Desktop) and the script silently finds nothing.
if [ ! -d "$DIR" ] && [ -d "$HOME/Desktop/$DIR" ]; then DIR="$HOME/Desktop/$DIR"; fi
if [ ! -d "$DIR" ]; then echo "[err] project folder not found: $1 (looked in cwd and ~/Desktop)"; exit 1; fi
EXP="$DIR/02 - Export"
if [ ! -d "$EXP" ]; then echo "[err] no '02 - Export' dir in: $DIR"; exit 1; fi
MODELS="$(cd "$(dirname "$0")/.." && pwd)/models"
# Prefer the most accurate model the machine has: full large-v3 > turbo (quantized).
if [ -f "$MODELS/ggml-large-v3.bin" ]; then MODEL="$MODELS/ggml-large-v3.bin"
else MODEL="$MODELS/ggml-large-v3-turbo-q5_0.bin"; fi
VAD="$MODELS/ggml-silero-vad.bin"

V="$(find "$EXP" -maxdepth 1 \( -iname '*.mov' -o -iname '*.mp4' \) 2>/dev/null | head -1)"
[ -z "$V" ] && { echo "[err] no export video (.mov/.mp4) in: $EXP"; exit 1; }
[ -f "$EXP/audio_16k.wav" ] || ffmpeg -nostdin -loglevel error -i "$V" -ac 1 -ar 16000 -vn "$EXP/audio_16k.wav" -y

PROMPT=""
[ -f "$EXP/glossary.txt" ] && PROMPT="$(tr '\n' ' ' < "$EXP/glossary.txt")"

ARGS=(-m "$MODEL" -f "$EXP/audio_16k.wav" -l zh -osrt -of "$EXP/captions_raw"
      -ng -bs 5 -bo 5 -mc 0 --carry-initial-prompt)   # -ng = CPU (Metal crashes on exit cleanup)
[ -n "$PROMPT" ] && ARGS+=(--prompt "$PROMPT")
[ -f "$VAD" ] && ARGS+=(--vad --vad-model "$VAD")

echo "[transcribe] $DIR  (prompt: ${PROMPT:0:60}...)"
whisper-cli "${ARGS[@]}" >/dev/null 2>&1
echo "[done] $(wc -l < "$EXP/captions_raw.srt" | tr -d ' ') lines -> captions_raw.srt"
