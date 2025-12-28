"""Run tests for specific changed files across test tiers.

This module provides functionality to:
1. Map source files to their appropriate test tiers
2. Find relevant test files for each source file
3. Run pytest on those test files
4. Return structured results including pass/fail status and output

Usage:
    uv run test-files app/core/factory.py scripts/dev/linter/lint_cli.py

The script automatically:
- Determines which test tier applies to each file (unit, component, integration, scripts)
- Finds corresponding test files based on file path patterns
- Runs pytest for all matching tests
- Reports results grouped by tier and file

Dependencies:
    - uv: Required for running pytest. Install via https://docs.astral.sh/uv/
      Override the test command via TEST_RUNNER_CMD environment variable
      (e.g., TEST_RUNNER_CMD="python -m pytest" for direct pytest usage).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)


def _find_repo_root(start_path: Path | None = None) -> Path:
    """Find the repository root by walking upward from the given path.

    Searches for repository markers (pyproject.toml or .git) in parent directories.
    This is more robust than hardcoding the number of parent directories to traverse.

    Args:
        start_path: Starting path to search from. Defaults to the directory
                    containing this file.

    Returns:
        Path to the repository root directory.

    Raises:
        FileNotFoundError: If no repository marker is found after traversing
                           to the filesystem root.
    """
    if start_path is None:
        start_path = Path(__file__).resolve().parent

    markers = ("pyproject.toml", ".git")
    current = start_path

    while current != current.parent:  # Stop at filesystem root
        for marker in markers:
            if (current / marker).exists():
                return current
        current = current.parent

    # Check root directory as well
    for marker in markers:
        if (current / marker).exists():
            return current

    # Fallback: return the original parent chain (4 levels up from this file)
    # This maintains backward compatibility if markers are somehow missing
    fallback = Path(__file__).resolve().parent.parent.parent.parent
    logger.warning(
        "No repository marker (pyproject.toml or .git) found. Falling back to: %s",
        fallback,
    )
    return fallback


REPO_ROOT = _find_repo_root()

# Regex patterns for pytest output parsing (exported for testing)
# Matches "FAILED path::testname" or "FAILED path::testname - reason"
FAILED_LINE_PATTERN = re.compile(r"^FAILED\s+(\S+?)(?:\s+-|$)")
# Matches failure section headers like "_____ test_foo _____"
FAILURE_HEADER_PATTERN = re.compile(r"^_+\s+(\S+)\s+_+$")


def normalize_path(file_path: str) -> str:
    """Normalize a file path to POSIX form for consistent pattern matching.

    Converts Windows backslashes to forward slashes to ensure patterns
    work correctly on all platforms. Also converts absolute paths to
    repo-relative paths for consistent tier matching.
    """
    # Replace backslashes explicitly to handle cross-platform scenarios
    # Path.as_posix() only converts separators for the current OS
    normalized = file_path.replace("\\", "/")

    # Convert absolute paths to repo-relative
    try:
        path_obj = Path(normalized)
        if path_obj.is_absolute():
            resolved = path_obj.resolve()
            relative = resolved.relative_to(REPO_ROOT)
            return str(relative).replace("\\", "/")
    except ValueError:
        # Path is not relative to REPO_ROOT - fall back to normalized form
        logger.debug("Path '%s' is not relative to REPO_ROOT, using normalized form", normalized)
    except OSError as e:
        # Path resolution failed (e.g., invalid path)
        logger.warning("Failed to resolve path '%s': %s. Using normalized form.", normalized, e)

    return normalized


@dataclass
class TestResult:
    """Result of running tests for a file."""

    file: str
    tier: str
    test_files: list[str]
    passed: bool
    exit_code: int
    output: str
    failed_tests: list[str] = field(default_factory=list)
    no_tests: bool = False


@dataclass
class TierConfig:
    """Configuration for a test tier."""

    name: str
    test_path: str
    source_patterns: list[str]


def _validate_tier_config(tier_name: str, tier_data: dict[str, object]) -> None:
    """Validate tier configuration data and raise ValueError if invalid.

    Args:
        tier_name: Name of the tier being validated.
        tier_data: Raw tier data from pyproject.toml.

    Raises:
        ValueError: If required fields are missing, empty, or have incorrect types.
    """
    # Check test_path exists and is a non-empty string
    if "test_path" not in tier_data:
        raise ValueError(f"Tier '{tier_name}': missing required field 'test_path'")

    test_path = tier_data["test_path"]
    if not isinstance(test_path, str):
        raise TypeError(
            f"Tier '{tier_name}': 'test_path' must be a string, got {type(test_path).__name__}"
        )
    if not test_path.strip():
        raise ValueError(f"Tier '{tier_name}': 'test_path' must be a non-empty string")

    # Check source_paths exists and is a non-empty list of strings
    if "source_paths" not in tier_data:
        raise ValueError(f"Tier '{tier_name}': missing required field 'source_paths'")

    source_paths = tier_data["source_paths"]
    if not isinstance(source_paths, list):
        raise TypeError(
            f"Tier '{tier_name}': 'source_paths' must be a list, got {type(source_paths).__name__}"
        )
    if not source_paths:
        raise ValueError(f"Tier '{tier_name}': 'source_paths' must be a non-empty list")

    for i, pattern in enumerate(source_paths):
        if not isinstance(pattern, str):
            raise TypeError(
                f"Tier '{tier_name}': 'source_paths[{i}]' must be a string, "
                f"got {type(pattern).__name__}"
            )


def load_tier_configs() -> list[TierConfig]:
    """Load tier configurations from pyproject.toml."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError("pyproject.toml not found")

    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    test_coverage = data.get("tool", {}).get("test_coverage", {})
    tiers_table = test_coverage.get("tiers", {})

    configs: list[TierConfig] = []
    for tier_name, tier_data in tiers_table.items():
        _validate_tier_config(tier_name, tier_data)
        configs.append(
            TierConfig(
                name=tier_name,
                test_path=tier_data["test_path"],
                source_patterns=tier_data["source_paths"],
            )
        )

    return configs


