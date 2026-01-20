#!/usr/bin/env python3
"""
Sync body content from plan.md to library files.
For each section that exists in both, replace library body with plan body.
"""

from __future__ import annotations

import argparse
import re
from difflib import SequenceMatcher
from pathlib import Path


# Legal ID patterns (for ([=ID]) declarations)
ID_PATTERNS_LEGAL = [
    r'Algorithm \d+',
    r'Comp\d+',
    r'D\d+',
    r'G\d+',
    r'C\d+',
    r'S\d+',
    r'T\d+',
    r'P\d+I\d+',
    r'P\d+C\d+',
    r'P\d+\.\d+',
    r'P\d+',
    r'Lean\d+',
    r'NFG\d+',
    r'Gap G\d+\.\d+',
]

# Annotation pattern for declarations: ([=ID])
ANNOTATION_PATTERN = re.compile(r'\(\[=([^\]]+)\]\)')


def is_legal_id(text):
    """Check if text matches a legal ID pattern."""
    for pattern in ID_PATTERNS_LEGAL:
        if re.match(f'^{pattern}$', text):
            return True
    return False


def extract_sections_by_annotation(lines):
    """Extract sections based on ([=ID]) declarations.

    Returns: {id: (header_line, body_text, start_line_idx, end_line_idx)}
    """
    sections = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        match = ANNOTATION_PATTERN.search(line)

        if match and is_legal_id(match.group(1)):
            id_name = match.group(1)
            header_line = line
            start_idx = i

            # Collect body until next annotation or EOF
            body_lines = []
            i += 1
            while i < len(lines):
                next_match = ANNOTATION_PATTERN.search(lines[i])
                if next_match and is_legal_id(next_match.group(1)):
                    break
                body_lines.append(lines[i])
                i += 1

            end_idx = i  # exclusive
            sections[id_name] = (header_line, '\n'.join(body_lines), start_idx, end_idx)
        else:
            i += 1

    return sections


def normalize_body(body):
    """Normalize body for comparison."""
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync library section bodies to match plan.md.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to library files (default: dry-run).",
    )
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing (default).",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=0.50,
        help="Minimum similarity ratio to sync (default: 0.50).",
    )
    args = parser.parse_args()
    apply_changes = args.apply
    min_similarity = args.min_similarity

    base = Path(__file__).resolve().parents[2]
    plan_path = base / "plan.md"
    libs_dir = base / "libraries"

    # Read plan.md
    plan_content = plan_path.read_text(encoding='utf-8')
    plan_lines = plan_content.split('\n')

    # Extract sections from plan.md
    print("Extracting sections from plan.md...")
    plan_sections = extract_sections_by_annotation(plan_lines)
    print(f"Found {len(plan_sections)} sections in plan.md\n")

    if not apply_changes:
        print("DRY RUN: pass --apply to write changes.\n")

    total_synced = 0
    total_identical = 0

    # Process each library file
    for lib_file in sorted(libs_dir.glob("*.md")):
        lib_name = lib_file.stem
        content = lib_file.read_text(encoding='utf-8')
        lines = content.split('\n')

        lib_sections = extract_sections_by_annotation(lines)
        if not lib_sections:
            continue

        synced_count = 0
        identical_count = 0
        modified = False
        new_lines = lines.copy()

        # Sort by start line descending to avoid index shifting issues
        sorted_sections = sorted(
            lib_sections.items(),
            key=lambda x: x[1][2],
            reverse=True
        )

        for id_name, (lib_header, lib_body, start_idx, end_idx) in sorted_sections:
            if id_name not in plan_sections:
                continue

            plan_header, plan_body, _, _ = plan_sections[id_name]

            lib_body_norm = normalize_body(lib_body)
            plan_body_norm = normalize_body(plan_body)

            if lib_body_norm == plan_body_norm:
                identical_count += 1
                continue

            # Calculate similarity
            sim = (
                SequenceMatcher(None, plan_body_norm, lib_body_norm).ratio()
                if (plan_body_norm and lib_body_norm)
                else 0
            )

            # Sync if:
            # - similarity meets the threshold, OR
            # - library is a stub (< 20 chars normalized) and plan has content
            is_lib_stub = len(lib_body_norm) < 20
            should_sync = sim >= min_similarity or (is_lib_stub and plan_body_norm)
            if should_sync:
                # Replace library section with plan body (keep library header)
                # Format: header line + newline + body lines
                plan_body_lines = plan_body.split('\n') if plan_body else []

                # Build new section
                new_section = [lib_header] + plan_body_lines

                # Replace in new_lines
                new_lines[start_idx:end_idx] = new_section

                synced_count += 1
                modified = True
                action = "synced" if apply_changes else "would sync"
                print(f"  {id_name}: {action} ({sim*100:.0f}% similar)")

        if modified:
            if apply_changes:
                new_content = '\n'.join(new_lines)
                lib_file.write_text(new_content, encoding='utf-8')
                print(f"{lib_name}.md: {synced_count} synced, {identical_count} identical")
            else:
                print(f"{lib_name}.md: {synced_count} would sync, {identical_count} identical")
        else:
            print(f"{lib_name}.md: {identical_count} identical (no changes)")

        total_synced += synced_count
        total_identical += identical_count

    print(f"\n{'=' * 60}")
    if apply_changes:
        print(f"TOTAL: {total_synced} sections synced, {total_identical} identical")
    else:
        print(f"TOTAL: {total_synced} sections would sync, {total_identical} identical")


if __name__ == "__main__":
    main()
