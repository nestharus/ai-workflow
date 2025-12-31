"""Ruff linter for Python formatting and linting."""

import json
import subprocess

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    filter_files_with_config,
    get_executable,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
LINT_RUFF_CONFIG = REPO_ROOT / ".lint.ruff.yaml"


def _parse_ruff_json(json_output: str) -> list[LintError]:
    """Parse ruff JSON output into LintError objects.

    Args:
        json_output: Raw JSON string from ruff --output-format json.

    Returns:
        List of LintError objects.
    """
    if not json_output.strip():
        return []

    try:
        errors_data = json.loads(json_output)
    except json.JSONDecodeError:
        return []

    errors = []
    for item in errors_data:
        fix_info = item.get("fix")
        errors.append(
            LintError(
                file=item.get("filename", ""),
                line=item.get("location", {}).get("row", 0),
                column=item.get("location", {}).get("column", 0),
                code=item.get("code", ""),
                message=item.get("message", ""),
                context=None,  # ruff JSON doesn't include context
                fix_available=fix_info is not None,
                fix_message=fix_info.get("message") if fix_info else None,
            )
        )
    return errors


class RuffLinter(BaseLinter):
    """Run ruff format and check.

    This linter modifies source files in-place via:
    - ruff format: Applies code formatting
    - ruff check --fix: Auto-fixes lint issues

    Therefore mutates_files is set to True.
    """

    name = "ruff"
    supports_file_filtering = True
    mutates_files = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run ruff format and check.

        Args:
            files: Optional list of files to lint. If None, lints entire repo.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        uv_exe = get_executable("uv", UV_CLI_REQUIRED)

        if files is None:
            targets = ["."]
        else:
            py_files = [f for f in files if f.endswith(".py")]
            if not py_files:
                print("No Python files to lint with ruff")
                return LinterResult(success=True)

            # Apply included_paths filter from config
            py_files, error = filter_files_with_config(py_files, LINT_RUFF_CONFIG, "ruff")
            if error is not None:
                return error
            if not py_files:
                return LinterResult(success=True)

            targets = py_files

        # Step 1: Run ruff format (modifies files, suppress output)
        subprocess.run(
            [uv_exe, "run", "ruff", "format", *targets],
            capture_output=True,
            check=True,
        )

        # Step 2: Run ruff check --fix to apply safe fixes (modifies files)
        subprocess.run(
            [uv_exe, "run", "ruff", "check", "--fix", *targets],
            capture_output=True,
            text=True,
        )

        # Step 3: Run ruff check with JSON output to get remaining errors
        result = subprocess.run(
            [uv_exe, "run", "ruff", "check", "--output-format", "json", *targets],
            capture_output=True,
            text=True,
        )

        # Parse errors from JSON output
        errors = _parse_ruff_json(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
