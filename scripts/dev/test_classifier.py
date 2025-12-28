"""Classify test files by suite type (unit, component, integration).

Analyzes test files to determine their type based on:
- Presence of @patch decorators or patch() calls → unit test
- No patches but tests single module → unit test
- Tests multiple modules together → component test
- Calls external services → integration test

Usage:
    uv run python -m scripts.dev.test_classifier scripts/tests/
    uv run python -m scripts.dev.test_classifier scripts/tests/ --output report.json
"""

from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class TestType(Enum):
    """Classification of test type."""

    UNIT = "unit"  # Tests single function/class with mocks
    COMPONENT = "component"  # Tests multiple modules together
    INTEGRATION = "integration"  # Tests with external services
    UNKNOWN = "unknown"  # Cannot determine


@dataclass
class TestFunction:
    """Information about a single test function."""

    name: str
    has_patch_decorator: bool = False
    has_patch_context: bool = False
    has_mock_fixture: bool = False
    imports_used: set[str] = field(default_factory=set)
    external_calls: set[str] = field(default_factory=set)
    enclosing_class: str | None = None

    @property
    def has_patches(self) -> bool:
        """Check if test has any form of patching or mocking."""
        return self.has_patch_decorator or self.has_patch_context or self.has_mock_fixture

    @property
    def qualified_name(self) -> str:
        """Return qualified name (ClassName.method_name) if inside a class."""
        if self.enclosing_class:
            return f"{self.enclosing_class}.{self.name}"
        return self.name


@dataclass
class TestFileAnalysis:
    """Analysis result for a test file."""

    path: Path
    module_imports: set[str] = field(default_factory=set)
    patch_targets: set[str] = field(default_factory=set)
    test_functions: list[TestFunction] = field(default_factory=list)
    suggested_type: TestType = TestType.UNKNOWN
    suggested_path: Path | None = None
    reason: str = ""


class TestAnalyzer(ast.NodeVisitor):
    """AST visitor to analyze test files."""

    # Patterns that indicate external service calls
    EXTERNAL_PATTERNS = frozenset(
        {
            "requests",
            "httpx",
            "aiohttp",
            "urllib",
            "socket",
            "subprocess",
            "os.system",
            "redis",
            "pymongo",
            "psycopg",
            "sqlalchemy.create_engine",
            "boto3",
            "google.cloud",
        }
    )

    # Mock/patch related names
    PATCH_NAMES = frozenset(
        {
            "patch",
            "Mock",
            "MagicMock",
            "AsyncMock",
            "PropertyMock",
            "mock_open",
            "create_autospec",
        }
    )

    def __init__(self) -> None:
        """Initialize TestAnalyzer."""
        self.imports: set[str] = set()
        self.patch_targets: set[str] = set()
        self.test_functions: list[TestFunction] = []
        self._current_function: TestFunction | None = None
        self._class_stack: list[str] = []  # Track nested class names

    def visit_Import(self, node: ast.Import) -> None:
        """Visit Import node and track imports."""
        for alias in node.names:
            self.imports.add(alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Visit ImportFrom node and track imports."""
        if node.module:
            self.imports.add(node.module.split(".")[0])
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track class context for qualified function names."""
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit FunctionDef node and analyze test functions."""
        if node.name.startswith("test_"):
            self._analyze_test_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit AsyncFunctionDef node and analyze test functions."""
        if node.name.startswith("test_"):
            self._analyze_test_function(node)
        self.generic_visit(node)

    def _analyze_test_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Get innermost enclosing class (last in stack)
        enclosing = self._class_stack[-1] if self._class_stack else None
        func = TestFunction(name=node.name, enclosing_class=enclosing)

        # Check decorators for @patch
        for decorator in node.decorator_list:
            if self._is_patch_decorator(decorator):
                func.has_patch_decorator = True
                target = self._extract_patch_target(decorator)
                if target:
                    self.patch_targets.add(target)

        # Check function arguments for mock fixtures
        for arg in node.args.args:
            arg_name = arg.arg.lower()
            if "mock" in arg_name or "patch" in arg_name or "fake" in arg_name:
                func.has_mock_fixture = True

        # Check function body for patch() context managers and calls
        for child in ast.walk(node):
            if isinstance(child, ast.With):
                for item in child.items:
                    if self._is_patch_call(item.context_expr):
                        func.has_patch_context = True
                        target = self._extract_call_target(item.context_expr)
                        if target:
                            self.patch_targets.add(target)

        self.test_functions.append(func)

    def _is_patch_decorator(self, node: ast.expr) -> bool:
        """Check if a decorator is a patch decorator."""
        if isinstance(node, ast.Call):
            return self._is_patch_call(node)
        if isinstance(node, ast.Attribute):
            return node.attr in self.PATCH_NAMES
        if isinstance(node, ast.Name):
            return node.id in self.PATCH_NAMES
        return False

    def _is_patch_call(self, node: ast.expr) -> bool:
        """Check if an expression is a patch() call."""
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr in self.PATCH_NAMES
        if isinstance(func, ast.Name):
            return func.id in self.PATCH_NAMES
        return False

    def _extract_patch_target(self, node: ast.expr) -> str | None:
        """Extract the target path from a @patch decorator."""
        if isinstance(node, ast.Call) and node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                return first_arg.value
        return None

    def _extract_call_target(self, node: ast.expr) -> str | None:
        """Extract target from patch() call."""
        if isinstance(node, ast.Call) and node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                return first_arg.value
        return None


def analyze_test_file(file_path: Path) -> TestFileAnalysis:
    """Analyze a single test file.

    Args:
        file_path: Path to the test file.

    Returns:
        Analysis result.
    """
    analysis = TestFileAnalysis(path=file_path)

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError) as e:
        analysis.reason = f"Failed to parse: {e}"
        return analysis

    analyzer = TestAnalyzer()
    analyzer.visit(tree)

    analysis.module_imports = analyzer.imports
    analysis.patch_targets = analyzer.patch_targets
    analysis.test_functions = analyzer.test_functions

    # Classify the file
    analysis.suggested_type, analysis.reason = _classify_test_file(analysis)

    # Suggest new path
    analysis.suggested_path = _suggest_new_path(file_path, analysis.suggested_type)

    return analysis


