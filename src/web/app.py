"""Flask web application for YouTube Manager."""

import os
import json
import tempfile
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

from src.auth.youtube_auth import YouTubeAuthenticator
from src.youtube_client.client import YouTubeClient
from src.seo_optimizer.optimizer import BilingualSEOOptimizer
from src.analytics.tracker import AnalyticsTracker
from src.analytics.reporter import AnalyticsReporter
from src.thumbnail_generator.generator import ThumbnailGenerator


def get_authenticated_service():
    """Get authenticated YouTube service."""
    auth = YouTubeAuthenticator()
    return auth.get_youtube_service()


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB max file size
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.secret_key = os.urandom(24)

# Allowed file extensions
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}


def allowed_file(filename, allowed_extensions):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


@app.route('/')
def index():
    """Home page with navigation."""
    return render_template('index.html')


@app.route('/analytics')
def analytics_page():
    """Analytics dashboard page."""
    return render_template('analytics.html')


@app.route('/upload')
def upload_page():
    """Video upload page."""
    return render_template('upload.html')


@app.route('/api/analytics/dashboard', methods=['GET'])
def get_analytics_dashboard():
    """
    Generate analytics dashboard data.

    Returns:
        JSON with analytics data for frontend rendering
    """
    try:
        # Get authenticated YouTube service
        youtube_service = get_authenticated_service()
        youtube_client = YouTubeClient(youtube_service)
        tracker = AnalyticsTracker(youtube_service)

        # Fetch analytics data
        channel_data = tracker.fetch_channel_analytics()
        videos_data = tracker.fetch_video_analytics(limit=50)  # Fetch recent 50 videos

        # Save video analytics to history for tracker methods
        tracker.save_snapshot(channel_data, videos_data)

        growth_metrics = tracker.get_growth_metrics(days=7)
        top_videos = tracker.get_top_performing_videos(metric='views', limit=10)
        underperforming = tracker.get_underperforming_videos(threshold_percentile=25, limit=5)

        # Format data for frontend
        return jsonify({
            'success': True,
            'data': {
                'channel': {
                    'id': channel_data.get('channel_id', ''),
                    'title': channel_data.get('channel_title', ''),
                    'subscribers': channel_data.get('total_subscribers', 0),
                    'totalVideos': channel_data.get('total_videos', 0),
                    'totalViews': channel_data.get('total_views', 0),
                },
                'growth': {
                    'subscriberGrowth': growth_metrics.get('subscriber_growth', 0),
                    'viewsGrowth': growth_metrics.get('views_growth', 0),
                    'periodDays': growth_metrics.get('period_days', 7),
                },
                'recent': {
                    'videosTracked': len(videos_data),
                    'totalViews': sum(v['views'] for v in videos_data),
                    'totalLikes': sum(v['likes'] for v in videos_data),
                    'totalComments': sum(v['comments'] for v in videos_data),
                    'avgEngagement': sum(v['engagement_rate'] for v in videos_data) / len(videos_data) if videos_data else 0,
                },
                'topVideos': top_videos,
                'underperforming': underperforming,
                'timestamp': datetime.now().isoformat()
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/playlists', methods=['GET'])
def get_playlists():
    """
    Fetch all playlists for the authenticated user.

    Returns:
        JSON with list of playlists (id, title, video count)
    """
    try:
        youtube_service = get_authenticated_service()

        # Fetch all playlists
        playlists = []
        request = youtube_service.playlists().list(
            part='snippet,contentDetails',
            mine=True,
            maxResults=50
        )

        while request:
            response = request.execute()

            for item in response.get('items', []):
                playlists.append({
                    'id': item['id'],
                    'title': item['snippet']['title'],
                    'videoCount': item['contentDetails']['itemCount']
                })

            request = youtube_service.playlists().list_next(request, response)

        return jsonify({
            'success': True,
            'playlists': playlists
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/thumbnail/generate', methods=['POST'])
def generate_thumbnail():
    """
    Generate 3 AI-powered thumbnail options with text overlays.

    Expected multipart form data:
    - image: image file
    - title: video title
    - description: video description (optional)
    - location: video location (optional)

    Returns:
        JSON with 3 thumbnail options (base64 encoded images + text details)
    """
    try:
        if 'image' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No image file provided'
            }), 400

        image_file = request.files['image']
        title = request.form.get('title', '')
        description = request.form.get('description', '')
        location = request.form.get('location', None)
        language = request.form.get('language', 'zh-CN')  # Default to Simplified Chinese

        if not title:
            return jsonify({
                'success': False,
                'error': 'Title is required'
            }), 400

        # Save image temporarily
        from io import BytesIO
        image_data = BytesIO(image_file.read())

        # Generate 3 thumbnail options
        generator = ThumbnailGenerator()
        options = generator.generate_thumbnail_options(
            image_path=image_data,
            title=title,
            description=description or title,
            location=location,
            language=language
        )

        return jsonify({
            'success': True,
            'options': options
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/upload/generate-metadata', methods=['POST'])
def generate_metadata():
    """
    Generate multiple SEO-optimized metadata options for a new video.

    Expected JSON body:
    {
        "videoDescription": "What you talked about in the video",
        "locations": "Optional: locations featured",
        "numOptions": 3  // Optional: number of options to generate
    }

    Returns:
        JSON with multiple metadata options
    """
    try:
        data = request.get_json()
        video_description = data.get('videoDescription', '')
        locations = data.get('locations', '')
        num_options = data.get('numOptions', 3)

        if not video_description:
            return jsonify({
                'success': False,
                'error': 'Video description is required'
            }), 400

        # Initialize SEO optimizer
        optimizer = BilingualSEOOptimizer()

        # Generate multiple metadata options
        result = optimizer.generate_multiple_options(
            topic=video_description,
            locations=locations if locations else None,
            num_options=num_options
        )

        return jsonify({
            'success': True,
            'options': result.get('options', [])
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/upload/video', methods=['POST'])
def upload_video():
    """
    Handle video and thumbnail upload, then publish to YouTube.

    Expected multipart/form-data:
    - videoFile: Video file
    - thumbnailFile: Thumbnail image
    - title: Video title
    - description: Video description
    - tags: JSON array of tags
    - hashtags: JSON array of hashtags

    Returns:
        JSON with upload status and video URL
    """
    try:
        # Validate files
        if 'videoFile' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No video file provided'
            }), 400

        video_file = request.files['videoFile']
        thumbnail_file = request.files.get('thumbnailFile')

        if video_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No video file selected'
            }), 400

        if not allowed_file(video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            return jsonify({
                'success': False,
                'error': 'Invalid video file format'
            }), 400

        if thumbnail_file and not allowed_file(thumbnail_file.filename, ALLOWED_IMAGE_EXTENSIONS):
            return jsonify({
                'success': False,
                'error': 'Invalid thumbnail file format'
            }), 400

        # Get metadata
        title = request.form.get('title')
        description = request.form.get('description')
        tags = json.loads(request.form.get('tags', '[]'))
        hashtags = json.loads(request.form.get('hashtags', '[]'))
        privacy_status = request.form.get('privacyStatus', 'private')
        publish_at = request.form.get('publishAt')  # ISO 8601 format
        recording_date = request.form.get('recordingDate')  # YYYY-MM-DD format
        playlist_id = request.form.get('playlistId')  # Optional playlist ID

        if not title or not description:
            return jsonify({
                'success': False,
                'error': 'Title and description are required'
            }), 400

        # Save files temporarily
        video_filename = secure_filename(video_file.filename)
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
        video_file.save(video_path)

        thumbnail_path = None
        if thumbnail_file:
            thumbnail_filename = secure_filename(thumbnail_file.filename)
            thumbnail_path = os.path.join(app.config['UPLOAD_FOLDER'], thumbnail_filename)
            thumbnail_file.save(thumbnail_path)

        # Prepend hashtags to description (first 3 hashtags appear above video)
        hashtag_str = ' '.join(hashtags[:5])  # Use up to 5 hashtags
        full_description = f"{hashtag_str}\n\n{description}"

        # Upload to YouTube
        youtube_service = get_authenticated_service()

        # Prepare video metadata
        body = {
            'snippet': {
                'title': title,
                'description': full_description,
                'tags': tags,
                'categoryId': '19',  # Travel & Events category
            },
            'status': {
                'privacyStatus': privacy_status,
                'selfDeclaredMadeForKids': False,
            }
        }

        # Add recording date if provided
        if recording_date:
            # Convert YYYY-MM-DD to ISO 8601 format (YYYY-MM-DDTHH:MM:SS.sZ)
            body['recordingDetails'] = {
                'recordingDate': f"{recording_date}T12:00:00.0Z"  # Use noon UTC as default time
            }

        # Add scheduled publish time if provided
        if publish_at:
            body['status']['publishAt'] = publish_at
            body['status']['privacyStatus'] = 'private'  # Must be private for scheduled videos

        # Upload video using YouTube API
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(
            video_path,
            mimetype='video/*',
            resumable=True,
            chunksize=1024*1024  # 1MB chunks
        )

        request_upload = youtube_service.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request_upload.next_chunk()
            if status:
                print(f"Upload progress: {int(status.progress() * 100)}%")

        video_id = response['id']

        # Upload thumbnail if provided
        if thumbnail_path:
            youtube_service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()

        # Add to playlist if specified
        if playlist_id:
            youtube_service.playlistItems().insert(
                part='snippet',
                body={
                    'snippet': {
                        'playlistId': playlist_id,
                        'resourceId': {
                            'kind': 'youtube#video',
                            'videoId': video_id
                        }
                    }
                }
            ).execute()

        # Clean up temporary files
        os.remove(video_path)
        if thumbnail_path:
            os.remove(thumbnail_path)

        return jsonify({
            'success': True,
            'videoId': video_id,
            'videoUrl': f'https://www.youtube.com/watch?v={video_id}',
            'message': 'Video uploaded successfully! (Set to private - you can publish it in YouTube Studio)'
        })

    except Exception as e:
        # Clean up files on error
        if 'video_path' in locals() and os.path.exists(video_path):
            os.remove(video_path)
        if 'thumbnail_path' in locals() and thumbnail_path and os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    })


if __name__ == '__main__':
    print("🚀 Starting YouTube Manager Web UI...")
    print("📊 Access at: http://localhost:5000")
    print("   - Analytics: http://localhost:5000/analytics")
    print("   - Upload: http://localhost:5000/upload")
    app.run(debug=True, host='0.0.0.0', port=5000)
