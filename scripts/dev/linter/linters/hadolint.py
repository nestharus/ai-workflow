"""Hadolint Dockerfile linter."""

import json
import subprocess
from pathlib import Path

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
)

HADOLINT_CLI_REQUIRED = "hadolint CLI required to run lint"
HADOLINT_CONFIG = REPO_ROOT / ".hadolint.yaml"


def _is_dockerfile(filepath: str) -> bool:
    """Check if a file is a Dockerfile."""
    return Path(filepath).name == "Dockerfile"


def _parse_hadolint_json(json_output: str) -> list[LintError]:
    """Parse hadolint JSON output into LintError objects.

    Args:
        json_output: Raw JSON string from hadolint --format json.

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
                file=item.get("file", ""),
                line=item.get("line", 0),
                column=item.get("column", 0),
                code=item.get("code", ""),
                message=item.get("message", ""),
                context=None,  # hadolint JSON doesn't include context
                fix_available=False,  # hadolint doesn't provide auto-fixes
                fix_message=None,
            )
        )
    return errors


class HadolintLinter(BaseLinter):
    """Run hadolint on Dockerfiles."""

    name = "hadolint"
    config_file = ".lint.hadolint.yaml"
    extensions = _is_dockerfile  # Use callable for filename-based matching
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run hadolint on Dockerfiles.

        Args:
            files: Optional list of files to check. If None, checks all Dockerfiles.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        hadolint_exe = get_executable("hadolint", HADOLINT_CLI_REQUIRED)

        if files is not None:
            dockerfiles = [Path(f) for f in self.filter_files(files)]
        else:
            dockerfiles = [Path(f) for f in self.discover_files()]

        if not dockerfiles:
            print("No Dockerfiles found for hadolint scan")
            return LinterResult(success=True)

        # Run hadolint with JSON output format
        result = subprocess.run(
            [
                hadolint_exe,
                "--format",
                "json",
                "--config",
                str(HADOLINT_CONFIG),
                *[str(path) for path in dockerfiles],
            ],
            capture_output=True,
            text=True,
        )

        # Parse errors from JSON output
        errors = _parse_hadolint_json(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
