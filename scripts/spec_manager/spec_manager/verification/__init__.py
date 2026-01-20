"""
Verification phase operations for spec management.

Goal: Confirm no drift or duplication after merging.

Operations:
- verify_content: Compare library content against plan.md
- detect_duplicates: Find IDs duplicated across libraries
- find_empty_stubs: Find library sections with empty bodies
- verify_assignments: Validate all IDs are in correct libraries
"""

from spec_manager.verification.operations import (
    verify_content,
    detect_duplicates,
    find_empty_stubs,
    verify_assignments,
    run_verification,
)

__all__ = [
    "verify_content",
    "detect_duplicates",
    "find_empty_stubs",
    "verify_assignments",
    "run_verification",
]
