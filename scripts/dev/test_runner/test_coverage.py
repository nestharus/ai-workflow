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
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Fallback defaults if pyproject.toml settings are missing
DEFAULT_MIN_LINE_OVERALL = 80.0
DEFAULT_MIN_BRANCH_OVERALL = 70.0
DEFAULT_MIN_LINE_PER_FUNCTION = 60.0
DEFAULT_MIN_BRANCH_PER_FUNCTION = 50.0
DEFAULT_MIN_USECASE = 100.0


# Define dataclasses early to avoid circular import with coverage_db
@dataclass
class MissingLineDetail:
    """Details about a missing line of coverage."""

    file: str
    line_number: int
    content: str
    context_before: list[dict[str, Any]]
    context_after: list[dict[str, Any]]
    missing_branch_exits: list[int]


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
class TestTierConfig:
    """Configuration for a test tier."""

    name: str
    test_path: str
    source_paths: list[str]
    coverage_type: str  # "line_branch" or "usecase"
    min_line_overall: float = DEFAULT_MIN_LINE_OVERALL
    min_branch_overall: float = DEFAULT_MIN_BRANCH_OVERALL
    min_line_per_function: float = DEFAULT_MIN_LINE_PER_FUNCTION
    min_branch_per_function: float = DEFAULT_MIN_BRANCH_PER_FUNCTION
    min_usecase: float = DEFAULT_MIN_USECASE
    skip_private_functions: bool = False
    service_layer_only: bool = False
    exclude_class_fields: bool = True


# Import modules after dataclass definitions to avoid circular imports
from scripts.dev.test_runner import coverage_db
from scripts.dev.test_runner.redundant_test_detector import (
    RedundantTestResult,
    detect_redundant_tests,
)


@dataclass
class TierSettings:
    """Settings for a single test tier loaded from pyproject.toml."""

    min_line_overall: float = DEFAULT_MIN_LINE_OVERALL
    min_branch_overall: float = DEFAULT_MIN_BRANCH_OVERALL
    min_line_per_function: float = DEFAULT_MIN_LINE_PER_FUNCTION
    min_branch_per_function: float = DEFAULT_MIN_BRANCH_PER_FUNCTION
    min_usecase: float = DEFAULT_MIN_USECASE


@dataclass
class CoverageSettings:
    """All coverage settings loaded from pyproject.toml."""

    unit: TierSettings = field(default_factory=TierSettings)
    component: TierSettings = field(default_factory=TierSettings)
    integration: TierSettings = field(default_factory=TierSettings)
    e2e: TierSettings = field(default_factory=TierSettings)
    scripts: TierSettings = field(default_factory=TierSettings)


def load_coverage_settings(pyproject_path: Path | None = None) -> CoverageSettings:
    """Load coverage settings from pyproject.toml.

    Args:
        pyproject_path: Path to pyproject.toml. Defaults to REPO_ROOT/pyproject.toml.

    Returns:
        CoverageSettings with all tier configurations.
    """
    path = pyproject_path or REPO_ROOT / "pyproject.toml"
    if not path.exists():
        return CoverageSettings()

    with path.open("rb") as f:
        data = tomllib.load(f)

    test_coverage = data.get("tool", {}).get("test_coverage", {})

    def load_tier(name: str) -> TierSettings:
        tier_data = test_coverage.get(name, {})
        return TierSettings(
            min_line_overall=tier_data.get("min_line_overall", DEFAULT_MIN_LINE_OVERALL),
            min_branch_overall=tier_data.get("min_branch_overall", DEFAULT_MIN_BRANCH_OVERALL),
            min_line_per_function=tier_data.get(
                "min_line_per_function", DEFAULT_MIN_LINE_PER_FUNCTION
            ),
            min_branch_per_function=tier_data.get(
                "min_branch_per_function", DEFAULT_MIN_BRANCH_PER_FUNCTION
            ),
            min_usecase=tier_data.get("min_usecase", DEFAULT_MIN_USECASE),
        )

    return CoverageSettings(
        unit=load_tier("unit"),
        component=load_tier("component"),
        integration=load_tier("integration"),
        e2e=load_tier("e2e"),
        scripts=load_tier("scripts"),
    )


# Load settings at module level (can be reloaded for testing)
_settings: CoverageSettings | None = None


