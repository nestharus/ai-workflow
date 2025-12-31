"""Actionlint GitHub Actions workflow linter."""

import json
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

ACTIONLINT_CLI_REQUIRED = "actionlint CLI required to run lint"
LINT_ACTIONLINT_CONFIG = REPO_ROOT / ".lint.actionlint.yaml"


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

    name = "actionlint"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run actionlint on GitHub Actions workflow files.

        Args:
            files: Optional list of files to check. If None, checks all workflow files.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        actionlint_exe = get_executable("actionlint", ACTIONLINT_CLI_REQUIRED)
        config = load_yaml_config(LINT_ACTIONLINT_CONFIG)
        ignore_patterns: list[str] = config.get("ignore", [])
        included_paths = config.get("included_paths", [])

        workflows_dir = REPO_ROOT / ".github" / "workflows"

        if files is not None:
            # Filter to only workflow YAML files that match include patterns
            workflow_files = [
                f
                for f in files
                if (f.endswith(".yml") or f.endswith(".yaml"))
                and is_path_included(f, included_paths)
            ]
            if not workflow_files:
                print("No GitHub Actions workflow files to check with actionlint")
                return LinterResult(success=True)
            targets = workflow_files
        else:
            if not workflows_dir.exists():
                print("No .github/workflows/ directory found for actionlint scan")
                return LinterResult(success=True)
            # Enumerate workflow files, respecting include patterns
            workflow_files = [
                str(path)
                for path in workflows_dir.rglob("*.yml")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), included_paths)
            ]
            workflow_files.extend(
                str(path)
                for path in workflows_dir.rglob("*.yaml")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), included_paths)
            )
            if not workflow_files:
                print("No workflow files found for actionlint scan")
                return LinterResult(success=True)
            targets = workflow_files

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
