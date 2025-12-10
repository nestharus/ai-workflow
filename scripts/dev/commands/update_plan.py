"""Update-plan command implementation.

Updates an existing implementation plan with additional requirements from either
a provided prompt or unresolved Linear comments.

Workflow:
1. Validate ticket ID exists via Linear API
2. Fetch ticket description to temp file
3. Determine update source (args prompt or unresolved comments)
4. Parse comments with Haiku if needed
5. Run planner agent for each comment
6. Collect summaries from planner runs
7. Update Linear ticket with modified plan
8. Post summary comment to Linear
9. Cleanup temp file
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.clients.linear_client import LinearClient, LinearClientError
from scripts.dev.commands._claude_invoker import (
    OPUS_MODEL,
    invoke_claude,
    invoke_planner,
    parse_comments_with_haiku,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_DIR = PROJECT_ROOT / ".tmp"


def run(ticket_id: str, update_prompt: str | None = None) -> int:
    """Execute update-plan workflow.

    Args:
        ticket_id: Linear ticket ID (e.g., NES-102).
        update_prompt: Optional update prompt. If None, fetches unresolved comments.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    client = LinearClient()
    temp_file = TMP_DIR / f"{ticket_id}.md"
    summaries: list[str] = []

    try:
        # Step 1: Validate ticket exists
        print(f"Validating ticket {ticket_id}...", file=sys.stderr)
        try:
            ticket = client.get_issue(ticket_id)
        except LinearClientError as e:
            print(f"Error: Ticket validation failed - {e.message}", file=sys.stderr)
            return 1

        title = ticket.get("title", ticket_id)

        # Step 2: Create temp dir and fetch description
        TMP_DIR.mkdir(parents=True, exist_ok=True)

        description = ticket.get("description") or ""
        if not description.strip():
            print(f"Error: Ticket {ticket_id} has no description.", file=sys.stderr)
            print("Suggest running /create-plan first.", file=sys.stderr)
            return 1

        temp_file.write_text(description, encoding="utf-8")
        print(f"Fetched description to {temp_file}", file=sys.stderr)

        # Step 3: Determine update source
        comments_to_process: list[str] = []

        if update_prompt:
            # Use provided prompt
            comments_to_process = [update_prompt]
            print("Using provided update prompt", file=sys.stderr)
        else:
            # Fetch unresolved comments
            print(f"Fetching unresolved comments for {ticket_id}...", file=sys.stderr)
            result = _fetch_unresolved_comments(ticket_id)

            if not result:
                print("No unresolved comments found.", file=sys.stderr)
                return 0

            # Step 4: Parse comments with Haiku
            print("Parsing comments with Haiku...", file=sys.stderr)
            comments_to_process = parse_comments_with_haiku(json.dumps(result))

            if not comments_to_process:
                print("No comments extracted.", file=sys.stderr)
                return 0

        print(f"Processing {len(comments_to_process)} update(s)...", file=sys.stderr)

        # Step 5: Run planner for each comment
        for i, comment in enumerate(comments_to_process, 1):
            print(f"Processing update {i}/{len(comments_to_process)}...", file=sys.stderr)

            planner_prompt = f"""file:{temp_file}

## Update Request
{comment}"""

            exit_code, stdout, stderr = invoke_planner(planner_prompt)

            if exit_code != 0:
                print(f"Error: Planner failed - {stderr}", file=sys.stderr)
                return 1

            # Collect summary from planner output
            summary = stdout.strip() if stdout else f"Update {i} applied"
            summaries.append(summary)
            print(f"Update {i} complete: {summary[:100]}...", file=sys.stderr)

        # Step 6: Update Linear ticket
        print(f"Updating ticket {ticket_id}...", file=sys.stderr)
        _update_ticket_from_file(ticket_id, temp_file)

        # Step 7: Create summary and post comment
        combined_summary = _create_combined_summary(summaries)
        _post_update_comment(ticket_id, combined_summary)

        # Step 8: Print confirmation
        _print_confirmation(ticket_id, title, combined_summary)

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    finally:
        # Step 9: Cleanup
        if temp_file.exists():
            temp_file.unlink()
            print(f"Cleaned up {temp_file}", file=sys.stderr)


def _fetch_unresolved_comments(ticket_id: str) -> dict[str, Any] | None:
    """Fetch unresolved comments via PR CLI.

    Args:
        ticket_id: Linear ticket ID.

    Returns:
        Dict with comments data, or None if no comments or error.
    """
    result = subprocess.run(
        ["uv", "run", "pr", "list-unresolved-comments", ticket_id],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        check=False,
    )

    if result.returncode != 0:
        return None

    try:
        data: dict[str, Any] = json.loads(result.stdout)
        if data.get("totalCount", 0) == 0:
            return None
        return data
    except json.JSONDecodeError:
        return None


def _update_ticket_from_file(ticket_id: str, file_path: Path) -> None:
    """Update ticket description from temp file.

    Args:
        ticket_id: Linear ticket ID.
        file_path: Path to file containing updated description.
    """
    subprocess.run(
        [
            "uv",
            "run",
            "linear",
            "update-issue",
            ticket_id,
            "--description-file",
            str(file_path),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def _post_update_comment(ticket_id: str, summary: str) -> None:
    """Post update summary as comment on Linear ticket.

    Args:
        ticket_id: Linear ticket ID.
        summary: Summary of changes made.
    """
    body = f"""## Plan Updated

Changes incorporated:
{summary}

The implementation plan in the ticket description has been updated."""

    subprocess.run(
        ["uv", "run", "linear", "create-comment", ticket_id, "--body", body],
        cwd=PROJECT_ROOT,
        check=True,
    )


def _create_combined_summary(summaries: list[str]) -> str:
    """Combine planner summaries into a single coherent summary.

    If there's only one summary, returns it directly. Otherwise uses Opus
    to create a combined summary.

    Args:
        summaries: List of individual planner summaries.

    Returns:
        Combined summary string.
    """
    if len(summaries) == 1:
        return summaries[0]

    # Use Opus to combine multiple summaries
    prompt = f"""Combine these planner update summaries into a single coherent summary:

{chr(10).join(f"- {s}" for s in summaries)}

Output a brief, bulleted summary of all changes made. Be concise."""

    system_prompt = "You are a technical writer. Create concise summaries of changes."

    _, stdout, _ = invoke_claude(
        prompt=prompt,
        model=OPUS_MODEL,
        system_prompt=system_prompt,
        timeout=60,
    )

    return stdout.strip() if stdout else "\n".join(f"- {s}" for s in summaries)


def _print_confirmation(ticket_id: str, title: str, summary: str) -> None:
    """Print confirmation message to stdout.

    Args:
        ticket_id: Linear ticket ID.
        title: Ticket title.
        summary: Summary of changes made.
    """
    print(
        f"""
================================================================================
PLAN UPDATE COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: {ticket_id} - {title}

Please review the updated plan on the ticket before executing:
`uv run linear get-issue {ticket_id}`

Changes incorporated:
{summary}
================================================================================
"""
    )
