# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube Manager is a Python CLI tool designed to optimize video metadata for a Chinese travel YouTube channel, sync to Bilibili, and track analytics. The tool generates bilingual (Chinese-English) SEO-optimized titles, descriptions, tags, and hashtags using the Claude API and updates videos via the YouTube Data API v3.

## Architecture

**Tech Stack:**
- Python 3.9+
- YouTube Data API v3 (OAuth2)
- Anthropic Claude API
- Click (CLI framework)
- Rich (terminal UI)

**Project Structure:**
```
youtube_manager/
├── src/
│   ├── auth/              # YouTube OAuth2 authentication
│   │   └── youtube_auth.py
│   ├── youtube_client/    # YouTube API client for video operations
│   │   └── client.py
│   ├── seo_optimizer/     # Claude API-powered bilingual metadata generator
│   │   └── optimizer.py
│   ├── bilibili_client/   # Bilibili API integration
│   │   └── client.py
│   ├── analytics/         # Analytics tracking & reporting
│   │   ├── tracker.py
│   │   └── reporter.py
│   └── cli/               # CLI commands and UI
│       └── main.py
├── config/                # API credentials (gitignored)
│   ├── .gitkeep
│   ├── client_secrets.json  (user must provide)
│   └── token.pickle         (auto-generated)
├── youtube_manager.py     # Main entry point
├── requirements.txt
└── .env                   # API keys (gitignored)
```

## Setup and Configuration

**1. Install dependencies:**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Configure API credentials:**
- Copy `.env.example` to `.env`
- Add Anthropic API key to `.env`
- Download YouTube OAuth2 client secrets from Google Cloud Console
- Place `client_secrets.json` in `config/` directory

**3. First-time YouTube authentication:**
The first run will open a browser for OAuth2 authentication. Token is saved to `config/token.pickle` for future use.

## Commands

**Batch update existing videos:**
```bash
python youtube_manager.py batch-update
python youtube_manager.py batch-update --limit 5           # Process first 5 videos
python youtube_manager.py batch-update --video-id VIDEO_ID # Process specific video
python youtube_manager.py batch-update --auto-apply        # Skip manual approval
```

**Generate metadata for new videos:**
```bash
python youtube_manager.py new-video
python youtube_manager.py new-video --topic "北京旅游攻略" --locations "故宫,长城" --save metadata.txt
```

## Key Components

**src/auth/youtube_auth.py:**
- Handles OAuth2 flow for YouTube API
- Manages token persistence and refresh
- Provides authenticated YouTube service object

**src/youtube_client/client.py:**
- `get_all_channel_videos()`: Fetches all videos from authenticated user's channel
- `get_video_details(video_id)`: Gets metadata for a specific video
- `update_video_metadata()`: Updates title, description, tags via API

**src/seo_optimizer/optimizer.py:**
- `generate_metadata()`: Optimizes existing video metadata (bilingual)
- `generate_new_video_metadata()`: Creates metadata from scratch for new videos
- Implements SEO best practices:
  - Chinese titles (60 chars optimal)
  - Bilingual descriptions (Chinese 250+ words, English 150+ words)
  - Mixed Chinese/English tags (8-12 total)
  - Bilingual hashtags (2-3)

**src/bilibili_client/client.py:**
- `get_user_videos()`: Fetches all videos from authenticated Bilibili account
- `get_video_details()`: Gets metadata for specific video
- `update_video_metadata()`: Updates video metadata (experimental - see BILIBILI_API_NOTES.md)
- `generate_update_data()`: Helper for manual sync workflow
- Cookie-based authentication (SESSDATA, bili_jct)

**src/analytics/tracker.py:**
- `fetch_channel_analytics()`: Fetches channel-level metrics
- `fetch_video_analytics()`: Fetches per-video performance data
- `save_snapshot()`: Stores historical analytics data
- `get_growth_metrics()`: Calculates week-over-week growth
- `get_top_performing_videos()`: Identifies best performers
- `get_underperforming_videos()`: Flags videos needing attention

**src/analytics/reporter.py:**
- `generate_dashboard_report()`: Creates comprehensive visual dashboard
- `format_number()`, `format_change()`: Pretty formatting utilities
- Displays: channel overview, recent performance, top videos, insights

**src/cli/main.py:**
- CLI interface using Click and Rich
- Eight main commands:
  - `batch-update`, `new-video` (SEO optimization)
  - `match-bilibili`, `sync-to-bilibili`, `generate-bilibili-descriptions` (Bilibili sync)
  - `analytics-dashboard` (Analytics tracking)
  - `mark-tool-generated`, `backfill-metadata` (Utilities)
- Interactive review mode with side-by-side comparisons
- Batch processing with parallel SEO generation
- Rate limiting for Claude API

## Development Notes

**API Quotas:**
- YouTube Data API: 10,000 units/day
- `videos.list`: 1 unit per call
- `videos.update`: 50 units per call
- Budget ~60 videos = ~3,060 units (safe for daily quota)

**Bilingual SEO Strategy:**
- Titles: Primarily Chinese for native audience
- Descriptions: Chinese section first, then English translation
- Tags: Balanced mix (Chinese: 中国旅行, 旅游攻略; English: China travel, travel guide)
- Focus: Travel content, destinations, cultural experiences

**Error Handling:**
- OAuth2 token auto-refresh on expiration
- Graceful handling of API errors with user-friendly messages
- Individual video error recovery in batch mode

## Testing

**Manual testing workflow:**
1. Test authentication: Run any command to trigger OAuth2 flow
2. Test single video: `python youtube_manager.py batch-update --video-id <ID> --limit 1`
3. Test metadata generation: `python youtube_manager.py new-video --topic "测试"`
4. Review mode: Check side-by-side comparisons before applying changes
5. Verify updates in YouTube Studio

## Troubleshooting

**"Client secrets file not found":**
- Ensure `client_secrets.json` is in `config/` directory
- Download from Google Cloud Console > APIs & Services > Credentials

**"ANTHROPIC_API_KEY not found":**
- Check `.env` file exists and contains `ANTHROPIC_API_KEY=<your-key>`
- Ensure `python-dotenv` is installed

**YouTube API quota exceeded:**
- Each update costs 50 units; daily limit is 10,000
- Wait 24 hours or request quota increase in Google Cloud Console

**OAuth2 authentication loop:**
- Delete `config/token.pickle` and re-authenticate
- Check OAuth2 consent screen is configured properly

**Notification system:**
- For long-running tasks, Claude Code uses `~/.claude_notify_helper.sh` (see global profile in `~/.claude/CLAUDE.md` for details)
