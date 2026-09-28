---
name: grow-channel
description: Grow a small YouTube channel (built around travel vlogs, with notes for Chinese-language channels) by running a weekly loop. The agent reads analytics, repackages titles and thumbnails with Test & Compare, cuts Shorts that link back to the long videos, fixes the channel page, and logs every experiment. Use when the creator asks how to get more views or subscribers, or asks for a weekly growth check (涨粉 / 增长 / 周报).
---

# Grow Channel (weekly loop, agent-first)

The agent is the channel's growth analyst. It **reads the data, proposes levers, and logs
experiments**. The creator approves anything that changes the public channel. Everything
below is backed by YouTube's own guidance where possible (Sources at the end). Treat
third-party heuristics as hypotheses to test, not rules.

Resolve `REPO` as two levels up from this file. Keep all channel data, plans, and experiment
logs in a **private, gitignored** folder (e.g. `sessions/growth/`), never in this skill.

## Principles (what the system actually rewards)

- **The system follows viewers, not videos.** Recommendations weigh watch history,
  likes and dislikes, subscriptions, and **satisfaction surveys** ("valued watchtime").
  A click that ends in a quick exit hurts, and clickbait lowers average view duration (AVD).
  So always read CTR together with AVD. [S1][S2][S3]
- **Search ranks on three things: relevance** (the title, description, and content match
  the query), **engagement** (watch time *for that query*), and **quality**. Tags matter
  little. They mostly help with misspellings. [S4][S5]
- **Normal CTR is roughly 2–10%.** CTR falls as impressions grow, which is expected. Compare
  a video with the channel's own typical, not with other channels. [S3]
- **Returning viewers come from consistency:** similar topics in a familiar format, plus
  community tools such as posts, comments, and premieres. [S6]

## One-time setup (the channel page)

1. **Trailer (non-subscribers)**: 30–60 s showing what the channel is *now*: the niche,
   the format, and the promise. Each viewer sees it once. Never use an off-niche video. [S7]
2. **Featured video (returning subscribers)**: the latest or best episode of the current
   series. [S7]
3. **Sections (up to 12)**: order them *current series playlist → best-of / start-here
   playlist → regional or theme playlists → Shorts → everything else*. Keep legacy off-niche
   content public but low on the page or off the Home tab. [S7]
4. **Description, links, and keywords**: the first line states the promise (what, where,
   how often). Add translations of the channel name and description for secondary
   languages [S8]. Channel keywords (Studio → Settings → Channel) are cheap but low-impact.
   Fill them in once.
5. **Upload defaults**: set the category, language, a description template (hook line → route
   or itinerary → chapters → playlist link → hashtags), and the location where supported.

## Per-upload checklist (in addition to the publish skill)

- **Title**: the important words first. Pick a lane on purpose [S9][S10]:
  - *Searchable*: `<place> + <query word> + <specific payoff>`. For Chinese travel this
    means words people actually type: `攻略 / 一日游 / 自驾 / 必去 / 怎么玩 / 值得吗`, the
    standard Chinese place name, and optionally the English name.
  - *Curiosity*: a question the video truly answers (the thumbnail sets it up, the video pays
    it off). Use it for Browse and Suggested traffic.
  - Keep it accurate and short enough that the first ~20 Chinese characters carry the hook.
    No all-caps or emoji spam.
- **Thumbnail**: one focal subject, big readable text (≤6 CJK chars), and it must read at
  phone size. Of the best-performing videos, 90% use custom thumbnails. [S9]
- **Test & Compare**: upload 2–3 *meaningfully different* options (a title, a thumbnail, or
  both). The winner is chosen by **watch-time share**, not CTR. A test takes days to 2 weeks.
  It isn't available for Shorts. [S11]
