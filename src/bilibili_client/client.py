"""Bilibili API client for video operations."""

import requests
from typing import List, Dict, Optional
import time


class BilibiliClient:
    """Client for interacting with Bilibili APIs."""

    def __init__(self, sessdata: str, bili_jct: str):
        """
        Initialize the Bilibili client.

        Args:
            sessdata: SESSDATA cookie value from Bilibili
            bili_jct: bili_jct cookie value (CSRF token)
        """
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.cookies = {
            'SESSDATA': sessdata,
            'bili_jct': bili_jct
        }
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://member.bilibili.com/'
        }

    def get_user_videos(self) -> List[Dict]:
        """
        Fetch all videos from the authenticated user's channel.

        Returns:
            List of video dictionaries with bvid, title, description, tags, etc.

        Raises:
            Exception: If unable to retrieve videos
        """
        videos = []
        page_num = 1
        page_size = 30

        try:
            while True:
                # API endpoint for getting user's uploaded videos
                url = 'https://member.bilibili.com/x/web/archives'
                params = {
                    'pn': page_num,
                    'ps': page_size,
                    'coop': 1,
                    'status': 'is_pubing,pubed,not_pubed',
                    'interactive': 1
                }

                response = requests.get(
                    url,
                    params=params,
                    cookies=self.cookies,
                    headers=self.headers,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()

                if data.get('code') != 0:
                    raise Exception(f"Bilibili API error: {data.get('message', 'Unknown error')}")

                page_data = data.get('data', {})
                arc_audits = page_data.get('arc_audits', [])

                if not arc_audits:
                    break

                for item in arc_audits:
                    archive = item.get('Archive', {})
                    video_info = {
                        'bvid': archive.get('bvid'),
                        'aid': archive.get('aid'),
                        'title': archive.get('title'),
                        'description': archive.get('desc', ''),
                        'tags': archive.get('tag', '').split(',') if archive.get('tag') else [],
                        'cover': archive.get('cover'),
                        'duration': archive.get('duration'),
                        'pubdate': archive.get('pubdate'),
                        'state': archive.get('state'),
                        'typeid': archive.get('typeid'),
                        'copyright': archive.get('copyright')
                    }
                    videos.append(video_info)

                # Check if we've reached the last page
                if len(arc_audits) < page_size:
                    break

                page_num += 1
                time.sleep(0.5)  # Rate limiting

            print(f"Successfully fetched {len(videos)} videos from Bilibili.")
            return videos

        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching Bilibili videos: {e}")
        except Exception as e:
            raise Exception(f"Error processing Bilibili response: {e}")

    def get_video_details(self, bvid: str) -> Dict:
        """
        Get detailed information for a specific video.

        Args:
            bvid: Bilibili video ID (BV format)

        Returns:
            Dictionary with video metadata

        Raises:
            Exception: If unable to retrieve video details
        """
        try:
            url = 'https://api.bilibili.com/x/web-interface/view'
            params = {'bvid': bvid}

            response = requests.get(
                url,
                params=params,
                cookies=self.cookies,
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if data.get('code') != 0:
                raise Exception(f"Bilibili API error: {data.get('message', 'Unknown error')}")

            video_data = data.get('data', {})
            return {
                'bvid': video_data.get('bvid'),
                'aid': video_data.get('aid'),
                'title': video_data.get('title'),
                'description': video_data.get('desc', ''),
                'tags': [tag.get('tag_name') for tag in video_data.get('tag', [])],
                'cover': video_data.get('pic'),
                'duration': video_data.get('duration'),
                'pubdate': video_data.get('pubdate'),
                'copyright': video_data.get('copyright'),
                'typeid': video_data.get('tid')
            }

        except Exception as e:
            raise Exception(f"Error fetching video details for {bvid}: {e}")

    def update_video_metadata(
        self,
        aid: int,
        title: str,
        description: str,
        tags: List[str],
        cover: Optional[str] = None,
        typeid: Optional[int] = None,
        copyright: Optional[int] = None
    ) -> bool:
        """
        Update metadata for a video.

        IMPORTANT: This method is currently experimental. Bilibili's video edit API
        requires complex parameters including video part information (cid, filename, etc.)
        which are not easily accessible. For reliable updates, use the
        `generate_update_data()` method to create data for manual updates via Bilibili's
        web interface.

        API Findings (as of 2025):
        - Endpoint: https://member.bilibili.com/x/vu/web/edit (NOT /v2)
        - Method: POST with JSON payload (not form data)
        - Auth: CSRF token as query parameter (?csrf={bili_jct})
        - Required fields: aid, title, desc, tag, cover, tid, copyright, desc_format_id
        - Complex requirement: videos array with cid/filename for each video part

        Args:
            aid: Video AV ID (numeric ID, not BV)
            title: New title (max 80 characters)
            description: New description
            tags: New tags list (max 10 tags)
            cover: Cover image URL (optional)
            typeid: Category ID (optional)
            copyright: Copyright type: 1=original, 2=repost (optional)

        Returns:
            True if successful

        Raises:
            Exception: If update fails or API requirements not met
        """
        try:
            # Validate inputs
            if len(title) > 80:
                raise ValueError(f"Title too long: {len(title)} chars (max 80)")

            if len(tags) > 10:
                raise ValueError(f"Too many tags: {len(tags)} (max 10)")

            # Get current video info to fill missing fields
            current = self.get_video_details_by_aid(aid)

            # Correct endpoint (no /v2)
            url = 'https://member.bilibili.com/x/vu/web/edit'

            # Build JSON payload with desc_format_id
            payload = {
                'aid': aid,
                'title': title,
                'desc': description,
                'tag': ','.join(tags),
                'desc_format_id': 31,  # Required for proper formatting
                'tid': typeid if typeid else current.get('typeid'),
                'cover': cover if cover else current.get('cover'),
                'copyright': copyright if copyright else current.get('copyright')
            }

            # CSRF must be query parameter, not in body
            url_with_csrf = f"{url}?csrf={self.bili_jct}"

            # Send as JSON (not form data)
            headers = {
                **self.headers,
                'Content-Type': 'application/json'
            }

            response = requests.post(
                url_with_csrf,
                json=payload,  # JSON payload, not data
                cookies=self.cookies,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if data.get('code') != 0:
                error_msg = data.get('message', 'Unknown error')
                error_code = data.get('code')

                # Common error codes
                if error_code == -111:
                    raise Exception(f"CSRF verification failed. Please refresh your Bilibili cookies.")
                elif error_code == 21001:
                    raise Exception(f"Parameter error: {error_msg}. API may require additional video part data.")
                elif error_code == 21011:
                    raise Exception(f"Video parts data required: {error_msg}. Use manual sync for now.")
                elif error_code == 21015:
                    raise Exception(f"Video upload issue: {error_msg}. Cannot edit without proper video data.")
                else:
                    raise Exception(f"Bilibili API error (code {error_code}): {error_msg}")

            print(f"Successfully updated Bilibili video: {aid}")
            return True

        except Exception as e:
            raise Exception(f"Error updating video metadata: {e}")

    def generate_update_data(
        self,
        aid: int,
        title: str,
        description: str,
        tags: List[str]
    ) -> Dict:
        """
        Generate update data for manual copy-paste into Bilibili's web interface.

        This is the recommended method until the automated API is fully working.

        Args:
            aid: Video AV ID
            title: New title
            description: New description
            tags: New tags

        Returns:
            Dictionary with formatted data ready for manual update
        """
        current = self.get_video_details_by_aid(aid)

        return {
            'bvid': current['bvid'],
            'aid': aid,
            'title': title[:80],  # Bilibili max title length
            'description': description[:250] if len(description) > 250 else description,
            'tags': ', '.join(tags[:10]),  # Bilibili max 10 tags
            'edit_link': f"https://member.bilibili.com/platform/upload/video/frame?aid={aid}",
            'view_link': f"https://www.bilibili.com/video/{current['bvid']}"
        }

    def get_video_details_by_aid(self, aid: int) -> Dict:
        """
        Get detailed information for a video by AID.

        Args:
            aid: Video AV ID (numeric)

        Returns:
            Dictionary with video metadata
        """
        try:
            url = 'https://api.bilibili.com/x/web-interface/view'
            params = {'aid': aid}

            response = requests.get(
                url,
                params=params,
                cookies=self.cookies,
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            if data.get('code') != 0:
                raise Exception(f"Bilibili API error: {data.get('message', 'Unknown error')}")

            video_data = data.get('data', {})
            return {
                'bvid': video_data.get('bvid'),
                'aid': video_data.get('aid'),
                'title': video_data.get('title'),
                'description': video_data.get('desc', ''),
                'tags': [tag.get('tag_name') for tag in video_data.get('tag', [])],
                'cover': video_data.get('pic'),
                'duration': video_data.get('duration'),
                'pubdate': video_data.get('pubdate'),
                'copyright': video_data.get('copyright'),
                'typeid': video_data.get('tid')
            }

        except Exception as e:
            raise Exception(f"Error fetching video details for aid {aid}: {e}")