def get_settings() -> CoverageSettings:
    """Get cached coverage settings."""
    global _settings
    if _settings is None:
        _settings = load_coverage_settings()
    return _settings


# Service layer path pattern (relative to repo root)
SERVICE_LAYER_PATH = "app/services"


def is_excluded_path(file_path: str) -> bool:
    """Check if a file path is excluded from coverage validation.

    Note: Currently no path exclusions - unit tests cover all of app/.
    This function is kept for API compatibility but always returns False.
    """
    # No path exclusions - unit tests cover ALL paths
    return False


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
class UseCaseCoverageResult:
    """Use case coverage results for a test tier."""

    tier: str
    total_cases: int
    covered_cases: int
    uncovered_cases: list[str]
    coverage_pct: float


def get_test_tiers() -> dict[str, TestTierConfig]:
    """Get test tier configurations with settings from pyproject.toml."""
    settings = get_settings()
    return {
        "unit": TestTierConfig(
            name="unit",
            test_path="tests/unit",
            source_paths=["app"],
            coverage_type="line_branch",
            min_line_overall=settings.unit.min_line_overall,
            min_branch_overall=settings.unit.min_branch_overall,
            min_line_per_function=settings.unit.min_line_per_function,
            min_branch_per_function=settings.unit.min_branch_per_function,
            skip_private_functions=False,
            service_layer_only=False,
            exclude_class_fields=True,
        ),
        "component": TestTierConfig(
            name="component",
            test_path="tests/unit",  # Component tests may be within unit tests targeting services
            source_paths=["app/services"],
            coverage_type="line_branch",
            min_line_overall=settings.component.min_line_overall,
            min_branch_overall=settings.component.min_branch_overall,
            min_line_per_function=settings.component.min_line_per_function,
            min_branch_per_function=settings.component.min_branch_per_function,
            skip_private_functions=True,
            service_layer_only=True,
            exclude_class_fields=True,
        ),
        "integration": TestTierConfig(
            name="integration",
            test_path="tests/integration",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=settings.integration.min_usecase,
        ),
        "e2e": TestTierConfig(
            name="e2e",
            test_path="tests/e2e",
            source_paths=["app"],
            coverage_type="usecase",
            min_usecase=settings.e2e.min_usecase,
        ),
        "scripts": TestTierConfig(
            name="scripts",
            test_path="scripts/tests",
            source_paths=["scripts", "tools"],
            coverage_type="line_branch",
            min_line_overall=settings.scripts.min_line_overall,
            min_branch_overall=settings.scripts.min_branch_overall,
            min_line_per_function=settings.scripts.min_line_per_function,
            min_branch_per_function=settings.scripts.min_branch_per_function,
            skip_private_functions=True,
            service_layer_only=False,
            exclude_class_fields=True,
        ),
    }


