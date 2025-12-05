"""Concatenate all files under app/ into a single file with path headings.

The script walks the app/ directory tree recursively and writes a combined
text file where each section is preceded by a heading containing the file
path relative to the repository root.
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


APP_DIR = REPO_ROOT / "app"
DEFAULT_OUTPUT = REPO_ROOT / "app_concatenated.txt"


def concatenate_app(output_path: Path) -> None:
    """Concatenate all app files into a single output file."""
    files = iter_directory_files(APP_DIR)
    write_concatenated_files(files, output_path)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the app concatenation script."""
    args = parse_concat_args("app", DEFAULT_OUTPUT, argv)
    concatenate_app(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
