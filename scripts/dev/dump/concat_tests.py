"""Concatenate all files under tests/ into a single file with path headings.

The script walks the tests/ directory tree recursively (including ``conftest``
files) and writes a combined text file where each section is preceded by a
heading containing the file path relative to the repository root. ``__pycache__``
directories are excluded.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from scripts.dev.utils import (
    REPO_ROOT,
    iter_directory_files,
    parse_concat_args,
    write_concatenated_files,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


TESTS_DIR = REPO_ROOT / "tests"
DEFAULT_OUTPUT = REPO_ROOT / "tests_concatenated.txt"


def concatenate_tests(output_path: Path) -> None:
    """Concatenate all tests files into a single output file."""
    files = iter_directory_files(TESTS_DIR)
    write_concatenated_files(files, output_path)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the tests concatenation script."""
    args = parse_concat_args("tests", DEFAULT_OUTPUT, argv)
    concatenate_tests(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
