"""Wrapper to run CodeRabbit reviews and output to stdout.

Usage:
    uv run review.coderabbit [--base <branch> | --type <mode> | --base-commit <sha>]

    # Capture output to a file:
    uv run review.coderabbit --base main > .tmp/pr-review/review.coderabbit

Notes:
- ``--prompt-only`` is always applied by the wrapper.
- If no target flag is provided, the wrapper defaults to ``--base main``.
- Output goes to stdout for piping/redirection by the caller.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


class CoderabbitNotFoundError(FileNotFoundError):
    """Raised when the coderabbit executable is unavailable."""

    def __init__(self, message: str | None = None) -> None:
        """Initialize with a default or custom message."""
        super().__init__(message or "coderabbit executable not found on PATH")


def run_coderabbit(target_args: list[str], extra_args: list[str]) -> int:
    """Run coderabbit review and stream output to stdout.

    Args:
        target_args: Target specification args (--base, --type, or --base-commit).
        extra_args: Additional args to pass to coderabbit.

    Returns:
        Exit code from coderabbit process.

    Raises:
        CoderabbitNotFoundError: If coderabbit executable is not found.
    """
    coderabbit_exe = shutil.which("coderabbit")
    if coderabbit_exe is None:
        raise CoderabbitNotFoundError()

    cmd = [
        coderabbit_exe,
        "review",
        "--prompt-only",
        *target_args,
        *extra_args,
    ]

    # Stream output directly to stdout (caller can redirect to file)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
    )

    stdout = process.stdout
    if stdout is None:
        process.kill()
        print("ERROR: Failed to capture stdout from coderabbit", file=sys.stderr)
        return 1

    # Stream stdout line by line
    for line in stdout:
        sys.stdout.write(line)
        sys.stdout.flush()

    return process.wait()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the coderabbit wrapper."""
    parser = argparse.ArgumentParser(
        description="Run CodeRabbit review and output to stdout"
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("--base", help="Base branch for the review (default: main)")
    target_group.add_argument("--type", help="CodeRabbit review type (e.g., uncommitted)")
    target_group.add_argument(
        "--base-commit", dest="base_commit", help="Base commit SHA for the review"
    )
    parser.add_argument(
        "extra_args", nargs=argparse.REMAINDER, help="Additional args for coderabbit"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for invoking coderabbit wrapper."""
    args = parse_args(argv)
    if args.base:
        target_args = ["--base", args.base]
    elif args.type:
        target_args = ["--type", args.type]
    elif args.base_commit:
        target_args = ["--base-commit", args.base_commit]
    else:
        target_args = ["--base", "main"]

    extra = args.extra_args
    if extra and extra[0] == "--":
        extra = extra[1:]

    return run_coderabbit(target_args, extra)


if __name__ == "__main__":
    raise SystemExit(main())