- **Description**: the keyword phrase in the first 1–2 lines (the part shown before "Show
  more"), then the itinerary, chapters, and links to the series playlist. [S12]
- **Chapters**: the first one at `00:00`, at least 3, each ≥10 s. Name them with searchable
  place names. [S13]
- **Location and recording date** (Upload → Show more). Set them in Studio when the API
  can't. [S14]
- **Hashtags**: 2–3 relevant ones. The first three show above the title. More than 60
  makes YouTube ignore all of them. [S15]
- **Translations**: add translated titles and descriptions (e.g. English, or Traditional
  Chinese for a Simplified-Chinese channel). They appear in search for viewers of those
  languages. [S16]
- **End screen** (last 5–20 s; the video must be ≥25 s): the *next episode in the series* +
  the series playlist + subscribe. **Cards** (up to 5): link the previous episode at the
  moment it's referenced. Cards and end screens don't show everywhere on mobile, so also say
  "下一集" out loud. [S17][S18]
- **Pinned comment**: one specific question the video sets up (an A-or-B choice, "which
  one would you pick"). Reply to and heart early comments. [S19][S20]

## Shorts as a subscriber funnel

- **One Short = one self-contained moment**: a question, a reveal, a laugh, or a scale shot.
  Show the payoff or the question in the first second. Vertical 9:16, burned-in captions,
  15–40 s. (Shorts can run up to 3 min [S21], but a funnel Short should be short.)
- **Always link it**: Studio → Content → the Short → **Related video** = the long-form episode
  (must be your own channel, public or unlisted). Viewers see the link under the channel
  name. [S22] "Edit into a Short" from the watch page also links back automatically (≤60 s
  selected; no Audio Library music). [S23]
- **Cadence**: 2–4 Shorts a week. Publish each 1–3 days *after* its long video, so the link
  points somewhere public. Mine the back catalog too: a proven long video + a new Short
  pointing at it is the cheapest win.
- **Making one**: write a JSON spec (source clips + in/out, crop x-centre keyframes that follow
  the subject, captions, music) and run `scripts/make_short.py <spec> --check`. It crops 9:16 from
  the 4K source (or letterboxes over a blurred fill), burns captions in the editor's style inside
  the Shorts safe zone, ducks the episode's music under speech, normalizes to −14 LUFS, and ends
  without a fade so the Short loops. Then look at the `_check/` frames at full size and on the
  phone-size sheet (unsafe zones shaded): the subject's head must stay in frame, and captions must
  not cover a face or the subject. When the subject sits low, raise `caption_bottom`. For a small
  or moving subject (an animal underwater), punch in (`zoom` 1.5–2 on 4K) and give both `x` and
  `y` keyframes from a tracker so the subject is big and centred from the first frame. Keep the
  spec next to the episode's EDL (`02 - Export/edit/shorts/<slug>.json`) so the Short can be
  re-rendered.
- **Archive the final file**: make_short writes to `<episode>/02 - Export/shorts/<slug>.mp4` by
  default (next to `thumbnail/`). Keep that file after upload, never render only to a temp dir,
  and add a row to `02 - Export/shorts/README.md`: file → YouTube id, publish time, spec, related
  video. The Short's cover goes in the same folder (`<slug>_cover.jpg`).
- **Upload**: private + `publishAt`, in a slot that doesn't clash with the long-video slots. Put
  the long video's link on the description's first line (`完整版：<title> <url>`), add 2–3
  hashtags, and add the Short to the episode's regional playlist. The API can't set Related video,
  so list each Short → long video id for the creator to set in Studio.
- Shorts views don't count toward long-form watch-time thresholds. Subscribers from Shorts
  do count. Judge Shorts by **subscribers gained** and **related-video clicks**, not
  views. [S24]

## Cadence, series, and binge chains

- Choose a rhythm you can keep for months [S10]. A steady 3–5 uploads a week beats a burst
  followed by silence. When a backlog exists, **meter it out** instead of dumping it.
- Group episodes into **series playlists** (one trip or region = one playlist, in order).
  Every episode's end screen points to the next episode. The last episode points to the
  "start here" playlist.
- Put recaps and "previously…" hooks inside the videos. They help bingers and new viewers
  arriving mid-series.

## Community

- **Posts** (all channels except made-for-kids or supervised ones): polls ("which trip
  next?"), quizzes that reuse a video's riddle, behind-the-scenes photos, and "new episode
  tonight" teasers. 1–3 a week. There's a daily post limit. [S25][S26]
- **Comments**: reply within 24 h, heart the good ones, pin the question. Early replies
  bring the commenter back when they get the notification. [S19][S20]
- **Collaborations**: pick similar-size creators with an overlapping audience. The
  Collaborations feature (2025) surfaces one video on every collaborator's channel. [S20][S27]
- **Cross-posting (Chinese channels)**: mirror to Bilibili with the same series structure
  (合集). On Xiaohongshu, post the vertical cut plus an image-carousel 攻略 note, and point
  to the channel by name, because external links are limited. These are practitioner
  heuristics with no official source here. Log them as experiments.

## The weekly routine (run every 7 days, ~30–45 min)

1. **Pull numbers** (last 7 and 28 days) into the private log:
   subscribers (net, gained, lost), views, watch hours, and **per new upload**: impressions,
   CTR, AVD, % viewed, and first-30 s retention ("intro %"). Also collect the traffic-source
   mix (Search / Browse / Suggested / Shorts feed / External), **new vs casual vs regular
   viewers** [S6], **subscription source** (which videos and pages convert) [S28], Shorts
   "viewed vs swiped away", end-screen click rate [S29], and Test & Compare results.
   Standard Analytics API reports don't include impressions or CTR, so read those in Studio.
2. **Diagnose each new video with one rule**:
   - Low impressions → a topic or search-demand problem, or the channel isn't being tested.
     Fix the topic choice and the search keywords.
   - Impressions OK, CTR below the channel's typical → packaging. Start a Test & Compare.
   - CTR OK, AVD or intro % low → a promise mismatch or a slow open. Check the retention
     dips (key moments [S30]) and note the lesson for the editor.
   - Good retention, few subscribers → a weak end screen or CTA, or the series isn't clear.
3. **Pull 2–3 levers only** (one change per video, so the effect can be attributed):
   repackage one back-catalog video, cut 2–4 Shorts, write 1–3 posts, and fix one
   channel-page item.
4. **Log every experiment** in `experiments.md`:

   ```
   ## EXP-<n> <yyyy-mm-dd> <lever> on <video id>
   Hypothesis: <why this should move metric M>
   Change: <exact before → after>
   Metric / window: <e.g. CTR + views/day, 7 days before vs 7 days after>
   Result (<date>): <numbers> → keep / revert / inconclusive
   Lesson: <one line, generalizable>
   ```
   Close experiments when their window ends. Promote repeated lessons into the publish
   skill's packaging memory, so new uploads start from what already worked.
5. **Report** to the creator in ≤10 lines: the deltas, what worked, what's next, and anything
   that needs a human (Studio-only settings, collaborations, approvals).

## Guardrails

- Never change public metadata, privacy, or the channel page without the creator's OK.
- Never delete or privatize videos to "clean up". That removes views and watch history.
  Reorder or hide them from the Home tab instead.
- No fake engagement, sub-for-sub, or misleading thumbnails. Satisfaction signals punish
  them. [S1][S2]
- Test older, stable videos first. YouTube recommends this to limit the risk. [S11]

## Sources

- S1 How YouTube recommendations work: https://www.youtube.com/howyoutubeworks/product-features/recommendations/
- S2 On YouTube's recommendation system (2021): https://blog.youtube/inside-youtube/on-youtubes-recommendation-system/
- S3 Impressions & CTR FAQ: https://support.google.com/youtube/answer/7628154
- S4 How YouTube search works: https://support.google.com/youtube/answer/16090438
- S5 Tags: https://support.google.com/youtube/answer/146402
- S6 New, casual & regular viewers: https://support.google.com/youtube/answer/10246996
- S7 Channel layout, trailer, sections: https://support.google.com/youtube/answer/3219384
- S8 Channel profile, links, translations: https://support.google.com/youtube/answer/2972003
- S9 Thumbnails & titles: https://support.google.com/youtube/answer/12340300
- S10 Optimize your content: https://www.youtube.com/creators/grow/optimize-your-content/
- S11 Test & Compare: https://support.google.com/youtube/answer/13861714
- S12 Descriptions: https://support.google.com/youtube/answer/12948449
- S13 Chapters: https://support.google.com/youtube/answer/9884579
- S14 Upload settings, location: https://support.google.com/youtube/answer/57407
- S15 Hashtags: https://support.google.com/youtube/answer/6390658
- S16 Translate titles & descriptions: https://support.google.com/youtube/answer/4792576
- S17 End screens: https://support.google.com/youtube/answer/6388789
- S18 Cards: https://support.google.com/youtube/answer/6140493
- S19 Comments (pin, heart, reply): https://support.google.com/youtube/answer/9482367
- S20 Engage your community: https://www.youtube.com/creators/grow/engage-your-community/
- S21 Shorts basics: https://support.google.com/youtube/answer/10059070
- S22 Related video on Shorts: https://support.google.com/youtube/answer/14075157
- S23 Edit into a Short: https://support.google.com/youtube/answer/12836917
- S24 YouTube algorithm guide (Hootsuite, Feb 2025): https://blog.hootsuite.com/youtube-algorithm/
- S25 Create posts: https://support.google.com/youtube/answer/7124474
- S26 Posts eligibility: https://support.google.com/youtube/answer/9409631
- S27 Made on YouTube 2025 (Collaborations, title A/B tests): https://blog.youtube/news-and-events/made-on-youtube-2025/
- S28 Subscription source: https://support.google.com/youtube/answer/9717879
- S29 Engagement tab: https://support.google.com/youtube/answer/9313698
- S30 Key moments for retention: https://support.google.com/youtube/answer/9314415
- Also: impressions funnel https://support.google.com/youtube/answer/9314486 ·
  understand your audience https://www.youtube.com/creators/grow/understand-your-audience/ ·
  YouTube SEO (Backlinko, Dec 2025) https://backlinko.com/how-to-rank-youtube-videos

**Shorts covers:** every Short gets a vertical cover picked from options through the same independent art-director loop as long-form thumbnails. Keep the subject and text inside the center safe area, because the grid crops to about 1:1–4:5. Check rare glyphs at full size (the heavy title font leaves enclosed counters such as 魟's 魚 dots unstroked, so fill them with the stroke colour). Save the approved cover next to the file as `02 - Export/shorts/<slug>_cover.jpg`; the API accepts `thumbnails().set` on a Short, but the Shorts feed may still show a frame, so pick the frame in Studio if it doesn't take. Schedule Shorts like long videos, with `publishAt` at a fixed daily slot.
