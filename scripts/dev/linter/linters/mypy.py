"""Mypy type checker linter."""

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
LINT_MYPY_CONFIG = REPO_ROOT / ".lint.mypy.yaml"


def _parse_mypy_json(json_output: str) -> list[LintError]:
    """Parse mypy JSON output into LintError objects.

    Args:
        json_output: Raw JSON string from mypy --output=json.

    Returns:
        List of LintError objects.
    """
    if not json_output.strip():
        return []

    errors = []
    # Mypy outputs one JSON object per line
    for line in json_output.strip().splitlines():
        if not line.strip():
            continue

        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Only include errors, not notes/warnings
        if item.get("severity") != "error":
            continue

        errors.append(
            LintError(
                file=item.get("file", ""),
                line=item.get("line", 0),
                column=item.get("column", 0),
                code=item.get("code", ""),
                message=item.get("message", ""),
                context=item.get("hint"),  # mypy provides hints as context
                fix_available=False,  # mypy doesn't provide auto-fixes
                fix_message=None,
            )
        )
    return errors


class MypyLinter(BaseLinter):
    """Run mypy type checking."""

    name = "mypy"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run mypy type checking.

        Args:
            files: Optional list of files to check. If None, checks entire repo.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        uv_exe = get_executable("uv", UV_CLI_REQUIRED)

        if files is None:
            targets = []
        else:
            py_files = [f for f in files if f.endswith(".py")]
            if not py_files:
                print("No Python files to check with mypy")
                return LinterResult(success=True)

            # Apply included_paths filter from config
            py_files, error = filter_files_with_config(py_files, LINT_MYPY_CONFIG, "mypy")
            if error is not None:
                return error
            if not py_files:
                return LinterResult(success=True)

            targets = py_files

        # Run mypy with JSON output format
        result = subprocess.run(
            [uv_exe, "run", "mypy", "--output=json", *targets],
            capture_output=True,
            text=True,
        )

        # Parse errors from JSON output
        errors = _parse_mypy_json(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
