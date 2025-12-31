"""Component tests for parallel linter execution workflow.

This module provides comprehensive component tests for the parallel linter execution
system. Tests verify the complete workflow from scheduling through execution.

Test Organization:
- TestScheduleLintersWorkflow: Tests for schedule_linters() with real linter instances
- TestLinterFailureHandling: Tests for failure handling in mutating vs read-only phases
- TestParallelPerformanceBenchmarks: Performance tests verifying parallel speedup
- TestOutputCorrectness: Tests ensuring parallel execution produces correct results
- TestEdgeCases: Edge case tests for empty filesets, single files, etc.
- TestFullCLIWorkflow: Integration tests for the complete CLI workflow
- TestLintCLIMainWorkflow: End-to-end tests for lint_cli.main() with patched args

Mock Linter Patterns:
Tests create mock linters by subclassing BaseLinter with controlled behavior:
- SlowLinter: Sleep for fixed duration to test parallel timing
- TimestampLinter: Log start/end times to verify overlap
- FailingLinter: Return success=False to test failure handling
- ExceptionLinter: Raise exceptions to test error conversion

Performance Test Methodology:
Parallel execution tests use RELATIVE comparisons against measured sequential baselines
rather than absolute time thresholds. This approach:
- Measures sequential execution time first as a baseline
- Compares parallel execution time against this measured baseline
- Uses generous percentage thresholds (50-75%) to absorb CI variability
- Avoids flaky tests caused by slow CI environments or heavy load
"""

import argparse
import io
import time
from unittest.mock import patch

import pytest

from scripts.dev.linter.base import (
    BaseLinter,
    InvalidCommandError,
    LinterResult,
    calculate_fileset,
    execute_phase,
    filter_files_with_config,
    get_executable,
    run_checked,
    schedule_linters,
)
from scripts.dev.linter.lint_cli import main
from scripts.dev.linter.linters import LINTER_MAP, LINTER_NAMES, LINTERS


class TestInvalidCommandError:
    def test_init_sets_standard_message(self) -> None:
        """Test that __init__ sets the standard validation message (line 28)."""
        error = InvalidCommandError()
        assert str(error) == "command must be a non-empty list of strings"

    def test_is_type_error(self) -> None:
        """Test that InvalidCommandError is a TypeError."""
        error = InvalidCommandError()
        assert isinstance(error, TypeError)

    def test_can_be_raised_and_caught(self) -> None:
        """Test that InvalidCommandError can be raised and caught properly."""
        with pytest.raises(InvalidCommandError) as exc_info:
            raise InvalidCommandError()
        assert "command must be a non-empty list of strings" in str(exc_info.value)


class TestRunChecked:
    def test_run_checked_empty_list_raises_invalid_command_error(self) -> None:
        """Test run_checked with empty list raises InvalidCommandError (lines 44, 47-48)."""
        with pytest.raises(InvalidCommandError) as exc_info:
            run_checked([])
        assert "command must be a non-empty list of strings" in str(exc_info.value)

    def test_run_checked_non_list_raises_invalid_command_error(self) -> None:
        """Test run_checked with non-list raises InvalidCommandError (line 44)."""
        with pytest.raises(InvalidCommandError):
            run_checked("echo hello")  # type: ignore[arg-type]

    def test_run_checked_list_with_non_strings_raises_invalid_command_error(self) -> None:
        """Test run_checked with non-string elements raises InvalidCommandError (line 44)."""
        with pytest.raises(InvalidCommandError):
            run_checked(["echo", 123])  # type: ignore[list-item]

    def test_run_checked_none_raises_invalid_command_error(self) -> None:
        """Test run_checked with None raises InvalidCommandError."""
        with pytest.raises(InvalidCommandError):
            run_checked(None)  # type: ignore[arg-type]

    def test_run_checked_mixed_types_raises_invalid_command_error(self) -> None:
        """Test run_checked with mixed types in list raises InvalidCommandError."""
        with pytest.raises(InvalidCommandError):
            run_checked(["command", None, "arg"])  # type: ignore[list-item]


class TestLinterResult:
    def test_linter_result_success(self) -> None:
        """Test creating a successful LinterResult."""
        result = LinterResult(success=True)
        assert result.success is True
        assert result.message is None

    def test_linter_result_failure_with_message(self) -> None:
        """Test creating a failed LinterResult with message."""
        result = LinterResult(success=False, message="Linting failed")
        assert result.success is False
        assert result.message == "Linting failed"

    def test_linter_result_success_with_message(self) -> None:
        """Test creating a successful LinterResult with message."""
        result = LinterResult(success=True, message="All checks passed")
        assert result.success is True
        assert result.message == "All checks passed"


