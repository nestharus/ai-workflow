"""Lint for markdown file restrictions in the repository.

Enforces that only README.md and AGENTS.md are allowed as markdown files
in root, app/**, docs/**, scripts/**, and tests/** directories.
All other documentation must be in YAML format.

Usage:
    uv run lint markdown-restriction

Configuration:
    See .lint.markdown-restriction.yaml for allowed files and excluded directories.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TypedDict

import yaml

from scripts.dev.utils import REPO_ROOT


class ViolationResult(TypedDict):
    """A single violation for a forbidden markdown file."""

    file_path: str
    error_type: str
    message: str


def load_config(config_path: Path) -> dict[str, Any]:
    """Load the markdown restriction configuration file.

    Args:
        config_path: Path to the configuration YAML file.

    Returns:
        Parsed configuration dictionary.

    Raises:
        FileNotFoundError: If the config file does not exist.
        yaml.YAMLError: If the config file is malformed.
    """
    with config_path.open() as f:
        return yaml.safe_load(f) or {}


def _is_path_excluded(path: Path, exclude_paths: set[Path]) -> bool:
    """Check if a path is under any excluded directory.

    Args:
        path: The file path to check.
        exclude_paths: Set of excluded directory paths (absolute).

    Returns:
        True if the path is under an excluded directory.
    """
    return any(excluded in path.parents for excluded in exclude_paths)


def find_markdown_files(
    restricted_dirs: list[str],
    exclude_dirs: set[str],
) -> list[Path]:
    """Find all markdown files in restricted directories.

    Args:
        restricted_dirs: List of directories to scan for markdown files.
        exclude_dirs: Set of directory paths to exclude from scanning.

    Returns:
        Sorted list of markdown file paths.
    """
    markdown_files: list[Path] = []
    # Convert exclude_dirs to absolute paths
    exclude_paths = {REPO_ROOT / d for d in exclude_dirs}

    for dir_name in restricted_dirs:
        search_path = REPO_ROOT if dir_name == "." else REPO_ROOT / dir_name

        if not search_path.exists() or not search_path.is_dir():
            continue

        for md_file in search_path.rglob("*.md"):
            if not md_file.is_file():
                continue

            # Check if file is under any excluded directory
            if _is_path_excluded(md_file, exclude_paths):
                continue

            markdown_files.append(md_file)

    return sorted(set(markdown_files))


def validate_markdown_files(
    markdown_files: list[Path],
    allowed_files: set[str],
) -> list[ViolationResult]:
    """Validate markdown files against allowed list.

    Args:
        markdown_files: List of markdown file paths to validate.
        allowed_files: Set of allowed relative file paths.

    Returns:
        List of violation results for forbidden files.
    """
    violations: list[ViolationResult] = []

    for md_file in markdown_files:
        relative_path = md_file.relative_to(REPO_ROOT).as_posix()

        if relative_path not in allowed_files:
            violations.append(
                ViolationResult(
                    file_path=relative_path,
                    error_type="forbidden_markdown_file",
                    message=(
                        f"Markdown file '{relative_path}' is not allowed. "
                        "Only README.md and AGENTS.md are permitted in root. "
                        "Convert to YAML format following the schema in "
                        "docs/development/general/general.yaml.schema-guidelines.yml"
                    ),
                )
            )

    return violations


def lint_markdown_restriction(
    config_path: Path | None = None,
) -> tuple[list[ViolationResult], int]:
    """Run the markdown restriction linter.

    Args:
        config_path: Path to configuration file. If None, uses default location.

    Returns:
        Tuple of (violations list, exit code). Exit code is 0 if no violations,
        1 if violations found.
    """
    if config_path is None:
        config_path = REPO_ROOT / ".lint.markdown-restriction.yaml"

    config = load_config(config_path)

    restricted_dirs = config.get("restricted_dirs", ["."])
    allowed_files = set(config.get("allowed_files", ["README.md", "AGENTS.md"]))
    exclude_dirs = set(config.get("exclude_dirs", []))

    markdown_files = find_markdown_files(restricted_dirs, exclude_dirs)
    violations = validate_markdown_files(markdown_files, allowed_files)

    return violations, 1 if violations else 0


def format_violations(violations: list[ViolationResult]) -> str:
    """Format violations for display.

    Args:
        violations: List of violation results.

    Returns:
        Formatted string of violations.
    """
    if not violations:
        return ""

    lines: list[str] = ["Forbidden markdown files found:"]
    for violation in violations:
        lines.append(f"  {violation['file_path']}")
        lines.append(f"    {violation['error_type']}: {violation['message']}")

    return "\n".join(lines)


def main() -> int:
    """Run the markdown restriction linter as a command.

    Returns:
        Exit code (0 for success, 1 for violations found).
    """
    violations, exit_code = lint_markdown_restriction()

    if violations:
        print(format_violations(violations), file=sys.stderr)
        print(
            f"\nFound {len(violations)} forbidden markdown file(s).",
            file=sys.stderr,
        )
    else:
        print("No forbidden markdown files found.")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
