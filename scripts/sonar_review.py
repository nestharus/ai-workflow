"""Wrapper to run sonar_scan and capture output to .review files.

Usage:
    uv run sonar-review -- [sonar_scan args]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.utils import run_command_with_tee, utc_timestamp


class SonarScriptNotFoundError(FileNotFoundError):
    """Raised when the sonar_scan script is missing."""

    def __init__(self, script_path: Path) -> None:
        """Record the missing script path in the exception."""
        super().__init__(f"sonar_scan script not found at {script_path}")


def run_sonar(extra_args: list[str], output_dir: Path) -> Path:
    """Run sonar_scan wrapper and store combined output."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = utc_timestamp()
    output_path = output_dir / f"{ts}.review.sonar"

    script_path = (Path(__file__).resolve().parent / "sonar_scan.sh").resolve()
    if not script_path.is_file():
        raise SonarScriptNotFoundError(script_path)

    cmd = [str(script_path), *extra_args]

    retcode = run_command_with_tee(cmd, output_path)
    if retcode != 0:
        raise SystemExit(retcode)

    print(f"Sonar output saved to {output_path}")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the sonar review wrapper."""
    parser = argparse.ArgumentParser(description="Run sonar_scan and tee output to .review")
    parser.add_argument(
        "--output-dir",
        default=".review",
        help="Directory to store review outputs (default: .review)",
    )
    parser.add_argument(
        "extra_args", nargs=argparse.REMAINDER, help="Arguments passed to sonar_scan.sh"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for running sonar review collection."""
    args = parse_args(argv)
    extra = args.extra_args
    if extra and extra[0] == "--":
        extra = extra[1:]

    output_dir = Path(args.output_dir)
    run_sonar(extra, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
