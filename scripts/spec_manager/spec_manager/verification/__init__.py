"""Verification phase operations for spec management.

Goal: Confirm no drift or duplication after merging.

Operations:
- verify_content: Compare library content against plan.md
- detect_duplicates: Find IDs duplicated across libraries
- find_empty_stubs: Find library sections with empty bodies
- verify_assignments: Validate all IDs are in correct libraries
"""

from spec_manager.verification.operations import (
    detect_duplicates,
    find_empty_stubs,
    run_verification,
    verify_assignments,
    verify_content,
)

__all__ = [
    "detect_duplicates",
    "find_empty_stubs",
    "run_verification",
    "verify_assignments",
    "verify_content",
]
