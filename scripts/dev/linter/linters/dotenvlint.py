"""Dotenv-linter for .env files."""

from pathlib import Path

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    get_executable,
    is_path_excluded,
    load_yaml_config,
    run_checked,
)

DOTENV_LINTER_CLI_REQUIRED = "dotenv-linter CLI required to run lint"
LINT_DOTENVLINT_CONFIG = REPO_ROOT / ".lint.dotenvlint.yaml"


class DotenvlintLinter(BaseLinter):
    """Run dotenv-linter on .env files."""

    name = "dotenvlint"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run dotenv-linter on .env files.

        Args:
            files: Optional list of files to check. If None, checks configured targets.

        Returns:
            LinterResult indicating success/failure.
        """
        dotenv_linter_exe = get_executable("dotenv-linter", DOTENV_LINTER_CLI_REQUIRED)
        config = load_yaml_config(LINT_DOTENVLINT_CONFIG)
        exclude_dirs = {REPO_ROOT / d for d in config.get("exclude_dirs", [])}

        if files:
            # Filter to only .env files
            env_files = [f for f in files if Path(f).name.startswith(".env")]
            if not env_files:
                print("No .env files to check with dotenv-linter")
                return LinterResult(success=True)
            targets = env_files
        else:
            # Find all .env files based on configured targets
            targets_config = config.get("targets", [".env", ".env.*"])
            exclude_patterns = config.get("exclude_patterns", [])
            env_files = []
            for pattern in targets_config:
                for path in REPO_ROOT.glob(pattern):
                    if path.is_file() and not is_path_excluded(path, exclude_dirs):
                        # Check exclude patterns
                        excluded = any(path.match(ep) for ep in exclude_patterns)
                        if not excluded:
                            env_files.append(str(path))
            targets = env_files

        if not targets:
            print("No .env files found for dotenv-linter scan")
        else:
            run_checked([dotenv_linter_exe, "check", *targets])

        return LinterResult(success=True)
