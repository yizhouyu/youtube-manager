"""YouTube Data API client for video operations."""

from typing import List, Dict, Optional
from googleapiclient.errors import HttpError


class YouTubeClient:
    """Client for interacting with YouTube Data API v3."""

    def __init__(self, youtube_service):
        """
        Initialize the YouTube client.

        Args:
            youtube_service: Authenticated YouTube API service object
        """
        self.youtube = youtube_service

    def get_channel_id(self) -> str:
        """
        Get the authenticated user's channel ID.

        Returns:
            Channel ID string

        Raises:
            Exception: If unable to retrieve channel information
        """
        try:
            request = self.youtube.channels().list(
                part='id',
                mine=True
            )
            response = request.execute()

            if 'items' in response and len(response['items']) > 0:
                return response['items'][0]['id']
            else:
                raise Exception("No channel found for the authenticated user.")

        except HttpError as e:
            raise Exception(f"Error retrieving channel ID: {e}")

    def get_all_channel_videos(self, channel_id: Optional[str] = None) -> List[Dict]:
        """
        Fetch all videos from a channel.

        Args:
            channel_id: Channel ID (if None, uses authenticated user's channel)

        Returns:
            List of video dictionaries with id, title, description, tags, etc.
        """
        if channel_id is None:
            channel_id = self.get_channel_id()

        videos = []
        page_token = None

        print(f"Fetching videos from channel: {channel_id}")

        try:
            # First, get all video IDs using search endpoint
            video_ids = []
            while True:
                search_request = self.youtube.search().list(
                    part='id',
                    channelId=channel_id,
                    maxResults=50,
                    type='video',
                    pageToken=page_token
                )
                search_response = search_request.execute()

                for item in search_response.get('items', []):
                    if item['id']['kind'] == 'youtube#video':
                        video_id = item['id']['videoId']
                        # Deduplicate: YouTube Search API can return same video multiple times
                        if video_id not in video_ids:
                            video_ids.append(video_id)

                page_token = search_response.get('nextPageToken')
                if not page_token:
                    break

            print(f"Found {len(video_ids)} unique videos. Fetching details...")

            # Fetch video details in batches of 50 (API limit)
            for i in range(0, len(video_ids), 50):
                batch_ids = video_ids[i:i + 50]
                videos_request = self.youtube.videos().list(
                    part='snippet,statistics,contentDetails',
                    id=','.join(batch_ids)
                )
                videos_response = videos_request.execute()

                for item in videos_response.get('items', []):
                    video_data = {
                        'id': item['id'],
                        'title': item['snippet']['title'],
                        'description': item['snippet']['description'],
                        'tags': item['snippet'].get('tags', []),
                        'categoryId': item['snippet']['categoryId'],
                        'publishedAt': item['snippet']['publishedAt'],
                        'defaultLanguage': item['snippet'].get('defaultLanguage'),
                        'defaultAudioLanguage': item['snippet'].get('defaultAudioLanguage'),
                        'duration': item['contentDetails'].get('duration'),
                        'viewCount': item['statistics'].get('viewCount', '0'),
                        'likeCount': item['statistics'].get('likeCount', '0'),
                    }
                    videos.append(video_data)

            print(f"Successfully fetched details for {len(videos)} videos.")
            return videos

        except HttpError as e:
            raise Exception(f"Error fetching channel videos: {e}")

    def get_video_details(self, video_id: str) -> Dict:
        """
        Get detailed information for a specific video.

        Args:
            video_id: YouTube video ID

        Returns:
            Dictionary with video metadata
        """
        try:
            request = self.youtube.videos().list(
                part='snippet,statistics,contentDetails',
                id=video_id
            )
            response = request.execute()

            if 'items' in response and len(response['items']) > 0:
                item = response['items'][0]
                return {
                    'id': item['id'],
                    'title': item['snippet']['title'],
                    'description': item['snippet']['description'],
                    'tags': item['snippet'].get('tags', []),
                    'categoryId': item['snippet']['categoryId'],
                    'publishedAt': item['snippet']['publishedAt'],
                    'defaultLanguage': item['snippet'].get('defaultLanguage'),
                    'defaultAudioLanguage': item['snippet'].get('defaultAudioLanguage'),
                    'duration': item['contentDetails'].get('duration'),
                    'viewCount': item['statistics'].get('viewCount', '0'),
                    'likeCount': item['statistics'].get('likeCount', '0'),
                }
            else:
                raise Exception(f"Video not found: {video_id}")

        except HttpError as e:
            raise Exception(f"Error fetching video details: {e}")

    def update_video_metadata(
        self,
        video_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        category_id: Optional[str] = None
    ) -> bool:
        """
        Update metadata for a video.

        Args:
            video_id: YouTube video ID
            title: New title (required by API if updating snippet)
            description: New description
            tags: New tags list
            category_id: Category ID (required by API if updating snippet)

        Returns:
            True if successful

        Raises:
            Exception: If update fails
        """
        try:
            # First, get current video details to preserve required fields
            current = self.get_video_details(video_id)

            # Build the update request
            snippet = {
                'title': title if title is not None else current['title'],
                'description': description if description is not None else current['description'],
                'categoryId': category_id if category_id is not None else current['categoryId']
            }

            # Add tags if provided
            if tags is not None:
                snippet['tags'] = tags
            elif current.get('tags'):
                snippet['tags'] = current['tags']

            request = self.youtube.videos().update(
                part='snippet',
                body={
                    'id': video_id,
                    'snippet': snippet
                }
            )
            request.execute()
            print(f"Successfully updated video: {video_id}")
            return True

        except HttpError as e:
            raise Exception(f"Error updating video metadata: {e}")
