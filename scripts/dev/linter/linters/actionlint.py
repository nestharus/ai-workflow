"""Actionlint GitHub Actions workflow linter."""

import json
import subprocess
from typing import ClassVar

from scripts.dev.linter.base import (
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
)

ACTIONLINT_CLI_REQUIRED = "actionlint CLI required to run lint"


def _parse_actionlint_json(json_output: str) -> list[LintError]:
    """Parse actionlint JSON output into LintError objects.

    Args:
        json_output: Raw JSON string from actionlint -format '{{json .}}'.

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
        errors.append(
            LintError(
                file=item.get("filepath", ""),
                line=item.get("line", 0),
                column=item.get("column", 0),
                code=item.get("kind", ""),
                message=item.get("message", ""),
                context=item.get("snippet"),
                fix_available=False,  # actionlint doesn't provide auto-fixes
                fix_message=None,
            )
        )
    return errors


class ActionlintLinter(BaseLinter):
    """Run actionlint on GitHub Actions workflow files."""

    name: ClassVar[str] = "actionlint"
    config_file: ClassVar[str] = ".lint.actionlint.yaml"
    extensions: ClassVar[list[str]] = [".yml", ".yaml"]
    supports_file_filtering: ClassVar[bool] = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run actionlint on GitHub Actions workflow files.

        Args:
            files: Optional list of files to check. If None, checks all workflow files.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        actionlint_exe = get_executable("actionlint", ACTIONLINT_CLI_REQUIRED)
        config = self.load_config()
        ignore_patterns: list[str] = config.get("ignore", [])

        if files is not None:
            targets = self.filter_files(files)
            if not targets:
                print("No GitHub Actions workflow files to check with actionlint")
                return LinterResult(success=True)
        else:
            targets = self.discover_files()
            if not targets:
                print("No workflow files found for actionlint scan")
                return LinterResult(success=True)

        cmd = [actionlint_exe, "-format", "{{json .}}"]
        for pattern in ignore_patterns:
            cmd.extend(["-ignore", pattern])
        cmd.extend(targets)

        # Run actionlint with JSON output format
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        # Parse errors from JSON output
        errors = _parse_actionlint_json(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
