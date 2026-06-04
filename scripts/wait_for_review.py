#!/usr/bin/env python
"""Block until the review page asks the skill for something.

Polls a session dir for either:
  - request.json  → the user clicked a Regenerate button (returns the request)
  - done.json     → the user confirmed/uploaded (skill should stop)
  - (timeout)     → nothing happened within the window

Prints one line of JSON describing the event, so the publish-video skill can
decide what to do next:
  {"event": "regenerate", "action": "...", "feedback": "..."}
  {"event": "done", "upload_id": "..."}
  {"event": "timeout"}

Usage: python scripts/wait_for_review.py <session_dir> [timeout_seconds]
"""

import json
import os
import sys
import time

POLL_SECONDS = 2


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"event": "error", "message": "session_dir required"}))
        sys.exit(1)

    session_dir = os.path.abspath(sys.argv[1])
    # Default ~9 min so it returns before the Bash tool's 10-min cap; the skill
    # re-invokes on "timeout" if the session isn't done yet.
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 540

    request_path = os.path.join(session_dir, "request.json")
    done_path = os.path.join(session_dir, "done.json")

    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(request_path):
            try:
                with open(request_path, encoding="utf-8") as f:
                    req = json.load(f)
            except (json.JSONDecodeError, OSError):
                time.sleep(POLL_SECONDS)
                continue
            os.remove(request_path)  # consume it
            print(json.dumps({
                "event": "regenerate",
                "action": req.get("action"),
                "feedback": req.get("feedback", ""),
            }, ensure_ascii=False))
            return
        if os.path.exists(done_path):
            try:
                with open(done_path, encoding="utf-8") as f:
                    done = json.load(f)
            except (json.JSONDecodeError, OSError):
                done = {}
            print(json.dumps({"event": "done", "upload_id": done.get("upload_id")}))
            return
        time.sleep(POLL_SECONDS)

    print(json.dumps({"event": "timeout"}))


if __name__ == "__main__":
    main()
