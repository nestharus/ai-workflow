"""Mypy type checker linter."""

from scripts.dev.linter.base import (
    BaseLinter,
    LinterResult,
    get_executable,
    run_checked,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"


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
            # Filter out common test directories to avoid unnecessary mypy runs.
            # This is a performance optimization; mypy applies its full exclude rules
            # regardless.
            filtered_files = [
                f
                for f in py_files
                if not (f.startswith("tests/") or f.startswith("scripts/tests/"))
            ]
            if not filtered_files:
                print("All Python files are excluded from mypy checking")
                return LinterResult(success=True)
            run_checked([uv_exe, "run", "mypy", *filtered_files])
        else:
            run_checked([uv_exe, "run", "mypy"])

        return LinterResult(success=True)
