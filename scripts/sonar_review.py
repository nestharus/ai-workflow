"""Wrapper to run sonar_scan and capture output to .review files.

Usage:
    uv run sonar-review -- [sonar_scan args]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def _utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


class StdoutCaptureError(RuntimeError):
    """Raised when sonar_scan output cannot be read."""

    def __init__(self) -> None:
        """Initialize with a fixed capture failure message."""
        super().__init__("Failed to capture stdout from sonar_scan process")


class SonarScriptNotFoundError(FileNotFoundError):
    """Raised when the sonar_scan script is missing."""

    def __init__(self, script_path: Path) -> None:
        """Record the missing script path in the exception."""
        super().__init__(f"sonar_scan script not found at {script_path}")


def run_sonar(extra_args: list[str], output_dir: Path) -> Path:
    """Run sonar_scan wrapper and store combined output."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = _utc_timestamp()
    output_path = output_dir / f"{ts}.review.sonar"

    script_path = (Path(__file__).resolve().parent / "sonar_scan.sh").resolve()
    if not script_path.is_file():
        raise SonarScriptNotFoundError(script_path)

    cmd = [str(script_path), *extra_args]

    with output_path.open("w", encoding="utf-8") as outfile:
        process = subprocess.Popen(  # noqa: S603
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
        retcode = process.wait()

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
