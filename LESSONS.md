## YouTube API needs an explicit proxy in this Mac environment (2026-11-01)

During the Codex App trial, the YouTube API call hung even though ordinary `requests` calls worked. macOS has an HTTP proxy at `127.0.0.1:7890`, but Python's Google API transport (`httplib2`) did not pick up the system proxy automatically. The uploader now supports `YOUTUBE_API_PROXY` in `src/auth/youtube_auth.py`; `PySocks` is in `requirements.txt`. With the variable unset, the existing direct connection behavior is unchanged.

For the normal Orca-launched Claude workflow on this Mac, pass the proxy explicitly and keep the Mac awake. Example for episode 120 (Codex Desktop should use the foreground-session form below):

```bash
cd ~/Desktop/youtube-manager/sessions/upload_chains/ep120pub
YOUTUBE_API_PROXY=http://127.0.0.1:7890 YOUTUBE_HTTP_TIMEOUT=600 CHUNK_MB=8 \
  caffeinate -i ./chain120.sh >> chain120.log 2>&1 &
```

Use the matching `chain121.sh` / `chain122.sh` and log in each episode folder. Choose `CHUNK_MB` based on the uplink; 8 MB worked as the retry size for 120, while 4 MB was used for the longer 121–122 sequence. The proxy setting is only needed when this Mac requires that local proxy; do not hard-code it into account configuration.

Before retrying a stalled-looking upload, inspect the chain log and episode `ids`/resumable-session state. A slow transfer may still be active. Never start a second uploader or delete `long_session.json` while a resumable upload is in progress; let the idempotent chain resume it. For the approved 120–122 sequence, use `sessions/upload_chains/approved_120_122.log` to follow the supervisor and each episode's own chain log to see step-level progress.

This was a one-off Codex App test. The creator's normal desktop workflow remains Orca launching Claude Code; keep that as the default and reuse only the proxy diagnosis/command when the same Mac transport issue appears.

## Running upload chains from Codex Desktop (2026-11-01)

For a long upload chain started from Codex Desktop, run it in the foreground through the terminal tool so Codex returns a persistent session ID; poll that session for output instead of detaching it with `nohup`. The chain's `busy()` guard calls `ps`, which may be blocked by the default desktop sandbox; if that happens, retry the same authorized chain with process-list access approved for that command. Example:

```bash
cd ~/Desktop/youtube-manager/sessions/upload_chains/ep120pub
export YOUTUBE_API_PROXY=http://127.0.0.1:7890 YOUTUBE_HTTP_TIMEOUT=600 CHUNK_MB=4
caffeinate -i ./chain120.sh
```

In Codex, use a short initial wait and keep the returned session ID for later polling. If a chain is only in its outer retry sleep and has no uploader child, it is safe to restart the idempotent chain **with its existing resumable session intact**; first query the session status and confirm the server still has it. Never run a second uploader while the original uploader child is active, and never delete its session file to “unstick” it.

For this Mac's proxy transport, explicitly remove HTTP 308 from `httplib2.Http.redirect_codes`. YouTube uses 308 plus a `Range` header to report resumable-upload progress; otherwise `httplib2` raises `RedirectMissingLocation` before `googleapiclient` can consume the response. `googleapiclient.http.build_http()` already applies this workaround, but a custom `ProxyInfo` transport must apply it itself. A read-only status query can confirm the retained offset: PUT the saved session URI with an empty body and `Content-Range: bytes */<master-size>` through the local proxy; expect HTTP 308 and inspect `Range` without printing the session URI. In the 120 run, this exposed 8 MB retained server-side; after fixing the transport, the same session resumed and advanced to 1%.

## Bilibili comments through Chrome Computer Use (2026-11-01)

The public video page's comments can look stuck on “正在玩命加载…” until the page is scrolled down to the comments area. In this run, scrolling revealed the comment composer. For Chinese text in the Bilibili contenteditable composer, `typeText()` produced only the trailing digits under the active input method, and `setValue()` changed the accessibility value without changing what Publish actually submitted. Use `paste(text, {format:"text"})`, inspect the visible composer text before clicking Publish, then verify the posted comment and pin toast/menu. A mistaken `33` was posted during the first attempt; do not assume the AX value is the browser's real editor contents.

- **Raw page vs bogus rotation (2026-10-15):** clips in `noautorotate` render upright, but the browser on 8765 obeys their bogus display matrix (105 0511 showed upside down). footage_player now serves a stream-copied copy with `-display_rotation:v:0 0` (cached in /tmp/yt-editor/<project>/upright). If he says a raw clip is flipped, check the preview first.
- **ASR stops early under music (2026-10-15):** 105 0516 lost its last line (52.6–58.6 s) and the rough cut ended the shot there. clip_index now flags `⚠ 转写止于 Xs/Ys`; for flagged clips that are used, re-transcribe the tail from the voice stem before 审片.
- **Label gaps live in per-episode copies too (2026-10-15):** the routemap sub-line gap fix (e13e0e5) did not reach maps drawn by episode scripts (105–107 make_cards pin/panel) or maps rendered before it (108–112). After fixing a shared drawing bug, grep the open episodes for copies and re-render their assets + previews. Title/sub-title in routemap now also sits 40 px under the title ink.
- **Multi-place covers (ep 106, 2026-10-15):** creator loved a diagonal multi-spot cover (hero landmark + 2 other places on diagonal seams, a cut-out dancer breaking the seam via rembg, hairline dark seams, no white frames); grids were 「太规整」. Use only frames from shots in the cut (a critic caught a cover frame that was not in the video). Reference implementation: 106 `thumbnail/multi/multi.py` M7 (episode folder, not repo).

