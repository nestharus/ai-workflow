"""Yamllint YAML linter."""

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

UV_CLI_REQUIRED = "uv CLI required to run lint"
YAMLLINT_CONFIG = REPO_ROOT / ".yamllint"
LINT_YAMLLINT_CONFIG = REPO_ROOT / ".lint.yamllint.yaml"


class YamllintLinter(BaseLinter):
    """Run yamllint on YAML files."""

    name = "yamllint"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run yamllint on YAML files.

        Args:
            files: Optional list of files to check. If None, checks all YAML files.

        Returns:
            LinterResult indicating success/failure.
        """
        yamllint_exe = get_executable("yamllint", UV_CLI_REQUIRED)
        config = load_yaml_config(LINT_YAMLLINT_CONFIG)
        included_paths = config.get("included_paths", [])
        excludes = config.get("excludes", [])
        glob_patterns = included_paths + excludes

        if files is not None:
            # Filter to YAML files that match glob patterns
            yaml_files = [
                Path(f)
                for f in files
                if (f.endswith(".yaml") or f.endswith(".yml"))
                and is_path_included(f, glob_patterns)
            ]
        else:
            # Find all YAML files and filter by glob patterns
            yaml_files = [
                path
                for path in REPO_ROOT.rglob("*.yaml")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), glob_patterns)
            ]
            # Also check .yml files
            yaml_files.extend(
                path
                for path in REPO_ROOT.rglob("*.yml")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), glob_patterns)
            )

        if not yaml_files:
            print("No YAML files found for yamllint scan")
        else:
            run_checked(
                [
                    yamllint_exe,
                    "-c",
                    str(YAMLLINT_CONFIG),
                    *[str(path) for path in yaml_files],
                ]
            )

        return LinterResult(success=True)
