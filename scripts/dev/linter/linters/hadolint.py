"""Hadolint Dockerfile linter."""

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
        included_paths = config.get("included_paths", [])
        excludes = config.get("excludes", [])
        glob_patterns = included_paths + excludes

        if files is not None:
            # Filter to only Dockerfile files that match glob patterns
            dockerfiles = [
                Path(f)
                for f in files
                if Path(f).name == "Dockerfile"
                and is_path_included(f, glob_patterns)
            ]
        else:
            # Find all Dockerfiles and filter by glob patterns
            dockerfiles = [
                path
                for path in REPO_ROOT.rglob("Dockerfile")
                if path.is_file()
                and is_path_included(str(path.relative_to(REPO_ROOT)), glob_patterns)
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