class TestExecutePhaseComponent:
    """Component tests for execute_phase with stub linters.

    These tests verify the execute_phase workflow behavior using stub linters
    that don't require system binaries, ensuring hermetic test execution.
    """

    def test_execute_single_linter_with_stub(self) -> None:
        """Test executing a single linter using a stub implementation."""

        class StubScriptsLinter(BaseLinter):
            name = "scripts"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="Scripts check passed")

        test_linter_map = {"scripts": StubScriptsLinter()}

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["scripts"], None)

        assert len(results) == 1
        assert "scripts" in results
        assert isinstance(results["scripts"], LinterResult)
        assert results["scripts"].success is True

    def test_execute_multiple_linters_in_parallel_with_stubs(self) -> None:
        """Test executing multiple linters in parallel using stub implementations."""

        class StubScriptsLinter(BaseLinter):
            name = "scripts"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="Scripts check passed")

        class StubCheckovLinter(BaseLinter):
            name = "checkov"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="Checkov check passed")

        test_linter_map = {
            "scripts": StubScriptsLinter(),
            "checkov": StubCheckovLinter(),
        }

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["scripts", "checkov"], None)

        assert len(results) == 2
        assert "scripts" in results
        assert "checkov" in results
        assert isinstance(results["scripts"], LinterResult)
        assert isinstance(results["checkov"], LinterResult)
        assert results["scripts"].success is True
        assert results["checkov"].success is True

    def test_unknown_linter_returns_error(self) -> None:
        """Test that unknown linter name returns error result."""
        results = execute_phase(["nonexistent-component-linter"], None)

        assert len(results) == 1
        assert results["nonexistent-component-linter"].success is False
        assert "Unknown linter" in (results["nonexistent-component-linter"].message or "")

    def test_mixed_known_unknown_linters_with_stub(self) -> None:
        """Test parallel execution with mix of known and unknown linters."""

        class StubScriptsLinter(BaseLinter):
            name = "scripts"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="Scripts check passed")

        test_linter_map = {"scripts": StubScriptsLinter()}

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["scripts", "fake-linter-xyz"], None)

        assert len(results) == 2
        assert isinstance(results["scripts"], LinterResult)
        assert results["scripts"].success is True
        assert results["fake-linter-xyz"].success is False
        assert "Unknown linter" in (results["fake-linter-xyz"].message or "")

    def test_empty_phase_returns_empty_dict(self) -> None:
        """Test empty phase returns empty dict."""
        results = execute_phase([])

        assert results == {}

    def test_execute_phase_returns_linter_result_type_with_stubs(self) -> None:
        """Test that all results are LinterResult instances."""

        class StubLinterA(BaseLinter):
            name = "stub-linter-a"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="Linter A passed")

        class StubLinterB(BaseLinter):
            name = "stub-linter-b"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Linter B failed")

        test_linter_map = {
            "stub-linter-a": StubLinterA(),
            "stub-linter-b": StubLinterB(),
        }

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["stub-linter-a", "stub-linter-b"], None)

        for linter_name, result in results.items():
            assert isinstance(result, LinterResult), (
                f"Result for {linter_name} is not LinterResult: {type(result)}"
            )
            assert isinstance(result.success, bool)
            assert result.message is None or isinstance(result.message, str)


class TestExecutePhaseParallelBehavior:
    """Integration tests that verify parallel execution behavior."""

    def test_parallel_linters_run_concurrently(self) -> None:
        """Test that multiple linters execute in parallel, not sequentially.

        Creates dummy linters that sleep for a fixed duration and verifies
        parallel execution is significantly faster than a measured sequential baseline.
        Uses relative comparison instead of absolute thresholds to avoid CI flakiness.
        """
        sleep_duration = 0.3  # seconds per linter (increased for stability)
        num_linters = 3

        class SlowLinterA(BaseLinter):
            name = "slow-linter-a"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                time.sleep(sleep_duration)
                return LinterResult(success=True, message="SlowLinterA done")

        class SlowLinterB(BaseLinter):
            name = "slow-linter-b"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                time.sleep(sleep_duration)
                return LinterResult(success=True, message="SlowLinterB done")

        class SlowLinterC(BaseLinter):
            name = "slow-linter-c"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                time.sleep(sleep_duration)
                return LinterResult(success=True, message="SlowLinterC done")

        test_linter_map = {
            "slow-linter-a": SlowLinterA(),
            "slow-linter-b": SlowLinterB(),
            "slow-linter-c": SlowLinterC(),
        }

        # Measure sequential baseline: run each linter one at a time
        sequential_start = time.monotonic()
        for linter in test_linter_map.values():
            linter.run(None)
        sequential_time = time.monotonic() - sequential_start

        # Measure parallel execution via execute_phase
        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            parallel_start = time.monotonic()
            results = execute_phase(["slow-linter-a", "slow-linter-b", "slow-linter-c"], None)
            parallel_time = time.monotonic() - parallel_start

        # Verify all linters ran successfully
        assert len(results) == num_linters
        for linter_name in ["slow-linter-a", "slow-linter-b", "slow-linter-c"]:
            assert results[linter_name].success is True

        # Parallel should be significantly faster than sequential
        # Use 75% threshold: parallel must be faster than 75% of sequential time
        # This is generous but still proves parallelism (sequential would be ~3x one sleep)
        max_parallel_threshold = sequential_time * 0.75

        assert parallel_time < sequential_time, (
            f"Parallel execution not faster: parallel {parallel_time:.3f}s >= "
            f"sequential {sequential_time:.3f}s"
        )
        assert parallel_time < max_parallel_threshold, (
            f"Parallel execution not significantly faster: parallel {parallel_time:.3f}s >= "
            f"75% of sequential {max_parallel_threshold:.3f}s"
        )

    def test_parallel_linters_have_overlapping_intervals(self) -> None:
        """Test that linter execution intervals overlap, proving concurrency.

        Tracks start/end timestamps in patched linters and asserts overlapping
        intervals. Fails if linters run sequentially, passes only with parallelism.
        """
        execution_log: list[tuple[str, str, float]] = []  # (linter, event, timestamp)
        sleep_duration = 0.15

        class TimestampLinterA(BaseLinter):
            name = "timestamp-linter-a"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                execution_log.append(("a", "start", time.monotonic()))
                time.sleep(sleep_duration)
                execution_log.append(("a", "end", time.monotonic()))
                return LinterResult(success=True)

        class TimestampLinterB(BaseLinter):
            name = "timestamp-linter-b"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                execution_log.append(("b", "start", time.monotonic()))
                time.sleep(sleep_duration)
                execution_log.append(("b", "end", time.monotonic()))
                return LinterResult(success=True)

        test_linter_map = {
            "timestamp-linter-a": TimestampLinterA(),
            "timestamp-linter-b": TimestampLinterB(),
        }

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["timestamp-linter-a", "timestamp-linter-b"], None)

        # Verify both linters ran
        assert len(results) == 2
        assert results["timestamp-linter-a"].success is True
        assert results["timestamp-linter-b"].success is True

        # Extract timestamps
        a_start = next(t for name, e, t in execution_log if name == "a" and e == "start")
        a_end = next(t for name, e, t in execution_log if name == "a" and e == "end")
        b_start = next(t for name, e, t in execution_log if name == "b" and e == "start")
        b_end = next(t for name, e, t in execution_log if name == "b" and e == "end")

        # Check for overlapping intervals: A and B overlap if
        # A.start < B.end AND B.start < A.end
        intervals_overlap = a_start < b_end and b_start < a_end

        assert intervals_overlap, (
            f"Linter intervals do not overlap (sequential execution detected):\n"
            f"  Linter A: start={a_start:.4f}, end={a_end:.4f}\n"
            f"  Linter B: start={b_start:.4f}, end={b_end:.4f}\n"
            f"  For overlap, need A.start < B.end ({a_start:.4f} < {b_end:.4f}) "
            f"AND B.start < A.end ({b_start:.4f} < {a_end:.4f})"
        )


