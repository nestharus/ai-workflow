"""Gitleaks linter for scanning secrets.

CLI Contract (v8.19.0+):
-------------------------
The gitleaks CLI underwent a major change in v8.19.0 that deprecated `detect` and
`protect` commands in favor of `git`, `dir`, and `stdin`. This implementation relies
on the following documented behavior:

- Primary command for full repo scans: `gitleaks dir --config .gitleaks.toml .`
  - The `dir` command (aliases: `files`, `directory`) scans directories and files
    without git history
  - Automatically uses `.gitleaks.toml` from repo root when present
  - Works reliably in both git and non-git directories

- Primary command for file-filtered scans:
  `gitleaks dir --config .gitleaks.toml <file1> <file2> ...`
  - Pass specific files as positional arguments after the config flag
  - Does NOT require `--no-git` flag (that flag does not exist in v8.19.0+)
  - The `dir` command naturally operates on filesystem paths without git awareness

- Exit codes (documented behavior):
  - 0 = No leaks present (success)
  - 1 = Leaks found OR error encountered (failure)
  - 126 = Unknown flag (configuration error)

Version compatibility:
- This implementation requires gitleaks v8.19.0 or later
- The `detect` command was deprecated in v8.19.0; do not use it
- If upgrading gitleaks, verify exit code behavior has not changed
"""

import subprocess
import sys
from pathlib import Path

from scripts.dev.linter.base import (
    REPO_ROOT,
    BaseLinter,
    LinterResult,
    get_executable,
    is_path_excluded,
    load_yaml_config,
)

GITLEAKS_CLI_NOT_FOUND = (
    "gitleaks CLI not found. Install with: brew install gitleaks (macOS/Linux) "
    "or go install github.com/gitleaks/gitleaks/v8@v8.24.2"
)
GITLEAKS_CONFIG_MISSING = (
    ".gitleaks.toml not found in repository root. "
    "This config file is required for consistent secret detection rules. "
    "Create the file or restore it from version control."
)
GITLEAKS_CONFIG_UNREADABLE = (
    ".gitleaks.toml exists but cannot be read (permission denied). "
    "Check file permissions and ensure it is readable."
)
LINT_GITLEAKS_CONFIG = REPO_ROOT / ".lint.gitleaks.yaml"
GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"


class GitleaksLinter(BaseLinter):
    """Run gitleaks to scan for secrets."""

    name = "gitleaks"
    supports_file_filtering = True

    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run gitleaks secret scanner.

        Args:
            files: Optional list of files to scan. If None, scans all files.

        Returns:
            LinterResult indicating success/failure.
        """
        # Locate gitleaks binary
        try:
            gitleaks_bin = get_executable("gitleaks", GITLEAKS_CLI_NOT_FOUND)
        except RuntimeError:
            # Binary not found - print message and return failure
            print(GITLEAKS_CLI_NOT_FOUND, file=sys.stderr)
            return LinterResult(success=False, message=GITLEAKS_CLI_NOT_FOUND)

        # Verify .gitleaks.toml config exists and is readable
        if not GITLEAKS_CONFIG.exists():
            print(GITLEAKS_CONFIG_MISSING, file=sys.stderr)
            return LinterResult(success=False, message=GITLEAKS_CONFIG_MISSING)

        try:
            # Attempt to read the config to verify permissions
            GITLEAKS_CONFIG.read_text()
        except PermissionError:
            print(GITLEAKS_CONFIG_UNREADABLE, file=sys.stderr)
            return LinterResult(success=False, message=GITLEAKS_CONFIG_UNREADABLE)

        # Build base command with config
        cmd = [gitleaks_bin, "dir", "--config", str(GITLEAKS_CONFIG)]

        if files is not None:
            # Load exclusion config from .lint.gitleaks.yaml (optional, defaults to empty)
            config = load_yaml_config(LINT_GITLEAKS_CONFIG) if LINT_GITLEAKS_CONFIG.exists() else {}
            excluded_extensions = set(config.get("excluded_extensions", []))
            excluded_names = set(config.get("excluded_names", []))
            excluded_dirs = {REPO_ROOT / d for d in config.get("excluded_dirs", [])}

            scannable_files = []
            for f in files:
                file_path = Path(f)
                # Check extension exclusion
                if any(f.endswith(ext) for ext in excluded_extensions):
                    continue
                # Check name exclusion
                if file_path.name in excluded_names:
                    continue
                # Check directory exclusion
                if is_path_excluded(REPO_ROOT / f, excluded_dirs):
                    continue
                scannable_files.append(f)

            if not scannable_files:
                print("No scannable files for gitleaks")
                return LinterResult(success=True)

            # Add files to scan
            cmd.extend(scannable_files)
        else:
            # Scan entire repo directory
            cmd.append(".")

        # Run gitleaks
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        except FileNotFoundError:
            # Binary was found but execution failed (race condition or path issue)
            print(GITLEAKS_CLI_NOT_FOUND, file=sys.stderr)
            return LinterResult(success=False, message=GITLEAKS_CLI_NOT_FOUND)

        # Handle exit codes
        if result.returncode == 0:
            return LinterResult(success=True)
        elif result.returncode == 1:
            # Print output for user to see what was found
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return LinterResult(
                success=False,
                message="gitleaks found potential secrets",
            )
        elif result.returncode == 126:
            msg = "gitleaks configuration error: unknown flag"
            print(msg, file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return LinterResult(success=False, message=msg)
        else:
            msg = (
                f"gitleaks failed with unexpected exit code {result.returncode}. "
                "Check gitleaks version compatibility (requires v8.19.0+)."
            )
            print(msg, file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return LinterResult(success=False, message=msg)