def _glob_pattern_to_regex(pattern: str) -> re.Pattern[str]:
    r"""Convert a glob pattern with ** support to a regex pattern.

    This is a fallback for Python < 3.13 which doesn't have PurePosixPath.full_match.

    The conversion handles:
    - ** matches any characters including / (recursive directory matching)
    - * matches any characters except /
    - ? matches any single character except /
    - [...] character classes with proper backslash escape handling
    - Unterminated character classes are treated as literal [

    Known limitations/edge-cases:
    - Escaped brackets outside character classes (e.g., \[) are not supported
    - Platform path separators: assumes POSIX forward slashes; Windows backslashes
      must be normalized before matching
    - Leading/trailing slashes: patterns should not start or end with / unless
      matching absolute paths or trailing-slash directories
    - Nested character classes are not supported (e.g., [[a-z]])
    - Backslash at end of pattern may produce unexpected regex

    Note: This fallback is only used on Python < 3.13. On Python 3.13+,
    PurePosixPath.full_match provides standard, well-tested glob behavior.
    """
    result_parts: list[str] = []
    i = 0
    n = len(pattern)

    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # ** - match anything including /
                result_parts.append(".*")
                i += 2
                # Skip trailing / after ** if present (e.g., **/ -> .*/)
                if i < n and pattern[i] == "/":
                    result_parts.append("/")
                    i += 1
            else:
                # Single * - match anything except /
                result_parts.append("[^/]*")
                i += 1
        elif c == "?":
            # ? matches any single character except /
            result_parts.append("[^/]")
            i += 1
        elif c == "[":
            # Character class - find the closing ] and process inner content
            j = i + 1
            negated = False
            if j < n and pattern[j] == "!":
                negated = True
                j += 1
            # Handle literal ] at the start of the class (e.g., []abc] or [!]abc])
            if j < n and pattern[j] == "]":
                j += 1
            # Find the closing ] while tracking backslash escapes
            while j < n and pattern[j] != "]":
                if pattern[j] == "\\" and j + 1 < n:
                    # Skip escaped character
                    j += 2
                else:
                    j += 1

            # Check for unterminated character class
            if j >= n:
                # No closing ] found - treat [ as a literal character
                result_parts.append("\\[")
                i += 1
                continue

            # Extract inner content (after [ and optional !)
            inner_start = i + 1
            if negated:
                inner_start += 1
            raw_inner = pattern[inner_start:j]

            # Process backslash escapes inside the character class
            # In glob patterns, backslash escapes the next character to make it literal
            processed_inner: list[str] = []
            k = 0
            while k < len(raw_inner):
                if raw_inner[k] == "\\" and k + 1 < len(raw_inner):
                    # Escaped character - include it literally
                    next_char = raw_inner[k + 1]
                    # Some characters need escaping in regex character classes
                    if next_char in "\\]^-":
                        processed_inner.append("\\" + next_char)
                    else:
                        processed_inner.append(next_char)
                    k += 2
                else:
                    processed_inner.append(raw_inner[k])
                    k += 1

            inner_content = "".join(processed_inner)

            # Build the character class: convert ! to ^ for negation
            if negated:
                result_parts.append("[^" + inner_content + "]")
            else:
                result_parts.append("[" + inner_content + "]")
            i = j + 1
        elif c in ".^$+{}|()":
            # Escape regex special characters
            result_parts.append("\\" + c)
            i += 1
        else:
            result_parts.append(c)
            i += 1

    regex_pattern = "".join(result_parts)
    return re.compile(f"^{regex_pattern}$")


