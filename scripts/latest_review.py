"""Locate the most recent review artifact in .review.

Usage:
    uv run latest-review --type coderabbit
    uv run latest-review --type sonar --dir /path/to/reviews

Notes:
- This script does not run reviews; it only finds existing artifacts.
- Files should use UTC timestamp prefixes (e.g., 20250101T120000Z.review.coderabbit).
"""

from __future__ import annotations

import argparse
from pathlib import Path

REVIEW_SUFFIXES = {
    "coderabbit": ".review.coderabbit",
    "sonar": ".review.sonar",
}


class ReviewDirectoryNotFoundError(FileNotFoundError):
    """Raised when the expected review directory does not exist."""

    def __init__(self, directory: Path) -> None:
        """Store the missing directory path in the message."""
        super().__init__(f"Review directory not found: {directory}")


class ReviewFileNotFoundError(FileNotFoundError):
    """Raised when no review files with the expected suffix are found."""

    def __init__(self, suffix: str, directory: Path) -> None:
        """Store the suffix and directory in the error message."""
        message = (
            f"No files ending with {suffix} found in {directory}. Ensure the review command ran."
        )
        super().__init__(message)


def find_latest(review_type: str, directory: Path) -> Path:
    """Return the newest review file path for the given type."""
    suffix = REVIEW_SUFFIXES[review_type]
    if not directory.is_dir():
        raise ReviewDirectoryNotFoundError(directory)

    candidates = sorted(directory.glob(f"*{suffix}"))
    if not candidates:
        raise ReviewFileNotFoundError(suffix, directory)

    return candidates[-1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for locating review artifacts."""
    parser = argparse.ArgumentParser(description="Find the newest review artifact")
    parser.add_argument(
        "--type",
        required=True,
        choices=sorted(REVIEW_SUFFIXES.keys()),
        help="Review type to locate (coderabbit or sonar)",
    )
    parser.add_argument(
        "--dir",
        dest="directory",
        default=".review",
        help="Directory to search (default: .review)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for locating the latest review file."""
    args = parse_args(argv)
    directory = Path(args.directory)

    try:
        latest = find_latest(args.type, directory)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    print(latest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
