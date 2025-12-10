"""Claude CLI invocation utilities for AI commands.

Provides functions to run Claude CLI in headless mode with:
- Model selection (haiku for simple tasks, opus for complex)
- Prompt passing via stdin
- Output capture and parsing
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Model constants - Claude Code accepts these as model aliases
HAIKU_MODEL = "haiku"
OPUS_MODEL = "opus"

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def invoke_claude(
    *,
    prompt: str,
    model: str = OPUS_MODEL,
    system_prompt: str | None = None,
    allowed_tools: list[str] | None = None,
    timeout: int = 300,
) -> tuple[int, str, str]:
    """Invoke Claude CLI in headless mode.

    Args:
        prompt: User prompt to send via stdin.
        model: Model to use (HAIKU_MODEL or OPUS_MODEL).
        system_prompt: Optional system prompt override.
        allowed_tools: Optional list of allowed tools.
        timeout: Command timeout in seconds.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    command = [
        "claude",
        "-p",
        "--dangerously-skip-permissions",
        "--model",
        model,
    ]

    if system_prompt:
        command.extend(["--system-prompt", system_prompt])

    if allowed_tools:
        command.extend(["--allowedTools", ",".join(allowed_tools)])

    try:
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout} seconds"


def invoke_haiku(prompt: str, system_prompt: str | None = None) -> tuple[int, str, str]:
    """Invoke Claude CLI with Haiku for fast parsing tasks.

    Args:
        prompt: User prompt.
        system_prompt: Optional system prompt.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    return invoke_claude(
        prompt=prompt,
        model=HAIKU_MODEL,
        system_prompt=system_prompt,
        allowed_tools=None,  # No tools for parsing tasks
        timeout=60,  # Short timeout for parsing
    )


def invoke_planner(prompt: str) -> tuple[int, str, str]:
    """Invoke planner agent via Claude CLI with Opus.

    Uses the planner agent definition from .claude/agents/planner.md.

    Args:
        prompt: Planner prompt including file reference.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    from scripts.dev.claude_agent_runner import build_command, load_agent

    frontmatter, system_prompt = load_agent("planner")
    command = build_command(frontmatter, system_prompt)

    # Add dangerous permissions flag for headless mode after "claude"
    if "--dangerously-skip-permissions" not in command:
        # Insert after "claude" and before other flags
        command.insert(1, "--dangerously-skip-permissions")

    try:
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=300,
            check=False,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return 1, "", "Planner timed out after 300 seconds"


def parse_comments_with_haiku(comments_json: str) -> list[str]:
    """Parse Linear comments JSON to extract individual comment bodies.

    Uses Haiku to intelligently extract comment bodies from the Linear API
    response format.

    Args:
        comments_json: JSON string from list-unresolved-comments.

    Returns:
        List of comment body strings. Empty list if parsing fails.
    """
    system_prompt = """You are a JSON parser. Extract comment bodies from Linear API response.
Output each comment body on its own line, separated by "---" markers.
Only output the comment bodies, nothing else. No explanations or preamble."""

    prompt = f"""Parse the following JSON and extract each comment body:

{comments_json}

Output format (use exactly this format):
<comment body 1>
---
<comment body 2>
---
<etc>"""

    exit_code, stdout, _ = invoke_haiku(prompt, system_prompt)

    if exit_code != 0 or not stdout.strip():
        return _fallback_parse_comments(comments_json)

    # Split by --- markers and filter empty entries
    comments = [c.strip() for c in stdout.split("---") if c.strip()]
    return comments


def _fallback_parse_comments(comments_json: str) -> list[str]:
    """Fallback parser when Haiku parsing fails.

    Simple JSON extraction without LLM.

    Args:
        comments_json: JSON string from list-unresolved-comments.

    Returns:
        List of comment body strings.
    """
    import json

    try:
        data = json.loads(comments_json)
        comments = data.get("comments", [])
        return [c.get("body", "") for c in comments if c.get("body")]
    except (json.JSONDecodeError, TypeError, KeyError):
        return []
