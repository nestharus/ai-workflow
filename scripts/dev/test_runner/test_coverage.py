"""Test coverage runner with separate reporting for different test tiers.

This module provides:
- Separate coverage tracking for 4 test tiers (unit, component, integration, e2e)
- Separate coverage between scripts/tests/ and tests/
- Per-function line and branch coverage validation
- Use-case coverage tracking for integration and e2e tests

Test Tier Coverage Requirements:
- Unit tests (tests/unit/): 80% line/branch per function across app/ (excluding class fields)
- Component tests (tests/component/ or tests/unit/ with service focus): 80% line/branch
  per function for app/services/ only
- Integration tests (tests/integration/): 100% use-case coverage
- E2E tests (tests/e2e/): 100% use-case coverage
- Scripts tests (scripts/tests/): Coverage for scripts/ and tools/

Coverage Calculation:
- Per-function coverage: Each function must individually meet the threshold
- Class fields (Pydantic model fields in contracts) are excluded
- Files with no functions can have 0% coverage (valid)
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.dev.test_runner.redundant_test_detector import (
    RedundantTestResult,
    detect_redundant_tests,
    format_redundant_test_report,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Coverage configuration defaults
# These can be overridden via command line arguments
# Per-function thresholds are intentionally lower than overall thresholds
# because some infrastructure code is excluded from unit testing
DEFAULT_MIN_LINE_COVERAGE = 80.0
DEFAULT_MIN_BRANCH_COVERAGE = 70.0
DEFAULT_MIN_FUNCTION_LINE_COVERAGE = 60.0
DEFAULT_MIN_FUNCTION_BRANCH_COVERAGE = 50.0
DEFAULT_USECASE_COVERAGE = 100.0

# Service layer path pattern (relative to repo root)
SERVICE_LAYER_PATH = "app/services"

# Infrastructure paths that are excluded from unit test coverage validation
# These modules require external dependencies and are tested via integration/e2e tests
INFRASTRUCTURE_PATHS = (
    "app/infrastructure/",
    "app/repositories/",
    "app/main.py",
)

# HTTP handling paths excluded from unit test coverage - tested via integration tests
# These involve HTTP request/response handling which is inherently integration-level
HTTP_HANDLING_PATHS = (
    "app/api/v1/endpoints/",
    "app/api/v1/dependencies.py",
    "app/core/middleware.py",
)

# Functions to skip from coverage validation (framework-generated code)
SKIP_FUNCTIONS = {
    # Pydantic BaseSettings __init__ is auto-generated and mostly covered via validation tests
    "app/core/settings.py::__init__",
}


@dataclass
class CoverageResult:
    """Container for coverage results."""

    suite_name: str
    total_lines: int
    covered_lines: int
    missing_lines: int
    line_coverage_pct: float
    total_branches: int
    covered_branches: int
    missing_branches: int
    branch_coverage_pct: float
    files: dict[str, dict[str, Any]]
    functions: dict[str, dict[str, Any]]


@dataclass
class FunctionCoverage:
    """Coverage data for a single function."""

    name: str
    file_path: str
    start_line: int
    end_line: int
    total_lines: int
    covered_lines: int
    missing_lines: list[int]
    line_coverage_pct: float
    total_branches: int
    covered_branches: int
    missing_branches: list[tuple[int, int]]
    branch_coverage_pct: float


@dataclass
class UseCase:
    """A single use case from the registry."""

    id: str
    endpoint: str
    method: str
    description: str
    test_tier: str


@dataclass
class UseCaseCoverageResult:
    """Use case coverage results for a test tier."""

    tier: str
    total_cases: int
    covered_cases: int
    uncovered_cases: list[str]
    coverage_pct: float


@dataclass
class TestTierConfig:
    """Configuration for a test tier."""

    name: str
    test_path: str
    source_paths: list[str]
    coverage_file: str
    coverage_type: str  # "line_branch" or "usecase"
    min_line: float = DEFAULT_MIN_FUNCTION_LINE_COVERAGE
    min_branch: float = DEFAULT_MIN_FUNCTION_BRANCH_COVERAGE
    min_usecase: float = DEFAULT_USECASE_COVERAGE
    skip_private_functions: bool = False
    service_layer_only: bool = False
    exclude_class_fields: bool = True


# Test tier configurations
TEST_TIERS: dict[str, TestTierConfig] = {
    "unit": TestTierConfig(
        name="unit",
        test_path="tests/unit",
        source_paths=["app"],
        coverage_file="coverage_unit.json",
        coverage_type="line_branch",
        skip_private_functions=False,
        service_layer_only=False,
        exclude_class_fields=True,
    ),
    "component": TestTierConfig(
        name="component",
        test_path="tests/unit",  # Component tests may be within unit tests targeting services
        source_paths=["app/services"],
        coverage_file="coverage_component.json",
        coverage_type="line_branch",
        skip_private_functions=True,
        service_layer_only=True,
        exclude_class_fields=True,
    ),
    "integration": TestTierConfig(
        name="integration",
        test_path="tests/integration",
        source_paths=["app"],
        coverage_file="coverage_integration.json",
        coverage_type="usecase",
        min_usecase=100.0,
    ),
    "e2e": TestTierConfig(
        name="e2e",
        test_path="tests/e2e",
        source_paths=["app"],
        coverage_file="coverage_e2e.json",
        coverage_type="usecase",
        min_usecase=100.0,
    ),
    "scripts": TestTierConfig(
        name="scripts",
        test_path="scripts/tests",
        source_paths=["scripts", "tools"],
        coverage_file="coverage_scripts.json",
        coverage_type="line_branch",
        skip_private_functions=True,
        service_layer_only=False,
        exclude_class_fields=True,
    ),
}


def _run_command(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command."""
    return subprocess.run(  # noqa: S603
        cmd,
        capture_output=capture,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _is_class_field_line(source_lines: list[str], line_num: int) -> bool:
    """Check if a line is a class field (type annotation without assignment logic).

    Class fields in Pydantic models look like:
        message: str
        type: MessageType = "info"
        items: Annotated[list[T], Field(...)]

    These are just declarations, not executable code, so should be excluded.
    """
    if line_num < 1 or line_num > len(source_lines):
        return False

    line = source_lines[line_num - 1].strip()

    # Skip empty lines and comments
    if not line or line.startswith("#"):
        return False

    # Class field patterns: "name: Type" or "name: Type = value"
    # But NOT function definitions, assignments without type hints, etc.
    if ":" in line and not line.startswith("def ") and not line.startswith("async def "):
        # Check if it's a simple type annotation (class field)
        # These typically don't have complex logic
        parts = line.split(":", 1)
        if len(parts) == 2:
            name_part = parts[0].strip()
            # Valid identifier check (field name)
            if name_part.isidentifier() or name_part.startswith("_"):
                # It's likely a class field
                return True

    return False


def _extract_functions_from_file(file_path: Path) -> list[tuple[str, int, int, bool]]:
    """Extract function definitions from a Python file.

    Returns list of (function_name, start_line, end_line, is_method) tuples.
    is_method is True if the function is a method inside a class.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, OSError):
        return []

    functions: list[tuple[str, int, int, bool]] = []

    class FunctionVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.in_class = False

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            old_in_class = self.in_class
            self.in_class = True
            self.generic_visit(node)
            self.in_class = old_in_class

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._process_function(node)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._process_function(node)
            self.generic_visit(node)

        def _process_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            start = node.lineno
            end = start
            for child in ast.walk(node):
                if hasattr(child, "lineno"):
                    end = max(end, child.lineno)
            functions.append((node.name, start, end, self.in_class))

    visitor = FunctionVisitor()
    visitor.visit(tree)

    return functions


def _get_class_field_lines(file_path: Path) -> set[int]:
    """Get line numbers that are class field definitions.

    These are lines inside class bodies that are type annotations (field definitions).
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, OSError):
        return set()

    class_field_lines: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                # AnnAssign is a type-annotated assignment: field: Type = value
                if isinstance(item, ast.AnnAssign):
                    class_field_lines.add(item.lineno)

    return class_field_lines