def _classify_test_file(analysis: TestFileAnalysis) -> tuple[TestType, str]:
    """Classify a test file based on its analysis.

    Args:
        analysis: The file analysis.

    Returns:
        Tuple of (test type, reason).
    """
    # Standard library modules to ignore
    STDLIB = frozenset(
        {
            "__future__",
            "abc",
            "argparse",
            "ast",
            "asyncio",
            "base64",
            "builtins",
            "collections",
            "contextlib",
            "copy",
            "csv",
            "dataclasses",
            "datetime",
            "enum",
            "functools",
            "hashlib",
            "io",
            "itertools",
            "json",
            "logging",
            "math",
            "os",
            "pathlib",
            "pickle",
            "random",
            "re",
            "shutil",
            "socket",
            "string",
            "subprocess",
            "sys",
            "tempfile",
            "textwrap",
            "threading",
            "time",
            "traceback",
            "typing",
            "unittest",
            "urllib",
            "uuid",
            "warnings",
            "weakref",
            "xml",
            "zipfile",
        }
    )

    # Test-related modules to ignore
    TEST_MODULES = frozenset(
        {
            "pytest",
            "pyfakefs",
            "unittest",
            "mock",
            "fakeredis",
            "responses",
            "httpretty",
            "freezegun",
            "factory",
            "faker",
        }
    )

    if not analysis.test_functions:
        return TestType.UNKNOWN, "No test functions found"

    # Count functions with patches
    patched_count = sum(1 for f in analysis.test_functions if f.has_patches)
    total_count = len(analysis.test_functions)

    # Filter to actual project imports
    project_imports = analysis.module_imports - STDLIB - TEST_MODULES

    # Check for external service imports (only if NOT patched)
    external_imports = analysis.module_imports & {
        "requests",
        "httpx",
        "aiohttp",
        "redis",
        "pymongo",
        "psycopg",
        "boto3",
    }

    if external_imports:
        # If has external imports but all tests have patches, still unit
        if patched_count == total_count:
            return TestType.UNIT, f"All {total_count} tests use patches (external imports mocked)"
        # Check if external libs are in patch targets
        patched_externals = {t.split(".")[0] for t in analysis.patch_targets}
        if external_imports <= patched_externals:
            return TestType.UNIT, f"External imports are mocked: {external_imports}"
        return TestType.INTEGRATION, f"Uses external services: {external_imports}"

    # Check patch targets to see how many PROJECT modules are being patched
    if analysis.patch_targets:
        target_modules = {
            t.split(".")[0]
            for t in analysis.patch_targets
            if "." in t and t.split(".")[0] in ("app", "scripts")
        }
        if len(target_modules) > 1:
            return TestType.COMPONENT, f"Patches multiple project modules: {target_modules}"

    # If most tests have patches, it's unit
    if patched_count > 0:
        if patched_count == total_count:
            return TestType.UNIT, f"All {total_count} tests use patches"
        if patched_count / total_count >= 0.5:
            return TestType.UNIT, f"{patched_count}/{total_count} tests use patches"

    # No patches - check project imports
    actual_project_imports = {imp for imp in project_imports if imp in ("app", "scripts")}

    if len(actual_project_imports) <= 1:
        return TestType.UNIT, "Tests single module without patches (pure function tests)"

    return TestType.COMPONENT, f"Imports multiple project roots: {actual_project_imports}"


