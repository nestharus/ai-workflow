"""Shellcheck linter for shell scripts."""

import json
import subprocess
import sys

import yaml

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
    is_path_included,
    load_yaml_config,
)

SHELLCHECK_CLI_REQUIRED = "shellcheck CLI required to run lint"
LINT_SHELLCHECK_CONFIG = REPO_ROOT / ".lint.shellcheck.yaml"


def _parse_shellcheck_json(json_output: str) -> list[LintError]:
    """Parse shellcheck JSON output into LintError objects.

    Args:
        json_output: Raw JSON string from shellcheck --format=json.

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
        fix_info = item.get("fix")
        errors.append(
            LintError(
                file=item.get("file", ""),
                line=item.get("line", 0),
                column=item.get("column", 0),
                code=f"SC{item.get('code', 0)}",
                message=item.get("message", ""),
                context=None,  # shellcheck JSON doesn't include context
                fix_available=fix_info is not None,
                fix_message=None,  # shellcheck doesn't provide fix messages
            )
        )
    return errors


class ShellcheckLinter(BaseLinter):
    """Run shellcheck on shell scripts."""

    name = "shellcheck"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run shellcheck on shell scripts.

        Args:
            files: Optional list of files to check. If None, checks all .sh files.

        Returns:
            LinterResult indicating success/failure with structured errors.
        """
        # Handle missing binary gracefully
        try:
            shellcheck_exe = get_executable("shellcheck", SHELLCHECK_CLI_REQUIRED)
        except RuntimeError:
            print(SHELLCHECK_CLI_REQUIRED, file=sys.stderr)
            return LinterResult(success=False, message=SHELLCHECK_CLI_REQUIRED)

        # Load inclusion config
        config = {}
        if LINT_SHELLCHECK_CONFIG.exists():
            try:
                config = load_yaml_config(LINT_SHELLCHECK_CONFIG)
            except (OSError, yaml.YAMLError) as e:
                msg = f"Invalid or unreadable {LINT_SHELLCHECK_CONFIG.name}: {e}"
                print(msg, file=sys.stderr)
                return LinterResult(success=False, message=msg)

        if not isinstance(config, dict):
            config = {}
        included_paths = config.get("included_paths", [])

        if files is not None:
            # Filter to only .sh files that match include patterns
            shell_files = [
                str(REPO_ROOT / f)
                for f in files
                if f.endswith(".sh") and (not included_paths or is_path_included(f, included_paths))
            ]
        else:
            # Recursively find all .sh files and filter by include patterns
            shell_files = [
                str(path)
                for path in REPO_ROOT.rglob("*.sh")
                if path.is_file()
                and (
                    not included_paths
                    or is_path_included(str(path.relative_to(REPO_ROOT)), included_paths)
                )
            ]

        if not shell_files:
            print("No shell scripts to check with shellcheck")
            return LinterResult(success=True)

        # Run shellcheck with JSON output format
        result = subprocess.run(
            [shellcheck_exe, "--format=json", *shell_files],
            capture_output=True,
            text=True,
        )

        # Parse errors from JSON output
        errors = _parse_shellcheck_json(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