def _run_command(
    cmd: list[str], capture: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command.

    Args:
        cmd: Command and arguments to run
        capture: If True, capture stdout/stderr
        env: Optional environment variables to set (merged with current env)

    Returns:
        Completed process with return code and output
    """
    run_env = None
    if env:
        run_env = os.environ.copy()
        run_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        cwd=str(REPO_ROOT),
        env=run_env,
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


def run_test_suite(
    config: TestTierConfig, coverage_db_path: Path, first_tier: bool = False
) -> tuple[CoverageResult | None, Any]:
    """Run a test suite and collect coverage data.

    Args:
        config: Test tier configuration
        coverage_db_path: Path to the .coverage database
        first_tier: If True, this is the first tier (don't use --cov-append)

    Returns:
        Tuple of (CoverageResult if successful, TestSummary from junit XML)
    """
    # Set up junit XML output path
    junit_xml_path = coverage_db_path.parent / f"junit_{config.name}.xml"

    # Set up coverage data file path (inside .coverage directory to avoid conflict)
    # pytest-cov uses .coverage as a file by default, but we use .coverage as a directory
    coverage_data_file = coverage_db_path.parent / "data"
    cov_env = {"COVERAGE_FILE": str(coverage_data_file)}

    # Build pytest command with coverage
    # Each source path needs its own --cov argument
    cov_args = [f"--cov={path}" for path in config.source_paths]
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "pytest",
        config.test_path,
        *cov_args,
        "--cov-branch",
        "--cov-context=test",  # Enable per-test coverage tracking for redundant test detection
        "--cov-report=term-missing",
        "--cov-fail-under=0",  # Disable fail-under (we do our own validation)
        f"--junitxml={junit_xml_path}",  # Generate JUnit XML for test results
        "-q",
        "-p",
        "no:randomly",
    ]

    # Add --cov-append for all tiers except the first one
    if not first_tier:
        cmd.append("--cov-append")

    print(f"\n{'=' * 70}")
    print(f"Running {config.name} tests: {config.test_path}")
    print(f"Measuring coverage for: {', '.join(config.source_paths)}")
    print("=" * 70)

    result = _run_command(cmd, capture=False, env=cov_env)

    # Parse junit XML to extract test results
    test_summary = None
    if junit_xml_path.exists():
        from scripts.dev.test_runner.junit_parser import parse_junit_xml

        try:
            test_results, test_summary = parse_junit_xml(junit_xml_path)
            # Write test results to database
            for test_result in test_results:
                coverage_db.write_test_result(
                    coverage_db_path,
                    tier=config.name,
                    test_name=test_result.test_name,
                    status=test_result.status,
                    duration=test_result.duration,
                    message=test_result.message,
                    traceback=test_result.traceback,
                )
        except Exception as e:
            print(f"\nWARNING: Failed to parse junit XML: {e}")

    if result.returncode != 0:
        print(f"\nWARNING: {config.name} tests had failures (exit code {result.returncode})")

    # Load coverage data from the consolidated .coverage database
    # We need to generate a JSON report temporarily to extract the data
    json_output_path = REPO_ROOT / ".coverage" / f"temp_{config.name}.json"
    json_output_path.parent.mkdir(parents=True, exist_ok=True)

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
        print(f"ERROR: Coverage JSON report not generated: {json_output_path}")
        return None, test_summary

    with json_output_path.open() as f:
        coverage_data = json.load(f)

    totals = coverage_data.get("totals", {})

    # Calculate function-level coverage
    all_functions: dict[str, dict[str, Any]] = {}
    all_function_coverages: list[FunctionCoverage] = []
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
            # Skip private functions if configured
            if config.skip_private_functions and _is_private_function(fc.name):
                continue

            # For service-layer-only mode, skip non-service files
            if config.service_layer_only and not _is_in_service_layer(fc.file_path):
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
    coverage_db.write_tier_config(coverage_db_path, config.name, config)

    # Write function coverage to database with pass/fail flags
    if all_function_coverages:
        coverage_db.write_function_coverage(
            coverage_db_path,
            config.name,
            all_function_coverages,
            config.min_line_per_function,
            config.min_branch_per_function,
        )

    # Clean up temporary JSON file
    json_output_path.unlink(missing_ok=True)

    coverage_result = CoverageResult(
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

    return coverage_result, test_summary


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


class _UsecaseMarkerVisitor(ast.NodeVisitor):
    """AST visitor that collects pytest.mark.usecase markers with test function info."""

    def __init__(self, rel_path: str) -> None:
        """Initialize visitor with relative file path."""
        self.rel_path = rel_path
        self.found: dict[str, list[dict[str, str]]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit regular function definition."""
        self._visit_test_node(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition."""
        self._visit_test_node(node)
        self.generic_visit(node)

    def _visit_test_node(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Extract usecase markers from test function decorators."""
        func_name = node.name
        for dec in node.decorator_list:
            uc_ids = self._extract_usecase_ids(dec)
            for uc_id in uc_ids:
                if uc_id not in self.found:
                    self.found[uc_id] = []
                self.found[uc_id].append(
                    {
                        "file": self.rel_path,
                        "test_function": func_name,
                    }
                )

    @staticmethod
    def _extract_usecase_ids(dec: ast.expr) -> list[str]:
        """Extract usecase IDs from a decorator expression."""
        if not isinstance(dec, ast.Call):
            return []

        func = dec.func
        func_name = ""

        # Handle pytest.mark.usecase (attribute access)
        if isinstance(func, ast.Attribute):
            parts: list[str] = []
            cur: ast.expr | None = func
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            func_name = ".".join(reversed(parts))
        elif isinstance(func, ast.Name):
            func_name = func.id

        if not func_name.endswith("usecase"):
            return []

        uc_ids: list[str] = []
        # Extract from positional arguments
        for arg in dec.args:
            if (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value.startswith("UC-")
            ):
                uc_ids.append(arg.value)

        # Extract from keyword arguments (e.g., id="UC-XXX-001")
        for kw in dec.keywords:
            if (
                kw.arg == "id"
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
                and kw.value.value.startswith("UC-")
            ):
                uc_ids.append(kw.value.value)

        return uc_ids


def _scan_tests_for_usecases(test_path: str, repo_root: Path) -> dict[str, list[dict[str, str]]]:
    """Scan test files for usecase markers using AST parsing.

    Args:
        test_path: Path to test directory
        repo_root: Repository root directory

    Returns:
        Dictionary mapping use case IDs to list of test locations
        Example: {"UC-HEALTH-001": [{"file": "tests/e2e/test_health.py",
                                      "test_function": "test_health"}]}
    """
    usecase_to_tests: dict[str, list[dict[str, str]]] = {}
    test_dir = Path(test_path)

    if not test_dir.exists():
        return usecase_to_tests

    for test_file in test_dir.rglob("test_*.py"):
        try:
            text = test_file.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(test_file))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        # Get relative path from repo root
        try:
            rel_path = str(test_file.relative_to(repo_root))
        except ValueError:
            rel_path = str(test_file)

        visitor = _UsecaseMarkerVisitor(rel_path)
        visitor.visit(tree)

        # Merge visitor results into global mapping
        for uc_id, occurrences in visitor.found.items():
            if uc_id not in usecase_to_tests:
                usecase_to_tests[uc_id] = []
            usecase_to_tests[uc_id].extend(occurrences)

    return usecase_to_tests


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

        line_cov = func_data["line_coverage"]
        branch_cov = func_data["branch_coverage"]

        if line_cov < config.min_line_per_function:
            failures.append(
                f"{config.name}: Function {func_key} line coverage "
                f"{line_cov:.1f}% < {config.min_line_per_function:.1f}% minimum"
            )

        if branch_cov < config.min_branch_per_function and func_data.get("missing_branches"):
            failures.append(
                f"{config.name}: Function {func_key} branch coverage "
                f"{branch_cov:.1f}% < {config.min_branch_per_function:.1f}% minimum"
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


def _read_source_lines(repo_root: Path, filename: str) -> list[str] | None:
    """Read source lines from a file."""
    file_path = (repo_root / filename).resolve()
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text.splitlines()


def _build_context(
    lines: list[str],
    lineno: int,
    radius: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build context lines before and after a given line number."""
    before: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    total = len(lines)
    start = max(1, lineno - radius)
    end = min(total, lineno + radius)

    for n in range(start, lineno):
        before.append({"line_number": n, "content": lines[n - 1]})
    for n in range(lineno + 1, end + 1):
        after.append({"line_number": n, "content": lines[n - 1]})
    return before, after


def generate_missing_line_details(
    coverage_data: dict[str, Any], repo_root: Path, context_radius: int = 3
) -> list[MissingLineDetail]:
    """Generate missing line details with source context.

    Args:
        coverage_data: Coverage data from coverage.py JSON report
        repo_root: Repository root path
        context_radius: Number of lines of context before/after

    Returns:
        List of MissingLineDetail objects
    """
    from collections import defaultdict

    files = coverage_data.get("files", {})
    missing_lines_details: list[MissingLineDetail] = []

    for filename, file_data in files.items():
        missing_lines = list(file_data.get("missing_lines", []))
        missing_branches_raw = file_data.get("missing_branches", []) or []

        source_lines = _read_source_lines(repo_root, filename)
        if source_lines is None:
            continue

        # Group missing branch arcs by source line
        branch_exits_by_source: dict[int, list[int]] = defaultdict(list)
        for arc in missing_branches_raw:
            if not isinstance(arc, (list, tuple)) or len(arc) != 2:
                continue
            src, dst = int(arc[0]), int(arc[1])
            branch_exits_by_source[src].append(dst)

        # Generate line-level gap details
        for lineno in sorted(missing_lines):
            if lineno < 1 or lineno > len(source_lines):
                content = ""
                before: list[dict[str, Any]] = []
                after: list[dict[str, Any]] = []
            else:
                content = source_lines[lineno - 1]
                before, after = _build_context(source_lines, lineno, context_radius)

            missing_line_detail = MissingLineDetail(
                file=filename,
                line_number=lineno,
                content=content,
                context_before=before,
                context_after=after,
                missing_branch_exits=sorted(set(branch_exits_by_source.get(lineno, []))),
            )
            missing_lines_details.append(missing_line_detail)

    return missing_lines_details


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
            if data["line_coverage"] < config.min_line_per_function
            and not (config.skip_private_functions and _is_private_function(data["name"]))
        ]
        if low_coverage_funcs:
            print(f"\n  Functions below {config.min_line_per_function:.0f}% line coverage:")
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
        default=DEFAULT_MIN_LINE_PER_FUNCTION,
        help=f"Minimum per-function line coverage (default: {DEFAULT_MIN_LINE_PER_FUNCTION})",
    )
    parser.add_argument(
        "--min-branch",
        type=float,
        default=DEFAULT_MIN_BRANCH_PER_FUNCTION,
        help=f"Minimum per-function branch coverage (default: {DEFAULT_MIN_BRANCH_PER_FUNCTION})",
    )
    parser.add_argument(
        "--min-usecase",
        type=float,
        default=DEFAULT_MIN_USECASE,
        help=f"Minimum use-case coverage %% (default: {DEFAULT_MIN_USECASE})",
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

    # Set up coverage database path (.coverage/coverage.db)
    coverage_dir = REPO_ROOT / ".coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)
    coverage_db_path = coverage_dir / "coverage.db"

    # Set up coverage data file path (inside .coverage directory)
    # pytest-cov uses .coverage as a file by default, but we use .coverage as a directory
    coverage_data_file = coverage_dir / "data"
    cov_env = {"COVERAGE_FILE": str(coverage_data_file)}

    # Initialize custom tables and clear previous run data
    coverage_db.init_custom_tables(coverage_db_path)
    coverage_db.clear_custom_tables(coverage_db_path)

    # Load use cases for integration/e2e coverage
    use_cases_path = REPO_ROOT / "tests" / "docs" / "use_cases.yaml"
    use_cases = load_use_cases(use_cases_path)

    # Write use case registry to database
    if use_cases:
        coverage_db.write_usecase_registry(coverage_db_path, use_cases)

    # Get tier configurations from settings
    test_tiers = get_test_tiers()

    # Determine which tiers to run
    tiers_to_run = list(test_tiers.keys()) if args.tier == "all" else [args.tier]

    # Collect results
    line_branch_results: list[tuple[TestTierConfig, CoverageResult]] = []
    usecase_results: list[tuple[TestTierConfig, UseCaseCoverageResult]] = []
    all_failures: list[str] = []
    # Track test summaries for each tier (tier_name -> TestSummary)
    tier_test_summaries: dict[str, Any] = {}

    for idx, tier_name in enumerate(tiers_to_run):
        config = test_tiers[tier_name]

        # Override per-function thresholds from args if provided
        if args.min_line != DEFAULT_MIN_LINE_PER_FUNCTION:
            config.min_line_per_function = args.min_line
        if args.min_branch != DEFAULT_MIN_BRANCH_PER_FUNCTION:
            config.min_branch_per_function = args.min_branch
        if args.min_usecase != DEFAULT_MIN_USECASE:
            config.min_usecase = args.min_usecase

        if config.coverage_type == "line_branch":
            # First tier should not use --cov-append
            is_first_tier = idx == 0
            result, test_summary = run_test_suite(
                config, coverage_db_path, first_tier=is_first_tier
            )
            if test_summary:
                tier_test_summaries[tier_name] = test_summary
            if result:
                line_branch_results.append((config, result))
                if not args.no_validate:
                    failures = validate_line_branch_coverage(result, config)
                    all_failures.extend(failures)

        elif config.coverage_type == "usecase":
            # Run tests (without coverage measurement for usecase tiers)
            cmd = [
                "uv",
                "run",
                "python",
                "-m",
                "pytest",
                config.test_path,
                "-v",
                "-p",
                "no:randomly",
            ]
            print(f"\n{'=' * 70}")
            print(f"Running {config.name} tests: {config.test_path}")
            print("=" * 70)
            _run_command(cmd, capture=False)

            # Write tier config for usecase tiers too
            coverage_db.write_tier_config(coverage_db_path, config.name, config)

            # Scan test files for usecase markers with test function information
            usecase_to_tests = _scan_tests_for_usecases(config.test_path, REPO_ROOT)
            covered_ids = set(usecase_to_tests.keys())

            # Write use case coverage to database for each use case in this tier
            tier_use_cases = [uc for uc in use_cases if uc.test_tier == tier_name]
            for uc in tier_use_cases:
                if uc.id in usecase_to_tests:
                    # Use case is covered - get first test location
                    test_info = usecase_to_tests[uc.id][0]
                    coverage_db.write_usecase_coverage(
                        coverage_db_path,
                        uc.id,
                        covered=True,
                        test_file=test_info["file"],
                        test_function=test_info["test_function"],
                    )
                else:
                    # Use case is not covered
                    coverage_db.write_usecase_coverage(
                        coverage_db_path,
                        uc.id,
                        covered=False,
                        test_file=None,
                        test_function=None,
                    )

            # Calculate use-case coverage from detected markers
            uc_result = calculate_usecase_coverage(tier_name, use_cases, covered_ids)
            usecase_results.append((config, uc_result))
            if not args.no_validate:
                failures = validate_usecase_coverage(uc_result, config)
                all_failures.extend(failures)

    if not line_branch_results and not usecase_results:
        print("ERROR: No coverage results collected")
        return 1

    # Write run metadata
    coverage_db.write_run_metadata(coverage_db_path, REPO_ROOT)

    # Generate and write missing line details with context
    # Generate JSON report from .coverage to extract missing lines
    json_output_path = coverage_dir / "temp_missing_lines.json"
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

    if json_output_path.exists():
        with json_output_path.open() as f:
            coverage_data = json.load(f)
        missing_line_details = generate_missing_line_details(coverage_data, REPO_ROOT)
        if missing_line_details:
            coverage_db.write_missing_lines(coverage_db_path, missing_line_details)
        # Clean up temporary file
        json_output_path.unlink(missing_ok=True)

    # Write tier summaries for each tier
    for config, result in line_branch_results:
        # Calculate passing/failing functions
        passing_funcs = sum(
            1
            for func_data in result.functions.values()
            if func_data["line_coverage"] >= config.min_line_per_function
            and func_data["branch_coverage"] >= config.min_branch_per_function
        )
        failing_funcs = len(result.functions) - passing_funcs

        # Get test counts from junit summary
        test_summary = tier_test_summaries.get(config.name)
        total_tests = test_summary.total if test_summary else 0
        tests_passed = test_summary.passed if test_summary else 0
        tests_failed = (test_summary.failed + test_summary.errors) if test_summary else 0

        # Check if there are tier-specific coverage failures
        tier_failures = [f for f in all_failures if f.startswith(f"{config.name}:")]
        has_coverage_failures = len(tier_failures) > 0
        has_test_failures = tests_failed > 0

        # Determine if tier passes all requirements (coverage + all tests passed)
        tier_pass = 1 if not has_coverage_failures and not has_test_failures else 0

        summary = {
            "coverage_type": config.coverage_type,
            "total_functions": len(result.functions),
            "passing_functions": passing_funcs,
            "failing_functions": failing_funcs,
            "overall_line_pct": result.line_coverage_pct,
            "overall_branch_pct": result.branch_coverage_pct,
            "total_tests": total_tests,
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "tier_pass": tier_pass,
        }
        coverage_db.write_tier_summary(coverage_db_path, config.name, summary)

    for config, uc_result in usecase_results:
        # Determine if tier passes
        tier_pass = 1 if uc_result.coverage_pct >= config.min_usecase else 0

        summary = {
            "coverage_type": config.coverage_type,
            "total_usecases": uc_result.total_cases,
            "usecases_covered": uc_result.covered_cases,
            "tier_pass": tier_pass,
        }
        coverage_db.write_tier_summary(coverage_db_path, config.name, summary)

    # Run redundant test detection
    redundant_result: RedundantTestResult | None = None
    if not args.skip_redundant_detection and coverage_data_file.exists():
        # The coverage data file is now at .coverage/data (not .coverage which is a directory)
        print("\n" + "=" * 70)
        print("Analyzing test coverage for redundant tests...")
        print("=" * 70)
        redundant_result = detect_redundant_tests(
            coverage_data_file,
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
