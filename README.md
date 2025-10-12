# YouTube Manager

A Python tool for content creators to optimize video metadata with bilingual (Chinese-English) SEO, upload videos with AI-powered metadata generation, sync to Bilibili, and track analytics. Available as both a **Web UI** and **CLI tool**.

## Features

### 🌐 Web UI (NEW!)
- **Video Upload Workflow**: Upload videos directly to YouTube with AI-generated metadata
  - Smart file detection (automatically identifies video + thumbnail)
  - 3 AI-generated metadata options (engaging, informative, curiosity-based)
  - Edit metadata before upload (description, tags, hashtags)
  - Real-time upload progress with ETA
  - Scheduled publishing support
  - Privacy settings (private/unlisted/public)
- **Analytics Dashboard**: Visual dashboard with channel metrics and top performing videos
- **Modern Interface**: Clean, responsive design built with Flask + Tailwind CSS
- **Start server**: `python start_web.py` → Access at http://localhost:5001

### SEO Optimization
- **Batch Update**: Optimize metadata for all existing videos
- **New Video Mode**: Generate SEO-optimized metadata for upcoming videos
- **Bilingual SEO**: Simplified Chinese (简体中文) titles with bilingual descriptions and tags
- **Multiple Options**: Generate 3 different metadata styles with parallel API calls
- **Interactive Review**: Preview changes before applying
- **AI-Powered**: Uses Claude API for intelligent metadata generation

### Bilibili Integration
- **Video Matching**: Automatically match YouTube videos with Bilibili videos by title
- **LLM Compression**: Intelligently compress descriptions to fit Bilibili's 250-character limit
- **Metadata Sync**: Sync titles, descriptions, and tags from YouTube to Bilibili
- **Manual Sync Workflow**: Generate ready-to-paste compressed descriptions

### Analytics Dashboard
- **Channel Analytics**: Track subscribers, views, and video count
- **Video Performance**: Analyze engagement rates, views, and likes
- **Growth Metrics**: Week-over-week growth tracking
- **Top Performers**: Identify your best performing videos
- **Underperforming Videos**: Flag videos that need attention
- **Historical Tracking**: Save snapshots for trend analysis

### General
- **Video Tracking**: Never re-process the same video twice
- **Parallel Processing**: Generate SEO metadata for multiple videos simultaneously
- **Rate Limiting**: Built-in protection for API limits

## SEO Optimization Strategy

### What Gets Optimized:

**Titles (Chinese)**
- 60 characters optimal length
- Primary keywords placed first
- Engaging power words (必看, 攻略, 完整版, 深度, 实拍, 最新)

**Descriptions (Bilingual)**
- Chinese section: 250+ words with keywords in first 25 words
- English section: 150+ words translation/summary
- Both sections SEO-optimized for their respective languages

**Tags (Mixed Chinese & English)**
- 8-12 tags total
- Chinese: 中国旅行, 旅游攻略, 自由行, 旅行vlog
- English: China travel, travel guide, travel vlog
- Location-specific tags in both languages

**Hashtags (Bilingual)**
- 2-3 focused hashtags
- Example: #中国旅行 #TravelChina #旅游攻略

## Installation

### Prerequisites

- Python 3.9 or higher
- YouTube channel with videos
- Google Cloud Platform account (for YouTube API)
- Anthropic API key (for Claude)
- (Optional) Bilibili account with videos (for Bilibili sync features)

### Setup

1. **Clone the repository:**
   ```bash
   cd youtube_manager
   ```

2. **Create and activate virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up YouTube API:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing one
   - Enable YouTube Data API v3
   - Create OAuth 2.0 credentials (Desktop application)
   - Download the JSON file and save as `config/client_secrets.json`

