"""Analytics tracker for fetching YouTube performance data."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from googleapiclient.errors import HttpError


class AnalyticsTracker:
    """Tracks YouTube analytics data and stores historical records."""

    def __init__(self, youtube_service, data_dir: str = "data"):
        """
        Initialize analytics tracker.

        Args:
            youtube_service: Authenticated YouTube API service
            data_dir: Directory to store analytics data
        """
        self.youtube = youtube_service
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.analytics_file = self.data_dir / "analytics_history.json"
        self.history = self._load_history()

    def _load_history(self) -> Dict:
        """Load historical analytics data."""
        if self.analytics_file.exists():
            with open(self.analytics_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"snapshots": [], "videos": {}}

    def _save_history(self):
        """Save analytics history to file."""
        with open(self.analytics_file, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)

    def fetch_channel_analytics(self, days: int = 28) -> Dict:
        """
        Fetch channel-level analytics for the specified time period.

        Args:
            days: Number of days to look back (default 28)

        Returns:
            Dictionary with channel analytics
        """
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)

        try:
            # Fetch channel statistics
            channels_response = self.youtube.channels().list(
                part='statistics,snippet',
                mine=True
            ).execute()

            if not channels_response.get('items'):
                raise Exception("No channel found")

            channel = channels_response['items'][0]
            stats = channel['statistics']

            # YouTube Analytics API reports (requires YouTube Analytics API enabled)
            try:
                analytics = self.youtube.reports().query(
                    ids='channel==MINE',
                    startDate=start_date.isoformat(),
                    endDate=end_date.isoformat(),
                    metrics='views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost',
                    dimensions='day'
                ).execute()

                analytics_data = analytics.get('rows', [])
            except (HttpError, AttributeError):
                # Analytics API not available, use basic stats only
                analytics_data = []

            return {
                'channel_id': channel['id'],
                'channel_title': channel['snippet']['title'],
                'total_subscribers': int(stats.get('subscriberCount', 0)),
                'total_views': int(stats.get('viewCount', 0)),
                'total_videos': int(stats.get('videoCount', 0)),
                'period_days': days,
                'period_start': start_date.isoformat(),
                'period_end': end_date.isoformat(),
                'daily_analytics': analytics_data,
                'fetched_at': datetime.now().isoformat()
            }

        except Exception as e:
            raise Exception(f"Error fetching channel analytics: {e}")

    def fetch_video_analytics(self, video_ids: Optional[List[str]] = None, limit: int = 50) -> List[Dict]:
        """
        Fetch detailed analytics for videos.

        Args:
            video_ids: Specific video IDs to fetch (if None, fetches recent videos)
            limit: Maximum number of videos to fetch

        Returns:
            List of video analytics dictionaries
        """
        try:
            if not video_ids:
                # Fetch recent videos
                search_response = self.youtube.search().list(
                    part='id',
                    forMine=True,
                    type='video',
                    order='date',
                    maxResults=limit
                ).execute()

                video_ids = [item['id']['videoId'] for item in search_response.get('items', [])]

            if not video_ids:
                return []

            # Fetch video statistics
            videos_response = self.youtube.videos().list(
                part='statistics,snippet,contentDetails',
                id=','.join(video_ids[:50])  # API limit is 50
            ).execute()

            videos_data = []
            for video in videos_response.get('items', []):
                stats = video['statistics']
                snippet = video['snippet']

                video_data = {
                    'video_id': video['id'],
                    'title': snippet['title'],
                    'published_at': snippet['publishedAt'],
                    'views': int(stats.get('viewCount', 0)),
                    'likes': int(stats.get('likeCount', 0)),
                    'comments': int(stats.get('commentCount', 0)),
                    'duration': video['contentDetails']['duration'],
                    'fetched_at': datetime.now().isoformat()
                }

                # Calculate engagement rate
                if video_data['views'] > 0:
                    video_data['engagement_rate'] = (
                        (video_data['likes'] + video_data['comments']) / video_data['views'] * 100
                    )
                else:
                    video_data['engagement_rate'] = 0

                videos_data.append(video_data)

            return videos_data

        except Exception as e:
            raise Exception(f"Error fetching video analytics: {e}")

    def save_snapshot(self, channel_data: Dict, videos_data: List[Dict]):
        """
        Save a snapshot of current analytics.

        Args:
            channel_data: Channel analytics data
            videos_data: List of video analytics data
        """
        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'channel': channel_data,
            'video_count': len(videos_data),
            'total_views': sum(v['views'] for v in videos_data),
            'total_engagement': sum(v['likes'] + v['comments'] for v in videos_data),
            'avg_engagement_rate': sum(v['engagement_rate'] for v in videos_data) / len(videos_data) if videos_data else 0
        }

        self.history['snapshots'].append(snapshot)

        # Update video history
        for video in videos_data:
            video_id = video['video_id']
            if video_id not in self.history['videos']:
                self.history['videos'][video_id] = {
                    'title': video['title'],
                    'published_at': video['published_at'],
                    'snapshots': []
                }

            self.history['videos'][video_id]['snapshots'].append({
                'timestamp': datetime.now().isoformat(),
                'views': video['views'],
                'likes': video['likes'],
                'comments': video['comments'],
                'engagement_rate': video['engagement_rate']
            })

        self._save_history()

    def get_growth_metrics(self, days: int = 7) -> Dict:
        """
        Calculate growth metrics over the specified period.

        Args:
            days: Number of days to calculate growth

        Returns:
            Dictionary with growth metrics
        """
        if len(self.history['snapshots']) < 2:
            return {
                'insufficient_data': True,
                'message': 'Need at least 2 snapshots to calculate growth'
            }

        # Get recent snapshots within the time period
        cutoff_time = datetime.now() - timedelta(days=days)
        recent_snapshots = [
            s for s in self.history['snapshots']
            if datetime.fromisoformat(s['timestamp']) >= cutoff_time
        ]

        if len(recent_snapshots) < 2:
            recent_snapshots = self.history['snapshots'][-2:]

        oldest = recent_snapshots[0]
        newest = recent_snapshots[-1]

        # Calculate growth
        views_growth = newest['total_views'] - oldest['total_views']
        engagement_growth = newest['total_engagement'] - oldest['total_engagement']

        # Subscriber growth
        old_subs = oldest['channel'].get('total_subscribers', 0)
        new_subs = newest['channel'].get('total_subscribers', 0)
        sub_growth = new_subs - old_subs

        return {
            'period_days': days,
            'views_growth': views_growth,
            'engagement_growth': engagement_growth,
            'subscriber_growth': sub_growth,
            'old_total_views': oldest['total_views'],
            'new_total_views': newest['total_views'],
            'old_subscribers': old_subs,
            'new_subscribers': new_subs,
            'snapshots_compared': len(recent_snapshots)
        }

    def get_top_performing_videos(self, metric: str = 'views', limit: int = 10) -> List[Dict]:
        """
        Get top performing videos by specified metric.

        Args:
            metric: Metric to sort by ('views', 'likes', 'engagement_rate')
            limit: Number of videos to return

        Returns:
            List of top performing videos
        """
        videos_with_latest = []

        for video_id, video_data in self.history['videos'].items():
            if video_data['snapshots']:
                latest = video_data['snapshots'][-1]
                videos_with_latest.append({
                    'video_id': video_id,
                    'title': video_data['title'],
                    'published_at': video_data['published_at'],
                    **latest
                })

        # Sort by specified metric
        videos_with_latest.sort(key=lambda x: x.get(metric, 0), reverse=True)

        return videos_with_latest[:limit]

    def get_underperforming_videos(self, threshold_percentile: int = 25, limit: int = 10) -> List[Dict]:
        """
        Identify underperforming videos below the threshold percentile.

        Args:
            threshold_percentile: Percentile threshold (e.g., 25 for bottom 25%)
            limit: Maximum videos to return

        Returns:
            List of underperforming videos
        """
        videos_with_latest = []

        for video_id, video_data in self.history['videos'].items():
            if video_data['snapshots']:
                latest = video_data['snapshots'][-1]
                videos_with_latest.append({
                    'video_id': video_id,
                    'title': video_data['title'],
                    'published_at': video_data['published_at'],
                    **latest
                })

        if not videos_with_latest:
            return []

        # Calculate threshold
        views = sorted([v['views'] for v in videos_with_latest])
        threshold_index = int(len(views) * threshold_percentile / 100)
        threshold_views = views[threshold_index] if threshold_index < len(views) else views[0]

        # Filter underperforming
        underperforming = [v for v in videos_with_latest if v['views'] <= threshold_views]
        underperforming.sort(key=lambda x: x['views'])

        return underperforming[:limit]