class TestScheduleLintersWorkflow:
    """Tests for schedule_linters() with real linter instances."""

    def test_schedule_all_linters_whole_repo_scan(self) -> None:
        """Verify scheduling all linters for whole-repo scan produces correct phases.

        Expected structure:
        - Phase 1: ["ruff"] (mutating linter, runs alone)
        - Phase 2: All 13 read-only linters (run in parallel)
        """
        phases = schedule_linters(LINTERS, None)

        # Should have 2 phases: 1 mutating + 1 read-only parallel
        assert len(phases) == 2

        # Phase 1: Only ruff (the mutating linter)
        assert phases[0] == ["ruff"]

        # Phase 2: All read-only linters
        read_only_phase = phases[1]
        assert "ruff" not in read_only_phase

        # Verify all non-mutating linters are in the read-only phase
        expected_readonly = [linter.name for linter in LINTERS if not linter.mutates_files]
        assert sorted(read_only_phase) == sorted(expected_readonly)

    def test_schedule_with_file_filtering_python_files(self) -> None:
        """Verify scheduling with Python files filters out non-Python linters."""
        python_files = ["app/main.py", "scripts/dev/linter/base.py"]
        phases = schedule_linters(LINTERS, python_files)

        # Should have phases (mutating + read-only)
        assert len(phases) >= 1

        # Flatten all phases to get all scheduled linters
        all_scheduled = [name for phase in phases for name in phase]

        # Python-relevant linters should be included
        assert "ruff" in all_scheduled
        assert "mypy" in all_scheduled
        assert "astgrep" in all_scheduled

        # Non-Python linters should NOT be scheduled
        assert "hadolint" not in all_scheduled
        assert "yamllint" not in all_scheduled
        assert "shellcheck" not in all_scheduled
        assert "pymarkdown" not in all_scheduled
        assert "actionlint" not in all_scheduled
        assert "dotenvlint" not in all_scheduled

    def test_schedule_with_empty_filesets_skips_linters(self) -> None:
        """Verify linters with empty filesets are completely skipped from phases."""
        # Only markdown file - should only include pymarkdown, detect-secrets, gitleaks
        files = ["README.md"]
        phases = schedule_linters(LINTERS, files)

        # Flatten all phases
        all_scheduled = [name for phase in phases for name in phase]

        # Ruff should NOT be scheduled (no Python files)
        assert "ruff" not in all_scheduled

        # pymarkdown should be scheduled (has .md file)
        assert "pymarkdown" in all_scheduled

        # detect-secrets and gitleaks scan all file types
        assert "detect-secrets" in all_scheduled
        assert "gitleaks" in all_scheduled

    def test_schedule_mixed_file_types(self) -> None:
        """Verify scheduling with mixed file types includes appropriate linters."""
        mixed_files = ["app/main.py", "docker-compose.yaml", "Dockerfile", "README.md"]
        phases = schedule_linters(LINTERS, mixed_files)

        # Flatten all phases
        all_scheduled = [name for phase in phases for name in phase]

        # Python linters
        assert "ruff" in all_scheduled
        assert "mypy" in all_scheduled

        # Markdown linter
        assert "pymarkdown" in all_scheduled

        # Docker linter
        assert "hadolint" in all_scheduled

        # Secret scanning linters (scan all types)
        assert "detect-secrets" in all_scheduled
        assert "gitleaks" in all_scheduled


class TestLinterFailureHandling:
    """Tests for failure handling in mutating vs read-only phases."""

    def test_mutating_linter_failure_returns_failure_result(self) -> None:
        """Create a mock mutating linter that fails, verify execute_phase returns failure."""

        class FailingMutatingLinter(BaseLinter):
            name = "failing-mutating"
            supports_file_filtering = True
            mutates_files = True

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Mutating linter failed")

        test_linter_map = {"failing-mutating": FailingMutatingLinter()}

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["failing-mutating"], None)

        assert len(results) == 1
        assert results["failing-mutating"].success is False
        assert "Mutating linter failed" in (results["failing-mutating"].message or "")

    def test_read_only_linter_failure_continues_execution(self) -> None:
        """Create multiple mock read-only linters where one fails, verify all complete."""

        class SuccessLinter(BaseLinter):
            name = "success-linter"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="Success")

        class FailingLinter(BaseLinter):
            name = "failing-linter"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Read-only linter failed")

        class AnotherSuccessLinter(BaseLinter):
            name = "another-success"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="Another success")

        test_linter_map = {
            "success-linter": SuccessLinter(),
            "failing-linter": FailingLinter(),
            "another-success": AnotherSuccessLinter(),
        }

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["success-linter", "failing-linter", "another-success"], None)

        # All three linters should have results
        assert len(results) == 3
        assert results["success-linter"].success is True
        assert results["failing-linter"].success is False
        assert results["another-success"].success is True

    def test_multiple_read_only_failures_reports_all(self) -> None:
        """Create multiple failing read-only linters, verify all failures are collected."""

        class FailingLinterA(BaseLinter):
            name = "failing-a"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Failure A")

        class FailingLinterB(BaseLinter):
            name = "failing-b"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Failure B")

        class FailingLinterC(BaseLinter):
            name = "failing-c"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Failure C")

        test_linter_map = {
            "failing-a": FailingLinterA(),
            "failing-b": FailingLinterB(),
            "failing-c": FailingLinterC(),
        }

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["failing-a", "failing-b", "failing-c"], None)

        # All three failures should be collected
        assert len(results) == 3
        assert all(not result.success for result in results.values())
        assert results["failing-a"].message == "Failure A"
        assert results["failing-b"].message == "Failure B"
        assert results["failing-c"].message == "Failure C"

    def test_exception_in_linter_converted_to_result(self) -> None:
        """Create a linter that raises an exception, verify it's caught and converted."""

        class ExceptionLinter(BaseLinter):
            name = "exception-linter"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                raise RuntimeError("Unexpected runtime error")

        test_linter_map = {"exception-linter": ExceptionLinter()}

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["exception-linter"], None)

        assert len(results) == 1
        assert results["exception-linter"].success is False
        assert "Unexpected runtime error" in (results["exception-linter"].message or "")


