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

    path_parts = path.split("/")
    pattern_parts = pattern.split("/")

    i = 0  # Index in path_parts
    j = 0  # Index in pattern_parts

    while j < len(pattern_parts):
        pattern_part = pattern_parts[j]

        if pattern_part == "**":
            # ** matches zero or more directories
            j += 1
            if j >= len(pattern_parts):
                # ** at end matches rest of path
                return True
            # Try to match remaining pattern at current or subsequent positions
            next_pattern = pattern_parts[j]
            while i < len(path_parts):
                if fnmatch.fnmatch(path_parts[i], next_pattern) and match_glob_pattern(
                    "/".join(path_parts[i:]), "/".join(pattern_parts[j:])
                ):
                    return True
                i += 1
            return False

        if i >= len(path_parts):
            return False

        if not fnmatch.fnmatch(path_parts[i], pattern_part):
            return False

        i += 1
        j += 1

    # All pattern parts consumed - path matches if we also consumed all parts
    return i == len(path_parts)


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
    excluded = False
    included = False

    for pattern in glob_patterns:
        if pattern.startswith("!"):
            if match_glob_pattern(path, pattern[1:]):
                excluded = True
        else:
            if match_glob_pattern(path, pattern):
                included = True

    # Path is included only if it matches at least one inclusion pattern
    # and is not excluded by any exclusion pattern
    return included and not excluded


def _validate_list_config(
    config: dict[str, Any], key: str, linter_name: str
) -> tuple[list[str], LinterResult | None]:
    """Validate a list config value from the config dict.

    Args:
        config: The parsed config dictionary.
        key: The config key to validate (e.g., "included_paths", "excluded_paths").
        linter_name: Name of the linter (for error messages).

    Returns:
        A tuple of (value_or_empty_list, error_result). If error_result is not None,
        the caller should return it immediately. Otherwise, use the returned list.
    """
    value = config.get(key, [])
    if value is not None and not isinstance(value, list):
        type_name = type(value).__name__
        print(f"Invalid {key} in {linter_name} config: expected list, got {type_name}")
        return [], LinterResult(success=False, message=f"Invalid {key} config")
    return value if value is not None else [], None


def filter_files_with_config(
    py_files: list[str],
    config_path: Path,
    linter_name: str,
) -> tuple[list[str], LinterResult | None]:
    """Load config and filter Python files by included_paths.

    This is a shared helper for linters that need to filter files based on
    included_paths from their config YAML. Files must match at least one
    inclusion pattern to pass the filter.

    Empty-match behavior: When no files match the included_paths patterns,
    the function prints a diagnostic message and returns ([], None). This is treated
    as a valid empty result (not a failure), and callers should proceed accordingly
    rather than treating it as an exception. An empty list with None error_result
    indicates "no files matched the filter" and the caller may skip linting.

    Args:
        py_files: List of Python files to filter.
        config_path: Path to the linter's YAML config file.
        linter_name: Name of the linter (for error messages).

    Returns:
        A tuple of (filtered_files, error_result). If error_result is not None,
        the caller should return it immediately (indicates a real error like
        missing config or parse failure). If error_result is None, use filtered_files
        (which may be empty if no files matched the patterns - this is valid).
    """
    try:
        config = load_yaml_config(config_path)
    except FileNotFoundError:
        print(f"{linter_name.capitalize()} config file not found: {config_path}")
        return [], LinterResult(success=False, message="Config file not found")
    except PermissionError as e:
        print(f"Permission denied reading {linter_name} config {config_path}: {e}")
        return [], LinterResult(success=False, message=f"Config permission error: {e}")
    except yaml.YAMLError as e:
        print(f"Failed to parse {linter_name} config {config_path}: {e}")
        return [], LinterResult(success=False, message=f"Config parse error: {e}")

    included_paths, error = _validate_list_config(config, "included_paths", linter_name)
    if error is not None:
        return [], error

    if included_paths:
        filtered = [f for f in py_files if is_path_included(f, included_paths)]
        if not filtered:
            print(f"No Python files match {linter_name} included_paths filter")
            return [], None
        return filtered, None

    return py_files, None
