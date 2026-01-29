"""Count total lines of all test functions in a directory.

Used to verify test reorganization preserves all code:
- Original line count == new line count
- All tests compile (no syntax errors)

Usage:
    uv run dev.count-test-lines scripts/tests/
    uv run dev.count-test-lines scripts/tests/ --verbose
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestFunctionInfo:
    """Information about a test function."""

    file_path: Path
    name: str
    class_name: str | None  # Enclosing class if any
    start_line: int  # First line (decorator or def)
    end_line: int
    line_count: int


def _get_function_start(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Get the starting line of a function including decorators."""
    start = node.lineno
    if node.decorator_list:
        start = min(d.lineno for d in node.decorator_list)
    return start


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if a function has @pytest.fixture decorator."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "fixture":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "fixture":
            return True
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name) and func.id == "fixture":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "fixture":
                return True
    return False


def _count_test_functions_in_file(file_path: Path, silent: bool = False) -> list[TestFunctionInfo]:
    """Count test functions in a single file.

    Args:
        file_path: Path to the Python file.
        silent: If True, don't print errors.

    Returns:
        List of TestFunctionInfo for each test function found.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []

    results: list[TestFunctionInfo] = []

    def visit_function(
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None = None,
    ) -> None:
        """Process a function node."""
        # Skip fixtures (e.g., test_client fixture)
        if _is_fixture(node):
            return
        if node.name.startswith("test_"):
            start = _get_function_start(node)
            end = node.end_lineno or node.lineno
            results.append(
                TestFunctionInfo(
                    file_path=file_path,
                    name=node.name,
                    class_name=class_name,
                    start_line=start,
                    end_line=end,
                    line_count=end - start + 1,
                )
            )

    def visit_class(node: ast.ClassDef) -> None:
        """Process a class node to find test methods."""
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit_function(child, node.name)
            elif isinstance(child, ast.ClassDef):
                # Nested class - recurse
                visit_nested_class(child, node.name)

    def visit_nested_class(node: ast.ClassDef, parent_class: str) -> None:
        """Process nested classes."""
        full_name = f"{parent_class}.{node.name}"
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit_function(child, full_name)
            elif isinstance(child, ast.ClassDef):
                visit_nested_class(child, full_name)

    # Walk top-level nodes
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_function(node)
        elif isinstance(node, ast.ClassDef):
            visit_class(node)

    return results


def count_test_lines(
    root_path: Path,
    verbose: bool = False,
) -> tuple[int, int, list[TestFunctionInfo]]:
    """Count total lines of all test functions in a directory.

    Args:
        root_path: Root directory to search.
        verbose: If True, print details for each file.

    Returns:
        Tuple of (total_lines, total_functions, list of TestFunctionInfo).
    """
    all_functions: list[TestFunctionInfo] = []

    # Find all test files
    test_files = sorted(root_path.rglob("test_*.py"))

    for file_path in test_files:
        functions = _count_test_functions_in_file(file_path)
        if verbose and functions:
            file_lines = sum(f.line_count for f in functions)
            print(f"  {file_path}: {len(functions)} functions, {file_lines} lines")
        all_functions.extend(functions)

    total_lines = sum(f.line_count for f in all_functions)
    return total_lines, len(all_functions), all_functions


def verify_syntax(root_path: Path, max_errors: int = 0) -> tuple[bool, list[str]]:
    """Verify all Python files in the directory have valid syntax.

    Args:
        root_path: Root directory to check.
        max_errors: Maximum number of errors to collect (0 = unlimited).

    Returns:
        Tuple of (all_valid, list of error messages).
    """
    errors: list[str] = []
    test_files = sorted(root_path.rglob("*.py"))

    for file_path in test_files:
        try:
            source = file_path.read_text(encoding="utf-8")
            ast.parse(source)
        except SyntaxError as e:
            errors.append(f"{file_path}:{e.lineno}: {e.msg}")
            if max_errors > 0 and len(errors) >= max_errors:
                break
        except (UnicodeDecodeError, OSError) as e:
            errors.append(f"{file_path}: {e}")
            if max_errors > 0 and len(errors) >= max_errors:
                break

    return len(errors) == 0, errors


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Count total lines of all test functions")
    parser.add_argument("path", type=Path, help="Directory to analyze")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-file details")
    parser.add_argument(
        "--verify-syntax", action="store_true", help="Also verify syntax of all files"
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=1,
        help="Maximum syntax errors to show (default: 1, 0 = unlimited)",
    )
    parser.add_argument("--json", action="store_true", help="Output in JSON format")

    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"Error: {args.path} does not exist", file=sys.stderr)
        return 1

    if not args.path.is_dir():
        print(f"Error: {args.path} is not a directory", file=sys.stderr)
        return 1

    # Count test lines
    if args.verbose:
        print(f"Analyzing {args.path}...\n")

    total_lines, total_functions, _ = count_test_lines(args.path, verbose=args.verbose)

    # Verify syntax if requested
    syntax_ok = True
    syntax_errors: list[str] = []
    if args.verify_syntax:
        syntax_ok, syntax_errors = verify_syntax(args.path, max_errors=args.max_errors)

    # Output results
    if args.json:
        import json

        result = {
            "path": str(args.path),
            "total_lines": total_lines,
            "total_functions": total_functions,
            "syntax_valid": syntax_ok,
            "syntax_errors": syntax_errors,
        }
        print(json.dumps(result, indent=2))
    else:
        print(f"\n{'=' * 50}")
        print(f"Directory: {args.path}")
        print(f"Total test functions: {total_functions}")
        print(f"Total lines in test functions: {total_lines}")

        if args.verify_syntax:
            if syntax_ok:
                print("Syntax check: PASSED")
            else:
                print(f"Syntax check: FAILED ({len(syntax_errors)} errors)")
                for error in syntax_errors[:10]:
                    print(f"  {error}")
                if len(syntax_errors) > 10:
                    print(f"  ... and {len(syntax_errors) - 10} more")

        print(f"{'=' * 50}")

    return 0 if syntax_ok else 1


if __name__ == "__main__":
    sys.exit(main())