## Before killing a background process, read its full command line (2026-10-16)
After a session restart I killed a "python -u /private/tmp/.../scratchpad/…" process thinking it was the old log watcher; `ps … | cut -c1-200` had truncated the path and it was 107's `upload_bili.py`. Its biliup child kept uploading but nothing would record the BV. Fix: `ps -o command= -p <pid>` (no cut) before any kill; give watchers distinctive names. If it happens: let the orphaned biliup finish, then read the BV from `biliup list` by title (never re-upload blind; upload_bili.py's title check prevents a double).

## A failed upload step must exit non-zero (2026-10-16)
108's `upload_bili.py` printed "NO BVID" after a Wi-Fi drop (biliup: dns error) but exited 0, so the chain's `retry` saw success and moved on to Shorts; B站 was silently skipped for 8 h. Every chain step script must `sys.exit(1)` when its id isn't recorded. Check new chains for this before arming them. When the laptop sleeps, `sleep 1800` retries pause too: after a reconnect, look at the log and restart the chain (it is idempotent) rather than waiting.

## Ep 116 experiments (2026-10-20)
- **Silkscreen-poster opener** (lemo-opuscar grammar in numpy/Pillow, `116/edit/scripts/silkscreen_opener.py`): flat inks per squeegee pull, stepped bands, paper = salt flat, route stamped as a layer, registration snap before the facts. 12.5 s was too long (4 seats agreed): **~9 s**, starting with the first colour already down, then hard-cut on the clack into the first live arrival. Reusable for any trip by swapping shapes + text.
- **Elevation ruler (海拔尺)** pip at each stop with ghost ticks of earlier stops and a broken scale (0…+1800 compressed, 0…−100 stretched) — snap it in on the spoken number, not over a walking shot. Make it ~1.2× the first draft; at phone size only the red number reads.
- **Plant from above, pay off from below:** a 2 s match cut (salt flat looking up ↔ the viewpoint looking down) answered the open question better than a note alone. Keep a hook's punchline (「咸的」) out of the hook when the same take plays later — cut the hook on the gesture.
- **Seat debate before locking** (retention / Bilibili viewer / channel voice / motion, then a rebuttal round) converged fast and caught real bugs (duplicate notes, a dead first 30 s). ~10 min wall time.
- **Studio Audio Library downloads from automation stall after one file** (Chrome blocks repeated automatic downloads; capturing the signed URL was refused by the permission classifier). Fetch music pools with the creator present or after he allows automatic downloads for studio.youtube.com.
- **tighten can clip a word inside a long line** (s012 lost 「旁边的这」): re-listen to the shots tighten touched before QA.

## B站 dtime must be ≤15 days ahead (2026-10-20, ep 111)
biliup uploaded 111's 7.5 GB master, then the submit failed with code 21173 「发布时间离当前时间必须≥5分钟且≤15天」: 11/05 09:00 ET was 15.8 days out. No 稿件 was created (nothing to clean up), but the chain's `retry` would have re-uploaded the whole file every 30 min. Before arming a chain, check `dtime - now ≤ 15 d`; if not, gate the B站 step on `date +%s ≥ dtime − 15 d + 10 min` and do the other steps first (chain111b.sh). With 2 long videos a week queued ~2 weeks ahead, this hits every episode scheduled more than 15 days out.

## Channel inventory: a Short is ≤60 s, not <3 min (2026-10-22, 123 trailer audit)
To list the channel's "long videos", I filtered out everything under 3 min as Shorts. That silently dropped 7 real episodes, including all 4 Utah parks (2–3 min each). As a result I told the creator Utah "was never published" (wrong). Treat only ≤60 s as a Short, or better, exclude the videos in the 短视频 | Shorts playlist. Before claiming something is missing, search the full upload list by keyword.

## Code-made films: the creator judges the animal first, and by eye (2026-10-23, ep 124 falling cat)
He rejected the whole first draft of the falling-cat film on sight: 「这个猫…长的样子就非常的不对」「猫现在3d太粗糙」「猫太假了」, then clarified 「真实感不一定要是 real 逼真…要像猫…只要不要出戏」. Seven agent reviews had passed the procedural cat. What to do now:
- Any animal or character in a code-made film is tested blind next to real photos of that animal, at phone size, with a pet-owner seat and an animator seat, before animation.
- Real footage (archival or licensed) leads; animation only where footage can't show the idea.
- Chinese narration: he hears a Taiwan accent and unnatural prosody at once. Audition across models (ElevenLabs v2 had tone errors, v3 drifted to Taiwan readings, v4 was cleanest for the same voices) and send him clips with on-screen text; edge-tts voices aren't licensed for commercial use.

## YouTube API quota: uploads first, bulk fixes after (2026-11-08)

The Data API has 10,000 units a day; it resets at midnight Pacific (03:00 ET). Costs:
- video upload: 1,600
- caption insert: 400
- videos.update: 50
- commentThreads.insert: 50
- search.list: 100
- list calls: 1

On 11/08 a channel-wide cleanup ran while the 120–122 chains were uploading, and the quota ran out in the middle of 121's caption step. The cleanup was 35 localization updates, 62 comments, embedding fixes and audits. Two Shorts uploads plus one long already take about 5,000 units.

Rules:
- Run the publish chains first, and do bulk metadata or comment passes after them, or the next day.
- Before a bulk pass, estimate its cost (count × unit cost). Keep about 3,500 units free for each long-plus-Shorts upload still to come that day.
- On `quotaExceeded`, stop the chains; don't let them retry. Resume after 03:00 ET. Chains are idempotent, so see `sessions/upload_chains/resume_after_quota.sh`.
