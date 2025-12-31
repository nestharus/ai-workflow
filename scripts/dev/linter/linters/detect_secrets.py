"""Detect-secrets linter for scanning secrets."""

import json
import subprocess
import sys
from pathlib import Path

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    LintError,
    get_executable,
    is_path_included,
    load_yaml_config,
)

# Exit code 3 means baseline was updated (line numbers changed, no new secrets)
EXIT_CODE_BASELINE_UPDATED = 3

UV_CLI_REQUIRED = "uv CLI required to run lint"
SECRETS_BASELINE = REPO_ROOT / ".secrets.baseline"
# Relative path for detect-secrets to avoid machine-specific absolute paths in baseline
SECRETS_BASELINE_RELATIVE = ".secrets.baseline"
LINT_DETECT_SECRETS_CONFIG = REPO_ROOT / ".lint.detect-secrets.yaml"


def _parse_detect_secrets_json(json_output: str) -> list[LintError]:
    """Parse detect-secrets JSON output into LintError objects.

    Args:
        json_output: Raw JSON string from detect-secrets-hook --json.

    Returns:
        List of LintError objects.
    """
    if not json_output.strip():
        return []

    try:
        data = json.loads(json_output)
    except json.JSONDecodeError:
        return []

    results = data.get("results", {})
    errors = []

    for filename, secrets in results.items():
        for secret in secrets:
            errors.append(
                LintError(
                    file=secret.get("filename", filename),
                    line=secret.get("line_number", 0),
                    column=0,  # detect-secrets doesn't provide column info
                    code=secret.get("type", "secret-detected"),
                    message=f"Potential secret detected: {secret.get('type', 'Unknown type')}",
                    context=None,  # detect-secrets JSON doesn't include context
                    fix_available=False,
                    fix_message=None,
                )
            )

    return errors


class DetectSecretsLinter(BaseLinter):
    """Run detect-secrets to scan for secrets."""

    name = "detect-secrets"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run detect-secrets to scan for secrets.

        Args:
            files: Optional list of files to scan. If None, scans all tracked files.

        Returns:
            LinterResult indicating success/failure.
        """
        if not SECRETS_BASELINE.exists():
            print(
                f"Secrets baseline missing at {SECRETS_BASELINE}. "
                "Run `uv run detect-secrets scan > .secrets.baseline` first.",
                file=sys.stderr,
            )
            return LinterResult(success=False)

        uv_exe = get_executable("uv", UV_CLI_REQUIRED)

        if files is not None:
            # Load config from .lint.detect-secrets.yaml
            config = load_yaml_config(LINT_DETECT_SECRETS_CONFIG)
            excluded_extensions = set(config.get("excluded_extensions", []))
            excluded_names = set(config.get("excluded_names", []))
            included_paths = config.get("included_paths", [])

            scannable_files = [
                f
                for f in files
                # Check inclusion via glob patterns
                if (not included_paths or is_path_included(f, included_paths))
                # Check extension exclusion
                and not any(f.endswith(ext) for ext in excluded_extensions)
                # Check name exclusion
                and Path(f).name not in excluded_names
            ]

            if not scannable_files:
                print("No scannable files for detect-secrets")
                return LinterResult(success=True)

            # Use detect-secrets-hook for file-based scanning with JSON output
            # Handle exit code 3 (baseline updated) as success - it just means
            # line numbers changed, not that new secrets were found
            result = subprocess.run(
                [
                    uv_exe,
                    "run",
                    "detect-secrets-hook",
                    "--json",
                    "--baseline",
                    str(SECRETS_BASELINE),
                    *scannable_files,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            # Parse errors from JSON output
            errors = _parse_detect_secrets_json(result.stdout)

            if result.returncode == EXIT_CODE_BASELINE_UPDATED:
                print(
                    "Note: .secrets.baseline was updated (line numbers changed). "
                    "Please commit the updated baseline.",
                    file=sys.stderr,
                )
                # Return success even if errors were parsed, as this is just a baseline update
                return LinterResult(success=True, errors=errors)
            elif result.returncode != 0:
                # If no structured errors were parsed but command failed,
                # create an error from stderr (e.g., Python compatibility issues)
                if not errors and result.stderr:
                    # Extract first meaningful line from traceback or error
                    stderr_lines = result.stderr.strip().splitlines()
                    error_msg = stderr_lines[-1] if stderr_lines else "Unknown error"
                    errors = [
                        LintError(
                            file=".secrets.baseline",
                            line=0,
                            column=0,
                            code="detect-secrets-error",
                            message=f"detect-secrets failed: {error_msg}",
                            fix_available=False,
                        )
                    ]
                return LinterResult(success=False, errors=errors)
        else:
            # Whole-repo scan: get all git-tracked files and use detect-secrets-hook
            try:
                git_result = subprocess.run(
                    ["git", "ls-files"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                all_files = [f.strip() for f in git_result.stdout.splitlines() if f.strip()]
            except subprocess.CalledProcessError:
                print("Failed to get git-tracked files", file=sys.stderr)
                return LinterResult(success=False)

            if not all_files:
                print("No files to scan")
                return LinterResult(success=True)

            # Apply config filters to all files
            config = load_yaml_config(LINT_DETECT_SECRETS_CONFIG)
            excluded_extensions = set(config.get("excluded_extensions", []))
            excluded_names = set(config.get("excluded_names", []))
            included_paths = config.get("included_paths", [])

            scannable_files = [
                f
                for f in all_files
                # Check inclusion via glob patterns
                if (not included_paths or is_path_included(f, included_paths))
                # Check extension exclusion
                and not any(f.endswith(ext) for ext in excluded_extensions)
                # Check name exclusion
                and Path(f).name not in excluded_names
            ]

            if not scannable_files:
                print("No scannable files for detect-secrets")
                return LinterResult(success=True)

            # Use detect-secrets-hook with JSON output for whole-repo scan
            result = subprocess.run(
                [
                    uv_exe,
                    "run",
                    "detect-secrets-hook",
                    "--json",
                    "--baseline",
                    str(SECRETS_BASELINE),
                    *scannable_files,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            # Parse errors from JSON output
            errors = _parse_detect_secrets_json(result.stdout)

            if result.returncode == EXIT_CODE_BASELINE_UPDATED:
                print(
                    "Note: .secrets.baseline was updated (line numbers changed). "
                    "Please commit the updated baseline.",
                    file=sys.stderr,
                )
                return LinterResult(success=True, errors=errors)
            elif result.returncode != 0:
                # If no structured errors were parsed but command failed,
                # create an error from stderr (e.g., Python compatibility issues)
                if not errors and result.stderr:
                    # Extract first meaningful line from traceback or error
                    stderr_lines = result.stderr.strip().splitlines()
                    error_msg = stderr_lines[-1] if stderr_lines else "Unknown error"
                    errors = [
                        LintError(
                            file=".secrets.baseline",
                            line=0,
                            column=0,
                            code="detect-secrets-error",
                            message=f"detect-secrets failed: {error_msg}",
                            fix_available=False,
                        )
                    ]
                return LinterResult(success=False, errors=errors)

        return LinterResult(success=True)