def _suggest_new_path(original_path: Path, test_type: TestType) -> Path | None:
    """Suggest a new path for the test file based on its type.

    Args:
        original_path: Current path of the test file.
        test_type: Classified test type.

    Returns:
        Suggested new path, or None if no move needed.
    """
    if test_type == TestType.UNKNOWN:
        return None

    path_str = str(original_path)

    # Already in correct location?
    if f"/tests/{test_type.value}/" in path_str:
        return None
    if f"/scripts/tests/{test_type.value}/" in path_str:
        return None

    # Determine base test directory
    if "/scripts/tests/" in path_str:
        # scripts/tests/foo/test_bar.py -> scripts/tests/unit/foo/test_bar.py
        parts = original_path.parts
        try:
            tests_idx = parts.index("tests")
            # Insert test type after "tests"
            new_parts = (*parts[: tests_idx + 1], test_type.value, *parts[tests_idx + 1 :])
            return Path(*new_parts)
        except ValueError:
            return None

    if "/tests/" in path_str:
        # tests/foo/test_bar.py -> tests/unit/foo/test_bar.py
        parts = original_path.parts
        try:
            tests_idx = parts.index("tests")
            # Check if already has type subdirectory
            if tests_idx + 1 < len(parts) and parts[tests_idx + 1] in (
                "unit",
                "component",
                "integration",
            ):
                return None
            new_parts = (*parts[: tests_idx + 1], test_type.value, *parts[tests_idx + 1 :])
            return Path(*new_parts)
        except ValueError:
            return None

    return None


def analyze_directory(test_dir: Path, num_workers: int = 8) -> dict[str, list[TestFileAnalysis]]:
    """Analyze all test files in a directory.

    Args:
        test_dir: Directory containing test files.
        num_workers: Number of parallel workers.

    Returns:
        Dict mapping test type to list of analyses.
    """
    # Find all test files
    test_files = list(test_dir.rglob("test_*.py"))

    # Analyze in parallel
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        analyses = list(executor.map(analyze_test_file, test_files))

    # Group by suggested type
    by_type: dict[str, list[TestFileAnalysis]] = defaultdict(list)
    for analysis in analyses:
        by_type[analysis.suggested_type.value].append(analysis)

    return dict(by_type)


def _classify_function(func: TestFunction) -> TestType:
    """Classify a single test function.

    Args:
        func: The test function analysis.

    Returns:
        The test type.
    """
    if func.has_patches:
        return TestType.UNIT
    # No patches - could be unit (pure function) or needs more context
    return TestType.UNKNOWN


