"""GitHub API data access operations.

Provides low-level functions for interacting with the GitHub GraphQL and REST APIs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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


def run_gh_command(args: list[str]) -> str:
    """Run a gh command and return stdout.

    Args:
        args: Command arguments to pass to gh.

    Returns:
        Command stdout.

    Raises:
        GraphQLError: If command fails.
    """
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


def run_graphql_query(query: str) -> dict[str, Any]:
    """Run a GraphQL query via gh api.

    Args:
        query: GraphQL query string.

    Returns:
        Parsed JSON response.
    """
    output = run_gh_command(["api", "graphql", "-f", f"query={query}"])
    try:
        result: dict[str, Any] = json.loads(output)
    except json.JSONDecodeError as e:
        raise GraphQLError(f"Invalid JSON from gh: {e}") from e
    return result


def run_graphql_mutation(mutation: str) -> dict[str, Any]:
    """Run a GraphQL mutation via gh api.

    Args:
        mutation: GraphQL mutation string.

    Returns:
        Parsed JSON response.
    """
    output = run_gh_command(["api", "graphql", "-f", f"query={mutation}"])
    try:
        result: dict[str, Any] = json.loads(output)
    except json.JSONDecodeError as e:
        raise GraphQLError(f"Invalid JSON from gh: {e}") from e
    return result


def fetch_thread_comments(thread_id: str) -> list[dict[str, Any]]:
    """Fetch all comments for a thread with pagination.

    Args:
        thread_id: GraphQL ID of the review thread.

    Returns:
        List of comment dictionaries.
    """
    all_comments: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        after_clause = f', after: "{cursor}"' if cursor else ""
        query = f"""
{{
  node(id: "{thread_id}") {{
    ... on PullRequestReviewThread {{
      comments(first: 100{after_clause}) {{
        pageInfo {{
          hasNextPage
          endCursor
        }}
        nodes {{
          id
          databaseId
          body
          author {{ login }}
          createdAt
        }}
      }}
    }}
  }}
}}
"""
        result = run_graphql_query(query)
        node = result.get("data", {}).get("node", {})
        if not node:
            break

        comments = node.get("comments", {})
        nodes = comments.get("nodes", [])
        all_comments.extend(nodes)

        page_info = comments.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return all_comments


def fetch_comment_thumbs_up_reactions(comment_id: str) -> list[dict[str, Any]]:
    """Fetch all THUMBS_UP reactions for a comment with pagination.

    Args:
        comment_id: GraphQL ID of the comment.

    Returns:
        List of reaction dictionaries with user info.
    """
    all_reactions: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        after_clause = f', after: "{cursor}"' if cursor else ""
        query = f"""
{{
  node(id: "{comment_id}") {{
    ... on PullRequestReviewComment {{
      reactions(first: 100, content: THUMBS_UP{after_clause}) {{
        pageInfo {{
          hasNextPage
          endCursor
        }}
        nodes {{
          content
          user {{ login }}
        }}
      }}
    }}
  }}
}}
"""
        result = run_graphql_query(query)
        node = result.get("data", {}).get("node", {})
        if not node:
            break

        reactions = node.get("reactions", {})
        nodes = reactions.get("nodes", [])
        all_reactions.extend(nodes)

        page_info = reactions.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return all_reactions


def fetch_unresolved_threads(pr_number: int) -> list[dict[str, Any]]:
    """Fetch unresolved review threads from a PR.

    Args:
        pr_number: The PR number to fetch threads from.

    Returns:
        List of unresolved thread dictionaries with all comments and reactions.
    """
    all_threads: list[dict[str, Any]] = []
    cursor: str | None = None

    # First pass: fetch all threads with basic info
    while True:
        after_clause = f', after: "{cursor}"' if cursor else ""
        query = f"""
{{
  repository(owner: "{REPO_OWNER}", name: "{REPO_NAME}") {{
    pullRequest(number: {pr_number}) {{
      reviewThreads(first: 100{after_clause}) {{
        pageInfo {{
          hasNextPage
          endCursor
        }}
        nodes {{
          id
          isResolved
          path
          line
          startLine
          originalLine
          originalStartLine
        }}
      }}
    }}
  }}
}}
"""
        result = run_graphql_query(query)

        pr_data = result.get("data", {}).get("repository", {}).get("pullRequest", {})
        if not pr_data:
            break

        review_threads = pr_data.get("reviewThreads", {})
        nodes = review_threads.get("nodes", [])
        all_threads.extend(nodes)

        page_info = review_threads.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    # Filter to unresolved threads
    unresolved = [t for t in all_threads if not t.get("isResolved", True)]

    # Second pass: fetch all comments and reactions for unresolved threads
    for thread in unresolved:
        thread_id = thread.get("id")
        if not thread_id:
            continue

        # Fetch all comments with pagination
        comments = fetch_thread_comments(thread_id)

        # Fetch THUMBS_UP reactions for each comment
        for comment in comments:
            comment_id = comment.get("id")
            if comment_id:
                reactions = fetch_comment_thumbs_up_reactions(comment_id)
                comment["reactions"] = {"nodes": reactions}

        thread["comments"] = {"nodes": comments}

    return unresolved


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
    result = run_graphql_mutation(mutation)
    thread = result.get("data", {}).get("resolveReviewThread", {}).get("thread", {})
    is_resolved = thread.get("isResolved", False)
    return bool(is_resolved)


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
    result = run_graphql_query(query)
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
    output = run_gh_command(
        ["api", f"repos/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_number}/files", "--paginate"]
    )
    try:
        files_data = json.loads(output)
    except json.JSONDecodeError as e:
        raise GraphQLError(f"Invalid JSON from gh: {e}") from e
    return [f.get("filename", "") for f in files_data if f.get("filename")]


def post_pr_comment(pr_number: int, body: str) -> None:
    """Post a comment on a PR.

    Args:
        pr_number: PR number.
        body: Comment body text.
    """
    run_gh_command(["pr", "comment", str(pr_number), "--body", body])


def post_reply_to_comment(pr_number: int, comment_id: int, body: str) -> None:
    """Post a reply to a PR review comment.

    Args:
        pr_number: PR number.
        comment_id: Database ID of the comment to reply to.
        body: Reply body text.
    """
    run_gh_command(
        [
            "api",
            f"repos/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_number}/comments/{comment_id}/replies",
            "-f",
            f"body={body}",
        ]
    )


def merge_pr(pr_number: int, squash: bool = True, auto: bool = False) -> bool:
    """Merge a PR.

    Args:
        pr_number: PR number to merge.
        squash: Use squash merge if True.
        auto: Enable auto-merge if True.

    Returns:
        True if successful.
    """
    args = ["pr", "merge", str(pr_number)]
    if squash:
        args.append("--squash")
    if auto:
        args.append("--auto")

    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def create_pr(worktree_path: str, title: str, body: str, head_branch: str) -> tuple[bool, str]:
    """Create a new PR.

    Args:
        worktree_path: Path to the git worktree.
        title: PR title.
        body: PR body text.
        head_branch: Branch name for the PR head.

    Returns:
        Tuple of (success, output_or_error).
    """
    result = subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--head", head_branch],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, result.stdout.strip()


def get_pr_for_branch(branch_name: str) -> dict[str, Any] | None:
    """Get the first open PR info for a branch using gh CLI.

    Args:
        branch_name: The branch name to find PR for.

    Returns:
        Dictionary with pr_number, pr_url, base_branch, or None if no open PR.
    """
    output = run_gh_command(
        [
            "pr",
            "list",
            "--head",
            branch_name,
            "--state",
            "open",
            "--json",
            "number,url,baseRefName",
            "--limit",
            "1",
        ]
    )

    try:
        prs = json.loads(output)
    except json.JSONDecodeError as e:
        raise GraphQLError(f"Invalid JSON from gh: {e}") from e
    if not prs:
        return None

    pr = prs[0]
    return {
        "pr_number": pr.get("number"),
        "pr_url": pr.get("url"),
        "base_branch": pr.get("baseRefName"),
    }
