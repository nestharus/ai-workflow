"""Hadolint Dockerfile linter."""

from pathlib import Path

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    get_executable,
    load_yaml_config,
    run_checked,
)

HADOLINT_CLI_REQUIRED = "hadolint CLI required to run lint"
HADOLINT_CONFIG = REPO_ROOT / ".hadolint.yaml"
LINT_HADOLINT_CONFIG = REPO_ROOT / ".lint.hadolint.yaml"


class HadolintLinter(BaseLinter):
    """Run hadolint on Dockerfiles."""

    name = "hadolint"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run hadolint on Dockerfiles.

        Args:
            files: Optional list of files to check. If None, checks all Dockerfiles.

        Returns:
            LinterResult indicating success/failure.
        """
        hadolint_exe = get_executable("hadolint", HADOLINT_CLI_REQUIRED)
        config = load_yaml_config(LINT_HADOLINT_CONFIG)
        exclude_dirs = {REPO_ROOT / d for d in config.get("exclude_dirs", [])}

        if files is not None:
            # Filter to only Dockerfile files
            dockerfiles = [Path(f) for f in files if Path(f).name == "Dockerfile"]
        else:
            dockerfiles = [
                path
                for path in REPO_ROOT.rglob("Dockerfile")
                if path.is_file() and not any(excluded in path.parents for excluded in exclude_dirs)
            ]

        if not dockerfiles:
            print("No Dockerfiles found for hadolint scan")
        else:
            run_checked(
                [
                    hadolint_exe,
                    "--config",
                    str(HADOLINT_CONFIG),
                    *[str(path) for path in dockerfiles],
                ]
            )

        return LinterResult(success=True)
