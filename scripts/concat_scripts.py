"""Concatenate all files under scripts/ into a single file with path headings.

The script walks the scripts/ directory tree recursively and writes a combined
text file where each section is preceded by a heading containing the file path
relative to the repository root. ``__pycache__`` directories are excluded.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
DEFAULT_OUTPUT = REPO_ROOT / "scripts_concatenated.txt"


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser for the scripts concatenation script."""
    parser = argparse.ArgumentParser(
        description=(
            "Concatenate all files under scripts/ into a single file with "
            "headings using paths relative to the repository root."
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


def _iter_scripts_files() -> list[Path]:
    """Return sorted files within scripts/ (recursive, excluding __pycache__)."""
    if not SCRIPTS_DIR.is_dir():
        msg = f"Scripts directory not found at {SCRIPTS_DIR}"
        raise FileNotFoundError(msg)

    files = [
        path
        for path in SCRIPTS_DIR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    return sorted(
        files,
        key=lambda path: path.relative_to(REPO_ROOT).as_posix(),
    )


def concatenate_scripts(output_path: Path) -> None:
    """Concatenate all scripts files into a single output file."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    files = [f for f in _iter_scripts_files() if f.resolve() != output_path]

    with output_path.open("w", encoding="utf-8") as destination:
        for index, file_path in enumerate(files):
            relative_label = file_path.resolve().relative_to(REPO_ROOT)
            heading = f"===== {relative_label.as_posix()} =====\n"
            if index > 0:
                destination.write("\n")
            destination.write(heading)

            content = file_path.read_text(encoding="utf-8", errors="replace")
            destination.write(content)
            if not content.endswith("\n"):
                destination.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the scripts concatenation script."""
    args = parse_args(argv)
    concatenate_scripts(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
