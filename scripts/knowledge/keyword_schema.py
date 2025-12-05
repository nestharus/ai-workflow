"""Keyword index schema definition.

This module is the single source of truth for the keywords.csv schema used by
the keyword extraction and classification pipeline. All modules that read or
write to `.knowledge/keywords/keywords.csv` should import KEYWORD_COLUMNS from
this module to ensure consistency.

The keywords.csv table stores one row per (keyword, source_file, element_id)
combination, tracking where each classified keyword appears in the documentation.
"""

from __future__ import annotations

# CSV columns for the keywords index (.knowledge/keywords/keywords.csv)
# One row per (keyword, source_file, element_id) combination
KEYWORD_COLUMNS = [
    "keyword",  # Canonical term (string)
    "source_file",  # YAML path (relative to repo root)
    "element_id",  # YAML element ID where keyword was found
    "snippet",  # Optional sentence or short excerpt
    "first_detected",  # ISO 8601 timestamp when first detected
    "last_updated",  # ISO 8601 timestamp when last updated
]


def make_empty_keyword_row() -> dict[str, str]:
    """Create an empty keyword row with all columns set to empty strings.

    Returns:
        Dictionary with all KEYWORD_COLUMNS keys set to empty strings.
    """
    return {col: "" for col in KEYWORD_COLUMNS}
