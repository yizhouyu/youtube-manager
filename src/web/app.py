"""Flask web application for YouTube Manager."""

import os
import json
import tempfile
import uuid
import time
import threading
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, session
from werkzeug.utils import secure_filename

from src.auth.youtube_auth import YouTubeAuthenticator
from src.youtube_client.client import YouTubeClient
from src.seo_optimizer.optimizer import BilingualSEOOptimizer
from src.analytics.tracker import AnalyticsTracker
from src.analytics.reporter import AnalyticsReporter
from src.thumbnail_generator.generator import ThumbnailGenerator


# Global YouTube service - initialize once and reuse
_youtube_service = None
_youtube_service_lock = threading.Lock()


def get_authenticated_service():
    """Get authenticated YouTube service (singleton pattern for thread safety)."""
    global _youtube_service

    with _youtube_service_lock:
        if _youtube_service is None:
            import socket
            # Set socket timeout to prevent hanging
            default_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(30)  # 30 second timeout
            try:
                print("[DEBUG] Creating new YouTube service instance...")
                auth = YouTubeAuthenticator()
                _youtube_service = auth.get_youtube_service()
                print("[DEBUG] YouTube service created successfully")
            finally:
                socket.setdefaulttimeout(default_timeout)

        return _youtube_service


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB max file size
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.secret_key = os.urandom(24)

# Allowed file extensions
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

# Global dictionary to store upload progress by session
upload_progress = {}


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
    import socket
    import httplib2

    try:
        # Set shorter timeout for HTTP requests
        socket.setdefaulttimeout(15)  # 15 second timeout

        youtube_service = get_authenticated_service()

        # Fetch all playlists with timeout handling
        playlists = []
        next_page_token = None
        page_count = 0
        max_pages = 10  # Limit pagination to prevent long hangs

        while page_count < max_pages:
            request_params = {
                'part': 'snippet,contentDetails',
                'mine': True,
                'maxResults': 50
            }

            if next_page_token:
                request_params['pageToken'] = next_page_token

            try:
                request = youtube_service.playlists().list(**request_params)
                response = request.execute()  # Remove timeout parameter (not supported by this API)

                for item in response.get('items', []):
                    playlists.append({
                        'id': item['id'],
                        'title': item['snippet']['title'],
                        'videoCount': item['contentDetails']['itemCount']
                    })

                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    break

                page_count += 1

            except socket.timeout:
                print(f"Timeout loading playlists page {page_count + 1}")
                # Return partial results if we have some
                if playlists:
                    return jsonify({
                        'success': True,
                        'playlists': playlists,
                        'partial': True,
                        'warning': 'Playlist loading timed out - showing partial results'
                    })
                else:
                    raise Exception('YouTube API request timed out. Please check your internet connection.')

        print(f"Successfully loaded {len(playlists)} playlists")

        return jsonify({
            'success': True,
            'playlists': playlists
        })

    except socket.timeout:
        print("Timeout error loading playlists")
        return jsonify({
            'success': False,
            'error': 'Request timed out while loading playlists. Please try again or check your internet connection.'
        }), 504
    except Exception as e:
        import traceback
        print(f"Error loading playlists: {str(e)}")
        traceback.print_exc()
        error_msg = str(e)
        if 'timed out' in error_msg.lower() or 'timeout' in error_msg.lower():
            return jsonify({
                'success': False,
                'error': 'Request timed out. Please check your internet connection and try again.'
            }), 504
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500
    finally:
        # Reset timeout to default
        socket.setdefaulttimeout(None)


