"""Orchestrate complete PR review workflow: setup, cycle loop, finalize."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .finalize_review_command import finalize_review_command
from .inner_cycle_command import inner_cycle_command
from .setup_review_command import setup_review_command


def _tasks_exist(tasks_folder: Path) -> bool:
    """Check if any task JSON files exist in the tasks folder."""
    if not tasks_folder.is_dir():
        return False
    return any(tasks_folder.glob("*.json"))


def review_loop_command(
    ticket: str | None = None,
    worktree: Path | None = None,
    tasks_file: Path | None = None,
    local_tasks: list[str] | None = None,
    max_cycles: int = 10,
) -> int:
    """Orchestrate complete PR review workflow.

    Runs setup, executes cycle loop (spawning pr-inner-cycle agent), and finalizes.

    Args:
        ticket: Linear ticket ID (e.g., "NES-123"). Triggers worktree mode.
        worktree: Path to existing worktree. Triggers worktree mode without ticket.
        tasks_file: Path to file containing tasks separated by ---.
        local_tasks: List of local task strings.
        max_cycles: Maximum number of cycles before stopping (default 10).

    Returns:
        Exit code (0 for success).
    """
    # Step 1: Run setup
    print("=== Step 1: Setup ===", file=sys.stderr)
    result = setup_review_command(ticket, worktree, tasks_file, local_tasks)
    if result != 0:
        print("Setup failed", file=sys.stderr)
        return result

    # Parse setup output to get state file path
    # setup_review_command prints JSON to stdout, but we need to capture it
    # Instead, we'll reconstruct the paths based on working directory
    if ticket is not None:
        # Worktree mode with ticket - need to find the worktree path
        from scripts.clients.linear_client import _get_default_client

        from .util import _find_existing_branch_for_ticket, _get_expected_branch_name

        info = _get_default_client().get_ticket_info(ticket)
        linear_branch_name = info.get("branch_name")
        branch_name = _find_existing_branch_for_ticket(linear_branch_name)
        if not branch_name:
            branch_name = _get_expected_branch_name(linear_branch_name)
        working_dir = (Path(".worktrees") / branch_name).resolve()
    elif worktree is not None:
        working_dir = worktree.resolve()
    else:
        working_dir = Path.cwd()

    tmp_folder = working_dir / ".tmp" / "pr-review"
    state_file = tmp_folder / "state" / "session.json"
    tasks_folder = tmp_folder / "tasks"

    if not state_file.is_file():
        print(f"Error: State file not found after setup: {state_file}", file=sys.stderr)
        return 1

    # Step 2: Cycle loop
    print("\n=== Step 2: Cycle Loop ===", file=sys.stderr)
    cycle = 1

    while cycle <= max_cycles and _tasks_exist(tasks_folder):
        print(f"\n--- Cycle {cycle} ---", file=sys.stderr)

        # Run inner cycle
        cycle_result = inner_cycle_command(state_file, cycle)

        if cycle_result.get("status") == "error":
            print(f"Cycle {cycle} failed: {cycle_result.get('error')}", file=sys.stderr)
            # Update state file with error status
            if state_file.is_file():
                state = json.loads(state_file.read_text(encoding="utf-8"))
                state["run_status"] = "error"
                state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
            break

        cycle += 1

    # Check if we hit cycle limit with tasks remaining
    if cycle > max_cycles and _tasks_exist(tasks_folder):
        print(f"Reached max cycles ({max_cycles}) with tasks remaining", file=sys.stderr)
        if state_file.is_file():
            state = json.loads(state_file.read_text(encoding="utf-8"))
            state["run_status"] = "cycle_limit"
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # Step 3: Finalize
    print("\n=== Step 3: Finalize ===", file=sys.stderr)
    return finalize_review_command(state_file)
