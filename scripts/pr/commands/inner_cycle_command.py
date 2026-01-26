"""Execute one review-fix-test cycle within the PR Review workflow."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run_command(cmd: list[str], cwd: Path) -> tuple[bool, str, str]:
    """Run a command and return (success, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0, result.stdout, result.stderr


def _aggregate_tasks(working_dir: Path, tasks_folder: Path) -> dict[str, Any] | None:
    """Aggregate task files into a manifest."""
    success, stdout, stderr = _run_command(
        ["uv", "run", "pr", "aggregate-tasks", "--input-dir", str(tasks_folder)],
        working_dir,
    )
    if not success:
        print(f"Error aggregating tasks: {stderr}", file=sys.stderr)
        return None

    # Parse aggregated output
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        print(f"Error parsing aggregated tasks: {stdout}", file=sys.stderr)
        return None


def _build_file_handler_context(
    file_path: str,
    task_files: list[str],
    tasks_folder: Path,
) -> dict[str, Any]:
    """Build context JSON for pr-file-handler from task files."""
    tasks = []
    for task_file in task_files:
        task_path = tasks_folder / task_file
        if task_path.is_file():
            try:
                task_data = json.loads(task_path.read_text(encoding="utf-8"))
                # Map task file format to handler format
                task_id = task_file.replace(".json", "")
                task_type = "coderabbit" if task_file.startswith("coderabbit_") else "pr_comment"
                tasks.append(
                    {
                        "id": task_id,
                        "type": task_type,
                        "content": task_data.get("content", task_data.get("description", "")),
                        "line": task_data.get("line", task_data.get("line_start")),
                    }
                )
            except (json.JSONDecodeError, OSError):
                continue

    return {
        "file_path": file_path,
        "tasks": tasks,
    }


def _spawn_file_handlers(
    working_dir: Path,
    tasks_by_file: dict[str, list[str]],
    tasks_folder: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Spawn pr-file-handler agents in parallel and collect results.

    Returns (modified_files, local_task_responses).
    """
    modified_files: list[str] = []
    local_task_responses: list[dict[str, Any]] = []

    # Spawn handlers for file-specific tasks (in parallel)
    processes: list[tuple[str, subprocess.Popen[str]]] = []

    for file_path, task_files in tasks_by_file.items():
        if file_path == "__global__":
            continue

        context = _build_file_handler_context(file_path, task_files, tasks_folder)
        context_json = json.dumps(context)

        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "scripts.agents", "pr-file-handler", context_json],
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append((file_path, proc))

    # Collect results from parallel handlers
    for file_path, proc in processes:
        stdout, stderr = proc.communicate()
        if proc.returncode == 0:
            try:
                result = json.loads(stdout)
                if result.get("changes_made"):
                    modified_files.append(file_path)
                if result.get("deferred_reply"):
                    # Check if it's a local task
                    if any(tf.startswith("local_") for tf in tasks_by_file.get(file_path, [])):
                        local_task_responses.append(
                            {
                                "task_id": file_path,
                                "reply": result["deferred_reply"],
                            }
                        )
            except json.JSONDecodeError:
                print(f"Warning: Could not parse handler result for {file_path}", file=sys.stderr)
        else:
            print(f"Warning: Handler failed for {file_path}: {stderr}", file=sys.stderr)

    # Process global tasks sequentially
    global_tasks = tasks_by_file.get("__global__", [])
    for task_file in global_tasks:
        context = _build_file_handler_context("__global__", [task_file], tasks_folder)
        context_json = json.dumps(context)

        success, stdout, stderr = _run_command(
            ["uv", "run", "python", "-m", "scripts.agents", "pr-file-handler", context_json],
            working_dir,
        )
        if success:
            try:
                result = json.loads(stdout)
                if result.get("deferred_reply") and task_file.startswith("local_"):
                    local_task_responses.append(
                        {
                            "task_id": task_file.replace(".json", ""),
                            "reply": result["deferred_reply"],
                        }
                    )
            except json.JSONDecodeError:
                pass
        else:
            print(f"Warning: Global handler failed for {task_file}: {stderr}", file=sys.stderr)

    return modified_files, local_task_responses


def _cleanup_task_files(tasks_folder: Path) -> None:
    """Remove processed task files."""
    patterns = [
        "thread_*.json",
        "local_*.json",
        "coderabbit_*.json",
        "review_*.json",
        "aggregated.json",
    ]
    for pattern in patterns:
        for f in tasks_folder.glob(pattern):
            f.unlink(missing_ok=True)


def _run_tests(working_dir: Path, modified_files: list[str]) -> bool:
    """Run tests for modified Python files. Returns True if all pass."""
    py_files = [f for f in modified_files if f.endswith(".py")]
    if not py_files:
        return True

    # Spawn test-fixer agents in parallel
    processes: list[tuple[str, subprocess.Popen[str]]] = []

    for file_path in py_files:
        # Resolve test file path
        if file_path.startswith("scripts/"):
            # scripts/foo/bar.py -> scripts/tests/unit/foo/test_bar.py
            parts = file_path.split("/")
            if len(parts) >= 2:
                test_file = f"scripts/tests/unit/{'/'.join(parts[1:-1])}/test_{parts[-1]}"
            else:
                continue
        else:
            continue

        context = json.dumps(
            {
                "file_path": file_path,
                "test_file": test_file,
                "working_dir": str(working_dir),
            }
        )

        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "scripts.agents", "pr-test-fixer", context],
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append((file_path, proc))

    # Collect results
    all_passed = True
    for file_path, proc in processes:
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            print(f"Warning: Test fixer failed for {file_path}: {stderr}", file=sys.stderr)
            all_passed = False
        else:
            try:
                result = json.loads(stdout)
                if not result.get("tests_passed", True):
                    all_passed = False
            except json.JSONDecodeError:
                pass

    return all_passed


def _run_lint(working_dir: Path, modified_files: list[str]) -> None:
    """Run lint-fix on modified files."""
    if not modified_files:
        return

    _run_command(
        ["uv", "run", "lint-fix", "--files", *modified_files],
        working_dir,
    )


def _run_coderabbit(
    working_dir: Path,
    review_folder: Path,
    mode: str,
    cycle: int,
) -> None:
    """Run coderabbit review."""
    # Determine review args
    if mode == "worktree" or cycle > 1:
        review_args = ["--base-commit", "HEAD~1"]
    else:
        # Check for uncommitted changes
        success, stdout, _ = _run_command(["git", "status", "--porcelain"], working_dir)
        if success and stdout.strip():
            review_args = ["--type", "uncommitted"]
        else:
            review_args = ["--base-commit", "HEAD~1"]

    output_file = review_folder / "coderabbit.out"
    result = subprocess.run(
        ["uv", "run", "review.coderabbit", *review_args],
        cwd=working_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    output_file.write_text(result.stdout, encoding="utf-8")


def _parse_coderabbit(
    working_dir: Path,
    review_folder: Path,
    tasks_folder: Path,
) -> None:
    """Parse coderabbit output into task files."""
    review_file = review_folder / "coderabbit.out"
    if not review_file.is_file():
        return

    _run_command(
        [
            "uv",
            "run",
            "pr",
            "parse-coderabbit",
            "--review-file",
            str(review_file),
            "--output-dir",
            str(tasks_folder),
        ],
        working_dir,
    )

    # Cleanup raw review file
    review_file.unlink(missing_ok=True)


def _commit_changes(working_dir: Path, cycle: int, tasks_processed: int) -> tuple[bool, str | None]:
    """Commit changes if any exist. Returns (committed, commit_sha)."""
    # Check for changes
    success, stdout, _ = _run_command(["git", "status", "--porcelain"], working_dir)
    if not success or not stdout.strip():
        return False, None

    # Stage and commit
    _run_command(["git", "add", "-A"], working_dir)

    message = f"Review cycle {cycle}: applied {tasks_processed} tasks"
    success, _, stderr = _run_command(
        ["git", "commit", "-m", message],
        working_dir,
    )

    if not success:
        print(f"Warning: Commit failed: {stderr}", file=sys.stderr)
        return False, None

    # Get commit SHA
    success, stdout, _ = _run_command(["git", "rev-parse", "HEAD"], working_dir)
    commit_sha = stdout.strip() if success else None

    return True, commit_sha


def _post_deferred_replies(working_dir: Path, pr_number: int) -> None:
    """Post deferred replies to PR threads."""
    _run_command(
        ["uv", "run", "pr", "post-deferred-replies", "--pr", str(pr_number)],
        working_dir,
    )


def inner_cycle_command(state_file: Path, cycle: int) -> dict[str, Any]:
    """Execute one complete inner cycle.

    Args:
        state_file: Path to session state JSON file.
        cycle: Current cycle number.

    Returns:
        Cycle result dictionary with status, files, tasks_processed, etc.
    """
    # Read session state
    if not state_file.is_file():
        return {"status": "error", "error": f"State file not found: {state_file}"}

    state: dict[str, Any] = json.loads(state_file.read_text(encoding="utf-8"))

    mode = state.get("mode", "local")
    working_dir = Path(state.get("working_dir", "."))
    tmp_folder = Path(state.get("tmp_folder", ".tmp/pr-review"))
    pr_number = state.get("pr_number")

    tasks_folder = tmp_folder / "tasks"
    review_folder = tmp_folder / "review"

    # Ensure folders exist
    tasks_folder.mkdir(parents=True, exist_ok=True)
    review_folder.mkdir(parents=True, exist_ok=True)

    # Step 1: Aggregate tasks
    print(f"Cycle {cycle}: Aggregating tasks...", file=sys.stderr)
    aggregated = _aggregate_tasks(working_dir, tasks_folder)
    if aggregated is None:
        return {"status": "error", "error": "Task aggregation failed"}

    tasks_by_file: dict[str, list[str]] = aggregated.get("tasks_by_file", {})
    task_count = aggregated.get("task_count", 0)

    if task_count == 0:
        return {
            "status": "tasks_handled",
            "files": [],
            "tasks_processed": 0,
            "tests_passed": True,
            "committed": False,
            "commit_sha": None,
            "error": None,
            "local_task_responses": [],
        }

    # Step 2: Handle tasks (spawn file handlers in parallel)
    print(f"Cycle {cycle}: Processing {task_count} tasks...", file=sys.stderr)
    modified_files, local_task_responses = _spawn_file_handlers(
        working_dir, tasks_by_file, tasks_folder
    )

    # Step 3: Cleanup processed task files
    print(f"Cycle {cycle}: Cleaning up task files...", file=sys.stderr)
    _cleanup_task_files(tasks_folder)

    # Step 4: Run tests
    print(f"Cycle {cycle}: Running tests...", file=sys.stderr)
    tests_passed = _run_tests(working_dir, modified_files)

    # Step 5: Run lint
    print(f"Cycle {cycle}: Running lint...", file=sys.stderr)
    _run_lint(working_dir, modified_files)

    # Step 6: Run coderabbit
    print(f"Cycle {cycle}: Running coderabbit review...", file=sys.stderr)
    _run_coderabbit(working_dir, review_folder, mode, cycle)

    # Step 7: Parse coderabbit
    print(f"Cycle {cycle}: Parsing coderabbit output...", file=sys.stderr)
    _parse_coderabbit(working_dir, review_folder, tasks_folder)

    # Step 8: Commit changes
    print(f"Cycle {cycle}: Committing changes...", file=sys.stderr)
    committed, commit_sha = _commit_changes(working_dir, cycle, task_count)

    # Step 9: Update session state
    state["commits_made"] = state.get("commits_made", 0) + (1 if committed else 0)
    state["all_modified_files"] = list(set(state.get("all_modified_files", []) + modified_files))
    state.setdefault("cycle_summaries", []).append(
        {
            "cycle": cycle,
            "tasks_processed": task_count,
            "files_modified": len(modified_files),
            "committed": committed,
            "commit_sha": commit_sha,
        }
    )
    state.setdefault("local_task_responses", []).extend(local_task_responses)

    # Atomic write
    tmp_file = state_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp_file.replace(state_file)

    # Post-commit: Post deferred replies (worktree mode only)
    if mode == "worktree" and pr_number is not None and committed:
        print(f"Cycle {cycle}: Posting deferred replies...", file=sys.stderr)
        _post_deferred_replies(working_dir, pr_number)

    return {
        "status": "tasks_handled",
        "files": modified_files,
        "tasks_processed": task_count,
        "tests_passed": tests_passed,
        "committed": committed,
        "commit_sha": commit_sha,
        "error": None,
        "local_task_responses": local_task_responses,
    }
