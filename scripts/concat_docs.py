"""Concatenate top-level files in docs/ into a single file with path headings.

The script looks only at immediate children of the docs/ directory (non-recursive)
and writes a combined text file with headings containing paths relative to the
repository root.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_OUTPUT = REPO_ROOT / "docs_concatenated.txt"


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser for the docs concatenation script."""
    parser = argparse.ArgumentParser(
        description=(
            "Concatenate non-recursive files in docs/ into a single file "
            "with headings using paths relative to the repository root."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "Output file path (default: %(default)s). The file will be "
            "overwritten if it already exists."
        ),
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse and return CLI arguments."""
    parser = build_parser()
    return parser.parse_args(argv)


def _iter_docs_files() -> list[Path]:
    """Return sorted immediate child files within docs/ (non-recursive)."""
    if not DOCS_DIR.is_dir():
        msg = f"Docs directory not found at {DOCS_DIR}"
        raise FileNotFoundError(msg)

    files = [path for path in DOCS_DIR.iterdir() if path.is_file()]
    return sorted(files, key=lambda path: path.name)


def concatenate_docs(output_path: Path) -> None:
    """Concatenate top-level docs files into a single output file."""
    files = _iter_docs_files()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as destination:
        for index, file_path in enumerate(files):
            relative_label = file_path.resolve().relative_to(REPO_ROOT)
            heading = f"===== {relative_label.as_posix()} =====\n"
            if index:
                destination.write("\n")
            destination.write(heading)

            content = file_path.read_text(encoding="utf-8", errors="replace")
            destination.write(content)
            if not content.endswith("\n"):
                destination.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the docs concatenation script."""
    args = parse_args(argv)
    concatenate_docs(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
