"""Pymarkdown Markdown linter."""

import re
import subprocess
from typing import ClassVar

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"


def _parse_pymarkdown_output(output: str) -> list[LintError]:
    """Parse pymarkdown text output into LintError objects.

    Pymarkdown outputs errors in the format:
    file-name:line:column: rule-id: description (aliases)

    Example:
    test.md:1:1: MD041: First line in file should be a top level heading
    (first-line-heading,first-line-h1)

    Args:
        output: Raw text output from pymarkdown.

    Returns:
        List of LintError objects.
    """
    if not output.strip():
        return []

    errors = []
    # Pattern: file:line:column: CODE: message (aliases)
    # Note: Some rules include additional context in brackets like [Column: 18]
    pattern = r"^(.+?):(\d+):(\d+):\s+([A-Z]+\d+):\s+(.+?)(?:\s+\(.*\))?$"

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        match = re.match(pattern, line)
        if match:
            file_path = match.group(1)
            line_num = int(match.group(2))
            column_num = int(match.group(3))
            rule_code = match.group(4)
            message = match.group(5)

            errors.append(
                LintError(
                    file=file_path,
                    line=line_num,
                    column=column_num,
                    code=rule_code,
                    message=message,
                    context=None,  # pymarkdown doesn't provide context
                    fix_available=False,  # we don't run in fix mode
                    fix_message=None,
                )
            )

    return errors


class PymarkdownLinter(BaseLinter):
    """Run pymarkdown on Markdown files."""

    name: ClassVar[str] = "pymarkdown"
    config_file: ClassVar[str] = ".lint.pymarkdown.yaml"
    extensions: ClassVar[list[str]] = [".md"]
    supports_file_filtering: ClassVar[bool] = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run pymarkdown on Markdown files.

        Args:
            files: Optional list of files to check. If None, checks configured targets.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        uv_exe = get_executable("uv", UV_CLI_REQUIRED)

        if files is not None:
            md_files = self.filter_files(files)
            if not md_files:
                print("No Markdown files to check with pymarkdown")
                return LinterResult(success=True)
            pymarkdown_cmd = [
                uv_exe,
                "run",
                "pymarkdown",
                "-c",
                str(REPO_ROOT / ".pymarkdown.json"),
                "scan",
                *md_files,
            ]
        else:
            # Use included_paths directly for recursive scan
            included_paths = self.get_included_paths()
            pymarkdown_cmd = [
                uv_exe,
                "run",
                "pymarkdown",
                "-c",
                str(REPO_ROOT / ".pymarkdown.json"),
                "scan",
                "-r",
                *included_paths,
            ]

        # Run pymarkdown and capture output
        result = subprocess.run(
            pymarkdown_cmd,
            capture_output=True,
            text=True,
        )

        # Parse errors from text output (pymarkdown outputs to stdout)
        errors = _parse_pymarkdown_output(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
