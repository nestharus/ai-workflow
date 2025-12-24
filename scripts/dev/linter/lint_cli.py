"""Run the project lint suite including formatting, type checks, and security scans."""

import argparse
import re
import subprocess
import sys

import yaml

from scripts.dev.linter.linters import LINTER_MAP, LINTER_NAMES


def _get_changed_files(commit: str | None = None) -> list[str]:
    """Get list of changed files from git.

    Args:
        commit: Optional commit SHA to get files from. If None, returns uncommitted
            changes (staged + unstaged), or files from last commit if no uncommitted.

    Returns:
        List of file paths relative to repo root.
    """
    try:
        if commit:
            # Get files changed in the specified commit
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{commit}~1..{commit}"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if result:
                return sorted(set(result.splitlines()))
            return []

        # Get uncommitted changes (staged + unstaged)
        staged = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        unstaged = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        # Combine and deduplicate
        uncommitted_files = set()
        if staged:
            uncommitted_files.update(staged.splitlines())
        if unstaged:
            uncommitted_files.update(unstaged.splitlines())

        if uncommitted_files:
            return sorted(uncommitted_files)

        # No uncommitted changes - get files from last commit
        last_commit = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1..HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        if last_commit:
            return sorted(set(last_commit.splitlines()))

        return []
    except subprocess.CalledProcessError:
        # Git command failed (not a repo, no commits, etc.)
        return []


def _expand_linter_spec(spec: str) -> list[str] | None:
    """Expand a linter specification into a list of linter names.

    Supports range operators:
    - `>linter`: All linters after the specified linter
    - `>=linter`: The specified linter and all linters after it
    - `<linter`: All linters before the specified linter
    - `<=linter`: All linters before the specified linter and itself
    - `linter`: Just the specified linter

    Args:
        spec: A linter specification (e.g., "ruff", ">=mypy", "<yamllint")

    Returns:
        List of linter names, or None if the spec is invalid.
    """
    # Check for range operators
    match = re.match(r"^(>=|<=|>|<)?(.+)$", spec)
    if not match:
        return None

    operator, linter_name = match.groups()
    operator = operator or ""  # Default to empty string if no operator

    if linter_name not in LINTER_NAMES:
        return None

    linter_index = LINTER_NAMES.index(linter_name)

    if operator == ">=":
        return LINTER_NAMES[linter_index:]
    elif operator == ">":
        return LINTER_NAMES[linter_index + 1 :]
    elif operator == "<=":
        return LINTER_NAMES[: linter_index + 1]
    elif operator == "<":
        return LINTER_NAMES[:linter_index]
    else:
        # No operator - just the single linter
        return [linter_name]


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run the project lint suite.",
        epilog=f"Available linters: {', '.join(LINTER_NAMES)}. "
        "Supports range operators: >=linter, >linter, <=linter, <linter",
    )
    parser.add_argument(
        "linters",
        nargs="*",
        metavar="LINTER",
        help=f"Linter(s) to run. Options: {', '.join(LINTER_NAMES)}. "
        "Supports range operators: >=ruff (ruff and after), >ruff (after ruff), "
        "<=mypy (up to and including mypy), <mypy (before mypy). "
        "If omitted, all linters run in order.",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        metavar="FILE",
        help="Only lint the specified files. Paths should be relative to repo root.",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Only lint files that have been changed (uncommitted or last commit).",
    )
    parser.add_argument(
        "--commit",
        metavar="SHA",
        help="Only lint files changed in the specified commit.",
    )
    return parser.parse_args()


def main() -> int:
    """Execute linting steps and return a process exit code."""
    args = _parse_args()

    # Handle mutual exclusivity for file options
    file_options = [args.changed_only, args.files is not None, args.commit is not None]
    if sum(file_options) > 1:
        print(
            "Error: --changed-only, --files, and --commit are mutually exclusive.",
            file=sys.stderr,
        )
        return 1

    # Determine files to lint
    files: list[str] | None = None
    if args.changed_only:
        files = _get_changed_files()
        if not files:
            print("No changed files to lint.")
            return 0
        print(f"Linting {len(files)} changed file(s):")
        for f in files:
            print(f"  {f}")
    elif args.commit:
        files = _get_changed_files(args.commit)
        if not files:
            print(f"No files changed in commit {args.commit}.")
            return 0
        print(f"Linting {len(files)} file(s) from commit {args.commit}:")
        for f in files:
            print(f"  {f}")
    elif args.files:
        files = args.files

    # Determine which linters to run
    if args.linters:
        # Expand linter specs (may include range operators)
        linters_to_run: list[str] = []
        seen: set[str] = set()
        for spec in args.linters:
            expanded = _expand_linter_spec(spec)
            if expanded is None:
                print(f"Invalid linter specification: {spec}", file=sys.stderr)
                print(f"Available linters: {', '.join(LINTER_NAMES)}", file=sys.stderr)
                return 1
            for name in expanded:
                if name not in seen:
                    linters_to_run.append(name)
                    seen.add(name)
    else:
        linters_to_run = list(LINTER_NAMES)

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
