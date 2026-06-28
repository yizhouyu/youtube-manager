"""Flask-free YouTube upload worker with progress tracking.

This is the upload engine lifted out of `src/web/app.py:upload_video_background`
so it can be reused by the thin review server (and tests) without the web layer.

Usage:
    from src.uploader import start_upload, upload_progress
    upload_id = start_upload(video_path=..., thumbnail_path=..., title=..., ...)
    # poll upload_progress[upload_id] for {status, progress, stage, video_url, ...}
"""

import os
import time
import socket
import threading
import traceback
import uuid

from src.auth.youtube_auth import YouTubeAuthenticator

# Shared progress registry, keyed by upload_id. The web app's progress endpoint
# reads from this same dict (imported by reference).
upload_progress = {}

# Singleton authenticated YouTube service (thread-safe).
_youtube_service = None
_youtube_service_lock = threading.Lock()


def _execute_with_retry(request_fn, what, retries=5):
    """Run a YouTube API call with backoff on transient errors.

    Used for the small post-upload steps (recording details, thumbnail, playlist).
    These can hit intermittent TLS interception (SSL cert errors via a proxy/VPN);
    one flaky call should never abort an upload whose video is already live.
    Returns the result, or None if every attempt fails (caller decides severity).
    """
    for attempt in range(1, retries + 1):
        try:
            return request_fn().execute()
        except Exception as e:
            msg = str(e)
            if "HttpError 4" in msg and "409" not in msg:
                # genuine client error (bad request / auth) — don't spin
                print(f"[UPLOAD] {what}: client error, not retrying: {msg[:120]}")
                raise
            print(f"[UPLOAD] {what}: attempt {attempt}/{retries} failed: {msg[:120]}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    print(f"[UPLOAD] {what}: gave up after {retries} attempts")
    return None


def get_authenticated_service():
    """Return a cached authenticated YouTube service (singleton)."""
    global _youtube_service
    with _youtube_service_lock:
        if _youtube_service is None:
            default_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(30)
            try:
                _youtube_service = YouTubeAuthenticator().get_youtube_service()
            finally:
                socket.setdefaulttimeout(default_timeout)
        return _youtube_service


def start_upload(
    *,
    video_path,
    thumbnail_path=None,
    title,
    description,
    tags=None,
    hashtags=None,
    privacy_status="private",
    publish_at=None,
    recording_date=None,
    playlist_id=None,
    all_playlist_ids=None,
    video_location=None,
    cleanup=False,
):
    """Initialize progress tracking and start a background upload thread.

    Returns the upload_id; poll ``upload_progress[upload_id]`` for status.

    ``all_playlist_ids`` (used by the swap feature) adds the video to several
    playlists; it takes precedence over ``playlist_id`` in the worker.

    ``cleanup`` controls whether the video/thumbnail files are deleted after
    upload. Defaults to False so a user's real source video is never removed —
    only set True for throwaway temp copies.
    """
    tags = tags or []
    hashtags = hashtags or []

    upload_id = str(uuid.uuid4())
    file_size = os.path.getsize(video_path)

    # Conservative initial ETA assuming ~5 Mbps + 30% processing buffer.
    bytes_per_second = (5 * 1024 * 1024) / 8
    estimated_seconds = int((file_size / bytes_per_second) * 1.3)

    upload_progress[upload_id] = {
        "status": "starting",
        "progress": 0,
        "stage": "Preparing upload...",
        "phase": "preparing",
        "file_size": file_size,
        "bytes_uploaded": 0,
        "start_time": time.time(),
        "error": None,
        "video_id": None,
        "video_url": None,
        "estimated_total_seconds": estimated_seconds,
        "current_speed_mbps": None,
        "all_playlist_ids": all_playlist_ids or [],
    }

    thread = threading.Thread(
        target=_upload_worker,
        args=(upload_id, video_path, thumbnail_path, title, description, tags,
              hashtags, privacy_status, publish_at, recording_date, playlist_id,
              video_location, cleanup),
    )
    thread.daemon = True
    thread.start()
    return upload_id


def _upload_worker(upload_id, video_path, thumbnail_path, title, description,
                   tags, hashtags, privacy_status, publish_at, recording_date,
                   playlist_id, video_location, cleanup):
    """Background thread: upload video + thumbnail + playlist with progress."""
    try:
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        print(f"[UPLOAD] Started upload {upload_id}")
        print(f"[UPLOAD] Video: {os.path.basename(video_path)} ({file_size_mb:.1f} MB)")
        print(f"[UPLOAD] Title: {title} | Privacy: {privacy_status}")
        if publish_at:
            print(f"[UPLOAD] Scheduled publish: {publish_at}")

        # Prepend up to 5 hashtags (first 3 show above the title on YouTube).
        hashtag_str = " ".join(hashtags[:5])
        full_description = f"{hashtag_str}\n\n{description}" if hashtag_str else description

        youtube_service = get_authenticated_service()

        body = {
            "snippet": {
                "title": title,
                "description": full_description,
                "tags": tags,
                "categoryId": "19",  # Travel & Events
                "defaultLanguage": "zh-CN",
                "defaultAudioLanguage": "zh-CN",
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        # recordingDetails must be set after insert, not during.
        recording_date_for_update = recording_date

        if publish_at:
            body["status"]["publishAt"] = publish_at
            body["status"]["privacyStatus"] = "private"

        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(
            video_path,
            mimetype="video/*",
            resumable=True,
            chunksize=1024 * 1024 * 5,  # 5MB chunks for smoother progress
        )

        request_upload = youtube_service.videos().insert(
            part="snippet,status", body=body, media_body=media
        )

        print("[UPLOAD] Starting resumable upload (chunk size: 5MB)...")
        upload_progress[upload_id]["status"] = "uploading"
        upload_progress[upload_id]["phase"] = "uploading"
        upload_progress[upload_id]["stage"] = "Uploading video to YouTube..."

        response = None
        last_update_time = time.time()
        last_bytes_uploaded = 0
        last_progress_change_time = time.time()
        retry_count = 0
        max_retries = 5
        stall_timeout = 60
        progress_stall_timeout = 120

        while response is None:
            try:
                socket.setdefaulttimeout(stall_timeout)
                status, response = request_upload.next_chunk()
                retry_count = 0
            except Exception as chunk_error:
                error_msg = str(chunk_error)
                print(f"[UPLOAD] Chunk upload error: {error_msg}")

                is_client_error = "HttpError 4" in error_msg
                is_recoverable = (
                    any(k in error_msg.lower() for k in
                        ["timeout", "timed out", "connection", "reset", "broken pipe",
                         # transient TLS interception (corporate proxy / VPN) — usually
                         # succeeds on retry; do NOT let it abort a near-complete upload
                         "ssl", "certificate", "eof occurred", "handshake",
                         "decryption failed", "wrong version", "socket"])
                    or "HttpError 5" in error_msg
                )

                if is_client_error:
                    print("[UPLOAD] Client error (4xx) - not retryable")
                    raise chunk_error

                retry_count += 1
                if is_recoverable and retry_count <= max_retries:
                    backoff_seconds = 2 ** retry_count
                    print(f"[UPLOAD] Recoverable error, retry {retry_count}/{max_retries} "
                          f"(backoff: {backoff_seconds}s)")
                    upload_progress[upload_id]["stage"] = (
                        f"Connection issue, retrying... ({retry_count}/{max_retries})")
                    time.sleep(backoff_seconds)
                    continue
                raise Exception(f"Upload failed after {retry_count} retries: {error_msg}")

            if status:
                progress_pct = int(status.progress() * 100)
                bytes_uploaded = int(status.progress() * upload_progress[upload_id]["file_size"])

                if bytes_uploaded > last_bytes_uploaded:
                    last_progress_change_time = time.time()
                elif time.time() - last_progress_change_time > progress_stall_timeout:
                    raise Exception(
                        f"Upload stalled - no progress for {progress_stall_timeout} seconds")

                if progress_pct < 5:
                    phase, stage = "preparing", "Initializing upload to YouTube..."
                elif progress_pct < 90:
                    phase, stage = "uploading", f"Uploading video to YouTube... ({progress_pct}%)"
                elif progress_pct < 95:
                    phase, stage = "processing", "YouTube is processing your video..."
                else:
                    phase, stage = "uploading", "Finalizing video upload..."

                upload_progress[upload_id]["progress"] = progress_pct
                upload_progress[upload_id]["bytes_uploaded"] = bytes_uploaded
                upload_progress[upload_id]["phase"] = phase
                upload_progress[upload_id]["stage"] = stage

                current_time = time.time()
                time_diff = current_time - last_update_time
                if time_diff >= 2.0 and progress_pct > 5:
                    bytes_diff = bytes_uploaded - last_bytes_uploaded
                    speed_mbps = (bytes_diff * 8) / (time_diff * 1024 * 1024)
                    upload_progress[upload_id]["current_speed_mbps"] = round(speed_mbps, 1)
                    last_update_time = current_time
                    last_bytes_uploaded = bytes_uploaded

                elapsed_time = time.time() - upload_progress[upload_id]["start_time"]
                if progress_pct > 5:
                    adjusted_progress = (progress_pct - 5) / 95
                    if adjusted_progress > 0:
                        total_time = elapsed_time / adjusted_progress
                        upload_progress[upload_id]["eta_seconds"] = int(total_time - elapsed_time)
                else:
                    upload_progress[upload_id]["eta_seconds"] = \
                        upload_progress[upload_id].get("estimated_total_seconds", 0)

        video_id = response["id"]
        # Record the id IMMEDIATELY: the video now exists on YouTube. If a later
        # post-step (thumbnail / playlist) fails transiently, the caller still gets
        # the id so it can finish via the API instead of re-uploading a duplicate.
        upload_progress[upload_id]["video_id"] = video_id
        upload_progress[upload_id]["video_url"] = f"https://www.youtube.com/watch?v={video_id}"
        elapsed = time.time() - upload_progress[upload_id]["start_time"]
        print(f"[UPLOAD] Video uploaded! ID: {video_id} (took {elapsed:.1f}s)")

        # Recording date / location (post-insert update).
        if recording_date_for_update or video_location:
            upload_progress[upload_id]["phase"] = "metadata"
            upload_progress[upload_id]["stage"] = "Setting recording details..."
            upload_progress[upload_id]["progress"] = 92

            recording_details = {}
            if recording_date_for_update:
                recording_details["recordingDate"] = f"{recording_date_for_update}T12:00:00.0Z"
            if video_location:
                recording_details["locationDescription"] = video_location

            _execute_with_retry(
                lambda: youtube_service.videos().update(
                    part="recordingDetails",
                    body={"id": video_id, "recordingDetails": recording_details},
                ),
                "recording details update",
            )

        # Custom thumbnail. Retry transient failures; the video is already live, so
        # a flaky thumbnail call must not abort — it's flagged below if it never lands.
        if thumbnail_path:
            upload_progress[upload_id]["phase"] = "thumbnail"
            upload_progress[upload_id]["stage"] = "Uploading custom thumbnail..."
            upload_progress[upload_id]["progress"] = 95
            if _execute_with_retry(
                lambda: youtube_service.thumbnails().set(
                    videoId=video_id, media_body=MediaFileUpload(thumbnail_path)),
                "thumbnail set",
            ) is None:
                upload_progress[upload_id].setdefault("warnings", []).append(
                    "custom thumbnail not set (set it manually in Studio)")

        # Playlist(s).
        all_playlists = upload_progress[upload_id].get("all_playlist_ids", [])
        if all_playlists:
            playlists_to_add = all_playlists
        elif playlist_id:
            playlists_to_add = [playlist_id]
        else:
            playlists_to_add = []

        if playlists_to_add:
            upload_progress[upload_id]["phase"] = "playlist"
            upload_progress[upload_id]["progress"] = 98
            for idx, pl_id in enumerate(playlists_to_add):
                upload_progress[upload_id]["stage"] = \
                    f"Adding to playlist {idx + 1}/{len(playlists_to_add)}..."
                if _execute_with_retry(
                    lambda pid=pl_id: youtube_service.playlistItems().insert(
                        part="snippet",
                        body={"snippet": {
                            "playlistId": pid,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        }}),
                    f"playlist add ({pl_id})",
                ) is None:
                    upload_progress[upload_id].setdefault("warnings", []).append(
                        f"not added to playlist {pl_id} (add it manually)")

        total_time = time.time() - upload_progress[upload_id]["start_time"]
        print(f"[UPLOAD] Complete! {video_id} | {total_time:.1f}s | "
              f"https://www.youtube.com/watch?v={video_id}")

        upload_progress[upload_id]["status"] = "completed"
        upload_progress[upload_id]["phase"] = "complete"
        upload_progress[upload_id]["progress"] = 100
        upload_progress[upload_id]["stage"] = "Upload complete!"
        upload_progress[upload_id]["video_id"] = video_id
        upload_progress[upload_id]["video_url"] = f"https://www.youtube.com/watch?v={video_id}"

        if cleanup:
            try:
                os.remove(video_path)
                if thumbnail_path:
                    os.remove(thumbnail_path)
            except OSError:
                pass

    except Exception as e:
        traceback.print_exc()
        # If the video already uploaded, a later failure is only a post-step issue —
        # the video is LIVE. Report completed-with-warning (and keep the id) rather
        # than "error", so the caller doesn't think nothing happened and re-upload.
        existing_id = upload_progress[upload_id].get("video_id")
        if existing_id:
            print(f"[UPLOAD] Post-upload step failed but video is live ({existing_id}): {e}")
            upload_progress[upload_id]["status"] = "completed"
            upload_progress[upload_id]["progress"] = 100
            upload_progress[upload_id]["stage"] = "Uploaded (a post-step needs finishing)"
            upload_progress[upload_id].setdefault("warnings", []).append(str(e))
        else:
            print(f"[UPLOAD] Upload failed: {e}")
            upload_progress[upload_id]["status"] = "error"
            upload_progress[upload_id]["error"] = str(e)
        if cleanup and upload_progress[upload_id]["status"] == "error":
            try:
                if os.path.exists(video_path):
                    os.remove(video_path)
                if thumbnail_path and os.path.exists(thumbnail_path):
                    os.remove(thumbnail_path)
            except OSError:
                pass
