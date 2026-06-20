#!/usr/bin/env python
"""Upload a caption (subtitle) track to an existing YouTube video.

Usage:
    python scripts/upload_captions.py <video_id> <srt_path> [language] [name]

Defaults: language=zh-CN, name="中文". Accepts .srt (YouTube also accepts .sbv/.vtt).

Note: captions.insert requires the OAuth scope `youtube.force-ssl`. If the saved
token was minted without it, this fails with an insufficient-permissions error —
delete config/token.pickle and re-auth (with that scope) once, then retry.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from googleapiclient.http import MediaFileUpload
from src.auth.youtube_auth import YouTubeAuthenticator


def upload_caption(video_id, srt_path, language="zh-CN", name="中文"):
    svc = YouTubeAuthenticator().get_youtube_service()
    body = {"snippet": {"videoId": video_id, "language": language,
                        "name": name, "isDraft": False}}
    media = MediaFileUpload(srt_path, mimetype="application/octet-stream", resumable=False)
    resp = svc.captions().insert(part="snippet", body=body, media_body=media).execute()
    return resp


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: upload_captions.py <video_id> <srt_path> [language] [name]", file=sys.stderr)
        sys.exit(1)
    vid, srt = sys.argv[1], sys.argv[2]
    lang = sys.argv[3] if len(sys.argv) > 3 else "zh-CN"
    nm = sys.argv[4] if len(sys.argv) > 4 else "中文"
    try:
        r = upload_caption(vid, srt, lang, nm)
        print("caption uploaded:", r.get("id"), "| lang", lang)
    except Exception as e:
        print("CAPTION UPLOAD FAILED:", str(e)[:400])
        if "insufficient" in str(e).lower() or "scope" in str(e).lower() or "forbidden" in str(e).lower():
            print("-> token likely lacks youtube.force-ssl scope; re-auth needed.")
        sys.exit(2)
