"""Diff test functions between original and reorganized folders.

Compares two folder sets to verify reorganization preserved all test functions:
- Maps functions from original files to new locations
- Performs line-by-line diff of function content
- Reports missing functions and content differences

Usage:
    uv run python -m scripts.dev.diff_test_functions scripts/tests/ \
        scripts/tests/unit/ scripts/tests/component/
    uv run python -m scripts.dev.diff_test_functions original/ new/ --verbose
"""

from __future__ import annotations

import ast
import difflib
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FunctionSource:
    """A function with its source code."""

    name: str
    file_path: Path
    class_name: str | None  # Enclosing class(es) if any
    start_line: int
    end_line: int
    source_lines: list[str]  # The actual source code lines
    decorator_lines: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        """Get fully qualified name (ClassName.method or just function)."""
        if self.class_name:
            return f"{self.class_name}.{self.name}"
        return self.name

    @property
    def full_source(self) -> str:
        """Get full source including decorators."""
        return "".join(self.decorator_lines + self.source_lines)


@dataclass
class DiffResult:
    """Result of comparing two functions."""

    function_name: str
    original_file: Path
    new_file: Path | None
    status: str  # 'match', 'differ', 'missing_in_new', 'missing_in_original'
    diff_lines: list[str] = field(default_factory=list)


