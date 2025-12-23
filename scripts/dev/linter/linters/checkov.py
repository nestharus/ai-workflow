"""Checkov OpenAPI security linter."""

import sys

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    get_executable,
    run_checked,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
OPENAPI_SCHEMA = REPO_ROOT / "openapi" / "openapi.json"
CHECKOV_CONFIG = REPO_ROOT / ".checkov.yaml"


class CheckovLinter(BaseLinter):
    """Run checkov on OpenAPI schema."""

    name = "checkov"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run checkov on OpenAPI schema.

        Args:
            files: Optional list of files to filter. Only runs if any openapi.json
                   file is in the files list.

        Returns:
            LinterResult indicating success/failure.
        """
        # If files are specified, only run if any openapi.json file is in the list
        if files is not None:
            has_openapi = any(f.endswith("openapi.json") for f in files)
            if not has_openapi:
                print("No openapi.json file in changed files, skipping checkov linter.")
                return LinterResult(success=True)

        if not OPENAPI_SCHEMA.exists():
            print(
                f"OpenAPI schema missing at {OPENAPI_SCHEMA}. Run `uv run app.api.generate` first.",
                file=sys.stderr,
            )
            return LinterResult(success=False)

        uv_exe = get_executable("uv", UV_CLI_REQUIRED)
        run_checked(
            [
                uv_exe,
                "run",
                "checkov",
                "--config-file",
                str(CHECKOV_CONFIG),
                "--framework",
                "openapi",
                "-f",
                str(OPENAPI_SCHEMA),
            ]
        )
        return LinterResult(success=True)
