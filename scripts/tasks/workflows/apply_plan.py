#!/usr/bin/env python3
"""Orchestrate Traycer AI plans using OpenCode and Claude agents.

This orchestrator automatically routes tasks to appropriate implementor models
based on task file complexity (character count). The routing is now automatic
based on the implementor agent's `routing_thresholds` configuration in its
frontmatter, using prompt character count to select the appropriate runner/model
combination dynamically.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from scripts.tasks.commands import clipboard_to_plan
from scripts.tasks.workflows.implementation import (
    _count_task_chars,
    _parse_implementor_output,
    _run_tasks_agent,
)
from scripts.tasks.workflows.testing import (
    run_testing_workflow,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class ApplyPlanError(Exception):
    """Custom exception for orchestrator failures."""


def _run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        return {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _compute_plan_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_task_header(task_path: Path) -> str:
    first_line = task_path.read_text(encoding="utf-8").splitlines()[0:1]
    if not first_line:
        return ""
    header = first_line[0].lstrip("# ").strip()
    return header


def _collect_tasks(task_dir: Path) -> list[Path]:
    return sorted(task_dir.glob("task_*.md"))


def _init_status(task_dir: Path, plan_hash: str) -> dict[str, Any]:
    tasks = []
    for task_path in _collect_tasks(task_dir):
        tasks.append(
            {
                "task_file": task_path.name,
                "file": _parse_task_header(task_path),
                "status": "pending",
                "conclusion_file": None,
                "changes_file": None,
            }
        )
    return {"plan_hash": plan_hash, "tasks": tasks}


def _update_status(
    status_path: Path,
    status_data: dict[str, Any],
    task_file: str,
    **updates: Any,
) -> None:
    for task in status_data.get("tasks", []):
        if task.get("task_file") == task_file:
            task.update(updates)
            break
    _write_yaml(status_path, status_data)


def _run_clipboard_to_plan() -> Path:
    script_path = PROJECT_ROOT / "scripts" / "tasks" / "commands" / "clipboard_to_plan.py"
    result = subprocess.run(
        [sys.executable, str(script_path)], capture_output=True, text=True, cwd=PROJECT_ROOT
    )
    if result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
        raise ApplyPlanError("clipboard_to_plan.py failed")
    if not result.stdout.strip():
        raise ApplyPlanError("clipboard_to_plan.py returned no output")
    return Path(result.stdout.strip().splitlines()[-1])


def _run_opencode_agent(agent: str, prompt: str) -> subprocess.CompletedProcess[str]:
    runner = PROJECT_ROOT / "scripts" / "dev" / "opencode_agent_runner.py"
    command = [sys.executable, str(runner), "--agent", agent, "--prompt", prompt]
    return _run(command)


def _create_changes_files(task_dir: Path) -> list[str]:
    names_result = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    if names_result.returncode != 0:
        return []
    changes_files: list[str] = []
    for name in [n for n in names_result.stdout.splitlines() if n.strip()]:
        diff_result = subprocess.run(
            ["git", "diff", "--", name],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        if diff_result.returncode != 0 or not diff_result.stdout:
            continue
        sanitized = name.replace("/", "__")
        change_path = task_dir / f"{sanitized}.changes"
        change_path.write_text(diff_result.stdout)
        changes_files.append(str(change_path))
    return changes_files


def _detect_conclusion(task_dir: Path) -> Path | None:
    conclusions = sorted(task_dir.glob("*.conclusion"))
    return conclusions[0] if conclusions else None


def _patch_incomplete_tasks(
    task_dir: Path, status_path: Path, status_data: dict[str, Any], plan_text: str
) -> None:
    for task in status_data.get("tasks", []):
        if task.get("status") == "completed":
            continue
        task_path = task_dir / task.get("task_file", "")
        if not task_path.exists():
            continue
        prompt = (
            f"Task File: {task_path}\n"
            f"Status: {task.get('status')}\n"
            f"Implemented: Unknown (status={task.get('status')})\n"
            f"Not Implemented: Remaining items in task file\n"
            f"New Plan Content: {plan_text}"
        )
        _run_tasks_agent("task-patcher", prompt)
        _update_status(
            status_path, status_data, task["task_file"], status=task.get("status", "pending")
        )


def _process_task(
    task_dir: Path, task: dict[str, Any], status_path: Path, status_data: dict[str, Any]
) -> str:
    task_file = task.get("task_file")
    if not task_file:
        return "fail"
    task_path = task_dir / task_file
    task_content = task_path.read_text(encoding="utf-8")

    _update_status(status_path, status_data, task_file, status="in_progress")

    # Route to appropriate implementor model based on task complexity (character count)
    char_count = _count_task_chars(task_path)
    implementor_prompt = str(task_path)

    # Use _run_tasks_agent which automatically routes via agent's routing_thresholds
    result = _run_tasks_agent("implementor", implementor_prompt, char_count)
    mode, tests, failure_detail = _parse_implementor_output(result.stdout or "")

    if mode == "success":
        review_prompt = f"Review the implementation in {task_path} against the plan"
        _run_opencode_agent("reviewer", review_prompt)
        _update_status(status_path, status_data, task_file, status="completed")
        return "completed"

    if mode == "tests" and tests:
        run_testing_workflow(task_content, tests)
        _update_status(status_path, status_data, task_file, status="pending")
        return "tests"

    changes_files = _create_changes_files(task_dir)
    changes_blob = (
        "\n\n".join(
            f"=== {Path(path).name.replace('__', '/')} ===\n{Path(path).read_text()}"
            for path in changes_files
        )
        if changes_files
        else ""
    )
    fail_prompt = (
        f"Task: {task_content}\n"
        f"Changes Made:\n{changes_blob}\n"
        f"Failure: {failure_detail or 'No detail provided'}\n"
        "Instructions: Analyze the current state and determine if you can complete "
        "the implementation or if design decisions are needed."
    )
    _run_tasks_agent("implementation-analyzer", fail_prompt)
    conclusion = _detect_conclusion(task_dir)
    if conclusion:
        _update_status(
            status_path,
            status_data,
            task_file,
            status="pending",
            conclusion_file=str(conclusion),
        )
        return "conclusion"
    _update_status(
        status_path,
        status_data,
        task_file,
        status="pending",
        changes_file=changes_files or None,
    )
    return "fail"


def main() -> int:
    """Main entry point for applying Traycer AI plan."""
    parser = argparse.ArgumentParser(
        description="Apply Traycer AI plan using OpenCode and Claude agents"
    )
    parser.add_argument(
        "--tasks-dir", type=str, help="Existing tasks directory to resume", required=False
    )
    args = parser.parse_args()

    clipboard_text = clipboard_to_plan.get_clipboard_content()
    plan_hash = _compute_plan_hash(clipboard_text)

    task_dir = Path(args.tasks_dir) if args.tasks_dir else _run_clipboard_to_plan()

    status_path = task_dir / "status.yml"
    status_data = _load_yaml(status_path)

    if not status_data:
        status_data = _init_status(task_dir, plan_hash)
        _write_yaml(status_path, status_data)
    elif status_data.get("plan_hash") != plan_hash:
        _patch_incomplete_tasks(task_dir, status_path, status_data, clipboard_text)
        status_data["plan_hash"] = plan_hash
        _write_yaml(status_path, status_data)

    tasks = status_data.get("tasks", [])
    conclusion_detected = False

    for task in tasks:
        if task.get("status") == "completed":
            continue
        outcome = _process_task(task_dir, task, status_path, status_data)
        if outcome == "conclusion":
            conclusion_detected = True
            break

    remaining = [t for t in status_data.get("tasks", []) if t.get("status") != "completed"]
    if conclusion_detected:
        return 2
    if remaining:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ApplyPlanError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)
    except Exception as exc:  # pragma: no cover - defensive
        sys.stderr.write(f"Unexpected error: {exc}\n")
        sys.exit(1)
