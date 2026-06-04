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
from src.analytics.tracker import AnalyticsTracker
from src.analytics.reporter import AnalyticsReporter
from src.thumbnail_generator.compositor import render_session
from src.uploader import start_upload
from src.uploader.uploader import upload_progress  # shared progress registry


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

# Where the publish-video skill writes session dirs (session.json + thumb_N.jpg).
SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'sessions')


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
@app.route('/review')
def review_page():
    """Review & publish page (fed by the publish-video skill's sessions)."""
    return render_template('review.html')


@app.route('/swap')
def swap_page():
    """Video swap page."""
    return render_template('swap.html')


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


# ---------------------------------------------------------------------------
# Review surface — fed by the publish-video skill, which writes session dirs
# under sessions/<id>/ (session.json + thumb_N.jpg) and opens /review.
# ---------------------------------------------------------------------------

def _session_path(session_id):
    return os.path.join(SESSIONS_DIR, secure_filename(session_id))


def _latest_session_id():
    """Most recently modified session dir that contains a session.json."""
    if not os.path.isdir(SESSIONS_DIR):
        return None
    candidates = []
    for name in os.listdir(SESSIONS_DIR):
        meta = os.path.join(SESSIONS_DIR, name, 'session.json')
        if os.path.isfile(meta):
            candidates.append((os.path.getmtime(meta), name))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def _load_session(session_id):
    with open(os.path.join(_session_path(session_id), 'session.json'), encoding='utf-8') as f:
        return json.load(f)