def _calculate_function_coverage(
    file_path: str,
    coverage_data: dict[str, Any],
    repo_root: Path,
    exclude_class_fields: bool = True,
) -> list[FunctionCoverage]:
    """Calculate per-function coverage for a file."""
    abs_path = repo_root / file_path
    if not abs_path.exists():
        return []

    file_data = coverage_data.get("files", {}).get(file_path, {})
    executed_lines = set(file_data.get("executed_lines", []))
    missing_lines = set(file_data.get("missing_lines", []))
    missing_branches = file_data.get("missing_branches", [])

    # Get class field lines to exclude
    class_field_lines = _get_class_field_lines(abs_path) if exclude_class_fields else set()

    # Remove class field lines from coverage calculation
    executed_lines -= class_field_lines
    missing_lines -= class_field_lines

    # Build branch coverage mapping: source_line -> list of missing dest lines
    branch_map: dict[int, list[int]] = {}
    for arc in missing_branches:
        if isinstance(arc, (list, tuple)) and len(arc) == 2:
            src, dst = int(arc[0]), int(arc[1])
            if src not in class_field_lines:
                branch_map.setdefault(src, []).append(dst)

    functions = _extract_functions_from_file(abs_path)
    results: list[FunctionCoverage] = []

    for func_name, start, end, _is_method in functions:
        func_lines = set(range(start, end + 1))
        # Exclude class field lines from function lines
        func_lines -= class_field_lines

        # Lines in this function
        func_executed = executed_lines & func_lines
        func_missing = missing_lines & func_lines
        total_relevant = len(func_executed) + len(func_missing)
        line_pct = 100.0 if total_relevant == 0 else (len(func_executed) / total_relevant) * 100

        # Branches in this function
        func_missing_branches: list[tuple[int, int]] = []
        for src, dests in branch_map.items():
            if start <= src <= end:
                for dst in dests:
                    func_missing_branches.append((src, dst))

        # Estimate total branches
        total_branches = len(func_missing_branches) * 2 if func_missing_branches else 0
        covered_branches = total_branches - len(func_missing_branches)
        branch_pct = 100.0 if total_branches == 0 else (covered_branches / total_branches) * 100

        results.append(
            FunctionCoverage(
                name=func_name,
                file_path=file_path,
                start_line=start,
                end_line=end,
                total_lines=total_relevant,
                covered_lines=len(func_executed),
                missing_lines=sorted(func_missing),
                line_coverage_pct=line_pct,
                total_branches=total_branches,
                covered_branches=covered_branches,
                missing_branches=func_missing_branches,
                branch_coverage_pct=branch_pct,
            )
        )

    return results


