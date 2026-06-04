"""LLM-free thumbnail compositing helpers for publish sessions.

Wraps ``ThumbnailGenerator.add_text_to_image`` (pure Pillow) so the publish-video
skill (via scripts/render_thumbnails.py) and the web app's /api/review/recompose
endpoint share one implementation.
"""

import json
import os

from .generator import ThumbnailGenerator


def hex_to_rgb(value, default=(255, 255, 255)):
    """Convert '#RRGGBB' (or 'RRGGBB') to an (r, g, b) tuple."""
    if not value:
        return default
    value = value.lstrip("#")
    if len(value) != 6:
        return default
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


def normalize_position(position):
    """Accept 'top'/'center'/'bottom' or a numeric 0.0-1.0 (str or float)."""
    if position in ("top", "center", "bottom"):
        return position
    try:
        return float(position)
    except (TypeError, ValueError):
        return "center"


def render_option(base_image_path, option, output_path, generator=None):
    """Composite a single thumbnail option onto base_image_path -> output_path."""
    generator = generator or ThumbnailGenerator()
    font_size_main = int(option.get("font_size_main", 120))
    generator.add_text_to_image(
        base_image_path,
        main_text=option.get("main_text", ""),
        subtitle=option.get("subtitle", "") or "",
        output_path=output_path,
        font_size_main=font_size_main,
        font_size_subtitle=int(option.get("font_size_subtitle", font_size_main // 2)),
        text_color=hex_to_rgb(option.get("text_color"), (255, 255, 255)),
        outline_color=hex_to_rgb(option.get("outline_color"), (0, 0, 0)),
        position=normalize_position(option.get("position", "center")),
    )
    return output_path


def load_session(session_dir):
    with open(os.path.join(session_dir, "session.json"), encoding="utf-8") as f:
        return json.load(f)


def render_session(session_dir, only_index=None):
    """Composite thumb_<i>.jpg for each thumbnail_option in the session.

    If only_index is given, render just that one (used by the recompose endpoint).
    Returns the list of written file paths.
    """
    session_dir = os.path.abspath(session_dir)
    session = load_session(session_dir)
    base_image_path = session["base_image_path"]
    options = session.get("thumbnail_options", [])
    generator = ThumbnailGenerator()

    written = []
    for i, option in enumerate(options):
        if only_index is not None and i != only_index:
            continue
        out = os.path.join(session_dir, f"thumb_{i}.jpg")
        render_option(base_image_path, option, out, generator=generator)
        written.append(out)
    return written