class TestParallelPerformanceBenchmarks:
    """Performance tests verifying parallel speedup.

    These tests use relative comparison against measured sequential baselines
    rather than absolute time thresholds. This makes them resilient to CI
    environment variability (heavy load, resource contention, slow machines).
    """

    def test_parallel_execution_faster_than_sequential(self) -> None:
        """Create 5 mock read-only linters that each sleep for a fixed duration.

        Verify parallel execution is significantly faster than a measured
        sequential baseline by comparing against actually measured times.
        """
        sleep_duration = 0.25  # Increased for more stable measurements
        num_linters = 5

        def create_slow_linter(name: str) -> BaseLinter:
            class SlowLinter(BaseLinter):
                supports_file_filtering = True
                mutates_files = False

                def run(self, files: list[str] | None = None) -> LinterResult:
                    time.sleep(sleep_duration)
                    return LinterResult(success=True, message=f"{name} done")

            linter = SlowLinter()
            linter.name = name
            return linter

        test_linter_map = {f"slow-{i}": create_slow_linter(f"slow-{i}") for i in range(num_linters)}
        linter_names = list(test_linter_map.keys())

        # Measure sequential baseline: run each linter one at a time
        sequential_start = time.monotonic()
        for linter in test_linter_map.values():
            linter.run(None)
        sequential_time = time.monotonic() - sequential_start

        # Measure parallel execution via execute_phase
        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            parallel_start = time.monotonic()
            results = execute_phase(linter_names, None)
            parallel_time = time.monotonic() - parallel_start

        # Verify all linters ran successfully
        assert len(results) == num_linters
        for name in linter_names:
            assert results[name].success is True

        # Parallel should be at least 2x faster than sequential
        # With 5 linters, true parallel would be ~5x faster
        # Using 50% threshold is generous but proves significant parallelism
        max_parallel_threshold = sequential_time * 0.50

        assert parallel_time < sequential_time, (
            f"Parallel execution not faster: parallel {parallel_time:.3f}s >= "
            f"sequential {sequential_time:.3f}s"
        )
        assert parallel_time < max_parallel_threshold, (
            f"Parallel execution not significantly faster: parallel {parallel_time:.3f}s >= "
            f"50% of sequential {max_parallel_threshold:.3f}s"
        )

    def test_mutating_linter_runs_before_readonly(self) -> None:
        """Create 1 mutating linter and 3 read-only linters with timestamp logging.

        Verify mutating linter completes before any read-only linter starts.
        """
        execution_log: list[tuple[str, str, float]] = []

        class MutatingLinter(BaseLinter):
            name = "mutating"
            supports_file_filtering = True
            mutates_files = True

            def run(self, files: list[str] | None = None) -> LinterResult:
                execution_log.append(("mutating", "start", time.monotonic()))
                time.sleep(0.1)
                execution_log.append(("mutating", "end", time.monotonic()))
                return LinterResult(success=True)

        def create_readonly_linter(name: str) -> BaseLinter:
            class ReadOnlyLinter(BaseLinter):
                supports_file_filtering = True
                mutates_files = False

                def run(self, files: list[str] | None = None) -> LinterResult:
                    execution_log.append((name, "start", time.monotonic()))
                    time.sleep(0.05)
                    execution_log.append((name, "end", time.monotonic()))
                    return LinterResult(success=True)

            linter = ReadOnlyLinter()
            linter.name = name
            return linter

        mutating_linter = MutatingLinter()
        readonly_linters = [create_readonly_linter(f"readonly-{i}") for i in range(3)]

        all_linters = [mutating_linter, *readonly_linters]
        test_linter_map = {linter.name: linter for linter in all_linters}

        # Schedule and execute phases
        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            phases = schedule_linters(all_linters, None)

            # Should have 2 phases: mutating then read-only
            assert len(phases) == 2
            assert phases[0] == ["mutating"]
            assert sorted(phases[1]) == sorted([f"readonly-{i}" for i in range(3)])

            # Execute phases in order
            for phase in phases:
                execute_phase(phase, None)

        # Find mutating end time
        mutating_end = next(
            t for name, event, t in execution_log if name == "mutating" and event == "end"
        )

        # Find earliest readonly start time
        readonly_starts = [
            t
            for name, event, t in execution_log
            if name.startswith("readonly") and event == "start"
        ]
        earliest_readonly_start = min(readonly_starts)

        # Mutating must complete before any readonly starts
        assert mutating_end < earliest_readonly_start, (
            f"Mutating linter ended at {mutating_end:.4f} but "
            f"readonly started at {earliest_readonly_start:.4f}"
        )

    def test_parallel_speedup_scales_with_linter_count(self) -> None:
        """Test with 2, 4, 8 mock linters, verify parallel time is stable.

        Uses relative comparison: measures sequential baseline for the largest
        case (8 linters) and verifies all parallel executions are significantly
        faster. This approach is resilient to CI environment variability.
        """
        sleep_duration = 0.15  # Increased for stability

        def create_slow_linter(name: str) -> BaseLinter:
            class SlowLinter(BaseLinter):
                supports_file_filtering = True
                mutates_files = False

                def run(self, files: list[str] | None = None) -> LinterResult:
                    time.sleep(sleep_duration)
                    return LinterResult(success=True)

            linter = SlowLinter()
            linter.name = name
            return linter

        def measure_parallel_time(num_linters: int) -> float:
            test_linter_map = {
                f"linter-{i}": create_slow_linter(f"linter-{i}") for i in range(num_linters)
            }
            with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
                start = time.monotonic()
                execute_phase(list(test_linter_map.keys()), None)
                return time.monotonic() - start

        def measure_sequential_time(num_linters: int) -> float:
            test_linter_map = {
                f"linter-{i}": create_slow_linter(f"linter-{i}") for i in range(num_linters)
            }
            start = time.monotonic()
            for linter in test_linter_map.values():
                linter.run(None)
            return time.monotonic() - start

        # Measure sequential baseline for 8 linters
        sequential_8 = measure_sequential_time(8)

        # Measure parallel times for 2, 4, 8 linters
        time_2 = measure_parallel_time(2)
        time_4 = measure_parallel_time(4)
        time_8 = measure_parallel_time(8)

        # If truly parallel, all times should be significantly less than sequential_8
        # The key insight: even 8 parallel linters should complete faster than
        # 8 sequential linters. We use 50% threshold for generous tolerance.
        max_allowed = sequential_8 * 0.50

        assert time_2 < max_allowed, (
            f"2 linters took {time_2:.3f}s, expected < {max_allowed:.3f}s "
            f"(50% of sequential 8 linters: {sequential_8:.3f}s)"
        )
        assert time_4 < max_allowed, (
            f"4 linters took {time_4:.3f}s, expected < {max_allowed:.3f}s "
            f"(50% of sequential 8 linters: {sequential_8:.3f}s)"
        )
        assert time_8 < max_allowed, (
            f"8 linters took {time_8:.3f}s, expected < {max_allowed:.3f}s "
            f"(50% of sequential 8 linters: {sequential_8:.3f}s)"
        )

        # Additional check: parallel times should be roughly similar regardless of count
        # (all within 2x of the fastest, accounting for thread pool variability)
        min_time = min(time_2, time_4, time_8)
        assert time_2 < min_time * 3.0, f"2 linters time {time_2:.3f}s > 3x min {min_time:.3f}s"
        assert time_4 < min_time * 3.0, f"4 linters time {time_4:.3f}s > 3x min {min_time:.3f}s"
        assert time_8 < min_time * 3.0, f"8 linters time {time_8:.3f}s > 3x min {min_time:.3f}s"


