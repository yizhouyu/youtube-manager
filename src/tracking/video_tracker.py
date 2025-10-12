"""Video processing tracker to avoid re-processing videos."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


class VideoTracker:
    """Tracks which videos have been processed to avoid duplicates."""

    def __init__(self, tracking_file: str = 'processed_videos.json'):
        """
        Initialize the video tracker.

        Args:
            tracking_file: Path to JSON file for storing processed video IDs
        """
        self.tracking_file = Path(tracking_file)
        self.processed_videos = self._load_tracking_data()

    def _load_tracking_data(self) -> Dict:
        """Load tracking data from JSON file."""
        if self.tracking_file.exists():
            with open(self.tracking_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save_tracking_data(self):
        """Save tracking data to JSON file."""
        with open(self.tracking_file, 'w', encoding='utf-8') as f:
            json.dump(self.processed_videos, f, indent=2, ensure_ascii=False)

    def is_processed(self, video_id: str) -> bool:
        """
        Check if a video has already been processed.

        Args:
            video_id: YouTube video ID

        Returns:
            True if video has been processed, False otherwise
        """
        return video_id in self.processed_videos

    def mark_as_processed(
        self,
        video_id: str,
        title: str,
        description_preview: str,
        tags: list,
        metadata: Optional[Dict] = None
    ):
        """
        Mark a video as processed and save metadata.

        Args:
            video_id: YouTube video ID
            title: Updated video title
            description_preview: First 200 chars of description
            tags: List of tags
            metadata: Optional additional metadata
        """
        self.processed_videos[video_id] = {
            'processed_at': datetime.now().isoformat(),
            'title': title,
            'description_preview': description_preview[:200],
            'tags': tags,
            'metadata': metadata or {}
        }
        self._save_tracking_data()

    def get_processed_info(self, video_id: str) -> Optional[Dict]:
        """
        Get processing info for a video.

        Args:
            video_id: YouTube video ID

        Returns:
            Dict with processing info or None if not processed
        """
        return self.processed_videos.get(video_id)

    def get_processed_count(self) -> int:
        """Get total number of processed videos."""
        return len(self.processed_videos)

    def remove_from_tracking(self, video_id: str):
        """
        Remove a video from tracking (useful for re-processing).

        Args:
            video_id: YouTube video ID
        """
        if video_id in self.processed_videos:
            del self.processed_videos[video_id]
            self._save_tracking_data()

    def clear_all(self):
        """Clear all tracking data."""
        self.processed_videos = {}
        self._save_tracking_data()
