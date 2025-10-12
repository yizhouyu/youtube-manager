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
        original_metadata: Dict,
        optimized_metadata: Dict,
        video_info: Optional[Dict] = None
    ):
        """
        Mark a video as processed and save both before/after metadata.

        Args:
            video_id: YouTube video ID
            original_metadata: Original metadata before optimization (title, description, tags)
            optimized_metadata: Optimized metadata after changes (title, description, tags, hashtags)
            video_info: Additional video info (publishedAt, duration, etc.)
        """
        entry = {
            'processed_at': datetime.now().isoformat(),
            'status': 'optimized',  # 'optimized' or 'tool_generated'
            'before': {
                'title': original_metadata.get('title', ''),
                'description': original_metadata.get('description', ''),
                'tags': original_metadata.get('tags', [])
            },
            'after': {
                'title': optimized_metadata.get('title', ''),
                'description': optimized_metadata.get('description', ''),
                'tags': optimized_metadata.get('tags', []),
                'hashtags': optimized_metadata.get('hashtags', [])
            }
        }

        # Add video info if provided
        if video_info:
            entry['video_info'] = {
                'published_at': video_info.get('publishedAt'),
                'duration': video_info.get('duration'),
                'view_count': video_info.get('viewCount'),
                'like_count': video_info.get('likeCount')
            }

        self.processed_videos[video_id] = entry
        self._save_tracking_data()

    def mark_as_tool_generated(self, video_id: str, title: str, video_info: Optional[Dict] = None):
        """
        Mark a video as tool-generated (created with good SEO, skip processing).

        Args:
            video_id: YouTube video ID
            title: Video title for reference
            video_info: Additional video info (publishedAt, duration, etc.)
        """
        entry = {
            'processed_at': datetime.now().isoformat(),
            'status': 'tool_generated',
            'title': title,
            'note': 'Video created with SEO tool - no optimization needed'
        }

        # Add video info if provided
        if video_info:
            entry['video_info'] = {
                'published_at': video_info.get('publishedAt'),
                'duration': video_info.get('duration'),
                'view_count': video_info.get('viewCount'),
                'like_count': video_info.get('likeCount')
            }

        self.processed_videos[video_id] = entry
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
        """Get total number of tracked videos (both optimized and tool-generated)."""
        return len(self.processed_videos)

    def get_optimized_count(self) -> int:
        """Get count of videos that were optimized."""
        # Count entries with status='optimized' OR entries without status (legacy entries)
        return sum(1 for v in self.processed_videos.values()
                  if v.get('status') == 'optimized' or v.get('status') is None)

    def get_tool_generated_count(self) -> int:
        """Get count of videos marked as tool-generated."""
        return sum(1 for v in self.processed_videos.values() if v.get('status') == 'tool_generated')

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
