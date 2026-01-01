"""Shellcheck linter for shell scripts."""

import json
import subprocess
import sys
from typing import ClassVar

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
)

SHELLCHECK_CLI_REQUIRED = "shellcheck CLI required to run lint"


def _parse_shellcheck_json(json_output: str) -> list[LintError]:
    """Parse shellcheck JSON output into LintError objects.

    Args:
        json_output: Raw JSON string from shellcheck --format=json.

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
                file=item.get("file", ""),
                line=item.get("line", 0),
                column=item.get("column", 0),
                code=f"SC{item.get('code', 0)}",
                message=item.get("message", ""),
                context=None,  # shellcheck JSON doesn't include context
                fix_available=fix_info is not None,
                fix_message=None,  # shellcheck doesn't provide fix messages
            )
        )
    return errors


class ShellcheckLinter(BaseLinter):
    """Run shellcheck on shell scripts."""

    name: ClassVar[str] = "shellcheck"
    config_file: ClassVar[str] = ".lint.shellcheck.yaml"
    extensions: ClassVar[list[str]] = [".sh"]
    supports_file_filtering: ClassVar[bool] = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run shellcheck on shell scripts.

        Args:
            files: Optional list of files to check. If None, checks all .sh files.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        # Handle missing binary gracefully
        try:
            shellcheck_exe = get_executable("shellcheck", SHELLCHECK_CLI_REQUIRED)
        except RuntimeError:
            print(SHELLCHECK_CLI_REQUIRED, file=sys.stderr)
            return LinterResult(success=False, message=SHELLCHECK_CLI_REQUIRED)

        if files is not None:
            # Filter files using BaseLinter's filter_files
            shell_files = [str(REPO_ROOT / f) for f in self.filter_files(files)]
        else:
            # Discover files using BaseLinter's discover_files
            shell_files = [str(REPO_ROOT / f) for f in self.discover_files()]

        if not shell_files:
            print("No shell scripts to check with shellcheck")
            return LinterResult(success=True)

        # Run shellcheck with JSON output format
        result = subprocess.run(
            [shellcheck_exe, "--format=json", *shell_files],
            capture_output=True,
            text=True,
        )

        # Parse errors from JSON output
        errors = _parse_shellcheck_json(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
