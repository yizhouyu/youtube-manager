# Web UI Setup Instructions

## Overview

The YouTube Manager now includes a modern web UI for uploading videos and viewing analytics. The web interface provides:

1. **Analytics Dashboard** - Real-time channel metrics, growth tracking, and performance analysis
2. **Video Upload Workflow** - Upload videos with AI-generated SEO-optimized metadata

## System Requirements

**Important: Python 3.9+ is required for the web UI.**

Your current system has Python 3.7, which is not compatible with the latest Anthropic Claude API SDK and other modern dependencies.

### Checking Your Python Version

```bash
python3 --version
```

If you see `Python 3.7.x`, you'll need to upgrade to Python 3.9 or higher.

## Option 1: Install Python 3.9+ (Recommended)

### macOS (via Homebrew)

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.11 (recommended for stability)
brew install python@3.11

# Create virtual environment with new Python
python3.11 -m venv venv

# Activate and install requirements
source venv/bin/activate
pip install -r requirements.txt
```

### macOS (via python.org)

1. Download Python 3.11 from https://www.python.org/downloads/macos/
2. Install the .pkg file
3. Create virtual environment:

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Option 2: Use Docker (Alternative)

If you don't want to upgrade your system Python, you can run the web UI in a Docker container:

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install -r requirements.txt

EXPOSE 5000

CMD ["python", "start_web.py"]
```

```bash
# Build and run
docker build -t youtube-manager-web .
docker run -p 5000:5000 -v ./config:/app/config youtube-manager-web
```

## Starting the Web UI

Once Python 3.9+ and dependencies are installed:

```bash
# Activate virtual environment
source venv/bin/activate

# Start the web server
python start_web.py
```

Then open your browser to:
- **Home**: http://localhost:5000
- **Analytics**: http://localhost:5000/analytics
- **Upload**: http://localhost:5000/upload

## Features

### 1. Analytics Dashboard

- **Channel Overview**: Total subscribers, videos, and views
- **Growth Metrics**: 7-day subscriber and view growth
- **Top Performers**: See your best-performing videos
- **Engagement Analysis**: Track likes, comments, and engagement rates
- **Underperforming Videos**: Identify content that needs optimization

### 2. Video Upload Workflow

#### Step 1: Select Files
- Choose your video file (MP4, MOV, AVI, MKV, WebM)
- Select thumbnail image (JPG, PNG, WebP)
- Describe what's in your video (Chinese or English)

#### Step 2: Generate & Review Metadata
- AI generates SEO-optimized bilingual title
- Creates comprehensive Chinese + English description
- Suggests relevant tags (mixed Chinese/English)
- Generates hashtags (first 3 appear above video)
- Review and edit all metadata before uploading

#### Step 3: Upload to YouTube
- Automatic video upload to YouTube
- Thumbnail automatically set
- Video initially set to "Private" for safety
- Returns direct link to your video on YouTube

## Architecture

The web UI is built with:
- **Backend**: Flask (Python web framework)
- **Frontend**: HTML5 + Tailwind CSS
- **API Integration**: Reuses existing YouTube & Claude API clients
- **Authentication**: Shares OAuth2 tokens with CLI

All existing CLI functionality remains available - the web UI is an addition, not a replacement.

## Troubleshooting

### "Module not found" errors

Ensure you're using the virtual environment:
```bash
source venv/bin/activate
```

### YouTube authentication fails

The web UI shares credentials with the CLI. If you haven't authenticated yet:
```bash
python youtube_manager.py batch-update --limit 1
```

This will trigger the OAuth2 flow and save credentials to `config/token.pickle`.

### Port 5000 already in use

Change the port in [start_web.py](start_web.py):
```python
app.run(debug=True, host='0.0.0.0', port=5001)  # Change to 5001 or any available port
```

## Next Steps

1. Upgrade to Python 3.9+ (see options above)
2. Reinstall dependencies: `pip install -r requirements.txt`
3. Start the web server: `python start_web.py`
4. Open http://localhost:5000 in your browser
5. Upload your first video with AI-generated metadata!

## CLI vs Web UI

**Use CLI when:**
- Batch updating existing videos
- Automating with scripts
- Working on remote servers
- Syncing to Bilibili

**Use Web UI when:**
- Uploading new videos
- Reviewing analytics visually
- Editing metadata interactively
- Easier file selection workflow

Both interfaces work with the same YouTube channel and share authentication.
