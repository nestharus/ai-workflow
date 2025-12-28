"""Batch failing coverage functions by test file for parallel fixing.

This script reads the coverage database and creates batch files for parallel
test-debugger agents to process. Functions are grouped by their corresponding
test file to avoid conflicts.

Usage:
    uv run python scripts/dev/test_runner/batch_coverage_gaps.py [--tier TIER] [--batch-size N]

Arguments:
    --tier TIER      Only process specific tier (unit, component, scripts)
    --batch-size N   Target batch size (default: 10, may be larger if colocated)
    --output-dir     Output directory (default: .tmp/test_batches)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FailingFunction:
    """A function that's below coverage threshold."""

    file_path: str
    function_name: str
    tier: str
    line_coverage_pct: float
    branch_coverage_pct: float
    threshold_line: float
    threshold_branch: float
    missing_lines: str  # JSON array
    missing_branches: str  # JSON array

    @property
    def test_file_path(self) -> str:
        """Get the corresponding test file path."""
        return get_test_file_path(self.file_path, self.tier)


def get_test_file_path(source_path: str, tier: str) -> str:
    """Map a source file to its corresponding test file.

    Mappings:
    - app/foo/bar.py -> tests/unit/test_bar.py (for unit tier)
    - scripts/foo/bar.py -> scripts/tests/foo/test_bar.py (for scripts tier)
    """
    path = Path(source_path)

    if tier == "unit" or tier == "component":
        # app/core/factory.py -> tests/unit/test_factory.py
        # app/infrastructure/duckdb/client.py -> tests/unit/test_duckdb_client.py
        stem = path.stem
        # Handle nested paths by flattening the directory structure
        if "infrastructure" in source_path:
            # Get the subdirectory and filename
            parts = path.parts
            idx = parts.index("infrastructure")
            subdir = parts[idx + 1] if idx + 1 < len(parts) - 1 else ""
            stem = f"{subdir}_{path.stem}" if subdir else path.stem
        return f"tests/unit/test_{stem}.py"

    elif tier == "scripts":
        # scripts/knowledge/fact_store.py -> scripts/tests/unit/knowledge/test_fact_store.py
        # scripts/dev/test_runner/coverage.py -> scripts/tests/unit/test_runner/test_coverage.py
        # NOTE: scripts/tests/ is organized into unit/, component/, integration/ subdirectories
        parts = path.parts
        if parts[0] == "scripts":
            # Skip 'scripts' and any 'dev' prefix
            remaining = list(parts[1:])
            if remaining and remaining[0] == "dev":
                remaining = remaining[1:]
            if remaining:
                dir_parts = remaining[:-1]
                filename = f"test_{remaining[-1]}"
                if dir_parts:
                    return f"scripts/tests/{'/'.join(dir_parts)}/{filename}"
                return f"scripts/tests/{filename}"
        return f"scripts/tests/test_{path.stem}.py"

    return f"tests/test_{path.stem}.py"


def query_failing_functions(db_path: Path, tier: str | None = None) -> list[FailingFunction]:
    """Query the coverage database for functions below threshold."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
        SELECT file_path, function_name, tier,
               line_coverage_pct, branch_coverage_pct,
               threshold_line, threshold_branch,
               missing_lines, missing_branches
        FROM cc_function_coverage
        WHERE (line_pass = 0 OR branch_pass = 0)
    """
    if tier:
        query += f" AND tier = '{tier}'"
    query += " ORDER BY tier, file_path, function_name"

    cursor.execute(query)

    functions = []
    for row in cursor.fetchall():
        functions.append(
            FailingFunction(
                file_path=row[0],
                function_name=row[1],
                tier=row[2],
                line_coverage_pct=row[3],
                branch_coverage_pct=row[4],
                threshold_line=row[5],
                threshold_branch=row[6],
                missing_lines=row[7] or "[]",
                missing_branches=row[8] or "[]",
            )
        )

    conn.close()
    return functions


def group_by_test_file(functions: list[FailingFunction]) -> dict[str, list[FailingFunction]]:
    """Group functions by their corresponding test file."""
    groups: dict[str, list[FailingFunction]] = defaultdict(list)
    for func in functions:
        groups[func.test_file_path].append(func)
    return dict(groups)