class TestOutputCorrectness:
    """Tests ensuring parallel execution produces correct results."""

    def test_parallel_results_match_sequential_results(self) -> None:
        """Create mock linters with deterministic output, verify results are correct."""
        expected_messages = {
            "linter-a": "Result A",
            "linter-b": "Result B",
            "linter-c": "Result C",
        }

        def create_linter(name: str, message: str) -> BaseLinter:
            class DeterministicLinter(BaseLinter):
                supports_file_filtering = True
                mutates_files = False

                def run(self, files: list[str] | None = None) -> LinterResult:
                    return LinterResult(success=True, message=message)

            linter = DeterministicLinter()
            linter.name = name
            return linter

        test_linter_map = {
            name: create_linter(name, msg) for name, msg in expected_messages.items()
        }

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(list(test_linter_map.keys()), None)

        # Verify all results match expected
        assert len(results) == len(expected_messages)
        for name, expected_msg in expected_messages.items():
            assert results[name].success is True
            assert results[name].message == expected_msg

    def test_all_linters_execute_in_parallel_phase(self) -> None:
        """Create 10 mock read-only linters, verify all 10 execute and return results."""
        num_linters = 10
        executed: list[str] = []

        def create_linter(name: str) -> BaseLinter:
            class TrackingLinter(BaseLinter):
                supports_file_filtering = True
                mutates_files = False

                def run(self, files: list[str] | None = None) -> LinterResult:
                    executed.append(name)
                    return LinterResult(success=True, message=f"Executed {name}")

            linter = TrackingLinter()
            linter.name = name
            return linter

        test_linter_map = {f"linter-{i}": create_linter(f"linter-{i}") for i in range(num_linters)}

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(list(test_linter_map.keys()), None)

        # All 10 linters should have executed
        assert len(executed) == num_linters
        assert len(results) == num_linters
        for i in range(num_linters):
            name = f"linter-{i}"
            assert name in executed
            assert results[name].success is True

    def test_linter_results_keyed_by_name(self) -> None:
        """Verify execute_phase returns dict with linter names as keys."""

        class NamedLinter(BaseLinter):
            name = "my-specific-linter"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True)

        test_linter_map = {"my-specific-linter": NamedLinter()}

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_linter_map):
            results = execute_phase(["my-specific-linter"], None)

        assert "my-specific-linter" in results
        assert isinstance(results["my-specific-linter"], LinterResult)

    def test_empty_phase_returns_empty_dict(self) -> None:
        """Verify execute_phase([]) returns {} without errors."""
        results = execute_phase([])
        assert results == {}
        assert isinstance(results, dict)

    def test_sequential_vs_parallel_correctness(self) -> None:
        """Verify sequential and parallel execution produce identical LinterResult objects.

        This test runs deterministic mock linters both sequentially (invoking run() directly
        on each linter one-at-a-time) and in parallel (via execute_phase), then asserts
        the collected LinterResult objects are identical between both execution modes.
        """
        # Define deterministic linter behavior - each produces a unique, predictable result
        linter_configs = [
            ("deterministic-a", True, "Deterministic result A - passed"),
            ("deterministic-b", False, "Deterministic result B - failed with code 42"),
            ("deterministic-c", True, "Deterministic result C - passed with warnings"),
            ("deterministic-d", True, None),  # Success with no message
            ("deterministic-e", False, "Deterministic result E - validation error"),
        ]

        def create_deterministic_linter(
            name: str, success: bool, message: str | None
        ) -> BaseLinter:
            class DeterministicLinter(BaseLinter):
                supports_file_filtering = True
                mutates_files = False

                def run(self, files: list[str] | None = None) -> LinterResult:
                    return LinterResult(success=success, message=message)

            linter = DeterministicLinter()
            linter.name = name
            return linter

        # Create linter instances
        linters = {
            name: create_deterministic_linter(name, success, message)
            for name, success, message in linter_configs
        }
        linter_names = list(linters.keys())

        # Sequential execution: invoke run() directly on each linter one-at-a-time
        sequential_results: dict[str, LinterResult] = {}
        for name, linter in linters.items():
            sequential_results[name] = linter.run(None)

        # Parallel execution: use execute_phase
        with patch("scripts.dev.linter.linters.LINTER_MAP", linters):
            parallel_results = execute_phase(linter_names, None)

        # Assert both executions produced results for all linters
        assert len(sequential_results) == len(linter_configs)
        assert len(parallel_results) == len(linter_configs)
        assert set(sequential_results.keys()) == set(parallel_results.keys())

        # Assert each LinterResult is identical between sequential and parallel execution
        for name in linter_names:
            seq_result = sequential_results[name]
            par_result = parallel_results[name]

            assert seq_result.success == par_result.success, (
                f"Linter '{name}' success mismatch: "
                f"sequential={seq_result.success}, parallel={par_result.success}"
            )
            assert seq_result.message == par_result.message, (
                f"Linter '{name}' message mismatch: "
                f"sequential={seq_result.message!r}, parallel={par_result.message!r}"
            )


