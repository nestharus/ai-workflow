"""CLI client for repository management operations.

This module provides command-line interface for managing repository files,
including getting changed files and creating zip archives.
"""

import argparse
import sys
from pathlib import Path

from scripts.repo_manager import commands


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Optional list of command-line arguments. Defaults to None (uses sys.argv).

    Returns:
        Parsed arguments as Namespace object.
    """
    parser = argparse.ArgumentParser(
        description="Repository management utilities for AI workflow system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # get-changed-files command
    changed_parser = subparsers.add_parser(
        "get-changed-files",
        help="Get list of changed files (staged, unstaged, untracked, tracked)",
    )
    changed_parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Root path for relative file operations (default: current directory)",
    )

    # zip-files command
    zip_parser = subparsers.add_parser(
        "zip-files",
        help="Create zip archive from a list of files",
    )
    zip_parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Root path for resolving relative file paths (default: current directory)",
    )
    zip_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp"),
        help="Output directory for zip file (default: .tmp/)",
    )
    zip_parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="List of files to include in the archive",
    )

    # zip-changes command
    zip_changes_parser = subparsers.add_parser(
        "zip-changes",
        help="Create zip archive of all changed files",
    )
    zip_changes_parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Root path for relative file operations (default: current directory)",
    )
    zip_changes_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp"),
        help="Output directory for zip file (default: .tmp/)",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the repository management CLI.

    Args:
        argv: Optional list of command-line arguments. Defaults to None (uses sys.argv).

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    args = parse_args(argv)

    if args.command == "get-changed-files":
        return commands.get_changed_files_command(args.root)
    if args.command == "zip-files":
        return commands.zip_files_command(args.root, args.output_dir, args.files)
    if args.command == "zip-changes":
        return commands.zip_changes_command(args.root, args.output_dir)

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
