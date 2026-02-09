"""Comment scanner — re-exports from branches.gap_detection."""

from __future__ import annotations

from spec_manager.branches.gap_detection import (
    EXCLUDED_PREFIXES,
    CommentGap,
    comments_to_gap_evidence,
    scan_comments,
)

__all__ = [
    "EXCLUDED_PREFIXES",
    "CommentGap",
    "comments_to_gap_evidence",
    "scan_comments",
]
