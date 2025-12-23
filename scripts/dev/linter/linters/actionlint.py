"""Actionlint GitHub Actions workflow linter."""

from pathlib import Path

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    get_executable,
    is_path_included,
    load_yaml_config,
    run_checked,
)

ACTIONLINT_CLI_REQUIRED = "actionlint CLI required to run lint"
LINT_ACTIONLINT_CONFIG = REPO_ROOT / ".lint.actionlint.yaml"


class ActionlintLinter(BaseLinter):
    """Run actionlint on GitHub Actions workflow files."""

    name = "actionlint"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run actionlint on GitHub Actions workflow files.

        Args:
            files: Optional list of files to check. If None, checks all workflow files.

        Returns:
            LinterResult indicating success/failure.
        """
        actionlint_exe = get_executable("actionlint", ACTIONLINT_CLI_REQUIRED)
        config = load_yaml_config(LINT_ACTIONLINT_CONFIG)
        ignore_patterns: list[str] = config.get("ignore", [])
        included_paths = config.get("included_paths", [])
        excludes = config.get("excludes", [])
        glob_patterns = included_paths + excludes

        workflows_dir = REPO_ROOT / ".github" / "workflows"

        if files is not None:
            # Filter to only workflow YAML files that match glob patterns
            workflow_files = [
                f
                for f in files
                if (f.endswith(".yml") or f.endswith(".yaml"))
                and is_path_included(f, glob_patterns)
            ]
            if not workflow_files:
                print("No GitHub Actions workflow files to check with actionlint")
                return LinterResult(success=True)
            targets = workflow_files
        else:
            if not workflows_dir.exists():
                print("No .github/workflows/ directory found for actionlint scan")
                return LinterResult(success=True)
            # Enumerate workflow files, respecting glob patterns
            workflow_files = [
                path
                for path in workflows_dir.rglob("*.yml")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), glob_patterns)
            ]
            workflow_files.extend(
                path
                for path in workflows_dir.rglob("*.yaml")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), glob_patterns)
            )
            if not workflow_files:
                print("No workflow files found for actionlint scan")
                return LinterResult(success=True)
            targets = [str(path) for path in workflow_files]

        cmd = [actionlint_exe]
        for pattern in ignore_patterns:
            cmd.extend(["-ignore", pattern])
        cmd.extend(targets)

        run_checked(cmd)
        return LinterResult(success=True)