def _is_private_function(func_name: str) -> bool:
    """Check if a function name indicates a private function.

    Private functions start with underscore but are not special dunder methods.
    Special methods like __init__ and __call__ are considered public.
    """
    if not func_name.startswith("_"):
        return False
    return func_name not in ("__init__", "__call__")


def _is_in_service_layer(file_path: str) -> bool:
    """Check if a file is in the service layer."""
    return file_path.startswith(SERVICE_LAYER_PATH)


def _is_infrastructure_path(file_path: str) -> bool:
    """Check if a file is in the infrastructure layer.

    Infrastructure modules require external dependencies and are excluded
    from unit test coverage validation.
    """
    return any(file_path.startswith(path) for path in INFRASTRUCTURE_PATHS)


def _is_http_handling_path(file_path: str) -> bool:
    """Check if a file is HTTP handling code.

    HTTP handling code (endpoints, middleware) is tested via integration tests
    rather than unit tests, as it involves request/response processing.
    """
    return any(file_path.startswith(path) for path in HTTP_HANDLING_PATHS)


def load_use_cases(use_cases_path: Path) -> list[UseCase]:
    """Load use cases from YAML file."""
    if not use_cases_path.exists():
        return []

    with use_cases_path.open() as f:
        data = yaml.safe_load(f)

    use_cases: list[UseCase] = []
    features = data.get("features", {})

    for _feature_name, feature_data in features.items():
        for uc in feature_data.get("use_cases", []):
            use_cases.append(
                UseCase(
                    id=uc["id"],
                    endpoint=uc["endpoint"],
                    method=uc["method"],
                    description=uc["description"],
                    test_tier=uc["test_tier"],
                )
            )

    return use_cases