# Check if PurePosixPath.full_match is available (Python 3.13+)
_HAS_FULL_MATCH = hasattr(PurePosixPath, "full_match")

# Track whether we've already warned about fallback regex matching
_FALLBACK_WARNING_LOGGED = False


def match_pattern(path: str, pattern: str) -> bool:
    """Match a path against a glob-like pattern.

    Args:
        path: File path in POSIX form (forward slashes), repo-root relative.
        pattern: Glob pattern to match against. Must NOT start with '!' (negation).
                 Callers must strip the '!' prefix before calling this function
                 and handle the negation logic themselves (see file_matches_tier).

    Supports:
    - * matches any characters except /
    - ** matches any characters including /

    Note: Both path and pattern are expected to use forward slashes (POSIX form).
    Uses pathlib.PurePosixPath.full_match on Python 3.13+ for standard, well-tested
    glob behavior. Falls back to a regex-based implementation on older Python versions.

    Raises:
        ValueError: If pattern starts with '!' (negation patterns are not allowed).
                    Callers must strip the '!' and handle negation logic externally.
                    See file_matches_tier() for proper negation handling.
    """
    if pattern.startswith("!"):
        raise ValueError(
            f"Negation patterns are not allowed in match_pattern. "
            f"Strip the '!' prefix and handle negation in the caller. Got: {pattern!r}"
        )

    if _HAS_FULL_MATCH:
        # Use PurePosixPath.full_match for standard glob behavior with ** support
        # full_match() was added in Python 3.13 and properly handles ** wildcards
        return PurePosixPath(path).full_match(pattern)
    else:
        # Fallback for Python < 3.13: use regex-based matching
        global _FALLBACK_WARNING_LOGGED
        if not _FALLBACK_WARNING_LOGGED:
            logger.warning(
                "Using fallback regex-based glob matching (Python < 3.13). "
                "Some edge cases may not match pathlib.PurePosixPath.full_match behavior. "
                "See _glob_pattern_to_regex docstring for known limitations."
            )
            _FALLBACK_WARNING_LOGGED = True
        regex = _glob_pattern_to_regex(pattern)
        return regex.match(path) is not None


def file_matches_tier(file_path: str, tier: TierConfig) -> bool:
    """Check if a file matches a tier's source patterns.

    Args:
        file_path: File path in POSIX form (forward slashes), repo-root relative.
        tier: Tier configuration to match against.
    """
    included = False

    for pattern in tier.source_patterns:
        if pattern.startswith("!"):
            if match_pattern(file_path, pattern[1:]):
                return False
        else:
            if match_pattern(file_path, pattern):
                included = True

    return included


def get_tier_for_file(file_path: str, tiers: list[TierConfig]) -> TierConfig | None:
    """Get the test tier that applies to a source file.

    Args:
        file_path: File path in POSIX form (forward slashes), repo-root relative.
        tiers: List of tier configurations to check.
    """
    for tier in tiers:
        if file_matches_tier(file_path, tier):
            return tier
    return None