def create_batches(
    groups: dict[str, list[FailingFunction]], target_size: int = 10
) -> list[list[FailingFunction]]:
    """Create batches of functions, keeping test file groups together.

    Each batch contains functions that map to different test files.
    If a test file has more functions than target_size, it becomes its own batch.
    """
    batches: list[list[FailingFunction]] = []
    current_batch: list[FailingFunction] = []
    current_test_files: set[str] = set()

    # Sort groups by number of functions (descending)
    sorted_groups = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)

    for test_file, funcs in sorted_groups:
        # If this test file has more than target_size functions, it's its own batch
        if len(funcs) > target_size:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_test_files = set()
            batches.append(funcs)
            continue

        # If adding this would exceed target size, start a new batch
        if len(current_batch) + len(funcs) > target_size and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_test_files = set()

        # Add to current batch
        current_batch.extend(funcs)
        current_test_files.add(test_file)

    # Don't forget the last batch
    if current_batch:
        batches.append(current_batch)

    return batches


def write_batch_file(batch: list[FailingFunction], batch_num: int, output_dir: Path) -> Path:
    """Write a batch file with function details."""
    batch_file = output_dir / f"batch_{batch_num:03d}.json"

    # Group by test file for clarity
    by_test_file: dict[str, list[dict[str, object]]] = defaultdict(list)
    for func in batch:
        by_test_file[func.test_file_path].append(
            {
                "source_file": func.file_path,
                "function_name": func.function_name,
                "tier": func.tier,
                "line_coverage_pct": func.line_coverage_pct,
                "branch_coverage_pct": func.branch_coverage_pct,
                "threshold_line": func.threshold_line,
                "threshold_branch": func.threshold_branch,
                "missing_lines": json.loads(func.missing_lines) if func.missing_lines else [],
                "missing_branches": json.loads(func.missing_branches)
                if func.missing_branches
                else [],
            }
        )

    batch_data = {
        "batch_number": batch_num,
        "total_functions": len(batch),
        "test_files": list(by_test_file.keys()),
        "functions_by_test_file": by_test_file,
    }

    batch_file.write_text(json.dumps(batch_data, indent=2))
    return batch_file


def main() -> None:
    """Batch failing coverage functions for parallel fixing."""
    parser = argparse.ArgumentParser(
        description="Batch failing coverage functions for parallel fixing"
    )
    parser.add_argument(
        "--tier", choices=["unit", "component", "scripts"], help="Only process specific tier"
    )
    parser.add_argument(
        "--batch-size", type=int, default=10, help="Target batch size (default: 10)"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".tmp/test_batches"), help="Output directory"
    )
    parser.add_argument(
        "--db-path", type=Path, default=Path(".coverage/coverage.db"), help="Coverage database path"
    )
    args = parser.parse_args()

    # Clean output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for old_file in args.output_dir.glob("batch_*.json"):
        old_file.unlink()

    # Query failing functions
    functions = query_failing_functions(args.db_path, args.tier)
    if not functions:
        print("No failing functions found!")
        return

    print(f"Found {len(functions)} failing functions")

    # Group by test file
    groups = group_by_test_file(functions)
    print(f"Grouped into {len(groups)} test files")

    # Create batches
    batches = create_batches(groups, args.batch_size)
    print(f"Created {len(batches)} batches")

    # Write batch files
    batch_files = []
    for i, batch in enumerate(batches, 1):
        batch_file = write_batch_file(batch, i, args.output_dir)
        batch_files.append(batch_file)

        # Print summary
        test_files = set(f.test_file_path for f in batch)
        print(f"  Batch {i}: {len(batch)} functions across {len(test_files)} test files")

    # Write manifest
    manifest = {
        "total_batches": len(batches),
        "total_functions": len(functions),
        "tier_filter": args.tier,
        "batch_size": args.batch_size,
        "batch_files": [str(f.name) for f in batch_files],
    }
    manifest_file = args.output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written to {manifest_file}")


if __name__ == "__main__":
    main()
