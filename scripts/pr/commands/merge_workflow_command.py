"""Complete merge workflow: merge PR, cleanup, fetch, mark done."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from scripts.clients.linear_client import LinearClientError, _get_default_client
from scripts.pr import git_dao, github_dao

from .util import _get_open_prs_for_ticket


def merge_workflow_command(
    ticket_id: str | None,
    pr_number: int,
    working_dir: Path,
    branch_name: str,
    base_branch: str,
    *,
    is_worktree: bool = True,
) -> int:
    """Complete merge workflow: merge PR, cleanup, fetch, mark done.

    Args:
        ticket_id: Linear ticket ID (e.g., "NES-123"), or None to skip ticket operations.
        pr_number: PR number to merge.
        working_dir: Path to the working directory (worktree or repo root).
        branch_name: Name of the branch to delete.
        base_branch: Target branch (used for ticket operations, not checkout).
        is_worktree: If True, remove worktree and delete branch. If False, skip cleanup.

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

    # Step 2: Remove worktree (only if working in a worktree)
    if is_worktree:
        print(f"Step 2: Removing worktree {working_dir}...")
        if working_dir.is_dir():
            success, err = git_dao.remove_worktree(working_dir)
            if not success:
                errors.append(f"Failed to remove worktree: {err}")
                print(f"Warning: {errors[-1]}", file=sys.stderr)
            else:
                print("Worktree removed successfully")
        else:
            print(f"Worktree not found at {working_dir}, skipping removal")

        # Step 3: Delete local branch (only if working in a worktree)
        print(f"Step 3: Deleting local branch {branch_name}...")
        success, err = git_dao.delete_branch(branch_name)
        if not success:
            errors.append(f"Failed to delete branch: {err}")
            print(f"Warning: {errors[-1]}", file=sys.stderr)
        else:
            print("Local branch deleted successfully")
    else:
        print("Step 2: Skipping worktree removal (working on current branch)")
        print("Step 3: Skipping branch deletion (working on current branch)")

    # Step 4: Fetch and prune remote tracking branches
    print("Step 4: Fetching and pruning remote branches...")
    git_dao.fetch_all_prune()
    print("Remote branches updated")

    # Step 5: Check for remaining open PRs and conditionally mark done
    # Skip if no ticket_id provided
    if not ticket_id:
        print("Step 5: Skipping ticket operations (no ticket ID provided)")
    else:
        print(f"Step 5: Checking for remaining open PRs for {ticket_id}...")
        remaining_prs: list[dict[str, Any]] = []
        try:
            remaining_prs = _get_open_prs_for_ticket(ticket_id, exclude_pr=pr_number)
        except LinearClientError as e:
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
                client = _get_default_client()
                info = client.get_ticket_info(ticket_id)
                team_id = info.get("team_id")
                if team_id:
                    done_state_id = client.get_done_state_id(team_id)
                    issue_uuid = info.get("id")
                    if issue_uuid:
                        client.set_ticket_state(issue_uuid, done_state_id)
                        print(f"Marked {ticket_id} as Done")
                    else:
                        errors.append(f"Could not get issue UUID for {ticket_id}")
                        print(f"Warning: {errors[-1]}", file=sys.stderr)
                else:
                    errors.append(f"Could not get team ID for {ticket_id}")
                    print(f"Warning: {errors[-1]}", file=sys.stderr)
            except LinearClientError as e:
                errors.append(f"Linear API error: {e}")
                print(f"Warning: {errors[-1]}", file=sys.stderr)

    # Summary
    print("\n" + "=" * 60)
    print("MERGE WORKFLOW COMPLETE")
    print("=" * 60)
    print(f"Ticket: {ticket_id or 'N/A'}")
    print(f"PR: #{pr_number}")
    print(f"Branch: {branch_name}")
    print(f"Target: {base_branch}")
    if errors:
        print(f"\nWarnings ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")
    print("=" * 60)

    return 0
