"""Mypy type checker linter."""

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    filter_files_with_config,
    get_executable,
    run_checked,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
LINT_MYPY_CONFIG = REPO_ROOT / ".lint.mypy.yaml"


class MypyLinter(BaseLinter):
    """Run mypy type checking."""

    name = "mypy"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run mypy type checking.

        Args:
            files: Optional list of files to check. If None, checks entire repo.

        Returns:
            LinterResult indicating success/failure.
        """
        uv_exe = get_executable("uv", UV_CLI_REQUIRED)

        if files is not None:
            py_files = [f for f in files if f.endswith(".py")]
            if not py_files:
                print("No Python files to check with mypy")
                return LinterResult(success=True)

            # Apply included_paths filter from config
            py_files, error = filter_files_with_config(py_files, LINT_MYPY_CONFIG, "mypy")
            if error is not None:
                return error
            if not py_files:
                return LinterResult(success=True)

            run_checked([uv_exe, "run", "mypy", *py_files])
        else:
            run_checked([uv_exe, "run", "mypy"])

        return LinterResult(success=True)
