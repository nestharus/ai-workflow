"""GitHub and Linear operations client for PR management and ticket tracking.

Usage:
    uv run pr fetch-threads --pr <number> --output-dir <path>
    uv run pr commit-push --worktree <path> --message <msg>
    uv run pr post-reply --pr <number> --thread-file <file> --body <text>
    uv run pr resolve-thread --thread-file <file>
    uv run pr deferred-comment --thread-file <file> --body <text>
    uv run pr import-local-tasks --output-dir <path> <body_file1> <body_file2> ...
    uv run pr post-deferred-replies --pr <number> --threads-dir <path>
    uv run pr request-review --pr <number>
    uv run pr get-pr <ticket-id>
    uv run pr get-changed-files --pr <number>
    uv run pr set-ticket-done --ticket <id>
    uv run pr merge-pr --pr <number>
    uv run pr squash-rebase --worktree <path> --base-branch <branch>
    uv run pr merge --ticket <id> --pr <n> --worktree <path> --branch <name> --base-branch <b>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_OWNER = "nestharus"
REPO_NAME = "ai-workflow"
LINEAR_API_URL = "https://api.linear.app/graphql"


class GhNotFoundError(FileNotFoundError):
    """Raised when gh CLI is not available."""

    def __init__(self) -> None:
        """Initialize with default message."""
        super().__init__("gh executable not found on PATH")


class GraphQLError(RuntimeError):
    """Raised when a GraphQL query fails."""

    def __init__(self, message: str) -> None:
        """Initialize with error message."""
        super().__init__(message)


class LinearAPIError(RuntimeError):
    """Raised when a Linear API call fails."""

    def __init__(self, message: str) -> None:
        """Initialize with error message."""
        super().__init__(message)


def _get_gh_exe() -> str:
    """Get the path to gh executable."""
    gh_exe = shutil.which("gh")
    if gh_exe is None:
        raise GhNotFoundError()
    return gh_exe


def _run_gh_command(args: list[str]) -> str:
    """Run a gh command and return stdout."""
    gh_exe = _get_gh_exe()
    result = subprocess.run(
        [gh_exe, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GraphQLError(f"gh command failed: {result.stderr}")
    return result.stdout


def _run_graphql_query(query: str) -> dict[str, Any]:
    """Run a GraphQL query via gh api."""
    output = _run_gh_command(["api", "graphql", "-f", f"query={query}"])
    result: dict[str, Any] = json.loads(output)
    return result


def _run_graphql_mutation(mutation: str) -> dict[str, Any]:
    """Run a GraphQL mutation via gh api."""
    output = _run_gh_command(["api", "graphql", "-f", f"query={mutation}"])
    result: dict[str, Any] = json.loads(output)
    return result


# -----------------------------------------------------------------------------
# Linear API Functions
# -----------------------------------------------------------------------------


def _get_linear_api_key() -> str:
    """Get the Linear API key from environment."""
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise LinearAPIError("LINEAR_API_KEY environment variable not set")
    return api_key


def _run_linear_graphql(query: str) -> dict[str, Any]:
    """Run a GraphQL query against Linear API.

    Args:
        query: GraphQL query string.

    Returns:
        Parsed JSON response.

    Raises:
        LinearAPIError: If the API call fails.
    """
    api_key = _get_linear_api_key()
    data = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
            if "errors" in result:
                raise LinearAPIError(f"Linear API error: {result['errors']}")
            return result
    except urllib.error.URLError as e:
        raise LinearAPIError(f"Linear API request failed: {e}") from e


def get_linear_ticket_info(ticket_id: str) -> dict[str, Any]:
    """Get ticket info from Linear including branch name and PR URL.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Dictionary with keys: id, title, branch_name, pr_url, pr_number, state, team_id.
    """
    query = f"""
{{
  issue(id: "{ticket_id}") {{
    id
    identifier
    title
    branchName
    state {{
      id
      name
      type
    }}
    team {{
      id
    }}
    attachments {{
      nodes {{
        url
        title
      }}
    }}
  }}
}}
"""
    result = _run_linear_graphql(query)
    issue = result.get("data", {}).get("issue")
    if not issue:
        raise LinearAPIError(f"Ticket not found: {ticket_id}")

    # Find the first open PR from attachments (GitHub PR attachments have github.com in URL)
    pr_url = None
    pr_number = None
    attachments = issue.get("attachments", {}).get("nodes", [])

    # Collect all PR candidates from attachments
    pr_candidates: list[tuple[str, int]] = []
    for attachment in attachments:
        url = attachment.get("url", "")
        if "github.com" in url and "/pull/" in url:
            match = re.search(r"/pull/(\d+)", url)
            if match:
                pr_candidates.append((url, int(match.group(1))))

    # Find the first open PR by checking state via GitHub API
    for url, number in pr_candidates:
        try:
            pr_info = get_pr_info(number)
            if pr_info.get("state") == "OPEN":
                pr_url = url
                pr_number = number
                break
        except GraphQLError:
            # If we can't fetch PR info, skip this candidate
            continue

    return {
        "id": issue.get("id"),
        "identifier": issue.get("identifier"),
        "title": issue.get("title"),
        "branch_name": issue.get("branchName"),
        "pr_url": pr_url,
        "pr_number": pr_number,
        "state": issue.get("state", {}).get("name"),
        "state_type": issue.get("state", {}).get("type"),
        "team_id": issue.get("team", {}).get("id"),
    }


def get_done_state_id(team_id: str) -> str:
    """Get the 'Done' workflow state ID for a team.

    Args:
        team_id: Linear team ID.

    Returns:
        The workflow state ID for 'Done' state.
    """
    query = f"""
{{
  team(id: "{team_id}") {{
    states {{
      nodes {{
        id
        name
        type
      }}
    }}
  }}
}}
"""
    result = _run_linear_graphql(query)
    states = result.get("data", {}).get("team", {}).get("states", {}).get("nodes", [])

    # Find state with type "completed" (Done states have this type)
    for state in states:
        if state.get("type") == "completed":
            return str(state.get("id"))

    raise LinearAPIError(f"No 'Done' state found for team {team_id}")


def set_linear_ticket_state(ticket_id: str, state_id: str) -> bool:
    """Update a Linear ticket's state.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").
        state_id: Target workflow state ID.

    Returns:
        True if successful.
    """
    # Need the issue UUID, not the identifier
    info = get_linear_ticket_info(ticket_id)
    issue_uuid = info.get("id")

    mutation = f"""