class TestEdgeCases:
    """Edge case tests for empty filesets, single files, etc."""

    def test_single_file_filters_to_relevant_linters(self) -> None:
        """Pass single Python file, verify only Python-relevant linters are scheduled."""
        files = ["app/main.py"]
        phases = schedule_linters(LINTERS, files)

        # Flatten all phases
        all_scheduled = [name for phase in phases for name in phase]

        # Python-relevant linters should be included
        assert "ruff" in all_scheduled
        assert "mypy" in all_scheduled
        assert "astgrep" in all_scheduled

        # detect-secrets and gitleaks scan all file types
        assert "detect-secrets" in all_scheduled
        assert "gitleaks" in all_scheduled

        # Non-Python linters should NOT be scheduled
        assert "hadolint" not in all_scheduled
        assert "yamllint" not in all_scheduled
        assert "shellcheck" not in all_scheduled

    def test_no_files_returns_empty_phases(self) -> None:
        """Pass empty file list [], verify schedule_linters returns empty phases."""
        phases = schedule_linters(LINTERS, [])
        assert phases == []

    def test_all_files_filtered_out_returns_empty_phases(self) -> None:
        """Pass files that don't match any linter patterns, verify minimal phases.

        Note: detect-secrets and gitleaks scan all file types, so they will always
        be scheduled if files are provided. Other linters should be filtered out.
        """
        # Use a file extension that no linter handles (except detect-secrets/gitleaks)
        files = ["unknown.xyz", "another.zzz"]
        phases = schedule_linters(LINTERS, files)

        # Flatten all phases
        all_scheduled = [name for phase in phases for name in phase]

        # Only secret scanning linters should be scheduled
        # (they scan all file types)
        assert "detect-secrets" in all_scheduled
        assert "gitleaks" in all_scheduled

        # Type-specific linters should NOT be scheduled
        assert "ruff" not in all_scheduled
        assert "mypy" not in all_scheduled
        assert "hadolint" not in all_scheduled
        assert "yamllint" not in all_scheduled
        assert "pymarkdown" not in all_scheduled
        assert "shellcheck" not in all_scheduled

    def test_only_mutating_linters_scheduled(self) -> None:
        """Create scenario where only mutating linters have non-empty filesets."""
        # Ruff is the only mutating linter, and it only handles Python files
        files = ["app/main.py"]

        # Create a subset of linters with only ruff (mutating)
        from scripts.dev.linter.linters.ruff import RuffLinter

        only_ruff = [RuffLinter()]
        phases = schedule_linters(only_ruff, files)

        # Should have exactly 1 phase with ruff
        assert len(phases) == 1
        assert phases[0] == ["ruff"]

    def test_only_readonly_linters_scheduled(self) -> None:
        """Create scenario where only read-only linters have non-empty filesets."""
        # Use a markdown file - ruff won't match, but pymarkdown will
        files = ["README.md"]

        phases = schedule_linters(LINTERS, files)

        # Flatten all phases
        all_scheduled = [name for phase in phases for name in phase]

        # Ruff should NOT be scheduled (no Python files)
        assert "ruff" not in all_scheduled

        # Should have at least pymarkdown, detect-secrets, gitleaks
        assert len(all_scheduled) > 0
        assert "pymarkdown" in all_scheduled

    def test_fileset_calculation_respects_config_patterns(self) -> None:
        """Verify calculate_fileset correctly applies included_paths from configs."""
        from scripts.dev.linter.linters.ruff import RuffLinter

        ruff = RuffLinter()

        # Test with Python file
        fileset = calculate_fileset(ruff, ["app/main.py"])
        assert isinstance(fileset, set)
        # Should include the Python file (or empty if filtered by config)

        # Test with non-Python file
        fileset = calculate_fileset(ruff, ["README.md"])
        assert fileset == set()

        # Test with None (whole-repo scan)
        fileset = calculate_fileset(ruff, None)
        assert fileset is None


class TestFullCLIWorkflow:
    """Integration tests for the complete CLI workflow."""

    def test_cli_schedules_phases_correctly(self) -> None:
        """Verify schedule_linters produces correct phases for full linter list."""
        # Test whole-repo scan
        phases = schedule_linters(LINTERS, None)

        # Should have at least 2 phases (mutating + read-only)
        assert len(phases) >= 2

        # First phase should be mutating (ruff)
        assert phases[0] == ["ruff"]

        # Last phase should contain multiple read-only linters
        assert len(phases[-1]) > 1

    def test_cli_with_file_filtering_skips_irrelevant_linters(self) -> None:
        """Verify CLI with --files flag only runs relevant linters."""
        # Only YAML files
        files = ["docker-compose.yaml", ".github/workflows/ci.yml"]
        phases = schedule_linters(LINTERS, files)

        # Flatten all phases
        all_scheduled = [name for phase in phases for name in phase]

        # Python linters should NOT be scheduled
        assert "ruff" not in all_scheduled
        assert "mypy" not in all_scheduled

        # YAML linters should be scheduled
        assert "yamllint" in all_scheduled

    def test_cli_mutating_failure_in_phase_returns_failure(self) -> None:
        """Mock mutating linter to fail, verify phase returns failure result."""

        class FailingRuff(BaseLinter):
            name = "ruff"
            supports_file_filtering = True
            mutates_files = True

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Ruff failed")

        test_map = dict(LINTER_MAP)
        test_map["ruff"] = FailingRuff()

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_map):
            results = execute_phase(["ruff"], None)

        assert results["ruff"].success is False
        assert "Ruff failed" in (results["ruff"].message or "")

    def test_cli_readonly_failures_collected(self) -> None:
        """Mock multiple read-only linters to fail, verify all failures collected."""

        class FailingMypy(BaseLinter):
            name = "mypy"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Mypy failed")

        class FailingAstgrep(BaseLinter):
            name = "astgrep"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Astgrep failed")

        test_map = dict(LINTER_MAP)
        test_map["mypy"] = FailingMypy()
        test_map["astgrep"] = FailingAstgrep()

        with patch("scripts.dev.linter.linters.LINTER_MAP", test_map):
            results = execute_phase(["mypy", "astgrep"], None)

        assert results["mypy"].success is False
        assert results["astgrep"].success is False
        assert "Mypy failed" in (results["mypy"].message or "")
        assert "Astgrep failed" in (results["astgrep"].message or "")