5. **Set up Anthropic API:**
   - Get your API key from [Anthropic Console](https://console.anthropic.com/settings/keys)
   - Copy `.env.example` to `.env`
   - Add your API key: `ANTHROPIC_API_KEY=your_api_key_here`

6. **(Optional) Set up Bilibili credentials:**
   - Log in to Bilibili in your browser
   - Open browser DevTools (F12) → Application/Storage → Cookies
   - Copy `SESSDATA` and `bili_jct` cookie values
   - Add to `.env` file:
     ```
     BILIBILI_SESSDATA=your_sessdata_value
     BILIBILI_BILI_JCT=your_bili_jct_value
     ```
   - See `.env.example` for more details

7. **First-time authentication:**
   - Run any command (e.g., `python youtube_manager.py batch-update --limit 1`)
   - Browser will open for YouTube OAuth2 authentication
   - Grant permissions to the application
   - Token will be saved for future use

## Usage

### Web UI (Recommended)

Start the web server for a visual interface:

```bash
python start_web.py
```

Then open http://localhost:5001 in your browser.

**Features:**
- **Upload Videos**: Select video + thumbnail, generate AI metadata, upload to YouTube
- **Analytics Dashboard**: View channel performance, top videos, growth metrics
- **Easy to Use**: No command-line knowledge required

See [docs/WEB_UI_SETUP.md](docs/WEB_UI_SETUP.md) for detailed instructions.

---

### CLI Commands

For advanced users and automation:

#### Batch Update Existing Videos

Optimize metadata for all videos on your channel:

```bash
python youtube_manager.py batch-update
```

**Options:**

```bash
# Process only the first 5 videos
python youtube_manager.py batch-update --limit 5

# Update a specific video by ID
python youtube_manager.py batch-update --video-id VIDEO_ID

# Auto-apply all changes without manual review
python youtube_manager.py batch-update --auto-apply
```

**Workflow:**
1. Fetches all videos from your channel
2. For each video, generates optimized metadata using Claude
3. Shows side-by-side comparison (current vs. optimized)
4. Asks for confirmation before applying changes
5. Updates video on YouTube

### Generate Metadata for New Videos

Create SEO-optimized metadata for a new video:

```bash
python youtube_manager.py new-video
```

**With options:**

```bash
# Specify topic and details
python youtube_manager.py new-video \
  --topic "北京旅游攻略" \
  --locations "故宫,长城,天安门" \
  --key-points "历史文化,美食推荐,交通指南"

# Save output to file
python youtube_manager.py new-video --save metadata.txt
```

**Interactive mode:**
- Prompts for video topic
- Optionally asks for locations and key points
- Generates complete metadata
- Displays formatted output ready to copy

### Bilibili Sync

Match and sync your videos between YouTube and Bilibili:

```bash
# Step 1: Match videos between YouTube and Bilibili
python youtube_manager.py match-bilibili

# Step 2: Generate compressed descriptions for manual sync
python youtube_manager.py generate-bilibili-descriptions --min-confidence 0.9

# Or: Try automated sync (experimental)
python youtube_manager.py sync-to-bilibili --min-confidence 0.9
```

**Features:**
- Uses original YouTube titles for accurate matching
- LLM-powered intelligent compression (preserves ~85% of information)
- Handles Bilibili's 250-character description limit
- Manual sync workflow for reliability

See [BILIBILI_COMPRESSION_GUIDE.md](BILIBILI_COMPRESSION_GUIDE.md) and [BILIBILI_API_NOTES.md](BILIBILI_API_NOTES.md) for detailed documentation.

#### Analytics Dashboard (CLI)

Track your channel's performance in the terminal:

```bash
# Display comprehensive analytics dashboard
python youtube_manager.py analytics-dashboard

# Save a snapshot for historical tracking
python youtube_manager.py analytics-dashboard --save-snapshot

# Customize the analysis period
python youtube_manager.py analytics-dashboard --days 28 --growth-days 7 --video-limit 50
```

**Dashboard includes:**
- Channel overview (subscribers, views, total videos)
- Recent performance metrics (last 7-28 days)
- Top 10 performing videos
- Bottom 25% underperforming videos
- AI-generated insights and recommendations
- Week-over-week growth tracking

**Best practice:** Run with `--save-snapshot` weekly to track growth trends over time.

**Tip:** Use the web UI for a visual dashboard with charts and graphs!

## Project Structure

```
youtube_manager/
├── src/
│   ├── web/               # Flask web application
│   │   ├── app.py         # Web routes and API endpoints
│   │   └── templates/     # HTML templates
│   ├── auth/              # YouTube OAuth2 authentication
│   ├── youtube_client/    # YouTube API operations
│   ├── seo_optimizer/     # Claude API metadata generation
│   ├── bilibili_client/   # Bilibili integration
│   ├── analytics/         # Analytics tracking & reporting
│   └── cli/               # CLI interface
├── docs/                  # Documentation
├── config/                # API credentials (gitignored)
│   └── client_secrets.json
├── data/                  # Analytics history
├── start_web.py           # Web server launcher
├── youtube_manager.py     # CLI entry point
├── requirements.txt
├── .env                   # Environment variables
└── README.md
```

## API Quotas

**YouTube Data API:**
- Daily quota: 10,000 units
- Video list: 1 unit per call
- Video update: 50 units per call
- ~60 videos = ~3,060 units (safe for daily limit)

**Anthropic Claude API:**
- Pay-per-use pricing
- Each metadata generation uses ~2,000-4,000 tokens
- Estimated cost: ~$0.01-0.02 per video

## Troubleshooting

### "Client secrets file not found"

Ensure `client_secrets.json` is in the `config/` directory. Download it from Google Cloud Console.

### "ANTHROPIC_API_KEY not found"

1. Check that `.env` file exists in the root directory
2. Verify it contains: `ANTHROPIC_API_KEY=your_actual_key`
3. Ensure `python-dotenv` is installed

### YouTube API quota exceeded

You've reached the daily limit of 10,000 units. Wait 24 hours or request a quota increase in Google Cloud Console.

### Authentication loop

Delete `config/token.pickle` and re-authenticate:
```bash
rm config/token.pickle
python youtube_manager.py batch-update --limit 1
```

### Chinese characters not displaying correctly

Ensure your terminal supports UTF-8 encoding:
```bash
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
```

## Best Practices

1. **Test with a few videos first**: Use `--limit 5` to test the process
2. **Review before applying**: Don't use `--auto-apply` until you trust the output
3. **Backup your data**: YouTube doesn't provide undo for metadata changes
4. **Monitor quota usage**: Keep track of your daily API usage
5. **Iterate on results**: Adjust prompts in `optimizer.py` if needed

## Development

See [CLAUDE.md](CLAUDE.md) for detailed architecture and development guidance.

## License

MIT License - feel free to use and modify for your needs.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the [CLAUDE.md](CLAUDE.md) documentation
3. Check YouTube API and Anthropic API documentation

---

**Note**: This tool modifies your YouTube videos. Always review changes before applying them. Test with a small number of videos first.
