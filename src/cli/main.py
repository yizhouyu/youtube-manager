"""Main CLI application for YouTube SEO Helper."""

import os
import sys
from pathlib import Path

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

# Load environment variables
load_dotenv()

console = Console()


@click.group()
def cli():
    """YouTube SEO Helper - Optimize metadata for your travel videos."""
    pass


@cli.command()
@click.option('--limit', default=None, type=int, help='Limit number of videos to process')
@click.option('--video-id', default=None, help='Process only a specific video ID')
@click.option('--auto-apply', is_flag=True, help='Automatically apply all changes without review')
@click.option('--force', is_flag=True, help='Re-process already processed videos')
def batch_update(limit, video_id, auto_apply, force):
    """
    Batch update metadata for existing videos on your channel.

    This command will:
    1. Fetch all videos from your channel
    2. Generate SEO-optimized bilingual metadata for each video
    3. Show you a preview of the changes
    4. Apply updates after your approval
    """
    console.print("\n[bold cyan]YouTube SEO Batch Update[/bold cyan]\n")

    try:
        # Initialize video tracker
        tracker = VideoTracker()
        console.print(f"[dim]Tracking file: {tracker.tracking_file.absolute()}[/dim]")
        console.print(f"[dim]Previously processed: {tracker.get_processed_count()} videos[/dim]\n")

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
        else:
            console.print("[yellow]Fetching all videos from your channel...[/yellow]")
            videos = youtube_client.get_all_channel_videos()

        # Filter out already processed videos (unless force flag is set)
        if not force:
            original_count = len(videos)
            videos = [v for v in videos if not tracker.is_processed(v['id'])]
            skipped_count = original_count - len(videos)
            if skipped_count > 0:
                console.print(f"[yellow]Skipping {skipped_count} already processed video(s).[/yellow]")
                console.print(f"[dim]Use --force to re-process them.[/dim]")

        if limit:
            videos = videos[:limit]

        if len(videos) == 0:
            console.print("[yellow]No videos to process. All videos have been processed already.[/yellow]")
            console.print("[dim]Use --force to re-process videos.[/dim]")
            return

        console.print(f"[green]Found {len(videos)} video(s) to process.[/green]\n")

        # Track successful updates in this run
        processed_in_this_run = 0

        # Process each video
        for idx, video in enumerate(videos, 1):
            console.print(f"\n[bold]Processing video {idx}/{len(videos)}[/bold]")
            console.print(f"[cyan]Video ID:[/cyan] {video['id']}")
            console.print(f"[cyan]Current Title:[/cyan] {video['title'][:80]}...")

            # Generate optimized metadata
            console.print("[yellow]Generating SEO-optimized metadata...[/yellow]")
            try:
                optimized = optimizer.generate_metadata(
                    current_title=video['title'],
                    current_description=video['description'],
                    current_tags=video.get('tags', []),
                    default_language=video.get('defaultLanguage'),
                    default_audio_language=video.get('defaultAudioLanguage')
                )

                # Display comparison
                _display_comparison(video, optimized)

                # Ask for approval
                if not auto_apply:
                    if not Confirm.ask("\n[bold]Apply these changes?[/bold]", default=False):
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
                    optimized_metadata=optimized
                )

                # Increment current run counter
                processed_in_this_run += 1

            except Exception as e:
                console.print(f"[red]Error processing video: {e}[/red]")
                continue

        console.print("\n[bold green]Batch update completed![/bold green]")
        console.print(f"[green]Processed in this run: {processed_in_this_run} video(s)[/green]")
        console.print(f"[green]Total processed (all time): {tracker.get_processed_count()} video(s)[/green]")

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        sys.exit(1)


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


if __name__ == '__main__':
    cli()