def find_test_files(source_file: str, tier: TierConfig) -> list[str]:
    """Find test files that correspond to a source file.

    Args:
        source_file: Source file path in POSIX form (forward slashes), repo-root relative.
        tier: Tier configuration for test path lookup.

    Uses naming conventions:
    - app/core/factory.py -> tests/unit/app/core/test_factory.py
    - scripts/dev/linter/lint_cli.py -> scripts/tests/dev/linter/test_lint_cli.py
    """
    test_files: list[str] = []
    test_base = Path(REPO_ROOT / tier.test_path)

    if not test_base.exists():
        return test_files

    source_path = Path(source_file)

    # Build potential test file paths based on conventions
    if source_file.startswith("app/"):
        # app/core/factory.py -> tests/unit/app/core/test_factory.py
        rel_path = source_path.relative_to("app")
        test_path = test_base / "app" / rel_path.parent / f"test_{rel_path.name}"
        if test_path.exists():
            test_files.append(str(test_path.relative_to(REPO_ROOT)))

        # Also check without app prefix: tests/unit/core/test_factory.py
        test_path_alt = test_base / rel_path.parent / f"test_{rel_path.name}"
        if test_path_alt.exists():
            test_files.append(str(test_path_alt.relative_to(REPO_ROOT)))

    elif source_file.startswith("scripts/") and not source_file.startswith("scripts/tests/"):
        # scripts/dev/linter/lint_cli.py -> scripts/tests/dev/linter/test_lint_cli.py
        rel_path = source_path.relative_to("scripts")
        test_path = test_base / rel_path.parent / f"test_{rel_path.name}"
        if test_path.exists():
            test_files.append(str(test_path.relative_to(REPO_ROOT)))

    # If no direct mapping found, search for tests that might test this module
    if not test_files:
        module_name = source_path.stem
        fallback_matches: list[str] = []
        for test_file in test_base.rglob(f"test_*{module_name}*.py"):
            fallback_matches.append(str(test_file.relative_to(REPO_ROOT)))
        if fallback_matches:
            logger.debug(
                "Fallback glob pattern matched tests for module '%s': %s",
                module_name,
                fallback_matches,
            )
        else:
            logger.debug("Fallback glob pattern found no tests for module '%s'", module_name)
        test_files.extend(fallback_matches)

    return sorted(set(test_files))


def _extract_short_test_name(test_id: str) -> str:
    """Extract the short test name from a full test identifier.

    Handles various pytest identifier formats:
    - path/to/test.py::test_name -> test_name
    - path/to/test.py::TestClass::test_method -> TestClass::test_method
    - path/to/test.py::test_name[param1-param2] -> test_name[param1-param2]
    - path/to/test.py::TestClass::test_method[param] -> TestClass::test_method[param]

    This matches what pytest displays in failure headers:
    - For class methods: "_____ TestClass::test_method _____"
    - For functions: "_____ test_name _____"

    Args:
        test_id: Full test identifier from pytest output

    Returns:
        The short test name (everything after the file path)
    """
    # Split by :: to separate file path from test identifier
    parts = test_id.split("::")
    if len(parts) > 1:
        # Return everything after the file path (preserves class::method format)
        # parts[0] is the file path, remaining parts form the test identifier
        return "::".join(parts[1:])
    # No :: found, return as-is (already a short name)
    return test_id


def run_tests(test_files: list[str], timeout: int = 300) -> tuple[bool, int, str, list[str]]:
    """Run pytest on the given test files.

    Returns:
        Tuple of (passed, exit_code, output, failed_test_names)
    """
    if not test_files:
        return True, 0, "No test files to run", []

    # Build test command - configurable via TEST_RUNNER_CMD env var
    runner_cmd = os.environ.get("TEST_RUNNER_CMD", "").strip()
    if runner_cmd:
        # User-provided command - use shlex.split() to handle quoted paths/arguments
        cmd = [*shlex.split(runner_cmd), "-v", "--tb=short", *test_files]
    else:
        # Default: use uv run pytest
        if shutil.which("uv") is None:
            error_msg = (
                "Required executable 'uv' not found on PATH. "
                "Install uv from https://docs.astral.sh/uv/ or set TEST_RUNNER_CMD "
                "environment variable to override (e.g., TEST_RUNNER_CMD='python -m pytest')."
            )
            logger.error(error_msg)
            return False, -3, error_msg, []
        cmd = ["uv", "run", "pytest", "-v", "--tb=short", *test_files]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, -1, f"Test timeout after {timeout}s", []
    except subprocess.SubprocessError as e:
        # Covers CalledProcessError and other subprocess-related errors
        logger.exception("Subprocess error running tests")
        return False, -2, f"Subprocess error running tests: {e}", []
    except OSError as e:
        # Covers file not found, permission denied, etc.
        logger.exception("OS error executing test command")
        return False, -2, f"Failed to execute test command: {e}", []

    output = result.stdout + result.stderr
    passed = result.returncode == 0

    # Extract failed test names from output using regex for robust parsing
    # Collect full identifiers and short names separately, then deduplicate
    full_identifiers: set[str] = set()
    short_names: set[str] = set()

    for line in output.splitlines():
        if not line.strip():
            continue

        # Check for FAILED lines (summary section) - these have full identifiers
        failed_match = FAILED_LINE_PATTERN.match(line)
        if failed_match:
            test_id = failed_match.group(1)
            if test_id:
                full_identifiers.add(test_id)
            continue

        # Check for failure section headers - collect short names
        header_match = FAILURE_HEADER_PATTERN.match(line)
        if header_match:
            test_name = header_match.group(1)
            if test_name:
                short_names.add(test_name)

    # Deduplicate: prefer full identifiers, only keep short names without matching full ID
    # Extract normalized short names from full identifiers for proper comparison
    # This handles class-based tests (TestClass::test_method) and parametrized tests
    full_id_short_names = {_extract_short_test_name(fid) for fid in full_identifiers}

    failed_tests_set = set(full_identifiers)
    for short_name in short_names:
        # Check if any full identifier has a matching short name
        # This properly handles:
        # - path::test_foo vs test_foo
        # - path::TestClass::test_foo vs test_foo
        # - path::test_foo[param] vs test_foo[param]
        if short_name not in full_id_short_names:
            failed_tests_set.add(short_name)

    return passed, result.returncode, output, list(failed_tests_set)


