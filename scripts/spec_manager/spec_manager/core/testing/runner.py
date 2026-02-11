"""Language-agnostic test runner protocol and implementations.

Provides a swappable test runner abstraction so the PromotionLoop
can execute tests without assuming a specific language or framework.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

logger = logging.getLogger(__name__)


@dataclass
class TestFailure:
    """A single test failure."""

    test_id: str | None = None
    file: str | None = None
    message: str = ""
    raw_excerpt_path: str = ""


@dataclass
class TestRunResult:
    """Result of running tests."""

    passed: bool = False
    scope: Literal["SLICE", "FULL"] = "SLICE"
    runner_id: str = ""
    command: list[str] = field(default_factory=list)
    stdout_path: str = ""
    stderr_path: str = ""
    failures: list[TestFailure] = field(default_factory=list)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    duration_ms: float = 0.0


class TestRunner(Protocol):
    """Protocol for language-specific test runners."""

    runner_id: str

    def run(
        self,
        *,
        root: Path,
        scope: Literal["SLICE", "FULL"] = "SLICE",
        targets: list[str] | None = None,
    ) -> TestRunResult:
        """Run tests and return results."""
        ...


class PytestRunner:
    """Python test runner using pytest.

    Reuses the same execution pattern as the ALL_TESTS_PASS gate
    to avoid redundant test infrastructure.
    """

    runner_id: str = "pytest"

    def __init__(self, extra_args: list[str] | None = None) -> None:
        self._extra_args = extra_args or []

    def run(
        self,
        *,
        root: Path,
        scope: Literal["SLICE", "FULL"] = "SLICE",
        targets: list[str] | None = None,
    ) -> TestRunResult:
        """Run pytest on the given root directory.

        Args:
            root: Directory to run tests in.
            scope: SLICE for slice-local tests, FULL for all tests.
            targets: Specific test files/dirs to run (optional).

        Returns:
            TestRunResult with pass/fail status and failure details.
        """
        import time

        cmd = ["python", "-m", "pytest", "-q", "--tb=short", "-p", "no:randomly"]
        cmd.extend(self._extra_args)

        if targets:
            cmd.extend(targets)
        else:
            cmd.append(str(root))

        start = time.monotonic()

        result = TestRunResult(
            scope=scope,
            runner_id=self.runner_id,
            command=cmd,
        )

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=300,
            )

            # Write stdout/stderr to files
            stdout_path = root / ".pdd_test_stdout.txt"
            stderr_path = root / ".pdd_test_stderr.txt"
            stdout_path.write_text(proc.stdout, encoding="utf-8")
            stderr_path.write_text(proc.stderr, encoding="utf-8")
            result.stdout_path = str(stdout_path)
            result.stderr_path = str(stderr_path)

            result.passed = proc.returncode == 0

            # Parse failure info from stdout
            if not result.passed:
                result.failures = self._parse_failures(proc.stdout)

            # Parse test counts from pytest output
            counts = self._parse_counts(proc.stdout)
            result.total_tests = counts.get("total", 0)
            result.passed_tests = counts.get("passed", 0)
            result.failed_tests = counts.get("failed", 0)

        except subprocess.TimeoutExpired:
            result.passed = False
            result.failures = [TestFailure(message="Test execution timed out (300s)")]
        except FileNotFoundError:
            result.passed = False
            result.failures = [TestFailure(message="pytest not found in PATH")]

        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    @staticmethod
    def _parse_failures(stdout: str) -> list[TestFailure]:
        """Extract failure info from pytest short-traceback output."""
        failures: list[TestFailure] = []
        lines = stdout.splitlines()

        for line in lines:
            if line.startswith("FAILED "):
                # Format: "FAILED path/to/test.py::test_name - message"
                parts = line[7:].split(" - ", 1)
                test_id = parts[0].strip()
                message = parts[1].strip() if len(parts) > 1 else ""
                file_part = test_id.split("::")[0] if "::" in test_id else None
                failures.append(
                    TestFailure(
                        test_id=test_id,
                        file=file_part,
                        message=message,
                    )
                )

        return failures

    @staticmethod
    def _parse_counts(stdout: str) -> dict[str, int]:
        """Extract test counts from pytest summary line."""
        import re

        counts: dict[str, int] = {"total": 0, "passed": 0, "failed": 0}

        for line in reversed(stdout.splitlines()):
            # Look for lines like "5 passed, 2 failed in 1.23s"
            passed_match = re.search(r"(\d+) passed", line)
            failed_match = re.search(r"(\d+) failed", line)

            if passed_match or failed_match:
                if passed_match:
                    counts["passed"] = int(passed_match.group(1))
                if failed_match:
                    counts["failed"] = int(failed_match.group(1))
                counts["total"] = counts["passed"] + counts["failed"]
                break

        return counts
