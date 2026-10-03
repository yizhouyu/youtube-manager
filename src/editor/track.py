"""Follow a point through a clip so an arrow stays on its target while the camera moves.

    pts = track_point(path, t0, t1, x, y)  # [(t, x, y), ...] in source seconds and 0–1 frame coordinates

The camera motion is estimated from frame to frame: Lucas–Kanade optical flow on corners across the whole frame,
then a RANSAC similarity transform (estimateAffinePartial2D). Moving things (a car driving past the target, people)
are rejected as outliers, so the point follows the scene, not whatever crosses it. Results are cached.
"""
import hashlib
import json
import os

import cv2
import numpy as np

CACHE = "/tmp/yt-editor/track"
VERSION = 2


def track_point(path, t0, t1, x, y, step=1 / 15, scale_w=960, noautorotate=False):
    key = hashlib.sha1(json.dumps([VERSION, path, os.path.getmtime(path), t0, t1, x, y, step, scale_w]).encode()).hexdigest()[:16]
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, key + ".json")
    if os.path.exists(cp):
        return [tuple(p) for p in json.load(open(cp))]
    cap = cv2.VideoCapture(path)
    if noautorotate:
        cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
    cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
    ok, fr = cap.read()
    if not ok:
        return [(t0, x, y), (t1, x, y)]
    h0, w0 = fr.shape[:2]
    s = scale_w / w0
    small = lambda f: cv2.cvtColor(cv2.resize(f, (scale_w, int(h0 * s))), cv2.COLOR_BGR2GRAY)
    prev = small(fr)
    H, W = prev.shape
    pt = np.array([[x * W, y * H]], dtype=np.float32)
    out = [(float(t0), float(x), float(y))]
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    skip = max(1, int(round(step * fps)))
    t = t0
    while t < t1:
        for _ in range(skip - 1):
            cap.grab()
        ok, fr = cap.read()
        if not ok:
            break
        t += skip / fps
        cur = small(fr)
        p0 = cv2.goodFeaturesToTrack(prev, maxCorners=400, qualityLevel=0.01, minDistance=8)
        if p0 is not None and len(p0) >= 8:
            p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, p0, None, winSize=(21, 21), maxLevel=3)
            g = st.reshape(-1) == 1
            if g.sum() >= 8:
                M, _ = cv2.estimateAffinePartial2D(p0[g], p1[g], method=cv2.RANSAC, ransacReprojThreshold=2.0)
                if M is not None:
                    pt = cv2.transform(pt.reshape(1, 1, 2), M).reshape(1, 2)
        px = float(min(max(pt[0, 0], 0), W - 1))
        py = float(min(max(pt[0, 1], 0), H - 1))
        out.append((float(min(t, t1)), px / W, py / H))
        prev = cur
    cap.release()
    tmp = cp + ".tmp"
    json.dump(out, open(tmp, "w"))
    os.replace(tmp, cp)
    return out