def _test_path_matches_file(test_id: str, file_tests_parts: list[tuple[str, ...]]) -> bool:
    """Check if a failed test ID matches any of the expected test file paths.

    Args:
        test_id: Full test identifier (e.g., "path/to/test.py::test_name")
        file_tests_parts: List of path parts tuples for expected test files

    Returns:
        True if the test belongs to one of the expected test files
    """
    # Extract file path from test id (e.g., "path/to/test.py::test_name" -> "path/to/test.py")
    test_file_path = test_id.split("::")[0]
    test_path_parts = Path(test_file_path).parts

    for ft_parts in file_tests_parts:
        # Check if test path ends with the expected file path parts.
        # This handles both exact matches (equal lengths) and suffix matches
        # (test path is longer than expected file path).
        if len(test_path_parts) >= len(ft_parts) and test_path_parts[-len(ft_parts) :] == ft_parts:
            return True

    return False


def _find_failed_tests_for_file(failed_tests: list[str], file_tests: list[str]) -> list[str]:
    """Find which failed tests belong to the given test files.

    Args:
        failed_tests: List of failed test identifiers
        file_tests: List of test file paths to match against

    Returns:
        List of failed test identifiers that belong to the given test files
    """
    if not file_tests or not failed_tests:
        return []

    file_tests_parts = [Path(ft).parts for ft in file_tests]
    file_failed: list[str] = []

    for test_id in failed_tests:
        if _test_path_matches_file(test_id, file_tests_parts):
            file_failed.append(test_id)

    return file_failed


