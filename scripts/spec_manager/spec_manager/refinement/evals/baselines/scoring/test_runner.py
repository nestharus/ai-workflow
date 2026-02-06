"""Test runner for labyrinth evaluation - runs pytest and parses results."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestResults:
    """Parsed results from pytest execution.

    Attributes:
        total: Total number of tests.
        passed: Number of tests passed.
        failed: Number of tests failed.
        errors: Number of test errors.
        rule_tests_passed: Rule accuracy tests passed.
        rule_tests_total: Total rule accuracy tests.
        integration_tests_passed: Integration tests passed.
        integration_tests_total: Total integration tests.
        details: Per-test results.
    """
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    rule_tests_passed: int = 0
    rule_tests_total: int = 0
    integration_tests_passed: int = 0
    integration_tests_total: int = 0
    details: list[dict[str, str]] = field(default_factory=list)
    raw_output: str = ""


class TestRunner:
    """Runs pytest on labyrinth test suites and parses results."""

    def run(
        self,
        test_dir: Path,
        cwd: Path | None = None,
        extra_pythonpath: list[str] | None = None,
    ) -> TestResults:
        """Run pytest on the test directory.

        Args:
            test_dir: Directory containing test files.
            cwd: Working directory for pytest.
            extra_pythonpath: Additional paths to add to PYTHONPATH so
                model-written modules (e.g., labyrinth_setup.py) are importable.

        Returns:
            Parsed TestResults.
        """
        # Build environment with extra PYTHONPATH entries
        env = os.environ.copy()
        if extra_pythonpath:
            existing = env.get("PYTHONPATH", "")
            additions = os.pathsep.join(extra_pythonpath)
            env["PYTHONPATH"] = (
                f"{additions}{os.pathsep}{existing}" if existing else additions
            )

        # Run pytest with verbose output for per-test parsing
        cmd = [
            "uv", "run", "pytest",
            str(test_dir),
            "-v",
            "--tb=short",
            "--no-header",
        ]

        result = subprocess.run(
            cmd,
            cwd=cwd or test_dir.parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
            env=env,
        )

        raw = result.stdout + result.stderr
        return self._parse_verbose_output(raw)

    def _parse_verbose_output(self, output: str) -> TestResults:
        """Parse pytest verbose output for per-test results.

        Verbose mode outputs lines like:
        tests/test_labyrinth_l1.py::test_rule_accuracy_0001 PASSED
        tests/test_labyrinth_l1.py::test_chain_fired_0001 FAILED
        """
        results = TestResults(raw_output=output)

        # Match individual test results from verbose output
        test_line_re = re.compile(r"(\S+::(\S+))\s+(PASSED|FAILED|ERROR)")

        for match in test_line_re.finditer(output):
            nodeid = match.group(1)
            test_name = match.group(2)
            outcome = match.group(3).lower()

            results.details.append({"name": nodeid, "outcome": outcome})

            # Categorize as rule or integration test
            if "rule_accuracy" in test_name:
                results.rule_tests_total += 1
                if outcome == "passed":
                    results.rule_tests_passed += 1
            elif "integration" in test_name or "chain" in test_name or "side_effect" in test_name:
                results.integration_tests_total += 1
                if outcome == "passed":
                    results.integration_tests_passed += 1

        # Parse summary line for totals
        passed_m = re.search(r"(\d+) passed", output)
        failed_m = re.search(r"(\d+) failed", output)
        error_m = re.search(r"(\d+) error", output)

        if passed_m:
            results.passed = int(passed_m.group(1))
        if failed_m:
            results.failed = int(failed_m.group(1))
        if error_m:
            results.errors = int(error_m.group(1))

        results.total = results.passed + results.failed + results.errors

        return results
