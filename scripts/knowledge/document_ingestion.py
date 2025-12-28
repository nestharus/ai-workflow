"""Document ingestion pipeline for atomic fact extraction.

Supports text, PDF, and JSON input formats with canonical UTF-8 string creation
and work region initialization.

Architectural References:
- requirements.md lines 348-432: Input handling, canonical string, work regions
- QA_strategy.md lines 80-91: Step 1 validation

The ingestion pipeline:
1. Reads input files (text, PDF, JSON)
2. Creates canonical UTF-8 string with normalization
3. Initializes work regions for fact extraction
4. Validates ingestion artifacts

Usage:
    python -m scripts.knowledge.document_ingestion --input doc.txt --output .tmp/ingestion
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from math import ceil
from pathlib import Path

import regex

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge.atomic_fact_models import WorkRegion, work_region_to_json

# Module-level counter for rate-limiting unmatched sentence warnings
# Only the first _UNMATCHED_SENTENCE_WARNING_LIMIT occurrences are logged
_unmatched_sentence_warnings: int = 0
_UNMATCHED_SENTENCE_WARNING_LIMIT: int = 5

# Import pypdf exception types for explicit error handling
# pypdf is an optional dependency, so we use a try/except import
try:
    from pypdf.errors import PyPdfError
except ImportError:
    # Define a placeholder exception class that will never be raised
    # This allows the except clause to work even when pypdf is not installed
    class PyPdfError(Exception):  # type: ignore[no-redef]
        """Placeholder for pypdf.errors.PyPdfError when pypdf is not installed."""


# Default number of lines to examine at top/bottom of each PDF page for
# header/footer artifact detection. Used by _collect_header_footer_candidates
# and documented in ingest_pdf_file docstring.
HEADER_FOOTER_CANDIDATE_COUNT: int = 3

# Text file extensions that should be treated as plain text input
# This includes common text formats beyond just .txt
TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt",  # Plain text
        ".md",  # Markdown
        ".markdown",  # Markdown (alternate)
        ".rst",  # reStructuredText
        ".log",  # Log files
        ".csv",  # CSV (treated as text)
        ".tsv",  # TSV (treated as text)
        ".yml",  # YAML
        ".yaml",  # YAML (alternate)
        ".toml",  # TOML
        ".ini",  # INI config
        ".cfg",  # Config files
        ".conf",  # Config files (alternate)
        ".properties",  # Java properties
        ".env",  # Environment files
        ".sh",  # Shell scripts
        ".bash",  # Bash scripts
        ".zsh",  # Zsh scripts
        ".py",  # Python
        ".js",  # JavaScript
        ".ts",  # TypeScript
        ".java",  # Java
        ".c",  # C
        ".cpp",  # C++
        ".h",  # C/C++ headers
        ".hpp",  # C++ headers
        ".go",  # Go
        ".rs",  # Rust
        ".rb",  # Ruby
        ".php",  # PHP
        ".sql",  # SQL
        ".html",  # HTML
        ".htm",  # HTML (alternate)
        ".xml",  # XML
        ".css",  # CSS
        ".scss",  # SCSS
        ".sass",  # Sass
        ".less",  # Less
    }
)

# Combined set of all allowed file extensions for ingestion
# Used by expand_input_paths for directory/glob filtering
ALLOWED_TEXT_PDF_JSON_EXTENSIONS: frozenset[str] = TEXT_EXTENSIONS | frozenset({".pdf", ".json"})


def _generate_timestamp() -> str:
    """Generate ISO 8601 timestamp without colons for file naming.

    Returns:
        Timestamp string in format YYYYMMDDTHHMMSSZ.
    """
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _generate_iso_timestamp() -> str:
    """Generate ISO 8601 timestamp for created_at fields.

    Returns:
        Timestamp string in format YYYY-MM-DDTHH:MM:SSZ.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_file_path(file_path: Path) -> Path:
    """Normalize file path against the repository root.

    If the path is relative, resolves it against REPO_ROOT.
    If the path is absolute, returns it resolved.

    This ensures consistent path handling for both CLI usage (where paths
    may be relative to cwd) and programmatic usage (where paths may be
    relative to the repo root).

    Args:
        file_path: Path to normalize.

    Returns:
        Resolved absolute path.
    """
    if file_path.is_absolute():
        return file_path.resolve()
    return (REPO_ROOT / file_path).resolve()


def _get_repo_relative_stem(file_path: Path) -> str:
    """Get a normalized stem for doc_id generation.

    Uses the file stem (filename without extension) for doc_id generation.
    This provides consistent IDs regardless of whether the input path
    was absolute or relative.

    Args:
        file_path: Resolved file path.

    Returns:
        File stem for use in doc_id.
    """
    return file_path.stem


