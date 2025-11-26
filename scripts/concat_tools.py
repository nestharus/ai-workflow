"""Concatenate all files under tools/ into a single file with path headings.

The script walks the tools/ directory tree recursively and writes a combined
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
TOOLS_DIR = REPO_ROOT / "tools"
DEFAULT_OUTPUT = REPO_ROOT / "tools_concatenated.txt"


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser for the tools concatenation script."""
    parser = argparse.ArgumentParser(
        description=(
            "Concatenate all files under tools/ into a single file with "
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


def _iter_tools_files() -> list[Path]:
    """Return sorted files within tools/ (recursive, excluding __pycache__)."""
    if not TOOLS_DIR.is_dir():
        msg = f"Tools directory not found at {TOOLS_DIR}"
        raise FileNotFoundError(msg)

    files = [
        path for path in TOOLS_DIR.rglob("*") if path.is_file() and "__pycache__" not in path.parts
    ]
    return sorted(
        files,
        key=lambda path: path.resolve().relative_to(REPO_ROOT).as_posix(),
    )


def concatenate_tools(output_path: Path) -> None:
    """Concatenate all tools files into a single output file."""
    files = _iter_tools_files()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written_index = 0
    with output_path.open("w", encoding="utf-8") as destination:
        for file_path in files:
            if file_path.resolve() == output_path:
                continue
            relative_label = file_path.resolve().relative_to(REPO_ROOT)
            heading = f"===== {relative_label.as_posix()} =====\n"
            if written_index:
                destination.write("\n")
            destination.write(heading)

            content = file_path.read_text(encoding="utf-8", errors="replace")
            destination.write(content)
            if not content.endswith("\n"):
                destination.write("\n")
            written_index += 1


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the tools concatenation script."""
    args = parse_args(argv)
    concatenate_tools(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
