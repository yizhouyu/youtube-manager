"""Main CLI application for YouTube Manager."""

import os
import sys
import time
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional
from threading import Lock, Semaphore

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.auth.youtube_auth import YouTubeAuthenticator
from src.youtube_client.client import YouTubeClient
from src.seo_optimizer.optimizer import BilingualSEOOptimizer
from src.tracking.video_tracker import VideoTracker
from src.bilibili_client.client import BilibiliClient
from src.analytics.tracker import AnalyticsTracker
from src.analytics.reporter import AnalyticsReporter
from src.analytics.html_generator import HTMLDashboardGenerator

# Load environment variables
load_dotenv()

console = Console()


class RateLimiter:
    """
    Simple rate limiter using token bucket algorithm.

    Ensures API requests don't exceed specified rate limit (e.g., 50 requests per minute).
    """

    def __init__(self, max_requests: int, time_window: float):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum number of requests allowed
            time_window: Time window in seconds (e.g., 60 for per-minute)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.min_interval = time_window / max_requests  # Minimum seconds between requests
        self.last_request_time = 0
        self.lock = Lock()

    def acquire(self):
        """Wait if necessary to respect rate limit, then proceed."""
        with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time

            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)

            self.last_request_time = time.time()


# Global rate limiter for Claude API (conservative: 40 RPM to stay under 50 RPM Tier 1 limit)
claude_rate_limiter = RateLimiter(max_requests=40, time_window=60)


def _generate_seo_metadata(video: Dict, optimizer: 'BilingualSEOOptimizer') -> Optional[Dict]:
    """
    Generate SEO metadata for a single video (used for parallel processing).

    Args:
        video: Video dictionary with metadata
        optimizer: BilingualSEOOptimizer instance

    Returns:
        Dictionary with optimized metadata or None if failed
    """
    try:
        # Respect rate limits before making API call
        claude_rate_limiter.acquire()

        return optimizer.generate_metadata(
            current_title=video['title'],
            current_description=video['description'],
            current_tags=video.get('tags', []),
            default_language=video.get('defaultLanguage'),
            default_audio_language=video.get('defaultAudioLanguage')
        )
    except Exception as e:
        console.print(f"[red]Error generating metadata for {video['id']}: {e}[/red]")
        return None


@click.group()
def cli():
    """YouTube Manager - Optimize metadata, sync to Bilibili, and track analytics for your travel videos."""
    pass