def ingest_text_file(file_path: Path) -> tuple[str, str]:
    """Read text file with UTF-8 encoding, fallback to latin-1.

    Loads the entire file into memory. For very large files, consider
    using chunked processing at a higher level.

    The file_path is normalized against REPO_ROOT before processing:
    - Relative paths are resolved as REPO_ROOT / file_path
    - Absolute paths are resolved to canonical form

    Args:
        file_path: Path to the text file (absolute or relative to REPO_ROOT).

    Returns:
        Tuple of (raw_text, doc_id) where doc_id is text_{stem}_{timestamp}.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    resolved_path = _normalize_file_path(file_path)

    try:
        raw_text = resolved_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Fallback to latin-1 encoding for files that aren't valid UTF-8
        raw_text = resolved_path.read_text(encoding="latin-1")

    timestamp = _generate_timestamp()
    stem = _get_repo_relative_stem(resolved_path)
    doc_id = f"text_{stem}_{timestamp}"
    return raw_text, doc_id


def _collect_header_footer_candidates(
    page_text: str, candidate_count: int = HEADER_FOOTER_CANDIDATE_COUNT
) -> list[str]:
    """Extract candidate header/footer lines from a single page.

    Used during streaming PDF processing to collect candidates without
    holding all page texts in memory.

    Args:
        page_text: Text content of a single PDF page.
        candidate_count: Number of lines to examine at top/bottom of page.

    Returns:
        List of lowercase stripped lines from the first/last N lines.
    """
    lines = page_text.split("\n")
    first_lines = lines[:candidate_count]
    last_lines = lines[-candidate_count:] if len(lines) > candidate_count else []

    candidates: list[str] = []
    for line in first_lines + last_lines:
        stripped = line.strip().lower()
        if stripped:
            candidates.append(stripped)
    return candidates


def _identify_repeated_lines_from_candidates(
    all_candidates: list[str], page_count: int
) -> set[str]:
    """Identify repeated header/footer lines from collected candidates.

    Args:
        all_candidates: All candidate lines collected from all pages.
        page_count: Total number of pages processed.

    Returns:
        Set of lowercase lines that appear frequently enough to be artifacts.
    """
    if page_count < 2:
        return set()

    frequency = Counter(all_candidates)

    # Threshold: lines appearing in >=50% of pages, capped at 3 pages, minimum 2
    # Using ceil ensures odd page counts round up (e.g., 5 pages -> 3 required)
    threshold = max(2, min(ceil(page_count / 2), 3))

    artifact_lines: set[str] = set()
    for line, count in frequency.items():
        if count >= threshold:
            artifact_lines.add(line)

    return artifact_lines


def _remove_artifact_lines(page_text: str, artifact_lines: set[str]) -> str:
    """Remove artifact lines from a page's text.

    Filters out lines whose lowercase stripped form matches any artifact line.

    Args:
        page_text: Text content of a single page.
        artifact_lines: Set of lowercase artifact lines to remove.

    Returns:
        Page text with artifact lines removed.
    """
    if not artifact_lines:
        return page_text

    lines = page_text.split("\n")
    cleaned_lines: list[str] = []
    for line in lines:
        stripped_lower = line.strip().lower()
        if stripped_lower not in artifact_lines:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


# Maximum number of digits for standalone page number detection.
# Used in PAGE_NUMBER_PATTERN and is_page_number_artifact().
# Exposed as public constant for test synchronization.
PAGE_NUMBER_MAX_DIGITS: int = 4

# Pattern for standalone digit-only page numbers (1-4 digits with optional whitespace)
_PAGE_NUMBER_PATTERN = re.compile(rf"^\s*\d{{1,{PAGE_NUMBER_MAX_DIGITS}}}\s*$")

# Maximum line gap between digit-only lines to consider them part of a consecutive
# numbered sequence. Lines within this gap of each other with consecutive numeric
# values are treated as a numbered list, not page numbers. A gap of 4 allows for
# numbered lists with spacing (e.g., "1\nApples\nOranges\n2\nBananas").
#
# Usage locations:
# - _remove_page_number_lines(): Uses this as the default boundary_lines parameter
#   to determine context when checking if a digit-only line at page edges is isolated
# - _has_isolated_page_numbers(): Uses this as the default adjacency_gap parameter
#   to detect whether digit-only lines are part of consecutive numbered sequences
#
# Changing this value affects:
# - Both functions above (they share this constant for consistency)
# - TestHasIsolatedPageNumbers and TestRemovePageNumberLines in
#   scripts/tests/unit/knowledge/test_document_ingestion.py (tests deliberately lock
#   this value to verify expected behavior)
#
# If you modify this constant, update the related tests in lockstep.
PAGE_NUMBER_ADJACENCY_GAP: int = 4


def is_page_number_artifact(text: str) -> bool:
    """Check if text is a standalone page number artifact.

    A page number artifact is defined as a string that:
    - Is non-empty after stripping whitespace
    - Contains only digits
    - Has at most PAGE_NUMBER_MAX_DIGITS digits

    This function is exposed as a public helper for test synchronization.
    Tests should import and use this function rather than re-implementing
    the logic to avoid drift between test assertions and production behavior.

    Args:
        text: The text to check (will be stripped of whitespace).

    Returns:
        True if text appears to be a page number artifact, False otherwise.
    """
    stripped = text.strip() if text else ""
    return bool(stripped and stripped.isdigit() and len(stripped) <= PAGE_NUMBER_MAX_DIGITS)


def _remove_page_number_lines(page_text: str, boundary_lines: int | None = None) -> str:
    r"""Remove digit-only page number lines from page boundaries.

    Removes lines matching the pattern ^\s*\d{1,4}\s*$ (1-4 digit numbers)
    only when they appear at the very first or very last line of a page.
    This conservative approach targets typical page number placement while
    preserving numbered list content that might appear near page boundaries.

    The boundary_lines parameter controls how many lines from the top/bottom
    to examine for determining if a digit-only line is part of a numbered
    sequence. This uses PAGE_NUMBER_ADJACENCY_GAP by default for consistency
    with _has_isolated_page_numbers. Removal only happens for isolated
    digit-only lines at the actual page edges (first or last line).

    Args:
        page_text: Text content of a single page.
        boundary_lines: Number of lines at top/bottom to examine for context.
            Defaults to PAGE_NUMBER_ADJACENCY_GAP (used for context, not removal range).

    Returns:
        Page text with page number lines removed from page edges.
    """
    if boundary_lines is None:
        boundary_lines = PAGE_NUMBER_ADJACENCY_GAP
    lines = page_text.split("\n")
    total_lines = len(lines)

    if total_lines == 0:
        return page_text

    # Track which lines to remove
    lines_to_remove: set[int] = set()

    # Check only the very first line - typical top-of-page number placement
    if _PAGE_NUMBER_PATTERN.match(lines[0]):
        # Only remove if it's isolated (next non-empty line is not a consecutive number)
        is_isolated = True
        for i in range(1, min(boundary_lines + 1, total_lines)):
            if _PAGE_NUMBER_PATTERN.match(lines[i]):
                try:
                    first_val = int(lines[0].strip())
                    next_val = int(lines[i].strip())
                    # If sequential, it's part of a numbered list
                    if next_val == first_val + 1:
                        is_isolated = False
                        break
                except ValueError:
                    pass
        if is_isolated:
            lines_to_remove.add(0)

    # Check only the very last line - typical bottom-of-page number placement
    last_idx = total_lines - 1
    if last_idx > 0 and _PAGE_NUMBER_PATTERN.match(lines[last_idx]):
        # Only remove if it's isolated (previous non-empty line is not a consecutive number)
        is_isolated = True
        for i in range(last_idx - 1, max(last_idx - boundary_lines - 1, -1), -1):
            if _PAGE_NUMBER_PATTERN.match(lines[i]):
                try:
                    last_val = int(lines[last_idx].strip())
                    prev_val = int(lines[i].strip())
                    # If sequential, it's part of a numbered list
                    if last_val == prev_val + 1:
                        is_isolated = False
                        break
                except ValueError:
                    pass
        if is_isolated:
            lines_to_remove.add(last_idx)

    # If nothing to remove, return original
    if not lines_to_remove:
        return page_text

    # Build result excluding marked lines
    cleaned_lines = [line for i, line in enumerate(lines) if i not in lines_to_remove]
    return "\n".join(cleaned_lines)


def ingest_pdf_file(
    file_path: Path,
    max_pages_to_cache: int | None = None,
) -> tuple[str, str]:
    """Extract text from PDF file using adaptive caching approach.

    Uses pypdf to extract text from pages. For small/medium PDFs (page count
    <= max_pages_to_cache), uses single-pass caching for CPU efficiency.
    For very large PDFs, switches to a streaming two-pass approach that
    avoids holding all page texts in memory.

    Removes PDF artifacts including:
    - Form feed characters
    - "Page X" and "Page X of Y" patterns (case-insensitive)
    - Bracketed page numbers (e.g., "- 5 -", "[ 5 ]", "( 5 )")
    - Repeated textual headers/footers that appear across multiple pages
      (e.g., "Confidential", report titles). Lines appearing in the first
      or last HEADER_FOOTER_CANDIDATE_COUNT lines of >=50% of pages (using
      ceiling division, capped at 3, minimum 2 occurrences) are removed.
    - Standalone digit-only page numbers (1-4 digits) appearing in the first
      or last HEADER_FOOTER_CANDIDATE_COUNT lines of each page. This catches
      bare page numbers like "1", "42", etc. while preserving numbered list
      content in the page body.

    The file_path is normalized against REPO_ROOT before processing:
    - Relative paths are resolved as REPO_ROOT / file_path
    - Absolute paths are resolved to canonical form

    Args:
        file_path: Path to the PDF file (absolute or relative to REPO_ROOT).
        max_pages_to_cache: Maximum number of pages to cache in memory during
            processing. If page_count <= this threshold, uses single-pass caching
            (faster but more memory). If page_count > threshold, uses streaming
            two-pass approach (slower but memory-efficient). Defaults to 1000.
            Set to None for default behavior.

    Returns:
        Tuple of (raw_text, doc_id) where doc_id is pdf_{stem}_{timestamp}.

    Raises:
        FileNotFoundError: If the file does not exist.
        ImportError: If pypdf is not installed.
    """
    from pypdf import PdfReader

    # Default threshold for caching vs streaming
    if max_pages_to_cache is None:
        max_pages_to_cache = 1000

    resolved_path = _normalize_file_path(file_path)
    reader = PdfReader(resolved_path)
    page_count = len(reader.pages)

    # Choose processing strategy based on page count
    if page_count <= max_pages_to_cache:
        # Single-pass caching approach: Extract text once per page and cache for reuse.
        # This avoids calling page.extract_text() twice (once for candidate collection,
        # once for cleaning), reducing CPU usage for large PDFs at the cost of memory.
        page_texts: list[str] = []
        all_candidates: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            page_texts.append(page_text)
            candidates = _collect_header_footer_candidates(page_text)
            all_candidates.extend(candidates)

        # Identify repeated lines from collected candidates
        artifact_lines = _identify_repeated_lines_from_candidates(all_candidates, page_count)

        # Clean each page using cached text
        cleaned_parts: list[str] = []
        for page_text in page_texts:
            cleaned_page = _remove_artifact_lines(page_text, artifact_lines)
            # Remove standalone digit-only page numbers from page boundaries
            cleaned_page = _remove_page_number_lines(cleaned_page)
            cleaned_parts.append(cleaned_page)
    else:
        # Streaming two-pass approach for very large PDFs to minimize memory usage.
        # Pass 1: Iterate pages to collect header/footer candidates without storing text.
        all_candidates = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            candidates = _collect_header_footer_candidates(page_text)
            all_candidates.extend(candidates)
            # Do not store page_text - let it be garbage collected

        # Identify repeated lines from collected candidates
        artifact_lines = _identify_repeated_lines_from_candidates(all_candidates, page_count)

        # Pass 2: Re-extract each page's text and clean it immediately.
        # This re-extracts text (CPU cost) but avoids holding all pages in memory.
        cleaned_parts = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            cleaned_page = _remove_artifact_lines(page_text, artifact_lines)
            cleaned_page = _remove_page_number_lines(cleaned_page)
            cleaned_parts.append(cleaned_page)

    raw_text = "\n".join(cleaned_parts)

    # Remove form feed characters
    raw_text = raw_text.replace("\f", "")

    # Remove "Page X" patterns (case-insensitive)
    raw_text = re.sub(r"(?im)^Page\s+\d+\s*$", "", raw_text)

    # Remove "Page X of Y" patterns (case-insensitive)
    raw_text = re.sub(r"(?im)^Page\s+\d+\s+of\s+\d+\s*$", "", raw_text)

    # Remove standalone page numbers on lines with matching delimiters
    # Uses separate patterns for each delimiter style to ensure opening/closing match:
    # - Hyphen delimited: "- 5 -"
    # - Square bracket delimited: "[ 5 ]"
    # - Parenthesis delimited: "( 5 )"
    raw_text = re.sub(r"(?m)^-\s*\d+\s*-\s*$", "", raw_text)
    raw_text = re.sub(r"(?m)^\[\s*\d+\s*\]\s*$", "", raw_text)
    raw_text = re.sub(r"(?m)^\(\s*\d+\s*\)\s*$", "", raw_text)

    # NOTE: Digit-only page numbers are removed at page boundaries (first/last 3 lines
    # of each page) by _remove_page_number_lines(). This approach preserves legitimate
    # numbered list content in the body while catching bare page numbers.

    timestamp = _generate_timestamp()
    stem = _get_repo_relative_stem(resolved_path)
    doc_id = f"pdf_{stem}_{timestamp}"
    return raw_text, doc_id


def _extract_position_from_ijson_error(msg: str) -> int:
    """Extract numeric position from an ijson exception message.

    WARNING - Fragile Heuristic Implementation:
    This function relies on parsing backend-specific error message formats
    that are not part of any stable API contract. The message formats may
    change between ijson versions or when switching between backends
    (Python backend, YAJL backend, etc.). Callers should NOT assume accuracy
    of the returned position - it is a best-effort approximation for
    diagnostic purposes only.

    Backend-specific format handling:
    - Python backend: Parses "at N" or "at position N" patterns from messages
      like "Unexpected symbol 'key' at 1". This format is heuristic and may
      fail if the message wording changes.
    - YAJL backend: Attempts to extract position from visual caret markers
      in multi-line error output (e.g., lines containing "(right here)" with
      a "^" marker). This relies on specific formatting conventions that may
      vary across YAJL versions.

    Fallback behavior:
    When position extraction fails (unrecognized format, parsing error, or
    no position information in the message), this function silently returns 0.
    The fallback is intentional to allow callers to proceed with a default
    position rather than raising an exception, but it means the returned
    position may be completely inaccurate for the actual error location.

    Args:
        msg: The error message string from an ijson exception.

    Returns:
        Extracted position as an integer, or 0 if extraction fails.
        The returned value should be treated as approximate and unreliable.
    """
    # Pattern 1: Python backend format - "at N" or "at position N"
    # Examples: "Unexpected symbol 'key' at 1", "Unexpected token at position 17"
    match = re.search(r"\bat\s+(?:position\s+)?(\d+)\b", msg)
    if match:
        return int(match.group(1))

    # Pattern 2: YAJL backend format - extract position from caret alignment
    # Format has 3 lines: error description, JSON content, marker line with ^
    # Example:
    #   lexical error: invalid char in json text.
    #                               {"key": value}
    #                      (right here) ------^
    lines = msg.split("\n")
    if len(lines) >= 3:
        # Find the line containing "(right here)" and the caret
        for i, line in enumerate(lines):
            if "(right here)" in line and "^" in line:
                # The content line is typically the line before the marker line
                if i > 0:
                    content_line = lines[i - 1]
                    marker_line = line

                    # Find caret position in marker line
                    caret_pos = marker_line.find("^")
                    if caret_pos != -1:
                        # Find where content starts (strip leading whitespace)
                        stripped_content = content_line.lstrip()
                        if stripped_content:
                            content_start = len(content_line) - len(stripped_content)
                            # Calculate offset relative to content start
                            offset = caret_pos - content_start
                            if offset >= 0:
                                return offset
                break

    # Fallback: no position could be extracted
    return 0


def _stream_extract_json_values(file_path: Path) -> list[str]:
    """Extract all scalar values from JSON using streaming parser with key context.

    Uses ijson to parse JSON incrementally without loading entire file into memory.
    Wraps ijson exceptions to raise standard json.JSONDecodeError for consistency.

    Extracts string, number, boolean, and null values along with their JSON paths
    (key names), preserving original ordering. Each entry includes the field name
    to maintain document context that would otherwise be lost when extracting only
    values.

    Output format for each scalar:
    - For object properties: "key: value"
    - For array items: "item: value" (ijson uses "item" for array elements)
    - For root scalars: "value" (no prefix)

    Args:
        file_path: Path to the JSON file.

    Returns:
        List of key-prefixed scalar values (as strings) found in the structure.

    Raises:
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    import ijson
    import ijson.common

    values: list[str] = []
    try:
        with file_path.open("rb") as f:
            # Use ijson to stream parse and extract all scalar values with paths
            parser = ijson.parse(f)
            for prefix, event, value in parser:
                scalar_str: str | None = None

                if event == "string":
                    scalar_str = value
                elif event == "number":
                    # Convert number to string representation
                    scalar_str = str(value)
                elif event == "boolean":
                    # Convert boolean to lowercase string (true/false)
                    scalar_str = str(value).lower()
                elif event == "null":
                    # Convert null to string "null"
                    scalar_str = "null"

                if scalar_str is not None:
                    # Include the JSON path prefix to preserve field context
                    if prefix:
                        # Extract the last key from the path for concise output
                        # Full path would be prefix, but we use the last segment
                        # e.g., "metadata.author" -> "author: value"
                        # Note: ijson uses "item" for array elements, not numeric indices
                        path_parts = prefix.split(".")
                        last_part = path_parts[-1] if path_parts else ""
                        values.append(f"{last_part}: {scalar_str}")
                    else:
                        # Root-level scalar (rare but possible)
                        values.append(scalar_str)
    except ijson.common.IncompleteJSONError as e:
        # Convert ijson exception to standard json.JSONDecodeError
        msg = str(e)
        pos = _extract_position_from_ijson_error(msg)
        raise json.JSONDecodeError(msg, "", pos) from e
    except ijson.common.JSONError as e:
        # Handle other ijson parsing errors
        msg = str(e)
        pos = _extract_position_from_ijson_error(msg)
        raise json.JSONDecodeError(msg, "", pos) from e

    return values