@app.route('/api/thumbnail/generate', methods=['POST'])
def generate_thumbnail():
    """
    Generate 3 AI-powered thumbnail options with text overlays.

    Expected multipart form data:
    - image: image file
    - title: video title
    - description: video description (optional)
    - location: video location (optional)
    - position: manual position override (optional: top/center/bottom)

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
        manual_position = request.form.get('position', None)  # Manual position override

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
            language=language,
            manual_position=manual_position
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


@app.route('/api/upload/start', methods=['POST'])
def start_upload():
    """
    Start video upload in background thread and return upload ID.

    Returns:
        JSON with upload_id for progress tracking
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

        # Generate unique upload ID
        upload_id = str(uuid.uuid4())

        # Get file size for progress tracking
        file_size = os.path.getsize(video_path)

        # Calculate initial time estimate based on file size
        # Assume average upload speed of 5 Mbps (conservative estimate)
        avg_upload_speed_mbps = 5
        bytes_per_second = (avg_upload_speed_mbps * 1024 * 1024) / 8  # Convert Mbps to bytes/sec
        estimated_seconds = int((file_size / bytes_per_second) * 1.3)  # Add 30% buffer for processing

        # Initialize progress tracking
        upload_progress[upload_id] = {
            'status': 'starting',
            'progress': 0,
            'stage': 'Preparing upload...',
            'phase': 'preparing',
            'file_size': file_size,
            'bytes_uploaded': 0,
            'start_time': time.time(),
            'error': None,
            'video_id': None,
            'video_url': None,
            'estimated_total_seconds': estimated_seconds,
            'current_speed_mbps': None
        }

        # Start upload in background thread
        thread = threading.Thread(
            target=upload_video_background,
            args=(upload_id, video_path, thumbnail_path, title, description,
                  tags, hashtags, privacy_status, publish_at, recording_date, playlist_id)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'upload_id': upload_id
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


def upload_video_background(upload_id, video_path, thumbnail_path, title, description,
                           tags, hashtags, privacy_status, publish_at, recording_date, playlist_id):
    """
    Background thread function to upload video to YouTube with progress tracking.
    """
    import traceback
    try:
        print(f"[DEBUG] Upload {upload_id}: Background thread started")
        print(f"[DEBUG] Video path: {video_path}")
        print(f"[DEBUG] Thumbnail path: {thumbnail_path}")
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

        # Note: recordingDetails must be set AFTER upload, not during insert
        # Store recording_date for later use
        recording_date_for_update = recording_date

        # Add scheduled publish time if provided
        if publish_at:
            body['status']['publishAt'] = publish_at
            body['status']['privacyStatus'] = 'private'

        # Upload video using YouTube API with progress tracking
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(
            video_path,
            mimetype='video/*',
            resumable=True,
            chunksize=1024*1024*5  # 5MB chunks for better progress updates
        )

        request_upload = youtube_service.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )

        upload_progress[upload_id]['status'] = 'uploading'
        upload_progress[upload_id]['phase'] = 'uploading'
        upload_progress[upload_id]['stage'] = 'Uploading video to YouTube...'

        response = None
        last_update_time = time.time()
        last_bytes_uploaded = 0
        last_progress_change_time = time.time()
        retry_count = 0
        max_retries = 5
        stall_timeout = 60  # 60 seconds without progress = stalled
        progress_stall_timeout = 120  # 120 seconds without progress change = stalled

        while response is None:
            try:
                # Set socket timeout for this chunk
                import socket
                socket.setdefaulttimeout(stall_timeout)

                chunk_start_time = time.time()
                status, response = request_upload.next_chunk()

                # Reset retry count on successful chunk
                retry_count = 0

            except Exception as chunk_error:
                error_msg = str(chunk_error)

                # Check if it's a client error (4xx) - these are NOT recoverable
                is_client_error = 'HttpError 4' in error_msg

                # Check if it's a recoverable error (timeout, connection reset, server errors)
                is_recoverable = any(keyword in error_msg.lower() for keyword in
                                    ['timeout', 'timed out', 'connection', 'reset', 'broken pipe']) or \
                                'HttpError 5' in error_msg  # 5xx server errors are retryable

                if is_client_error:
                    # Client errors (400-499) are not retryable - fail immediately
                    raise chunk_error

                retry_count += 1

                if is_recoverable and retry_count <= max_retries:
                    print(f"Upload {upload_id}: Chunk failed ({error_msg}), retry {retry_count}/{max_retries}")
                    upload_progress[upload_id]['stage'] = f'Connection issue, retrying... ({retry_count}/{max_retries})'
                    time.sleep(2 ** retry_count)  # Exponential backoff: 2, 4, 8, 16, 32 seconds
                    continue
                else:
                    # Non-recoverable error or max retries exceeded
                    raise Exception(f"Upload failed after {retry_count} retries: {error_msg}")

            if status:
                progress_pct = int(status.progress() * 100)
                bytes_uploaded = int(status.progress() * upload_progress[upload_id]['file_size'])

                # Detect progress stalls
                if bytes_uploaded > last_bytes_uploaded:
                    last_progress_change_time = time.time()
                elif time.time() - last_progress_change_time > progress_stall_timeout:
                    raise Exception(f"Upload stalled - no progress for {progress_stall_timeout} seconds")

                # Map progress to phases with stage descriptions
                if progress_pct < 5:
                    phase = 'preparing'
                    stage = 'Initializing upload to YouTube...'
                elif progress_pct < 90:
                    phase = 'uploading'
                    stage = f'Uploading video to YouTube... ({progress_pct}%)'
                elif progress_pct < 95:
                    phase = 'processing'
                    stage = 'YouTube is processing your video...'
                else:
                    phase = 'uploading'
                    stage = 'Finalizing video upload...'

                upload_progress[upload_id]['progress'] = progress_pct
                upload_progress[upload_id]['bytes_uploaded'] = bytes_uploaded
                upload_progress[upload_id]['phase'] = phase
                upload_progress[upload_id]['stage'] = stage

                # Calculate current upload speed (update every 2 seconds to reduce jitter)
                current_time = time.time()
                time_diff = current_time - last_update_time

                if time_diff >= 2.0 and progress_pct > 5:  # Start speed calc after initial setup
                    bytes_diff = bytes_uploaded - last_bytes_uploaded
                    speed_mbps = (bytes_diff * 8) / (time_diff * 1024 * 1024)  # Convert to Mbps
                    upload_progress[upload_id]['current_speed_mbps'] = round(speed_mbps, 1)
                    last_update_time = current_time
                    last_bytes_uploaded = bytes_uploaded

                # Calculate time remaining with improved algorithm
                elapsed_time = time.time() - upload_progress[upload_id]['start_time']
                if progress_pct > 5:  # More accurate after initial setup phase
                    # Use actual progress rate, excluding the first 5% (slower due to setup)
                    adjusted_progress = (progress_pct - 5) / 95  # Normalize to 0-1 range
                    if adjusted_progress > 0:
                        total_time = elapsed_time / adjusted_progress
                        remaining_time = total_time - elapsed_time
                        upload_progress[upload_id]['eta_seconds'] = int(remaining_time)
                else:
                    # Use initial estimate for first 5%
                    upload_progress[upload_id]['eta_seconds'] = upload_progress[upload_id].get('estimated_total_seconds', 0)

                print(f"Upload {upload_id}: {progress_pct}% complete, phase: {phase}")

        video_id = response['id']

        # Update recording date if provided (must be done after upload, not during insert)
        if recording_date_for_update:
            upload_progress[upload_id]['phase'] = 'metadata'
            upload_progress[upload_id]['stage'] = 'Setting recording date...'
            upload_progress[upload_id]['progress'] = 92

            youtube_service.videos().update(
                part='recordingDetails',
                body={
                    'id': video_id,
                    'recordingDetails': {
                        'recordingDate': f"{recording_date_for_update}T12:00:00.0Z"
                    }
                }
            ).execute()

        # Upload thumbnail if provided
        if thumbnail_path:
            upload_progress[upload_id]['phase'] = 'thumbnail'
            upload_progress[upload_id]['stage'] = 'Uploading custom thumbnail...'
            upload_progress[upload_id]['progress'] = 95

            youtube_service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()

        # Add to playlist if specified
        if playlist_id:
            upload_progress[upload_id]['phase'] = 'playlist'
            upload_progress[upload_id]['stage'] = 'Adding video to playlist...'
            upload_progress[upload_id]['progress'] = 98

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

        # Mark as complete
        upload_progress[upload_id]['status'] = 'completed'
        upload_progress[upload_id]['phase'] = 'complete'
        upload_progress[upload_id]['progress'] = 100
        upload_progress[upload_id]['stage'] = 'Upload complete!'
        upload_progress[upload_id]['video_id'] = video_id
        upload_progress[upload_id]['video_url'] = f'https://www.youtube.com/watch?v={video_id}'

        # Clean up temporary files
        os.remove(video_path)
        if thumbnail_path:
            os.remove(thumbnail_path)

    except Exception as e:
        # Handle errors
        upload_progress[upload_id]['status'] = 'error'
        upload_progress[upload_id]['error'] = str(e)

        # Clean up files on error
        if os.path.exists(video_path):
            os.remove(video_path)
        if thumbnail_path and os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)

        print(f"Upload {upload_id} failed: {str(e)}")
        print(f"[DEBUG] Full traceback:")
        traceback.print_exc()


@app.route('/api/upload/progress/<upload_id>', methods=['GET'])
def get_upload_progress(upload_id):
    """
    Get current upload progress for a specific upload ID.

    Returns:
        JSON with progress information
    """
    if upload_id not in upload_progress:
        return jsonify({
            'success': False,
            'error': 'Upload ID not found'
        }), 404

    progress_data = upload_progress[upload_id]

    return jsonify({
        'success': True,
        'status': progress_data['status'],
        'progress': progress_data['progress'],
        'stage': progress_data['stage'],
        'phase': progress_data.get('phase', 'preparing'),
        'bytes_uploaded': progress_data['bytes_uploaded'],
        'file_size': progress_data['file_size'],
        'eta_seconds': progress_data.get('eta_seconds', None),
        'estimated_total_seconds': progress_data.get('estimated_total_seconds', None),
        'current_speed_mbps': progress_data.get('current_speed_mbps', None),
        'error': progress_data.get('error'),
        'video_id': progress_data.get('video_id'),
        'video_url': progress_data.get('video_url')
    })


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
