"""Concatenate top-level files in docs/ into a single file with path headings.

The script looks only at immediate children of the docs/ directory (non-recursive)
and writes a combined text file with headings containing paths relative to the
repository root.
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


DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_OUTPUT = REPO_ROOT / "docs_concatenated.txt"


def concatenate_docs(output_path: Path) -> None:
    """Concatenate top-level docs files into a single output file."""
    files = iter_directory_files(DOCS_DIR, recursive=False)
    write_concatenated_files(files, output_path)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the docs concatenation script."""
    args = parse_concat_args("docs", DEFAULT_OUTPUT, argv)
    concatenate_docs(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
