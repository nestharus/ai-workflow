"""Ruff linter for Python formatting and linting."""

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    filter_files_with_config,
    get_executable,
    run_checked,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
LINT_RUFF_CONFIG = REPO_ROOT / ".lint.ruff.yaml"


class RuffLinter(BaseLinter):
    """Run ruff format and check."""

    name = "ruff"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run ruff format and check.

        Args:
            files: Optional list of files to lint. If None, lints entire repo.

        Returns:
            LinterResult indicating success/failure.
        """
        uv_exe = get_executable("uv", UV_CLI_REQUIRED)

        if files is None:
            targets = ["."]
        else:
            py_files = [f for f in files if f.endswith(".py")]
            if not py_files:
                print("No Python files to lint with ruff")
                return LinterResult(success=True)

            # Apply included_paths filter from config
            py_files, error = filter_files_with_config(py_files, LINT_RUFF_CONFIG, "ruff")
            if error is not None:
                return error
            if not py_files:
                return LinterResult(success=True)

            targets = py_files

        run_checked([uv_exe, "run", "ruff", "format", *targets])
        run_checked([uv_exe, "run", "ruff", "check", "--fix", *targets])
        return LinterResult(success=True)