@cli.command()
@click.option('--limit', default=None, type=int, help='Limit number of videos to process')
@click.option('--video-id', default=None, help='Process only a specific video ID')
@click.option('--auto-apply', is_flag=True, help='Automatically apply all changes without review')
@click.option('--force', is_flag=True, help='Re-process already processed videos')
@click.option('--parallel', default=3, type=int, help='Number of videos to generate SEO suggestions in parallel (default: 3, max recommended: 5)')
def batch_update(limit, video_id, auto_apply, force, parallel):
    """
    Batch update metadata for existing videos on your channel.

    This command will:
    1. Fetch all videos from your channel
    2. Generate SEO-optimized bilingual metadata for each video (with rate limiting)
    3. Show you a preview of the changes
    4. Apply updates after your approval

    Note: Includes built-in rate limiting (40 requests/minute) to respect Claude API limits.
    """
    console.print("\n[bold cyan]YouTube SEO Batch Update[/bold cyan]\n")

    try:
        # Initialize video tracker
        tracker = VideoTracker()
        console.print(f"[dim]Tracking file: {tracker.tracking_file.absolute()}[/dim]")
        console.print(f"[dim]Currently tracking {len(tracker.processed_videos)} video IDs[/dim]")

        # Authenticate with YouTube
        console.print("[yellow]Authenticating with YouTube...[/yellow]")
        auth = YouTubeAuthenticator()
        youtube_service = auth.get_youtube_service()
        youtube_client = YouTubeClient(youtube_service)

        # Initialize SEO optimizer
        console.print("[yellow]Initializing SEO optimizer...[/yellow]")
        optimizer = BilingualSEOOptimizer()

        # Fetch videos
        if video_id:
            console.print(f"[yellow]Fetching video: {video_id}...[/yellow]")
            videos = [youtube_client.get_video_details(video_id)]
            total_videos = 1
        else:
            console.print("[yellow]Fetching all videos from your channel...[/yellow]")
            videos = youtube_client.get_all_channel_videos()
            total_videos = len(videos)

        # Show tracking summary
        tracked_count = tracker.get_processed_count()
        optimized_count = tracker.get_optimized_count()
        tool_generated_count = tracker.get_tool_generated_count()
        unprocessed_count = total_videos - tracked_count

        console.print(f"\n[cyan]Channel Summary:[/cyan]")
        console.print(f"  Total videos: {total_videos}")
        console.print(f"  Already optimized: {optimized_count}")
        console.print(f"  Tool-generated (skipped): {tool_generated_count}")
        console.print(f"  [bold]Not yet processed: {unprocessed_count}[/bold]\n")

        # Filter out already processed videos (unless force flag is set)
        if not force:
            original_count = len(videos)

            # Debug: Show which videos are being filtered
            skipped_videos = []
            for v in videos:
                if tracker.is_processed(v['id']):
                    skipped_videos.append((v['id'], v['title'][:50]))

            videos = [v for v in videos if not tracker.is_processed(v['id'])]
            skipped_count = original_count - len(videos)

            if skipped_count > 0:
                console.print(f"[yellow]Skipping {skipped_count} already tracked video(s).[/yellow]")
                if skipped_count <= 5:  # Show details if not too many
                    for vid_id, title in skipped_videos:
                        console.print(f"[dim]  - {vid_id}: {title}...[/dim]")
                console.print(f"[dim]Use --force to re-process them.[/dim]")

        if limit:
            videos = videos[:limit]

        if len(videos) == 0:
            console.print("[yellow]No videos to process. All videos already tracked.[/yellow]")
            console.print("[dim]Use --force to re-process videos.[/dim]")
            return

        console.print(f"[green]Processing {len(videos)} video(s) in this run.[/green]")
        if parallel > 1:
            console.print(f"[cyan]Parallel mode: Pre-generating SEO suggestions for {parallel} videos at a time[/cyan]\n")
        else:
            console.print()

        # Track successful updates in this run
        processed_in_this_run = 0
        user_quit = False

        # Use parallel processing for SEO metadata generation
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            # Map video_id -> Future for tracking
            futures_map = {}

            # Submit initial batch of tasks (pre-generate metadata for first N videos)
            initial_batch_size = min(parallel, len(videos))
            console.print(f"[dim]Pre-generating SEO suggestions for first {initial_batch_size} video(s)...[/dim]")

            for i in range(initial_batch_size):
                video = videos[i]
                future = executor.submit(_generate_seo_metadata, video, optimizer)
                futures_map[video['id']] = future

            next_video_idx = initial_batch_size  # Index of next video to submit

            # Process each video in order
            for idx, video in enumerate(videos, 1):
                console.print(f"\n[bold]Processing video {idx}/{len(videos)}[/bold]")
                console.print(f"[cyan]Video ID:[/cyan] {video['id']}")
                console.print(f"[cyan]Current Title:[/cyan] {video['title'][:80]}...")

                # Debug: Check if already tracked
                if tracker.is_processed(video['id']):
                    console.print(f"[yellow]⚠ WARNING: This video ID is already in tracking file![/yellow]")
                    console.print(f"[dim]This shouldn't happen - please report this issue.[/dim]")

                # Get the pre-generated metadata (wait if not ready yet)
                console.print("[yellow]Retrieving SEO-optimized metadata...[/yellow]")
                try:
                    future = futures_map[video['id']]
                    optimized = future.result()  # Wait for result (should be instant if user took time reviewing)

                    if optimized is None:
                        console.print(f"[red]Failed to generate metadata for this video. Skipping.[/red]")
                        continue

                    # Submit next video's task to maintain the buffer
                    if next_video_idx < len(videos):
                        next_video = videos[next_video_idx]
                        console.print(f"[dim]Pre-generating SEO suggestions for video {next_video_idx + 1}...[/dim]")
                        new_future = executor.submit(_generate_seo_metadata, next_video, optimizer)
                        futures_map[next_video['id']] = new_future
                        next_video_idx += 1

                    # Display comparison
                    _display_comparison(video, optimized)

                    # Ask for approval
                    if not auto_apply:
                        choice = Prompt.ask(
                            "\n[bold]Apply these changes?[/bold]",
                            choices=["y", "n", "q"],
                            default="n",
                            show_choices=True
                        )

                        if choice == 'q':
                            console.print("\n[yellow]Quitting batch update...[/yellow]")
                            console.print(f"[cyan]Processed so far: {processed_in_this_run} video(s)[/cyan]")
                            user_quit = True
                            break
                        elif choice == 'n':
                            console.print("[yellow]Skipping this video.[/yellow]")
                            continue

                    # Apply updates
                    console.print("[yellow]Updating video metadata...[/yellow]")
                    youtube_client.update_video_metadata(
                        video_id=video['id'],
                        title=optimized['title'],
                        description=optimized['description'],
                        tags=optimized['tags']
                    )
                    console.print("[green]✓ Video updated successfully![/green]")

                    # Mark as processed with full before/after metadata
                    tracker.mark_as_processed(
                        video_id=video['id'],
                        original_metadata={
                            'title': video['title'],
                            'description': video['description'],
                            'tags': video.get('tags', [])
                        },
                        optimized_metadata=optimized,
                        video_info={
                            'publishedAt': video.get('publishedAt'),
                            'duration': video.get('duration'),
                            'viewCount': video.get('viewCount'),
                            'likeCount': video.get('likeCount')
                        }
                    )

                    # Increment current run counter
                    processed_in_this_run += 1

                except Exception as e:
                    console.print(f"[red]Error processing video: {e}[/red]")
                    continue

        # Summary message
        if user_quit:
            console.print("\n[bold yellow]Batch update stopped by user.[/bold yellow]")
        else:
            console.print("\n[bold green]Batch update completed![/bold green]")

        # Calculate remaining videos
        final_tracked = tracker.get_processed_count()
        final_remaining = total_videos - final_tracked

        console.print(f"[green]Optimized in this run: {processed_in_this_run} video(s)[/green]")
        console.print(f"[green]Total tracked (all time): {final_tracked} video(s)[/green]")
        console.print(f"[dim]  - Optimized: {tracker.get_optimized_count()}[/dim]")
        console.print(f"[dim]  - Tool-generated: {tracker.get_tool_generated_count()}[/dim]")
        console.print(f"[cyan]Remaining videos to process: {final_remaining}[/cyan]")

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
@click.option('--video-ids', required=True, help='Comma-separated list of video IDs to mark as tool-generated')
def mark_tool_generated(video_ids):
    """
    Mark videos as tool-generated (skip future processing).

    Use this for newer videos that were created with good SEO metadata
    from the start. These videos will be excluded from batch processing.

    Example:
        python youtube_manager.py mark-tool-generated --video-ids "abc123,def456"
    """
    console.print("\n[bold cyan]Mark Videos as Tool-Generated[/bold cyan]\n")

    try:
        # Initialize tracker
        tracker = VideoTracker()

        # Authenticate with YouTube to get video titles
        console.print("[yellow]Authenticating with YouTube...[/yellow]")
        auth = YouTubeAuthenticator()
        youtube_service = auth.get_youtube_service()
        youtube_client = YouTubeClient(youtube_service)

        # Process each video ID
        video_id_list = [vid.strip() for vid in video_ids.split(',')]
        marked_count = 0

        for video_id in video_id_list:
            try:
                # Fetch video details
                video = youtube_client.get_video_details(video_id)

                # Mark as tool-generated
                tracker.mark_as_tool_generated(
                    video_id=video_id,
                    title=video['title'],
                    video_info={
                        'publishedAt': video.get('publishedAt'),
                        'duration': video.get('duration'),
                        'viewCount': video.get('viewCount'),
                        'likeCount': video.get('likeCount')
                    }
                )

                console.print(f"[green]✓ Marked as tool-generated:[/green] {video['title'][:80]}")
                marked_count += 1

            except Exception as e:
                console.print(f"[red]✗ Error with video {video_id}: {e}[/red]")
                continue

        console.print(f"\n[bold green]Marked {marked_count} video(s) as tool-generated![/bold green]")
        console.print(f"[dim]These videos will be skipped in future batch updates.[/dim]")

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
def backfill_metadata():
    """
    Backfill video metadata (publishedAt, duration, etc.) for existing tracked videos.

    This command will fetch metadata from YouTube API for all videos in the tracking
    file that don't yet have video_info, and update the tracking file with this data.
    """
    console.print("\n[bold cyan]Backfill Video Metadata[/bold cyan]\n")

    try:
        # Initialize tracker
        tracker = VideoTracker()

        # Count how many entries need backfilling
        entries_needing_update = []
        for video_id, entry in tracker.processed_videos.items():
            if 'video_info' not in entry:
                entries_needing_update.append(video_id)

        if len(entries_needing_update) == 0:
            console.print("[green]All tracked videos already have metadata. Nothing to backfill.[/green]")
            return

        console.print(f"[yellow]Found {len(entries_needing_update)} video(s) without metadata.[/yellow]")
        console.print("[yellow]Authenticating with YouTube...[/yellow]")

        # Authenticate with YouTube
        auth = YouTubeAuthenticator()
        youtube_service = auth.get_youtube_service()
        youtube_client = YouTubeClient(youtube_service)

        # Fetch and update each video
        updated_count = 0
        failed_count = 0

        for idx, video_id in enumerate(entries_needing_update, 1):
            try:
                console.print(f"[cyan]Fetching metadata for video {idx}/{len(entries_needing_update)}:[/cyan] {video_id}")

                # Fetch video details from YouTube API
                video = youtube_client.get_video_details(video_id)

                # Update the entry with video_info
                entry = tracker.processed_videos[video_id]
                entry['video_info'] = {
                    'published_at': video.get('publishedAt'),
                    'duration': video.get('duration'),
                    'view_count': video.get('viewCount'),
                    'like_count': video.get('likeCount')
                }

                updated_count += 1
                console.print(f"[green]✓ Updated[/green]")

            except Exception as e:
                console.print(f"[red]✗ Failed: {e}[/red]")
                failed_count += 1
                continue

        # Save the updated tracking data
        tracker._save_tracking_data()

        console.print(f"\n[bold green]Backfill completed![/bold green]")
        console.print(f"[green]Updated: {updated_count} video(s)[/green]")
        if failed_count > 0:
            console.print(f"[yellow]Failed: {failed_count} video(s)[/yellow]")

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
@click.option('--auto-match', is_flag=True, help='Automatically match videos with high confidence (>90% similarity)')
def match_bilibili(auto_match):
    """
    Match YouTube videos with Bilibili videos by title similarity.

    This command will fetch all videos from both platforms and match them
    based on title similarity. You'll be able to review the matches before
    syncing metadata.
    """
    console.print("\n[bold cyan]Match YouTube and Bilibili Videos[/bold cyan]\n")

    try:
        # Load Bilibili credentials
        sessdata = os.getenv('BILIBILI_SESSDATA')
        bili_jct = os.getenv('BILIBILI_BILI_JCT')

        if not sessdata or not bili_jct:
            console.print("[red]Error: Bilibili credentials not found in .env file.[/red]")
            console.print("[yellow]Please add BILIBILI_SESSDATA and BILIBILI_BILI_JCT to your .env file.[/yellow]")
            console.print("[dim]See .env.example for instructions on how to get these values.[/dim]")
            return

        # Authenticate with YouTube
        console.print("[yellow]Authenticating with YouTube...[/yellow]")
        auth = YouTubeAuthenticator()
        youtube_service = auth.get_youtube_service()
        youtube_client = YouTubeClient(youtube_service)

        # Initialize Bilibili client
        console.print("[yellow]Authenticating with Bilibili...[/yellow]")
        bilibili_client = BilibiliClient(sessdata, bili_jct)

        # Fetch all videos
        console.print("[yellow]Fetching YouTube videos...[/yellow]")
        youtube_videos = youtube_client.get_all_channel_videos()

        console.print("[yellow]Fetching Bilibili videos...[/yellow]")
        bilibili_videos = bilibili_client.get_user_videos()

        console.print(f"\n[cyan]Found {len(youtube_videos)} YouTube videos and {len(bilibili_videos)} Bilibili videos.[/cyan]\n")

        # Load tracking data to get original titles
        console.print("[yellow]Loading video tracking data for better matching...[/yellow]")
        tracker = VideoTracker()

        # Match videos by title similarity
        from difflib import SequenceMatcher

        matches = []
        matched_bili_ids = set()
        using_original_count = 0

        for yt_video in youtube_videos:
            # Use original title if video was optimized, otherwise use current title
            match_title = yt_video['title']

            if tracker.is_processed(yt_video['id']):
                processed_info = tracker.get_processed_info(yt_video['id'])
                if processed_info and 'before' in processed_info:
                    original_title = processed_info['before'].get('title')
                    if original_title:
                        match_title = original_title
                        using_original_count += 1
            best_match = None
            best_ratio = 0

            for bili_video in bilibili_videos:
                if bili_video['bvid'] in matched_bili_ids:
                    continue

                # Calculate similarity ratio using original title for better matching
                ratio = SequenceMatcher(None, match_title.lower(), bili_video['title'].lower()).ratio()

                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = bili_video

            if best_match and best_ratio >= 0.5:  # Threshold for considering a match
                matches.append({
                    'youtube': yt_video,
                    'bilibili': best_match,
                    'similarity': best_ratio
                })
                matched_bili_ids.add(best_match['bvid'])

        # Display matches
        console.print(f"[dim]Used original titles for {using_original_count} optimized video(s)[/dim]")
        console.print(f"[bold green]Found {len(matches)} potential matches:[/bold green]\n")

        # Sort matches by confidence (highest first)
        matches.sort(key=lambda x: x['similarity'], reverse=True)

        for idx, match in enumerate(matches, 1):
            yt = match['youtube']
            bili = match['bilibili']
            similarity = match['similarity']

            # Color code by confidence
            if similarity >= 0.9:
                confidence_color = "green"
                confidence_text = "High"
            elif similarity >= 0.7:
                confidence_color = "yellow"
                confidence_text = "Medium"
            else:
                confidence_color = "red"
                confidence_text = "Low"

            console.print(f"[bold]Match {idx}:[/bold] [{confidence_color}]{confidence_text} confidence ({similarity:.1%})[/{confidence_color}]")

            # Show original title if different from current
            if tracker.is_processed(yt['id']):
                processed_info = tracker.get_processed_info(yt['id'])
                if processed_info and 'before' in processed_info:
                    original_title = processed_info['before'].get('title', '')
                    if original_title and original_title != yt['title']:
                        console.print(f"  [dim]YouTube (original):[/dim] {original_title[:80]}")

            console.print(f"  [cyan]YouTube (current):[/cyan]  {yt['title'][:80]}")
            console.print(f"  [magenta]Bilibili:[/magenta] {bili['title'][:80]}")
            console.print(f"  [dim]YouTube ID: {yt['id']} | Bilibili BVID: {bili['bvid']}[/dim]\n")

        # Save matches to file
        import json
        match_file = Path('bilibili_matches.json')
        match_data = {
            'matches': [
                {
                    'youtube_id': m['youtube']['id'],
                    'youtube_title': m['youtube']['title'],
                    'bilibili_bvid': m['bilibili']['bvid'],
                    'bilibili_aid': m['bilibili']['aid'],
                    'bilibili_title': m['bilibili']['title'],
                    'similarity': m['similarity']
                }
                for m in matches
            ]
        }

        with open(match_file, 'w', encoding='utf-8') as f:
            json.dump(match_data, f, indent=2, ensure_ascii=False)

        console.print(f"[green]Matches saved to: {match_file.absolute()}[/green]")
        console.print("[dim]Use these matches with the 'sync-to-bilibili' command.[/dim]")

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
@click.option('--match-file', default='bilibili_matches.json', help='Path to matches JSON file')
@click.option('--min-confidence', default=0.7, type=float, help='Minimum similarity confidence (0.0-1.0)')
@click.option('--auto-apply', is_flag=True, help='Automatically sync all matches above threshold')
@click.option('--youtube-id', default=None, help='Sync only a specific YouTube video ID')
@click.option('--desc-limit', default=250, type=int, help='Bilibili description character limit (default 250, some categories allow 2000)')
@click.option('--simple-truncation', is_flag=True, help='Use simple truncation instead of LLM compression (faster, free, but loses more information)')
def sync_to_bilibili(match_file, min_confidence, auto_apply, youtube_id, desc_limit, simple_truncation):
    """
    Sync metadata from YouTube videos to Bilibili.

    This command will update Bilibili video metadata (title, description, tags)
    to match the corresponding YouTube videos based on matches found by
    the 'match-bilibili' command.

    Note: Bilibili has different description limits for different categories:
    - Most categories: 250 characters (default)
    - Some categories: 2000 characters
    Use --desc-limit to adjust if your videos are in a category with higher limits.

    Description compression modes:
    - Default: LLM-powered intelligent compression (preserves ~85% of information,
      removes redundancy, prioritizes Chinese content). Uses Claude API (~$0.002/video).
    - --simple-truncation: Simple truncation at sentence boundaries (fast, free, but
      loses ~40% of information). Use for quick updates or budget constraints.
    """
    console.print("\n[bold cyan]Sync YouTube Metadata to Bilibili[/bold cyan]\n")

    try:
        # Load Bilibili credentials
        sessdata = os.getenv('BILIBILI_SESSDATA')
        bili_jct = os.getenv('BILIBILI_BILI_JCT')

        if not sessdata or not bili_jct:
            console.print("[red]Error: Bilibili credentials not found in .env file.[/red]")
            return

        # Load matches
        match_path = Path(match_file)
        if not match_path.exists():
            console.print(f"[red]Error: Match file not found: {match_file}[/red]")
            console.print("[yellow]Run 'match-bilibili' command first to generate matches.[/yellow]")
            return

        with open(match_path, 'r', encoding='utf-8') as f:
            match_data = json.load(f)

        matches = match_data.get('matches', [])

        # Filter by confidence and youtube_id
        if youtube_id:
            matches = [m for m in matches if m['youtube_id'] == youtube_id]
            if not matches:
                console.print(f"[red]No match found for YouTube ID: {youtube_id}[/red]")
                return
        else:
            matches = [m for m in matches if m['similarity'] >= min_confidence]

        console.print(f"[cyan]Found {len(matches)} video(s) to sync (confidence >= {min_confidence:.0%})[/cyan]\n")

        if len(matches) == 0:
            console.print("[yellow]No videos to sync.[/yellow]")
            return

        # Authenticate with YouTube
        console.print("[yellow]Authenticating with YouTube...[/yellow]")
        auth = YouTubeAuthenticator()
        youtube_service = auth.get_youtube_service()
        youtube_client = YouTubeClient(youtube_service)

        # Initialize Bilibili client
        console.print("[yellow]Authenticating with Bilibili...[/yellow]")
        bilibili_client = BilibiliClient(sessdata, bili_jct)

        # Determine compression mode (LLM by default, simple truncation if flag is set)
        use_llm_compression = not simple_truncation
        optimizer = None

        if use_llm_compression:
            console.print("[yellow]Initializing LLM compression (Claude API)...[/yellow]")
            optimizer = BilingualSEOOptimizer()
            console.print("[cyan]Using intelligent LLM compression for descriptions (default)[/cyan]\n")
        else:
            console.print("[cyan]Using simple truncation for descriptions (--simple-truncation flag)[/cyan]\n")

        synced_count = 0

        for idx, match in enumerate(matches, 1):
            console.print(f"\n[bold]Processing {idx}/{len(matches)}[/bold]")
            console.print(f"[cyan]YouTube:[/cyan] {match['youtube_title'][:60]}...")
            console.print(f"[magenta]Bilibili:[/magenta] {match['bilibili_title'][:60]}...")

            try:
                # Fetch current YouTube metadata
                yt_video = youtube_client.get_video_details(match['youtube_id'])

                # Extract and compress Chinese section from description (for Bilibili)
                description = yt_video['description']

                if use_llm_compression:
                    # Use LLM for intelligent compression
                    console.print(f"  [dim]Compressing with LLM...[/dim]")
                    chinese_desc_raw, _ = _extract_chinese_section(description, max_length=999999)  # Extract first, don't truncate yet
                    chinese_desc = optimizer.compress_description_for_bilibili(
                        description=chinese_desc_raw,
                        max_length=desc_limit,
                        video_title=yt_video['title']
                    )
                    was_truncated = len(chinese_desc_raw) > desc_limit
                else:
                    # Use simple truncation
                    chinese_desc, was_truncated = _extract_chinese_section(description, max_length=desc_limit)

                # Prepare title (max 80 chars for Bilibili)
                title = yt_video['title'][:80]

                # Prepare tags (max 10 for Bilibili, filter Chinese tags)
                tags = yt_video.get('tags', [])[:10]

                console.print(f"  [dim]Title: {title}[/dim]")
                console.print(f"  [dim]Description: {len(chinese_desc)} chars{' (LLM compressed)' if (use_llm_compression and was_truncated) else (' (truncated)' if was_truncated else '')}[/dim]")
                console.print(f"  [dim]Tags: {', '.join(tags[:5])}{'...' if len(tags) > 5 else ''}[/dim]")
                if was_truncated:
                    if use_llm_compression:
                        console.print(f"  [green]✓ Description intelligently compressed to {desc_limit} chars using LLM[/green]")
                    else:
                        console.print(f"  [yellow]⚠ Description truncated to {desc_limit} chars for Bilibili[/yellow]")

                # Ask for confirmation
                if not auto_apply:
                    choice = Prompt.ask(
                        "\n[bold]Sync this video?[/bold]",
                        choices=["y", "n", "q"],
                        default="y"
                    )

                    if choice == 'q':
                        console.print("\n[yellow]Sync cancelled.[/yellow]")
                        break
                    elif choice == 'n':
                        console.print("[yellow]Skipped.[/yellow]")
                        continue

                # Update Bilibili video
                console.print("[yellow]Updating Bilibili metadata...[/yellow]")
                bilibili_client.update_video_metadata(
                    aid=match['bilibili_aid'],
                    title=title,
                    description=chinese_desc,
                    tags=tags
                )

                console.print("[green]✓ Synced successfully![/green]")
                synced_count += 1

            except Exception as e:
                console.print(f"[red]✗ Error syncing video: {e}[/red]")
                continue

        console.print(f"\n[bold green]Sync completed![/bold green]")
        console.print(f"[green]Successfully synced {synced_count}/{len(matches)} video(s)[/green]")

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        sys.exit(1)


