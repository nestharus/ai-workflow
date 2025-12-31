"""Yamllint YAML linter."""

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

UV_CLI_REQUIRED = "uv CLI required to run lint"
YAMLLINT_CONFIG = REPO_ROOT / ".yamllint.yaml"
LINT_YAMLLINT_CONFIG = REPO_ROOT / ".lint.yamllint.yaml"


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

    name = "yamllint"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run yamllint on YAML files.

        Args:
            files: Optional list of files to check. If None, checks all YAML files.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        yamllint_exe = get_executable("yamllint", UV_CLI_REQUIRED)
        config = load_yaml_config(LINT_YAMLLINT_CONFIG)
        included_paths = config.get("included_paths", [])

        if files is not None:
            # Filter to YAML files that match include patterns
            yaml_files = [
                Path(f)
                for f in files
                if (f.endswith(".yaml") or f.endswith(".yml"))
                and is_path_included(f, included_paths)
            ]
        else:
            # Find all YAML files and filter by include patterns
            yaml_files = [
                path
                for path in REPO_ROOT.rglob("*.yaml")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), included_paths)
            ]
            # Also check .yml files
            yaml_files.extend(
                path
                for path in REPO_ROOT.rglob("*.yml")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), included_paths)
            )

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
