"""ast-grep structural code linter for Python."""

import fnmatch
import json
import re
import subprocess
from functools import lru_cache
from typing import Any

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
    load_yaml_config,
)

ASTGREP_CLI_REQUIRED = "ast-grep CLI required (install via: pip install ast-grep-cli)"
LINT_ASTGREP_CONFIG = REPO_ROOT / ".lint.astgrep.yaml"


@lru_cache(maxsize=128)
def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a glob pattern to a compiled regex.

    Handles ** patterns correctly per standard glob semantics:
    - ** matches zero or more path components
    - * matches anything except path separators
    - ? matches a single character except path separators
    - [abc] matches any single character in the set
    - [a-z] matches any single character in the range
    - [!abc] matches any single character not in the set

    Args:
        pattern: A glob pattern (e.g., "app/**/*.py", "app/**/[a-z]*.py").

    Returns:
        A compiled regex pattern.
    """
    result = ""
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # ** - match zero or more path components
                if i + 2 < len(pattern) and pattern[i + 2] == "/":
                    # **/ - match zero or more directories followed by /
                    result += "(?:.+/)?"
                    i += 3
                    continue
                else:
                    # ** at end or followed by non-/ - match anything
                    result += ".*"
                    i += 2
                    continue
            else:
                # Single * - match anything except /
                result += "[^/]*"
                i += 1
                continue
        elif char == "?":
            result += "[^/]"
        elif char == "[":
            # Parse bracket expression for character class
            bracket_content, consumed = _parse_bracket_expression(pattern, i)
            result += bracket_content
            i += consumed
            continue
        elif char in ".^$+{}|()\\#":
            result += "\\" + char
        else:
            result += char
        i += 1
    return re.compile("^" + result + "$")


def _parse_bracket_expression(pattern: str, start: int) -> tuple[str, int]:
    """Parse a glob bracket expression and convert to regex character class.

    Handles:
    - [abc] - match any of a, b, or c
    - [a-z] - match any character in range a to z
    - [!abc] or [^abc] - match any character NOT in the set
    - Nested special characters are escaped as needed

    Args:
        pattern: The full glob pattern.
        start: Index of the opening '[' in the pattern.

    Returns:
        Tuple of (regex_fragment, characters_consumed).
        If no valid bracket expression found, returns escaped '[' and 1.
    """
    i = start + 1  # Skip opening '['
    length = len(pattern)

    # Check if we have a valid bracket expression (must have closing ']')
    # Find the closing bracket, accounting for ']' at start being literal
    close_idx = -1
    search_start = i
    # ']' immediately after '[' or '[!' is treated as literal
    if search_start < length and pattern[search_start] in "!^":
        search_start += 1
    if search_start < length and pattern[search_start] == "]":
        search_start += 1

    for j in range(search_start, length):
        if pattern[j] == "]":
            close_idx = j
            break

    if close_idx == -1:
        # No closing bracket found - treat '[' as literal
        return "\\[", 1

    # Extract the content between brackets
    content = pattern[start + 1 : close_idx]
    if not content:
        # Empty brackets - treat as literal
        return "\\[\\]", 2

    # Build the regex character class
    result = "["

    # Handle negation: glob uses '!' but regex uses '^'
    content_start = 0
    if content.startswith("!"):
        result += "^"
        content_start = 1
    elif content.startswith("^"):
        # Some globs also support '^' for negation
        result += "^"
        content_start = 1

    # Process the rest of the content
    # We need to escape regex metacharacters that aren't special in glob brackets
    remaining = content[content_start:]

    # Inside bracket expressions, most characters are literal
    # But we need to handle:
    # - ']' at the start is literal (already handled by finding close_idx)
    # - '-' at start or end is literal, otherwise it's a range
    # - '\' might need escaping in regex
    # - '^' after first position is literal

    for c in remaining:
        if c == "\\":
            # Escape backslash for regex
            result += "\\\\"
        else:
            # Most characters are literal inside character classes
            result += c

    result += "]"

    # Return the regex fragment and how many characters we consumed
    consumed = close_idx - start + 1
    return result, consumed


def _matches_glob_pattern(file_path: str, pattern: str) -> bool:
    """Check if a file path matches a glob pattern.

    Uses regex-based matching for ** patterns to correctly handle zero-or-more
    directory matching per standard glob semantics.

    Args:
        file_path: The file path to check (relative to repo root).
        pattern: A glob pattern (e.g., "app/**/*.py", "*.py").

    Returns:
        True if the path matches the pattern.
    """
    # Handle ** patterns with regex for correct zero-or-more matching
    if "**" in pattern:
        regex = _glob_to_regex(pattern)
        return regex.match(file_path) is not None

    # For patterns without path separators (e.g., "*.py"),
    # only match files at the root level
    if "/" not in pattern:
        # Only match if the file is at the root (no directory component)
        if "/" in file_path:
            return False
        return fnmatch.fnmatch(file_path, pattern)

    # For patterns with path separators but no **, use regex for full-path matching
    # Note: Path.match() matches from the right, so "app/*.py" would also match
    # "vendor/app/foo.py". Using regex enforces full-path matching from the left.
    return _glob_to_regex(pattern).match(file_path) is not None


def _is_file_included(file_path: str, included_paths: list[str]) -> bool:
    """Check if a file should be included based on include patterns.

    Args:
        file_path: The file path to check (relative to repo root).
        included_paths: List of glob patterns for paths to include.

    Returns:
        True if the file matches any include pattern.
    """
    # If no include patterns, include everything
    if not included_paths:
        return True

    # Check if file matches any include pattern
    return any(_matches_glob_pattern(file_path, p) for p in included_paths)


def _parse_astgrep_json(json_output: str) -> list[LintError]:
    """Parse ast-grep JSON output into LintError objects.

    Args:
        json_output: Raw JSON string from ast-grep --json output.

    Returns:
        List of LintError objects.
    """
    if not json_output.strip():
        return []

    try:
        matches = json.loads(json_output)
    except json.JSONDecodeError:
        return []

    errors = []
    for match in matches:
        # ast-grep uses 0-based line/column numbers
        # Convert to 1-based for consistency with other linters
        start_pos = match.get("range", {}).get("start", {})
        line = start_pos.get("line", 0) + 1
        column = start_pos.get("column", 0) + 1

        # Extract context from the 'lines' field
        context = match.get("lines", "").strip()

        errors.append(
            LintError(
                file=match.get("file", ""),
                line=line,
                column=column,
                code=match.get("ruleId", ""),
                message=match.get("message", ""),
                context=context if context else None,
                fix_available=False,  # ast-grep doesn't report fix availability in JSON
                fix_message=match.get("note"),  # Use note as additional context
            )
        )

    return errors


class AstgrepLinter(BaseLinter):
    """Run ast-grep structural code analysis."""

    name = "astgrep"
    supports_file_filtering = True

    def _validate_sgconfig(self) -> LinterResult | None:
        """Check if sgconfig.yml exists.

        Returns:
            LinterResult on failure, None on success.
        """
        sgconfig = REPO_ROOT / "sgconfig.yml"
        if not sgconfig.exists():
            return LinterResult(
                success=False,
                message="sgconfig.yml not found - ast-grep requires this configuration file",
            )
        return None

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run ast-grep scan on Python files.

        Args:
            files: Optional list of files to lint. If None, scans entire repo.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        sg_exe = get_executable("ast-grep", ASTGREP_CLI_REQUIRED)

        if (error := self._validate_sgconfig()) is not None:
            return error

        # Load optional configuration
        config: dict[str, Any] = {}
        if LINT_ASTGREP_CONFIG.exists():
            config = load_yaml_config(LINT_ASTGREP_CONFIG)

        included_paths = config.get("included_paths", [])
        if isinstance(included_paths, str):
            included_paths = [included_paths]
        elif isinstance(included_paths, list):
            included_paths = [p for p in included_paths if isinstance(p, str)]
        else:
            included_paths = []

        # Build command with JSON output
        cmd = [sg_exe, "scan", "--json=compact"]

        if files is not None:
            # File-filtered mode: filter files using include patterns
            py_files = [
                f
                for f in files
                if f.endswith((".py", ".pyi")) and _is_file_included(f, included_paths)
            ]
            if not py_files:
                return LinterResult(success=True, message="No Python files to scan with ast-grep")
            cmd.extend(py_files)
        else:
            # Whole-repo mode: use --globs for include patterns
            for include_path in included_paths:
                cmd.extend(["--globs", include_path])
            # Scan from current directory (repo root)
            cmd.append(".")

        # Run scan from repo root
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
        )

        # Parse JSON output into structured errors
        errors = _parse_astgrep_json(result.stdout)

        # Check for stderr errors (e.g., config issues, tool errors)
        if result.stderr:
            print(result.stderr)
            # If we have stderr but no structured errors, return failure with message
            if not errors and result.returncode != 0:
                return LinterResult(success=False, message=result.stderr)

        # Return structured result
        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)

    def test(self) -> LinterResult:
        """Run ast-grep rule tests to validate custom rules.

        Returns:
            LinterResult indicating success/failure.
        """
        sg_exe = get_executable("ast-grep", ASTGREP_CLI_REQUIRED)

        if (error := self._validate_sgconfig()) is not None:
            return error

        # Run rule tests
        result = subprocess.run(
            [sg_exe, "test"],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
        )

        # Print output for visibility
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)

        if result.returncode != 0:
            return LinterResult(
                success=False,
                message=f"ast-grep rule tests failed (exit code {result.returncode})",
            )

        return LinterResult(success=True, message="All ast-grep rule tests passed")
