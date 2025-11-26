"""Concatenate all files under scripts/ into a single file with path headings.

The script walks the scripts/ directory tree recursively and writes a combined
text file where each section is preceded by a heading containing the file path
relative to the repository root. ``__pycache__`` directories are excluded.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from scripts.utils import (
    REPO_ROOT,
    iter_directory_files,
    parse_concat_args,
    write_concatenated_files,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


SCRIPTS_DIR = REPO_ROOT / "scripts"
DEFAULT_OUTPUT = REPO_ROOT / "scripts_concatenated.txt"


def concatenate_scripts(output_path: Path) -> None:
    """Concatenate all scripts files into a single output file."""
    files = iter_directory_files(SCRIPTS_DIR)
    write_concatenated_files(files, output_path)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the scripts concatenation script."""
    args = parse_concat_args("scripts", DEFAULT_OUTPUT, argv)
    concatenate_scripts(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
