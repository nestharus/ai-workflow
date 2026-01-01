"""Dotenv-linter for .env files."""

import re
import subprocess
from pathlib import Path

from scripts.dev.linter.base import (
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
)

DOTENV_LINTER_CLI_REQUIRED = "dotenv-linter CLI required to run lint"


def _is_env_file(filepath: str) -> bool:
    """Check if a file is an .env file."""
    return Path(filepath).name.startswith(".env")


# Regex to parse dotenv-linter output format:
# Example: .env:2 LowercaseKey: The foo key should be in uppercase
DOTENV_ERROR_PATTERN = re.compile(r"^(.+):(\d+)\s+(\w+):\s+(.+)$")


def _parse_dotenvlint_output(output: str) -> list[LintError]:
    """Parse dotenv-linter text output into LintError objects.

    Args:
        output: Raw text output from dotenv-linter check.

    Returns:
        List of LintError objects.
    """
    if not output.strip():
        return []

    errors = []
    for line in output.splitlines():
        match = DOTENV_ERROR_PATTERN.match(line)
        if match:
            file_path = match.group(1)
            line_num = int(match.group(2))
            error_code = match.group(3)
            message = match.group(4)

            errors.append(
                LintError(
                    file=file_path,
                    line=line_num,
                    column=0,  # dotenv-linter doesn't provide column info
                    code=error_code,
                    message=message,
                    context=None,
                    fix_available=False,  # Can check if fix command exists
                    fix_message=None,
                )
            )

    return errors


class DotenvlintLinter(BaseLinter):
    """Run dotenv-linter on .env files."""

    name = "dotenvlint"
    config_file = ".lint.dotenvlint.yaml"
    extensions = _is_env_file  # Use callable for prefix-based matching
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run dotenv-linter on .env files.

        Args:
            files: Optional list of files to check. If None, checks configured targets.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        dotenv_linter_exe = get_executable("dotenv-linter", DOTENV_LINTER_CLI_REQUIRED)

        if files:
            targets = self.filter_files(files)
            if not targets:
                print("No .env files to check with dotenv-linter")
                return LinterResult(success=True)
        else:
            targets = self.discover_files()

        if not targets:
            print("No .env files found for dotenv-linter scan")
            return LinterResult(success=True)

        # Run dotenv-linter check with --plain flag for consistent output
        result = subprocess.run(
            [dotenv_linter_exe, "check", "--plain", *targets],
            capture_output=True,
            text=True,
        )

        # Parse errors from output
        errors = _parse_dotenvlint_output(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
