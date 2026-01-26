"""Setup PR review workspace with folder structure and session state."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.pr import git_dao, github_dao

from .fetch_threads_command import fetch_threads_command
from .import_local_tasks_command import import_local_tasks_command
from .parse_review_tasks_command import parse_review_tasks_command
from .setup_worktree_command import setup_worktree_command


def _is_review_format(file_path: Path) -> bool:
    """Check if a file is in review.txt format (vs plain local tasks)."""
    try:
        content = file_path.read_text(encoding="utf-8")
        first_line = content.strip().split("\n")[0] if content.strip() else ""
        # Review format starts with [CLEAN], [OPEN], or [RESOLVED]
        return first_line in ("[CLEAN]", "[OPEN]", "[RESOLVED]")
    except OSError:
        return False


def _get_branch_in_dir(directory: Path) -> str | None:
    """Get the current branch name in a directory."""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        cwd=directory,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def setup_review_command(
    ticket: str | None = None,
    worktree: Path | None = None,
    tasks_file: Path | None = None,
    local_tasks: list[str] | None = None,
) -> int:
    """Setup PR review workspace with folder structure and session state.

    Creates the workspace folder structure, imports local tasks, fetches PR
    threads (in worktree mode), and writes the session state file.

    Args:
        ticket: Linear ticket ID (e.g., "NES-123"). Triggers worktree mode.
        worktree: Path to existing worktree. Triggers worktree mode without ticket.
        tasks_file: Path to file containing tasks separated by ---.
        local_tasks: List of local task strings.

    Returns:
        Exit code (0 for success).
    """
    # Determine mode
    if ticket is not None or worktree is not None:
        mode = "worktree"
    else:
        mode = "local"

    # Setup working directory based on mode
    working_dir: Path
    pr_number: int | None = None
    base_branch: str | None = None
    branch_name: str | None = None

    if ticket is not None:
        # Worktree mode with ticket: setup worktree and get PR info
        result = setup_worktree_command(ticket)
        if result != 0:
            print(f"Error: Failed to setup worktree for ticket {ticket}", file=sys.stderr)
            return 1

        # Get PR info for the ticket
        # Re-fetch the info since setup_worktree_command printed JSON to stdout
        from scripts.clients.linear_client import _get_default_client

        info = _get_default_client().get_ticket_info(ticket)
        linear_branch_name = info.get("branch_name")

        # Find the actual branch (may have counter suffix)
        from .util import _find_existing_branch_for_ticket, _get_expected_branch_name

        branch_name = _find_existing_branch_for_ticket(linear_branch_name)
        if not branch_name:
            branch_name = _get_expected_branch_name(linear_branch_name)

        worktree_path = Path(".worktrees") / branch_name
        working_dir = worktree_path.resolve()

        # Get PR info from GitHub
        pr_data = github_dao.get_pr_for_branch(branch_name)
        if pr_data:
            pr_number = pr_data.get("pr_number")
            base_branch = pr_data.get("base_branch")

    elif worktree is not None:
        # Worktree mode without ticket: use provided worktree path
        working_dir = worktree.resolve()
        if not working_dir.is_dir():
            print(f"Error: Worktree path does not exist: {working_dir}", file=sys.stderr)
            return 1

        # Get branch name from the worktree
        branch_name = _get_branch_in_dir(working_dir)
        if branch_name:
            pr_data = github_dao.get_pr_for_branch(branch_name)
            if pr_data:
                pr_number = pr_data.get("pr_number")
                base_branch = pr_data.get("base_branch")

    else:
        # Local mode: use current directory
        working_dir = Path.cwd()
        branch_name = git_dao.get_current_branch()
        base_branch = branch_name

    # Record initial commit
    initial_commit = git_dao.get_head_sha(working_dir)
    if not initial_commit:
        print("Error: Could not determine current commit", file=sys.stderr)
        return 1

    # Initialize folder structure
    tmp_folder = working_dir / ".tmp" / "pr-review"

    # Clean and recreate
    if tmp_folder.exists():
        shutil.rmtree(tmp_folder)

    state_folder = tmp_folder / "state"
    tasks_folder = tmp_folder / "tasks"
    review_folder = tmp_folder / "review"

    state_folder.mkdir(parents=True, exist_ok=True)
    tasks_folder.mkdir(parents=True, exist_ok=True)
    review_folder.mkdir(parents=True, exist_ok=True)

    # Import tasks
    local_tasks_imported = False
    if tasks_file is not None:
        # Detect format and use appropriate parser
        if _is_review_format(tasks_file):
            result = parse_review_tasks_command(tasks_file, tasks_folder)
        else:
            result = import_local_tasks_command(tasks_folder, from_file=tasks_file)
        if result == 0:
            local_tasks_imported = True
    elif local_tasks:
        # Write tasks to a temp file and import
        temp_tasks_file = tmp_folder / "local_tasks_raw.txt"
        temp_tasks_file.write_text("\n---\n".join(local_tasks), encoding="utf-8")
        result = import_local_tasks_command(tasks_folder, from_file=temp_tasks_file)
        if result == 0:
            local_tasks_imported = True
        temp_tasks_file.unlink(missing_ok=True)

    # Fetch PR threads (worktree mode only)
    if mode == "worktree" and pr_number is not None:
        fetch_threads_command(pr_number, tasks_folder)

    # Write session state
    session_state: dict[str, Any] = {
        "mode": mode,
        "working_dir": str(working_dir),
        "tmp_folder": str(tmp_folder),
        "initial_commit": initial_commit,
        "commits_made": 0,
        "all_modified_files": [],
        "cycle_summaries": [],
        "loop_start_time": datetime.now(UTC).isoformat(),
        "pr_number": pr_number,
        "base_branch": base_branch,
        "branch_name": branch_name,
        "local_tasks_imported": local_tasks_imported,
        "local_task_responses": [],
        "run_status": "clean",
    }

    state_file = state_folder / "session.json"
    state_file.write_text(json.dumps(session_state, indent=2), encoding="utf-8")

    # Output result
    result_data = {
        "status": "ready",
        "state_file": str(state_file),
        "mode": mode,
        "working_dir": str(working_dir),
    }

    print(json.dumps(result_data, indent=2))
    return 0
