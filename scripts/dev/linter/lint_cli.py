"""Run the project lint suite including formatting, type checks, and security scans."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.dev.linter.base import BaseLinter, LinterResult, execute_phase, schedule_linters
from scripts.dev.linter.linters import LINTER_MAP, LINTER_NAMES


def _filter_existing_files(files: list[str]) -> list[str]:
    """Filter out files that don't exist on disk.

    Args:
        files: List of file paths relative to repo root.

    Returns:
        List of file paths that actually exist.
    """
    return [f for f in files if Path(f).exists()]


def _get_changed_files(commit: str | None = None) -> list[str]:
    """Get list of changed files from git.

    Args:
        commit: Optional commit SHA to get files from. If None, returns uncommitted
            changes (staged + unstaged), or files from last commit if no uncommitted.

    Returns:
        List of file paths relative to repo root, excluding deleted files.
    """
    try:
        if commit:
            # Get files changed in the specified commit (excluding deletions)
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=ACMRTUX", f"{commit}~1..{commit}"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if result:
                return sorted(set(result.splitlines()))
            return []

        # Get uncommitted changes (staged + unstaged, excluding deletions)
        staged = subprocess.run(
            ["git", "diff", "--name-only", "--cached", "--diff-filter=ACMRTUX"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        unstaged = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--diff-filter=ACMRTUX"],
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

        # No uncommitted changes - get files from last commit (excluding deletions)
        last_commit = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMRTUX", "HEAD~1..HEAD"],
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
    parser.add_argument(
        "--output-format",
        choices=["text", "yaml"],
        default="text",
        help="Output format: text (default) for human-readable, yaml for structured errors.",
    )
    return parser.parse_args()


def main() -> int:
    """Execute linting steps and return a process exit code."""
    args = _parse_args()
    yaml_output = args.output_format == "yaml"

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
        files = _filter_existing_files(_get_changed_files())
        if not files:
            if not yaml_output:
                print("No changed files to lint.")
            return 0
        if not yaml_output:
            print(f"Linting {len(files)} changed file(s):")
            for f in files:
                print(f"  {f}")
    elif args.commit:
        files = _filter_existing_files(_get_changed_files(args.commit))
        if not files:
            if not yaml_output:
                print(f"No files changed in commit {args.commit}.")
            return 0
        if not yaml_output:
            print(f"Linting {len(files)} file(s) from commit {args.commit}:")
            for f in files:
                print(f"  {f}")
    elif args.files:
        files = _filter_existing_files(args.files)
        if not files:
            if not yaml_output:
                print("No specified files exist.")
            return 0

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

    # Convert linter names to instances
    linter_instances = []
    for linter_name in linters_to_run:
        linter = LINTER_MAP.get(linter_name)
        if linter is None:
            print(f"Unknown linter: {linter_name}", file=sys.stderr)
            return 1
        linter_instances.append(linter)

    # Schedule linters into phases for parallel execution
    phases = schedule_linters(linter_instances, files)

    if not phases:
        if not yaml_output:
            print("No linters to run (all have empty filesets).")
        return 0

    failed_in_readonly_phase = False
    all_results: dict[str, LinterResult] = {}

    try:
        for phase_idx, phase in enumerate(phases):
            # Determine if this is a mutating phase (single linter, before read-only phase)
            is_mutating_phase = len(phase) == 1 and phase_idx < len(phases) - 1

            # Run tests for linters in this phase
            for linter_name in phase:
                linter = LINTER_MAP[linter_name]
                test_method = getattr(linter, "test", None)
                if test_method is not None and type(linter).test is not BaseLinter.test:
                    if not yaml_output:
                        print(f"\n{'=' * 60}")
                        print(f"Testing: {linter_name}")
                        print("=" * 60)

                    test_result = linter.test()
                    if not test_result.success:
                        return 1

            # Execute the phase
            if not yaml_output:
                print(f"\n{'=' * 60}")
                if len(phase) == 1:
                    print(f"Running: {phase[0]}")
                else:
                    print(f"Running {len(phase)} linters in parallel: {', '.join(phase)}")
                print("=" * 60)

            results = execute_phase(phase, files)
            all_results.update(results)

            # Print errors in text mode
            if not yaml_output:
                for result in results.values():
                    for error in result.errors:
                        loc = f"{error.file}:{error.line}:{error.column}"
                        print(f"{loc}: {error.code} {error.message}")

            # Check results and handle failures
            failed_linters = [name for name, result in results.items() if not result.success]

            if failed_linters:
                if is_mutating_phase:
                    # Mutating linter failed - abort immediately
                    if not yaml_output:
                        print(
                            f"\nMutating linter {failed_linters[0]} failed. Aborting.",
                            file=sys.stderr,
                        )
                    break
                else:
                    # Read-only linter(s) failed - report but continue
                    if not yaml_output:
                        print(f"\nFailed linters: {', '.join(failed_linters)}", file=sys.stderr)
                    failed_in_readonly_phase = True

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

    # Output YAML format if requested
    if yaml_output:
        _output_yaml_results(all_results)

    # Check if any linter failed
    any_failure = any(not r.success for r in all_results.values())
    return 1 if (failed_in_readonly_phase or any_failure) else 0


def _output_yaml_results(results: dict[str, LinterResult]) -> None:
    """Output linter results in YAML format.

    Args:
        results: Dictionary mapping linter names to their results.
    """
    # Collect all errors from all linters
    all_errors: list[dict[str, object]] = []
    for linter_name, result in results.items():
        for error in result.errors:
            all_errors.append(
                {
                    "linter": linter_name,
                    "file": error.file,
                    "line": error.line,
                    "column": error.column,
                    "code": error.code,
                    "message": error.message,
                    "fix_available": error.fix_available,
                    "fix_message": error.fix_message,
                }
            )

    if not all_errors:
        print("errors: []")
        return

    # Output YAML manually for better control over formatting
    print("errors:")
    for err in all_errors:
        print(f"  - linter: {err['linter']}")
        print(f"    file: {err['file']}")
        print(f"    line: {err['line']}")
        print(f"    column: {err['column']}")
        print(f"    code: {err['code']}")
        # Handle message with potential special characters
        msg = str(err["message"])
        if "\n" in msg or ":" in msg or '"' in msg:
            print("    message: |")
            for line in msg.splitlines():
                print(f"      {line}")
        else:
            print(f"    message: {msg}")
        print(f"    fix_available: {str(err['fix_available']).lower()}")
        if err["fix_message"]:
            print(f"    fix_message: {err['fix_message']}")


if __name__ == "__main__":
    raise SystemExit(main())