def _save_session(session_id, data):
    with open(os.path.join(_session_path(session_id), 'session.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _thumb_url(session_id, idx):
    """Cache-busted URL for a composited thumbnail."""
    path = os.path.join(_session_path(session_id), f'thumb_{idx}.jpg')
    bust = int(os.path.getmtime(path)) if os.path.exists(path) else 0
    return f'/session/{session_id}/thumb_{idx}.jpg?t={bust}'


@app.route('/api/review/current', methods=['GET'])
def review_current():
    """Return the current (or ?id=) session: metadata + thumbnail options."""
    session_id = request.args.get('id') or _latest_session_id()
    if not session_id or not os.path.isfile(
            os.path.join(_session_path(session_id), 'session.json')):
        return jsonify({'success': False, 'error': 'No publish session found. '
                        'Run /publish-video first.'}), 404

    data = _load_session(session_id)
    thumbnails = []
    for idx, opt in enumerate(data.get('thumbnail_options', [])):
        thumbnails.append({**opt, 'image_url': _thumb_url(session_id, idx)})

    meta_path = os.path.join(_session_path(session_id), 'session.json')
    return jsonify({
        'success': True,
        'id': session_id,
        'updated_at': int(os.path.getmtime(meta_path)),
        'video_filename': os.path.basename(data.get('video_path', '')),
        'metadata_options': data.get('metadata_options', []),
        'thumbnail_options': thumbnails,
    })


@app.route('/session/<session_id>/<path:filename>', methods=['GET'])
def serve_session_file(session_id, filename):
    """Serve composited thumbnails / base image from a session dir."""
    return send_from_directory(_session_path(session_id), filename)


@app.route('/api/review/recompose', methods=['POST'])
def review_recompose():
    """Re-composite one thumbnail with new position/size/text (no LLM).

    Backs the position/size sliders and manual text edits. Persists the edited
    option back to session.json so confirm uploads exactly what's shown.
    """
    body = request.get_json() or {}
    session_id = body.get('id') or _latest_session_id()
    idx = int(body.get('thumbnail_idx', 0))

    if not session_id:
        return jsonify({'success': False, 'error': 'No session'}), 404

    data = _load_session(session_id)
    options = data.get('thumbnail_options', [])
    if idx >= len(options):
        return jsonify({'success': False, 'error': 'Bad thumbnail index'}), 400

    # Apply only the fields that were sent.
    for key in ('position', 'font_size_main', 'main_text', 'subtitle',
                'text_color', 'outline_color'):
        if body.get(key) is not None:
            options[idx][key] = body[key]
    # 'text_size' is the slider's name for font_size_main.
    if body.get('text_size') is not None:
        options[idx]['font_size_main'] = int(body['text_size'])

    _save_session(session_id, data)
    render_session(_session_path(session_id), only_index=idx)

    return jsonify({'success': True, 'image_url': _thumb_url(session_id, idx)})


@app.route('/api/review/request', methods=['POST'])
def review_request():
    """Queue a regenerate request for the live skill's wait-loop to pick up."""
    body = request.get_json() or {}
    session_id = body.get('id') or _latest_session_id()
    if not session_id:
        return jsonify({'success': False, 'error': 'No session'}), 404

    action = body.get('action')  # 'regenerate_titles' | 'regenerate_thumbnail_text'
    req = {'action': action, 'feedback': body.get('feedback', ''), 'ts': time.time()}
    with open(os.path.join(_session_path(session_id), 'request.json'), 'w',
              encoding='utf-8') as f:
        json.dump(req, f, ensure_ascii=False)
    return jsonify({'success': True})


@app.route('/api/review/confirm', methods=['POST'])
def review_confirm():
    """Upload the chosen metadata + thumbnail; signal the skill loop to stop."""
    body = request.get_json() or {}
    session_id = body.get('id') or _latest_session_id()
    if not session_id:
        return jsonify({'success': False, 'error': 'No session'}), 404

    data = _load_session(session_id)
    session_dir = _session_path(session_id)
    video_path = data.get('video_path')
    if not video_path or not os.path.exists(video_path):
        return jsonify({'success': False, 'error': f'Video not found: {video_path}'}), 400

    thumb_idx = int(body.get('thumbnail_idx', 0))
    thumbnail_path = os.path.join(session_dir, f'thumb_{thumb_idx}.jpg')
    if not os.path.exists(thumbnail_path):
        thumbnail_path = None

    publish_at = body.get('publishAt') or None
    upload_id = start_upload(
        video_path=video_path,
        thumbnail_path=thumbnail_path,
        title=body.get('title', ''),
        description=body.get('description', ''),
        tags=body.get('tags', []),
        hashtags=body.get('hashtags', []),
        privacy_status=body.get('privacyStatus', 'private'),
        publish_at=publish_at,
        recording_date=body.get('recordingDate') or None,
        playlist_id=body.get('playlistId') or None,
        video_location=body.get('videoLocation') or None,
        cleanup=False,  # never delete the user's source video / session thumbnails
    )

    # Signal the skill's wait-loop that the session is done.
    with open(os.path.join(session_dir, 'done.json'), 'w', encoding='utf-8') as f:
        json.dump({'upload_id': upload_id, 'ts': time.time()}, f)

    return jsonify({'success': True, 'upload_id': upload_id})


@app.route('/api/swap/videos', methods=['GET'])
def get_swap_videos():
    """
    Fetch all videos from the user's channel for swapping.

    Returns:
        JSON with list of videos (id, title, views, published date)
    """
    try:
        youtube_service = get_authenticated_service()
        youtube_client = YouTubeClient(youtube_service)

        # Get all videos from the channel
        videos = youtube_client.get_all_channel_videos()

        # Sort by published date (newest first)
        videos.sort(key=lambda x: x['publishedAt'], reverse=True)

        return jsonify({
            'success': True,
            'videos': videos
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/swap/upload', methods=['POST'])
def swap_video_upload():
    """
    Upload a new video with metadata copied from an existing video.

    Expected multipart form data:
    - videoFile: new video file
    - originalVideoId: ID of the video to copy metadata from

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
        original_video_id = request.form.get('originalVideoId')

        if not original_video_id:
            return jsonify({
                'success': False,
                'error': 'Original video ID is required'
            }), 400

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

        # Get metadata from original video
        youtube_service = get_authenticated_service()
        youtube_client = YouTubeClient(youtube_service)
        original_metadata = youtube_client.get_video_details(original_video_id)

        # Extract metadata
        title = original_metadata['title']
        description = original_metadata['description']
        tags = original_metadata.get('tags', [])
        category_id = original_metadata.get('categoryId', '19')

        # Extract recording details if available
        recording_date = None
        recording_location = None
        if 'recordingDate' in original_metadata:
            # Recording date is in ISO format: 2024-10-24T12:00:00.0Z
            # We need just the date part: 2024-10-24
            recording_date_full = original_metadata['recordingDate']
            if recording_date_full:
                recording_date = recording_date_full.split('T')[0]
                print(f"[SWAP] Found recording date: {recording_date}")

        if 'recordingLocation' in original_metadata:
            recording_location = original_metadata['recordingLocation']
            print(f"[SWAP] Found recording location: {recording_location}")

        # Extract hashtags from description (they're at the beginning)
        hashtags = []
        description_lines = description.split('\n')
        for line in description_lines:
            line = line.strip()
            if line.startswith('#'):
                # Extract all hashtags from this line
                words = line.split()
                for word in words:
                    if word.startswith('#'):
                        hashtags.append(word)
            elif line:  # Non-empty line that doesn't start with #
                break  # Stop looking for hashtags

        # Find which playlists the original video is in
        playlist_ids = []
        try:
            print(f"[SWAP] Searching for playlists containing video {original_video_id}...")
            # Get all playlists
            playlists_request = youtube_service.playlists().list(
                part='id',
                mine=True,
                maxResults=50
            )
            playlists_response = playlists_request.execute()

            all_playlist_ids = [item['id'] for item in playlists_response.get('items', [])]

            # Check each playlist to see if it contains the original video
            for playlist_id in all_playlist_ids:
                try:
                    playlist_items_request = youtube_service.playlistItems().list(
                        part='contentDetails',
                        playlistId=playlist_id,
                        videoId=original_video_id,
                        maxResults=1
                    )
                    playlist_items_response = playlist_items_request.execute()

                    if playlist_items_response.get('items'):
                        playlist_ids.append(playlist_id)
                        print(f"[SWAP] Found video in playlist: {playlist_id}")
                except Exception as playlist_check_error:
                    # Some playlists might not be accessible, skip them
                    continue

            if playlist_ids:
                print(f"[SWAP] Video is in {len(playlist_ids)} playlist(s)")
            else:
                print(f"[SWAP] Video is not in any playlists")

        except Exception as playlist_error:
            print(f"[SWAP] Could not check playlists: {playlist_error}")
            # Continue without playlist info

        # Save video file temporarily
        video_filename = secure_filename(video_file.filename)
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
        video_file.save(video_path)

        # Check if original video has a custom thumbnail
        thumbnail_path = None
        try:
            # Try to download the thumbnail from the original video
            # YouTube returns multiple thumbnail sizes, we'll use maxres or high
            thumbnails_request = youtube_service.videos().list(
                part='snippet',
                id=original_video_id
            )
            thumbnails_response = thumbnails_request.execute()

            if thumbnails_response.get('items'):
                thumbnails = thumbnails_response['items'][0]['snippet'].get('thumbnails', {})

                # Try to get the best quality thumbnail
                thumbnail_url = None
                for quality in ['maxres', 'high', 'medium']:
                    if quality in thumbnails:
                        thumbnail_url = thumbnails[quality]['url']
                        break

                if thumbnail_url:
                    # Download thumbnail
                    import urllib.request
                    thumbnail_filename = f"thumb_{original_video_id}.jpg"
                    thumbnail_path = os.path.join(app.config['UPLOAD_FOLDER'], thumbnail_filename)
                    urllib.request.urlretrieve(thumbnail_url, thumbnail_path)
                    print(f"[SWAP] Downloaded thumbnail from original video")

        except Exception as thumb_error:
            print(f"[SWAP] Could not download thumbnail: {thumb_error}")
            # Continue without thumbnail

        # Start upload via the shared uploader engine. Swap adds the new video to
        # every playlist the original belonged to (all_playlist_ids). cleanup=True
        # since the saved video + downloaded thumbnail are throwaway temp copies.
        primary_playlist_id = playlist_ids[0] if playlist_ids else None
        upload_id = start_upload(
            video_path=video_path,
            thumbnail_path=thumbnail_path,
            title=title,
            description=description,
            tags=tags,
            hashtags=hashtags,
            privacy_status='private',
            recording_date=recording_date,
            playlist_id=primary_playlist_id,
            all_playlist_ids=playlist_ids,
            video_location=recording_location,
            cleanup=True,
        )

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
    print("   - Swap Video: http://localhost:5000/swap")
    app.run(debug=True, host='0.0.0.0', port=5000)
