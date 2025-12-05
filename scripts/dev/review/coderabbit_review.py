"""Wrapper to run CodeRabbit reviews and capture output to .review files.

Usage:
    uv run review.coderabbit -- [--base <branch> | --type <mode> | --base-commit <sha>]
    [extra coderabbit args]

Notes:
- ``--prompt-only`` is always applied by the wrapper.
- If no target flag is provided, the wrapper defaults to ``--base main``.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from scripts.dev.utils import run_command_with_tee, utc_timestamp


class CoderabbitNotFoundError(FileNotFoundError):
    """Raised when the coderabbit executable is unavailable."""

    def __init__(self, message: str | None = None) -> None:
        """Initialize with a default or custom message."""
        super().__init__(message or "coderabbit executable not found on PATH")


def run_coderabbit(target_args: list[str], extra_args: list[str], output_dir: Path) -> Path:
    """Run coderabbit review and tee output to a timestamped file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = utc_timestamp()
    output_path = output_dir / f"{ts}.review.coderabbit"

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

    retcode = run_command_with_tee(cmd, output_path)
    if retcode != 0:
        raise SystemExit(retcode)

    print(f"CodeRabbit output saved to {output_path}")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the coderabbit wrapper."""
    parser = argparse.ArgumentParser(description="Run CodeRabbit review and tee output to .review")
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument("--base", help="Base branch for the review (default: main)")
    target_group.add_argument("--type", help="CodeRabbit review type (e.g., uncommitted)")
    target_group.add_argument(
        "--base-commit", dest="base_commit", help="Base commit SHA for the review"
    )
    parser.add_argument(
        "--output-dir",
        default=".review",
        help="Directory to store review outputs (default: .review)",
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

    output_dir = Path(args.output_dir)
    run_coderabbit(target_args, extra, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