def analyze_mixed_files(analyses: list[TestFileAnalysis]) -> list[dict[str, str | list[str] | int]]:
    """Find files that contain mixed test types and need splitting.

    Args:
        analyses: List of file analyses.

    Returns:
        List of files with mixed content.
    """
    mixed_files: list[dict[str, str | list[str] | int]] = []

    for analysis in analyses:
        if len(analysis.test_functions) < 2:
            continue

        # Classify each function
        func_types: dict[str, list[str]] = {
            "unit": [],
            "unknown": [],
        }

        for func in analysis.test_functions:
            func_type = _classify_function(func)
            func_types[func_type.value].append(func.name)

        # Check if mixed
        has_unit = len(func_types["unit"]) > 0
        has_unknown = len(func_types["unknown"]) > 0

        if has_unit and has_unknown:
            mixed_files.append(
                {
                    "path": str(analysis.path),
                    "unit_tests": func_types["unit"],
                    "unknown_tests": func_types["unknown"],
                    "unit_count": len(func_types["unit"]),
                    "unknown_count": len(func_types["unknown"]),
                }
            )

    return mixed_files


def generate_report(
    by_type: dict[str, list[TestFileAnalysis]],
) -> dict[str, Any]:
    """Generate a JSON-serializable report.

    Args:
        by_type: Analyses grouped by type.

    Returns:
        Report dictionary.
    """
    all_analyses = [a for analyses in by_type.values() for a in analyses]

    report: dict[str, Any] = {
        "summary": {test_type: len(analyses) for test_type, analyses in by_type.items()},
        "mixed_files": analyze_mixed_files(all_analyses),
        "files": {},
    }

    files_dict: dict[str, list[dict[str, Any]]] = report["files"]
    for test_type, analyses in by_type.items():
        files_dict[test_type] = [
            {
                "path": str(a.path),
                "suggested_path": str(a.suggested_path) if a.suggested_path else None,
                "reason": a.reason,
                "test_count": len(a.test_functions),
                "patched_tests": sum(1 for f in a.test_functions if f.has_patches),
                "patch_targets": list(a.patch_targets)[:10],  # Limit for readability
                "functions": [
                    {
                        "name": f.name,
                        "has_patches": f.has_patches,
                        "type": _classify_function(f).value,
                    }
                    for f in a.test_functions
                ],
            }
            for a in sorted(analyses, key=lambda x: str(x.path))
        ]

    return report


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Classify test files by suite type")
    parser.add_argument("test_dir", type=Path, help="Directory containing test files")
    parser.add_argument("--output", "-o", type=Path, help="Output JSON file")
    parser.add_argument("--workers", "-w", type=int, default=8, help="Parallel workers")

    args = parser.parse_args(argv)

    if not args.test_dir.exists():
        print(f"Error: {args.test_dir} does not exist", file=sys.stderr)
        return 1

    print(f"Analyzing {args.test_dir}...")
    by_type = analyze_directory(args.test_dir, args.workers)

    report = generate_report(by_type)

    # Print summary
    print("\n=== File-level Summary ===")
    for test_type, count in report["summary"].items():
        print(f"  {test_type}: {count} files")

    # Print mixed files that need splitting
    if report["mixed_files"]:
        print(f"\n=== Mixed Files (need splitting): {len(report['mixed_files'])} ===")
        for mf in report["mixed_files"][:30]:
            print(f"\n  {mf['path']}")
            print(f"    Unit tests ({mf['unit_count']}): {', '.join(mf['unit_tests'][:5])}")
            if mf["unit_count"] > 5:
                print(f"      ... and {mf['unit_count'] - 5} more")
            print(
                f"    Unknown tests ({mf['unknown_count']}): {', '.join(mf['unknown_tests'][:5])}"
            )
            if mf["unknown_count"] > 5:
                print(f"      ... and {mf['unknown_count'] - 5} more")
        if len(report["mixed_files"]) > 30:
            print(f"\n  ... and {len(report['mixed_files']) - 30} more mixed files")

    # Count total functions by type
    total_unit = 0
    total_unknown = 0
    for files in report["files"].values():
        for f in files:
            for func in f.get("functions", []):
                if func["type"] == "unit":
                    total_unit += 1
                elif func["type"] == "unknown":
                    total_unknown += 1

    print("\n=== Function-level Summary ===")
    print(f"  Unit tests (have patches): {total_unit}")
    print(f"  Unknown (no patches): {total_unknown}")
    print(f"  Total: {total_unit + total_unknown}")

    # Write full report
    if args.output:
        args.output.write_text(json.dumps(report, indent=2))
        print(f"\nFull report written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
