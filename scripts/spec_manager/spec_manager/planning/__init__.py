"""
Planning phase operations for spec management.

Goal: Decompose a large change into small, safe batches.

Operations:
- compare_ids: Compare libs.md IDs against plan/library headers
- find_missing: Find IDs not in libs.md
- check_sequences: Detect numbering gaps/duplicates
- create_batches: Group changes into processable batches
"""

from spec_manager.planning.operations import (
    compare_ids,
    find_missing_in_registry,
    find_missing_in_libraries,
    check_sequences,
    create_batches,
    run_planning,
)

__all__ = [
    "compare_ids",
    "find_missing_in_registry",
    "find_missing_in_libraries",
    "check_sequences",
    "create_batches",
    "run_planning",
]
