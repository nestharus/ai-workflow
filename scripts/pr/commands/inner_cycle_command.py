"""Execute one review-fix-test cycle within the PR Review workflow."""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def _run_command(cmd: list[str], cwd: Path) -> tuple[bool, int, str, str]:
    """Run a command and return (success, exit_code, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0, result.returncode, result.stdout, result.stderr


def _aggregate_tasks(working_dir: Path, tasks_folder: Path) -> dict[str, Any] | None:
    """Aggregate task files into a manifest."""
    success, _exit_code, stdout, stderr = _run_command(
        ["uv", "run", "pr", "aggregate-tasks", "--input-dir", str(tasks_folder)],
        working_dir,
    )
    if not success:
        print(f"Error aggregating tasks: {stderr}", file=sys.stderr)
        return None

    # Parse aggregated output
    try:
        raw: Any = json.loads(stdout)
        if not isinstance(raw, dict):
            print("Error parsing aggregated tasks: unexpected output type", file=sys.stderr)
            return None
    except json.JSONDecodeError:
        print(f"Error parsing aggregated tasks: {stdout}", file=sys.stderr)
        return None

    # Log aggregation details
    tasks_by_file = raw.get("tasks_by_file", {})
    task_count = raw.get("task_count", 0)
    print(
        f"  Aggregated {task_count} task(s) across {len(tasks_by_file)} target(s):", file=sys.stderr
    )
    for file_path, task_files in tasks_by_file.items():
        print(f"    {file_path}: {task_files}", file=sys.stderr)

    return raw


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


def _run_single_task(
    working_dir: Path,
    file_path: str,
    task_file: str,
    tasks_folder: Path,
) -> dict[str, Any] | None:
    """Run a single task through the pr-file-handler agent.

    Returns the parsed JSON result or None on failure.
    """
    context = _build_file_handler_context(file_path, [task_file], tasks_folder)
    context_json = json.dumps(context)
    task = context["tasks"][0]
    content_preview = (task.get("content") or "")[:120]
    print(
        f"    task={task['id']} type={task.get('type')} "
        f"line={task.get('line')} content={content_preview!r}",
        file=sys.stderr,
    )

    success, exit_code, stdout, stderr = _run_command(
        ["uv", "run", "agents", "pr-file-handler", context_json],
        working_dir,
    )
    if not success:
        print(
            f"    [agent] Warning: Handler failed for {file_path} task={task['id']} "
            f"(exit={exit_code})",
            file=sys.stderr,
        )
        if stderr:
            print(f"      stderr: {stderr[:500]}", file=sys.stderr)
        return None

    try:
        result = json.loads(stdout)
        if not isinstance(result, dict):
            print(
                f"    [agent] Warning: Result not a dict for {file_path} task={task['id']}",
                file=sys.stderr,
            )
            return None
        return result
    except json.JSONDecodeError:
        print(
            f"    [agent] Warning: Could not parse result for {file_path} task={task['id']}",
            file=sys.stderr,
        )
        print(f"      stdout: {stdout[:500]}", file=sys.stderr)
        return None


def _process_file_tasks(
    working_dir: Path,
    file_path: str,
    task_files: list[str],
    tasks_folder: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Process all tasks for a single file sequentially.

    Returns (modified_files, local_task_responses).
    """
    modified_files: list[str] = []
    local_task_responses: list[dict[str, Any]] = []

    print(
        f"  [agent] Processing {file_path} with {len(task_files)} task(s)",
        file=sys.stderr,
    )

    for task_file in task_files:
        result = _run_single_task(working_dir, file_path, task_file, tasks_folder)
        if result is None:
            continue

        changes = result.get("changes_made", False)
        reply_preview = (result.get("deferred_reply") or "")[:200]
        print(
            f"    [agent] Result: changes_made={changes}",
            file=sys.stderr,
        )
        if reply_preview:
            print(f"      reply: {reply_preview!r}", file=sys.stderr)
        if changes and file_path not in modified_files:
            modified_files.append(file_path)
        if result.get("deferred_reply") and task_file.startswith("local_"):
            local_task_responses.append(
                {
                    "task_id": task_file.replace(".json", ""),
                    "reply": result["deferred_reply"],
                }
            )

    return modified_files, local_task_responses