def run_test_suite(config: TestTierConfig) -> CoverageResult | None:
    """Run a test suite and collect coverage data.

    Args:
        config: Test tier configuration

    Returns:
        CoverageResult if successful, None if tests failed
    """
    # Build pytest command with coverage
    source_args = ",".join(config.source_paths)
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "pytest",
        config.test_path,
        f"--cov={source_args}",
        "--cov-branch",
        "--cov-context=test",  # Enable per-test coverage tracking for redundant test detection
        f"--cov-report=json:{config.coverage_file}",
        "--cov-report=term-missing",
        "--cov-fail-under=0",  # Disable fail-under (we do our own validation)
        "-q",
        "-p",
        "no:randomly",
    ]

    print(f"\n{'=' * 70}")
    print(f"Running {config.name} tests: {config.test_path}")
    print(f"Measuring coverage for: {source_args}")
    print("=" * 70)

    result = _run_command(cmd, capture=False)

    if result.returncode != 0:
        print(f"\nWARNING: {config.name} tests had failures (exit code {result.returncode})")

    # Load coverage data
    coverage_path = REPO_ROOT / config.coverage_file
    if not coverage_path.exists():
        print(f"ERROR: Coverage file not found: {config.coverage_file}")
        return None

    with coverage_path.open() as f:
        coverage_data = json.load(f)

    totals = coverage_data.get("totals", {})

    # Calculate function-level coverage
    all_functions: dict[str, dict[str, Any]] = {}
    files_data = coverage_data.get("files", {})

    for file_path in files_data:
        # For component tests, only include service layer files
        if config.service_layer_only and not _is_in_service_layer(file_path):
            continue

        func_coverages = _calculate_function_coverage(
            file_path,
            coverage_data,
            REPO_ROOT,
            exclude_class_fields=config.exclude_class_fields,
        )
        for fc in func_coverages:
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

    return CoverageResult(
        suite_name=config.name,
        total_lines=totals.get("num_statements", 0),
        covered_lines=totals.get("covered_lines", 0),
        missing_lines=totals.get("missing_lines", 0),
        line_coverage_pct=totals.get("percent_covered", 0.0),
        total_branches=totals.get("num_branches", 0),
        covered_branches=totals.get("covered_branches", 0),
        missing_branches=totals.get("num_partial_branches", 0) + totals.get("missing_branches", 0),
        branch_coverage_pct=totals.get("percent_covered_branches", 0.0)
        if "percent_covered_branches" in totals
        else 0.0,
        files=files_data,
        functions=all_functions,
    )


def _parse_usecase_markers_from_content(content: str) -> set[str]:
    """Parse use-case IDs from test file content.

    Args:
        content: Python source code content to parse

    Returns:
        Set of use-case IDs found in @pytest.mark.usecase markers
    """
    import re

    # Pattern matches @pytest.mark.usecase("UC-XXX-NNN") or ('UC-XXX-NNN')
    pattern = r'usecase\(["\']?(UC-[A-Z]+-\d+)["\']?\)'
    matches = re.findall(pattern, content)
    return set(matches)


def collect_covered_usecases(test_path: str) -> set[str]:
    """Collect use-case IDs from pytest markers in tests.

    Parses test files directly to extract @pytest.mark.usecase markers
    and determine which use cases have corresponding tests.

    Args:
        test_path: Path to test directory to collect from

    Returns:
        Set of use-case IDs that have tests with usecase markers
    """
    covered_ids: set[str] = set()

    # Parse test file contents directly for reliable detection
    test_dir = Path(test_path)
    if test_dir.exists():
        for test_file in test_dir.rglob("test_*.py"):
            try:
                content = test_file.read_text()
                matches = _parse_usecase_markers_from_content(content)
                covered_ids.update(matches)
            except (OSError, UnicodeDecodeError):
                continue

    return covered_ids


