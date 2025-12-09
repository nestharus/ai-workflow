"""Pymarkdown Markdown linter."""

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    get_executable,
    load_yaml_config,
    run_checked,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
LINT_PYMARKDOWN_CONFIG = REPO_ROOT / ".lint.pymarkdown.yaml"


class PymarkdownLinter(BaseLinter):
    """Run pymarkdown on Markdown files."""

    name = "pymarkdown"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run pymarkdown on Markdown files.

        Args:
            files: Optional list of files to check. If None, checks configured targets.

        Returns:
            LinterResult indicating success/failure.
        """
        uv_exe = get_executable("uv", UV_CLI_REQUIRED)
        config = load_yaml_config(LINT_PYMARKDOWN_CONFIG)
        excludes = config.get("excludes", [])

        if files is not None:
            md_files = [f for f in files if f.endswith(".md")]
            if not md_files:
                print("No Markdown files to check with pymarkdown")
                return LinterResult(success=True)
            targets = md_files
            pymarkdown_cmd = [
                uv_exe,
                "run",
                "pymarkdown",
                "-c",
                str(REPO_ROOT / ".pymarkdown.json"),
                "scan",
                *targets,
            ]
        else:
            targets = config.get("targets", [])
            pymarkdown_cmd = [
                uv_exe,
                "run",
                "pymarkdown",
                "-c",
                str(REPO_ROOT / ".pymarkdown.json"),
                "scan",
                "-r",
                *targets,
            ]

        for pattern in excludes:
            pymarkdown_cmd.extend(["-e", pattern])

        run_checked(pymarkdown_cmd)
        return LinterResult(success=True)
