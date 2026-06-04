"""LLM access layer.

Routes model calls through the local Claude Code CLI (`claude -p`) instead of
the metered Anthropic API, so generation runs on the Claude Code subscription.
"""

from .claude_cli import generate, generate_json, ClaudeCLIError

__all__ = ["generate", "generate_json", "ClaudeCLIError"]
