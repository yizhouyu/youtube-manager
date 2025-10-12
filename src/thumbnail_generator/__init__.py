"""
Thumbnail Generator Module

AI-powered thumbnail generator that:
1. Uses Claude to analyze video context and suggest compelling text
2. Uses Pillow to add text overlay to user-provided images
"""

from .generator import ThumbnailGenerator

__all__ = ['ThumbnailGenerator']
