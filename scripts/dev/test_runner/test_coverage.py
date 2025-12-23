"""Test coverage runner with separate reporting for different test tiers.

This module provides:
- Separate coverage tracking for 4 test tiers (unit, component, integration, scripts)
- Separate coverage between scripts/tests/ and tests/
- Per-function line and branch coverage validation
- Use-case coverage tracking for integration tests
- Glob pattern matching with negation support for source_paths

Test Tier Coverage Requirements:
- Unit tests (tests/unit/): 80% line/branch per function across app/ (excluding class fields)
- Component tests (tests/component/ or tests/unit/ with service focus): 80% line/branch
  per function for app/services/ only
- Integration tests (tests/integration/): 100% use-case coverage
- Scripts tests (scripts/tests/): Coverage for scripts/ and tools/

Coverage Calculation:
- Per-function coverage: Each function must individually meet the threshold
- Class fields (Pydantic model fields in contracts) are excluded
- Files with no functions can have 0% coverage (valid)

Glob Pattern Matching with Negation:
    Source paths in tier configurations support glob patterns with negation using '!' prefix:

    Example in pyproject.toml:
        [tool.test_coverage.tiers.unit]
        source_paths = ["app/**/*.py", "!app/**/__init__.py"]

    Pattern Processing:
        - Patterns without '!' add matching files to coverage measurement
        - Patterns with '!' remove matching files from coverage measurement
        - Patterns are processed in order for fine-grained control

    Implementation Functions:
        - expand_source_patterns(): Expands patterns to actual file paths (for debugging)
        - get_coverage_source_args(): Converts patterns to coverage.py --source and --omit args

    Example Conversions:
        Input:  ["app/**/*.py", "!app/**/__init__.py", "!app/api/**/router.py"]
        Output: --source=app --omit=app/**/__init__.py,app/api/**/router.py

        Input:  ["scripts/**/*.py", "!scripts/tests/**/*.py"]
        Output: --source=scripts --omit=scripts/tests/**/*.py

--no-validate Behavior:
    The --no-validate flag skips coverage threshold validation, but its effect differs
    between coverage types:

    Line/Branch Tiers (unit, component, scripts):
        - Coverage threshold checks are skipped (functions below threshold do not cause failure)
        - Test failures still cause tier_pass=0 (test execution results are always respected)
        - Coverage metrics are still collected and reported, just not enforced

    Usecase Tiers (integration):
        - Coverage threshold checks are skipped entirely
        - tier_pass is ALWAYS set to 1 when --no-validate is used
        - This is because usecase tiers do not track individual test pass/fail status;
          they only measure whether use-case markers exist in test files
        - Teams adding custom usecase tiers should be aware that --no-validate effectively
          disables all gating for usecase coverage

    Use --no-validate for exploratory runs or when you want coverage metrics without
    enforcement. Do not use it in CI pipelines that require coverage gates.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Default threshold values if not specified in pyproject.toml
DEFAULT_MIN_LINE_OVERALL = 80.0
DEFAULT_MIN_BRANCH_OVERALL = 70.0
DEFAULT_MIN_LINE_PER_FUNCTION = 60.0
DEFAULT_MIN_BRANCH_PER_FUNCTION = 50.0
DEFAULT_MIN_USECASE = 100.0

# Valid tier configuration properties
VALID_TIER_PROPERTIES = {
    "test_path",
    "source_paths",
    "min_line_overall",
    "min_branch_overall",
    "min_line_per_function",
    "min_branch_per_function",
    "min_usecase",
    "skip_private_functions",
    "exclude_class_fields",
}


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
    """Configuration for a test tier.

    Coverage type is determined dynamically based on which threshold fields are populated:
    - If min_line_per_function or min_branch_per_function is set: coverage_type = "line_branch"
    - If min_usecase is set: coverage_type = "usecase"
    - If both are set, line_branch takes priority

    Source path exclusions are specified using '!' prefix in source_paths, not via exclude_patterns.
    """

    name: str
    test_path: str
    source_paths: list[str]
    min_line_overall: float | None = None
    min_branch_overall: float | None = None
    min_line_per_function: float | None = None
    min_branch_per_function: float | None = None
    min_usecase: float | None = None
    skip_private_functions: bool = False
    exclude_class_fields: bool = True

    @property
    def coverage_type(self) -> str:
        """Infer coverage type from which threshold fields are populated.

        Returns:
            "line_branch" if line or branch per-function thresholds are set
            "usecase" if usecase threshold is set
            "line_branch" if both are set (line_branch takes priority)

        Raises:
            ValueError: If no threshold fields are set
        """
        has_line_branch = (
            self.min_line_per_function is not None or self.min_branch_per_function is not None
        )
        has_usecase = self.min_usecase is not None

        if has_line_branch:
            return "line_branch"
        elif has_usecase:
            return "usecase"
        else:
            raise ValueError(
                f"Tier '{self.name}' has no coverage thresholds set. "
                "At least one of min_line_per_function, min_branch_per_function, "
                "or min_usecase must be set."
            )


# Import modules after dataclass definitions to avoid circular imports
from scripts.dev.test_runner import coverage_db
from scripts.dev.test_runner.redundant_test_detector import (
    RedundantTestResult,
    detect_redundant_tests,
)


def load_tier_configs(pyproject_path: Path | None = None) -> dict[str, TestTierConfig]:
    """Load tier configurations from pyproject.toml.

    This is the single source of truth for loading tier configurations.
    All tiers must be defined in [tool.test_coverage.tiers.<tier_name>] sections
    with explicit test_path and source_paths fields.

    Coverage type is inferred from which threshold fields are populated:
    - min_line_per_function or min_branch_per_function -> "line_branch"
    - min_usecase -> "usecase"

    IMPORTANT: Tier order is determined by TOML file order. This function
    iterates directly over tiers_table.items() without sorting or set
    conversion to preserve the exact order from tomllib.load().

    Validation:
    - Checks for unknown properties against VALID_TIER_PROPERTIES
    - Validates required fields (test_path, source_paths)
    - Ensures at least one threshold type is set (line/branch or usecase)
    - Logs the inferred coverage type for each tier

    Args:
        pyproject_path: Path to pyproject.toml. Defaults to REPO_ROOT / "pyproject.toml".

    Returns:
        Mapping of tier names to TestTierConfig objects, in execution order.

    Raises:
        ValueError: If pyproject.toml is missing, has no tiers configured,
            if a tier contains unknown properties, is missing required fields,
            or has no coverage thresholds set.
    """
    path = pyproject_path or REPO_ROOT / "pyproject.toml"
    if not path.exists():
        raise ValueError(f"pyproject.toml not found at {path}")

    with path.open("rb") as f:
        data = tomllib.load(f)

    test_coverage = data.get("tool", {}).get("test_coverage", {})
    tiers_table = test_coverage.get("tiers")

    if tiers_table is None:
        raise ValueError(
            "No [tool.test_coverage.tiers] section found in pyproject.toml. "
            "All tiers must be defined in [tool.test_coverage.tiers.<tier_name>] sections."
        )

    result: dict[str, TestTierConfig] = {}
    # Iterate directly over items() - tomllib preserves TOML key order.
    # Do NOT use set(), sorted(), or list(set(...)) here.
    for tier_name, tier_data in tiers_table.items():
        # Validate for unknown properties without using set() to preserve order
        unknown_props = [key for key in tier_data if key not in VALID_TIER_PROPERTIES]
        if unknown_props:
            raise ValueError(
                f"Tier '{tier_name}' contains unknown properties: "
                f"{', '.join(unknown_props)}. "
                f"Valid properties are: {', '.join(VALID_TIER_PROPERTIES)}"
            )

        # Validate required fields
        test_path = tier_data.get("test_path")
        source_paths = tier_data.get("source_paths")

        if not test_path or not source_paths:
            missing = [f for f in ["test_path", "source_paths"] if not tier_data.get(f)]
            raise ValueError(f"Tier '{tier_name}' missing required fields: {', '.join(missing)}")

        # Validate at least one threshold type is set
        has_line_branch = (
            tier_data.get("min_line_per_function") is not None
            or tier_data.get("min_branch_per_function") is not None
        )
        has_usecase = tier_data.get("min_usecase") is not None

        if not has_line_branch and not has_usecase:
            raise ValueError(
                f"Tier '{tier_name}' has no coverage thresholds set. "
                "At least one of min_line_per_function, min_branch_per_function, "
                "or min_usecase must be set."
            )

        # Construct TestTierConfig directly with None defaults for threshold fields
        config = TestTierConfig(
            name=tier_name,
            test_path=test_path,
            source_paths=source_paths,
            min_line_overall=tier_data.get("min_line_overall"),
            min_branch_overall=tier_data.get("min_branch_overall"),
            min_line_per_function=tier_data.get("min_line_per_function"),
            min_branch_per_function=tier_data.get("min_branch_per_function"),
            min_usecase=tier_data.get("min_usecase"),
            skip_private_functions=tier_data.get("skip_private_functions", False),
            exclude_class_fields=tier_data.get("exclude_class_fields", True),
        )

        # Log which coverage type was inferred for this tier
        print(
            f"[tier-config] Tier '{tier_name}' configured with "
            f"coverage_type='{config.coverage_type}'"
        )

        result[tier_name] = config

    # Log discovered tiers
    tier_names = list(result.keys())
    print(f"[tier-config] Discovered tiers (in order): {tier_names}")
    return result


def expand_source_patterns(patterns: list[str], repo_root: Path) -> set[str]:
    """Expand glob patterns with negation support to a set of file paths.

    Takes a list of patterns where:
    - Patterns without '!' prefix add matching files to the result
    - Patterns with '!' prefix remove matching files from the result

    Patterns are processed in order, allowing for fine-grained control over
    what files are included in coverage measurement.

    This function is useful for debugging coverage configuration or when you need
    to know the exact set of files that will be measured. For normal coverage
    execution, use get_coverage_source_args() instead, which generates the
    appropriate --source and --omit arguments for coverage.py.

    Args:
        patterns: List of glob patterns like ["app/**/*.py", "!app/**/__init__.py"]
        repo_root: Repository root path to resolve patterns against

    Returns:
        Set of relative file paths (strings) that match the patterns after
        applying all inclusions and exclusions. Paths use forward slashes (/)
        for consistency across platforms.

    Examples:
        >>> patterns = ["app/**/*.py", "!app/**/__init__.py"]
        >>> expand_source_patterns(patterns, Path("/repo"))
        {'app/models.py', 'app/services/foo.py', ...}  # excludes __init__.py files

        >>> patterns = ["app/**/*.py", "!app/api/**/*.py", "app/api/health.py"]
        >>> expand_source_patterns(patterns, Path("/repo"))
        # Includes all app/*.py except app/api/*.py, but then adds back app/api/health.py

    Edge Cases:
        - Empty patterns list returns empty set
        - Patterns that match no files contribute nothing to the result
        - Only files (not directories) are included in the result
        - Paths outside repo_root are silently skipped
    """
    result: set[str] = set()

    for pattern in patterns:
        is_negation = pattern.startswith("!")
        glob_pattern = pattern[1:] if is_negation else pattern

        # Use pathlib's glob to find matching files
        # glob_pattern is relative to repo_root
        matches = repo_root.glob(glob_pattern)

        # Convert to relative paths (strings) from repo_root
        matched_files = set()
        for path in matches:
            if path.is_file():  # Only include actual files, not directories
                try:
                    rel_path = str(path.relative_to(repo_root))
                    # Normalize path separators to forward slashes for consistency
                    rel_path = rel_path.replace("\\", "/")
                    matched_files.add(rel_path)
                except ValueError:
                    # Path is not relative to repo_root, skip it
                    continue

        # Apply pattern based on negation flag
        if is_negation:
            result -= matched_files
        else:
            result |= matched_files

    return result


def get_coverage_source_args(
    config: TestTierConfig, repo_root: Path
) -> tuple[list[str], list[str]]:
    """Convert glob patterns with negation to coverage.py --source and --omit args.

    coverage.py uses directory-based --source and file-based --omit patterns.
    This function extracts base directories from include patterns and converts
    negation patterns to --omit patterns.

    The conversion handles the semantic difference between our pattern syntax
    and coverage.py's argument model:
    - Our patterns: "app/**/*.py" means "all Python files under app/"
    - coverage.py --source: Expects base directories like "app"
    - coverage.py --omit: Expects file patterns like "app/**/__init__.py"

    Args:
        config: Test tier configuration with source_paths containing patterns
            like ["app/**/*.py", "!app/**/__init__.py"]
        repo_root: Repository root path (currently unused, reserved for future use)

    Returns:
        Tuple of (source_dirs, omit_patterns):
        - source_dirs: Sorted list of base directories for --source argument
        - omit_patterns: List of glob patterns for --omit argument (order preserved)

    Examples:
        >>> config.source_paths = ["app/**/*.py", "!app/**/__init__.py", "!app/api/**/router.py"]
        >>> get_coverage_source_args(config, Path("/repo"))
        (['app'], ['app/**/__init__.py', 'app/api/**/router.py'])

        >>> config.source_paths = ["app/services/**/*.py", "app/models/**/*.py", "!**/__init__.py"]
        >>> get_coverage_source_args(config, Path("/repo"))
        (['app/models', 'app/services'], ['**/__init__.py'])

    Edge Cases:
        - Patterns with no base directory (e.g., "**/*.py") are ignored for --source
        - Multiple patterns can resolve to the same base directory (deduplicated)
        - Negation patterns are passed through to --omit unchanged (except removing '!')
    """
    source_dirs: set[str] = set()
    omit_patterns: list[str] = []

    for pattern in config.source_paths:
        is_negation = pattern.startswith("!")
        glob_pattern = pattern[1:] if is_negation else pattern

        if is_negation:
            # Convert negation pattern to omit pattern (just remove the '!' prefix)
            omit_patterns.append(glob_pattern)
        else:
            # Extract base directory from glob pattern
            # Examples:
            #   "app/**/*.py" -> "app"
            #   "scripts/**/*.py" -> "scripts"
            #   "app/services/**/*.py" -> "app/services"
            parts = glob_pattern.split("/")
            # Find the first part that doesn't contain glob characters
            base_parts = []
            for part in parts:
                if "*" in part or "?" in part or "[" in part:
                    break
                base_parts.append(part)

            if base_parts:
                base_dir = "/".join(base_parts)
                source_dirs.add(base_dir)

    return sorted(source_dirs), omit_patterns


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
    """Get test tier configurations from pyproject.toml.

    This is a convenience wrapper around load_tier_configs() that uses the
    default pyproject.toml path. For custom paths, use load_tier_configs() directly.
    """
    return load_tier_configs()


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


# -----------------------------------------------------------------------------
# LEGACY/BACKWARD-COMPATIBILITY FUNCTION
# This function is retained only for backward compatibility with external callers.
# It is NOT used by the new strategy classes (IntegrationTestStrategy).
# For internal use, prefer _scan_tests_for_usecases() which provides richer
# metadata (test file paths and function names) required for
# coverage_db.write_usecase_coverage().
# -----------------------------------------------------------------------------
def collect_covered_usecases(test_path: str) -> set[str]:
    """Collect use-case IDs from pytest markers in tests.

    .. deprecated::
        This function is retained for backward compatibility only.
        New code should use :func:`_scan_tests_for_usecases` instead,
        which returns richer metadata (test file and function names)
        required for ``coverage_db.write_usecase_coverage()``.

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


