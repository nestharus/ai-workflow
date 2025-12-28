"""Detect-secrets linter for scanning secrets."""

import subprocess
import sys
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

# Exit code 3 means baseline was updated (line numbers changed, no new secrets)
EXIT_CODE_BASELINE_UPDATED = 3

UV_CLI_REQUIRED = "uv CLI required to run lint"
SECRETS_BASELINE = REPO_ROOT / ".secrets.baseline"
# Relative path for detect-secrets to avoid machine-specific absolute paths in baseline
SECRETS_BASELINE_RELATIVE = ".secrets.baseline"
LINT_DETECT_SECRETS_CONFIG = REPO_ROOT / ".lint.detect-secrets.yaml"


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

            # Use detect-secrets-hook for file-based scanning
            # Handle exit code 3 (baseline updated) as success - it just means
            # line numbers changed, not that new secrets were found
            result = subprocess.run(
                [
                    uv_exe,
                    "run",
                    "detect-secrets-hook",
                    "--baseline",
                    str(SECRETS_BASELINE),
                    *scannable_files,
                ],
                check=False,
            )
            if result.returncode == EXIT_CODE_BASELINE_UPDATED:
                print(
                    "Note: .secrets.baseline was updated (line numbers changed). "
                    "Please commit the updated baseline.",
                    file=sys.stderr,
                )
            elif result.returncode != 0:
                return LinterResult(success=False)
        else:
            # Scan all files and compare against baseline
            # Use relative path and cwd to avoid machine-specific paths in baseline
            run_checked(
                [
                    uv_exe,
                    "run",
                    "detect-secrets",
                    "scan",
                    "--baseline",
                    SECRETS_BASELINE_RELATIVE,
                ],
                cwd=REPO_ROOT,
            )

        return LinterResult(success=True)
