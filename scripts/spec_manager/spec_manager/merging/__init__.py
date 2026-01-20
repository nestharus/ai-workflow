"""
Merging phase operations for spec management.

Goal: Apply prepared batches to library files.

Operations:
- extract_to_libraries: Insert missing sections into libraries
- move_to_correct_library: Relocate misplaced sections
- fix_duplicates: Remove duplicate sections
- sort_by_id: Sort library sections by ID
"""

from spec_manager.merging.operations import (
    extract_to_libraries,
    move_to_correct_library,
    fix_duplicates,
    sort_by_id,
    run_merging,
)

__all__ = [
    "extract_to_libraries",
    "move_to_correct_library",
    "fix_duplicates",
    "sort_by_id",
    "run_merging",
]
