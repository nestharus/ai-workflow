"""Pymarkdown Markdown linter."""

import re
import subprocess

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
    is_path_included,
    load_yaml_config,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
LINT_PYMARKDOWN_CONFIG = REPO_ROOT / ".lint.pymarkdown.yaml"


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

    name = "pymarkdown"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run pymarkdown on Markdown files.

        Args:
            files: Optional list of files to check. If None, checks configured targets.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        uv_exe = get_executable("uv", UV_CLI_REQUIRED)
        config = load_yaml_config(LINT_PYMARKDOWN_CONFIG)
        included_paths = config.get("included_paths", [])

        if files is not None:
            md_files = [f for f in files if f.endswith(".md")]
            # Filter by include patterns
            md_files = [f for f in md_files if is_path_included(f, included_paths)]
            if not md_files:
                print("No Markdown files to check with pymarkdown")
                return LinterResult(success=True)
            targets = md_files
            pymarkdown_cmd = [
                uv_exe,
                "run",
                "pymarkdown",
                "-c",
                str(REPO_ROOT / ".pymarkdown.json"),
                "scan",
                *targets,
            ]
        else:
            targets = included_paths
            pymarkdown_cmd = [
                uv_exe,
                "run",
                "pymarkdown",
                "-c",
                str(REPO_ROOT / ".pymarkdown.json"),
                "scan",
                "-r",
                *targets,
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
