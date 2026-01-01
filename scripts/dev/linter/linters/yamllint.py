"""Yamllint YAML linter."""

import re
import subprocess
from pathlib import Path
from typing import ClassVar

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
YAMLLINT_CONFIG = REPO_ROOT / ".yamllint.yaml"


def _parse_yamllint_parsable(output: str) -> list[LintError]:
    """Parse yamllint parsable format output into LintError objects.

    Args:
        output: Raw output string from yamllint -f parsable.

    Returns:
        List of LintError objects.

    Format:
        file.yml:6:2: [warning] missing starting space in comment (comments)
        file.yml:57:1: [error] trailing spaces (trailing-spaces)
    """
    if not output.strip():
        return []

    errors = []
    # Pattern: filename:line:column: [level] message (rule-name)
    pattern = r"^(.+?):(\d+):(\d+):\s+\[(warning|error)\]\s+(.+?)\s+\((.+?)\)$"

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        match = re.match(pattern, line)
        if not match:
            continue

        file_path, line_no, col_no, _level, message, rule_name = match.groups()

        errors.append(
            LintError(
                file=file_path,
                line=int(line_no),
                column=int(col_no),
                code=rule_name,
                message=message,
                context=None,  # yamllint parsable format doesn't include context
                fix_available=False,  # yamllint doesn't provide auto-fixes
                fix_message=None,
            )
        )

    return errors


class YamllintLinter(BaseLinter):
    """Run yamllint on YAML files."""

    name: ClassVar[str] = "yamllint"
    config_file: ClassVar[str] = ".lint.yamllint.yaml"
    extensions: ClassVar[list[str]] = [".yaml", ".yml"]
    supports_file_filtering: ClassVar[bool] = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run yamllint on YAML files.

        Args:
            files: Optional list of files to check. If None, checks all YAML files.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        yamllint_exe = get_executable("yamllint", UV_CLI_REQUIRED)

        if files is not None:
            yaml_files = [Path(f) for f in self.filter_files(files)]
        else:
            yaml_files = [Path(f) for f in self.discover_files()]

        if not yaml_files:
            print("No YAML files found for yamllint scan")
            return LinterResult(success=True)

        # Run yamllint with parsable format to get structured output
        result = subprocess.run(
            [
                yamllint_exe,
                "-f",
                "parsable",
                "-c",
                str(YAMLLINT_CONFIG),
                *[str(path) for path in yaml_files],
            ],
            capture_output=True,
            text=True,
        )

        # Parse errors from parsable output
        errors = _parse_yamllint_parsable(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
