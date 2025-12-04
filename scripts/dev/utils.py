"""Shared utilities for review wrapper scripts."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class StdoutCaptureError(RuntimeError):
    """Raised when process output cannot be read."""

    def __init__(self, message: str = "Failed to capture stdout from process") -> None:
        """Initialize with a default or custom message."""
        super().__init__(message)


def utc_timestamp() -> str:
    """Return a UTC timestamp string in ISO 8601 basic format."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_command_with_tee(cmd: list[str], output_path: Path) -> int:
    """Run a command, tee output to file and stdout, return exit code.

    Args:
        cmd: Command and arguments to execute.
        output_path: Path to write combined stdout/stderr output.

    Returns:
        The process exit code.

    Raises:
        StdoutCaptureError: If stdout pipe cannot be read.
    """
    with output_path.open("w", encoding="utf-8") as outfile:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        stdout = process.stdout
        if stdout is None:  # pragma: no cover - defensive guard
            process.kill()
            raise StdoutCaptureError()
        try:
            for line in stdout:
                sys.stdout.write(line)
                outfile.write(line)
        except Exception:
            process.kill()
            raise
        return process.wait()


def iter_directory_files(
    directory: Path,
    *,
    recursive: bool = True,
) -> list[Path]:
    """Return sorted files within a directory.

    Args:
        directory: Directory path to iterate.
        recursive: If True, use rglob for recursive search; otherwise use iterdir.

    Returns:
        Sorted list of file paths, excluding __pycache__ directories.

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    if not directory.is_dir():
        msg = f"Directory not found at {directory}"
        raise FileNotFoundError(msg)

    if recursive:
        files = [
            path
            for path in directory.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ]
    else:
        files = [path for path in directory.iterdir() if path.is_file()]

    return sorted(
        files,
        key=lambda path: path.resolve().relative_to(REPO_ROOT).as_posix(),
    )


def build_concat_parser(target_name: str, default_output: Path) -> argparse.ArgumentParser:
    """Build a standard argument parser for concatenation scripts.

    Args:
        target_name: Directory name being concatenated (e.g., "app", "tests").
        default_output: Default output file path.

    Returns:
        Configured argument parser with --output option.
    """
    parser = argparse.ArgumentParser(
        description=(
            f"Concatenate files under {target_name}/ into a single file "
            "with headings using paths relative to the repository root."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=(
            "Output file path (default: %(default)s). The file will be "
            "overwritten if it already exists."
        ),
    )
    return parser


def parse_concat_args(
    target_name: str,
    default_output: Path,
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    """Parse CLI arguments for concatenation scripts.

    Args:
        target_name: Directory name being concatenated (e.g., "app", "tests").
        default_output: Default output file path.
        argv: Command line arguments (defaults to sys.argv).

    Returns:
        Parsed argument namespace with output attribute.
    """
    parser = build_concat_parser(target_name, default_output)
    return parser.parse_args(argv)


def write_concatenated_files(files: list[Path], output_path: Path) -> None:
    """Write files to a concatenated output with headings.

    Each file is written with a heading showing its path relative to the
    repository root. Files are separated by blank lines.

    Args:
        files: List of file paths to concatenate.
        output_path: Destination file path (will be resolved and created).
    """
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Filter out the output file itself
    files = [f for f in files if f.resolve() != output_path]

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