@cli.command()
@click.option('--match-file', default='bilibili_matches.json', help='Path to matches JSON file')
@click.option('--min-confidence', default=0.7, type=float, help='Minimum similarity confidence (0.0-1.0)')
@click.option('--desc-limit', default=250, type=int, help='Bilibili description character limit')
@click.option('--output', default='bilibili_sync_manual.txt', help='Output file for manual sync')
def generate_bilibili_descriptions(match_file, min_confidence, desc_limit, output):
    """
    Generate LLM-compressed descriptions for manual copy-paste to Bilibili.

    Since Bilibili's update API can be finicky, this command generates a text
    file with all compressed descriptions that you can manually copy-paste
    into Bilibili's web interface.
    """
    console.print("\n[bold cyan]Generate Bilibili Descriptions (Manual Sync)[/bold cyan]\n")

    try:
        # Load matches
        match_path = Path(match_file)
        if not match_path.exists():
            console.print(f"[red]Error: Match file not found: {match_file}[/red]")
            return

        with open(match_path, 'r', encoding='utf-8') as f:
            match_data = json.load(f)

        matches = match_data.get('matches', [])
        matches = [m for m in matches if m['similarity'] >= min_confidence]

        console.print(f"[cyan]Generating compressed descriptions for {len(matches)} videos...[/cyan]\n")

        # Initialize clients
        console.print("[yellow]Authenticating with YouTube...[/yellow]")
        auth = YouTubeAuthenticator()
        youtube_service = auth.get_youtube_service()
        youtube_client = YouTubeClient(youtube_service)

        console.print("[yellow]Initializing LLM compression...[/yellow]\n")
        optimizer = BilingualSEOOptimizer()

        # Generate compressed descriptions
        results = []
        for idx, match in enumerate(matches, 1):
            console.print(f"[dim]Processing {idx}/{len(matches)}: {match['youtube_title'][:50]}...[/dim]")

            try:
                # Fetch YouTube video
                yt_video = youtube_client.get_video_details(match['youtube_id'])

                # Extract and compress
                description = yt_video['description']
                chinese_desc_raw, _ = _extract_chinese_section(description, max_length=999999)
                compressed_desc = optimizer.compress_description_for_bilibili(
                    description=chinese_desc_raw,
                    max_length=desc_limit,
                    video_title=yt_video['title']
                )

                results.append({
                    'match': match,
                    'youtube_title': yt_video['title'],
                    'compressed_desc': compressed_desc,
                    'tags': ', '.join(yt_video.get('tags', [])[:10])
                })

            except Exception as e:
                console.print(f"  [red]Error: {e}[/red]")
                continue

        # Write to file
        output_path = Path(output)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("BILIBILI VIDEO DESCRIPTIONS (LLM COMPRESSED)\n")
            f.write("Copy-paste these into Bilibili's web interface\n")
            f.write("=" * 80 + "\n\n")

            for idx, result in enumerate(results, 1):
                match = result['match']
                f.write(f"\n{'=' * 80}\n")
                f.write(f"VIDEO {idx}/{len(results)}\n")
                f.write(f"{'=' * 80}\n\n")
                f.write(f"Bilibili Video: {match['bilibili_title']}\n")
                f.write(f"Bilibili BVID: {match['bilibili_bvid']}\n")
                f.write(f"Bilibili Link: https://www.bilibili.com/video/{match['bilibili_bvid']}\n\n")
                f.write(f"YouTube Title (Reference):\n{result['youtube_title']}\n\n")
                f.write(f"COMPRESSED DESCRIPTION ({len(result['compressed_desc'])} chars):\n")
                f.write("-" * 80 + "\n")
                f.write(result['compressed_desc'])
                f.write("\n" + "-" * 80 + "\n\n")
                f.write(f"TAGS:\n{result['tags']}\n\n")

        console.print(f"\n[bold green]✓ Generated {len(results)} compressed descriptions![/bold green]")
        console.print(f"[green]Output file: {output_path.absolute()}[/green]\n")
        console.print("[cyan]Instructions:[/cyan]")
        console.print("1. Open the output file")
        console.print("2. For each video, click the Bilibili link to open the edit page")
        console.print("3. Copy-paste the compressed description into the description field")
        console.print("4. Update tags if desired")
        console.print("5. Save changes\n")

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        sys.exit(1)