def run_tests_for_files(
    files: list[str],
    tiers: list[TierConfig] | None = None,
    timeout: int = 300,
) -> list[TestResult]:
    """Run tests for a list of source files.

    Args:
        files: List of source file paths (relative to repo root).
               Paths are normalized to POSIX form internally for cross-platform
               pattern matching.
        tiers: Optional tier configurations (loaded from pyproject.toml if not provided)
        timeout: Timeout in seconds for each test run

    Returns:
        List of TestResult objects with test outcomes
    """
    if tiers is None:
        tiers = load_tier_configs()

    if not tiers:
        raise ValueError(
            "No tier configurations found in pyproject.toml. "
            "Expected [tool.test_coverage.tiers] section with tier definitions."
        )

    results: list[TestResult] = []

    # Group files by tier and cache test files per source file to avoid redundant lookups
    tier_files: dict[str, list[str]] = {}
    tier_test_files: dict[str, list[str]] = {}
    # Cache mapping (tier_name, source_file) -> test_files list
    source_test_files_cache: dict[tuple[str, str], list[str]] = {}

    for raw_file_path in files:
        # Normalize to POSIX form for consistent pattern matching across platforms
        file_path = normalize_path(raw_file_path)
        # Skip non-Python files and test files
        if not file_path.endswith(".py"):
            logger.debug(
                "Skipping '%s': non-Python file",
                file_path,
            )
            continue
        if "/tests/" in file_path or file_path.startswith("tests/"):
            logger.debug(
                "Skipping '%s': is a test file",
                file_path,
            )
            continue

        tier = get_tier_for_file(file_path, tiers)
        if tier is None:
            logger.warning(
                "No matching tier for file '%s'. Check tier patterns in "
                "[tool.test_coverage.tiers] in pyproject.toml.",
                file_path,
            )
            continue

        if tier.name not in tier_files:
            tier_files[tier.name] = []
            tier_test_files[tier.name] = []

        tier_files[tier.name].append(file_path)

        # Find test files for this source file and cache the result
        test_files = find_test_files(file_path, tier)
        source_test_files_cache[(tier.name, file_path)] = test_files
        tier_test_files[tier.name].extend(test_files)

    # Run tests for each tier
    for tier_name, source_files in tier_files.items():
        test_files = sorted(set(tier_test_files[tier_name]))

        # Skip calling run_tests when no test files exist for this tier
        # This avoids unnecessary subprocess invocation
        if not test_files:
            exit_code = 0
            output = ""
            failed_tests: list[str] = []
        else:
            _passed, exit_code, output, failed_tests = run_tests(test_files, timeout)

        # Track which failed tests are attributed to source files
        attributed_failed_tests: set[str] = set()

        # Create results for each source file in this tier
        for source_file in source_files:
            # Use cached test files instead of calling find_test_files again
            file_tests = source_test_files_cache[(tier_name, source_file)]
            file_failed = _find_failed_tests_for_file(failed_tests, file_tests)

            # Track attributed failures
            attributed_failed_tests.update(file_failed)

            # Detect "no tests found" case
            has_no_tests = len(file_tests) == 0

            # For infra errors/timeouts (negative exit_code), mark all files as failed.
            # For "no tests found", mark as failed so consumers can distinguish from "tests passed".
            # For normal pytest runs (exit_code >= 0), determine passed solely from
            # whether this specific file has any failed tests.
            passed_per_file = False if exit_code < 0 or has_no_tests else not file_failed

            # Include output when there's an infra error, no tests found, or when file has
            # failures
            if exit_code < 0 or file_failed:
                output_for_file = output
            elif has_no_tests:
                output_for_file = "No tests found for source file"
            else:
                output_for_file = ""

            results.append(
                TestResult(
                    file=source_file,
                    tier=tier_name,
                    test_files=file_tests,
                    passed=passed_per_file,
                    exit_code=exit_code,
                    output=output_for_file,
                    failed_tests=file_failed,
                    no_tests=has_no_tests,
                )
            )

        # Check for unattributed failed tests after processing all source files in this tier
        if failed_tests:
            unattributed = set(failed_tests) - attributed_failed_tests
            if unattributed:
                # Create a synthetic TestResult for unattributed failures
                # This ensures these failures are visible and not silently ignored
                logger.warning(
                    "Tier '%s' has %d failed test(s) not mapped to any source file: %s",
                    tier_name,
                    len(unattributed),
                    sorted(unattributed),
                )
                results.append(
                    TestResult(
                        file="<unattributed>",
                        tier=tier_name,
                        test_files=test_files,
                        passed=False,
                        exit_code=exit_code,
                        output=output,
                        failed_tests=sorted(unattributed),
                        no_tests=False,
                    )
                )

    return results


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run tests for specific source files across test tiers.",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Source files to run tests for (relative to repo root)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds for test execution (default: 300)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    return parser.parse_args()


def main() -> int:
    """Run tests for specified files and report results."""
    args = parse_args()

    results = run_tests_for_files(args.files, timeout=args.timeout)

    if args.json:
        output = [
            {
                "file": r.file,
                "tier": r.tier,
                "test_files": r.test_files,
                "passed": r.passed,
                "exit_code": r.exit_code,
                "failed_tests": r.failed_tests,
                "output": r.output,
                "no_tests": r.no_tests,
            }
            for r in results
        ]
        print(json.dumps(output, indent=2))
    else:
        # Human-readable output
        passed_count = sum(1 for r in results if r.passed)
        failed_count = len(results) - passed_count

        print("=" * 70)
        print("TEST RESULTS FOR CHANGED FILES")
        print("=" * 70)

        for r in results:
            status = "PASS" if r.passed else "FAIL"
            print(f"\n{status}: {r.file} ({r.tier})")
            if r.test_files:
                print(f"  Tests: {', '.join(r.test_files)}")
            else:
                print("  Tests: No matching test files found")
            if r.failed_tests:
                print("  Failed:")
                for t in r.failed_tests:
                    print(f"    - {t}")

        print("\n" + "=" * 70)
        print(f"Summary: {passed_count} passed, {failed_count} failed")
        print("=" * 70)

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
