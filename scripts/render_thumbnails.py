#!/usr/bin/env python
"""Composite thumbnail variants for a publish session.

Reads ``<session_dir>/session.json`` and writes ``thumb_<i>.jpg`` for each entry
in ``thumbnail_options`` using the shared (LLM-free) Pillow compositor.

Usage:
    python scripts/render_thumbnails.py <session_dir> [index]

If ``index`` is given, only that one option is (re)rendered.

session.json schema (written by the publish-video skill):
{
  "id": "...",
  "video_path": "/abs/video.mp4",
  "srt_path": "/abs/captions.srt",
  "base_image_path": "/abs/base.jpg",
  "metadata_options": [
    {"title": "...", "description": "...", "tags": [...], "hashtags": [...]}
  ],
  "thumbnail_options": [
    {"main_text": "震撼!", "subtitle": "...", "text_color": "#FFFFFF",
     "outline_color": "#000000", "position": "top", "font_size_main": 120}
  ]
}
"""

import os
import sys

# Make the project root importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.thumbnail_generator.compositor import render_session


def main():
    if len(sys.argv) < 2:
        print("Usage: render_thumbnails.py <session_dir> [index]", file=sys.stderr)
        sys.exit(1)

    session_dir = sys.argv[1]
    only_index = int(sys.argv[2]) if len(sys.argv) > 2 else None

    written = render_session(session_dir, only_index=only_index)
    for path in written:
        print(f"[render] wrote {os.path.basename(path)}")
    print(f"[render] {len(written)} thumbnail(s) in {os.path.abspath(session_dir)}")


if __name__ == "__main__":
    main()