mutation {{
  issueUpdate(id: "{issue_uuid}", input: {{stateId: "{state_id}"}}) {{
    success
    issue {{
      state {{
        name
      }}
    }}
  }}
}}
"""
    result = _run_linear_graphql(mutation)
    success = result.get("data", {}).get("issueUpdate", {}).get("success", False)
    return bool(success)


# -----------------------------------------------------------------------------
# GitHub PR Functions
# -----------------------------------------------------------------------------


def fetch_unresolved_threads(pr_number: int) -> list[dict[str, Any]]:
    """Fetch unresolved review threads from a PR.

    Args:
        pr_number: The PR number to fetch threads from.

    Returns:
        List of unresolved thread dictionaries.
    """
    query = f"""
{{
  repository(owner: "{REPO_OWNER}", name: "{REPO_NAME}") {{
    pullRequest(number: {pr_number}) {{
      reviewThreads(first: 50) {{
        nodes {{
          id
          isResolved
          path
          line
          startLine
          originalLine
          originalStartLine
          comments(first: 20) {{
            nodes {{
              id
              databaseId
              body
              author {{ login }}
              createdAt
              reactions(first: 10) {{
                nodes {{
                  content
                  user {{ login }}
                }}
              }}
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""
    result = _run_graphql_query(query)

    threads = result.get("data", {}).get("repository", {}).get("pullRequest", {})
    if not threads:
        return []

    review_threads = threads.get("reviewThreads", {}).get("nodes", [])
    return [t for t in review_threads if not t.get("isResolved", True)]


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
        True if the thread has a line number (new or original side, single or multi-line).
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


def resolve_thread(thread_id: str) -> bool:
    """Resolve a review thread.

    Args:
        thread_id: The GraphQL ID of the thread to resolve.

    Returns:
        True if resolution was successful.
    """
    mutation = f"""
mutation {{
  resolveReviewThread(input: {{threadId: "{thread_id}"}}) {{
    thread {{ isResolved }}
  }}
}}
"""
    result = _run_graphql_mutation(mutation)
    thread = result.get("data", {}).get("resolveReviewThread", {}).get("thread", {})
    is_resolved = thread.get("isResolved", False)
    return bool(is_resolved)


def fetch_threads_command(pr_number: int, output_dir: Path) -> int:
    """Fetch threads, filter, format, resolve thumbs-up threads, and save to files.

    Args:
        pr_number: PR number to fetch threads from.
        output_dir: Directory to write thread files to.

    Returns:
        Exit code (0 for success).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean existing thread files
    for existing in output_dir.glob("thread_*.json"):
        existing.unlink()

    threads = fetch_unresolved_threads(pr_number)
    print(f"Fetched {len(threads)} unresolved threads from PR #{pr_number}")

    # Filter to only threads with line numbers
    threads_with_lines = [t for t in threads if _thread_has_line_number(t)]
    print(f"Filtered to {len(threads_with_lines)} threads with line numbers")

    # Separate threads with thumbs-up (auto-resolve) from those needing attention
    threads_to_resolve: list[dict[str, Any]] = []
    threads_to_process: list[dict[str, Any]] = []

    for thread in threads_with_lines:
        if _has_thumbs_up_from_author(thread):
            threads_to_resolve.append(thread)
        else:
            threads_to_process.append(thread)

    # Auto-resolve thumbs-up threads
    print(f"Auto-resolving {len(threads_to_resolve)} threads with thumbs-up reactions")
    for thread in threads_to_resolve:
        thread_id = thread.get("id")
        if thread_id:
            success = resolve_thread(thread_id)
            status = "resolved" if success else "failed"
            path = thread.get("path", "unknown")
            line = thread.get("line", "?")
            print(f"  {status}: {path}:{line}")

    # Write remaining threads to files
    print(f"Writing {len(threads_to_process)} threads to {output_dir}")
    files_created: list[Path] = []
    for index, thread in enumerate(threads_to_process):
        formatted = _format_thread_for_agent(thread, index)
        file_path = output_dir / f"thread_{index}.json"
        file_path.write_text(json.dumps(formatted, indent=2), encoding="utf-8")
        files_created.append(file_path)
        print(f"  Created: {file_path}")

    print("\nSummary:")
    print(f"  Total unresolved threads: {len(threads)}")
    print(f"  Threads with line numbers: {len(threads_with_lines)}")
    print(f"  Auto-resolved (thumbs-up): {len(threads_to_resolve)}")
    print(f"  Files created for review: {len(files_created)}")

    return 0


def commit_push_command(worktree: Path, message: str) -> int:
    """Commit and push changes from a worktree.

    Args:
        worktree: Path to the git worktree.
        message: Commit message.

    Returns:
        Exit code (0 for success).
    """
    if not worktree.is_dir():
        print(f"Error: Worktree not found at {worktree}", file=sys.stderr)
        return 1

    # Check for changes
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if not status_result.stdout.strip():
        print("No changes to commit")
        return 0

    # Stage all changes
    subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)

    # Commit
    subprocess.run(["git", "commit", "-m", message], cwd=worktree, check=True)

    # Push
    subprocess.run(["git", "push"], cwd=worktree, check=True)

    print(f"Successfully committed and pushed: {message}")
    return 0


def _read_thread_file(thread_file: Path) -> dict[str, Any]:
    """Read and parse a thread JSON file.

    Args:
        thread_file: Path to the thread JSON file.

    Returns:
        Parsed thread data.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If the file isn't valid JSON.
    """
    content = thread_file.read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(content)
    return data


def post_reply_command(pr_number: int, thread_file: Path, body: str) -> int:
    """Post a reply to a PR comment.

    Args:
        pr_number: PR number.
        thread_file: Path to the thread JSON file containing comment info.
        body: Reply body text.

    Returns:
        Exit code (0 for success).
    """
    if not thread_file.is_file():
        print(f"Error: Thread file not found: {thread_file}", file=sys.stderr)
        return 1

    thread_data = _read_thread_file(thread_file)
    comments = thread_data.get("comments", [])
    if not comments:
        print(f"Error: No comments in thread file: {thread_file}", file=sys.stderr)
        return 1

    # Reply to the last comment in the thread
    comment_id = comments[-1].get("database_id")
    if not comment_id:
        print(f"Error: No database_id in comment: {thread_file}", file=sys.stderr)
        return 1

    _run_gh_command(
        [
            "api",
            f"repos/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_number}/comments/{comment_id}/replies",
            "-f",
            f"body={body}",
        ]
    )
    print(f"Posted reply to comment {comment_id}")
    return 0


def resolve_thread_command(thread_file: Path) -> int:
    """Resolve a review thread by reading the thread file.

    Args:
        thread_file: Path to the thread JSON file containing thread_id.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    if not thread_file.is_file():
        print(f"Error: Thread file not found: {thread_file}", file=sys.stderr)
        return 1

    thread_data = _read_thread_file(thread_file)
    thread_id = thread_data.get("thread_id")
    if not thread_id:
        print(f"Error: No thread_id in file: {thread_file}", file=sys.stderr)
        return 1

    success = resolve_thread(thread_id)
    if success:
        print(f"Resolved thread: {thread_id}")
        return 0
    print(f"Failed to resolve thread: {thread_id}", file=sys.stderr)
    return 1


def deferred_comment_command(thread_file: Path, body: str) -> int:
    """Store a deferred reply in a thread file for later posting.

    Adds a 'deferred_reply' field to the thread JSON file. The reply will be
    posted when post-deferred-replies is called.

    Args:
        thread_file: Path to the thread JSON file.
        body: Reply body text to store.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    if not thread_file.is_file():
        print(f"Error: Thread file not found: {thread_file}", file=sys.stderr)
        return 1

    thread_data = _read_thread_file(thread_file)
    thread_data["deferred_reply"] = body
    thread_file.write_text(json.dumps(thread_data, indent=2), encoding="utf-8")
    print(f"Stored deferred reply in: {thread_file}")
    return 0


def import_local_tasks_command(output_dir: Path, body_files: list[Path]) -> int:
    """Import local task body files into JSON task files.

    Reads each body file, creates a local_N.json file with the correct format,
    then deletes the body file.

    Args:
        output_dir: Directory to write the local task JSON files to.
        body_files: List of paths to body files (plain text with task content).

    Returns:
        Exit code (0 for success).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, body_file in enumerate(body_files):
        if not body_file.is_file():
            print(f"Warning: Body file not found: {body_file}", file=sys.stderr)
            continue

        body = body_file.read_text(encoding="utf-8").strip()

        task_data = {
            "index": index,
            "origin": "LOCAL",
            "content": body,
            "comments": [
                {
                    "body": body,
                    "author": "local",
                }
            ],
        }
        task_file = output_dir / f"local_{index}.json"
        task_file.write_text(json.dumps(task_data, indent=2), encoding="utf-8")
        print(f"Created: {task_file}")

        # Delete the body file after import
        body_file.unlink()
        print(f"Deleted: {body_file}")

    print(f"\nImported {len(body_files)} local task(s)")
    return 0


def post_deferred_replies_command(pr_number: int, threads_dir: Path) -> int:
    """Post deferred replies from thread files to a PR.

    Scans thread files in the directory for deferred_reply fields and posts
    those replies to the corresponding PR comments. Skips LOCAL origin tasks
    (they don't have GitHub threads to post to).

    Args:
        pr_number: PR number to post replies on.
        threads_dir: Directory containing thread JSON files with deferred replies.

    Returns:
        Exit code (0 for success).
    """
    if not threads_dir.is_dir():
        print(f"Threads directory not found: {threads_dir}", file=sys.stderr)
        return 1

    # Only process thread_*.json files (GitHub threads)
    # local_*.json files have deferred replies too, but those go to terminal output
    # instead of being posted to GitHub (handled by the orchestrator)
    thread_files = sorted(threads_dir.glob("thread_*.json"))
    replies_posted = 0
    for thread_file in thread_files:
        thread_data = _read_thread_file(thread_file)
        deferred_reply = thread_data.get("deferred_reply")
        if deferred_reply:
            comments = thread_data.get("comments", [])
            if not comments:
                print(
                    f"Warning: No comments in thread file: {thread_file}",
                    file=sys.stderr,
                )
                continue

            comment_id = comments[-1].get("database_id")
            if not comment_id:
                print(
                    f"Warning: No database_id in comment: {thread_file}",
                    file=sys.stderr,
                )
                continue

            _run_gh_command(
                [
                    "api",
                    f"repos/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_number}/comments/{comment_id}/replies",
                    "-f",
                    f"body={deferred_reply}",
                ]
            )
            replies_posted += 1
            path = thread_data.get("path", "unknown")
            line = thread_data.get("line", "?")
            print(f"Posted deferred reply to {path}:{line}")

    print(f"Posted {replies_posted} deferred reply(ies)")
    return 0


def request_review_command(pr_number: int) -> int:
    """Request a CodeRabbit review on a PR.

    Args:
        pr_number: PR number to request review on.

    Returns:
        Exit code (0 for success).
    """
    _run_gh_command(
        [
            "pr",
            "comment",
            str(pr_number),
            "--body",
            "@coderabbitai review",
        ]
    )
    print(f"Requested CodeRabbit review on PR #{pr_number}")
    return 0


def open_pr_command(worktree: Path, title: str, body: str, branch: str) -> int:
    """Create a new PR for a branch.

    Args:
        worktree: Path to the git worktree.
        title: PR title.
        body: PR body text.
        branch: Branch name for the PR head.

    Returns:
        Exit code (0 for success).
    """
    if not worktree.is_dir():
        print(f"Error: Worktree not found at {worktree}", file=sys.stderr)
        return 1

    result = subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--head", branch],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Error creating PR: {result.stderr}", file=sys.stderr)
        return 1

    print(result.stdout.strip())
    return 0


def get_pr_info(pr_number: int) -> dict[str, Any]:
    """Get detailed PR info from GitHub including base branch.

    Args:
        pr_number: The PR number.

    Returns:
        Dictionary with PR details including base_branch.
    """
    query = f"""
{{
  repository(owner: "{REPO_OWNER}", name: "{REPO_NAME}") {{
    pullRequest(number: {pr_number}) {{
      baseRefName
      headRefName
      state
      title
    }}
  }}
}}
"""
    result = _run_graphql_query(query)
    pr = result.get("data", {}).get("repository", {}).get("pullRequest", {})
    return {
        "base_branch": pr.get("baseRefName"),
        "head_branch": pr.get("headRefName"),
        "state": pr.get("state"),
        "title": pr.get("title"),
    }


def get_pr_changed_files(pr_number: int) -> list[str]:
    """Get list of files changed in a PR.

    Args:
        pr_number: The PR number.

    Returns:
        List of file paths changed in the PR.
    """
    # Use REST API for files as GraphQL pagination is complex for this
    output = _run_gh_command(
        ["api", f"repos/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_number}/files", "--paginate"]
    )
    files_data = json.loads(output)
    return [f.get("filename", "") for f in files_data if f.get("filename")]


def get_pr_command(ticket_id: str) -> int:
    """Get PR info for a Linear ticket: branch name, PR number, PR URL, base branch.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Exit code (0 for success).
    """
    try:
        info = get_linear_ticket_info(ticket_id)
        pr_number = info.get("pr_number")

        pr_info: dict[str, Any] = {
            "branch_name": info.get("branch_name"),
            "pr_number": pr_number,
            "pr_url": info.get("pr_url"),
            "base_branch": None,
        }

        # If we have a PR number, fetch the base branch from GitHub
        if pr_number:
            gh_pr_info = get_pr_info(pr_number)
            pr_info["base_branch"] = gh_pr_info.get("base_branch")

        print(json.dumps(pr_info, indent=2))
        return 0
    except LinearAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except GraphQLError as e:
        print(f"Error fetching PR info from GitHub: {e}", file=sys.stderr)
        return 1


def get_changed_files_command(pr_number: int) -> int:
    """Get list of files changed in a PR.

    Args:
        pr_number: PR number.

    Returns:
        Exit code (0 for success).
    """
    try:
        files = get_pr_changed_files(pr_number)
        print(json.dumps(files, indent=2))
        return 0
    except GraphQLError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def set_ticket_done_command(ticket_id: str) -> int:
    """Mark a Linear ticket as Done.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Exit code (0 for success).
    """
    try:
        info = get_linear_ticket_info(ticket_id)
        team_id = info.get("team_id")
        if not team_id:
            print(f"Error: Could not get team ID for {ticket_id}", file=sys.stderr)
            return 1

        done_state_id = get_done_state_id(team_id)
        success = set_linear_ticket_state(ticket_id, done_state_id)

        if success:
            print(f"Marked {ticket_id} as Done")
            return 0
        print(f"Failed to mark {ticket_id} as Done", file=sys.stderr)
        return 1
    except LinearAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def merge_pr_command(pr_number: int) -> int:
    """Merge a PR using squash merge.

    Args:
        pr_number: PR number to merge.

    Returns:
        Exit code (0 for success).
    """
    result = subprocess.run(
        ["gh", "pr", "merge", str(pr_number), "--squash", "--auto"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Error merging PR: {result.stderr}", file=sys.stderr)
        return 1

    print(f"Merged PR #{pr_number}")
    return 0


def squash_rebase_command(worktree: Path, base_branch: str) -> int:
    """Squash all commits and rebase onto base branch.

    Always squashes first (if multiple commits), then rebases.

    Args:
        worktree: Path to the git worktree.
        base_branch: Target branch to rebase onto.

    Returns:
        Exit code (0 for success, 1 if conflicts need resolution).
    """
    if not worktree.is_dir():
        print(f"Error: Worktree not found at {worktree}", file=sys.stderr)
        return 1

    # Fetch latest target branch
    print(f"Fetching origin/{base_branch}...")
    result = subprocess.run(
        ["git", "fetch", "origin", base_branch],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Error fetching branch: {result.stderr}", file=sys.stderr)
        return 1

    # Count commits ahead of target branch
    result = subprocess.run(
        ["git", "rev-list", "--count", f"origin/{base_branch}..HEAD"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Error counting commits: {result.stderr}", file=sys.stderr)
        return 1

    commit_count = int(result.stdout.strip())
    print(f"Found {commit_count} commit(s) ahead of origin/{base_branch}")

    # If more than 1 commit, squash them using soft reset and recommit
    if commit_count > 1:
        print(f"Squashing {commit_count} commits...")

        # Get the merge base
        result = subprocess.run(
            ["git", "merge-base", f"origin/{base_branch}", "HEAD"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"Error finding merge base: {result.stderr}", file=sys.stderr)
            return 1
        merge_base = result.stdout.strip()

        # Get the current commit message for the squashed commit
        result = subprocess.run(
            ["git", "log", "--format=%B", "-1"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        commit_msg = result.stdout.strip() if result.returncode == 0 else "Squashed commits"

        # Soft reset to merge base, keeping changes staged
        result = subprocess.run(
            ["git", "reset", "--soft", merge_base],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"Error during soft reset: {result.stderr}", file=sys.stderr)
            return 1

        # Recommit with the original message
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"Error creating squashed commit: {result.stderr}", file=sys.stderr)
            return 1

        print("Commits squashed successfully")

    # Rebase onto target branch
    print(f"Rebasing onto origin/{base_branch}...")
    result = subprocess.run(
        ["git", "rebase", f"origin/{base_branch}"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        # Check if it's a conflict situation
        if "CONFLICT" in result.stdout or "CONFLICT" in result.stderr:
            print("Rebase conflicts detected. Resolve conflicts and continue.")
            print("After resolving: git add <files> && git rebase --continue")
            return 1
        print(f"Error during rebase: {result.stderr}", file=sys.stderr)
        return 1

    print("Squash and rebase completed successfully")
    return 0


def merge_workflow_command(
    ticket_id: str,
    pr_number: int,
    worktree: Path,
    branch_name: str,
    base_branch: str,
) -> int:
    """Complete merge workflow: merge PR, cleanup, sync, mark done.

    Performs:
    1. Merge the PR (squash merge)
    2. Remove git worktree
    3. Delete local branch
    4. Sync target branch (fetch, stash, checkout, pull, stash pop)
    5. Mark Linear ticket as Done

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").
        pr_number: PR number to merge.
        worktree: Path to the git worktree.
        branch_name: Name of the branch to delete.
        base_branch: Target branch to sync.

    Returns:
        Exit code (0 for success).
    """
    errors: list[str] = []

    # Step 1: Merge the PR
    print(f"Step 1: Merging PR #{pr_number}...")
    result = subprocess.run(
        ["gh", "pr", "merge", str(pr_number), "--squash"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Error merging PR: {result.stderr}", file=sys.stderr)
        return 1
    print(f"PR #{pr_number} merged successfully")

    # Step 2: Remove worktree
    print(f"Step 2: Removing worktree {worktree}...")
    if worktree.is_dir():
        result = subprocess.run(
            ["git", "worktree", "remove", str(worktree)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            errors.append(f"Failed to remove worktree: {result.stderr}")
            print(f"Warning: {errors[-1]}", file=sys.stderr)
        else:
            print("Worktree removed successfully")
    else:
        print(f"Worktree not found at {worktree}, skipping removal")

    # Step 3: Delete local branch
    print(f"Step 3: Deleting local branch {branch_name}...")
    result = subprocess.run(
        ["git", "branch", "-D", branch_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        errors.append(f"Failed to delete branch: {result.stderr}")
        print(f"Warning: {errors[-1]}", file=sys.stderr)
    else:
        print("Local branch deleted successfully")

    # Step 4: Sync target branch
    print(f"Step 4: Syncing {base_branch}...")

    # Fetch all and prune
    subprocess.run(
        ["git", "fetch", "--all", "--prune"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Stash any local changes
    stash_result = subprocess.run(
        ["git", "stash"],
        capture_output=True,
        text=True,
        check=False,
    )
    had_stash = "No local changes" not in stash_result.stdout

    # Checkout target branch
    result = subprocess.run(
        ["git", "checkout", base_branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        errors.append(f"Failed to checkout {base_branch}: {result.stderr}")
        print(f"Warning: {errors[-1]}", file=sys.stderr)
    else:
        # Pull latest
        result = subprocess.run(
            ["git", "pull"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            errors.append(f"Failed to pull: {result.stderr}")
            print(f"Warning: {errors[-1]}", file=sys.stderr)
        else:
            print(f"Synced {base_branch} successfully")

    # Pop stash if we had one
    if had_stash:
        result = subprocess.run(
            ["git", "stash", "pop"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            errors.append(f"Stash pop had conflicts: {result.stderr}")
            print(f"Warning: {errors[-1]} - manual resolution required", file=sys.stderr)

    # Step 5: Mark ticket as Done
    print(f"Step 5: Marking {ticket_id} as Done...")
    try:
        info = get_linear_ticket_info(ticket_id)
        team_id = info.get("team_id")
        if team_id:
            done_state_id = get_done_state_id(team_id)
            success = set_linear_ticket_state(ticket_id, done_state_id)
            if success:
                print(f"Marked {ticket_id} as Done")
            else:
                errors.append(f"Failed to mark {ticket_id} as Done")
                print(f"Warning: {errors[-1]}", file=sys.stderr)
        else:
            errors.append(f"Could not get team ID for {ticket_id}")
            print(f"Warning: {errors[-1]}", file=sys.stderr)
    except LinearAPIError as e:
        errors.append(f"Linear API error: {e}")
        print(f"Warning: {errors[-1]}", file=sys.stderr)

    # Summary
    print("\n" + "=" * 60)
    print("MERGE WORKFLOW COMPLETE")
    print("=" * 60)
    print(f"Ticket: {ticket_id}")
    print(f"PR: #{pr_number}")
    print(f"Branch: {branch_name}")
    print(f"Target: {base_branch}")
    if errors:
        print(f"\nWarnings ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")
    print("=" * 60)

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="GitHub PR operations client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # fetch-threads command
    fetch_parser = subparsers.add_parser(
        "fetch-threads",
        help="Fetch unresolved threads, filter, format, and save to files",
    )
    fetch_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number to fetch threads from",
    )
    fetch_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write thread files to",
    )

    # commit-push command
    commit_parser = subparsers.add_parser(
        "commit-push",
        help="Commit and push changes from a worktree",
    )
    commit_parser.add_argument(
        "--worktree",
        type=Path,
        required=True,
        help="Path to the git worktree",
    )
    commit_parser.add_argument(
        "--message",
        required=True,
        help="Commit message",
    )

    # post-reply command
    reply_parser = subparsers.add_parser(
        "post-reply",
        help="Post a reply to a PR comment",
    )
    reply_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number",
    )
    reply_parser.add_argument(
        "--thread-file",
        type=Path,
        required=True,
        help="Path to thread JSON file",
    )
    reply_parser.add_argument(
        "--body",
        required=True,
        help="Reply body text",
    )

    # resolve-thread command
    resolve_parser = subparsers.add_parser(
        "resolve-thread",
        help="Resolve a review thread",
    )
    resolve_parser.add_argument(
        "--thread-file",
        type=Path,
        required=True,
        help="Path to thread JSON file",
    )

    # deferred-comment command
    deferred_parser = subparsers.add_parser(
        "deferred-comment",
        help="Store a deferred reply in a thread file for later posting",
    )
    deferred_parser.add_argument(
        "--thread-file",
        type=Path,
        required=True,
        help="Path to thread JSON file",
    )
    deferred_parser.add_argument(
        "--body",
        required=True,
        help="Reply body text to store",
    )

    # import-local-tasks command
    import_tasks_parser = subparsers.add_parser(
        "import-local-tasks",
        help="Import local task body files into JSON task files",
    )
    import_tasks_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write the local task JSON files to",
    )
    import_tasks_parser.add_argument(
        "body_files",
        nargs="+",
        type=Path,
        help="Paths to body files (plain text with task content)",
    )

    # post-deferred-replies command
    post_replies_parser = subparsers.add_parser(
        "post-deferred-replies",
        help="Post deferred replies from thread files to a PR",
    )
    post_replies_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number",
    )
    post_replies_parser.add_argument(
        "--threads-dir",
        type=Path,
        required=True,
        help="Directory containing thread files with deferred replies",
    )

    # request-review command
    review_parser = subparsers.add_parser(
        "request-review",
        help="Request a CodeRabbit review on a PR",
    )
    review_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number",
    )

    # open-pr command
    open_parser = subparsers.add_parser(
        "open-pr",
        help="Create a new PR for a branch",
    )
    open_parser.add_argument(
        "--worktree",
        type=Path,
        required=True,
        help="Path to the git worktree",
    )
    open_parser.add_argument(
        "--title",
        required=True,
        help="PR title",
    )
    open_parser.add_argument(
        "--body",
        required=True,
        help="PR body text",
    )
    open_parser.add_argument(
        "--branch",
        required=True,
        help="Branch name for the PR head",
    )

    # get-pr command
    pr_info_parser = subparsers.add_parser(
        "get-pr",
        help="Get PR info for a Linear ticket (branch name, PR number, PR URL, base branch)",
    )
    pr_info_parser.add_argument(
        "ticket_id",
        help="Linear ticket ID (e.g., NES-123)",
    )

    # get-changed-files command
    changed_files_parser = subparsers.add_parser(
        "get-changed-files",
        help="Get list of files changed in a PR",
    )
    changed_files_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number",
    )

    # set-ticket-done command
    done_parser = subparsers.add_parser(
        "set-ticket-done",
        help="Mark a Linear ticket as Done",
    )
    done_parser.add_argument(
        "--ticket",
        required=True,
        help="Linear ticket ID (e.g., NES-123)",
    )

    # merge-pr command (simple merge only)
    merge_parser = subparsers.add_parser(
        "merge-pr",
        help="Merge a PR using squash merge (simple)",
    )
    merge_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number to merge",
    )

    # squash-rebase command
    squash_rebase_parser = subparsers.add_parser(
        "squash-rebase",
        help="Squash all commits and rebase onto base branch",
    )
    squash_rebase_parser.add_argument(
        "--worktree",
        type=Path,
        required=True,
        help="Path to the git worktree",
    )
    squash_rebase_parser.add_argument(
        "--base-branch",
        required=True,
        help="Target branch to rebase onto",
    )

    # merge command (full workflow)
    merge_workflow_parser = subparsers.add_parser(
        "merge",
        help="Complete merge workflow: merge PR, cleanup, sync, mark done",
    )
    merge_workflow_parser.add_argument(
        "--ticket",
        required=True,
        help="Linear ticket ID (e.g., NES-123)",
    )
    merge_workflow_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number to merge",
    )
    merge_workflow_parser.add_argument(
        "--worktree",
        type=Path,
        required=True,
        help="Path to the git worktree",
    )
    merge_workflow_parser.add_argument(
        "--branch",
        required=True,
        help="Branch name to delete",
    )
    merge_workflow_parser.add_argument(
        "--base-branch",
        required=True,
        help="Target branch to sync",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the GitHub client."""
    args = parse_args(argv)

    if args.command == "fetch-threads":
        return fetch_threads_command(args.pr, args.output_dir)
    if args.command == "commit-push":
        return commit_push_command(args.worktree, args.message)
    if args.command == "post-reply":
        return post_reply_command(args.pr, args.thread_file, args.body)
    if args.command == "resolve-thread":
        return resolve_thread_command(args.thread_file)
    if args.command == "deferred-comment":
        return deferred_comment_command(args.thread_file, args.body)
    if args.command == "import-local-tasks":
        return import_local_tasks_command(args.output_dir, args.body_files)
    if args.command == "post-deferred-replies":
        return post_deferred_replies_command(args.pr, args.threads_dir)
    if args.command == "request-review":
        return request_review_command(args.pr)
    if args.command == "open-pr":
        return open_pr_command(args.worktree, args.title, args.body, args.branch)
    if args.command == "get-pr":
        return get_pr_command(args.ticket_id)
    if args.command == "get-changed-files":
        return get_changed_files_command(args.pr)
    if args.command == "set-ticket-done":
        return set_ticket_done_command(args.ticket)
    if args.command == "merge-pr":
        return merge_pr_command(args.pr)
    if args.command == "squash-rebase":
        return squash_rebase_command(args.worktree, args.base_branch)
    if args.command == "merge":
        return merge_workflow_command(
            args.ticket,
            args.pr,
            args.worktree,
            args.branch,
            args.base_branch,
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
