"""Dotenv-linter for .env files."""

import re
import subprocess
from pathlib import Path

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
    is_path_included,
    load_yaml_config,
)

DOTENV_LINTER_CLI_REQUIRED = "dotenv-linter CLI required to run lint"
LINT_DOTENVLINT_CONFIG = REPO_ROOT / ".lint.dotenvlint.yaml"

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
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run dotenv-linter on .env files.

        Args:
            files: Optional list of files to check. If None, checks configured targets.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        dotenv_linter_exe = get_executable("dotenv-linter", DOTENV_LINTER_CLI_REQUIRED)
        config = load_yaml_config(LINT_DOTENVLINT_CONFIG)
        included_paths = config.get("included_paths", [])

        if files:
            # Filter to only .env files that match include patterns
            env_files = [
                f
                for f in files
                if Path(f).name.startswith(".env") and is_path_included(f, included_paths)
            ]
            if not env_files:
                print("No .env files to check with dotenv-linter")
                return LinterResult(success=True)
            targets = env_files
        else:
            # Find all .env files that match included_paths patterns
            env_files = []
            for path in REPO_ROOT.rglob(".env*"):
                if path.is_file():
                    rel_path = str(path.relative_to(REPO_ROOT))
                    if is_path_included(rel_path, included_paths):
                        env_files.append(str(path))
            targets = env_files

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
