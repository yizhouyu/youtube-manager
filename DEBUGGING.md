# Debugging Guide for YouTube Manager

This document captures debugging techniques and lessons learned while developing and troubleshooting the YouTube Manager web application.

## Table of Contents
- [Debugging Video Upload Issues](#debugging-video-upload-issues)
- [Common Upload Errors](#common-upload-errors)
- [YouTube API Gotchas](#youtube-api-gotchas)
- [Network and Timeout Issues](#network-and-timeout-issues)
- [Reading Server Logs](#reading-server-logs)

---

## Debugging Video Upload Issues

### Key Principle: Always Check Server Logs First

When upload issues occur, the Flask server logs contain the most valuable debugging information. The web UI may only show "Upload failed" but the server logs will show:
- Exact error messages from YouTube API
- Stack traces with line numbers
- Progress information
- Network timeout details

**How to check logs:**
```bash
# If running in background, check the bash output
# In this project, Flask runs with ID f86a60 during development

# Look for these log patterns:
[UPLOAD] - Upload lifecycle events
[DEBUG] - Detailed debugging information
[ERROR] - Error conditions
```

### The 2024-10-13 Upload Stall Investigation

**Initial symptom:** Upload appeared to stall at 0% indefinitely

**Wrong assumption:** Network connection issue or upload stalling

**Debugging process:**
1. ✅ Added debug logs to capture upload start
2. ✅ Checked server output using BashOutput tool
3. ✅ Found actual error in logs: `HttpError 400: 'recording_details' - unexpectedPart`

**Root cause:** YouTube API v3 doesn't accept `recordingDetails` during video insert operation

**Lesson learned:**
- Don't assume network issues when upload appears to stall
- Read server logs first before adding retry/timeout logic
- API parameter errors (4xx) often masquerade as "stalls" in UI

---

## Common Upload Errors

### 1. `HttpError 400: 'recording_details' - unexpectedPart`

**Error message:**
```
<HttpError 400 when requesting None returned "'recording_details'". Details: "[{'message': "'recording_details'", 'domain': 'youtube.part', 'reason': 'unexpectedPart', 'location': 'part', 'locationType': 'parameter'}]">
```

**Cause:**
- Attempted to include `recordingDetails` in video insert request body
- YouTube API only accepts `snippet` and `status` parts during upload

**Solution:**
```python
# ❌ Wrong: Include recordingDetails in insert body
body = {
    'snippet': {...},
    'status': {...},
    'recordingDetails': {  # This causes 400 error!
        'recordingDate': '2024-10-13T12:00:00.0Z'
    }
}
youtube.videos().insert(part='snippet,status', body=body)

# ✅ Correct: Update recordingDetails after upload
# Step 1: Upload video
response = youtube.videos().insert(
    part='snippet,status',
    body={'snippet': {...}, 'status': {...}}
).execute()

# Step 2: Update with recording date
video_id = response['id']
youtube.videos().update(
    part='recordingDetails',
    body={
        'id': video_id,
        'recordingDetails': {
            'recordingDate': '2024-10-13T12:00:00.0Z'
        }
    }
).execute()
```

**Prevention:**
- Always consult YouTube API docs for which parts are accepted by each endpoint
- Insert operations often have more restrictions than update operations

---

## YouTube API Gotchas

### 1. Parts Accepted by Different Operations

| Operation | Accepted Parts | Notes |
|-----------|---------------|-------|
| `videos().insert()` | `snippet`, `status` | Cannot include `recordingDetails`, `contentDetails`, etc. |
| `videos().update()` | `snippet`, `status`, `recordingDetails`, etc. | Most fields can be updated |
| `thumbnails().set()` | N/A (media only) | Separate operation, requires video ID |
| `playlistItems().insert()` | `snippet` | Link video to playlist |

### 2. Error Types and Retry Strategy

**Client errors (4xx) - NOT retryable:**
- `400 Bad Request` - Invalid parameters (fix code)
- `401 Unauthorized` - Auth issue (refresh token)
- `403 Forbidden` - Quota/permission issue
- `404 Not Found` - Invalid resource ID

**Server errors (5xx) - Retryable:**
- `500 Internal Server Error`
- `503 Service Unavailable`
- `504 Gateway Timeout`

**Network errors - Retryable:**
- Socket timeout
- Connection reset
- Broken pipe

**Implementation:**
```python
is_client_error = 'HttpError 4' in error_msg
is_server_error = 'HttpError 5' in error_msg
is_network_error = any(kw in error_msg.lower()
                       for kw in ['timeout', 'connection', 'reset', 'broken pipe'])

if is_client_error:
    # Fail immediately - code needs fixing
    raise error

if is_server_error or is_network_error:
    # Retry with exponential backoff
    retry_with_backoff()
```

### 3. Resumable Upload Behavior

YouTube uses resumable uploads for large files:
- Uploads in chunks (default 5MB in this project)
- Each chunk is a separate HTTP request
- If a chunk fails, only that chunk is retried
- Progress is tracked server-side by YouTube

**Key insight:**
- `next_chunk()` can block indefinitely on network stalls
- Must set socket timeout for each chunk
- Cannot rely on overall timeout - need per-chunk timeout

---

## Network and Timeout Issues

### The Stall Detection Strategy

**Problem:** Large file uploads can genuinely stall without throwing errors

**Solution:** Multi-layer timeout protection

```python
# Layer 1: Per-chunk socket timeout (60s)
socket.setdefaulttimeout(60)
status, response = request.next_chunk()

# Layer 2: Progress stall detection (120s)
if bytes_uploaded > last_bytes_uploaded:
    last_progress_change_time = time.time()
elif time.time() - last_progress_change_time > 120:
    raise Exception("Upload stalled - no progress for 120 seconds")
```

**Why two layers?**
1. Socket timeout catches network-level hangs (no data received)
2. Progress stall catches application-level hangs (data received but no progress)

### Exponential Backoff for Retries

```python
max_retries = 5
for retry in range(max_retries):
    try:
        upload_chunk()
        break
    except RetryableError:
        wait_time = 2 ** retry  # 2, 4, 8, 16, 32 seconds
        time.sleep(wait_time)
```

**Rationale:**
- Quick retry for transient blips (2s)
- Longer waits for persistent issues (up to 32s)
- Gives network/server time to recover

---

## Reading Server Logs

### Log Prefixes

The codebase uses consistent log prefixes for easy filtering:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `[UPLOAD]` | Upload lifecycle events | `[UPLOAD] Started upload abc-123` |
| `[DEBUG]` | Detailed debugging info | `[DEBUG] Creating new YouTube service` |
| `[ERROR]` | Error conditions | `[ERROR] Failed to authenticate` |

### Typical Upload Log Flow

**Successful upload:**
```
[UPLOAD] Started upload abc-123
[UPLOAD] Video: my_video.mp4 (1500.0 MB)
[UPLOAD] Thumbnail: my_thumbnail.png
[UPLOAD] Title: Amazing Travel Video
[UPLOAD] Privacy: private
[UPLOAD] Recording date: 2024-10-13
[UPLOAD] Authenticating with YouTube API...
[UPLOAD] Starting resumable upload (chunk size: 5MB)...
[UPLOAD] Progress: 10% | 150.0/1500.0 MB | Speed: 8.2 Mbps | ETA: 180s
[UPLOAD] Progress: 20% | 300.0/1500.0 MB | Speed: 8.5 Mbps | ETA: 160s
...
[UPLOAD] Video uploaded successfully! ID: xyz789 (took 185.2s)
[UPLOAD] Setting recording date: 2024-10-13
[UPLOAD] Recording date set successfully
[UPLOAD] Uploading custom thumbnail...
[UPLOAD] Thumbnail uploaded successfully
[UPLOAD] Upload complete! Video ID: xyz789 | Total time: 192.3s
[UPLOAD] URL: https://www.youtube.com/watch?v=xyz789
[UPLOAD] Cleaning up temporary files...
```

**Failed upload with retry:**
```
[UPLOAD] Started upload def-456
[UPLOAD] Video: large_video.mp4 (2000.0 MB)
[UPLOAD] Starting resumable upload...
[UPLOAD] Progress: 30% | 600.0/2000.0 MB | Speed: 7.8 Mbps | ETA: 240s
[UPLOAD] Chunk upload error: Socket timeout
[UPLOAD] Recoverable error, retry 1/5 (backoff: 2s)
[UPLOAD] Progress: 35% | 700.0/2000.0 MB | Speed: 7.5 Mbps | ETA: 220s
[UPLOAD] Video uploaded successfully! ID: uvw456 (took 320.5s)
```

**Failed upload with API error:**
```
[UPLOAD] Started upload ghi-789
[UPLOAD] Video: test.mp4 (500.0 MB)
[UPLOAD] Starting resumable upload...
[UPLOAD] Chunk upload error: <HttpError 400 'recording_details'>
[UPLOAD] Client error (4xx) - not retryable, failing immediately
[UPLOAD] Upload failed: <HttpError 400...>
[UPLOAD] Full traceback:
Traceback (most recent call last):
  File "app.py", line 550, in upload_video_background
    ...
```

### Debugging Checklist

When an upload fails:

1. ✅ Check server logs for `[UPLOAD]` entries
2. ✅ Look for error messages and HTTP status codes
3. ✅ Check if error is 4xx (code issue) or 5xx (server/network)
4. ✅ Review stack trace for line numbers
5. ✅ Check if retries were attempted
6. ✅ Verify network speed and ETA calculations were reasonable
7. ✅ Look for stall detection triggers

---

## Best Practices

### 1. Log Early and Often

Add logs at:
- Function entry points
- Before API calls
- After successful operations
- On errors (with full context)
- At major milestones (10%, 50%, 90% progress)

### 2. Use Structured Log Messages

```python
# ✅ Good: Structured, includes context
print(f"[UPLOAD] Progress: {progress_pct}% | {mb_uploaded}/{mb_total} MB | Speed: {speed} Mbps")

# ❌ Bad: Vague, no context
print("Upload progressing...")
```

### 3. Distinguish Error Types

```python
# ✅ Good: Clear error categorization
if is_client_error:
    print(f"[UPLOAD] Client error (4xx) - not retryable")
    raise
elif is_server_error:
    print(f"[UPLOAD] Server error (5xx) - retrying")
    retry()
```

### 4. Always Include Traceback on Errors

```python
import traceback

try:
    upload_video()
except Exception as e:
    print(f"[UPLOAD] Upload failed: {str(e)}")
    print(f"[UPLOAD] Full traceback:")
    traceback.print_exc()  # Critical for debugging!
```

---

## Tools and Commands

### Monitoring Flask Server Logs

```bash
# Start server in background
source venv/bin/activate && python start_web.py &

# Monitor logs in real-time
tail -f <log_output>

# Search for specific upload
grep "Upload abc-123" <log_output>

# Filter by log level
grep "\[UPLOAD\]" <log_output>
```

### Testing Upload Scenarios

```bash
# Test with small file (fast feedback)
# Create 10MB test file
dd if=/dev/zero of=test_video.mp4 bs=1m count=10

# Test with large file (realistic scenario)
# Use actual exported video

# Test timeout scenarios
# Throttle network: System Preferences → Network → Advanced → Hardware → Speed
```

---

## Reference

- [YouTube Data API v3 - Videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- [YouTube Data API v3 - Videos.update](https://developers.google.com/youtube/v3/docs/videos/update)
- [Resumable Upload Protocol](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
- [Google API Python Client - Media Upload](https://googleapis.github.io/google-api-python-client/docs/media.html)

---

*Last updated: 2024-10-13*
*Debugging lessons learned during upload stall investigation*
