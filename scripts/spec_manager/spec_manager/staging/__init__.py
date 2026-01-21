"""Staging phase operations for spec management.

Goal: Ensure incoming plan/patch content is legal, annotated, and consistent.

Operations:
- lint_patterns: Validate label formatting
- check_duplicates: Flag duplicate declarations
- find_missing_declarations: List headers missing declarations
- find_references: Report ID references missing annotations
- normalize_annotations: Convert legacy formats to canonical
"""

from spec_manager.staging.operations import (
    check_duplicate_declarations,
    find_missing_declarations,
    find_unannotated_references,
    lint_patterns,
    normalize_annotations,
    run_staging,
)

__all__ = [
    "check_duplicate_declarations",
    "find_missing_declarations",
    "find_unannotated_references",
    "lint_patterns",
    "normalize_annotations",
    "run_staging",
]
