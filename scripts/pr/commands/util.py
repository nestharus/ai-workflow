"""Utility functions for PR commands."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.clients.linear_client import _get_default_client
from scripts.pr import git_dao, github_dao

MAX_BRANCH_NAME_LENGTH = 50


def _get_expected_branch_name(linear_branch_name: str) -> str:
    """Get the expected branch name from a Linear branch name.

    Truncates the branch name to MAX_BRANCH_NAME_LENGTH characters to match
    what _find_available_branch_name would produce when creating a new branch.

    Args:
        linear_branch_name: The branch name from Linear (may exceed 50 chars).

    Returns:
        The truncated branch name (max 50 characters).
    """
    if len(linear_branch_name) > MAX_BRANCH_NAME_LENGTH:
        return linear_branch_name[:MAX_BRANCH_NAME_LENGTH]
    return linear_branch_name


def _find_existing_branch_for_ticket(linear_branch_name: str) -> str | None:
    """Find an existing branch that matches the expected pattern for a ticket.

    Searches for branches matching the expected name or with counter suffixes
    (-2, -3, etc.). Returns the first existing branch found.

    Args:
        linear_branch_name: The branch name from Linear (may exceed 50 chars).

    Returns:
        The existing branch name if found, None otherwise.
    """
    expected_base = _get_expected_branch_name(linear_branch_name)

    # Check if the base expected branch exists
    if git_dao.branch_exists(expected_base):
        return expected_base

    # Check for counter suffixes (-2, -3, etc.)
    for counter in range(2, 101):
        suffix = f"-{counter}"
        # Truncate base to ensure total length stays within max_length
        truncated_base = expected_base[: MAX_BRANCH_NAME_LENGTH - len(suffix)]
        candidate = f"{truncated_base}{suffix}"
        if git_dao.branch_exists(candidate):
            return candidate

    return None


def _find_available_branch_name(base_name: str, max_length: int = MAX_BRANCH_NAME_LENGTH) -> str:
    """Find an available branch name, adding a counter if needed.

    Args:
        base_name: The base branch name to start with.
        max_length: Maximum length for the branch name. When adding a counter
            suffix, the base name is truncated to ensure the total length
            stays within this limit.

    Returns:
        An available branch name (base_name, base_name-2, base_name-3, etc.).
    """
    # Truncate base_name if it exceeds max_length
    if len(base_name) > max_length:
        base_name = base_name[:max_length]

    if not git_dao.branch_exists(base_name):
        return base_name

    # Try with counter starting at 2
    counter = 2
    while True:
        suffix = f"-{counter}"
        # Truncate base to ensure total length stays within max_length
        truncated_base = base_name[: max_length - len(suffix)]
        candidate = f"{truncated_base}{suffix}"
        if not git_dao.branch_exists(candidate):
            return candidate
        counter += 1

        # Safety limit to prevent infinite loops
        if counter > 100:
            raise RuntimeError(f"Could not find available branch name for {base_name}")


def _has_thumbs_up_from_author(thread: dict[str, Any]) -> bool:
    """Check if the thread has a thumbs-up reaction from the first author.

    Args:
        thread: Thread dictionary with comments and reactions.

    Returns:
        True if the first author gave a thumbs-up on any comment.
    """
    comments = thread.get("comments", {}).get("nodes", [])
    if not comments:
        return False

    first_author = comments[0].get("author", {}).get("login")
    if not first_author:
        return False

    for comment in comments:
        reactions = comment.get("reactions", {}).get("nodes", [])
        for reaction in reactions:
            if (
                reaction.get("content") == "THUMBS_UP"
                and reaction.get("user", {}).get("login") == first_author
            ):
                return True

    return False


def _thread_has_line_number(thread: dict[str, Any]) -> bool:
    """Check if thread has a line number (file-specific comment).

    Args:
        thread: Thread dictionary.

    Returns:
        True if the thread has a line number.
    """
    return (
        thread.get("line") is not None
        or thread.get("startLine") is not None
        or thread.get("originalLine") is not None
        or thread.get("originalStartLine") is not None
    )


def _format_thread_for_agent(thread: dict[str, Any], index: int) -> dict[str, Any]:
    """Format a thread for agent consumption.

    Args:
        thread: Raw thread dictionary from GraphQL.
        index: Index number for the thread.

    Returns:
        Formatted thread dictionary.
    """
    comments = thread.get("comments", {}).get("nodes", [])
    first_author = comments[0].get("author", {}).get("login") if comments else None

    formatted_comments = []
    for comment in comments:
        formatted_comments.append(
            {
                "id": comment.get("id"),
                "database_id": comment.get("databaseId"),
                "body": comment.get("body"),
                "author": comment.get("author", {}).get("login"),
                "created_at": comment.get("createdAt"),
                "reactions": [
                    {
                        "content": r.get("content"),
                        "user": r.get("user", {}).get("login"),
                    }
                    for r in comment.get("reactions", {}).get("nodes", [])
                ],
            }
        )

    return {
        "index": index,
        "thread_id": thread.get("id"),
        "path": thread.get("path"),
        "line": thread.get("line"),
        "start_line": thread.get("startLine"),
        "original_line": thread.get("originalLine"),
        "original_start_line": thread.get("originalStartLine"),
        "first_author": first_author,
        "comments": formatted_comments,
    }


def _read_thread_file(thread_file: Path) -> dict[str, Any]:
    """Read and parse a thread JSON file.

    Args:
        thread_file: Path to the thread JSON file.

    Returns:
        Parsed thread data.
    """
    content = thread_file.read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(content)
    return data


def _get_open_prs_for_ticket(ticket_id: str, exclude_pr: int | None = None) -> list[dict[str, Any]]:
    """Get list of open PRs for a Linear ticket.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").
        exclude_pr: Optional PR number to exclude from results.

    Returns:
        List of dicts with 'url' and 'number' for each open PR.
    """
    attachments = _get_default_client().fetch_github_attachments(ticket_id)

    # Extract PR candidates from attachments
    pr_candidates: list[tuple[str, int]] = []
    for attachment in attachments:
        url = attachment.get("url", "")
        if "/pull/" in url:
            match = re.search(r"/pull/(\d+)", url)
            if match:
                pr_candidates.append((url, int(match.group(1))))

    # Filter to only open PRs
    open_prs: list[dict[str, Any]] = []
    for url, number in pr_candidates:
        if exclude_pr is not None and number == exclude_pr:
            continue
        try:
            gh_pr_info = github_dao.get_pr_info(number)
            if gh_pr_info.get("state") == "OPEN":
                open_prs.append({"url": url, "number": number})
        except github_dao.GraphQLError:
            continue

    return open_prs


def _looks_like_pr_id(identifier: str) -> int | None:
    """Check if identifier looks like a PR ID (e.g., 17 or #17).

    Args:
        identifier: String to check.

    Returns:
        PR number if it matches, None otherwise.
    """
    # Strip leading # if present
    cleaned = identifier.lstrip("#")
    if cleaned.isdigit():
        return int(cleaned)
    return None


def _looks_like_ticket_id(identifier: str) -> bool:
    """Check if identifier looks like a Linear ticket ID (e.g., NES-87).

    Ticket IDs have format: LETTERS-NUMBER (e.g., NES-87, PROJ-123).

    Args:
        identifier: String to check.

    Returns:
        True if it matches the ticket ID pattern (letters-digits).
    """
    return bool(re.match(r"^[A-Za-z]+-\d+$", identifier))


def _is_valid_branch_name(
    branch_name: str, expected_base: str, max_length: int = MAX_BRANCH_NAME_LENGTH
) -> bool:
    """Check if a branch name matches the expected pattern.

    A branch name is valid if it matches either:
    1. The expected base name (truncated to max_length if needed)
    2. The pattern <truncated_base>-N where N is a counter >= 2

    Args:
        branch_name: The branch name to validate.
        expected_base: The expected base branch name from Linear.
        max_length: Maximum length for branch names (default 50).

    Returns:
        True if the branch name is valid, False otherwise.
    """
    # Enforce overall max length to prevent long numeric suffixes from bypassing the limit
    if len(branch_name) > max_length:
        return False

    # Truncate expected base if it exceeds max_length
    if len(expected_base) > max_length:
        truncated_base = expected_base[:max_length]
    else:
        truncated_base = expected_base

    # Check for exact match
    if branch_name == truncated_base:
        return True

    # Check for pattern with counter suffix: <base>-N or <truncated_base>-N
    # The counter suffix requires the base to be truncated to fit within max_length
    pattern = r"^(.+)-(\d+)$"
    match = re.match(pattern, branch_name)
    if not match:
        return False

    base_part = match.group(1)
    counter_str = match.group(2)

    # Counter must be >= 2 (per _find_available_branch_name logic)
    try:
        counter = int(counter_str)
        if counter < 2:
            return False
    except ValueError:
        return False

    # The base part should match a truncated version of expected_base
    # The truncation accounts for the suffix length
    suffix_len = len(f"-{counter_str}")
    max_base_len = max_length - suffix_len
    expected_truncated = expected_base[:max_base_len]

    return base_part == expected_truncated


def _extract_ticket_id_from_branch(branch_name: str) -> str | None:
    """Extract a ticket ID from a branch name.

    Looks for a ticket ID pattern in the branch name after the last '/'.
    The first two tokens (separated by '-') form the ticket ID:
    - First token: alphanumeric (e.g., 'nes', 'NES', 'PROJ')
    - Second token: numeric (e.g., '87', '123')

    Examples:
        'mrasolomon/nes-87-fix-bug' -> 'NES-87'
        'nes-123-feature' -> 'NES-123'
        'main' -> None

    Args:
        branch_name: The branch name to parse.

    Returns:
        Ticket ID in uppercase (e.g., 'NES-87'), or None if no valid pattern found.
    """
    # Get part after last '/' (or whole string if no '/')
    name_part = branch_name.rsplit("/", 1)[1] if "/" in branch_name else branch_name

    # Split by '-' and check first two tokens
    parts = name_part.split("-")
    if len(parts) < 2:
        return None

    first_token = parts[0]
    second_token = parts[1]

    # First token must be alphanumeric
    if not first_token.isalnum():
        return None

    # Second token must be numeric
    if not second_token.isdigit():
        return None

    # Return uppercase ticket ID
    return f"{first_token.upper()}-{second_token}"