def _extract_chinese_section(description: str, max_length: int = 250) -> tuple[str, bool]:
    """
    Extract the Chinese section from a bilingual description and truncate if needed.

    Args:
        description: Full bilingual description
        max_length: Maximum character length for Bilibili (default 250)

    Returns:
        Tuple of (extracted_description, was_truncated)
    """
    # Look for common separators
    separators = ['---', '___', '===']
    extracted = None

    for sep in separators:
        if sep in description:
            sections = description.split(sep)
            # Find the section with most Chinese characters
            best_section = ""
            max_chinese = 0

            for section in sections:
                chinese_count = len([c for c in section if '\u4e00' <= c <= '\u9fff'])
                if chinese_count > max_chinese:
                    max_chinese = chinese_count
                    best_section = section.strip()

            if best_section:
                extracted = best_section
                break

    # If no separator found, use the whole description
    if extracted is None:
        extracted = description.strip()

    # Truncate if needed
    if len(extracted) <= max_length:
        return extracted, False

    # Smart truncation: try to break at sentence boundaries
    truncated = extracted[:max_length]

    # Look for sentence endings (Chinese and English)
    sentence_endings = ['。', '！', '？', '.', '!', '?', '\n']
    best_break = -1

    # Search backwards from the truncation point for a good break point
    for i in range(len(truncated) - 1, max(0, len(truncated) - 50), -1):
        if truncated[i] in sentence_endings:
            best_break = i + 1
            break

    # If found a good break point within last 50 chars, use it
    if best_break > 0:
        truncated = truncated[:best_break].strip()
    else:
        # Otherwise just truncate at max_length
        truncated = truncated.rstrip()

    return truncated, True


