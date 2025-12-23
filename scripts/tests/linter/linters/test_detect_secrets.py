"""Tests for scripts/dev/linter/linters/detect_secrets.py - run function branches."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.dev.linter.linters.detect_secrets import DetectSecretsLinter


class TestDetectSecretsLinterRun:
    """Tests for DetectSecretsLinter.run method covering branches."""

    def test_returns_failure_when_baseline_missing(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns failure when secrets baseline is missing (lines 37-43)."""
        linter = DetectSecretsLinter()

        with (
            patch(
                "scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE",
                tmp_path / "missing.baseline",
            ),
        ):
            result = linter.run()

            assert result.success is False
            captured = capsys.readouterr()
            assert "Secrets baseline missing" in captured.err
            assert "detect-secrets scan" in captured.err

    def test_runs_scan_when_no_files_specified(self, tmp_path: Path) -> None:
        """Test run executes scan against baseline when no files (lines 75-88)."""
        linter = DetectSecretsLinter()

        # Create baseline file
        baseline_file = tmp_path / ".secrets.baseline"
        baseline_file.write_text("{}")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE", baseline_file),
            patch("scripts.dev.linter.linters.detect_secrets.REPO_ROOT", tmp_path),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.detect_secrets.run_checked") as mock_run,
        ):
            result = linter.run()

            assert result.success is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "detect-secrets" in call_args
            assert "scan" in call_args
            assert "--baseline" in call_args

    def test_returns_success_when_no_scannable_files(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Test run returns success when all files are excluded (lines 60-62)."""
        linter = DetectSecretsLinter()

        # Create baseline file
        baseline_file = tmp_path / ".secrets.baseline"
        baseline_file.write_text("{}")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE", baseline_file),
            patch(
                "scripts.dev.linter.linters.detect_secrets.load_yaml_config",
                return_value={
                    "excluded_extensions": [".lock", ".png"],
                    "excluded_names": ["package-lock.json"],
                },
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
        ):
            # Pass only excluded files
            result = linter.run(files=["uv.lock", "image.png", "package-lock.json"])

            assert result.success is True
            captured = capsys.readouterr()
            assert "No scannable files" in captured.out

    def test_runs_hook_for_specified_files(self, tmp_path: Path) -> None:
        """Test run executes detect-secrets-hook for specified files (lines 64-74)."""
        linter = DetectSecretsLinter()

        # Create baseline file
        baseline_file = tmp_path / ".secrets.baseline"
        baseline_file.write_text("{}")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE", baseline_file),
            patch(
                "scripts.dev.linter.linters.detect_secrets.load_yaml_config",
                return_value={"excluded_extensions": [], "excluded_names": []},
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.detect_secrets.run_checked") as mock_run,
        ):
            result = linter.run(files=["src/main.py", "config.json"])

            assert result.success is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "detect-secrets-hook" in call_args
            assert "--baseline" in call_args
            assert "src/main.py" in call_args
            assert "config.json" in call_args

    def test_filters_excluded_extensions(self, tmp_path: Path) -> None:
        """Test run filters files with excluded extensions (lines 53-58)."""
        linter = DetectSecretsLinter()

        # Create baseline file
        baseline_file = tmp_path / ".secrets.baseline"
        baseline_file.write_text("{}")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE", baseline_file),
            patch(
                "scripts.dev.linter.linters.detect_secrets.load_yaml_config",
                return_value={"excluded_extensions": [".lock"], "excluded_names": []},
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.detect_secrets.run_checked") as mock_run,
        ):
            # Mix of scannable and excluded files
            result = linter.run(files=["src/main.py", "uv.lock", "config.json"])

            assert result.success is True
            call_args = mock_run.call_args[0][0]
            assert "src/main.py" in call_args
            assert "config.json" in call_args
            assert "uv.lock" not in call_args

    def test_filters_excluded_names(self, tmp_path: Path) -> None:
        """Test run filters files with excluded names (line 57)."""
        linter = DetectSecretsLinter()

        # Create baseline file
        baseline_file = tmp_path / ".secrets.baseline"
        baseline_file.write_text("{}")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE", baseline_file),
            patch(
                "scripts.dev.linter.linters.detect_secrets.load_yaml_config",
                return_value={"excluded_extensions": [], "excluded_names": ["secrets.json"]},
            ),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.detect_secrets.run_checked") as mock_run,
        ):
            result = linter.run(files=["src/main.py", "secrets.json"])

            assert result.success is True
            call_args = mock_run.call_args[0][0]
            assert "src/main.py" in call_args
            assert "secrets.json" not in call_args

    def test_uses_relative_baseline_path(self, tmp_path: Path) -> None:
        """Test run uses relative baseline path for full scan (line 85)."""
        linter = DetectSecretsLinter()

        # Create baseline file
        baseline_file = tmp_path / ".secrets.baseline"
        baseline_file.write_text("{}")

        with (
            patch("scripts.dev.linter.linters.detect_secrets.SECRETS_BASELINE", baseline_file),
            patch("scripts.dev.linter.linters.detect_secrets.REPO_ROOT", tmp_path),
            patch(
                "scripts.dev.linter.linters.detect_secrets.get_executable",
                return_value="/usr/bin/uv",
            ),
            patch("scripts.dev.linter.linters.detect_secrets.run_checked") as mock_run,
        ):
            result = linter.run()

            assert result.success is True
            # Check cwd was set
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs.get("cwd") == tmp_path
            # Check relative path was used
            call_args = mock_run.call_args[0][0]
            assert ".secrets.baseline" in call_args
