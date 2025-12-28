"""Find all test files affected by changes to a source file.

Uses transitive import graph analysis to find all test files that
directly or indirectly depend on a given source file.

Uses Python 3.14 free-threading for parallel file parsing.

Usage:
    uv run pr affected-tests app/services/auth.py
    uv run pr affected-tests app/services/auth.py --root /path/to/repo
"""

from __future__ import annotations

import ast
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Use available CPUs for parallel parsing
_NUM_WORKERS = min(32, (os.cpu_count() or 1) + 4)


def _parse_imports(file_path: Path) -> tuple[Path, set[str]]:
    """Parse a Python file and extract all imported module paths.

    Args:
        file_path: Path to the Python file.

    Returns:
        Tuple of (file_path, set of imported module paths).
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return (file_path, set())

    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            # Also add fully qualified names for specific imports
            for alias in node.names:
                if alias.name != "*":
                    imports.add(f"{node.module}.{alias.name}")

    return (file_path, imports)


def _module_path_to_file(module_path: str, root: Path) -> Path | None:
    """Convert a module path to a file path.

    Args:
        module_path: Dot-separated module path (e.g., 'app.services.auth').
        root: Repository root.

    Returns:
        Path to the module file, or None if not found.
    """
    # Try as a module file
    parts = module_path.split(".")

    # Try module.py
    file_path = root / Path(*parts).with_suffix(".py")
    if file_path.exists():
        return file_path

    # Try package/__init__.py
    package_init = root / Path(*parts) / "__init__.py"
    if package_init.exists():
        return package_init

    return None


def _file_to_module_path(file_path: Path, root: Path) -> str | None:
    """Convert a file path to a module path.

    Args:
        file_path: Path to the Python file.
        root: Repository root.

    Returns:
        Dot-separated module path, or None if not in root.
    """
    try:
        rel_path = file_path.relative_to(root)
    except ValueError:
        return None

    # Remove .py extension and convert to dots
    if rel_path.name == "__init__.py":
        parts = rel_path.parent.parts
    else:
        parts = rel_path.with_suffix("").parts

    if not parts:
        return None

    return ".".join(parts)


def _is_test_file(path: Path) -> bool:
    """Check if a path is a test file.

    Args:
        path: Path to check.

    Returns:
        True if this is a test file.
    """
    path_str = str(path)

    # Check if in test directories
    if "/tests/" in path_str or "/scripts/tests/" in path_str:
        return True

    # Check for test_ prefix in filename
    if path.name.startswith("test_"):
        return True

    # Check for _test suffix
    return bool(path.stem.endswith("_test"))


def _collect_python_files(root: Path) -> list[Path]:
    """Collect all Python files to analyze, excluding non-source directories.

    Args:
        root: Repository root.

    Returns:
        List of Python file paths.
    """
    skip_patterns = frozenset(
        {
            ".venv",
            "venv",
            ".git",
            "node_modules",
            "__pycache__",
            "build",
            "dist",
            ".tox",
            ".eggs",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
        }
    )

    py_files: list[Path] = []
    for py_file in root.rglob("*.py"):
        # Check if any parent directory is in skip list
        if not any(part in skip_patterns for part in py_file.parts):
            py_files.append(py_file)

    return py_files


def _build_import_graph(root: Path) -> dict[str, set[str]]:
    """Build a graph of module dependencies using parallel file parsing.

    Uses ThreadPoolExecutor for parallel AST parsing (Python 3.14 free-threading).

    Args:
        root: Repository root.

    Returns:
        Dict mapping module_path -> set of module_paths it imports.
    """
    graph: dict[str, set[str]] = defaultdict(set)

    # Collect files first
    py_files = _collect_python_files(root)

    # Parse imports in parallel
    with ThreadPoolExecutor(max_workers=_NUM_WORKERS) as executor:
        results = executor.map(_parse_imports, py_files)

    # Build graph from results
    for py_file, imports in results:
        module_path = _file_to_module_path(py_file, root)
        if not module_path:
            continue

        # Filter to imports that are local modules (exist in repo)
        for imp in imports:
            # Check if this import corresponds to a file in the repo
            imp_file = _module_path_to_file(imp, root)
            if imp_file:
                imp_module = _file_to_module_path(imp_file, root)
                if imp_module:
                    graph[module_path].add(imp_module)

            # Also try parent modules (for 'from app.services import auth')
            parts = imp.split(".")
            for i in range(len(parts), 0, -1):
                partial = ".".join(parts[:i])
                partial_file = _module_path_to_file(partial, root)
                if partial_file:
                    partial_module = _file_to_module_path(partial_file, root)
                    if partial_module:
                        graph[module_path].add(partial_module)
                        break

    return dict(graph)


def _invert_graph(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    """Invert a dependency graph.

    Args:
        graph: Dict mapping module -> modules it imports.

    Returns:
        Dict mapping module -> modules that import it.
    """
    inverted: dict[str, set[str]] = defaultdict(set)

    for module, deps in graph.items():
        for dep in deps:
            inverted[dep].add(module)

    return dict(inverted)


def _transitive_dependents(module: str, inverted_graph: dict[str, set[str]]) -> set[str]:
    """Find all modules that transitively depend on a given module.

    Args:
        module: The module to find dependents for.
        inverted_graph: Dict mapping module -> modules that import it.

    Returns:
        Set of all modules that directly or transitively depend on module.
    """
    dependents: set[str] = set()
    to_visit = [module]
    visited: set[str] = set()

    while to_visit:
        current = to_visit.pop()
        if current in visited:
            continue
        visited.add(current)

        direct_dependents = inverted_graph.get(current, set())
        for dep in direct_dependents:
            if dep not in dependents:
                dependents.add(dep)
                to_visit.append(dep)

    return dependents


def affected_tests_command(file_path: str, root: str | None = None) -> int:
    """Find all test files affected by changes to a source file.

    Uses transitive import analysis to find all tests that depend on
    the given file, directly or indirectly.

    Args:
        file_path: Path to the source file.
        root: Repository root (defaults to cwd).

    Returns:
        Exit code (0 for success).
    """
    root_path = Path(root) if root else Path.cwd()
    source_path = Path(file_path)

    # Make absolute if relative
    if not source_path.is_absolute():
        source_path = root_path / source_path

    # Check if file exists
    if not source_path.exists():
        print(
            json.dumps(
                {
                    "file": file_path,
                    "error": "file does not exist",
                    "test_files": [],
                }
            )
        )
        return 1

    # If input is already a test file, return it
    if _is_test_file(source_path):
        print(
            json.dumps(
                {
                    "file": file_path,
                    "test_files": [str(source_path)],
                    "method": "input_is_test",
                }
            )
        )
        return 0

    # Get module path for the source file
    source_module = _file_to_module_path(source_path, root_path)
    if not source_module:
        print(
            json.dumps(
                {
                    "file": file_path,
                    "error": "could not determine module path",
                    "test_files": [],
                }
            )
        )
        return 1

    # Build import graph
    graph = _build_import_graph(root_path)

    # Invert to get "who imports me" relationships
    inverted = _invert_graph(graph)

    # Find all transitive dependents
    dependents = _transitive_dependents(source_module, inverted)

    # Also include the source module itself (tests might import it directly)
    dependents.add(source_module)

    # Convert back to file paths and filter to test files
    test_files: list[str] = []
    for module in dependents:
        module_file = _module_path_to_file(module, root_path)
        if module_file and _is_test_file(module_file):
            test_files.append(str(module_file))

    # Sort for consistent output
    test_files.sort()

    print(
        json.dumps(
            {
                "file": file_path,
                "module": source_module,
                "test_files": test_files,
                "count": len(test_files),
            }
        )
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: uv run pr affected-tests <file_path> [--root <dir>]",
            file=sys.stderr,
        )
        sys.exit(1)

    file_arg = sys.argv[1]
    root_arg = None

    if "--root" in sys.argv:
        idx = sys.argv.index("--root")
        if idx + 1 < len(sys.argv):
            root_arg = sys.argv[idx + 1]

    sys.exit(affected_tests_command(file_arg, root_arg))
