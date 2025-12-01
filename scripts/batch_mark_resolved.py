"""Batch-process MIXED→split items and mark them as resolved.

This module automates the batch resolution marking step of the granular ID
breakdown process. It parses a breakdown table to find MIXED→split items,
then invokes `mark-resolved` for each one via subprocess.

Usage:
    uv run batch-mark-resolved --breakdown-table <breakdown.md> \
        --original-file <timestamped.yml> \
        --general-file <general.yml> \
        --project-file <project.yml>

Args:
    --breakdown-table: Path to the markdown breakdown table.
    --original-file: Path to the timestamped original YAML file.
    --general-file: Path to the GENERAL split file.
    --project-file: Path to the PROJECT split file.
    --knowledge-path: Base knowledge directory (default: .knowledge).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from scripts.utils import REPO_ROOT


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for batch resolution marking.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Batch-process MIXED→split items and mark them as resolved.",
    )
    parser.add_argument(
        "--breakdown-table",
        type=Path,
        required=True,
        help="Path to the markdown breakdown table.",
    )
    parser.add_argument(
        "--original-file",
        type=Path,
        required=True,
        help="Path to the timestamped original YAML file.",
    )
    parser.add_argument(
        "--general-file",
        type=Path,
        required=True,
        help="Path to the GENERAL split file.",
    )
    parser.add_argument(
        "--project-file",
        type=Path,
        required=True,
        help="Path to the PROJECT split file.",
    )
    parser.add_argument(
        "--knowledge-path",
        type=Path,
        default=Path(".knowledge"),
        help="Base knowledge directory (default: .knowledge).",
    )
    return parser.parse_args(argv)


def _parse_table_line(line: str) -> list[str] | None:
    """Parse a markdown table line by splitting on pipe characters.

    Uses tolerant parsing that splits on `|`, trims whitespace, and ignores
    leading/trailing empty entries from the pipe delimiters.

    Args:
        line: A line from the markdown file.

    Returns:
        List of column values if valid table row, None otherwise.
    """
    # Must contain at least one pipe to be a table row
    if "|" not in line:
        return None

    # Split on pipe and strip whitespace from each part
    parts = [p.strip() for p in line.split("|")]

    # Remove empty first and last entries caused by leading/trailing pipes
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]

    return parts if parts else None


def _is_separator_row(columns: list[str]) -> bool:
    """Check if a row is a markdown table separator (contains only dashes)."""
    return all(col.replace("-", "").replace(":", "").strip() == "" for col in columns)


def parse_breakdown_table(table_path: Path) -> list[str]:
    """Parse markdown table to extract IDs classified as MIXED→split.

    Uses tolerant parsing that splits on `|` rather than strict regex matching.

    Args:
        table_path: Path to the markdown breakdown table.

    Returns:
        List of element IDs classified as MIXED→split.
    """
    content = table_path.read_text(encoding="utf-8")
    mixed_ids: list[str] = []

    parsed_count = 0
    skipped_count = 0
    header_indices: dict[str, int] = {}

    for line_num, line in enumerate(content.split("\n"), 1):
        columns = _parse_table_line(line)

        if columns is None:
            continue

        # Need at least 5 columns for basic format
        if len(columns) < 5:
            # Check if it looks like a table row but has wrong column count
            if "|" in line and not line.strip().startswith("#"):
                skipped_count += 1
                print(
                    f"Warning: Line {line_num} looks like a table row but has "
                    f"{len(columns)} columns (expected >= 5), skipping.",
                    file=sys.stderr,
                )
            continue

        # Check for separator row
        if _is_separator_row(columns):
            continue

        # Check for header row and capture column indices
        if columns[0].upper() == "ID" or columns[0] == "ID":
            # Map column names to indices for flexible parsing
            for idx, col_name in enumerate(columns):
                header_indices[col_name.upper().strip()] = idx
            continue

        # Skip rows where classification column contains header text
        classification_idx = header_indices.get("CLASSIFICATION", 2)
        if classification_idx < len(columns):
            classification = columns[classification_idx].strip()
            if classification.upper() in ("CLASSIFICATION", ""):
                continue
        else:
            continue

        # Extract element ID
        id_idx = header_indices.get("ID", 0)
        element_id = columns[id_idx].strip() if id_idx < len(columns) else ""

        if not element_id:
            continue

        # Handle structural elements with parentheses prefix
        # e.g., "(table) http_method_defaults" -> "http_method_defaults"
        if element_id.startswith("("):
            paren_match = re.match(r"^\([^)]+\)\s*(.+)$", element_id)
            if paren_match:
                element_id = paren_match.group(1).strip()

        parsed_count += 1

        # Check for MIXED→split classification
        if classification == "MIXED→split":
            mixed_ids.append(element_id)

    if skipped_count > 0:
        print(
            f"Note: Parsed {parsed_count} rows, skipped {skipped_count} malformed rows.",
            file=sys.stderr,
        )

    return mixed_ids


def mark_resolved_for_id(
    element_id: str,
    original_file: Path,
    general_file: Path,
    project_file: Path,
    knowledge_path: Path,
) -> tuple[bool, str]:
    """Invoke mark-resolved for a single ID via subprocess.

    Args:
        element_id: The element ID to mark as resolved.
        original_file: Path to the original YAML file.
        general_file: Path to the GENERAL split file.
        project_file: Path to the PROJECT split file.
        knowledge_path: Base knowledge directory.

    Returns:
        Tuple of (success, message).
    """
    cmd = [
        "uv",
        "run",
        "mark-resolved",
        "--id",
        element_id,
        "--source-file",
        str(original_file),
        "--split-file",
        str(general_file),
        "--split-file",
        str(project_file),
        "--knowledge-path",
        str(knowledge_path),
    ]

    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )

        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    except subprocess.SubprocessError as exc:
        return False, str(exc)


def main() -> int:
    """Run batch resolution marking for MIXED→split items.

    Returns:
        0 on success, 1 on error.
    """
    args = parse_args()

    # Resolve paths
    breakdown_table = args.breakdown_table
    if not breakdown_table.is_absolute():
        breakdown_table = (REPO_ROOT / breakdown_table).resolve()

    original_file = args.original_file
    if not original_file.is_absolute():
        original_file = (REPO_ROOT / original_file).resolve()

    general_file = args.general_file
    if not general_file.is_absolute():
        general_file = (REPO_ROOT / general_file).resolve()

    project_file = args.project_file
    if not project_file.is_absolute():
        project_file = (REPO_ROOT / project_file).resolve()

    knowledge_path = args.knowledge_path
    if not knowledge_path.is_absolute():
        knowledge_path = (REPO_ROOT / knowledge_path).resolve()

    # Validate inputs exist
    if not breakdown_table.exists():
        print(f"Error: Breakdown table not found: {breakdown_table}", file=sys.stderr)
        return 1

    if not original_file.exists():
        print(f"Error: Original file not found: {original_file}", file=sys.stderr)
        return 1

    if not general_file.exists():
        print(f"Error: GENERAL file not found: {general_file}", file=sys.stderr)
        return 1

    if not project_file.exists():
        print(f"Error: PROJECT file not found: {project_file}", file=sys.stderr)
        return 1

    # Parse breakdown table for MIXED→split IDs
    mixed_ids = parse_breakdown_table(breakdown_table)

    if not mixed_ids:
        print("No MIXED→split items found in breakdown table.")
        return 0

    print(f"Found {len(mixed_ids)} MIXED→split items to mark as resolved.")
    print()

    # Process each ID
    success_count = 0
    failure_count = 0
    failures: list[tuple[str, str]] = []

    for index, element_id in enumerate(mixed_ids, 1):
        print(f"Marking resolved: {element_id} ({index}/{len(mixed_ids)})")

        success, message = mark_resolved_for_id(
            element_id,
            original_file,
            general_file,
            project_file,
            knowledge_path,
        )

        if success:
            success_count += 1
            if message:
                print(f"  ✓ {message}")
        else:
            failure_count += 1
            failures.append((element_id, message))
            print(f"  ✗ Failed: {message}")

    # Print summary
    print()
    print("=" * 60)
    print(f"Successfully marked {success_count} MIXED→split items as resolved.")

    if failures:
        print(f"\n{failure_count} items failed:")
        for element_id, message in failures:
            print(f"  - {element_id}: {message}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
