"""Detect-secrets linter for scanning secrets."""

import sys
from pathlib import Path

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    get_executable,
    load_yaml_config,
    run_checked,
)

UV_CLI_REQUIRED = "uv CLI required to run lint"
SECRETS_BASELINE = REPO_ROOT / ".secrets.baseline"
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
            # Load exclusion config from .lint.detect-secrets.yaml
            config = load_yaml_config(LINT_DETECT_SECRETS_CONFIG)
            excluded_extensions = set(config.get("excluded_extensions", []))
            excluded_names = set(config.get("excluded_names", []))

            scannable_files = [
                f
                for f in files
                if not any(f.endswith(ext) for ext in excluded_extensions)
                and Path(f).name not in excluded_names
            ]

            if not scannable_files:
                print("No scannable files for detect-secrets")
                return LinterResult(success=True)

            # Use detect-secrets-hook for file-based scanning
            run_checked(
                [
                    uv_exe,
                    "run",
                    "detect-secrets-hook",
                    "--baseline",
                    str(SECRETS_BASELINE),
                    *scannable_files,
                ]
            )
        else:
            # Scan all files and compare against baseline
            run_checked(
                [
                    uv_exe,
                    "run",
                    "detect-secrets",
                    "scan",
                    "--baseline",
                    str(SECRETS_BASELINE),
                ]
            )

        return LinterResult(success=True)
