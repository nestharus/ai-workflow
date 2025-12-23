"""Base linter interface and shared utilities."""

import fnmatch
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@dataclass
class LinterResult:
    """Result of running a linter."""

    success: bool
    message: str | None = None


class InvalidCommandError(TypeError):
    """Raised when a command argument is malformed."""

    def __init__(self) -> None:
        """Initialize with a standard validation message."""
        super().__init__("command must be a non-empty list of strings")


def load_yaml_config(config_path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""
    with config_path.open() as f:
        return yaml.safe_load(f) or {}


def run_checked(command: list[str], *, cwd: Path | None = None) -> None:
    """Invoke a subprocess command with error propagation.

    Args:
        command: Command and arguments to run.
        cwd: Optional working directory for the command.
    """
    if not (
        isinstance(command, list) and command and all(isinstance(part, str) for part in command)
    ):
        raise InvalidCommandError()
    subprocess.check_call(command, cwd=cwd)


def is_path_excluded(path: Path, exclude_paths: set[Path]) -> bool:
    """Check if a path is under any excluded directory or equals one.

    Args:
        path: The file path to check.
        exclude_paths: Set of excluded directory paths (relative to REPO_ROOT).

    Returns:
        True if the path is under an excluded directory or equals one.
    """
    return path in exclude_paths or any(excluded in path.parents for excluded in exclude_paths)


def get_executable(name: str, error_message: str) -> str:
    """Locate an executable on PATH.

    Args:
        name: Name of the executable to find.
        error_message: Error message if executable not found.

    Returns:
        Path to the executable.

    Raises:
        RuntimeError: If executable is not found.
    """
    exe = shutil.which(name)
    if exe is None:
        raise RuntimeError(error_message)
    return exe


class BaseLinter(ABC):
    """Base class for all linters."""

    # Subclasses must define these
    name: str
    supports_file_filtering: bool = True

    @abstractmethod
    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run the linter.

        Args:
            files: Optional list of files to lint. If None, lints entire repo.
                   Only used if supports_file_filtering is True.

        Returns:
            LinterResult indicating success/failure.
        """
        pass


def match_glob_pattern(path: str, pattern: str) -> bool:
    """Match a path against a glob pattern.

    Supports:
    - * matches any characters except /
    - ** matches any characters including / (recursive)
    - !prefix negates the pattern

    Args:
        path: The file path to check (relative to repo root).
        pattern: The glob pattern to match against.

    Returns:
        True if the path matches the pattern.
    """
    # Handle negation patterns
    if pattern.startswith("!"):
        return not match_glob_pattern(path, pattern[1:])

    # Handle recursive glob
    if pattern.startswith("**"):
        # ** at the start matches everything
        rest = pattern[2:]
        if rest.startswith("/"):
            rest = rest[1:]
        if not rest:
            return True
        # Check if path contains the rest of the pattern anywhere
        parts = rest.split("/")
        path_parts = path.split("/")
        # Match remaining parts anywhere in the path
        idx = 0
        for part in parts:
            found = False
            for i in range(idx, len(path_parts)):
                if fnmatch.fnmatch(path_parts[i], part):
                    idx = i + 1
                    found = True
                    break
            if not found:
                return False
        return True

    # Use fnmatch for regular patterns
    return fnmatch.fnmatch(path, pattern)


def filter_paths_by_glob(
    paths: list[str], glob_patterns: list[str], repo_root: Path | None = None
) -> list[str]:
    """Filter paths based on glob patterns following coderabbit path_filters semantics.

    Patterns are processed in order:
    - Patterns without ! prefix are inclusions
    - Patterns with ! prefix are exclusions (processed after inclusions)
    - A path is included if it matches any inclusion pattern AND no exclusion pattern

    Args:
        paths: List of file paths to filter (relative to repo root).
        glob_patterns: List of glob patterns (following coderabbit path_filters format).
        repo_root: Optional repo root for path normalization (unused, kept for API compat).

    Returns:
        Filtered list of paths matching the inclusion/exclusion rules.
    """
    included = []
    excluded_patterns = []

    for pattern in glob_patterns:
        if pattern.startswith("!"):
            excluded_patterns.append(pattern)
        else:
            # Check each path against this inclusion pattern
            for path in paths:
                if match_glob_pattern(path, pattern):
                    # Check if this path is excluded by any exclusion pattern
                    is_excluded = any(match_glob_pattern(path, excl) for excl in excluded_patterns)
                    if not is_excluded and path not in included:
                        included.append(path)

    return included


def is_path_included(path: str, glob_patterns: list[str]) -> bool:
    """Check if a path is included by glob patterns.

    Args:
        path: The file path to check (relative to repo root).
        glob_patterns: List of glob patterns (following coderabbit path_filters format).

    Returns:
        True if the path is included by the patterns.
    """
    has_inclusion = False
    excluded = False

    for pattern in glob_patterns:
        if pattern.startswith("!"):
            if match_glob_pattern(path, pattern[1:]):
                excluded = True
        else:
            has_inclusion = True
            if match_glob_pattern(path, pattern):
                # Path matches an inclusion, check if it's excluded by subsequent patterns
                pass

    if not has_inclusion:
        # No inclusion patterns means all paths are included by default
        # But if there's an exclusion pattern that matches, it's excluded
        for pattern in glob_patterns:
            if pattern.startswith("!") and match_glob_pattern(path, pattern[1:]):
                return False
        return True

    # Check if path matches any inclusion and no exclusion
    if excluded:
        return False

    for pattern in glob_patterns:
        if not pattern.startswith("!") and match_glob_pattern(path, pattern):
            return True

    return False