@cli.command()
@click.option('--topic', prompt='Video topic', help='Main topic/title of the video')
@click.option('--locations', default=None, help='Locations covered in the video')
@click.option('--key-points', default=None, help='Key highlights or points covered')
@click.option('--save', default=None, help='Save output to a file')
def new_video(topic, locations, key_points, save):
    """
    Generate SEO-optimized metadata for a new video.

    This command will generate bilingual metadata based on your video topic
    and key information, ready to use when uploading your video.
    """
    console.print("\n[bold cyan]Generate Metadata for New Video[/bold cyan]\n")

    try:
        # Initialize SEO optimizer
        console.print("[yellow]Initializing SEO optimizer...[/yellow]")
        optimizer = BilingualSEOOptimizer()

        # Generate metadata
        console.print("[yellow]Generating SEO-optimized metadata...[/yellow]\n")
        metadata = optimizer.generate_new_video_metadata(
            topic=topic,
            locations=locations,
            key_points=key_points
        )

        # Display results
        _display_new_metadata(metadata)

        # Save to file if requested
        if save:
            _save_metadata(metadata, save)
            console.print(f"\n[green]Metadata saved to: {save}[/green]")

        console.print("\n[bold green]Metadata generated successfully![/bold green]")
        console.print("[dim]Copy the above content and use it when uploading your video.[/dim]")

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        sys.exit(1)


