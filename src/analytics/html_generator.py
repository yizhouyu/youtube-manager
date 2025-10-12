"""HTML dashboard generator for analytics reports."""

from datetime import datetime
from typing import Dict, List
from pathlib import Path


class HTMLDashboardGenerator:
    """Generates beautiful HTML dashboards for YouTube analytics."""

    def __init__(self):
        """Initialize the HTML generator."""
        pass

    def generate_dashboard(
        self,
        channel_data: Dict,
        videos_data: List[Dict],
        growth_metrics: Dict,
        top_videos: List[Dict],
        underperforming: List[Dict],
        output_file: str = None
    ) -> str:
        """
        Generate a complete HTML dashboard.

        Args:
            channel_data: Channel analytics data
            videos_data: Recent videos data
            growth_metrics: Growth metrics
            top_videos: Top performing videos
            underperforming: Underperforming videos
            output_file: Path to save HTML file (optional)

        Returns:
            Path to generated HTML file
        """
        if output_file is None:
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            output_file = f"analytics_report_{timestamp}.html"

        html_content = self._generate_html(
            channel_data=channel_data,
            videos_data=videos_data,
            growth_metrics=growth_metrics,
            top_videos=top_videos,
            underperforming=underperforming
        )

        output_path = Path(output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return str(output_path.absolute())

    def _generate_html(
        self,
        channel_data: Dict,
        videos_data: List[Dict],
        growth_metrics: Dict,
        top_videos: List[Dict],
        underperforming: List[Dict]
    ) -> str:
        """Generate the complete HTML content."""

        # Calculate aggregates for recent videos
        total_views = sum(v['views'] for v in videos_data) if videos_data else 0
        total_likes = sum(v['likes'] for v in videos_data) if videos_data else 0
        total_comments = sum(v['comments'] for v in videos_data) if videos_data else 0
        avg_engagement = (
            sum(v['engagement_rate'] for v in videos_data) / len(videos_data)
            if videos_data else 0
        )

        # Prepare chart data
        top_videos_labels = [v['title'][:30] + '...' if len(v['title']) > 30 else v['title'] for v in top_videos[:10]]
        top_videos_views = [v['views'] for v in top_videos[:10]]
        top_videos_engagement = [v['engagement_rate'] for v in top_videos[:10]]

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Analytics Dashboard - {datetime.now().strftime('%Y-%m-%d')}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: white;
            padding: 2rem;
            color: #333;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            text-align: center;
            color: #333;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 3px solid #667eea;
        }}

        .header h1 {{
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
            color: #667eea;
        }}

        .header .subtitle {{
            font-size: 1.1rem;
            color: #6b7280;
        }}

        .dashboard {{
            background: white;
            padding: 2rem;
        }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}

        .metric-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1.5rem;
            border-radius: 15px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }}

        .metric-card:hover {{
            transform: translateY(-5px);
        }}

        .metric-card .label {{
            font-size: 0.9rem;
            opacity: 0.9;
            margin-bottom: 0.5rem;
        }}

        .metric-card .value {{
            font-size: 2rem;
            font-weight: bold;
            margin-bottom: 0.3rem;
        }}

        .metric-card .change {{
            font-size: 0.9rem;
            opacity: 0.8;
        }}

        .metric-card.positive .change {{
            color: #4ade80;
        }}

        .metric-card.negative .change {{
            color: #f87171;
        }}

        .section {{
            margin-bottom: 2rem;
        }}

        .section-title {{
            font-size: 1.5rem;
            font-weight: bold;
            margin-bottom: 1rem;
            color: #667eea;
            border-bottom: 3px solid #667eea;
            padding-bottom: 0.5rem;
        }}

        .chart-container {{
            background: #f8f9fa;
            padding: 1.5rem;
            border-radius: 10px;
            margin-bottom: 2rem;
        }}

        .chart-wrapper {{
            position: relative;
            height: 400px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }}

        thead {{
            background: #667eea;
            color: white;
        }}

        th, td {{
            padding: 1rem;
            text-align: left;
            border-bottom: 1px solid #e5e7eb;
        }}

        tbody tr:hover {{
            background: #f8f9fa;
        }}

        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
        }}

        .badge.success {{
            background: #d1fae5;
            color: #065f46;
        }}

        .badge.warning {{
            background: #fef3c7;
            color: #92400e;
        }}

        .badge.danger {{
            background: #fee2e2;
            color: #991b1b;
        }}

        .insights {{
            background: #f0f9ff;
            border-left: 4px solid #0ea5e9;
            padding: 1.5rem;
            border-radius: 10px;
            margin-top: 2rem;
        }}

        .insights h3 {{
            color: #0c4a6e;
            margin-bottom: 1rem;
        }}

        .insights ul {{
            list-style: none;
        }}

        .insights li {{
            padding: 0.5rem 0;
            color: #0c4a6e;
        }}

        .insights li::before {{
            content: "💡 ";
            margin-right: 0.5rem;
        }}

        .footer {{
            text-align: center;
            color: #6b7280;
            margin-top: 2rem;
            padding-top: 1rem;
            border-top: 1px solid #e5e7eb;
        }}

        .footer a {{
            color: #667eea;
            text-decoration: none;
        }}

        .footer a:hover {{
            text-decoration: underline;
        }}

        @media print {{
            body {{
                background: white;
                padding: 1rem;
            }}

            .metric-card {{
                break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 YouTube Analytics Dashboard</h1>
            <p class="subtitle">Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
        </div>

        <div class="dashboard">
            <!-- Channel Overview -->
            <div class="section">
                <h2 class="section-title">📺 Channel Overview</h2>
                <div class="metrics-grid">
                    <div class="metric-card {self._get_change_class(growth_metrics.get('subscriber_growth', 0))}">
                        <div class="label">Total Subscribers</div>
                        <div class="value">{self._format_number(channel_data.get('total_subscribers', 0))}</div>
                        <div class="change">{self._format_change(growth_metrics.get('subscriber_growth', 0))}</div>
                    </div>
                    <div class="metric-card">
                        <div class="label">Total Videos</div>
                        <div class="value">{channel_data.get('total_videos', 0)}</div>
                        <div class="change">All time</div>
                    </div>
                    <div class="metric-card {self._get_change_class(growth_metrics.get('views_growth', 0))}">
                        <div class="label">Total Channel Views</div>
                        <div class="value">{self._format_number(channel_data.get('total_views', 0))}</div>
                        <div class="change">{self._format_change(growth_metrics.get('views_growth', 0))}</div>
                    </div>
                </div>
            </div>

            <!-- Recent Performance -->
            <div class="section">
                <h2 class="section-title">📈 Recent Performance</h2>
                <p style="color: #6b7280; margin-bottom: 1rem;">Last {growth_metrics.get('period_days', 7)} days • {len(videos_data)} videos tracked</p>
                <div class="metrics-grid">
                    <div class="metric-card" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);">
                        <div class="label">Total Views</div>
                        <div class="value">{self._format_number(total_views)}</div>
                    </div>
                    <div class="metric-card" style="background: linear-gradient(135deg, #ec4899 0%, #be185d 100%);">
                        <div class="label">Total Likes</div>
                        <div class="value">{self._format_number(total_likes)}</div>
                    </div>
                    <div class="metric-card" style="background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%);">
                        <div class="label">Total Comments</div>
                        <div class="value">{self._format_number(total_comments)}</div>
                    </div>
                    <div class="metric-card" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%);">
                        <div class="label">Avg Engagement</div>
                        <div class="value">{avg_engagement:.2f}%</div>
                    </div>
                </div>
            </div>

            <!-- Charts -->
            <div class="section">
                <h2 class="section-title">📊 Performance Charts</h2>

                <!-- Top Videos by Views -->
                <div class="chart-container">
                    <h3 style="margin-bottom: 1rem; color: #374151;">Top Videos by Views</h3>
                    <div class="chart-wrapper">
                        <canvas id="viewsChart"></canvas>
                    </div>
                </div>

                <!-- Engagement Rate Comparison -->
                <div class="chart-container">
                    <h3 style="margin-bottom: 1rem; color: #374151;">Engagement Rate Comparison</h3>
                    <div class="chart-wrapper">
                        <canvas id="engagementChart"></canvas>
                    </div>
                </div>
            </div>

            <!-- Top Performing Videos -->
            <div class="section">
                <h2 class="section-title">🏆 Top Performing Videos</h2>
                <table>
                    <thead>
                        <tr>
                            <th style="width: 50px;">#</th>
                            <th>Title</th>
                            <th style="width: 120px;">Views</th>
                            <th style="width: 120px;">Likes</th>
                            <th style="width: 120px;">Engagement</th>
                        </tr>
                    </thead>
                    <tbody>
                        {self._generate_top_videos_rows(top_videos[:10])}
                    </tbody>
                </table>
            </div>

            <!-- Underperforming Videos -->
            {self._generate_underperforming_section(underperforming)}

            <!-- Insights -->
            {self._generate_insights_section(channel_data, videos_data, growth_metrics)}
        </div>

        <div class="footer">
            <p>Generated by YouTube Manager • <a href="https://github.com/yizhouyu/youtube-manager">GitHub</a></p>
        </div>
    </div>

    <script>
        // Top Videos by Views Chart
        const viewsCtx = document.getElementById('viewsChart').getContext('2d');
        new Chart(viewsCtx, {{
            type: 'bar',
            data: {{
                labels: {top_videos_labels},
                datasets: [{{
                    label: 'Views',
                    data: {top_videos_views},
                    backgroundColor: 'rgba(102, 126, 234, 0.8)',
                    borderColor: 'rgba(102, 126, 234, 1)',
                    borderWidth: 2,
                    borderRadius: 8
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        display: false
                    }},
                    tooltip: {{
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        padding: 12,
                        titleFont: {{
                            size: 14
                        }},
                        bodyFont: {{
                            size: 13
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        grid: {{
                            color: 'rgba(0, 0, 0, 0.05)'
                        }},
                        ticks: {{
                            callback: function(value) {{
                                if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M';
                                if (value >= 1000) return (value / 1000).toFixed(1) + 'K';
                                return value;
                            }}
                        }}
                    }},
                    x: {{
                        grid: {{
                            display: false
                        }}
                    }}
                }}
            }}
        }});

        // Engagement Rate Chart
        const engagementCtx = document.getElementById('engagementChart').getContext('2d');
        new Chart(engagementCtx, {{
            type: 'line',
            data: {{
                labels: {top_videos_labels},
                datasets: [{{
                    label: 'Engagement Rate (%)',
                    data: {top_videos_engagement},
                    backgroundColor: 'rgba(236, 72, 153, 0.1)',
                    borderColor: 'rgba(236, 72, 153, 1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointBackgroundColor: 'rgba(236, 72, 153, 1)',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 5,
                    pointHoverRadius: 7
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        display: false
                    }},
                    tooltip: {{
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        padding: 12,
                        callbacks: {{
                            label: function(context) {{
                                return context.parsed.y.toFixed(2) + '%';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    y: {{
                        beginAtZero: true,
                        grid: {{
                            color: 'rgba(0, 0, 0, 0.05)'
                        }},
                        ticks: {{
                            callback: function(value) {{
                                return value.toFixed(1) + '%';
                            }}
                        }}
                    }},
                    x: {{
                        grid: {{
                            display: false
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""

    def _format_number(self, num: int) -> str:
        """Format large numbers with K/M suffixes."""
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num/1_000:.1f}K"
        return str(num)

    def _format_change(self, value: int) -> str:
        """Format change value with +/- prefix."""
        if value > 0:
            return f"+{self._format_number(value)}"
        elif value < 0:
            return f"{self._format_number(value)}"
        else:
            return "No change"

    def _get_change_class(self, value: int) -> str:
        """Get CSS class based on positive/negative change."""
        if value > 0:
            return "positive"
        elif value < 0:
            return "negative"
        return ""

    def _generate_top_videos_rows(self, top_videos: List[Dict]) -> str:
        """Generate HTML table rows for top videos."""
        rows = []
        for idx, video in enumerate(top_videos, 1):
            badge_class = "success" if video['engagement_rate'] > 5 else "warning" if video['engagement_rate'] > 2 else "danger"
            rows.append(f"""
                <tr>
                    <td style="font-weight: bold; color: #667eea;">#{idx}</td>
                    <td style="max-width: 400px;">{video['title'][:80]}</td>
                    <td>{self._format_number(video['views'])}</td>
                    <td>{self._format_number(video['likes'])}</td>
                    <td><span class="badge {badge_class}">{video['engagement_rate']:.2f}%</span></td>
                </tr>
            """)
        return '\n'.join(rows)

    def _generate_underperforming_section(self, underperforming: List[Dict]) -> str:
        """Generate underperforming videos section."""
        if not underperforming:
            return ""

        rows = []
        for video in underperforming[:5]:
            try:
                pub_date = datetime.fromisoformat(video['published_at'].replace('Z', '+00:00'))
                days_ago = (datetime.now(pub_date.tzinfo) - pub_date).days
                pub_str = f"{days_ago}d ago"
            except:
                pub_str = "N/A"

            rows.append(f"""
                <tr>
                    <td style="max-width: 400px;">{video['title'][:80]}</td>
                    <td>{self._format_number(video['views'])}</td>
                    <td>{pub_str}</td>
                </tr>
            """)

        return f"""
            <div class="section">
                <h2 class="section-title">⚠️ Videos Needing Attention</h2>
                <p style="color: #6b7280; margin-bottom: 1rem;">Bottom 25% by views</p>
                <table>
                    <thead>
                        <tr>
                            <th>Title</th>
                            <th style="width: 120px;">Views</th>
                            <th style="width: 120px;">Published</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(rows)}
                    </tbody>
                </table>
            </div>
        """

    def _generate_insights_section(
        self,
        channel_data: Dict,
        videos_data: List[Dict],
        growth_metrics: Dict
    ) -> str:
        """Generate AI insights section."""
        insights = []

        # Growth insight
        sub_growth = growth_metrics.get('subscriber_growth', 0)
        if sub_growth > 0:
            insights.append(f"Growing! +{sub_growth} subscribers in the last {growth_metrics.get('period_days', 7)} days")
        elif sub_growth < 0:
            insights.append(f"Losing subscribers: {sub_growth} in the last {growth_metrics.get('period_days', 7)} days")

        # Engagement insight
        if videos_data:
            avg_engagement = sum(v['engagement_rate'] for v in videos_data) / len(videos_data)
            if avg_engagement > 5:
                insights.append(f"Strong engagement: {avg_engagement:.1f}% average rate")
            elif avg_engagement < 2:
                insights.append(f"Low engagement: {avg_engagement:.1f}% - consider focusing on calls-to-action")

        # Views growth
        views_growth = growth_metrics.get('views_growth', 0)
        if views_growth > 1000:
            insights.append(f"View growth: +{self._format_number(views_growth)} in recent period")

        # Video count
        total_videos = channel_data.get('total_videos', 0)
        if total_videos > 0:
            insights.append(f"{total_videos} total videos on your channel")

        if not insights:
            insights.append("Keep creating great content and tracking your analytics!")

        insights_html = '\n'.join([f"<li>{insight}</li>" for insight in insights])

        return f"""
            <div class="insights">
                <h3>💡 Insights & Recommendations</h3>
                <ul>
                    {insights_html}
                </ul>
            </div>
        """
