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
    is_path_included,
    load_yaml_config,
)

HADOLINT_CLI_REQUIRED = "hadolint CLI required to run lint"
HADOLINT_CONFIG = REPO_ROOT / ".hadolint.yaml"
LINT_HADOLINT_CONFIG = REPO_ROOT / ".lint.hadolint.yaml"


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
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run hadolint on Dockerfiles.

        Args:
            files: Optional list of files to check. If None, checks all Dockerfiles.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        hadolint_exe = get_executable("hadolint", HADOLINT_CLI_REQUIRED)
        config = load_yaml_config(LINT_HADOLINT_CONFIG)
        included_paths = config.get("included_paths", [])

        if files is not None:
            # Filter to only Dockerfile files that match include patterns
            dockerfiles = [
                Path(f)
                for f in files
                if Path(f).name == "Dockerfile" and is_path_included(f, included_paths)
            ]
        else:
            # Find all Dockerfiles and filter by include patterns
            dockerfiles = [
                path
                for path in REPO_ROOT.rglob("Dockerfile")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), included_paths)
            ]

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
