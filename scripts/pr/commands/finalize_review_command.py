"""Finalize PR review with lint, squash, push, and cleanup."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.pr import git_dao

from .post_deferred_replies_command import post_deferred_replies_command


def finalize_review_command(state_file: Path) -> int:
    """Finalize PR review with lint, squash, push, and cleanup.

    Reads session state, runs lint-fix on modified files, squashes commits,
    pushes to origin, posts deferred replies, prints summary, and cleans up.

    Args:
        state_file: Path to session state JSON file.

    Returns:
        Exit code (0 for success).
    """
    # Read session state
    if not state_file.is_file():
        print(f"Error: State file not found: {state_file}", file=sys.stderr)
        return 1

    state: dict[str, Any] = json.loads(state_file.read_text(encoding="utf-8"))

    mode = state.get("mode", "local")
    working_dir = Path(state.get("working_dir", "."))
    tmp_folder = Path(state.get("tmp_folder", ".tmp/pr-review"))
    initial_commit = state.get("initial_commit", "")
    commits_made = state.get("commits_made", 0)
    all_modified_files: list[str] = state.get("all_modified_files", [])
    cycle_summaries: list[dict[str, Any]] = state.get("cycle_summaries", [])
    pr_number = state.get("pr_number")
    branch_name = state.get("branch_name")
    run_status = state.get("run_status", "clean")
    local_task_responses: list[dict[str, Any]] = state.get("local_task_responses", [])

    # Result tracking
    pushed = False
    squashed = False
    lint_fixes_applied = False
    deferred_replies_posted = 0
    error_msg: str | None = None

    # Skip lint/squash/push on error status
    if run_status == "error":
        print("Run status is error, skipping to cleanup", file=sys.stderr)
    else:
        # Step 3: Run lint-fix on modified files
        if all_modified_files:
            print(f"Running lint-fix on {len(all_modified_files)} files...", file=sys.stderr)
            lint_result = subprocess.run(
                ["uv", "run", "lint-fix", "--files", *all_modified_files],
                cwd=working_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if lint_result.returncode != 0:
                print(f"Warning: lint-fix failed: {lint_result.stderr}", file=sys.stderr)
            else:
                # Check for changes and commit lint fixes
                status_output, _ = git_dao.get_status(working_dir)
                if status_output.strip():
                    git_dao.stage_all(working_dir)
                    if git_dao.commit(working_dir, "Lint fixes"):
                        commits_made += 1
                        lint_fixes_applied = True
                        print("Committed lint fixes", file=sys.stderr)

        # Step 4: Squash commits if multiple
        if commits_made > 1 and initial_commit:
            print(f"Squashing {commits_made} commits...", file=sys.stderr)
            success, err = git_dao.soft_reset(working_dir, initial_commit)
            if success:
                total_tasks = sum(c.get("tasks_processed", 0) for c in cycle_summaries)
                cycles = len(cycle_summaries)
                message = f"PR review: applied {total_tasks} tasks across {cycles} cycles"

                # Add file list to commit message
                if all_modified_files:
                    message += "\n\nFiles modified:\n"
                    for f in sorted(set(all_modified_files)):
                        message += f"- {f}\n"

                if git_dao.commit(working_dir, message):
                    squashed = True
                    print("Squashed commits", file=sys.stderr)
                else:
                    print("Warning: Failed to create squash commit", file=sys.stderr)
            else:
                print(f"Warning: Failed to soft reset: {err}", file=sys.stderr)

        # Step 5: Push to origin
        print("Pushing to origin...", file=sys.stderr)
        success, err = git_dao.push(working_dir)
        if success:
            pushed = True
            print("Pushed to origin", file=sys.stderr)
        else:
            # Try with upstream
            print("Retrying with upstream set...", file=sys.stderr)
            success, err = git_dao.push(working_dir, set_upstream=True)
            if success:
                pushed = True
                print("Pushed to origin (with upstream)", file=sys.stderr)
            else:
                print(f"Warning: Push failed: {err}", file=sys.stderr)

        # Step 6: Post deferred replies (worktree mode only)
        if mode == "worktree" and pr_number is not None:
            tasks_folder = tmp_folder / "tasks"
            if tasks_folder.is_dir():
                print(f"Posting deferred replies to PR #{pr_number}...", file=sys.stderr)
                result = post_deferred_replies_command(pr_number, tasks_folder)
                if result == 0:
                    # Count how many were posted (rough estimate from files)
                    deferred_files = list(tasks_folder.glob("thread_*.json"))
                    deferred_replies_posted = len(deferred_files)

    # Step 7: Output summary
    print("\n=== PR Review Complete ===\n")
    print(f"Mode: {mode}")
    if branch_name:
        print(f"Branch: {branch_name}")
    if mode == "worktree" and pr_number:
        print(f"PR: #{pr_number}")
    print()
    print(f"Cycles completed: {len(cycle_summaries)}")
    print(f"Exit reason: {run_status}")
    print()

    if all_modified_files:
        print(f"Files modified ({len(set(all_modified_files))}):")
        for f in sorted(set(all_modified_files)):
            print(f"  - {f}")
        print()

    if cycle_summaries:
        print("Changes summary:")
        for summary in cycle_summaries:
            cycle = summary.get("cycle", "?")
            tasks = summary.get("tasks_processed", 0)
            files = summary.get("files_modified", 0)
            print(f"  Cycle {cycle}: {tasks} tasks, {files} files")
        print()

    if local_task_responses:
        print("Local task responses:")
        for response in local_task_responses:
            task_id = response.get("task_id", "?")
            reply = response.get("reply", "")
            # Truncate long replies
            if len(reply) > 60:
                reply = reply[:57] + "..."
            print(f"  - {task_id}: {reply}")
        print()

    # Step 8: Cleanup
    if tmp_folder.is_dir():
        try:
            shutil.rmtree(tmp_folder)
            print(f"Cleaned up {tmp_folder}", file=sys.stderr)
        except OSError as e:
            print(f"Warning: Failed to cleanup: {e}", file=sys.stderr)

    # Output JSON result
    result_data = {
        "status": "success" if not error_msg else "error",
        "pushed": pushed,
        "squashed": squashed,
        "lint_fixes_applied": lint_fixes_applied,
        "deferred_replies_posted": deferred_replies_posted,
        "error": error_msg,
    }
    print(json.dumps(result_data, indent=2))

    return 0