def _display_comparison(video, optimized):
    """Display side-by-side comparison of current vs optimized metadata."""
    # Title comparison
    table = Table(title="Title Comparison", show_header=True, show_lines=True)
    table.add_column("Current", style="yellow", ratio=1, no_wrap=False)
    table.add_column("Optimized", style="green", ratio=1, no_wrap=False)
    table.add_row(video['title'], optimized['title'])
    console.print(table)

    # Description comparison (full text)
    table = Table(title="Description (Full)", show_header=True, show_lines=True)
    table.add_column("Current", style="yellow", ratio=1, no_wrap=False)
    table.add_column("Optimized", style="green", ratio=1, no_wrap=False)
    table.add_row(video['description'], optimized['description'])
    console.print(table)

    # Tags comparison
    table = Table(title="Tags Comparison", show_header=True, show_lines=True)
    table.add_column("Current", style="yellow", ratio=1, no_wrap=False)
    table.add_column("Optimized", style="green", ratio=1, no_wrap=False)
    current_tags = ', '.join(video.get('tags', ['None']))
    optimized_tags = ', '.join(optimized['tags'])
    table.add_row(current_tags, optimized_tags)
    console.print(table)

    # Hashtags (new)
    if 'hashtags' in optimized:
        console.print(f"\n[cyan]New Hashtags:[/cyan] {' '.join(optimized['hashtags'])}")


