"""Yamllint YAML linter."""

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    get_executable,
    is_path_excluded,
    load_yaml_config,
    run_checked,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
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
        uv_exe = get_executable("uv", UV_CLI_REQUIRED)
        config = load_yaml_config(LINT_YAMLLINT_CONFIG)
        exclude_dirs = {REPO_ROOT / d for d in config.get("exclude_dirs", [])}

        if files is not None:
            yaml_files = [f for f in files if f.endswith(".yml") or f.endswith(".yaml")]
            if not yaml_files:
                print("No YAML files to check with yamllint")
                return LinterResult(success=True)
        else:
            yaml_files = [
                str(path)
                for path in REPO_ROOT.rglob("*.yml")
                if path.is_file() and not is_path_excluded(path, exclude_dirs)
            ]
            yaml_files.extend(
                str(path)
                for path in REPO_ROOT.rglob("*.yaml")
                if path.is_file() and not is_path_excluded(path, exclude_dirs)
            )

        if yaml_files:
            yamllint_config = str(REPO_ROOT / ".yamllint.yaml")
            run_checked([uv_exe, "run", "yamllint", "-c", yamllint_config, *yaml_files])

        return LinterResult(success=True)
