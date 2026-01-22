"""Merging phase operations for spec management.

Goal: Apply prepared batches to library files.

Operations:
- extract_to_libraries: Insert missing sections into libraries
- move_to_correct_library: Relocate misplaced sections
- fix_duplicates: Remove duplicate sections
- sort_by_id: Sort library sections by ID
"""

from spec_manager.merging.operations import (
    MergeAction,
    MergingResult,
    extract_to_libraries,
    fix_duplicates,
    move_to_correct_library,
    run_merging,
    sort_by_id,
)

__all__ = [
    "MergeAction",
    "MergingResult",
    "extract_to_libraries",
    "fix_duplicates",
    "move_to_correct_library",
    "run_merging",
    "sort_by_id",
]