# -----------------------------------------------------------------------------
# DEPRECATED: Legacy validation helper retained for backward compatibility.
# All orchestrated runs (via main()) must use LineBranchTestStrategy.validate()
# from test_strategies.py instead. This function is kept only for external,
# non-main callers. It will be removed once all external callers migrate to
# the strategy pattern.
# -----------------------------------------------------------------------------
def validate_line_branch_coverage(
    result: CoverageResult,
    config: TestTierConfig,
) -> list[str]:
    """Validate per-function line and branch coverage.

    .. deprecated::
        This function is deprecated. Use :meth:`LineBranchTestStrategy.validate`
        from ``test_strategies.py`` instead. This function is retained only for
        backward compatibility with external callers that are not part of the
        main orchestration loop.

    Returns list of failure messages.
    """
    failures: list[str] = []

    for func_key, func_data in result.functions.items():
        func_name = func_data["name"]

        # Skip private functions if configured
        if config.skip_private_functions and _is_private_function(func_name):
            continue

        line_cov = func_data["line_coverage"]
        branch_cov = func_data["branch_coverage"]

        if config.min_line_per_function is not None and line_cov < config.min_line_per_function:
            failures.append(
                f"{config.name}: Function {func_key} line coverage "
                f"{line_cov:.1f}% < {config.min_line_per_function:.1f}% minimum"
            )

        if (
            config.min_branch_per_function is not None
            and branch_cov < config.min_branch_per_function
            and func_data.get("missing_branches")
        ):
            failures.append(
                f"{config.name}: Function {func_key} branch coverage "
                f"{branch_cov:.1f}% < {config.min_branch_per_function:.1f}% minimum"
            )

    return failures


