"""PR command implementations.

High-level command functions that orchestrate DAO operations.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.pr import git_dao, github_dao, linear_dao

# Maximum length for branch names (git has limits, and long names are unwieldy)
MAX_BRANCH_LENGTH = 60


def _sanitize_title_for_branch(title: str) -> str:
    """Sanitize a ticket title for use in a git branch name.

    Args:
        title: The ticket title to sanitize.

    Returns:
        A sanitized string suitable for branch names.
    """
    # Convert to lowercase
    sanitized = title.lower()

    # Replace spaces and underscores with hyphens
    sanitized = re.sub(r"[\s_]+", "-", sanitized)

    # Remove any characters that aren't alphanumeric or hyphens
    sanitized = re.sub(r"[^a-z0-9-]", "", sanitized)

    # Collapse multiple hyphens into one
    sanitized = re.sub(r"-+", "-", sanitized)

    # Remove leading/trailing hyphens
    sanitized = sanitized.strip("-")

    return sanitized


def _generate_branch_name(ticket_id: str, title: str, max_length: int) -> str:
    """Generate a branch name from ticket ID and title.

    Args:
        ticket_id: The ticket identifier (e.g., "NES-87").
        title: The ticket title.
        max_length: Maximum length for the branch name.

    Returns:
        A branch name in the format "<TICKET-ID>-<sanitized-title>".
    """
    sanitized_title = _sanitize_title_for_branch(title)

    # Start with ticket ID (preserving case)
    branch_name = ticket_id

    # Calculate remaining space for the title (minus 1 for the hyphen)
    remaining_space = max_length - len(ticket_id) - 1

    if remaining_space > 0 and sanitized_title:
        # Truncate title if needed, but try to end on a word boundary
        if len(sanitized_title) > remaining_space:
            # Find the last hyphen within the limit
            truncated = sanitized_title[:remaining_space]
            last_hyphen = truncated.rfind("-")
            if last_hyphen > 0:
                truncated = truncated[:last_hyphen]
            sanitized_title = truncated.rstrip("-")

        branch_name = f"{ticket_id}-{sanitized_title}".rstrip("-")

    return branch_name


def _find_available_branch_name(base_name: str) -> str:
    """Find an available branch name, adding a counter if needed.

    Args:
        base_name: The base branch name to start with.

    Returns:
        An available branch name (base_name, base_name-2, base_name-3, etc.).
    """
    if not git_dao.branch_exists(base_name):
        return base_name

    # Try with counter starting at 2
    counter = 2
    while True:
        candidate = f"{base_name}-{counter}"
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
    attachments = linear_dao.fetch_github_attachments(ticket_id)

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

    threads = github_dao.fetch_unresolved_threads(pr_number)
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
            success = github_dao.resolve_thread(thread_id)
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
    status = git_dao.get_status(worktree)
    if not status:
        print("No changes to commit")
        return 0

    # Stage all changes
    git_dao.stage_all(worktree)

    # Commit
    git_dao.commit(worktree, message)

    # Push
    git_dao.push(worktree)

    print(f"Successfully committed and pushed: {message}")
    return 0


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

    github_dao.post_reply_to_comment(pr_number, comment_id, body)
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

    success = github_dao.resolve_thread(thread_id)
    if success:
        print(f"Resolved thread: {thread_id}")
        return 0
    print(f"Failed to resolve thread: {thread_id}", file=sys.stderr)
    return 1


def deferred_comment_command(thread_file: Path, body: str) -> int:
    """Store a deferred reply in a thread file for later posting.

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

    Args:
        pr_number: PR number to post replies on.
        threads_dir: Directory containing thread JSON files with deferred replies.

    Returns:
        Exit code (0 for success).
    """
    if not threads_dir.is_dir():
        print(f"Threads directory not found: {threads_dir}", file=sys.stderr)
        return 1

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

            github_dao.post_reply_to_comment(pr_number, comment_id, deferred_reply)
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
    github_dao.post_pr_comment(pr_number, "@coderabbitai review")
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

    success, result = github_dao.create_pr(str(worktree), title, body, branch)
    if not success:
        print(f"Error creating PR: {result}", file=sys.stderr)
        return 1

    print(result)
    return 0


def get_pr_command(ticket_id: str) -> int:
    """Get PR info for a Linear ticket: branch name, PR number, PR URL, base branch.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123").

    Returns:
        Exit code (0 for success).
    """
    try:
        info = linear_dao.get_ticket_info(ticket_id)

        # Fetch GitHub attachments to find PR
        attachments = linear_dao.fetch_github_attachments(ticket_id)

        # Collect all PR candidates from attachments
        pr_url = None
        pr_number = None
        pr_candidates: list[tuple[str, int]] = []
        for attachment in attachments:
            url = attachment.get("url", "")
            if "/pull/" in url:
                match = re.search(r"/pull/(\d+)", url)
                if match:
                    pr_candidates.append((url, int(match.group(1))))

        # Find the first open PR by checking state via GitHub API
        for url, number in pr_candidates:
            try:
                gh_pr_info = github_dao.get_pr_info(number)
                if gh_pr_info.get("state") == "OPEN":
                    pr_url = url
                    pr_number = number
                    break
            except github_dao.GraphQLError:
                continue

        branch_name = info.get("branch_name")
        pr_info: dict[str, Any] = {
            "branch_name": branch_name,
            "worktree_path": f".worktrees/{branch_name}" if branch_name else None,
            "pr_number": pr_number,
            "pr_url": pr_url,
            "base_branch": None,
        }

        # If we have a PR number, fetch the base branch from GitHub
        if pr_number:
            gh_pr_info = github_dao.get_pr_info(pr_number)
            pr_info["base_branch"] = gh_pr_info.get("base_branch")

        print(json.dumps(pr_info, indent=2))
        return 0
    except linear_dao.LinearAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except github_dao.GraphQLError as e:
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
        files = github_dao.get_pr_changed_files(pr_number)
        print(json.dumps(files, indent=2))
        return 0
    except github_dao.GraphQLError as e:
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
        info = linear_dao.get_ticket_info(ticket_id)
        team_id = info.get("team_id")
        if not team_id:
            print(f"Error: Could not get team ID for {ticket_id}", file=sys.stderr)
            return 1

        done_state_id = linear_dao.get_done_state_id(team_id)
        issue_uuid = info.get("id")
        if not issue_uuid:
            print(f"Error: Could not get issue UUID for {ticket_id}", file=sys.stderr)
            return 1
        success = linear_dao.set_ticket_state(issue_uuid, done_state_id)

        if success:
            print(f"Marked {ticket_id} as Done")
            return 0
        print(f"Failed to mark {ticket_id} as Done", file=sys.stderr)
        return 1
    except linear_dao.LinearAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def merge_pr_command(pr_number: int) -> int:
    """Merge a PR using squash merge.

    Args:
        pr_number: PR number to merge.

    Returns:
        Exit code (0 for success).
    """
    success = github_dao.merge_pr(pr_number, squash=True, auto=True)
    if not success:
        print(f"Error merging PR #{pr_number}", file=sys.stderr)
        return 1

    print(f"Merged PR #{pr_number}")
    return 0


def squash_rebase_command(worktree: Path, base_branch: str) -> int:
    """Squash all commits and rebase onto base branch.

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
    success, err = git_dao.fetch_branch(worktree, base_branch)
    if not success:
        print(f"Error fetching branch: {err}", file=sys.stderr)
        return 1

    # Count commits ahead of target branch
    commit_count, err = git_dao.count_commits_ahead(worktree, base_branch)
    if commit_count < 0:
        print(f"Error counting commits: {err}", file=sys.stderr)
        return 1

    print(f"Found {commit_count} commit(s) ahead of origin/{base_branch}")

    # If more than 1 commit, squash them using soft reset and recommit
    if commit_count > 1:
        print(f"Squashing {commit_count} commits...")

        # Get the merge base
        merge_base, err = git_dao.get_merge_base(worktree, base_branch)
        if not merge_base:
            print(f"Error finding merge base: {err}", file=sys.stderr)
            return 1

        # Get the current commit message for the squashed commit
        commit_msg = git_dao.get_last_commit_message(worktree)

        # Soft reset to merge base, keeping changes staged
        success, err = git_dao.soft_reset(worktree, merge_base)
        if not success:
            print(f"Error during soft reset: {err}", file=sys.stderr)
            return 1

        # Recommit with the original message
        success = git_dao.commit(worktree, commit_msg)
        if not success:
            print("Error creating squashed commit", file=sys.stderr)
            return 1

        print("Commits squashed successfully")

    # Rebase onto target branch
    print(f"Rebasing onto origin/{base_branch}...")
    success, has_conflicts, err = git_dao.rebase(worktree, base_branch)

    if not success:
        if has_conflicts:
            print("Rebase conflicts detected. Resolve conflicts and continue.")
            print("After resolving: git add <files> && git rebase --continue")
            return 1
        print(f"Error during rebase: {err}", file=sys.stderr)
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
    success = github_dao.merge_pr(pr_number, squash=True, auto=False)
    if not success:
        print("Error merging PR", file=sys.stderr)
        return 1
    print(f"PR #{pr_number} merged successfully")

    # Step 2: Remove worktree
    print(f"Step 2: Removing worktree {worktree}...")
    if worktree.is_dir():
        success, err = git_dao.remove_worktree(worktree)
        if not success:
            errors.append(f"Failed to remove worktree: {err}")
            print(f"Warning: {errors[-1]}", file=sys.stderr)
        else:
            print("Worktree removed successfully")
    else:
        print(f"Worktree not found at {worktree}, skipping removal")

    # Step 3: Delete local branch
    print(f"Step 3: Deleting local branch {branch_name}...")
    success, err = git_dao.delete_branch(branch_name)
    if not success:
        errors.append(f"Failed to delete branch: {err}")
        print(f"Warning: {errors[-1]}", file=sys.stderr)
    else:
        print("Local branch deleted successfully")

    # Step 4: Sync target branch
    print(f"Step 4: Syncing {base_branch}...")

    # Fetch all and prune
    git_dao.fetch_all_prune()

    # Stash any local changes
    had_stash = git_dao.stash()

    # Checkout target branch
    success, err = git_dao.checkout(base_branch)
    if not success:
        errors.append(f"Failed to checkout {base_branch}: {err}")
        print(f"Warning: {errors[-1]}", file=sys.stderr)
    else:
        # Pull latest
        success, err = git_dao.pull()
        if not success:
            errors.append(f"Failed to pull: {err}")
            print(f"Warning: {errors[-1]}", file=sys.stderr)
        else:
            print(f"Synced {base_branch} successfully")

    # Pop stash if we had one
    if had_stash:
        success, err = git_dao.stash_pop()
        if not success:
            errors.append(f"Stash pop had conflicts: {err}")
            print(f"Warning: {errors[-1]} - manual resolution required", file=sys.stderr)

    # Step 5: Check for remaining open PRs and conditionally mark done
    print(f"Step 5: Checking for remaining open PRs for {ticket_id}...")
    remaining_prs: list[dict[str, Any]] = []
    try:
        remaining_prs = _get_open_prs_for_ticket(ticket_id, exclude_pr=pr_number)
    except linear_dao.LinearAPIError as e:
        errors.append(f"Error checking remaining PRs: {e}")
        print(f"Warning: {errors[-1]}", file=sys.stderr)

    if remaining_prs:
        # Report remaining PRs instead of marking done
        next_pr = remaining_prs[0]
        print(f"Ticket {ticket_id} has {len(remaining_prs)} remaining open PR(s)")
        print(f"Next open PR: #{next_pr['number']} - {next_pr['url']}")
        print("Skipping mark as Done (ticket still has open PRs)")
    else:
        # No remaining PRs, mark as Done
        print(f"No remaining open PRs. Marking {ticket_id} as Done...")
        try:
            info = linear_dao.get_ticket_info(ticket_id)
            team_id = info.get("team_id")
            if team_id:
                done_state_id = linear_dao.get_done_state_id(team_id)
                issue_uuid = info.get("id")
                if issue_uuid:
                    success = linear_dao.set_ticket_state(issue_uuid, done_state_id)
                    if success:
                        print(f"Marked {ticket_id} as Done")
                    else:
                        errors.append(f"Failed to mark {ticket_id} as Done")
                        print(f"Warning: {errors[-1]}", file=sys.stderr)
                else:
                    errors.append(f"Could not get issue UUID for {ticket_id}")
                    print(f"Warning: {errors[-1]}", file=sys.stderr)
            else:
                errors.append(f"Could not get team ID for {ticket_id}")
                print(f"Warning: {errors[-1]}", file=sys.stderr)
        except linear_dao.LinearAPIError as e:
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


def generate_branch_command(ticket_id: str) -> int:
    """Generate a branch name for a Linear ticket.

    Creates a branch name from the ticket ID and title. If the branch already
    exists (locally or on remote), appends a counter (-2, -3, etc.).

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-87").

    Returns:
        Exit code (0 for success).
    """
    try:
        info = linear_dao.get_ticket_info(ticket_id)
        identifier = info.get("identifier") or ticket_id
        title = info.get("title", "")

        if not title:
            print(f"Error: No title found for ticket {ticket_id}", file=sys.stderr)
            return 1

        # Generate base branch name
        base_branch_name = _generate_branch_name(identifier, title, MAX_BRANCH_LENGTH)

        # Find available branch name (adds counter if needed)
        branch_name = _find_available_branch_name(base_branch_name)

        # Output just the branch name (for easy capture by scripts)
        print(branch_name)
        return 0
    except linear_dao.LinearAPIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