def calculate_usecase_coverage(
    tier: str, use_cases: list[UseCase], covered_ids: set[str]
) -> UseCaseCoverageResult:
    """Calculate use-case coverage for a test tier.

    Args:
        tier: Test tier name (e.g., "integration", "e2e")
        use_cases: List of use cases from the registry
        covered_ids: Set of use-case IDs detected from pytest markers

    Returns:
        UseCaseCoverageResult with coverage statistics
    """
    tier_cases = [uc for uc in use_cases if uc.test_tier == tier]

    covered = [uc for uc in tier_cases if uc.id in covered_ids]
    uncovered = [uc.id for uc in tier_cases if uc.id not in covered_ids]

    total = len(tier_cases)
    coverage_pct = 100.0 if total == 0 else (len(covered) / total) * 100

    return UseCaseCoverageResult(
        tier=tier,
        total_cases=total,
        covered_cases=len(covered),
        uncovered_cases=uncovered,
        coverage_pct=coverage_pct,
    )


def validate_line_branch_coverage(
    result: CoverageResult,
    config: TestTierConfig,
) -> list[str]:
    """Validate per-function line and branch coverage.

    Returns list of failure messages.
    """
    failures: list[str] = []

    for func_key, func_data in result.functions.items():
        func_name = func_data["name"]
        file_path = func_data["file"]

        # Skip private functions if configured
        if config.skip_private_functions and _is_private_function(func_name):
            continue

        # For service-layer-only mode, skip non-service files
        if config.service_layer_only and not _is_in_service_layer(file_path):
            continue

        # For unit tests, skip infrastructure files (they require integration testing)
        if config.name == "unit" and _is_infrastructure_path(file_path):
            continue

        # For unit tests, skip HTTP handling files (tested via integration tests)
        if config.name == "unit" and _is_http_handling_path(file_path):
            continue

        # Skip explicitly exempted functions (framework-generated code)
        if func_key in SKIP_FUNCTIONS:
            continue

        line_cov = func_data["line_coverage"]
        branch_cov = func_data["branch_coverage"]

        if line_cov < config.min_line:
            failures.append(
                f"{config.name}: Function {func_key} line coverage "
                f"{line_cov:.1f}% < {config.min_line:.1f}% minimum"
            )

        if branch_cov < config.min_branch and func_data.get("missing_branches"):
            failures.append(
                f"{config.name}: Function {func_key} branch coverage "
                f"{branch_cov:.1f}% < {config.min_branch:.1f}% minimum"
            )

    return failures


def validate_usecase_coverage(
    uc_result: UseCaseCoverageResult,
    config: TestTierConfig,
) -> list[str]:
    """Validate use-case coverage.

    Returns list of failure messages.
    """
    failures: list[str] = []

    if uc_result.coverage_pct < config.min_usecase:
        failures.append(
            f"{config.name}: Use-case coverage {uc_result.coverage_pct:.1f}% "
            f"< {config.min_usecase:.1f}% minimum"
        )
        for uc_id in uc_result.uncovered_cases[:10]:
            failures.append(f"  - Uncovered: {uc_id}")
        if len(uc_result.uncovered_cases) > 10:
            failures.append(f"  ... and {len(uc_result.uncovered_cases) - 10} more")

    return failures


