"""Ruff linter for Python formatting and linting."""

from scripts.dev.linter.base import (
    BaseLinter,
    LinterResult,
    get_executable,
    run_checked,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"


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
        targets = files if files is not None else ["."]

        # Filter to only Python files if files are specified
        if files is not None:
            py_files = [f for f in files if f.endswith(".py")]
            if not py_files:
                print("No Python files to lint with ruff")
                return LinterResult(success=True)
            targets = py_files

        run_checked([uv_exe, "run", "ruff", "format", *targets])
        run_checked([uv_exe, "run", "ruff", "check", "--fix", *targets])
        return LinterResult(success=True)