# -----------------------------------------------------------------------------
# DEPRECATED: Legacy validation helper retained for backward compatibility.
# All orchestrated runs (via main()) must use IntegrationTestStrategy.validate()
# from test_strategies.py instead. This function is kept only for external,
# non-main callers. It will be removed once all external callers migrate to
# the strategy pattern.
# -----------------------------------------------------------------------------
def validate_usecase_coverage(
    uc_result: UseCaseCoverageResult,
    config: TestTierConfig,
) -> list[str]:
    """Validate use-case coverage.

    .. deprecated::
        This function is deprecated. Use :meth:`IntegrationTestStrategy.validate`
        from ``test_strategies.py`` instead. This function is retained only for
        backward compatibility with external callers that are not part of the
        main orchestration loop.

    Returns list of failure messages.
    """
    failures: list[str] = []

    if config.min_usecase is not None and uc_result.coverage_pct < config.min_usecase:
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
        default="all",
        help="Which test tier to run. Valid tiers are derived from [tool.test_coverage.*] "
        "in pyproject.toml (e.g., unit, component, integration, scripts). Use 'all' to run "
        "all configured tiers. To see currently available tier names, run "
        "'uv run test-coverage --tier all' or pass an invalid tier name to see the error message.",
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
        help="Skip coverage threshold validation. For line/branch tiers, disables coverage "
        "gating but test failures still cause tier_pass=0. For usecase tiers, disables "
        "all gating and tier_pass is always 1 (use-case coverage is reported but not enforced).",
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


