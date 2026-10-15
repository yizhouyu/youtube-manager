
- **Raw page vs bogus rotation (2026-10-15):** clips in `noautorotate` render upright, but the browser on 8765 obeys their bogus display matrix (105 0511 showed upside down). footage_player now serves a stream-copied copy with `-display_rotation:v:0 0` (cached in /tmp/yt-editor/<project>/upright). If he says a raw clip is flipped, check the preview first.