def _spawn_file_handlers(
    working_dir: Path,
    tasks_by_file: dict[str, list[str]],
    tasks_folder: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Run pr-file-handler agents: parallel across files, sequential per file.

    Returns (modified_files, local_task_responses).
    """
    modified_files: list[str] = []
    local_task_responses: list[dict[str, Any]] = []

    # Separate file-specific and global tasks
    file_tasks = {fp: tf for fp, tf in tasks_by_file.items() if fp != "__global__"}
    global_task_files = tasks_by_file.get("__global__", [])

    # Process file-specific tasks in parallel (one thread per file, sequential within)
    if file_tasks:
        with ThreadPoolExecutor(max_workers=len(file_tasks)) as executor:
            futures = {
                executor.submit(_process_file_tasks, working_dir, fp, tf, tasks_folder): fp
                for fp, tf in file_tasks.items()
            }
            for future in as_completed(futures):
                fp = futures[future]
                try:
                    mf, ltr = future.result()
                    modified_files.extend(mf)
                    local_task_responses.extend(ltr)
                except Exception as exc:
                    print(
                        f"  [agent] Error processing {fp}: {exc}",
                        file=sys.stderr,
                    )

    # Process global tasks sequentially with pre/post diff tracking
    if global_task_files:
        _ok, _ec, pre_out, _ = _run_command(["git", "diff", "--name-only"], working_dir)
        pre_diff_files: set[str] = set()
        if _ok and pre_out.strip():
            pre_diff_files = {f.strip() for f in pre_out.strip().splitlines() if f.strip()}

        print(
            f"  [agent] Processing __global__ with {len(global_task_files)} task(s)",
            file=sys.stderr,
        )
        for task_file in global_task_files:
            result = _run_single_task(working_dir, "__global__", task_file, tasks_folder)
            if result is None:
                continue

            changes = result.get("changes_made", False)
            reply_preview = (result.get("deferred_reply") or "")[:200]
            print(
                f"    [agent] Global result: changes_made={changes}",
                file=sys.stderr,
            )
            if reply_preview:
                print(f"      reply: {reply_preview!r}", file=sys.stderr)
            if result.get("deferred_reply") and task_file.startswith("local_"):
                local_task_responses.append(
                    {
                        "task_id": task_file.replace(".json", ""),
                        "reply": result["deferred_reply"],
                    }
                )

        # Detect files modified by global handlers
        _ok, _ec, post_out, _ = _run_command(["git", "diff", "--name-only"], working_dir)
        if _ok and post_out.strip():
            post_files = {f.strip() for f in post_out.strip().splitlines() if f.strip()}
            for changed in sorted(post_files - pre_diff_files):
                if changed not in modified_files:
                    modified_files.append(changed)
                    print(
                        f"    [agent] Global handler modified: {changed}",
                        file=sys.stderr,
                    )

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

        # Skip files with no corresponding test file
        if not (working_dir / test_file).is_file():
            print(f"  [test] {file_path}: no test file ({test_file}), skipping", file=sys.stderr)
            continue

        context = json.dumps(
            {
                "file_path": file_path,
                "test_file": test_file,
                "working_dir": str(working_dir),
            }
        )

        proc = subprocess.Popen(
            ["uv", "run", "agents", "pr-test-fixer", context],
            cwd=working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append((file_path, proc))

    # Collect results
    all_passed = True
    for file_path, proc in processes:
        stdout, stderr = None, None
        try:
            stdout, stderr = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            print(
                f"  [test] Warning: Test fixer timed out for {file_path}, terminating process",
                file=sys.stderr,
            )
            proc.kill()
            timeout_stdout, timeout_stderr = proc.communicate()
            print(
                f"  [test] {file_path}: timed out - "
                f"stdout={timeout_stdout[:200]!r} stderr={timeout_stderr[:200]!r}",
                file=sys.stderr,
            )
            all_passed = False
            continue

        if proc.returncode != 0:
            print(
                f"  [test] Test fixer failed for {file_path} (exit={proc.returncode})",
                file=sys.stderr,
            )
            if stderr:
                print(f"    stderr: {stderr[:500]}", file=sys.stderr)
            all_passed = False
        else:
            try:
                result = json.loads(stdout)
                if not isinstance(result, dict):
                    print(
                        f"  [test] {file_path}: could not parse result (not a dict)",
                        file=sys.stderr,
                    )
                    all_passed = False
                    continue
                passed = result.get("tests_passed", True)
                fixes = result.get("fixes_applied", [])
                print(f"  [test] {file_path}: passed={passed} fixes={len(fixes)}", file=sys.stderr)
                if not passed:
                    all_passed = False
            except json.JSONDecodeError:
                print(f"  [test] {file_path}: could not parse result", file=sys.stderr)
                all_passed = False

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
        success, _exit_code, stdout, _ = _run_command(["git", "status", "--porcelain"], working_dir)
        if success and stdout.strip():
            review_args = ["--type", "uncommitted"]
        else:
            review_args = ["--base-commit", "HEAD~1"]

    print(
        f"  [coderabbit] Running: uv run review.coderabbit {' '.join(review_args)}", file=sys.stderr
    )

    output_file = review_folder / "coderabbit.out"
    result = subprocess.run(
        ["uv", "run", "review.coderabbit", *review_args],
        cwd=working_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    output_file.write_text(result.stdout, encoding="utf-8")

    # Log coderabbit output
    MAX_REVIEW_CHARS = 2000
    if result.returncode != 0:
        print(f"  [coderabbit] Exit code: {result.returncode}", file=sys.stderr)
        if result.stderr:
            truncated_stderr = (
                result.stderr[:MAX_REVIEW_CHARS]
                if len(result.stderr) > MAX_REVIEW_CHARS
                else result.stderr
            )
            print(f"  [coderabbit] stderr: {truncated_stderr}", file=sys.stderr)
            if len(result.stderr) > MAX_REVIEW_CHARS:
                print(
                    f"  [coderabbit] stderr: [truncated "
                    f"{len(result.stderr) - MAX_REVIEW_CHARS} chars]",
                    file=sys.stderr,
                )
    output_text = result.stdout.strip()
    if output_text:
        truncated_output = (
            output_text[:MAX_REVIEW_CHARS] if len(output_text) > MAX_REVIEW_CHARS else output_text
        )
        print(f"  [coderabbit] Review output ({len(output_text)} chars):", file=sys.stderr)
        # Print the review output (truncated if needed)
        for line in truncated_output.splitlines():
            print(f"  [coderabbit]   {line}", file=sys.stderr)
        if len(output_text) > MAX_REVIEW_CHARS:
            print(
                f"  [coderabbit]   [truncated {len(output_text) - MAX_REVIEW_CHARS} chars]",
                file=sys.stderr,
            )
    else:
        print("  [coderabbit] No review output (empty)", file=sys.stderr)


def _parse_coderabbit(
    working_dir: Path,
    review_folder: Path,
    tasks_folder: Path,
) -> None:
    """Parse coderabbit output into task files."""
    review_file = review_folder / "coderabbit.out"
    if not review_file.is_file():
        print("  [parse] No coderabbit.out file found, skipping parse", file=sys.stderr)
        return

    success, _exit_code, stdout, stderr = _run_command(
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

    if not success:
        print(f"  [parse] parse-coderabbit failed: {stderr}", file=sys.stderr)
    if stdout:
        for line in stdout.strip().splitlines():
            print(f"  [parse] {line}", file=sys.stderr)

    # Log newly created coderabbit task files
    new_tasks = sorted(tasks_folder.glob("coderabbit_*.json"))
    if new_tasks:
        print(
            f"  [parse] Created {len(new_tasks)} coderabbit task(s) for next cycle:",
            file=sys.stderr,
        )
        for task_path in new_tasks:
            try:
                task_data = json.loads(task_path.read_text(encoding="utf-8"))
                path = task_data.get("path", "?")
                line = task_data.get("line", "?")
                ctype = task_data.get("type", "?")
                content_preview = (task_data.get("content") or "")[:120]
                print(
                    f"    {task_path.name}: file={path} line={line} type={ctype}", file=sys.stderr
                )
                print(f"      content: {content_preview!r}", file=sys.stderr)
            except (json.JSONDecodeError, OSError):
                print(f"    {task_path.name}: (could not read)", file=sys.stderr)
    else:
        print(
            "  [parse] No coderabbit tasks created (clean review or no actionable comments)",
            file=sys.stderr,
        )

    # Cleanup raw review file
    review_file.unlink(missing_ok=True)


def _commit_changes(working_dir: Path, cycle: int, tasks_processed: int) -> tuple[bool, str | None]:
    """Commit changes if any exist. Returns (committed, commit_sha)."""
    # Check for changes
    success, _exit_code, stdout, _ = _run_command(["git", "status", "--porcelain"], working_dir)
    if not success or not stdout.strip():
        return False, None

    # Stage and commit
    add_ok, add_ec, add_out, add_err = _run_command(["git", "add", "-A"], working_dir)
    if not add_ok:
        print(
            f"Error: git add -A failed (exit={add_ec}) in {working_dir}",
            file=sys.stderr,
        )
        if add_err.strip():
            print(f"  stderr: {add_err.strip()}", file=sys.stderr)
        if add_out.strip():
            print(f"  stdout: {add_out.strip()}", file=sys.stderr)
        return False, None

    message = f"Review cycle {cycle}: applied {tasks_processed} tasks"
    success, _exit_code, _, stderr = _run_command(
        ["git", "commit", "-m", message],
        working_dir,
    )

    if not success:
        print(f"Warning: Commit failed: {stderr}", file=sys.stderr)
        return False, None

    # Get commit SHA
    success, _exit_code, stdout, _ = _run_command(["git", "rev-parse", "HEAD"], working_dir)
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
    if committed:
        print(f"  [commit] Committed: {commit_sha}", file=sys.stderr)
    else:
        print("  [commit] No changes to commit", file=sys.stderr)

    # Log cycle summary
    print(
        f"Cycle {cycle} summary: tasks={task_count} modified={len(modified_files)} "
        f"committed={committed} tests_passed={tests_passed}",
        file=sys.stderr,
    )

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
