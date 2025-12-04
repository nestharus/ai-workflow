"""Testing workflow for test debugging with agent invocations.

This module encapsulates the testing workflow that invokes the test-debugger
agent, parses its output, and returns structured results. This workflow is
called by the apply_plan orchestrator when implementation produces failing tests.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

TestingStatus = Literal["fixed", "partial", "blocked"]


@dataclass
class TestingResult:
    """Result from running the test-debugger workflow.

    This dataclass matches the output contract defined in `.tasks/agents/test-debugger.md`:
    - FIXED: All tests now pass - status="fixed"
    - PARTIAL: <remaining_issues> - status="partial", message contains remaining issues
    - BLOCKED: <reason> - status="blocked", message contains blocking reason

    Attributes:
        status: One of "fixed", "partial", or "blocked".
        message: Status message extracted from test-debugger agent output.
    """

    status: TestingStatus
    message: str


def _run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    """Execute a command and stream output to stdout/stderr."""
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result


def _run_tasks_agent(agent: str, prompt: str) -> subprocess.CompletedProcess[str]:
    """Invoke tasks_agent_runner.py with the specified agent and prompt.

    Args:
        agent: Name of the .tasks agent to run (without .md extension).
        prompt: Prompt to pass to the agent.

    Returns:
        CompletedProcess result from subprocess execution.
    """
    runner = PROJECT_ROOT / "scripts" / "dev" / "tasks_agent_runner.py"
    command = [sys.executable, str(runner), "--agent", agent, "--prompt", prompt]
    return _run(command)


def _parse_test_debugger_output(output: str) -> tuple[TestingStatus, str]:
    """Parse test-debugger agent output to determine status.

    Parses the test-debugger agent's stdout to detect FIXED, PARTIAL, or BLOCKED markers
    as defined in the test-debugger agent's output contract.

    Args:
        output: The stdout from the test-debugger agent.

    Returns:
        A tuple of (status, message) where:
        - status is one of "fixed", "partial", or "blocked"
        - message is the extracted status message
    """
    fixed_match = re.search(r"FIXED:\s*(.+)", output, re.IGNORECASE)
    if fixed_match:
        return "fixed", fixed_match.group(1).strip()

    partial_match = re.search(r"PARTIAL:\s*(.+)", output, re.IGNORECASE)
    if partial_match:
        return "partial", partial_match.group(1).strip()

    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE)
    if blocked_match:
        return "blocked", blocked_match.group(1).strip()

    return "blocked", "Unrecognized test-debugger response"


def run_testing_workflow(task_content: str, failing_tests: list[str]) -> TestingResult:
    """Execute the test-debugger workflow for failing tests.

    This workflow debugs specific failing tests reported by the implementor agent.
    It formats a prompt with the task content and failing test list, invokes the
    test-debugger agent, and parses the output to determine the result.

    Args:
        task_content: The full content of the task file being implemented.
        failing_tests: List of failing test names to debug and fix.

    Returns:
        TestingResult with status and message populated based on the
        test-debugger agent's output.
    """
    fail_list = ", ".join(failing_tests)
    prompt = (
        f"Task: {task_content}\n"
        f"Failing Tests: [{fail_list}]\n"
        "Instructions: Debug and fix the failing tests. Run tests after fixes to verify."
    )

    result = _run_tasks_agent("test-debugger", prompt)
    status, message = _parse_test_debugger_output(result.stdout or "")

    return TestingResult(status=status, message=message)
