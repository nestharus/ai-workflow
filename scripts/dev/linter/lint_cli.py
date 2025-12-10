"""Run the project lint suite including formatting, type checks, and security scans."""

import argparse
import subprocess
import sys

import yaml

from scripts.dev.linter.linters import LINTER_MAP, LINTER_NAMES


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run the project lint suite.",
        epilog=f"Available linters: {', '.join(LINTER_NAMES)}",
    )
    parser.add_argument(
        "linters",
        nargs="*",
        choices=LINTER_NAMES,
        metavar="LINTER",
        help=f"Linter(s) to run. Options: {', '.join(LINTER_NAMES)}. "
        "If omitted, all linters run in order.",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        metavar="FILE",
        help="Only lint the specified files. Paths should be relative to repo root.",
    )
    return parser.parse_args()


def main() -> int:
    """Execute linting steps and return a process exit code."""
    args = _parse_args()
    files: list[str] | None = args.files

    # Determine which linters to run (preserve order from LINTER_NAMES)
    if args.linters:
        linters_to_run = [name for name in LINTER_NAMES if name in args.linters]
    else:
        linters_to_run = LINTER_NAMES

    # If files are specified but only non-file-filtering linters are requested,
    # warn the user
    if files is not None:
        file_filtering_linters = {
            name for name, linter in LINTER_MAP.items() if linter.supports_file_filtering
        }
        requested_filterable = [
            linter for linter in linters_to_run if linter in file_filtering_linters
        ]
        if not requested_filterable:
            print(
                "Warning: --files specified but no file-filtering linters requested. "
                f"File filtering is supported by: {', '.join(file_filtering_linters)}",
                file=sys.stderr,
            )

    try:
        for linter_name in linters_to_run:
            print(f"\n{'=' * 60}")
            print(f"Running: {linter_name}")
            print("=" * 60)

            linter = LINTER_MAP.get(linter_name)
            if linter is None:
                print(f"Unknown linter: {linter_name}", file=sys.stderr)
                return 1

            # Run the linter with or without file filtering
            result = linter.run(files) if linter.supports_file_filtering else linter.run()

            if not result.success:
                return 1

    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except OSError as exc:
        print(f"OS error: {exc}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        print(f"YAML configuration error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