def print_summary(
    line_branch_results: list[tuple[TestTierConfig, CoverageResult]],
    usecase_results: list[tuple[TestTierConfig, UseCaseCoverageResult]],
    redundant_result: RedundantTestResult | None = None,
) -> None:
    """Print coverage summary for all test tiers."""
    print("\n" + "=" * 70)
    print("COVERAGE SUMMARY")
    print("=" * 70)

    # Line/branch coverage results
    for config, result in line_branch_results:
        print(f"\n{result.suite_name.upper()} TEST SUITE (Line/Branch Coverage)")
        print("-" * 40)
        print(f"  Total Statements:   {result.total_lines:>6}")
        print(f"  Covered Lines:      {result.covered_lines:>6}")
        print(f"  Missing Lines:      {result.missing_lines:>6}")
        print(f"  Line Coverage:      {result.line_coverage_pct:>6.1f}%")
        print()
        print(f"  Total Branches:     {result.total_branches:>6}")
        print(f"  Covered Branches:   {result.covered_branches:>6}")
        print(f"  Missing Branches:   {result.missing_branches:>6}")
        print(f"  Branch Coverage:    {result.branch_coverage_pct:>6.1f}%")
        print()
        print(f"  Functions Tracked:  {len(result.functions):>6}")

        # List functions with low coverage
        low_coverage_funcs = [
            (key, data)
            for key, data in result.functions.items()
            if data["line_coverage"] < config.min_line
            and not (config.skip_private_functions and _is_private_function(data["name"]))
        ]
        if low_coverage_funcs:
            print(f"\n  Functions below {config.min_line:.0f}% line coverage:")
            for key, data in sorted(low_coverage_funcs, key=lambda x: x[1]["line_coverage"])[:10]:
                print(f"    {key}: {data['line_coverage']:.1f}%")
            if len(low_coverage_funcs) > 10:
                print(f"    ... and {len(low_coverage_funcs) - 10} more")

    # Use-case coverage results
    for config, uc_result in usecase_results:
        print(f"\n{config.name.upper()} TEST SUITE (Use-Case Coverage)")
        print("-" * 40)
        print(f"  Total Use Cases:    {uc_result.total_cases:>6}")
        print(f"  Covered:            {uc_result.covered_cases:>6}")
        print(f"  Uncovered:          {len(uc_result.uncovered_cases):>6}")
        print(f"  Coverage:           {uc_result.coverage_pct:>6.1f}%")

        if uc_result.uncovered_cases:
            print("\n  Uncovered use cases:")
            for uc_id in uc_result.uncovered_cases[:10]:
                print(f"    - {uc_id}")
            if len(uc_result.uncovered_cases) > 10:
                print(f"    ... and {len(uc_result.uncovered_cases) - 10} more")

    # Redundant test results
    if redundant_result is not None:
        print("\n" + "=" * 70)
        print("REDUNDANT TEST ANALYSIS")
        print("=" * 70)

        if "error" in redundant_result.summary:
            print(f"\n  Note: {redundant_result.summary['error']}")
        else:
            print(f"\n  Total tests analyzed:       {redundant_result.total_tests:>6}")
            print(f"  Tests with unique coverage: {redundant_result.tests_with_unique_coverage:>6}")
            print(f"  Redundant tests:            {len(redundant_result.redundant_tests):>6}")

            if redundant_result.redundant_tests:
                print("\n  Tests that add no unique coverage (candidates for removal):")
                for test in redundant_result.redundant_tests[:15]:
                    print(f"    - {test['test_name']}")
                if len(redundant_result.redundant_tests) > 15:
                    remaining = len(redundant_result.redundant_tests) - 15
                    print(f"    ... and {remaining} more")

    print("\n" + "=" * 70)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run tests with separate coverage tracking for different test tiers.",
    )
    parser.add_argument(
        "--tier",
        choices=["unit", "component", "integration", "e2e", "scripts", "all"],
        default="all",
        help="Which test tier to run (default: all)",
    )
    parser.add_argument(
        "--min-line",
        type=float,
        default=DEFAULT_MIN_FUNCTION_LINE_COVERAGE,
        help=f"Minimum per-function line coverage (default: {DEFAULT_MIN_FUNCTION_LINE_COVERAGE})",
    )
    branch_default = DEFAULT_MIN_FUNCTION_BRANCH_COVERAGE
    parser.add_argument(
        "--min-branch",
        type=float,
        default=DEFAULT_MIN_FUNCTION_BRANCH_COVERAGE,
        help=f"Minimum per-function branch coverage (default: {branch_default})",
    )
    parser.add_argument(
        "--min-usecase",
        type=float,
        default=DEFAULT_USECASE_COVERAGE,
        help=f"Minimum use-case coverage %% (default: {DEFAULT_USECASE_COVERAGE})",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip coverage validation (just run and report)",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        help="Write combined coverage report to JSON file",
    )
    parser.add_argument(
        "--skip-redundant-detection",
        action="store_true",
        help="Skip redundant test detection (faster but less analysis)",
    )
    parser.add_argument(
        "--include-partial-redundant",
        action="store_true",
        help="Include tests with <5%% unique coverage in redundant report",
    )
    return parser.parse_args(argv)


