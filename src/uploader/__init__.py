"""Reusable YouTube upload worker (Flask-free).

Extracted from the web app's background-thread uploader so it can be driven by
the thin review server, the CLI, or tests without any Flask dependency.
"""

from .uploader import start_upload, upload_progress

__all__ = ["start_upload", "upload_progress"]
