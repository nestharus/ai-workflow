"""Implementation workflow for task execution with automatic model routing.

This module encapsulates the implementation workflow that invokes the implementor
agent, parses its output, and returns structured results. The routing logic
automatically selects the appropriate model based on task complexity (character count)
using the implementor agent's routing_thresholds configuration.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

ImplementationStatus = Literal["success", "tests", "fail"]


@dataclass
class ImplementationResult:
    """Result from running the implementation workflow.

    This dataclass matches the output contract defined in `.tasks/agents/implementor.md`:
    - SUCCESS: status="success", failing_tests=None, failure_detail=None
    - TESTS: [test1, test2]: status="tests", failing_tests=[...], failure_detail=None
    - FAIL: <message>: status="fail", failing_tests=None, failure_detail=<message>

    Attributes:
        status: One of "success", "tests", or "fail".
        failing_tests: List of failing test names when status is "tests", None otherwise.
        failure_detail: Failure message when status is "fail", None otherwise.
    """

    status: ImplementationStatus
    failing_tests: list[str] | None
    failure_detail: str | None


def _run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    """Execute a command and stream output to stdout/stderr."""
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result


def _count_task_chars(task_path: Path) -> int:
    """Count total characters in a task file.

    Args:
        task_path: Path to the task file.

    Returns:
        Number of characters in the file content.
    """
    content = task_path.read_text(encoding="utf-8")
    return len(content)


def _parse_implementor_output(
    output: str,
) -> tuple[ImplementationStatus, list[str] | None, str | None]:
    """Parse implementor agent output to determine status.

    Parses the implementor agent's stdout to detect SUCCESS, TESTS, or FAIL markers
    as defined in the implementor agent's output contract.

    Args:
        output: The stdout from the implementor agent.

    Returns:
        A tuple of (status, failing_tests, failure_detail) where:
        - status is one of "success", "tests", or "fail"
        - failing_tests is a list of test names when status is "tests"
        - failure_detail is the failure message when status is "fail"
    """
    if "SUCCESS" in output:
        return "success", None, None
    tests_match = re.search(r"TESTS:\s*\[(.*?)\]", output, re.IGNORECASE)
    if tests_match:
        tests = [t.strip() for t in tests_match.group(1).split(",") if t.strip()]
        return "tests", tests, None
    fail_match = re.search(r"FAIL:\s*(.+)", output, re.IGNORECASE)
    if fail_match:
        return "fail", None, fail_match.group(1).strip()
    return "fail", None, "Unrecognized implementor response"


def _run_tasks_agent(
    agent_name: str, prompt: str, prompt_chars: int | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a .tasks system agent with optional prompt character count for routing.

    Invokes tasks_agent_runner.py with the specified agent and prompt. When
    prompt_chars is provided, the agent's routing_thresholds are automatically
    consulted to select the appropriate model/provider.

    Args:
        agent_name: Name of the agent to run (without .md extension).
        prompt: Prompt to pass to the agent.
        prompt_chars: Optional character count for routing. When provided,
            enables automatic model selection based on the agent's
            routing_thresholds configuration.

    Returns:
        CompletedProcess result from subprocess execution.
    """
    runner = PROJECT_ROOT / "scripts" / "dev" / "tasks_agent_runner.py"
    command = [sys.executable, str(runner), "--agent", agent_name, "--prompt", prompt]

    if prompt_chars is not None:
        command.extend(["--prompt-chars", str(prompt_chars)])

    return _run(command)


def run_implementation_workflow(task_path: Path, task_dir: Path) -> ImplementationResult:
    """Execute the implementation workflow for a task.

    This workflow:
    1. Counts characters in the task file for routing decisions
    2. Invokes the implementor agent with automatic model selection
    3. Parses the output to determine success/tests/fail status
    4. Returns a structured result object

    The routing is automatic based on the implementor agent's routing_thresholds
    configuration in its frontmatter. The character count is passed to
    tasks_agent_runner.py which consults the thresholds to select the appropriate
    model/provider combination.

    Args:
        task_path: Path to the task file (e.g., task_001.md).
        task_dir: Directory containing the task files. Currently unused but kept
            for consistency with the orchestration layer in apply_plan.py, which
            may pass task_dir for future workflow extensions.

    Returns:
        ImplementationResult with status, failing_tests, and failure_detail
        populated based on the implementor agent's output.
    """
    # task_dir is unused but kept for API consistency with apply_plan orchestration
    _ = task_dir

    # Count characters for routing decision
    char_count = _count_task_chars(task_path)

    # Invoke implementor agent with character count for routing
    result = _run_tasks_agent("implementor", str(task_path), char_count)

    # Parse output to determine status
    status, failing_tests, failure_detail = _parse_implementor_output(result.stdout or "")

    return ImplementationResult(
        status=status,
        failing_tests=failing_tests,
        failure_detail=failure_detail,
    )