# =============================================================================
# ORCHESTRATOR INVARIANTS - main() delegates all tier-specific logic to strategies
#
# These invariants ensure main() remains a thin orchestrator, not a decision-maker:
#
# 1. NO COVERAGE-TYPE BRANCHING: main() must NOT branch on config.coverage_type for
#    core execution or validation logic. The factory (create_strategy) handles type
#    dispatch. main()'s ONLY tier-specific code is read-only presentation logic
#    (print_summary, JSON report).
#
# 2. NO DIRECT VALIDATION CALLS: main() must NOT call validate_line_branch_coverage()
#    or validate_usecase_coverage() directly. All threshold checking is delegated to
#    strategy.validate().
#
# 3. NO SUMMARY FIELD COMPUTATION: main() must NOT compute passing_functions,
#    failing_functions, or tier_pass itself. These values come exclusively from
#    strategy.build_summary(). The returned dict is opaque to main().
#
# 4. STRATEGY OWNERSHIP: Validation logic and summary construction are OWNED BY
#    STRATEGIES. main() only orchestrates the lifecycle: run_tests() ->
#    collect_results() -> validate() -> build_summary().
#
# 5. STRATEGY SUMMARIES ARE OPAQUE: main() must pass strategy.build_summary() output
#    directly to coverage_db.write_tier_summary() without inspection or modification.
#
# See also: test_strategies.py module docstring for complementary invariants about
# pytest command construction and tier_pass ownership within strategies.
# =============================================================================
def main() -> int:
    """Run test coverage analysis and validation."""
    # Import strategy pattern (deferred to avoid circular import at module level)
    from scripts.dev.test_runner.test_strategies import TestStrategy, create_strategy

    args = parse_args()

    # Set up coverage database path (.coverage/coverage.db)
    coverage_dir = REPO_ROOT / ".coverage"
    coverage_dir.mkdir(parents=True, exist_ok=True)
    coverage_db_path = coverage_dir / "coverage.db"

    # Initialize custom tables and clear previous run data
    coverage_db.init_custom_tables(coverage_db_path)
    coverage_db.clear_custom_tables(coverage_db_path)

    # Load use cases for integration/e2e coverage
    use_cases_path = REPO_ROOT / "tests" / "docs" / "use_cases.yaml"
    use_cases = load_use_cases(use_cases_path)

    # Write use case registry to database
    if use_cases:
        coverage_db.write_usecase_registry(coverage_db_path, use_cases)

    # Get tier configurations from settings (fail fast on config errors)
    try:
        test_tiers = get_test_tiers()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    # Validate --tier argument against available tiers
    if args.tier != "all" and args.tier not in test_tiers:
        available = ", ".join(sorted(test_tiers.keys()))
        print(f"ERROR: Unknown tier '{args.tier}'. Available tiers: {available}")
        return 1

    # Determine which tiers to run
    tiers_to_run = list(test_tiers.keys()) if args.tier == "all" else [args.tier]

    # =============================================================================
    # COVERAGE ISOLATION ARCHITECTURE
    #
    # Per-Tier Isolation:
    #   Each tier writes coverage to an isolated file: .coverage/data_{tier_name}
    #   This ensures tier-specific validation only considers lines executed by
    #   that tier's tests, eliminating cross-tier contamination.
    #
    # Global Aggregation:
    #   After all tiers complete, `coverage combine` merges per-tier files into
    #   .coverage/data (the combined database). This combined database is used for:
    #   - Missing-line analysis (generate_missing_line_details)
    #   - Redundant test detection (detect_redundant_tests)
    #
    # Why This Design:
    #   - Prevents coverage leakage: Lines covered by unit tests won't artificially
    #     inflate component test coverage metrics
    #   - Preserves global visibility: Missing-line reports show all uncovered lines
    #     across the entire codebase, not just one tier
    #   - Supports redundancy analysis: Detecting tests with no unique coverage
    #     requires seeing all test contexts in one database
    # =============================================================================

    # Precompute tier-specific coverage file paths for isolation
    tier_coverage_files: dict[str, Path] = {
        tier_name: coverage_dir / f"data_{tier_name}" for tier_name in tiers_to_run
    }

    # Log tier-to-coverage-file mapping
    print("\n[coverage-isolation] Tier coverage file mapping:")
    for tier_name, cov_file in tier_coverage_files.items():
        print(f"[coverage-isolation]   {tier_name} -> {cov_file}")

    # INVARIANT: This loop does not branch on config.coverage_type
    # Strategy instantiation and CLI threshold overrides
    strategies: list[TestStrategy] = []
    for tier_name in tiers_to_run:
        config = test_tiers[tier_name]

        # Apply CLI threshold overrides to each TestTierConfig
        if args.min_line != DEFAULT_MIN_LINE_PER_FUNCTION:
            config.min_line_per_function = args.min_line
        if args.min_branch != DEFAULT_MIN_BRANCH_PER_FUNCTION:
            config.min_branch_per_function = args.min_branch
        if args.min_usecase != DEFAULT_MIN_USECASE:
            config.min_usecase = args.min_usecase

        # main() passes all parameters - create_strategy() routes them appropriately
        # based on config.coverage_type. main() does NOT branch on coverage type.
        strategy = create_strategy(
            config,
            coverage_db_path,
            REPO_ROOT,
            tier_coverage_file=tier_coverage_files[tier_name],
            use_cases=use_cases,
        )
        strategies.append(strategy)

    # Execute strategies uniformly - NO coverage_type inspection
    all_failures: list[str] = []
    for strategy in strategies:
        strategy.run_tests()
        strategy.collect_results()
        # NOTE: Skipping validation when --no-validate is passed intentionally prevents
        # coverage failures from affecting tier_pass in build_summary().
        if not args.no_validate:
            all_failures.extend(strategy.validate())

    if not strategies:
        print("ERROR: No coverage results collected")
        return 1

    # Combine per-tier coverage data into single database for global reports
    # This combined database is used for missing-line analysis and redundant test detection
    combined_coverage_file = coverage_dir / "data"
    tier_data_files = [
        str(tier_coverage_files[t]) for t in tiers_to_run if tier_coverage_files[t].exists()
    ]
    if tier_data_files:
        print("\n" + "=" * 70)
        print("Combining per-tier coverage data into single database...")
        print("=" * 70)
        # Log input files
        print(f"[coverage-combine] Input files: {tier_data_files}")
        print(f"[coverage-combine] Output file: {combined_coverage_file}")
        combine_cmd = [
            "uv",
            "run",
            "python",
            "-m",
            "coverage",
            "combine",
            "--keep",  # Keep source files after combining
            *tier_data_files,
        ]
        combine_env = {"COVERAGE_FILE": str(combined_coverage_file)}
        _run_command(combine_cmd, capture=True, env=combine_env)
        print("[coverage-combine] Combine completed successfully")

    # Write run metadata
    coverage_db.write_run_metadata(coverage_db_path, REPO_ROOT)

    # Generate and write missing line details with context
    # Generate JSON report from combined coverage database to extract missing lines
    json_output_path = coverage_dir / "temp_missing_lines.json"
    cov_env = {"COVERAGE_FILE": str(combined_coverage_file)}
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

    # Write tier summaries - strategy owns ALL summary computation
    for strategy in strategies:
        summary = strategy.build_summary()
        # IMMEDIATELY pass to DB writer - no inspection or modification
        coverage_db.write_tier_summary(coverage_db_path, strategy.config.name, summary)

    # For print_summary() and JSON report ONLY (read-only presentation)
    line_branch_results: list[tuple[TestTierConfig, CoverageResult]] = [
        (s.config, s.coverage_result) for s in strategies if s.coverage_result is not None
    ]
    usecase_results: list[tuple[TestTierConfig, UseCaseCoverageResult]] = [
        (s.config, s.usecase_result) for s in strategies if s.usecase_result is not None
    ]

    # Run redundant test detection
    redundant_result: RedundantTestResult | None = None
    if not args.skip_redundant_detection and combined_coverage_file.exists():
        # The coverage data file is now at .coverage/data (combined from all tiers)
        print("\n" + "=" * 70)
        print("Analyzing test coverage for redundant tests...")
        print("=" * 70)
        redundant_result = detect_redundant_tests(
            combined_coverage_file,  # Use combined database for global analysis
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