def main() -> int:
    """Run test coverage analysis and validation."""
    args = parse_args()

    # Load use cases for integration/e2e coverage
    use_cases_path = REPO_ROOT / "tests" / "docs" / "use_cases.yaml"
    use_cases = load_use_cases(use_cases_path)

    # Determine which tiers to run
    tiers_to_run = list(TEST_TIERS.keys()) if args.tier == "all" else [args.tier]

    # Collect results
    line_branch_results: list[tuple[TestTierConfig, CoverageResult]] = []
    usecase_results: list[tuple[TestTierConfig, UseCaseCoverageResult]] = []
    all_failures: list[str] = []

    for tier_name in tiers_to_run:
        config = TEST_TIERS[tier_name]

        # Override thresholds from args
        config.min_line = args.min_line
        config.min_branch = args.min_branch
        config.min_usecase = args.min_usecase

        if config.coverage_type == "line_branch":
            result = run_test_suite(config)
            if result:
                line_branch_results.append((config, result))
                if not args.no_validate:
                    failures = validate_line_branch_coverage(result, config)
                    all_failures.extend(failures)

        elif config.coverage_type == "usecase":
            # Run tests (without coverage measurement for usecase tiers)
            cmd = ["uv", "run", "python", "-m", "pytest", config.test_path, "-v", "-p", "no:randomly"]
            print(f"\n{'=' * 70}")
            print(f"Running {config.name} tests: {config.test_path}")
            print("=" * 70)
            _run_command(cmd, capture=False)

            # Collect covered use cases from pytest markers
            covered_ids = collect_covered_usecases(config.test_path)

            # Calculate use-case coverage from detected markers
            uc_result = calculate_usecase_coverage(tier_name, use_cases, covered_ids)
            usecase_results.append((config, uc_result))
            if not args.no_validate:
                failures = validate_usecase_coverage(uc_result, config)
                all_failures.extend(failures)

    if not line_branch_results and not usecase_results:
        print("ERROR: No coverage results collected")
        return 1

    # Run redundant test detection
    redundant_result: RedundantTestResult | None = None
    if not args.skip_redundant_detection:
        coverage_db_path = REPO_ROOT / ".coverage"
        if coverage_db_path.exists():
            print("\n" + "=" * 70)
            print("Analyzing test coverage for redundant tests...")
            print("=" * 70)
            redundant_result = detect_redundant_tests(
                coverage_db_path,
                include_partial=args.include_partial_redundant,
            )

    # Print summary
    print_summary(line_branch_results, usecase_results, redundant_result)

    # Report validation results
    if not args.no_validate:
        if all_failures:
            print("\nCOVERAGE VALIDATION FAILED:")
            for failure in all_failures[:20]:
                print(f"  - {failure}")
            if len(all_failures) > 20:
                print(f"  ... and {len(all_failures) - 20} more failures")
            return 1
        else:
            print("\nCoverage validation PASSED")

    # Write JSON report if requested
    if args.json_report:
        report: dict[str, Any] = {
            "tiers": {},
            "thresholds": {
                "min_line": args.min_line,
                "min_branch": args.min_branch,
                "min_usecase": args.min_usecase,
            },
        }

        for config, result in line_branch_results:
            report["tiers"][config.name] = {
                "type": "line_branch",
                "line_coverage": result.line_coverage_pct,
                "branch_coverage": result.branch_coverage_pct,
                "total_lines": result.total_lines,
                "covered_lines": result.covered_lines,
                "total_branches": result.total_branches,
                "covered_branches": result.covered_branches,
                "functions": result.functions,
            }

        for config, uc_result in usecase_results:
            report["tiers"][config.name] = {
                "type": "usecase",
                "total_cases": uc_result.total_cases,
                "covered_cases": uc_result.covered_cases,
                "uncovered_cases": uc_result.uncovered_cases,
                "coverage_pct": uc_result.coverage_pct,
            }

        # Add redundant test data to report
        if redundant_result is not None:
            report["redundant_tests"] = {
                "summary": redundant_result.summary,
                "tests": redundant_result.redundant_tests,
                "total_tests_analyzed": redundant_result.total_tests,
                "tests_with_unique_coverage": redundant_result.tests_with_unique_coverage,
            }

        args.json_report.write_text(json.dumps(report, indent=2))
        print(f"\nCoverage report written to: {args.json_report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