def _get_function_start(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Get the starting line of a function including decorators."""
    start = node.lineno
    if node.decorator_list:
        start = min(d.lineno for d in node.decorator_list)
    return start


def _extract_functions_from_file(file_path: Path) -> list[FunctionSource]:
    """Extract all test functions with their source code from a file."""
    try:
        source = file_path.read_text(encoding="utf-8")
        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError) as e:
        print(f"  ERROR parsing {file_path}: {e}", file=sys.stderr)
        return []

    results: list[FunctionSource] = []

    def extract_function(
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None = None,
    ) -> None:
        """Extract a function's source code."""
        if not node.name.startswith("test_"):
            return

        start = _get_function_start(node)
        end = node.end_lineno or node.lineno

        # Split into decorator lines and function lines
        func_start = node.lineno
        decorator_lines = lines[start - 1 : func_start - 1]
        source_lines = lines[func_start - 1 : end]

        results.append(
            FunctionSource(
                name=node.name,
                file_path=file_path,
                class_name=class_name,
                start_line=start,
                end_line=end,
                source_lines=source_lines,
                decorator_lines=decorator_lines,
            )
        )

    def visit_class(node: ast.ClassDef, parent_class: str | None = None) -> None:
        """Process a class node to find test methods."""
        class_name = f"{parent_class}.{node.name}" if parent_class else node.name
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                extract_function(child, class_name)
            elif isinstance(child, ast.ClassDef):
                visit_class(child, class_name)

    # Walk top-level nodes
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            extract_function(node)
        elif isinstance(node, ast.ClassDef):
            visit_class(node)

    return results


def _collect_functions(root_path: Path) -> dict[str, list[FunctionSource]]:
    """Collect all test functions from a directory.

    Returns:
        Dict mapping function full_name to list of FunctionSource
        (list because same function might appear in multiple files after reorg)
    """
    functions: dict[str, list[FunctionSource]] = {}

    test_files = sorted(root_path.rglob("test_*.py"))
    for file_path in test_files:
        for func in _extract_functions_from_file(file_path):
            key = func.full_name
            if key not in functions:
                functions[key] = []
            functions[key].append(func)

    return functions


def _normalize_source(source: str) -> list[str]:
    """Normalize source for comparison (strip trailing whitespace)."""
    lines = source.splitlines()
    return [line.rstrip() for line in lines]


def _diff_functions(original: FunctionSource, new: FunctionSource) -> list[str]:
    """Generate a diff between two function sources."""
    orig_lines = _normalize_source(original.full_source)
    new_lines = _normalize_source(new.full_source)

    diff = list(
        difflib.unified_diff(
            orig_lines,
            new_lines,
            fromfile=str(original.file_path),
            tofile=str(new.file_path),
            lineterm="",
        )
    )

    return diff


def compare_folders(
    original_paths: list[Path],
    new_paths: list[Path],
    verbose: bool = False,
) -> tuple[list[DiffResult], dict[str, int]]:
    """Compare test functions between original and new folder sets.

    Args:
        original_paths: List of original folder paths to compare from.
        new_paths: List of new folder paths to compare to.
        verbose: If True, print progress.

    Returns:
        Tuple of (list of DiffResults, summary stats dict).
    """
    # Collect functions from both sets
    if verbose:
        print("Collecting functions from original folders...")
    original_funcs: dict[str, list[FunctionSource]] = {}
    for path in original_paths:
        for name, funcs in _collect_functions(path).items():
            if name not in original_funcs:
                original_funcs[name] = []
            original_funcs[name].extend(funcs)

    if verbose:
        print(f"  Found {len(original_funcs)} unique function names")
        print("Collecting functions from new folders...")

    new_funcs: dict[str, list[FunctionSource]] = {}
    for path in new_paths:
        for name, funcs in _collect_functions(path).items():
            if name not in new_funcs:
                new_funcs[name] = []
            new_funcs[name].extend(funcs)

    if verbose:
        print(f"  Found {len(new_funcs)} unique function names")
        print("Comparing functions...")

    results: list[DiffResult] = []
    stats = {"match": 0, "differ": 0, "missing_in_new": 0, "extra_in_new": 0}

    # Check all original functions
    for name, orig_list in sorted(original_funcs.items()):
        if name not in new_funcs:
            # Missing in new
            for orig in orig_list:
                results.append(
                    DiffResult(
                        function_name=name,
                        original_file=orig.file_path,
                        new_file=None,
                        status="missing_in_new",
                    )
                )
                stats["missing_in_new"] += 1
        else:
            # Compare each original with its corresponding new version
            new_list = new_funcs[name]

            # For each original, find the best matching new (by content)
            for orig in orig_list:
                best_match = None
                best_diff: list[str] = []

                for new in new_list:
                    diff = _diff_functions(orig, new)
                    if not diff:
                        # Exact match
                        best_match = new
                        best_diff = []
                        break
                    elif best_match is None or len(diff) < len(best_diff):
                        best_match = new
                        best_diff = diff

                if best_match is None:
                    results.append(
                        DiffResult(
                            function_name=name,
                            original_file=orig.file_path,
                            new_file=None,
                            status="missing_in_new",
                        )
                    )
                    stats["missing_in_new"] += 1
                elif not best_diff:
                    results.append(
                        DiffResult(
                            function_name=name,
                            original_file=orig.file_path,
                            new_file=best_match.file_path,
                            status="match",
                        )
                    )
                    stats["match"] += 1
                else:
                    results.append(
                        DiffResult(
                            function_name=name,
                            original_file=orig.file_path,
                            new_file=best_match.file_path,
                            status="differ",
                            diff_lines=best_diff,
                        )
                    )
                    stats["differ"] += 1

    # Check for extra functions in new (not in original)
    for name in new_funcs:
        if name not in original_funcs:
            for new in new_funcs[name]:
                results.append(
                    DiffResult(
                        function_name=name,
                        original_file=Path("N/A"),
                        new_file=new.file_path,
                        status="extra_in_new",
                    )
                )
                stats["extra_in_new"] += 1

    return results, stats


def print_report(
    results: list[DiffResult],
    stats: dict[str, int],
    show_diffs: bool = False,
    max_diffs: int = 10,
) -> None:
    """Print a comparison report."""
    print("\n" + "=" * 60)
    print("FUNCTION COMPARISON REPORT")
    print("=" * 60)

    print("\nSummary:")
    print(f"  Matching functions:     {stats['match']}")
    print(f"  Differing functions:    {stats['differ']}")
    print(f"  Missing in new:         {stats['missing_in_new']}")
    print(f"  Extra in new:           {stats['extra_in_new']}")

    total = stats["match"] + stats["differ"] + stats["missing_in_new"]
    if total > 0:
        match_pct = (stats["match"] / total) * 100
        print(f"\n  Match rate: {match_pct:.1f}%")

    # Report missing functions
    missing = [r for r in results if r.status == "missing_in_new"]
    if missing:
        print(f"\n--- MISSING IN NEW ({len(missing)}) ---")
        for r in missing[:20]:
            print(f"  {r.function_name}")
            print(f"    Original: {r.original_file}")
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")

    # Report differing functions
    differing = [r for r in results if r.status == "differ"]
    if differing:
        print(f"\n--- DIFFERING FUNCTIONS ({len(differing)}) ---")
        for shown, r in enumerate(differing):
            if shown >= max_diffs:
                print(f"\n  ... and {len(differing) - shown} more differing functions")
                break

            print(f"\n  {r.function_name}")
            print(f"    Original: {r.original_file}")
            print(f"    New:      {r.new_file}")

            if show_diffs and r.diff_lines:
                print("    Diff:")
                for line in r.diff_lines[:30]:
                    print(f"      {line}")
                if len(r.diff_lines) > 30:
                    print(f"      ... ({len(r.diff_lines) - 30} more lines)")

    # Report extra functions
    extra = [r for r in results if r.status == "extra_in_new"]
    if extra:
        print(f"\n--- EXTRA IN NEW ({len(extra)}) ---")
        for r in extra[:20]:
            print(f"  {r.function_name}")
            print(f"    New: {r.new_file}")
        if len(extra) > 20:
            print(f"  ... and {len(extra) - 20} more")

    print("\n" + "=" * 60)

    if stats["missing_in_new"] == 0 and stats["differ"] == 0:
        print("SUCCESS: All functions match!")
    else:
        print("FAILURE: Functions do not match")

    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Diff test functions between original and new folders"
    )
    parser.add_argument(
        "original",
        type=Path,
        nargs="+",
        help="Original folder path(s) to compare from",
    )
    parser.add_argument(
        "--new",
        type=Path,
        nargs="+",
        required=True,
        help="New folder path(s) to compare to",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show progress")
    parser.add_argument("--show-diffs", "-d", action="store_true", help="Show actual diff content")
    parser.add_argument(
        "--max-diffs",
        type=int,
        default=10,
        help="Maximum number of diffs to show (default: 10)",
    )
    parser.add_argument("--json", action="store_true", help="Output in JSON format")

    args = parser.parse_args(argv)

    # Validate paths
    for path in args.original:
        if not path.exists():
            print(f"Error: {path} does not exist", file=sys.stderr)
            return 1

    for path in args.new:
        if not path.exists():
            print(f"Error: {path} does not exist", file=sys.stderr)
            return 1

    # Compare
    results, stats = compare_folders(
        args.original,
        args.new,
        verbose=args.verbose,
    )

    # Output
    if args.json:
        import json

        output = {
            "stats": stats,
            "success": stats["missing_in_new"] == 0 and stats["differ"] == 0,
            "results": [
                {
                    "function_name": r.function_name,
                    "original_file": str(r.original_file),
                    "new_file": str(r.new_file) if r.new_file else None,
                    "status": r.status,
                    "diff_line_count": len(r.diff_lines),
                }
                for r in results
                if r.status != "match"  # Only include non-matching for brevity
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print_report(results, stats, show_diffs=args.show_diffs, max_diffs=args.max_diffs)

    # Return exit code based on success
    if stats["missing_in_new"] == 0 and stats["differ"] == 0:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
