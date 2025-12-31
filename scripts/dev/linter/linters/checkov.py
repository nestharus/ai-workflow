"""Checkov OpenAPI security linter."""

import json
import subprocess
import sys

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
OPENAPI_SCHEMA = REPO_ROOT / "openapi" / "openapi.json"
CHECKOV_CONFIG = REPO_ROOT / ".checkov.yaml"


def _parse_checkov_json(json_output: str) -> list[LintError]:
    """Parse checkov JSON output into LintError objects.

    Args:
        json_output: Raw JSON string from checkov --output json.

    Returns:
        List of LintError objects.
    """
    if not json_output.strip():
        return []

    try:
        data = json.loads(json_output)
    except json.JSONDecodeError:
        return []

    failed_checks = data.get("results", {}).get("failed_checks", [])
    errors = []

    for check in failed_checks:
        # Extract file path (prefer file_abs_path, fallback to file_path)
        file_path = check.get("file_abs_path") or check.get("file_path", "")

        # Extract line range (first line of the failure)
        file_line_range = check.get("file_line_range", [0, 0])
        line = file_line_range[0] if file_line_range else 0

        # Extract check information
        check_id = check.get("check_id", "")
        check_name = check.get("check_name", "")

        # Build context from code_block if available
        code_block = check.get("code_block", [])
        context_lines = []
        if code_block:
            # code_block is a list of [line_num, line_text] pairs
            for line_num, line_text in code_block[:10]:  # Limit to first 10 lines
                context_lines.append(f"{line_num}: {line_text.rstrip()}")
        context = "\n".join(context_lines) if context_lines else None

        # Build message with guideline link if available
        message = check_name
        guideline = check.get("guideline")
        if guideline:
            message = f"{check_name}\nGuideline: {guideline}"

        errors.append(
            LintError(
                file=file_path,
                line=line,
                column=0,  # checkov doesn't provide column information
                code=check_id,
                message=message,
                context=context,
                fix_available=False,  # checkov doesn't provide auto-fix
                fix_message=None,
            )
        )

    return errors


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
            LinterResult indicating success/failure with structured errors.
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

        # Run checkov with JSON output
        result = subprocess.run(
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
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
        )

        # Parse errors from JSON output
        errors = _parse_checkov_json(result.stdout)

        if errors:
            return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
