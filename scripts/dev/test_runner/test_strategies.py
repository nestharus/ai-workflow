"""Test strategy implementations for different coverage types.

This module defines the Strategy pattern for test execution:
- TestStrategy: Abstract base class defining the interface
- LineBranchTestStrategy: For unit, component, and scripts tiers (line/branch coverage)
- IntegrationTestStrategy: For integration tier (use-case coverage)
- create_strategy: Factory function to instantiate the appropriate strategy

IMPORT STRUCTURE (to avoid circular dependencies):
- This module imports dataclasses and helpers FROM test_coverage.py
- This module imports coverage_db module
- coverage_db.py imports ONLY dataclasses from test_coverage.py (not this module)

ARCHITECTURAL INVARIANTS:

1. PYTEST COMMAND CONSTRUCTION: Each concrete strategy's `run_tests()` method is
   the SINGLE LOCATION for pytest command construction for that tier. The
   orchestrator (`main()`) must NOT construct pytest commands directly.

2. TIER_PASS OWNERSHIP: Each strategy's `build_summary()` method FULLY OWNS the
   computation of `tier_pass`. The value is determined entirely within the strategy
   based on coverage thresholds and test results - `main()` must NOT compute or
   modify `tier_pass`.

3. VALIDATION OWNERSHIP: Each strategy's `validate()` method owns threshold checking.
   `main()` must NOT call `validate_line_branch_coverage()` or
   `validate_usecase_coverage()` directly.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from scripts.dev.test_runner import coverage_db
from scripts.dev.test_runner.junit_parser import TestSummary, parse_junit_xml
from scripts.dev.test_runner.test_coverage import (
    CoverageResult,
    FunctionCoverage,
    TestTierConfig,
    UseCase,
    UseCaseCoverageResult,
    _calculate_function_coverage,
    _is_in_service_layer,
    _is_private_function,
    _run_command,
    _scan_tests_for_usecases,
    calculate_usecase_coverage,
)


class TestStrategy(ABC):
    """Abstract base class for test tier execution strategies.

    SINGLE-USE INSTANCES:
        Each strategy instance is designed for a single tier invocation. Once the
        lifecycle (run_tests -> collect_results -> validate -> build_summary) has
        been executed, the instance should be discarded. Do NOT reuse strategy
        instances across multiple test runs, as internal state from previous runs
        may cause incorrect results.

    Concrete implementations must follow this lifecycle:
    1. `__init__()` - Initialize with config and paths
    2. run_tests() - Execute tests, populate self.test_summary (optional)
    3. collect_results() - Process coverage, populate self.coverage_result or
       self.usecase_result
    4. validate() - Check thresholds using internal state, return failures
    5. build_summary() - Build summary dict using internal state

    Lifecycle Ordering Guarantees:
        Methods MUST be called in the following order:
        1. run_tests() must be called before collect_results()
        2. collect_results() must complete successfully before validate() or
           build_summary() are called

        If methods are called out of order or required internal state is missing,
        implementations MUST raise RuntimeError with a descriptive message.

    State Guardrails:
        To prevent stale or partially-populated state from causing incorrect behavior:
        - Subclasses MUST initialize all mutable internal attributes in `__init__()`
        - Subclasses MUST track lifecycle progress via private boolean flags
          (_tests_ran, _results_collected)
        - collect_results() MUST raise RuntimeError if _tests_ran is False
        - validate() and build_summary() MUST raise RuntimeError if
          _results_collected is False
        - validate() MUST reinitialize self._failures to an empty list at the start
          of each call to prevent accumulation of stale failure messages

    Failure-Mode Semantics:
        When pytest exits with a non-zero return code (test failures):
        - Strategies MUST still attempt to collect whatever results are available
        - JUnit XML and coverage data should be parsed if present, even after test
          failures
        - validate() should still return coverage threshold failures (if any)
        - Test failure reporting is handled by main() via database queries, NOT by
          validate()

        Catastrophic parse failures (missing or malformed JSON/XML):
        - If JUnit XML or coverage JSON files are missing or malformed,
          collect_results() MAY raise an exception
        - These exceptions should propagate up to main() for a hard failure
        - Strategies MUST NOT silently swallow parse errors and return inconsistent
          state

    Internal State Attributes (set by subclasses):
        test_summary: Optional TestSummary from JUnit XML parsing
        coverage_result: CoverageResult for line/branch strategies (or None)
        usecase_result: UseCaseCoverageResult for usecase strategies (or None)
        _failures: List of failure messages populated by validate()
    """

    def __init__(self, config: TestTierConfig, coverage_db_path: Path, repo_root: Path) -> None:
        """Initialize strategy with configuration.

        Args:
            config: Test tier configuration
            coverage_db_path: Path to coverage database
            repo_root: Repository root path

        Note:
            Each strategy instance is single-use. Do not reuse instances across
            multiple tier invocations.
        """
        self.config = config
        self.coverage_db_path = coverage_db_path
        self.repo_root = repo_root
        # Internal state populated by run_tests() and collect_results()
        # All mutable attributes must be explicitly initialized to prevent stale state
        self.test_summary: TestSummary | None = None
        self.coverage_result: CoverageResult | None = None
        self.usecase_result: UseCaseCoverageResult | None = None
        self._failures: list[str] = []
        # Lifecycle tracking flags
        self._tests_ran: bool = False
        self._results_collected: bool = False

    @abstractmethod
    def run_tests(self) -> None:
        """Execute tests with tier-specific configuration.

        Side effects:
            - Runs pytest with appropriate arguments
            - Writes test results to coverage_db
            - Populates self.test_summary with parsed JUnit XML data
        """

    @abstractmethod
    def collect_results(self) -> None:
        """Process coverage data and compute metrics.

        Side effects:
            - For line/branch: Populates self.coverage_result, writes function
              coverage to db
            - For usecase: Populates self.usecase_result, writes usecase coverage
              to db
        """

    @abstractmethod
    def validate(self) -> list[str]:
        """Check thresholds and return failure messages.

        Reads from internal state (self.coverage_result or self.usecase_result).

        Returns:
            List of failure message strings (empty if validation passes)
        """

    @abstractmethod
    def build_summary(self) -> dict[str, Any]:
        """Build tier summary dictionary for database.

        Reads from internal state to construct summary.

        Returns:
            Dictionary with tier summary data for coverage_db.write_tier_summary()
        """


class LineBranchTestStrategy(TestStrategy):
    """Strategy for line/branch coverage tiers (unit, component, scripts).

    SINGLE-USE INSTANCES:
        Each strategy instance is designed for a single tier invocation. Do not
        reuse instances across multiple test runs.

    This strategy handles tiers with coverage_type="line_branch" and is responsible
    for:
    - Building pytest commands with coverage flags (--cov, --cov-branch, etc.)
    - Executing tests via _run_command()
    - Parsing JUnit XML for test results
    - Generating JSON coverage reports
    - Calculating per-function coverage metrics
    - Writing function coverage to the database
    - Validating coverage thresholds
    """

    def __init__(
        self,
        config: TestTierConfig,
        coverage_db_path: Path,
        repo_root: Path,
        first_tier: bool,
    ) -> None:
        """Initialize LineBranchTestStrategy.

        Args:
            config: Test tier configuration
            coverage_db_path: Path to coverage database
            repo_root: Repository root path
            first_tier: If True, this is the first tier (don't use --cov-append)
        """
        super().__init__(config, coverage_db_path, repo_root)
        self.first_tier = first_tier

    def run_tests(self) -> None:
        """Execute tests with coverage instrumentation.

        Side effects:
            - Runs pytest with coverage flags
            - Parses JUnit XML and writes test results to coverage_db
            - Populates self.test_summary with parsed JUnit XML data
            - Sets self._tests_ran = True

        Expected Behavior:
            - pytest command construction (--cov, --cov-branch, --cov-context=test, etc.)
            - COVERAGE_FILE environment variable pointing to .coverage/data
            - --cov-append logic for non-first tiers
            - JUnit XML path generation and parsing
            - Database writes via coverage_db.write_test_result()
            - Console logging format (separator lines, tier name, source paths)
        """
        # Set up junit XML output path
        junit_xml_path = self.coverage_db_path.parent / f"junit_{self.config.name}.xml"

        # Set up coverage data file path (inside .coverage directory)
        coverage_data_file = self.coverage_db_path.parent / "data"
        cov_env = {"COVERAGE_FILE": str(coverage_data_file)}

        # Build pytest command with coverage
        cov_args = [f"--cov={path}" for path in self.config.source_paths]
        cmd = [
            "uv",
            "run",
            "python",
            "-m",
            "pytest",
            self.config.test_path,
            *cov_args,
            "--cov-branch",
            "--cov-context=test",
            "--cov-report=term-missing",
            "--cov-fail-under=0",
            f"--junitxml={junit_xml_path}",
            "-q",
            "-p",
            "no:randomly",
        ]

        # Add --cov-append for all tiers except the first one
        if not self.first_tier:
            cmd.append("--cov-append")

        print(f"\n{'=' * 70}")
        print(f"Running {self.config.name} tests: {self.config.test_path}")
        print(f"Measuring coverage for: {', '.join(self.config.source_paths)}")
        print("=" * 70)

        result = _run_command(cmd, capture=False, env=cov_env)

        # Parse junit XML to extract test results
        if junit_xml_path.exists():
            try:
                test_results, test_summary = parse_junit_xml(junit_xml_path)
                # Write test results to database
                for test_result in test_results:
                    coverage_db.write_test_result(
                        self.coverage_db_path,
                        tier=self.config.name,
                        test_name=test_result.test_name,
                        status=test_result.status,
                        duration=test_result.duration,
                        message=test_result.message,
                        traceback=test_result.traceback,
                    )
                self.test_summary = test_summary
            except Exception as e:
                print(f"\nWARNING: Failed to parse junit XML: {e!r}")

        if result.returncode != 0:
            print(
                f"\nWARNING: {self.config.name} tests had failures (exit code {result.returncode})"
            )

        self._tests_ran = True

    def collect_results(self) -> None:
        """Process coverage data and compute per-function metrics.

        Side effects:
            - Generates JSON coverage report
            - Calculates per-function coverage
            - Writes tier config and function coverage to database
            - Populates self.coverage_result
            - Sets self._results_collected = True

        Expected Behavior:
            - JSON report generation via coverage json command
            - Per-file iteration over coverage_data["files"]
            - service_layer_only filter applied before _calculate_function_coverage
            - skip_private_functions filter applied to individual functions
            - Database writes via coverage_db.write_tier_config() and
              write_function_coverage()
            - CoverageResult construction with exact field mapping from totals

        Raises:
            RuntimeError: If run_tests() was not called first
        """
        if not self._tests_ran:
            msg = "run_tests() must be called before collect_results()"
            raise RuntimeError(msg)

        # Set up paths
        json_output_path = self.repo_root / ".coverage" / f"temp_{self.config.name}.json"
        json_output_path.parent.mkdir(parents=True, exist_ok=True)

        coverage_data_file = self.coverage_db_path.parent / "data"
        cov_env = {"COVERAGE_FILE": str(coverage_data_file)}

        # Generate JSON report for this tier's coverage
        cov_report_cmd = [
            "uv",
            "run",
            "python",
            "-m",
            "coverage",
            "json",
            "-o",
            str(json_output_path),
        ]
        _run_command(cov_report_cmd, capture=True, env=cov_env)

        if not json_output_path.exists():
            msg = f"Coverage JSON report could not be generated: {json_output_path}"
            raise RuntimeError(msg)

        with json_output_path.open() as f:
            coverage_data = json.load(f)

        totals = coverage_data.get("totals", {})

        # Calculate function-level coverage
        all_functions: dict[str, dict[str, Any]] = {}
        all_function_coverages: list[FunctionCoverage] = []
        files_data = coverage_data.get("files", {})

        for file_path in files_data:
            # For component tests, only include service layer files
            if self.config.service_layer_only and not _is_in_service_layer(file_path):
                continue

            func_coverages = _calculate_function_coverage(
                file_path,
                coverage_data,
                self.repo_root,
                exclude_class_fields=self.config.exclude_class_fields,
            )
            for fc in func_coverages:
                # Skip private functions if configured
                if self.config.skip_private_functions and _is_private_function(fc.name):
                    continue

                # For service-layer-only mode, skip non-service files
                if self.config.service_layer_only and not _is_in_service_layer(fc.file_path):
                    continue

                all_function_coverages.append(fc)
                key = f"{fc.file_path}::{fc.name}"
                all_functions[key] = {
                    "name": fc.name,
                    "file": fc.file_path,
                    "start_line": fc.start_line,
                    "end_line": fc.end_line,
                    "line_coverage": fc.line_coverage_pct,
                    "branch_coverage": fc.branch_coverage_pct,
                    "missing_lines": fc.missing_lines,
                    "missing_branches": fc.missing_branches,
                }

        # Write tier configuration to database
        coverage_db.write_tier_config(self.coverage_db_path, self.config.name, self.config)

        # Write function coverage to database with pass/fail flags
        if all_function_coverages:
            coverage_db.write_function_coverage(
                self.coverage_db_path,
                self.config.name,
                all_function_coverages,
                self.config.min_line_per_function,
                self.config.min_branch_per_function,
            )

        # Clean up temporary JSON file
        json_output_path.unlink(missing_ok=True)

        self.coverage_result = CoverageResult(
            suite_name=self.config.name,
            total_lines=totals.get("num_statements", 0),
            covered_lines=totals.get("covered_lines", 0),
            missing_lines=totals.get("missing_lines", 0),
            line_coverage_pct=totals.get("percent_covered", 0.0),
            total_branches=totals.get("num_branches", 0),
            covered_branches=totals.get("covered_branches", 0),
            missing_branches=totals.get("num_partial_branches", 0)
            + totals.get("missing_branches", 0),
            branch_coverage_pct=totals.get("percent_covered_branches", 0.0)
            if "percent_covered_branches" in totals
            else 0.0,
            files=files_data,
            functions=all_functions,
        )

        self._results_collected = True

    def validate(self) -> list[str]:
        """Check per-function line and branch coverage thresholds.

        PARITY NOTE: This method encapsulates the exact logic of
        validate_line_branch_coverage() from test_coverage.py (lines 911-948),
        reading from self.coverage_result and self.config instead of parameters.
        Message formats and filtering must remain identical.

        Returns:
            List of failure message strings (empty if validation passes)

        Raises:
            RuntimeError: If collect_results() was not called first or failed
        """
        # Reinitialize to prevent stale accumulation from repeated calls
        self._failures = []

        # Lifecycle check
        if not self._results_collected:
            msg = "collect_results() must be called before validate()"
            raise RuntimeError(msg)
        if self.coverage_result is None:
            msg = "coverage_result is None - collect_results() did not complete successfully"
            raise RuntimeError(msg)

        # Inline logic from validate_line_branch_coverage() (lines 921-946)
        for func_key, func_data in self.coverage_result.functions.items():
            func_name = func_data["name"]
            file_path = func_data["file"]

            # Skip private functions if configured
            if self.config.skip_private_functions and _is_private_function(func_name):
                continue

            # For service-layer-only mode, skip non-service files
            if self.config.service_layer_only and not _is_in_service_layer(file_path):
                continue

            line_cov = func_data["line_coverage"]
            branch_cov = func_data["branch_coverage"]

            # Line coverage failure message - EXACT format
            if line_cov < self.config.min_line_per_function:
                self._failures.append(
                    f"{self.config.name}: Function {func_key} line coverage "
                    f"{line_cov:.1f}% < {self.config.min_line_per_function:.1f}% minimum"
                )

            # Branch coverage failure message - EXACT format
            if branch_cov < self.config.min_branch_per_function and func_data.get(
                "missing_branches"
            ):
                self._failures.append(
                    f"{self.config.name}: Function {func_key} branch coverage "
                    f"{branch_cov:.1f}% < {self.config.min_branch_per_function:.1f}% minimum"
                )

        return self._failures

    def build_summary(self) -> dict[str, Any]:
        """Build tier summary dictionary for database.

        OWNERSHIP: This method FULLY OWNS the computation of:
        - total_functions, passing_functions, failing_functions
        - overall_line_pct, overall_branch_pct
        - total_tests, tests_passed, tests_failed
        - tier_pass

        main() must NOT recompute any of these values. The returned dict
        is passed directly to coverage_db.write_tier_summary().

        Returns:
            Dictionary matching cc_tier_summary schema exactly.

        Raises:
            RuntimeError: If collect_results() was not called first or failed
        """
        if not self._results_collected:
            msg = "collect_results() must be called before build_summary()"
            raise RuntimeError(msg)
        if self.coverage_result is None:
            msg = "coverage_result is None - collect_results() did not complete successfully"
            raise RuntimeError(msg)

        # Compute function pass/fail counts
        # A function passes if it meets BOTH line AND branch thresholds
        passing_funcs = 0
        for func_data in self.coverage_result.functions.values():
            line_passes = func_data["line_coverage"] >= self.config.min_line_per_function
            branch_passes = func_data["branch_coverage"] >= self.config.min_branch_per_function
            if line_passes and branch_passes:
                passing_funcs += 1

        total_funcs = len(self.coverage_result.functions)
        failing_funcs = total_funcs - passing_funcs

        # Derive test counts from self.test_summary (parsed from JUnit XML)
        total_tests = self.test_summary.total if self.test_summary else 0
        tests_passed = self.test_summary.passed if self.test_summary else 0
        tests_failed = (
            (self.test_summary.failed + self.test_summary.errors) if self.test_summary else 0
        )

        # -------------------------------------------------------------------------
        # TIER_PASS OWNERSHIP: This value is computed ENTIRELY within the strategy.
        # main() must NOT compute or modify tier_pass - it receives this dict as
        # opaque data and passes it directly to coverage_db.write_tier_summary().
        # -------------------------------------------------------------------------
        # Determine tier_pass: 1 only if NO coverage failures AND NO test failures
        #
        # NOTE: tier_pass depends on self._failures, which is populated by validate().
        # When main() runs with --no-validate, it skips calling validate(), so
        # self._failures remains empty. In that case, tier_pass will treat coverage
        # as passing unless tests fail. This preserves the legacy semantics where
        # --no-validate intentionally skips coverage threshold enforcement.
        has_coverage_failures = len(self._failures) > 0
        has_test_failures = tests_failed > 0
        tier_pass = 1 if not has_coverage_failures and not has_test_failures else 0

        return {
            "coverage_type": self.config.coverage_type,
            "total_functions": total_funcs,
            "passing_functions": passing_funcs,
            "failing_functions": failing_funcs,
            "overall_line_pct": self.coverage_result.line_coverage_pct,
            "overall_branch_pct": self.coverage_result.branch_coverage_pct,
            "total_tests": total_tests,
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "tier_pass": tier_pass,
            # Usecase fields default to 0 for line_branch tiers
            "total_usecases": 0,
            "usecases_covered": 0,
        }


class IntegrationTestStrategy(TestStrategy):
    """Strategy for use-case coverage tiers (integration).

    SINGLE-USE INSTANCES:
        Each strategy instance is designed for a single tier invocation. Do not
        reuse instances across multiple test runs.

    This strategy handles tiers with coverage_type="usecase" and is responsible for:
    - Building pytest commands WITHOUT coverage instrumentation
    - Executing tests via _run_command()
    - Scanning test files for @pytest.mark.usecase markers
    - Writing use-case coverage to the database
    - Validating use-case coverage thresholds

    NOTE: This strategy does NOT track JUnit summaries (self.test_summary remains
    None). Use-case coverage is the primary metric for integration tiers.

    SCANNING API: This strategy uses :func:`test_coverage._scan_tests_for_usecases`
    internally. That function returns richer metadata (test file paths and function
    names) than the legacy :func:`test_coverage.collect_covered_usecases`. If you
    need manual use-case scanning outside this strategy, prefer
    ``_scan_tests_for_usecases()`` for writing to ``coverage_db``.
    """

    def __init__(
        self,
        config: TestTierConfig,
        coverage_db_path: Path,
        repo_root: Path,
        use_cases: list[UseCase],
    ) -> None:
        """Initialize IntegrationTestStrategy.

        Args:
            config: Test tier configuration
            coverage_db_path: Path to coverage database
            repo_root: Repository root path
            use_cases: List of use cases from the registry
        """
        super().__init__(config, coverage_db_path, repo_root)
        self.use_cases = use_cases

    def run_tests(self) -> None:
        """Execute integration tests without coverage instrumentation.

        Side effects:
            - Runs pytest WITHOUT coverage flags
            - Writes tier config to database
            - Sets self._tests_ran = True
            - self.test_summary remains None (by design)

        Expected Behavior:
            - pytest command construction (test_path, -v, -p no:randomly, NO --cov flags)
            - Console logging format (separator lines, tier name, test_path)
            - Database write via coverage_db.write_tier_config()
        """
        # Build pytest command - NO coverage flags
        cmd = [
            "uv",
            "run",
            "python",
            "-m",
            "pytest",
            self.config.test_path,
            "-v",
            "-p",
            "no:randomly",
        ]

        print(f"\n{'=' * 70}")
        print(f"Running {self.config.name} tests: {self.config.test_path}")
        print("=" * 70)

        _run_command(cmd, capture=False)

        # Write tier config for usecase tiers
        coverage_db.write_tier_config(self.coverage_db_path, self.config.name, self.config)

        # NOTE: IntegrationTestStrategy does NOT track JUnit summaries.
        # self.test_summary remains None by design.

        self._tests_ran = True

    def collect_results(self) -> None:
        """Scan test files for use-case markers and calculate coverage.

        Side effects:
            - Scans test files for @pytest.mark.usecase markers
            - Writes use-case coverage to database
            - Populates self.usecase_result
            - Sets self._results_collected = True

        Expected Behavior:
            - _scan_tests_for_usecases() call with (config.test_path, repo_root)
            - Deriving covered_ids from usecase_to_tests.keys()
            - Per-use-case DB write semantics:
              * Covered: test_file and test_function from usecase_to_tests[uc.id][0]
              * Uncovered: test_file=None, test_function=None
            - calculate_usecase_coverage() call AFTER DB writes

        Raises:
            RuntimeError: If run_tests() was not called first
        """
        if not self._tests_ran:
            msg = "run_tests() must be called before collect_results()"
            raise RuntimeError(msg)

        # Scan test files for usecase markers with test function information
        usecase_to_tests = _scan_tests_for_usecases(self.config.test_path, self.repo_root)
        covered_ids = set(usecase_to_tests.keys())

        # Write use case coverage to database for each use case in this tier
        tier_use_cases = [uc for uc in self.use_cases if uc.test_tier == self.config.name]
        for uc in tier_use_cases:
            if uc.id in usecase_to_tests:
                # Use case is covered - get first test location
                test_info = usecase_to_tests[uc.id][0]
                coverage_db.write_usecase_coverage(
                    self.coverage_db_path,
                    uc.id,
                    covered=True,
                    test_file=test_info["file"],
                    test_function=test_info["test_function"],
                )
            else:
                # Use case is not covered
                coverage_db.write_usecase_coverage(
                    self.coverage_db_path,
                    uc.id,
                    covered=False,
                    test_file=None,
                    test_function=None,
                )

        # Calculate use-case coverage from detected markers
        self.usecase_result = calculate_usecase_coverage(
            self.config.name, self.use_cases, covered_ids
        )

        self._results_collected = True

    def validate(self) -> list[str]:
        """Check use-case coverage threshold.

        PARITY NOTE: This method encapsulates the exact logic of
        validate_usecase_coverage() from test_coverage.py (lines 951-971),
        reading from self.usecase_result and self.config instead of parameters.
        Message formats and truncation must remain identical.

        Returns:
            List of failure message strings (empty if validation passes)

        Raises:
            RuntimeError: If collect_results() was not called first or failed
        """
        # Reinitialize to prevent stale accumulation from repeated calls
        self._failures = []

        # Lifecycle check
        if not self._results_collected:
            msg = "collect_results() must be called before validate()"
            raise RuntimeError(msg)
        if self.usecase_result is None:
            msg = "usecase_result is None - collect_results() did not complete successfully"
            raise RuntimeError(msg)

        # Inline logic from validate_usecase_coverage() (lines 961-969)
        if self.usecase_result.coverage_pct < self.config.min_usecase:
            # Main failure message - EXACT format
            self._failures.append(
                f"{self.config.name}: Use-case coverage {self.usecase_result.coverage_pct:.1f}% "
                f"< {self.config.min_usecase:.1f}% minimum"
            )
            # List uncovered use cases - truncated to 10 items
            for uc_id in self.usecase_result.uncovered_cases[:10]:
                self._failures.append(f"  - Uncovered: {uc_id}")
            # "... and N more" suffix when >10 uncovered
            if len(self.usecase_result.uncovered_cases) > 10:
                self._failures.append(
                    f"  ... and {len(self.usecase_result.uncovered_cases) - 10} more"
                )

        return self._failures

    def build_summary(self) -> dict[str, Any]:
        """Build tier summary dictionary for database.

        OWNERSHIP: This method FULLY OWNS the computation of:
        - total_usecases, usecases_covered
        - tier_pass

        main() must NOT recompute any of these values. The returned dict
        is passed directly to coverage_db.write_tier_summary().

        Returns:
            Dictionary matching cc_tier_summary schema exactly.

        Raises:
            RuntimeError: If collect_results() was not called first or failed
        """
        if not self._results_collected:
            msg = "collect_results() must be called before build_summary()"
            raise RuntimeError(msg)
        if self.usecase_result is None:
            msg = "usecase_result is None - collect_results() did not complete successfully"
            raise RuntimeError(msg)

        # -------------------------------------------------------------------------
        # TIER_PASS OWNERSHIP: This value is computed ENTIRELY within the strategy.
        # main() must NOT compute or modify tier_pass - it receives this dict as
        # opaque data and passes it directly to coverage_db.write_tier_summary().
        # -------------------------------------------------------------------------
        # Determine tier_pass: 1 only if NO coverage failures exist
        #
        # NOTE: tier_pass depends on self._failures, which is populated by validate().
        # When main() runs with --no-validate, it skips calling validate(), so
        # self._failures remains empty. In that case, tier_pass will treat coverage
        # as passing. This aligns with LineBranchTestStrategy's semantics where
        # --no-validate intentionally skips coverage threshold enforcement.
        has_coverage_failures = len(self._failures) > 0
        tier_pass = 1 if not has_coverage_failures else 0

        return {
            "coverage_type": self.config.coverage_type,
            "total_usecases": self.usecase_result.total_cases,
            "usecases_covered": self.usecase_result.covered_cases,
            "tier_pass": tier_pass,
            # Line/branch fields default to 0/None for usecase tiers
            "total_functions": 0,
            "passing_functions": 0,
            "failing_functions": 0,
            "overall_line_pct": None,
            "overall_branch_pct": None,
            "total_tests": 0,
            "tests_passed": 0,
            "tests_failed": 0,
        }


def create_strategy(
    config: TestTierConfig,
    coverage_db_path: Path,
    repo_root: Path,
    first_tier: bool = False,
    use_cases: list[UseCase] | None = None,
) -> TestStrategy:
    """Create appropriate strategy based on coverage type.

    This factory function examines the config.coverage_type and instantiates
    the correct strategy class. main() should use this function rather than
    instantiating strategies directly.

    Args:
        config: Test tier configuration
        coverage_db_path: Path to coverage database
        repo_root: Repository root path
        first_tier: If True, this is the first tier (don't use --cov-append).
            Only relevant for LineBranchTestStrategy.
        use_cases: List of use cases (required for usecase coverage type).
            Only relevant for IntegrationTestStrategy.

    Returns:
        TestStrategy instance for the given coverage type

    Raises:
        ValueError: If coverage_type is unknown or if use_cases is not provided
            for coverage_type='usecase'
    """
    if config.coverage_type == "line_branch":
        return LineBranchTestStrategy(config, coverage_db_path, repo_root, first_tier)
    elif config.coverage_type == "usecase":
        if use_cases is None:
            raise ValueError("use_cases must be provided for coverage_type='usecase'")
        return IntegrationTestStrategy(config, coverage_db_path, repo_root, use_cases)
    else:
        msg = f"Unknown coverage type: {config.coverage_type}"
        raise ValueError(msg)
