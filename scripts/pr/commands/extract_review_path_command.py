"""Extract CodeRabbit review file path from command output.

Parses stdout from a CodeRabbit review command and extracts the review file path.
Includes security validations to prevent path traversal attacks.

Usage:
    echo "$stdout" | uv run pr extract-review-path
"""

from __future__ import annotations

import re
import sys


def _is_valid_hex(chars: str) -> bool:
    """Check if chars is exactly 2 valid hex digits.

    Args:
        chars: String to check.

    Returns:
        True if chars is exactly 2 hex digits (0-9, a-f, A-F).
    """
    if len(chars) != 2:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in chars)


def _percent_decode(input_str: str) -> str | None:
    """URL-style percent-decoder for file paths.

    Decodes %HH sequences where HH are two valid hex digits.
    Rejects encoded path separators (%2F, %5C) to prevent path traversal.

    Args:
        input_str: The percent-encoded string.

    Returns:
        Decoded string on success, None on failure.
    """
    result_bytes: list[int] = []
    i = 0

    while i < len(input_str):
        if input_str[i] == "%":
            # Check for valid %HH sequence
            if i + 2 >= len(input_str):
                return None  # Incomplete sequence

            hex_chars = input_str[i + 1 : i + 3]
            if not _is_valid_hex(hex_chars):
                return None  # Invalid hex digits

            byte_value = int(hex_chars, 16)

            # Security: Do NOT decode encoded path separators
            # %2F = '/', %5C = '\' - these could change path structure
            if byte_value in (0x2F, 0x5C):
                return None  # Reject encoded path separators

            result_bytes.append(byte_value)
            i += 3
        else:
            result_bytes.append(ord(input_str[i]))
            i += 1

    # Interpret byte sequence as UTF-8
    try:
        decoded = bytes(result_bytes).decode("utf-8")
    except UnicodeDecodeError:
        return None  # Invalid UTF-8 sequence

    # Final security check: reject if decoding introduced traversal
    if ".." in decoded:
        return None

    return decoded


def _extract_path_from_line(line: str) -> str | None:
    """Extract the review file path from a line containing '.review/'.

    Uses permissive matching with layered validation:
    1. Trailing punctuation is stripped post-match
    2. Percent-encoded sequences are decoded (with path separator rejection)
    3. '..' segments are rejected to block parent directory traversal

    Args:
        line: A line of text that may contain a review file path.

    Returns:
        The extracted path, or None if no valid path found.
    """
    # Match pattern: ".review/" followed by non-whitespace, non-delimiter chars
    matches = re.findall(r"\.review/[^\s'\"``]*", line)

    if not matches:
        return None

    path = matches[0]  # Take first/leftmost match

    # Strip trailing punctuation: . , ; : ? )
    while path and path[-1] in ".,;:?)":
        path = path[:-1]

    if not path:
        return None

    # Percent-decode the path (e.g., %20 -> space)
    decoded_path = _percent_decode(path)
    if decoded_path is None:
        return None

    # Normalize path: reject '..' segments for security
    if ".." in decoded_path:
        return None

    return decoded_path


def extract_review_path_command() -> int:
    """Extract review file path from stdin.

    Reads CodeRabbit command output from stdin and extracts the first
    line containing a '.review/' path. Outputs one of:
    - REVIEW_FILE: <path>  (success)
    - NO_CHANGES           (no review path found, exit 0)
    - ERROR: <message>     (validation failure, exit 1)

    Returns:
        Exit code (0 for success/no-changes, 1 for error).
    """
    try:
        stdout = sys.stdin.read()
    except UnicodeDecodeError:
        print("ERROR: stdin contains invalid UTF-8")
        return 1

    # Scan line by line for .review/ path
    for line in stdout.splitlines():
        if ".review/" in line:
            path = _extract_path_from_line(line)
            if path:
                print(f"REVIEW_FILE: {path}")
                return 0

    # No matching lines found - no changes to review
    print("NO_CHANGES")
    return 0