def ingest_json_file(file_path: Path) -> tuple[str, str]:
    """Parse JSON file and extract all scalar values with field names using streaming.

    Uses ijson streaming parser to extract scalar values (strings, numbers,
    booleans, nulls) from nested JSON structures without loading entire file
    into memory, suitable for large files. Non-string scalars are converted
    to their string representation.

    Field names are preserved to maintain document context. Output format:
    - Object properties: "key: value" (the last key segment from the path)
    - Array items: "item: value" (ijson uses literal "item" for array elements,
      not numeric indices)
    - Root scalars: "value" (no prefix)

    This ensures the canonical string retains the semantic context of where
    values appeared in the original JSON structure, enabling proper fact
    extraction with field attribution.

    The file_path is normalized against REPO_ROOT before processing:
    - Relative paths are resolved as REPO_ROOT / file_path
    - Absolute paths are resolved to canonical form

    Args:
        file_path: Path to the JSON file (absolute or relative to REPO_ROOT).

    Returns:
        Tuple of (raw_text, doc_id) where doc_id is json_{stem}_{timestamp}.
        The raw_text includes field names prefixed to each scalar value.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    resolved_path = _normalize_file_path(file_path)
    values = _stream_extract_json_values(resolved_path)
    raw_text = "\n".join(values)

    timestamp = _generate_timestamp()
    stem = _get_repo_relative_stem(resolved_path)
    doc_id = f"json_{stem}_{timestamp}"
    return raw_text, doc_id


def create_canonical_string(raw_text: str) -> tuple[str, list[int]]:
    """Normalize raw text to canonical UTF-8 string with offset mapping.

    Applies the following transformations:
    1. Unicode NFC normalization
    2. Normalize whitespace: collapse multiple spaces/tabs to single space
    3. Normalize line endings to LF
    4. Remove control characters except LF and TAB
    5. Strip leading/trailing whitespace

    IMPORTANT - Coupling with validate_ingestion:
    This function's normalization rules are tightly coupled with the validation
    logic in validate_ingestion() and the offset mapping invariants. When
    modifying normalization rules (e.g., Unicode category handling, whitespace
    collapse, line-ending treatment, or stripping semantics), you MUST update
    validate_ingestion() and its offset validators in lockstep to preserve:
    - Type invariants: All mapping entries must be integers
    - Bounds invariants: Values must be -1 or within [0, len(canonical_string)]
    - Monotonicity: Non-removed entries must be non-decreasing
    - Coverage: Mapping must span the full canonical string range
    - Region boundary presence: Work region offsets must appear in mapped values

    Args:
        raw_text: Raw input text.

    Returns:
        Tuple of (canonical_string, offset_mapping) where offset_mapping is a list
        where offset_mapping[raw_offset] gives the corresponding canonical offset,
        or -1 if the character was removed during normalization.
    """
    # Initialize offset mapping: each raw position maps to itself initially
    # We'll track through each transformation
    raw_len = len(raw_text)

    # Step 1: Unicode NFC normalization with grapheme-aware offset mapping
    # Use regex \X to iterate through grapheme clusters, ensuring combining sequences
    # are normalized together (not character-by-character which would break composition).
    raw_to_nfc: list[int] = [-1] * raw_len  # Initialize all to -1
    nfc_parts: list[str] = []
    nfc_offset = 0

    for match in regex.finditer(r"\X", raw_text):
        raw_cluster = match.group()
        cluster_start = match.start()
        raw_cluster_len = len(raw_cluster)

        # Normalize this complete grapheme cluster (preserves combining sequences)
        nfc_cluster = unicodedata.normalize("NFC", raw_cluster)
        nfc_cluster_len = len(nfc_cluster)

        # Map each raw character position in this cluster to NFC position
        for i in range(raw_cluster_len):
            raw_idx = cluster_start + i
            if nfc_cluster_len == 0:
                # Cluster normalized to empty (extremely rare)
                raw_to_nfc[raw_idx] = -1
            elif i < nfc_cluster_len:
                # 1:1 mapping for positions that exist in both
                raw_to_nfc[raw_idx] = nfc_offset + i
            else:
                # Extra raw chars due to composition - map to last NFC char
                # (e.g., 'e' + combining accent -> 'é', both raw chars map to 'é')
                raw_to_nfc[raw_idx] = nfc_offset + nfc_cluster_len - 1

        nfc_parts.append(nfc_cluster)
        nfc_offset += nfc_cluster_len

    nfc_text = "".join(nfc_parts)

    # Step 2: Normalize line endings (\r\n -> \n, \r -> \n)
    # Build mapping from NFC to line-ending-normalized text
    nfc_to_lf: list[int] = []
    lf_text_parts: list[str] = []
    lf_idx = 0
    i = 0
    while i < len(nfc_text):
        if i < len(nfc_text) - 1 and nfc_text[i] == "\r" and nfc_text[i + 1] == "\n":
            # \r\n -> \n: \r maps to the resulting \n position, the original \n is absorbed
            nfc_to_lf.append(lf_idx)  # \r maps to the resulting \n
            lf_text_parts.append("\n")
            lf_idx += 1
            i += 1
            nfc_to_lf.append(-1)  # The original \n is absorbed (mapped to -1)
            i += 1
        elif nfc_text[i] == "\r":
            # \r -> \n
            nfc_to_lf.append(lf_idx)
            lf_text_parts.append("\n")
            lf_idx += 1
            i += 1
        else:
            nfc_to_lf.append(lf_idx)
            lf_text_parts.append(nfc_text[i])
            lf_idx += 1
            i += 1

    lf_text = "".join(lf_text_parts)

    # Step 3: Remove control characters except \n and \t
    def keep_char(c: str) -> bool:
        if c == "\n" or c == "\t":
            return True
        category = unicodedata.category(c)
        return category not in ("Cc", "Cf")

    lf_to_ctrl: list[int] = []
    ctrl_text_parts: list[str] = []
    ctrl_idx = 0
    for c in lf_text:
        if keep_char(c):
            lf_to_ctrl.append(ctrl_idx)
            ctrl_text_parts.append(c)
            ctrl_idx += 1
        else:
            lf_to_ctrl.append(-1)  # Removed

    ctrl_text = "".join(ctrl_text_parts)

    # Step 4: Collapse whitespace within lines (but preserve newlines)
    # Split by \n, process each line, rejoin
    lines = ctrl_text.split("\n")
    ctrl_to_ws: list[int] = []
    ws_text_parts: list[str] = []
    ws_idx = 0

    for line_idx, line in enumerate(lines):
        # Process whitespace collapsing within this line
        in_whitespace = False
        for c in line:
            if c in " \t":
                if not in_whitespace:
                    # First whitespace in a run - keep it as space
                    ctrl_to_ws.append(ws_idx)
                    ws_text_parts.append(" ")
                    ws_idx += 1
                    in_whitespace = True
                else:
                    # Additional whitespace - collapse (remove)
                    ctrl_to_ws.append(-1)
            else:
                ctrl_to_ws.append(ws_idx)
                ws_text_parts.append(c)
                ws_idx += 1
                in_whitespace = False

        # Add newline between lines (except after last line)
        # The newline in ctrl_text (consumed by split) must also get a mapping entry
        if line_idx < len(lines) - 1:
            ctrl_to_ws.append(ws_idx)  # Map the consumed newline from ctrl_text
            ws_text_parts.append("\n")
            ws_idx += 1

    ws_text = "".join(ws_text_parts)

    # Step 5: Strip leading/trailing whitespace
    stripped = ws_text.strip()
    leading_stripped = len(ws_text) - len(ws_text.lstrip())
    trailing_stripped = len(ws_text) - len(ws_text.rstrip())

    # Build mapping from ws_text to stripped text
    ws_to_final: list[int] = []
    for i in range(len(ws_text)):
        if i < leading_stripped:
            ws_to_final.append(-1)  # Leading whitespace removed
        elif i >= len(ws_text) - trailing_stripped:
            ws_to_final.append(-1)  # Trailing whitespace removed
        else:
            ws_to_final.append(i - leading_stripped)

    # Now compose all mappings: raw -> nfc -> lf -> ctrl -> ws -> final
    #
    # Mapping invariants and -1 propagation rationale:
    # - Each stage maps positions monotonically (non-decreasing) to subsequent stage offsets.
    #   This ensures that if raw_offset_a < raw_offset_b, then
    #   canonical_offset_a <= canonical_offset_b.
    # - Removed characters are represented by -1, meaning the character was deleted during
    #   normalization (e.g., collapsed whitespace, stripped control chars, CRLF->LF absorption).
    # - Valid mapped offsets may equal len(canonical_string) to represent end-of-string position,
    #   which is valid for exclusive end bounds in spans.
    # - The composition loop checks for -1 at each stage and immediately propagates it:
    #   once a character is removed at any stage, it remains removed in the final mapping.
    #   This "short-circuit on -1" pattern ensures that validators can rely on -1 meaning
    #   "this raw character has no corresponding position in the canonical string".
    # - Validators should treat -1 as "removed during normalization" - the character existed
    #   in the raw input but was intentionally deleted. This is distinct from an out-of-bounds
    #   error; -1 is a valid, expected value for characters that don't survive normalization.
    final_mapping: list[int] = []
    for raw_idx in range(raw_len):
        # Stage 1: raw -> NFC. If -1, character was absorbed during Unicode composition.
        nfc_idx = raw_to_nfc[raw_idx] if raw_idx < len(raw_to_nfc) else -1
        if nfc_idx == -1:
            final_mapping.append(-1)  # Propagate removal: no canonical position exists
            continue

        # Stage 2: NFC -> line-ending normalized. If -1, absorbed (e.g., \n in \r\n).
        lf_idx = nfc_to_lf[nfc_idx] if nfc_idx < len(nfc_to_lf) else -1
        if lf_idx == -1:
            final_mapping.append(-1)  # Propagate removal
            continue

        # Stage 3: line-ending -> control-char filtered. If -1, was a removed control char.
        ctrl_idx = lf_to_ctrl[lf_idx] if lf_idx < len(lf_to_ctrl) else -1
        if ctrl_idx == -1:
            final_mapping.append(-1)  # Propagate removal
            continue

        # Stage 4: control-filtered -> whitespace-collapsed. If -1, was collapsed whitespace.
        ws_idx = ctrl_to_ws[ctrl_idx] if ctrl_idx < len(ctrl_to_ws) else -1
        if ws_idx == -1:
            final_mapping.append(-1)  # Propagate removal
            continue

        # Stage 5: whitespace-collapsed -> stripped. If -1, was leading/trailing whitespace.
        final_idx = ws_to_final[ws_idx] if ws_idx < len(ws_to_final) else -1
        final_mapping.append(final_idx)  # May be -1 (stripped) or valid offset

    return stripped, final_mapping


# Default chunk size for work regions (in characters)
# This is sized to stay well within model context limits (typically ~100K tokens)
# Assuming ~4 chars per token, 32K chars is roughly 8K tokens which provides
# headroom for fact extraction prompts and responses
DEFAULT_CHUNK_SIZE: int = 32000


def _get_sentence_boundaries_fallback(text: str) -> list[int]:
    """Get sentence boundaries using simple regex-based splitting.

    This is a fallback implementation that uses a simple regex pattern to
    split on sentence-ending punctuation followed by whitespace.

    This fallback is less accurate than NLTK's punkt tokenizer for edge cases like:
    - Abbreviations (e.g., "Dr. Smith" may be incorrectly split)
    - Decimal numbers (e.g., "3.14" may be incorrectly split)
    - Quoted text with periods

    Args:
        text: The text to segment into sentences.

    Returns:
        List of character offsets where sentences end (exclusive bounds).
        Empty list if text is empty or has no sentences.
    """
    if not text:
        return []

    # Simple sentence boundary pattern: sentence-ending punctuation followed by
    # whitespace and optional capital letter (or end of string)
    # This pattern finds positions after sentence-ending punctuation
    boundaries: list[int] = []

    # Match sentence-ending punctuation followed by whitespace
    # Pattern: . ! or ? followed by one or more whitespace chars
    pattern = re.compile(r"[.!?]+\s+")

    for match in pattern.finditer(text):
        # The boundary is at the end of the whitespace (start of next sentence)
        boundaries.append(match.end())

    # If we found boundaries, adjust them to point to sentence ends (before whitespace)
    # and add the final sentence end
    if boundaries:
        # Convert from "start of next sentence" to "end of current sentence"
        # by finding where the punctuation ends
        adjusted_boundaries: list[int] = []
        last_end = 0
        for match in pattern.finditer(text):
            # Find where the punctuation ends (before whitespace)
            punct_end = match.start()
            while punct_end < match.end() and text[punct_end] in ".!?":
                punct_end += 1
            adjusted_boundaries.append(punct_end)
            last_end = match.end()

        # Add the final sentence (from last boundary to end of text)
        if last_end < len(text):
            adjusted_boundaries.append(len(text))

        return adjusted_boundaries
    elif text.strip():
        # No sentence boundaries found - treat entire text as one sentence
        return [len(text)]

    return []


def _ensure_nltk_data() -> None:
    """Ensure NLTK punkt tokenizer data is available.

    Downloads the punkt_tab data if not already present. This is called
    lazily on first use to avoid download overhead when sentence boundaries
    are not needed.
    """
    import nltk

    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)


def _get_sentence_boundaries(text: str) -> list[int]:
    """Get character offsets of sentence boundaries using NLTK punkt tokenizer.

    Uses NLTK's pre-trained punkt tokenizer which handles abbreviations,
    honorifics, and other edge cases better than simple regex patterns.

    Args:
        text: The text to segment into sentences.

    Returns:
        List of character offsets where sentences end (exclusive bounds).
        Empty list if text is empty or has no sentences.
    """
    if not text or not text.strip():
        return []

    # Ensure NLTK data is available
    _ensure_nltk_data()

    from nltk.tokenize import sent_tokenize

    sentences = sent_tokenize(text)

    if not sentences:
        return []

    # Convert sentences back to character offsets using linear scan
    # NLTK returns the actual sentence strings, so we track positions as we go
    boundaries: list[int] = []
    current_pos = 0

    for sentence in sentences:
        # Find sentence in text starting from current position
        idx = text.find(sentence, current_pos)
        if idx != -1:
            end_idx = idx + len(sentence)
            boundaries.append(end_idx)
            current_pos = end_idx
        else:
            # Sentence not found exactly - try normalized search
            # This handles cases where NLTK normalizes whitespace
            norm_sentence = " ".join(sentence.split())
            found = False
            search_pos = current_pos

            while search_pos < len(text) and not found:
                # Skip leading whitespace
                while search_pos < len(text) and text[search_pos].isspace():
                    search_pos += 1

                # Try to match from this position
                for end in range(
                    search_pos + 1, min(search_pos + len(sentence) + 20, len(text) + 1)
                ):
                    candidate = text[search_pos:end]
                    if " ".join(candidate.split()) == norm_sentence:
                        boundaries.append(end)
                        current_pos = end
                        found = True
                        break
                    if len(" ".join(candidate.split())) > len(norm_sentence):
                        break

                if not found:
                    search_pos += 1

            # If still not found, skip this sentence and log (rate-limited)
            if not found:
                global _unmatched_sentence_warnings
                if _unmatched_sentence_warnings < _UNMATCHED_SENTENCE_WARNING_LIMIT:
                    logger = logging.getLogger(__name__)
                    if logger.isEnabledFor(logging.WARNING):
                        sentence_preview = sentence[:50] + "..." if len(sentence) > 50 else sentence
                        logger.warning(
                            "Could not locate sentence in text at position %d: %r",
                            current_pos,
                            sentence_preview,
                        )
                    _unmatched_sentence_warnings += 1

    # Ensure we cover the full text
    if boundaries and boundaries[-1] < len(text):
        boundaries[-1] = len(text)
    elif not boundaries and text.strip():
        boundaries.append(len(text))

    return boundaries


def initialize_work_regions(
    canonical_string: str,
    doc_id: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[WorkRegion]:
    """Create initial work regions covering the entire document.

    For small documents (below chunk_size), creates a single WorkRegion.
    For large documents, splits into multiple regions at sentence boundaries
    to enable chunked processing and avoid exceeding model context limits.

    Chunking strategy:
    1. If document is smaller than chunk_size, return single region
    2. If chunk_size is 0, chunking is disabled and a single region is returned
    3. Otherwise, use NLTK's punkt tokenizer for sentence segmentation with
       a string-search fallback to locate boundaries in the original text
    4. Accumulate sentences until chunk_size is reached, then split
    5. Chunks are contiguous and non-overlapping (each region starts where
       the previous one ended)
    6. If NLTK yields no sentence boundaries (or effectively a single
       overlong sentence), the function splits the document into contiguous,
       non-overlapping regions of size chunk_size, with the final region
       potentially smaller than chunk_size

    Args:
        canonical_string: The normalized canonical text.
        doc_id: Document identifier.
        chunk_size: Target size for each work region (default: 32000 chars).
            Set to 0 to disable chunking and create a single region regardless
            of document size. Must be non-negative.

    Returns:
        List of WorkRegion objects covering the full document.

    Raises:
        ValueError: If chunk_size is negative.
    """
    if chunk_size < 0:
        msg = f"chunk_size must be non-negative, got {chunk_size}"
        raise ValueError(msg)

    doc_len = len(canonical_string)

    # Empty documents produce no regions (zero-length regions fail validation)
    if doc_len == 0:
        return []

    timestamp = _generate_iso_timestamp()

    # For small documents or when chunking is disabled, return single region
    if chunk_size == 0 or doc_len <= chunk_size:
        region = WorkRegion(
            region_id=f"{doc_id}_region_0",
            doc_id=doc_id,
            start_char=0,
            end_char=doc_len,
            is_processed=False,
            created_at=timestamp,
        )
        return [region]

    # Get sentence boundaries using NLTK
    sentence_ends = _get_sentence_boundaries(canonical_string)

    # Initialize regions list
    regions: list[WorkRegion] = []

    # If no sentence boundaries found, split at chunk_size intervals
    if not sentence_ends:
        region_idx = 0
        region_start = 0
        while region_start < doc_len:
            region_end = min(region_start + chunk_size, doc_len)
            region = WorkRegion(
                region_id=f"{doc_id}_region_{region_idx}",
                doc_id=doc_id,
                start_char=region_start,
                end_char=region_end,
                is_processed=False,
                created_at=timestamp,
            )
            regions.append(region)
            region_idx += 1
            region_start = region_end
        return regions

    # Build regions by accumulating sentences until chunk_size is reached
    region_idx = 0
    region_start = 0
    sent_idx = 0

    while sent_idx < len(sentence_ends):
        sent_end = sentence_ends[sent_idx]
        region_size = sent_end - region_start

        # If adding this sentence would exceed chunk_size and we have content,
        # close the current region before this sentence
        if region_size > chunk_size and region_start < sent_end:
            # Find the previous sentence boundary to split at
            # (the last sentence end that's before current position)
            prev_boundaries = [
                b for b in sentence_ends if b <= region_start + chunk_size and b > region_start
            ]
            if prev_boundaries:
                split_at = prev_boundaries[-1]
                region = WorkRegion(
                    region_id=f"{doc_id}_region_{region_idx}",
                    doc_id=doc_id,
                    start_char=region_start,
                    end_char=split_at,
                    is_processed=False,
                    created_at=timestamp,
                )
                regions.append(region)
                region_idx += 1
                region_start = split_at
                # Don't advance sent_idx - re-process the current sentence
                continue
            else:
                # No sentence boundary within chunk range - a single sentence exceeds chunk_size.
                # This is intentional: we hard-split at chunk_size to enforce chunk limits even
                # when it means breaking mid-sentence. The resulting chunk may be smaller than
                # chunk_size and will not respect sentence boundaries. This trade-off prioritizes
                # memory safety over sentence coherence. See README section "Chunking invariants".
                split_at = min(region_start + chunk_size, doc_len)
                region = WorkRegion(
                    region_id=f"{doc_id}_region_{region_idx}",
                    doc_id=doc_id,
                    start_char=region_start,
                    end_char=split_at,
                    is_processed=False,
                    created_at=timestamp,
                )
                regions.append(region)
                region_idx += 1
                region_start = split_at
                # Don't advance sent_idx - re-process the current sentence
                continue

        # Advance to next sentence
        sent_idx += 1

    # Add final region if there's remaining content
    if region_start < doc_len:
        region = WorkRegion(
            region_id=f"{doc_id}_region_{region_idx}",
            doc_id=doc_id,
            start_char=region_start,
            end_char=doc_len,
            is_processed=False,
            created_at=timestamp,
        )
        regions.append(region)

    return regions


def _has_isolated_page_numbers(
    text: str,
    min_occurrences: int = 2,
    adjacency_gap: int = PAGE_NUMBER_ADJACENCY_GAP,
) -> bool:
    r"""Check if text contains isolated digit-only lines that appear to be page numbers.

    Detects digit-only lines (1-4 digits) that are NOT part of a consecutive
    numbered list. Consecutive numbered lists like "1\n2\n3" are preserved,
    but isolated numbers or non-sequential numbers are flagged as page number
    artifacts.

    To avoid false positives from legitimate single-number content in PDF bodies,
    this function requires at least `min_occurrences` distinct isolated page numbers
    before returning True. A single standalone number is not enough to trigger
    artifact detection.

    Args:
        text: The text to check.
        min_occurrences: Minimum number of distinct isolated page numbers required
            to flag as artifacts. Default is 2 to avoid false positives from
            legitimate single-number content.
        adjacency_gap: Maximum line distance between digit-only lines to consider
            them part of a consecutive numbered sequence. Default is
            PAGE_NUMBER_ADJACENCY_GAP (4). Increase this value if your documents
            have numbered lists with more spacing between entries.

    Returns:
        True if at least `min_occurrences` isolated page number artifacts are
        detected, False otherwise.
    """
    import contextlib

    lines = text.split("\n")

    # Find all digit-only lines with their values and indices
    digit_lines: list[tuple[int, int]] = []  # (line_index, numeric_value)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and _PAGE_NUMBER_PATTERN.match(stripped):
            with contextlib.suppress(ValueError):
                digit_lines.append((i, int(stripped)))

    if not digit_lines:
        return False

    # Count isolated page numbers (not part of consecutive sequences)
    isolated_count = 0

    # Check if digit lines form consecutive sequences
    # A line is isolated if it's not adjacent to lines with consecutive values
    for idx, (line_idx, value) in enumerate(digit_lines):
        is_in_sequence = False

        # Check if previous digit line is consecutive (value - 1)
        if idx > 0:
            prev_line_idx, prev_value = digit_lines[idx - 1]
            # Must be adjacent lines (within adjacency_gap) and consecutive values
            if line_idx - prev_line_idx <= adjacency_gap and value == prev_value + 1:
                is_in_sequence = True

        # Check if next digit line is consecutive (value + 1)
        if idx < len(digit_lines) - 1:
            next_line_idx, next_value = digit_lines[idx + 1]
            # Must be adjacent lines (within adjacency_gap) and consecutive values
            if next_line_idx - line_idx <= adjacency_gap and next_value == value + 1:
                is_in_sequence = True

        # If this digit line is not part of a sequence, it's an isolated page number
        if not is_in_sequence:
            isolated_count += 1
            # Early exit if we've found enough isolated numbers
            if isolated_count >= min_occurrences:
                return True

    return False


def check_utf8_encoding(text: str) -> bool:
    """Check if text can be encoded and decoded as UTF-8 without data loss.

    Performs a round-trip encoding check: encode to UTF-8 bytes, decode back to
    string, and verify the result matches the original.

    Args:
        text: The string to validate.

    Returns:
        True if the round-trip succeeds and preserves the original text,
        False if encoding/decoding fails or produces a different result.
    """
    try:
        encoded = text.encode("utf-8")
        decoded = encoded.decode("utf-8")
        return decoded == text
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


def _has_json_structural_artifacts(text: str) -> bool:
    """Detect JSON structural artifacts using context-aware pattern matching.

    Distinguishes between:
    - True JSON structure: braces/brackets that are part of JSON syntax
    - Legitimate content: braces/brackets appearing inside scalar string values

    The JSON streaming extractor produces output in the format "key: value" for each
    scalar. Structural artifacts are patterns that indicate raw JSON syntax was not
    fully extracted, such as {"key": ...} or [...].

    Detection focuses on definite JSON structural patterns:
    1. Quoted keys: "key": (JSON object property syntax)
    2. Empty structures: {} or []
    3. Line-initial braces/brackets: lines starting with { or [
    4. Comma-adjacent braces/brackets: },  ], [, {, indicating array/object elements

    Braces/brackets appearing mid-content (e.g., "array [1,2,3] from {obj}") are
    allowed since they represent legitimate scalar value content.

    Args:
        text: The canonical string to check for JSON artifacts.

    Returns:
        True if JSON structural artifacts are detected, False otherwise.
    """
    # Pattern 1: Quoted key followed by colon - definite JSON object syntax
    # Matches: "key": or "key" : (with optional whitespace)
    # This is the most reliable indicator of unextracted JSON
    if re.search(r'"[^"]*"\s*:', text):
        return True

    # Pattern 2: Empty object or array - definite JSON structure
    # Only flag empty {} or [] that appear on their own line or are surrounded by
    # whitespace/line boundaries. This avoids false positives when these tokens
    # appear inside scalar string values like "An empty object {} is used here"
    # or "The empty set is denoted []".
    # Match: standalone on line (with optional surrounding whitespace)
    if re.search(r"(?m)^\s*\{\s*\}\s*$", text) or re.search(r"(?m)^\s*\[\s*\]\s*$", text):
        return True

    # Pattern 3: Line starting with brace/bracket (possibly with leading whitespace)
    # This catches raw JSON that starts at line beginning: { "key"..., [1, 2...
    # But allows braces/brackets that appear after content on a line
    if re.search(r"(?m)^\s*[{\[]", text):
        return True

    # Pattern 4: Comma immediately followed by brace/bracket or preceded by it
    # This catches JSON array/object element boundaries: ,{  ,[  },  ],
    # The comma indicates structure, not content
    # If none of the structural patterns match, the braces/brackets are likely
    # inside scalar content and should not be flagged
    return bool(re.search(r",\s*[{\[]", text) or re.search(r"[}\]]\s*,", text))


def validate_ingestion(
    canonical_string: str,
    work_regions: list[WorkRegion],
    source_is_json: bool = False,
    source_is_pdf: bool = False,
    offset_mapping: list[int] | None = None,
    expected_raw_length: int | None = None,
) -> dict[str, bool]:
    """Validate ingestion artifacts.

    Performs four validation checks:
    1. encoding_valid: UTF-8 encode/decode round-trip succeeds
    2. offsets_valid: All work region offsets satisfy 0 <= start < end <= len(canonical_string).
       Zero-length regions (start == end) are invalid.
    3. artifacts_removed: No format artifacts remain (form feeds, null bytes,
       page number patterns for PDF sources, JSON delimiters for JSON sources)
    4. offset_mapping_valid: All offset mapping entries are integers, and each value
       is either -1 (character removed during normalization) or within 0..len(canonical_string).
       Additionally, if expected_raw_length is provided, the offset_mapping length must
       match exactly (one entry per raw character).

    IMPORTANT - Coupling with create_canonical_string:
    This function's validation logic is tightly coupled with the normalization
    rules in create_canonical_string(). The offset_mapping_valid check enforces
    invariants that the normalization pipeline must preserve:
    - Type: All entries are integers
    - Bounds: Each entry is -1 or within [0, len(canonical_string)]
    - Monotonicity: Non-removed entries are non-decreasing
    - Coverage: min(non_removed) == 0 and max(non_removed) >= len - 1
    - Region boundaries: Work region start/end offsets appear in mapped values

    When modifying normalization rules in create_canonical_string() (e.g.,
    Unicode category handling, whitespace collapse, line-ending treatment,
    or stripping semantics), update this function and its checks in lockstep
    to preserve these invariants.

    Args:
        canonical_string: The normalized canonical text.
        work_regions: List of work regions to validate.
        source_is_json: Whether the source document was JSON format. JSON artifact
            checks only run when True to avoid false positives on prose containing
            legitimate quotation marks, colons, or brackets.
        source_is_pdf: Whether the source document was PDF format. PDF page-number
            artifact checks only run when True to avoid false positives on text
            documents containing legitimate numbered lists or numeric content.
        offset_mapping: Optional list mapping raw character offsets to canonical offsets.
            Each entry should be an integer: -1 if the character was removed, or
            0..len(canonical_string) if it maps to a valid canonical position.
        expected_raw_length: Expected length of the raw text. If provided and
            offset_mapping is also provided, the offset_mapping length must match
            this value exactly.

    Returns:
        Dict with four boolean keys: encoding_valid, offsets_valid, artifacts_removed,
        offset_mapping_valid.
    """
    # Check encoding validity using extracted helper function
    encoding_valid = check_utf8_encoding(canonical_string)

    # Check offsets validity
    # Require start < end (strict inequality) to reject zero-length regions
    offsets_valid = True
    for region in work_regions:
        start = region.start_char
        end = region.end_char
        if not (0 <= start < end <= len(canonical_string)):
            offsets_valid = False
            break

    # Check artifacts removed
    artifacts_removed = True

    # Basic control characters (always check)
    if "\f" in canonical_string or "\x00" in canonical_string:
        artifacts_removed = False

    # PDF page number/header artifact checks only apply to PDF source documents.
    # Non-PDF sources (text/JSON) may legitimately contain numbered lists or
    # numeric content, so we skip these checks to avoid false positives.
    if source_is_pdf:
        # "Page X" or "Page X of Y" patterns (case-insensitive, on their own lines)
        if re.search(r"(?im)^Page\s+\d+(\s+of\s+\d+)?\s*$", canonical_string):
            artifacts_removed = False

        # Standalone page numbers on lines with matching delimiters
        # Uses separate patterns for each delimiter style to ensure opening/closing match
        if (
            re.search(r"(?m)^-\s*\d+\s*-\s*$", canonical_string)
            or re.search(r"(?m)^\[\s*\d+\s*\]\s*$", canonical_string)
            or re.search(r"(?m)^\(\s*\d+\s*\)\s*$", canonical_string)
        ):
            artifacts_removed = False

        # Check for isolated digit-only lines that appear to be page numbers.
        # This catches bare page numbers (1-4 digits) that weren't removed during
        # ingestion. Consecutive numbered lists (1, 2, 3) are NOT flagged to avoid
        # false positives on legitimate list content. Additionally, a minimum of
        # 2 distinct isolated page numbers is required to avoid false positives
        # from legitimate single-number content in PDF bodies.
        if _has_isolated_page_numbers(canonical_string):
            artifacts_removed = False

    # JSON artifact checks only apply to JSON source documents.
    # Non-JSON sources (PDF/text) may legitimately contain quotes, colons, and brackets
    # in prose, so we skip these checks to avoid false positives.
    if source_is_json and _has_json_structural_artifacts(canonical_string):
        # Check for remaining JSON structural syntax using context-aware detection.
        # Scalar values may legitimately contain braces/brackets (e.g., a string value
        # describing code: "returns array [1,2] from object {key}"). We only flag
        # patterns that indicate actual JSON structure, not content within values.
        artifacts_removed = False

    # Check offset mapping validity
    # Each entry must be an integer that is either -1 (removed) or within [0, len(canonical_string)]
    # If expected_raw_length is provided, the mapping length must match exactly
    offset_mapping_valid = True
    if offset_mapping is not None:
        # Check length matches expected raw text length if provided
        if expected_raw_length is not None and len(offset_mapping) != expected_raw_length:
            offset_mapping_valid = False
        else:
            canonical_len = len(canonical_string)
            for entry in offset_mapping:
                # Check that entry is an integer
                if not isinstance(entry, int):
                    offset_mapping_valid = False
                    break
                # Check that entry is either -1 or within valid range [0, len(canonical_string)]
                # Note: Valid offsets can equal len(canonical_string) to point to end position
                if entry != -1 and (entry < 0 or entry > canonical_len):
                    offset_mapping_valid = False
                    break

            # Additional checks if basic validation passed
            if offset_mapping_valid:
                # Collect non-removed entries for monotonicity and coverage checks
                non_removed = [e for e in offset_mapping if e != -1]

                if non_removed:
                    # Check monotonicity: non-removed entries must be non-decreasing
                    for i in range(1, len(non_removed)):
                        if non_removed[i] < non_removed[i - 1]:
                            offset_mapping_valid = False
                            break

                    # Check coverage: min should be 0, max should be at least len - 1
                    # This ensures the mapping spans the full canonical string range
                    # (max can equal canonical_len for end position markers)
                    if offset_mapping_valid and canonical_len > 0:
                        min_offset = min(non_removed)
                        max_offset = max(non_removed)
                        if min_offset != 0 or max_offset < canonical_len - 1:
                            offset_mapping_valid = False

                    # Check work region offsets are present in mapping values
                    if offset_mapping_valid and work_regions:
                        non_removed_set = set(non_removed)
                        for region in work_regions:
                            # start_char must be in mapping values
                            if region.start_char not in non_removed_set:
                                offset_mapping_valid = False
                                break
                            # end_char must be in mapping values OR equal canonical_len
                            # (since end_char is exclusive, it can point past the last char)
                            if (
                                region.end_char not in non_removed_set
                                and region.end_char != canonical_len
                            ):
                                offset_mapping_valid = False
                                break
                elif canonical_len > 0:
                    # Non-empty canonical string but no mapped positions - invalid
                    offset_mapping_valid = False

    return {
        "encoding_valid": encoding_valid,
        "offsets_valid": offsets_valid,
        "artifacts_removed": artifacts_removed,
        "offset_mapping_valid": offset_mapping_valid,
    }


def _detect_text_encoding_from_bom(sample: bytes) -> str | None:
    """Detect text encoding from Byte Order Mark (BOM).

    Checks for common Unicode BOM signatures at the start of a byte sample.
    Order matters: UTF-32 BOMs are checked before UTF-16 BOMs because
    UTF-32 LE BOM (FF FE 00 00) starts with UTF-16 LE BOM (FF FE).

    Args:
        sample: Byte sample from the start of a file.

    Returns:
        Encoding name if a recognized BOM is found, None otherwise.
        Possible values: "utf-8-sig", "utf-32-le", "utf-32-be",
        "utf-16-le", "utf-16-be".
    """
    # UTF-8 BOM (EF BB BF)
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"

    # UTF-32 LE BOM (FF FE 00 00) - must check before UTF-16 LE
    if sample.startswith(b"\xff\xfe\x00\x00"):
        return "utf-32-le"

    # UTF-32 BE BOM (00 00 FE FF)
    if sample.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32-be"

    # UTF-16 LE BOM (FF FE)
    if sample.startswith(b"\xff\xfe"):
        return "utf-16-le"

    # UTF-16 BE BOM (FE FF)
    if sample.startswith(b"\xfe\xff"):
        return "utf-16-be"

    return None


def is_text_file(file_path: Path) -> bool:
    """Check if a file should be treated as plain text.

    Checks against known text extensions and also attempts to detect
    text files without extensions by reading the first bytes. Properly
    handles Unicode files with BOMs (UTF-8, UTF-16 LE/BE, UTF-32 LE/BE)
    which may contain null bytes as part of their encoding.

    Args:
        file_path: Path to the file to check.

    Returns:
        True if the file should be treated as plain text, False otherwise.
    """
    extension = file_path.suffix.lower()

    # Known text extensions
    if extension in TEXT_EXTENSIONS:
        return True

    # Files without extension - try to detect if they're text
    if not extension:
        try:
            # Read first 8KB and check if it's valid text
            with file_path.open("rb") as f:
                sample = f.read(8192)

            # Check for Unicode BOM signatures first - files with recognized BOMs
            # are treated as text even if they contain null bytes (which are
            # valid in UTF-16/UTF-32 encodings)
            detected_encoding = _detect_text_encoding_from_bom(sample)
            if detected_encoding is not None:
                # File has a recognized BOM - verify by attempting to decode
                try:
                    sample.decode(detected_encoding)
                    return True
                except (UnicodeDecodeError, LookupError) as e:
                    # BOM present but decode failed - treat as invalid/binary file
                    # Log the error for diagnostics before returning False
                    logger = logging.getLogger(__name__)
                    logger.debug(
                        "File %s has %s BOM but decoding failed: %s",
                        file_path,
                        detected_encoding,
                        e,
                    )
                    return False

            # No BOM detected - check for binary indicators (null bytes)
            # Null bytes indicate binary content for non-BOM files since
            # UTF-8/ASCII/latin-1 don't use null bytes in normal text
            if b"\x00" in sample[:1024]:
                return False

            # Try to decode as UTF-8
            try:
                sample.decode("utf-8")
                return True
            except UnicodeDecodeError:
                # Not valid UTF-8 but no null bytes - treat as text (could be latin-1)
                return True
        except OSError:
            return False

    return False


def ingest_document(
    file_path: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> tuple[str, str, list[WorkRegion], list[int], dict[str, bool]]:
    """Main entry point for document ingestion.

    Detects format from file extension and processes accordingly.
    Supported formats: text files (many extensions), .pdf, .json

    For large documents, work regions are automatically chunked to stay within
    model context limits. The chunk_size parameter controls the target size
    for each work region (default: 32000 chars, roughly 8K tokens).

    Args:
        file_path: Path to the input document.
        chunk_size: Target size for work regions in characters. Set to 0 to
            disable chunking. Default: DEFAULT_CHUNK_SIZE (32000 chars).

    Returns:
        Tuple of (canonical_string, doc_id, work_regions, offset_mapping, validation_results).
        The offset_mapping maps raw character offsets to canonical offsets (-1 if removed).

    Raises:
        ValueError: If the file format is not supported.
        FileNotFoundError: If the file does not exist.
    """
    extension = file_path.suffix.lower()
    source_is_json = False
    source_is_pdf = False

    if extension == ".pdf":
        raw_text, doc_id = ingest_pdf_file(file_path)
        source_is_pdf = True
    elif extension == ".json":
        raw_text, doc_id = ingest_json_file(file_path)
        source_is_json = True
    elif is_text_file(file_path):
        raw_text, doc_id = ingest_text_file(file_path)
    else:
        msg = f"Unsupported file format: {extension}. Supported: text files, .pdf, .json"
        raise ValueError(msg)

    canonical_string, offset_mapping = create_canonical_string(raw_text)
    work_regions = initialize_work_regions(canonical_string, doc_id, chunk_size=chunk_size)
    validation_results = validate_ingestion(
        canonical_string,
        work_regions,
        source_is_json,
        source_is_pdf,
        offset_mapping,
        expected_raw_length=len(raw_text),
    )

    return canonical_string, doc_id, work_regions, offset_mapping, validation_results


def expand_input_paths(input_args: list[str], base_path: Path) -> list[Path]:
    """Expand input arguments to a list of file paths.

    Handles:
    - Single files
    - Directories (recursively finds supported files)
    - Glob patterns

    Args:
        input_args: List of input paths from command line.
        base_path: Base path for resolving relative paths.

    Returns:
        List of resolved file paths to process.
    """
    import glob as glob_module

    files: list[Path] = []
    seen: set[Path] = set()

    for input_arg in input_args:
        input_path = Path(input_arg)
        if not input_path.is_absolute():
            input_path = base_path / input_path

        # Check if it's a glob pattern
        if "*" in input_arg or "?" in input_arg or "[" in input_arg:
            # Expand glob pattern with same filtering as directory recursion
            for match in glob_module.glob(str(input_path), recursive=True):
                match_path = Path(match)
                if match_path.is_file() and match_path not in seen:
                    ext_lower = match_path.suffix.lower()
                    if ext_lower in ALLOWED_TEXT_PDF_JSON_EXTENSIONS:
                        seen.add(match_path)
                        files.append(match_path)
                    elif not match_path.suffix and is_text_file(match_path):
                        # Files without extensions - check if they're text
                        seen.add(match_path)
                        files.append(match_path)
        elif input_path.is_dir():
            # Recursively find all supported files in directory
            # Use case-insensitive extension matching to handle .PDF, .JSON, .TXT, etc.
            # on case-sensitive filesystems
            for file_path in input_path.rglob("*"):
                if file_path.is_file() and file_path not in seen:
                    ext_lower = file_path.suffix.lower()
                    if ext_lower in ALLOWED_TEXT_PDF_JSON_EXTENSIONS:
                        seen.add(file_path)
                        files.append(file_path)
                    elif not file_path.suffix and is_text_file(file_path):
                        # Files without extensions - check if they're text
                        seen.add(file_path)
                        files.append(file_path)
        elif input_path.is_file() and input_path not in seen:
            # Apply same filtering as glob/directory branches
            ext_lower = input_path.suffix.lower()
            if ext_lower in ALLOWED_TEXT_PDF_JSON_EXTENSIONS:
                seen.add(input_path)
                files.append(input_path)
            elif not input_path.suffix and is_text_file(input_path):
                # Files without extensions - check if they're text
                seen.add(input_path)
                files.append(input_path)
            # Otherwise skip the file (unsupported extension)

    # Sort for deterministic ordering
    return sorted(files)


def _validate_non_negative_int(value: str) -> int:
    """Validate that a string value is a non-negative integer.

    Args:
        value: String value from argument parser.

    Returns:
        Integer value if non-negative.

    Raises:
        argparse.ArgumentTypeError: If value is not a non-negative integer.
    """
    try:
        int_value = int(value)
    except ValueError:
        msg = f"invalid int value: '{value}'"
        raise argparse.ArgumentTypeError(msg) from None

    if int_value < 0:
        msg = f"must be non-negative, got {int_value}"
        raise argparse.ArgumentTypeError(msg)
    return int_value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Command line arguments. Defaults to sys.argv[1:].

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(description="Ingest documents for atomic fact extraction.")
    parser.add_argument(
        "--input",
        required=True,
        nargs="+",
        help="Input file(s) or directory. Accepts multiple paths, globs, or a directory.",
    )
    parser.add_argument(
        "--output",
        default=".tmp/ingestion",
        help="Output directory (default: .tmp/ingestion).",
    )
    parser.add_argument(
        "--chunk-size",
        type=_validate_non_negative_int,
        default=DEFAULT_CHUNK_SIZE,
        help=(
            f"Target size for work regions in characters (default: {DEFAULT_CHUNK_SIZE}). "
            "Set to 0 to disable chunking. Must be non-negative."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing files.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run validation only and print results.",
    )
    return parser.parse_args(argv)


def _ingest_single_file(
    input_path: Path,
    output_dir: Path,
    validate_only: bool,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> tuple[bool, str | None]:
    """Ingest a single document file.

    Args:
        input_path: Path to the input document.
        output_dir: Output directory for artifacts.
        validate_only: If True, only run validation without writing files.
        chunk_size: Target size for work regions in characters.

    Returns:
        Tuple of (success, doc_id). doc_id is None on failure.
    """
    # Ingest the document
    # Note: Exception handlers are ordered from most specific to most general.
    # json.JSONDecodeError inherits from ValueError, so it must be caught before ValueError.
    try:
        result = ingest_document(input_path, chunk_size=chunk_size)
        canonical_string, doc_id, work_regions, offset_mapping, validation_results = result
    except json.JSONDecodeError as e:
        print(f"Invalid JSON ({input_path}): {e}", file=sys.stderr)
        return False, None
    except ValueError as e:
        print(f"Error ({input_path}): {e}", file=sys.stderr)
        return False, None
    except OSError as e:
        # Covers FileNotFoundError, PermissionError, IOError for file I/O issues
        print(f"File I/O error ({input_path}): {e}", file=sys.stderr)
        return False, None
    except ImportError as e:
        # Missing optional dependency (e.g., pypdf for PDF files)
        print(f"Missing dependency ({input_path}): {e}", file=sys.stderr)
        return False, None
    except PyPdfError as e:
        # Explicitly catch pypdf exceptions (PdfReadError, ParseError, etc.)
        # PyPdfError is the base class for all pypdf-specific errors
        error_type = type(e).__name__
        print(f"PDF parsing error ({input_path}, {error_type}): {e}", file=sys.stderr)
        return False, None

    # Handle validate-only mode
    if validate_only:
        print(f"Validation Results for {input_path}:")
        for key, value in validation_results.items():
            status = "PASS" if value else "FAIL"
            print(f"  {key}: {status}")
        all_passed = all(validation_results.values())
        return all_passed, doc_id

    # Check validation before writing output (STOP+REPORT on validation failure)
    if not all(validation_results.values()):
        print(f"Error: Validation failed for {input_path}. Skipping.", file=sys.stderr)
        print("Validation Results:", file=sys.stderr)
        for key, value in validation_results.items():
            status = "PASS" if value else "FAIL"
            print(f"  {key}: {status}", file=sys.stderr)
        return False, doc_id

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write canonical string
    canonical_path = output_dir / f"{doc_id}_canonical.txt"
    canonical_path.write_text(canonical_string, encoding="utf-8")

    # Write work regions as JSON array
    work_regions_path = output_dir / f"{doc_id}_work_regions.json"
    work_regions_json = [work_region_to_json(region) for region in work_regions]
    work_regions_path.write_text(
        json.dumps(work_regions_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write offset mapping (raw offset -> canonical offset, -1 if removed)
    offset_mapping_path = output_dir / f"{doc_id}_offset_mapping.json"
    offset_mapping_path.write_text(
        json.dumps(offset_mapping, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write validation results
    validation_path = output_dir / f"{doc_id}_validation.json"
    validation_path.write_text(json.dumps(validation_results, indent=2), encoding="utf-8")

    # Print summary
    print(f"Ingested: {input_path}")
    print(f"  Document ID: {doc_id}")
    print(f"  Canonical string length: {len(canonical_string)} chars")
    print(f"  Work regions: {len(work_regions)}")
    print(f"  Offset mapping entries: {len(offset_mapping)}")

    return True, doc_id


def document_ingestion_main(args: argparse.Namespace) -> int:
    """Execute document ingestion based on parsed arguments.

    Supports multiple input files, directories, and glob patterns.
    Processes each file and aggregates results.

    Args:
        args: Parsed command line arguments.

    Returns:
        Exit code: 0 on success, 1 if any files failed.
    """
    # Expand input paths to list of files
    input_files = expand_input_paths(args.input, REPO_ROOT)

    if not input_files:
        print("Error: No valid input files found.", file=sys.stderr)
        return 1

    # Resolve output directory
    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir

    # Handle dry-run mode
    if args.dry_run:
        print(f"Would ingest {len(input_files)} file(s):")
        for f in input_files:
            print(f"  - {f} (format: {f.suffix or 'text'})")
        print(f"Output directory: {output_dir}")
        print("Files to create per document:")
        print("  - {doc_id}_canonical.txt")
        print("  - {doc_id}_work_regions.json")
        print("  - {doc_id}_offset_mapping.json")
        print("  - {doc_id}_validation.json")
        return 0

    # Process each file
    success_count = 0
    failure_count = 0
    doc_ids: list[str] = []

    for input_path in input_files:
        success, doc_id = _ingest_single_file(
            input_path, output_dir, args.validate_only, args.chunk_size
        )
        if success:
            success_count += 1
            if doc_id:
                doc_ids.append(doc_id)
        else:
            failure_count += 1

    # Print summary for multi-file processing
    if len(input_files) > 1:
        print(f"\nSummary: {success_count} succeeded, {failure_count} failed")
        if not args.validate_only:
            print(f"Output directory: {output_dir}")

    # Return 1 if any files failed
    return 0 if failure_count == 0 else 1


def main() -> int:
    """Entry point for document ingestion CLI.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    args = parse_args()
    return document_ingestion_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
