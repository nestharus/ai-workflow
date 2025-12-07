"""GitHub PR operations client for fetching, formatting, and managing review threads.

Usage:
    uv run github.fetch-threads --pr <number> --output-dir <path>
    uv run github.commit-push --worktree <path> --message <msg>
    uv run github.post-reply --pr <number> --comment-id <id> --body <text>
    uv run github.resolve-thread --thread-id <id>
    uv run github.request-review --pr <number>
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_OWNER = "nestharus"
REPO_NAME = "ai-workflow"


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
        True if the thread has a line number.
    """
    return thread.get("line") is not None


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
    if args.command == "request-review":
        return request_review_command(args.pr)
    if args.command == "open-pr":
        return open_pr_command(args.worktree, args.title, args.body, args.branch)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
