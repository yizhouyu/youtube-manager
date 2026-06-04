"""Thin wrapper around the Claude Code CLI (`claude -p`).

This replaces direct Anthropic SDK calls (`Anthropic().messages.create(...)`) so
that text + vision generation runs through the Claude Code subscription instead
of a separately-billed API key.

Drop-in usage:

    from src.llm import generate
    text = generate(prompt)                       # text generation
    text = generate(prompt, image_path="/abs.png")  # vision (image analysis)

The function returns the raw assistant text (callers do their own JSON parsing,
exactly as they did with the SDK response).
"""

import json
import re
import shutil
import subprocess
import tempfile

# Default model. `sonnet` resolves to the current Sonnet in the CLI (matches the
# original code's intent of using Sonnet for metadata, not Opus).
DEFAULT_MODEL = "sonnet"

# Generation can involve several hundred output tokens plus CLI startup; give it
# room but don't hang forever.
DEFAULT_TIMEOUT = 240


class ClaudeCLIError(RuntimeError):
    """Raised when the `claude` CLI is missing, errors, or returns no result."""


def _claude_binary() -> str:
    path = shutil.which("claude")
    if not path:
        raise ClaudeCLIError(
            "The `claude` CLI was not found on PATH. Install Claude Code and make "
            "sure you are logged in (so generation uses your subscription)."
        )
    return path


def generate(
    prompt: str,
    model: str = DEFAULT_MODEL,
    image_path: str = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Run a single prompt through `claude -p` and return the assistant text.

    Args:
        prompt: The full prompt to send (built by the caller, unchanged).
        model: Model alias/id passed to `--model` (default: sonnet).
        image_path: Optional absolute path to an image. When provided, the model
            is allowed to use the Read tool and the path is referenced in the
            prompt so it can analyze the image (vision).
        timeout: Seconds before the subprocess is killed.

    Returns:
        The raw text the model produced (may include markdown fences; the caller
        parses it, same as before).

    Raises:
        ClaudeCLIError: if the CLI is missing, times out, or reports an error.
    """
    cmd = [
        _claude_binary(),
        "-p",
        "--model", model,
        "--output-format", "json",
    ]

    full_prompt = prompt
    if image_path:
        # Pre-approve the Read tool so headless mode doesn't block on a
        # permission prompt, and point the model at the image up front.
        cmd += ["--allowedTools", "Read"]
        full_prompt = f"Read and analyze the image at: {image_path}\n\n{prompt}"

    try:
        # Run from a neutral temp dir so the target project's CLAUDE.md / repo
        # context does not bleed into (or derail) the generation.
        proc = subprocess.run(
            cmd,
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCLIError(f"claude -p timed out after {timeout}s") from exc

    if proc.returncode != 0:
        raise ClaudeCLIError(
            f"claude -p exited with code {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:500]}"
        )

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeCLIError(
            f"Could not parse claude -p output as JSON: {proc.stdout[:500]}"
        ) from exc

    if envelope.get("is_error"):
        raise ClaudeCLIError(
            f"claude -p reported an error: {envelope.get('result', '')[:500]}"
        )

    result = envelope.get("result")
    if not result:
        raise ClaudeCLIError(f"claude -p returned no result: {proc.stdout[:500]}")

    return result.strip()


def _extract_json(text: str):
    """Best-effort extraction of a JSON object/array from model output.

    Strips markdown fences and trailing commas, then isolates the outermost
    JSON value. Raises json.JSONDecodeError if it still doesn't parse.
    """
    text = text.strip()

    # Strip ```json ... ``` or ``` ... ``` fences.
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif text.startswith("```"):
        text = text.split("```", 1)[1].rsplit("```", 1)[0]

    # Isolate the outermost JSON value (object or array).
    match = re.search(r"[\{\[][\s\S]*[\}\]]", text)
    if match:
        text = match.group(0)

    # Remove trailing commas before closing braces/brackets.
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    return json.loads(text)


def generate_json(
    prompt: str,
    model: str = DEFAULT_MODEL,
    image_path: str = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 2,
):
    """Generate and parse a JSON response, retrying on malformed output.

    The model occasionally emits JSON with unescaped quotes inside string values
    (common with mixed Chinese/English text), which breaks json.loads. Since each
    call is independent, simply regenerating almost always recovers. Returns the
    parsed object/list.

    Args:
        retries: Number of extra attempts after the first (default 2 -> 3 total).

    Raises:
        ClaudeCLIError: if every attempt fails to produce parseable JSON.
    """
    # Directive that prevents the most common failure: the model emitting
    # straight double-quote characters inside JSON string values (very common
    # with mixed Chinese/English text like 「"震撼"」), which breaks json.loads.
    json_directive = (
        "\n\nCRITICAL OUTPUT FORMAT:\n"
        "- Return ONLY valid, strictly-parseable JSON. No markdown fences, no "
        "commentary before or after.\n"
        "- Inside JSON string values, NEVER use straight double-quote characters "
        '(").  If you need quotation marks inside text, use full-width quotes '
        "（「」or『』）or guillemets（《》）instead.\n"
        "- Do not include literal newlines inside string values; use \\n."
    )

    last_error = None
    for attempt in range(retries + 1):
        attempt_prompt = prompt + json_directive
        if last_error is not None:
            attempt_prompt += (
                f"\n\nYour previous response was NOT valid JSON (error: "
                f"{last_error}). Return corrected, strictly-valid JSON this time."
            )
        text = generate(
            attempt_prompt, model=model, image_path=image_path, timeout=timeout
        )
        try:
            return _extract_json(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue

    raise ClaudeCLIError(
        f"claude -p did not return valid JSON after {retries + 1} attempts: "
        f"{last_error}"
    )
