"""Analytics reporter for generating formatted reports."""

from datetime import datetime
from typing import Dict, List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text


class AnalyticsReporter:
    """Generates formatted analytics reports."""

    def __init__(self):
        """Initialize the reporter."""
        self.console = Console()

    def format_number(self, num: int) -> str:
        """Format large numbers with K/M suffixes."""
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num/1_000:.1f}K"
        return str(num)

    def format_change(self, value: int, show_plus: bool = True) -> str:
        """Format change value with color coding."""
        if value > 0:
            prefix = "+" if show_plus else ""
            return f"[green]{prefix}{self.format_number(value)}[/green]"
        elif value < 0:
            return f"[red]{self.format_number(value)}[/red]"
        else:
            return f"[dim]{value}[/dim]"

    def generate_dashboard_report(
        self,
        channel_data: Dict,
        videos_data: List[Dict],
        growth_metrics: Dict,
        top_videos: List[Dict],
        underperforming: List[Dict]
    ):
        """
        Generate comprehensive dashboard report.

        Args:
            channel_data: Channel analytics data
            videos_data: Recent videos data
            growth_metrics: Growth metrics
            top_videos: Top performing videos
            underperforming: Underperforming videos
        """
        self.console.print("\n")
        self.console.print("=" * 80, style="cyan")
        self.console.print(" " * 20 + "📊 YOUTUBE ANALYTICS DASHBOARD", style="bold cyan")
        self.console.print("=" * 80, style="cyan")
        self.console.print()

        # Channel Overview
        self._print_channel_overview(channel_data, growth_metrics)

        # Recent Performance
        self._print_recent_performance(videos_data, growth_metrics)

        # Top Performers
        self._print_top_performers(top_videos)

        # Underperforming Videos
        if underperforming:
            self._print_underperforming(underperforming)

        # Insights & Recommendations
        self._print_insights(channel_data, videos_data, growth_metrics)

        self.console.print()

    def _print_channel_overview(self, channel_data: Dict, growth_metrics: Dict):
        """Print channel overview section."""
        self.console.print("\n[bold]📺 CHANNEL OVERVIEW[/bold]")
        self.console.print("─" * 80, style="dim")

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="bold")
        table.add_column("Change", justify="right")

        # Subscribers
        sub_change = growth_metrics.get('subscriber_growth', 0)
        table.add_row(
            "Subscribers",
            self.format_number(channel_data.get('total_subscribers', 0)),
            self.format_change(sub_change)
        )

        # Total Videos
        table.add_row(
            "Total Videos",
            str(channel_data.get('total_videos', 0)),
            ""
        )

        # Total Views
        views_growth = growth_metrics.get('views_growth', 0)
        table.add_row(
            "Total Channel Views",
            self.format_number(channel_data.get('total_views', 0)),
            self.format_change(views_growth)
        )

        self.console.print(table)

    def _print_recent_performance(self, videos_data: List[Dict], growth_metrics: Dict):
        """Print recent performance metrics."""
        self.console.print("\n[bold]📈 RECENT PERFORMANCE[/bold]")
        days = growth_metrics.get('period_days', 7)
        self.console.print(f"[dim]Last {days} days[/dim]")
        self.console.print("─" * 80, style="dim")

        if not videos_data:
            self.console.print("[yellow]No recent video data available[/yellow]")
            return

        # Calculate aggregates
        total_views = sum(v['views'] for v in videos_data)
        total_likes = sum(v['likes'] for v in videos_data)
        total_comments = sum(v['comments'] for v in videos_data)
        avg_engagement = sum(v['engagement_rate'] for v in videos_data) / len(videos_data)

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="bold")

        table.add_row("Videos Tracked", str(len(videos_data)))
        table.add_row("Total Views", self.format_number(total_views))
        table.add_row("Total Likes", self.format_number(total_likes))
        table.add_row("Total Comments", self.format_number(total_comments))
        table.add_row("Avg Engagement Rate", f"{avg_engagement:.2f}%")

        self.console.print(table)

    def _print_top_performers(self, top_videos: List[Dict]):
        """Print top performing videos."""
        self.console.print("\n[bold]🏆 TOP PERFORMING VIDEOS[/bold]")
        self.console.print("─" * 80, style="dim")

        if not top_videos:
            self.console.print("[yellow]No video data available[/yellow]")
            return

        table = Table(show_header=True, show_lines=False)
        table.add_column("#", style="dim", width=3)
        table.add_column("Title", style="cyan", no_wrap=False, max_width=40)
        table.add_column("Views", justify="right", style="green")
        table.add_column("Likes", justify="right")
        table.add_column("Engage %", justify="right")

        for idx, video in enumerate(top_videos[:10], 1):
            title = video['title'][:37] + "..." if len(video['title']) > 40 else video['title']

            table.add_row(
                str(idx),
                title,
                self.format_number(video['views']),
                self.format_number(video['likes']),
                f"{video['engagement_rate']:.2f}%"
            )

        self.console.print(table)

    def _print_underperforming(self, videos: List[Dict]):
        """Print underperforming videos."""
        self.console.print("\n[bold]⚠️  VIDEOS NEEDING ATTENTION[/bold]")
        self.console.print("[dim]Bottom 25% by views[/dim]")
        self.console.print("─" * 80, style="dim")

        table = Table(show_header=True, show_lines=False)
        table.add_column("Title", style="yellow", no_wrap=False, max_width=45)
        table.add_column("Views", justify="right")
        table.add_column("Published", justify="right", style="dim")

        for video in videos[:5]:
            title = video['title'][:42] + "..." if len(video['title']) > 45 else video['title']

            # Format published date
            try:
                pub_date = datetime.fromisoformat(video['published_at'].replace('Z', '+00:00'))
                days_ago = (datetime.now(pub_date.tzinfo) - pub_date).days
                pub_str = f"{days_ago}d ago"
            except:
                pub_str = "N/A"

            table.add_row(
                title,
                self.format_number(video['views']),
                pub_str
            )

        self.console.print(table)

    def _print_insights(self, channel_data: Dict, videos_data: List[Dict], growth_metrics: Dict):
        """Print AI-generated insights and recommendations."""
        self.console.print("\n[bold]💡 INSIGHTS & RECOMMENDATIONS[/bold]")
        self.console.print("─" * 80, style="dim")

        insights = []

        # Growth insight
        if growth_metrics.get('subscriber_growth', 0) > 0:
            insights.append(f"✅ Growing! +{growth_metrics['subscriber_growth']} subscribers")
        elif growth_metrics.get('subscriber_growth', 0) < 0:
            insights.append(f"⚠️  Losing subscribers: {growth_metrics['subscriber_growth']}")

        # Engagement insight
        if videos_data:
            avg_engagement = sum(v['engagement_rate'] for v in videos_data) / len(videos_data)
            if avg_engagement > 5:
                insights.append(f"✅ Strong engagement: {avg_engagement:.1f}% avg rate")
            elif avg_engagement < 2:
                insights.append(f"⚠️  Low engagement: {avg_engagement:.1f}% - focus on CTAs")

        # Upload consistency
        total_videos = channel_data.get('total_videos', 0)
        if total_videos > 0:
            insights.append(f"📊 {total_videos} total videos on channel")

        # Views growth
        views_growth = growth_metrics.get('views_growth', 0)
        if views_growth > 1000:
            insights.append(f"✅ View growth: +{self.format_number(views_growth)}")

        for insight in insights:
            self.console.print(f"  {insight}")

        self.console.print()

    def generate_weekly_summary(
        self,
        channel_data: Dict,
        growth_metrics: Dict,
        top_videos: List[Dict]
    ) -> str:
        """
        Generate a concise weekly summary for email/notifications.

        Returns:
            Formatted text summary
        """
        summary = []
        summary.append("📊 WEEKLY YOUTUBE SUMMARY")
        summary.append("=" * 50)
        summary.append("")

        # Subscribers
        subs = channel_data.get('total_subscribers', 0)
        sub_growth = growth_metrics.get('subscriber_growth', 0)
        summary.append(f"Subscribers: {self.format_number(subs)} ({sub_growth:+d})")

        # Views
        views_growth = growth_metrics.get('views_growth', 0)
        summary.append(f"Views Growth: +{self.format_number(views_growth)}")

        # Top video
        if top_videos:
            top = top_videos[0]
            summary.append("")
            summary.append("🏆 Top Video:")
            summary.append(f"   {top['title'][:50]}")
            summary.append(f"   {self.format_number(top['views'])} views")

        summary.append("")
        summary.append(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(summary)
