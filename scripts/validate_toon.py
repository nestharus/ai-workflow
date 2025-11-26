"""Validate all TOON files in the repository for syntax and structural correctness.

Note for developers: Validation error fixtures from the TOON spec repository can be used
to verify coverage during development:
https://github.com/toon-format/spec/raw/refs/heads/main/tests/fixtures/decode/validation-errors.json
These fixtures should NOT be bundled with the linter; they are for testing purposes only.
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import toon_format
from toon_format import DecodeOptions, ToonDecodeError

from scripts.utils import REPO_ROOT

TOON_FILE_PATTERN = "**/*.toon"
EXCLUDED_DIRS = {
    ".venv",
    ".venv2",
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "build",
    "dist",
}

# Regex patterns for extracting line numbers from error messages
_LINE_NUMBER_PATTERNS = [
    re.compile(r"line\s+(\d+)", re.IGNORECASE),
    re.compile(r"at\s+line\s+(\d+)", re.IGNORECASE),
    re.compile(r"on\s+line\s+(\d+)", re.IGNORECASE),
    re.compile(r"Line\s+(\d+):"),
]


def _extract_line_number(error_msg: str) -> int | None:
    """Extract a line number from an error message if present.

    Searches for common line number patterns in exception messages
    such as "line N", "at line N", "on line N", or "Line N:".

    Args:
        error_msg: The error message string to parse.

    Returns:
        The extracted line number as an integer, or None if not found.
    """
    for pattern in _LINE_NUMBER_PATTERNS:
        match = pattern.search(error_msg)
        if match:
            return int(match.group(1))
    return None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for TOON validation.

    Args:
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace with path and verbose attributes.
    """
    parser = argparse.ArgumentParser(
        description="Validate all TOON files for syntax and structural correctness.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=REPO_ROOT,
        help="Root path to search for TOON files (default: repository root).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output showing each file as it is validated.",
    )
    return parser.parse_args(argv)


def find_toon_files(root_path: Path) -> list[Path]:
    """Discover all TOON files under the given path, excluding common directories.

    Args:
        root_path: Root directory to search for TOON files.

    Returns:
        Sorted list of Path objects pointing to .toon files.
    """
    files = [
        path
        for path in root_path.rglob(TOON_FILE_PATTERN)
        if path.is_file() and not any(excluded in path.parts for excluded in EXCLUDED_DIRS)
    ]
    return sorted(files)


def validate_toon_file(file_path: Path) -> tuple[bool, str | None]:
    """Validate a single TOON file for syntax and structural correctness.

    Args:
        file_path: Path to the TOON file to validate.

    Returns:
        A tuple of (is_valid, error_message). If valid, error_message is None.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        toon_format.decode(content, DecodeOptions(strict=True))
        return (True, None)
    except ToonDecodeError as exc:
        relative_path = file_path.relative_to(REPO_ROOT)
        error_str = str(exc)
        line_num = _extract_line_number(error_str)
        if line_num is not None:
            error_msg = f"{relative_path}:{line_num}: {error_str}"
        else:
            error_msg = f"{relative_path}: {error_str}"
        return (False, error_msg)
    except Exception as exc:
        relative_path = file_path.relative_to(REPO_ROOT)
        error_msg = f"{relative_path}: {exc}"
        return (False, error_msg)


def main() -> int:
    """Execute TOON validation and return a process exit code.

    Returns:
        0 if all files are valid, 1 if any validation fails.
    """
    args = parse_args()
    root_path = args.path.resolve()
    toon_files = find_toon_files(root_path)

    if not toon_files:
        print(f"No TOON files found in {root_path}.")
        return 0

    print(f"Validating {len(toon_files)} TOON file(s)...")

    errors: list[str] = []
    for file_path in toon_files:
        if args.verbose:
            relative = file_path.relative_to(root_path)
            print(f"  Checking {relative}...")
        is_valid, error_msg = validate_toon_file(file_path)
        if not is_valid and error_msg:
            errors.append(error_msg)

    if errors:
        print("\nTOON validation errors:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print("All TOON files are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