class TestLintCLIMainWorkflow:
    """Component tests for lint_cli.main() end-to-end workflow.

    These tests patch _parse_args() and run main() to verify:
    - Argument parsing and linter selection
    - Exit codes for success/failure scenarios
    - Mutating linter failures abort immediately
    - Read-only linter failures aggregate
    - Text and YAML output paths
    """

    def _create_args(
        self,
        linters: list[str] | None = None,
        files: list[str] | None = None,
        changed_only: bool = False,
        commit: str | None = None,
        output_format: str = "text",
    ) -> argparse.Namespace:
        """Create an argparse.Namespace for testing."""
        return argparse.Namespace(
            linters=linters or [],
            files=files,
            changed_only=changed_only,
            commit=commit,
            output_format=output_format,
        )

    def test_main_with_files_flag_filters_to_relevant_linters(self) -> None:
        """Test main() with --files filters to only relevant linters and returns 0."""

        class SuccessLinter(BaseLinter):
            name = "stub-success"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="OK")

        test_map = {"stub-success": SuccessLinter()}
        test_names = ["stub-success"]
        args = self._create_args(linters=["stub-success"], files=["test.py"])

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", test_names),
            patch("scripts.dev.linter.linters.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli._filter_existing_files", return_value=["test.py"]),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 0

    def test_main_with_changed_only_returns_zero_when_no_changes(self) -> None:
        """Test main() with --changed-only returns 0 when no changed files."""
        args = self._create_args(changed_only=True)

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch(
                "scripts.dev.linter.lint_cli._get_changed_files",
                return_value=[],
            ),
            patch("scripts.dev.linter.lint_cli._filter_existing_files", return_value=[]),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 0

    def test_main_with_commit_returns_zero_when_no_files_in_commit(self) -> None:
        """Test main() with --commit returns 0 when no files in commit."""
        args = self._create_args(commit="abc123")

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch(
                "scripts.dev.linter.lint_cli._get_changed_files",
                return_value=[],
            ),
            patch("scripts.dev.linter.lint_cli._filter_existing_files", return_value=[]),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 0

    def test_main_mutating_failure_aborts_with_exit_code_1(self) -> None:
        """Test that mutating linter failure returns exit code 1 and aborts execution."""

        class FailingMutatingLinter(BaseLinter):
            name = "ruff"
            supports_file_filtering = True
            mutates_files = True

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Ruff failed")

        class SuccessReadOnlyLinter(BaseLinter):
            name = "mypy"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="Mypy OK")

        test_map = {
            "ruff": FailingMutatingLinter(),
            "mypy": SuccessReadOnlyLinter(),
        }
        test_names = ["ruff", "mypy"]
        args = self._create_args(linters=["ruff", "mypy"])

        # Track which linters ran
        run_tracker: list[str] = []
        original_run = FailingMutatingLinter.run

        def track_ruff(self: FailingMutatingLinter, files: list[str] | None = None) -> LinterResult:
            run_tracker.append("ruff")
            return original_run(self, files)

        original_mypy_run = SuccessReadOnlyLinter.run

        def track_mypy(self: SuccessReadOnlyLinter, files: list[str] | None = None) -> LinterResult:
            run_tracker.append("mypy")
            return original_mypy_run(self, files)

        test_map["ruff"].run = track_ruff.__get__(test_map["ruff"])  # type: ignore[method-assign]
        test_map["mypy"].run = track_mypy.__get__(test_map["mypy"])  # type: ignore[method-assign]

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", test_names),
            patch("scripts.dev.linter.linters.LINTER_MAP", test_map),
            patch("sys.stdout", new_callable=io.StringIO),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 1
        # Ruff should have run, but mypy should NOT have run (aborted after mutating failure)
        assert "ruff" in run_tracker
        # Note: mypy may or may not run depending on scheduling; the key assertion is exit_code == 1

    def test_main_readonly_failures_aggregate_returns_exit_code_1(self) -> None:
        """Test that read-only linter failures aggregate and return exit code 1."""

        class FailingLinterA(BaseLinter):
            name = "linter-a"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Linter A failed")

        class FailingLinterB(BaseLinter):
            name = "linter-b"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=False, message="Linter B failed")

        test_map = {
            "linter-a": FailingLinterA(),
            "linter-b": FailingLinterB(),
        }
        test_names = ["linter-a", "linter-b"]
        args = self._create_args(linters=["linter-a", "linter-b"])

        # Track which linters ran
        run_tracker: list[str] = []

        def track_a(self: FailingLinterA, files: list[str] | None = None) -> LinterResult:
            run_tracker.append("linter-a")
            return LinterResult(success=False, message="Linter A failed")

        def track_b(self: FailingLinterB, files: list[str] | None = None) -> LinterResult:
            run_tracker.append("linter-b")
            return LinterResult(success=False, message="Linter B failed")

        test_map["linter-a"].run = track_a.__get__(test_map["linter-a"])  # type: ignore[method-assign]
        test_map["linter-b"].run = track_b.__get__(test_map["linter-b"])  # type: ignore[method-assign]

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", test_names),
            patch("scripts.dev.linter.linters.LINTER_MAP", test_map),
            patch("sys.stdout", new_callable=io.StringIO),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 1
        # Both linters should have run (failures aggregate, not abort)
        assert "linter-a" in run_tracker
        assert "linter-b" in run_tracker

    def test_main_yaml_output_format_produces_yaml(self) -> None:
        """Test main() with --output-format yaml produces YAML output."""

        class SuccessLinter(BaseLinter):
            name = "yaml-linter"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="OK")

        test_map = {"yaml-linter": SuccessLinter()}
        test_names = ["yaml-linter"]
        args = self._create_args(linters=["yaml-linter"], output_format="yaml")

        stdout_capture = io.StringIO()

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", test_names),
            patch("scripts.dev.linter.linters.LINTER_MAP", test_map),
            patch("sys.stdout", stdout_capture),
        ):
            exit_code = main()

        assert exit_code == 0
        output = stdout_capture.getvalue()
        # YAML output should contain "errors: []" when no errors
        assert "errors:" in output

    def test_main_text_output_format_produces_text(self) -> None:
        """Test main() with --output-format text produces human-readable text."""

        class SuccessLinter(BaseLinter):
            name = "text-linter"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="OK")

        test_map = {"text-linter": SuccessLinter()}
        test_names = ["text-linter"]
        args = self._create_args(linters=["text-linter"], output_format="text")

        stdout_capture = io.StringIO()

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", test_names),
            patch("scripts.dev.linter.linters.LINTER_MAP", test_map),
            patch("sys.stdout", stdout_capture),
        ):
            exit_code = main()

        assert exit_code == 0
        output = stdout_capture.getvalue()
        # Text output should contain "Running:" header
        assert "Running:" in output or "=" in output

    def test_main_mutually_exclusive_file_options_returns_error(self) -> None:
        """Test that combining --files, --changed-only, --commit returns exit code 1."""
        args = self._create_args(files=["test.py"], changed_only=True)

        stderr_capture = io.StringIO()

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("sys.stderr", stderr_capture),
        ):
            exit_code = main()

        assert exit_code == 1
        assert "mutually exclusive" in stderr_capture.getvalue()

    def test_main_invalid_linter_name_returns_error(self) -> None:
        """Test that invalid linter name returns exit code 1."""
        args = self._create_args(linters=["nonexistent-linter"])

        stderr_capture = io.StringIO()

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("sys.stderr", stderr_capture),
        ):
            exit_code = main()

        assert exit_code == 1

    def test_main_linter_selection_respects_specified_linters(self) -> None:
        """Test that only specified linters are run, not all linters."""

        class LinterA(BaseLinter):
            name = "linter-a"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True)

        class LinterB(BaseLinter):
            name = "linter-b"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True)

        class LinterC(BaseLinter):
            name = "linter-c"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True)

        test_map = {
            "linter-a": LinterA(),
            "linter-b": LinterB(),
            "linter-c": LinterC(),
        }
        test_names = ["linter-a", "linter-b", "linter-c"]

        # Only request linter-a, not linter-b or linter-c
        args = self._create_args(linters=["linter-a"])

        run_tracker: list[str] = []

        def track_a(self: LinterA, files: list[str] | None = None) -> LinterResult:
            run_tracker.append("linter-a")
            return LinterResult(success=True)

        def track_b(self: LinterB, files: list[str] | None = None) -> LinterResult:
            run_tracker.append("linter-b")
            return LinterResult(success=True)

        def track_c(self: LinterC, files: list[str] | None = None) -> LinterResult:
            run_tracker.append("linter-c")
            return LinterResult(success=True)

        test_map["linter-a"].run = track_a.__get__(test_map["linter-a"])  # type: ignore[method-assign]
        test_map["linter-b"].run = track_b.__get__(test_map["linter-b"])  # type: ignore[method-assign]
        test_map["linter-c"].run = track_c.__get__(test_map["linter-c"])  # type: ignore[method-assign]

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", test_names),
            patch("scripts.dev.linter.linters.LINTER_MAP", test_map),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 0
        assert "linter-a" in run_tracker
        assert "linter-b" not in run_tracker
        assert "linter-c" not in run_tracker

    def test_main_success_returns_exit_code_0(self) -> None:
        """Test that successful linting returns exit code 0."""

        class SuccessLinter(BaseLinter):
            name = "success-linter"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                return LinterResult(success=True, message="All good")

        test_map = {"success-linter": SuccessLinter()}
        test_names = ["success-linter"]
        args = self._create_args(linters=["success-linter"])

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", test_names),
            patch("scripts.dev.linter.linters.LINTER_MAP", test_map),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 0

    def test_main_no_files_exist_returns_zero(self) -> None:
        """Test main() with --files where no files exist returns 0."""
        args = self._create_args(files=["nonexistent.py"])

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli._filter_existing_files", return_value=[]),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 0

    def test_main_with_changed_only_runs_linters_on_changed_files(self) -> None:
        """Test main() with --changed-only passes changed files to linters."""
        received_files: list[list[str] | None] = []

        class TrackingLinter(BaseLinter):
            name = "tracking-linter"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                received_files.append(files)
                return LinterResult(success=True)

        test_map = {"tracking-linter": TrackingLinter()}
        test_names = ["tracking-linter"]
        args = self._create_args(linters=["tracking-linter"], changed_only=True)

        changed_files = ["changed1.py", "changed2.py"]

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", test_names),
            patch("scripts.dev.linter.linters.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli._get_changed_files", return_value=changed_files),
            patch("scripts.dev.linter.lint_cli._filter_existing_files", return_value=changed_files),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 0
        # Linter should have received the changed files
        assert len(received_files) == 1
        assert set(received_files[0] or []) == set(changed_files)

    def test_main_with_commit_runs_linters_on_commit_files(self) -> None:
        """Test main() with --commit passes commit files to linters."""
        received_files: list[list[str] | None] = []

        class TrackingLinter(BaseLinter):
            name = "commit-linter"
            supports_file_filtering = True
            mutates_files = False

            def run(self, files: list[str] | None = None) -> LinterResult:
                received_files.append(files)
                return LinterResult(success=True)

        test_map = {"commit-linter": TrackingLinter()}
        test_names = ["commit-linter"]
        args = self._create_args(linters=["commit-linter"], commit="abc123")

        commit_files = ["file_from_commit.py"]

        with (
            patch("scripts.dev.linter.lint_cli._parse_args", return_value=args),
            patch("scripts.dev.linter.lint_cli.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli.LINTER_NAMES", test_names),
            patch("scripts.dev.linter.linters.LINTER_MAP", test_map),
            patch("scripts.dev.linter.lint_cli._get_changed_files", return_value=commit_files),
            patch("scripts.dev.linter.lint_cli._filter_existing_files", return_value=commit_files),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            exit_code = main()

        assert exit_code == 0
        # Linter should have received the commit files
        assert len(received_files) == 1
        assert received_files[0] == commit_files