def _display_new_metadata(metadata):
    """Display generated metadata for a new video."""
    console.print(Panel(metadata['title'], title="[bold]Title[/bold]", border_style="green"))

    console.print("\n[bold cyan]Description:[/bold cyan]")
    console.print(Panel(metadata['description'], border_style="cyan"))

    console.print("\n[bold cyan]Tags:[/bold cyan]")
    console.print(', '.join(metadata['tags']))

    if 'hashtags' in metadata:
        console.print("\n[bold cyan]Hashtags:[/bold cyan]")
        console.print(' '.join(metadata['hashtags']))


def _save_metadata(metadata, filepath):
    """Save metadata to a text file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"TITLE:\n{metadata['title']}\n\n")
        f.write(f"DESCRIPTION:\n{metadata['description']}\n\n")
        f.write(f"TAGS:\n{', '.join(metadata['tags'])}\n\n")
        if 'hashtags' in metadata:
            f.write(f"HASHTAGS:\n{' '.join(metadata['hashtags'])}\n")


@cli.command()
@click.option('--days', default=28, type=int, help='Number of days for channel analytics (default: 28)')
@click.option('--video-limit', default=50, type=int, help='Number of recent videos to track (default: 50)')
@click.option('--growth-days', default=7, type=int, help='Number of days to calculate growth metrics (default: 7)')
@click.option('--save-snapshot', is_flag=True, help='Save a snapshot of current analytics')
@click.option('--html', is_flag=True, help='Generate HTML dashboard report (opens in browser)')
@click.option('--html-output', default=None, help='Custom filename for HTML report')
def analytics_dashboard(days, video_limit, growth_days, save_snapshot, html, html_output):
    """
    Display comprehensive analytics dashboard for your YouTube channel.

    This command will:
    1. Fetch channel-level analytics (subscribers, views, videos)
    2. Analyze recent video performance
    3. Calculate growth metrics (week-over-week)
    4. Identify top performing videos
    5. Flag underperforming videos
    6. Provide AI-generated insights and recommendations

    Optionally saves a snapshot for historical tracking and trend analysis.
    """
    console.print("\n[bold cyan]YouTube Analytics Dashboard[/bold cyan]\n")

    try:
        # Authenticate with YouTube
        console.print("[yellow]Authenticating with YouTube...[/yellow]")
        auth = YouTubeAuthenticator()
        youtube_service = auth.get_youtube_service()

        # Initialize analytics tracker
        console.print("[yellow]Initializing analytics tracker...[/yellow]")
        tracker = AnalyticsTracker(youtube_service)

        # Fetch channel analytics
        console.print(f"[yellow]Fetching channel analytics (last {days} days)...[/yellow]")
        channel_data = tracker.fetch_channel_analytics(days=days)

        # Fetch video analytics
        console.print(f"[yellow]Fetching video analytics (last {video_limit} videos)...[/yellow]")
        videos_data = tracker.fetch_video_analytics(limit=video_limit)

        console.print(f"[green]✓ Fetched data for {len(videos_data)} videos[/green]\n")

        # Filter videos to only those published in the specified time period for "recent performance"
        from datetime import datetime, timedelta, timezone
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        recent_videos = []
        for video in videos_data:
            try:
                # Parse ISO format date string
                pub_date = datetime.fromisoformat(video['published_at'].replace('Z', '+00:00'))
                if pub_date >= cutoff_date:
                    recent_videos.append(video)
            except (ValueError, KeyError):
                # Skip videos with invalid dates
                continue

        console.print(f"[dim]Found {len(recent_videos)} video(s) published in last {days} days[/dim]\n")

        # Save snapshot if requested
        if save_snapshot:
            console.print("[yellow]Saving analytics snapshot...[/yellow]")
            tracker.save_snapshot(channel_data, videos_data)
            console.print(f"[green]✓ Snapshot saved to: {tracker.analytics_file.absolute()}[/green]\n")

        # Calculate growth metrics
        console.print(f"[yellow]Calculating growth metrics (last {growth_days} days)...[/yellow]")
        growth_metrics = tracker.get_growth_metrics(days=growth_days)

        if growth_metrics.get('insufficient_data'):
            console.print(f"[yellow]⚠ {growth_metrics.get('message')}[/yellow]")
            console.print("[dim]Save snapshots regularly to track growth over time.[/dim]\n")
            growth_metrics = {'period_days': growth_days, 'subscriber_growth': 0, 'views_growth': 0}
        else:
            console.print("[green]✓ Growth metrics calculated[/green]\n")

        # Get top performing videos
        top_videos = tracker.get_top_performing_videos(metric='views', limit=10)
        if not top_videos:
            # Use current videos data if no history
            top_videos = sorted(videos_data, key=lambda x: x['views'], reverse=True)[:10]

        # Get underperforming videos
        underperforming = tracker.get_underperforming_videos(threshold_percentile=25, limit=5)
        if not underperforming:
            # Use current videos data if no history
            if len(videos_data) >= 4:
                sorted_videos = sorted(videos_data, key=lambda x: x['views'])
                underperforming = sorted_videos[:min(5, len(sorted_videos) // 4)]

        # Generate HTML dashboard if requested
        if html:
            console.print("\n[yellow]Generating HTML dashboard...[/yellow]")
            html_generator = HTMLDashboardGenerator()
            html_file = html_generator.generate_dashboard(
                channel_data=channel_data,
                videos_data=recent_videos,
                growth_metrics=growth_metrics,
                top_videos=top_videos,
                underperforming=underperforming,
                output_file=html_output
            )
            console.print(f"[green]✓ HTML dashboard saved to: {html_file}[/green]")

            # Try to open in browser
            import webbrowser
            try:
                webbrowser.open(f'file://{html_file}')
                console.print("[green]✓ Opening dashboard in your browser...[/green]\n")
            except:
                console.print(f"[yellow]Open the file manually: {html_file}[/yellow]\n")
        else:
            # Generate and display terminal dashboard
            reporter = AnalyticsReporter()
            reporter.generate_dashboard_report(
                channel_data=channel_data,
                videos_data=recent_videos,  # Use filtered recent videos for "recent performance"
                growth_metrics=growth_metrics,
                top_videos=top_videos,
                underperforming=underperforming
            )

        # Tips
        if not save_snapshot:
            console.print("[dim]Tip: Use --save-snapshot to track growth over time[/dim]")
        if not html:
            console.print("[dim]Tip: Use --html to generate a beautiful web dashboard[/dim]")

        console.print()

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


if __name__ == '__main__':
    cli()
