"""Determine if a file requires testing.

Analyzes file path and content to determine if a file needs tests.
Uses AST parsing for Python files to detect testable constructs.

Usage:
    uv run pr is-testable path/to/file.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

# File extensions that are never testable (configuration, documentation, etc.)
NON_TESTABLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".toml",
        ".ini",
        ".yaml",
        ".yml",
        ".json",
        ".md",
        ".rst",
        ".txt",
        ".cfg",
        ".env",
        ".pyi",  # Type stubs
        ".sql",
        ".graphql",
        ".proto",
        ".pyc",
    }
)

# Path patterns that indicate non-testable files
NON_TESTABLE_PATH_PATTERNS: tuple[str, ...] = (
    "migrations/",
    "versions/",
    "alembic/versions/",
    "generated/",
    "vendor/",
    "third_party/",
    "node_modules/",
    "build/",
    "dist/",
    "__pycache__/",
)

# File name patterns that indicate non-testable files
NON_TESTABLE_NAME_PATTERNS: tuple[str, ...] = (
    "_generated.py",
    "_pb2.py",
    "_pb2_grpc.py",
)


def _has_testable_constructs(source: str) -> tuple[bool, str]:
    """Check if Python source has testable constructs using AST.

    A file is testable if it contains:
    - Function definitions (def)
    - Class definitions with methods
    - Executable __main__ block with actual code

    Args:
        source: Python source code to analyze.

    Returns:
        Tuple of (is_testable, reason).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        # If we can't parse it, assume it's testable (let tests find the error)
        return True, f"syntax error during parsing: {e}"

    has_functions = False
    has_classes_with_methods = False
    has_main_block = False

    for node in ast.walk(tree):
        # Check for function definitions at module level or in classes
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            has_functions = True
            break

        # Check for class definitions
        if isinstance(node, ast.ClassDef):
            # Check if class has any methods
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    has_classes_with_methods = True
                    break
            if has_classes_with_methods:
                break

    # Check for executable __main__ block
    for node in tree.body:
        if isinstance(node, ast.If):
            # Check for: if __name__ == "__main__":
            test = node.test
            if isinstance(test, ast.Compare):
                if (
                    isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value == "__main__"
                ):
                    # Check if there's actual code in the block (not just pass/...)
                    for stmt in node.body:
                        if isinstance(stmt, ast.Pass):
                            continue
                        # Expr could be docstring or ellipsis - skip those
                        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                            # Skip string constants (docstrings) and ellipsis
                            if isinstance(stmt.value.value, str | type(...)):
                                continue
                        # Any other statement is actual code
                        has_main_block = True
                        break

    if has_functions:
        return True, "contains function definitions"
    if has_classes_with_methods:
        return True, "contains class with methods"
    if has_main_block:
        return True, "contains executable __main__ block"

    return False, "no functions, classes with methods, or executable code"


def is_testable_command(file_path: str) -> int:
    """Determine if a file requires testing.

    Outputs JSON with testability determination:
    - {"testable": true, "path": "...", "reason": "..."}
    - {"testable": false, "path": "...", "reason": "..."}

    Args:
        file_path: Path to the file to check.

    Returns:
        Exit code (0 for success).
    """
    path = Path(file_path)

    # Check if file exists
    if not path.exists():
        print(
            json.dumps(
                {
                    "testable": False,
                    "path": file_path,
                    "reason": "file does not exist",
                    "error": True,
                }
            )
        )
        return 1

    # Check extension
    if path.suffix.lower() in NON_TESTABLE_EXTENSIONS:
        print(
            json.dumps(
                {
                    "testable": False,
                    "path": file_path,
                    "reason": f"non-testable extension: {path.suffix}",
                }
            )
        )
        return 0

    # Check path patterns
    path_str = str(path)
    for pattern in NON_TESTABLE_PATH_PATTERNS:
        if pattern in path_str:
            print(
                json.dumps(
                    {
                        "testable": False,
                        "path": file_path,
                        "reason": f"non-testable path pattern: {pattern}",
                    }
                )
            )
            return 0

    # Check filename patterns
    for pattern in NON_TESTABLE_NAME_PATTERNS:
        if path.name.endswith(pattern):
            print(
                json.dumps(
                    {
                        "testable": False,
                        "path": file_path,
                        "reason": f"non-testable filename pattern: {pattern}",
                    }
                )
            )
            return 0

    # For non-Python files that passed the checks above, assume testable
    if path.suffix.lower() != ".py":
        print(
            json.dumps(
                {
                    "testable": True,
                    "path": file_path,
                    "reason": "non-Python file not matching exclusion patterns",
                }
            )
        )
        return 0

    # For Python files, analyze content
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(
            json.dumps(
                {
                    "testable": False,
                    "path": file_path,
                    "reason": f"cannot read file: {e}",
                    "error": True,
                }
            )
        )
        return 1

    # Empty files are not testable
    if not source.strip():
        print(
            json.dumps(
                {
                    "testable": False,
                    "path": file_path,
                    "reason": "empty file",
                }
            )
        )
        return 0

    is_testable, reason = _has_testable_constructs(source)
    print(
        json.dumps(
            {
                "testable": is_testable,
                "path": file_path,
                "reason": reason,
            }
        )
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run pr is-testable <file_path>", file=sys.stderr)
        sys.exit(1)
    sys.exit(is_testable_command(sys.argv[1]))
