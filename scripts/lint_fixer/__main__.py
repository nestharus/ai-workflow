"""CLI entry point for the lint-fixer orchestrator.

Usage:
    uv run lint-fix [OPTIONS]

Examples:
    uv run lint-fix                           # Lint all files
    uv run lint-fix --changed-only            # Lint changed files only
    uv run lint-fix --files app/main.py       # Lint specific files
    uv run lint-fix --pr NES-123              # Lint files changed in PR
    uv run lint-fix --worktree /path/to/wt    # Run in specific worktree

The orchestrator runs until all errors are fixed or no progress can be made.
It parses agent output to detect fixed vs unfixable issues.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.lint_fixer.orchestrator import orchestrate


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Run linters and fix errors iteratively using the lint-fixer agent.",
        prog="uv run lint-fix",
    )

    # File selection options (mutually exclusive)
    file_group = parser.add_mutually_exclusive_group()
    file_group.add_argument(
        "--changed-only",
        action="store_true",
        help="Only lint files that have been changed (uncommitted or last commit).",
    )
    file_group.add_argument(
        "--commit",
        metavar="SHA",
        help="Only lint files changed in the specified commit.",
    )
    file_group.add_argument(
        "--files",
        nargs="+",
        metavar="FILE",
        help="Only lint the specified files.",
    )
    file_group.add_argument(
        "--pr",
        metavar="TICKET",
        help="Lint files changed in PR for given ticket (e.g., NES-123). "
        "Mutually exclusive with other file selection options.",
    )

    # Working directory
    parser.add_argument(
        "--worktree",
        type=Path,
        metavar="PATH",
        help="Working directory for linting. If --pr is used, this is determined automatically.",
    )

    args = parser.parse_args(argv)

    # Validate: --pr is mutually exclusive with --worktree
    if args.pr and args.worktree:
        parser.error(
            "--pr is mutually exclusive with --worktree. "
            "When using --pr, the worktree is determined automatically."
        )

    return args


def main(argv: list[str] | None = None) -> int:
    """Execute the lint-fixer orchestrator.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    args = _parse_args(argv)
    return orchestrate(args)


if __name__ == "__main__":
    sys.exit(main())
