"""Tests for scripts.dev.linter.linters.gitleaks module."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.gitleaks import (
    GITLEAKS_CLI_NOT_FOUND,
    GITLEAKS_CONFIG_MISSING,
    GITLEAKS_CONFIG_UNREADABLE,
    GITLEAKS_TIMEOUT_MSG,
    GitleaksLinter,
)


class TestGitleaksLinterInit:
    """Tests for GitleaksLinter class attributes."""

    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = GitleaksLinter()
        assert linter.name == "gitleaks"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = GitleaksLinter()
        assert linter.supports_file_filtering is True


class TestGitleaksLinterRunBinaryNotFound:
    """Tests for GitleaksLinter.run when binary not found."""

    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_binary_not_found(
        self,
        mock_get_exe: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when gitleaks binary not found (lines 82-85)."""
        mock_get_exe.side_effect = RuntimeError(GITLEAKS_CLI_NOT_FOUND)

        linter = GitleaksLinter()
        result = linter.run()

        assert result.success is False
        assert result.message == GITLEAKS_CLI_NOT_FOUND
        captured = capsys.readouterr()
        assert GITLEAKS_CLI_NOT_FOUND in captured.err


class TestGitleaksLinterRunConfigIssues:
    """Tests for GitleaksLinter.run config validation."""

    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_config_missing(
        self,
        mock_get_exe: MagicMock,
        mock_config_path: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when .gitleaks.toml missing (lines 88-90)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_config_path.exists.return_value = False

        linter = GitleaksLinter()
        result = linter.run()

        assert result.success is False
        assert result.message == GITLEAKS_CONFIG_MISSING
        captured = capsys.readouterr()
        assert GITLEAKS_CONFIG_MISSING in captured.err

    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_config_unreadable(
        self,
        mock_get_exe: MagicMock,
        mock_config_path: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when .gitleaks.toml has permission error (lines 92-97)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_config_path.exists.return_value = True
        mock_config_path.read_text.side_effect = PermissionError("Access denied")

        linter = GitleaksLinter()
        result = linter.run()

        assert result.success is False
        assert result.message == GITLEAKS_CONFIG_UNREADABLE
        captured = capsys.readouterr()
        assert GITLEAKS_CONFIG_UNREADABLE in captured.err


class TestGitleaksLinterRunWithFiles:
    """Tests for GitleaksLinter.run with file filtering."""

    @patch("scripts.dev.linter.linters.gitleaks.subprocess.run")
    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.load_yaml_config")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_with_files_success(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_lint_config: MagicMock,
        mock_gitleaks_config: MagicMock,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """Test run with file filtering when no leaks found (branch 102 True)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_lint_config.exists.return_value = True
        mock_load_config.return_value = {
            "excluded_extensions": [],
            "excluded_names": [],
            "excluded_dirs": [],
        }
        mock_subprocess_run.return_value = MagicMock(returncode=0)

        linter = GitleaksLinter()
        result = linter.run(files=["app/main.py", "config.yaml"])

        assert result.success is True

    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.load_yaml_config")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_with_no_scannable_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_lint_config: MagicMock,
        mock_gitleaks_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when all files are excluded (lines 130-132)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_lint_config.exists.return_value = True
        mock_load_config.return_value = {
            "excluded_extensions": [".py", ".yaml"],
            "excluded_names": [],
            "excluded_dirs": [],
        }

        linter = GitleaksLinter()
        result = linter.run(files=["app/main.py", "config.yaml"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No scannable files for gitleaks" in captured.out

    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.LINT_GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.load_yaml_config")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_lint_config_invalid(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_lint_config: MagicMock,
        mock_gitleaks_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when lint config is invalid (lines 108-111)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_lint_config.exists.return_value = True
        mock_lint_config.name = ".lint.gitleaks.yaml"
        mock_load_config.side_effect = Exception("Invalid YAML")

        linter = GitleaksLinter()
        result = linter.run(files=["test.py"])

        assert result.success is False
        assert "Invalid or unreadable" in result.message
        captured = capsys.readouterr()
        assert "Invalid or unreadable" in captured.err


class TestGitleaksLinterRunWithoutFiles:
    """Tests for GitleaksLinter.run without file filtering (full scan)."""

    @patch("scripts.dev.linter.linters.gitleaks.subprocess.run")
    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_full_scan_success(
        self,
        mock_get_exe: MagicMock,
        mock_gitleaks_config: MagicMock,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """Test run full scan success (line 138)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_subprocess_run.return_value = MagicMock(returncode=0)

        linter = GitleaksLinter()
        result = linter.run(files=None)

        assert result.success is True
        # Verify "." was appended for full repo scan
        call_args = mock_subprocess_run.call_args[0][0]
        assert "." in call_args


class TestGitleaksLinterRunExitCodes:
    """Tests for GitleaksLinter.run exit code handling."""

    @patch("scripts.dev.linter.linters.gitleaks.subprocess.run")
    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_leaks_found_with_stdout(
        self,
        mock_get_exe: MagicMock,
        mock_gitleaks_config: MagicMock,
        mock_subprocess_run: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when leaks found with stdout (lines 160-169, branches 162 True)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_subprocess_run.return_value = MagicMock(
            returncode=1,
            stdout="Found secret in config.py",
            stderr="",
        )

        linter = GitleaksLinter()
        result = linter.run(files=None)

        assert result.success is False
        assert "gitleaks found potential secrets" in result.message
        captured = capsys.readouterr()
        assert "Found secret in config.py" in captured.out

    @patch("scripts.dev.linter.linters.gitleaks.subprocess.run")
    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_leaks_found_with_stderr(
        self,
        mock_get_exe: MagicMock,
        mock_gitleaks_config: MagicMock,
        mock_subprocess_run: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when leaks found with stderr (lines 164-165, branch 164 True)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_subprocess_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error detail in stderr",
        )

        linter = GitleaksLinter()
        result = linter.run(files=None)

        assert result.success is False
        captured = capsys.readouterr()
        assert "Error detail in stderr" in captured.err

    @patch("scripts.dev.linter.linters.gitleaks.subprocess.run")
    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_config_error_126(
        self,
        mock_get_exe: MagicMock,
        mock_gitleaks_config: MagicMock,
        mock_subprocess_run: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run with exit code 126 config error (lines 170-175, branches 173 True)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_subprocess_run.return_value = MagicMock(
            returncode=126,
            stdout="",
            stderr="Unknown flag: --invalid",
        )

        linter = GitleaksLinter()
        result = linter.run(files=None)

        assert result.success is False
        assert "configuration error" in result.message
        captured = capsys.readouterr()
        assert "gitleaks configuration error" in captured.err
        assert "Unknown flag: --invalid" in captured.err

    @patch("scripts.dev.linter.linters.gitleaks.subprocess.run")
    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_unexpected_exit_code(
        self,
        mock_get_exe: MagicMock,
        mock_gitleaks_config: MagicMock,
        mock_subprocess_run: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run with unexpected exit code (lines 176-184, branch 182 True)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_subprocess_run.return_value = MagicMock(
            returncode=99,
            stdout="",
            stderr="Unexpected error",
        )

        linter = GitleaksLinter()
        result = linter.run(files=None)

        assert result.success is False
        assert "unexpected exit code 99" in result.message
        captured = capsys.readouterr()
        assert "Unexpected error" in captured.err

    @patch("scripts.dev.linter.linters.gitleaks.subprocess.run")
    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_timeout(
        self,
        mock_get_exe: MagicMock,
        mock_gitleaks_config: MagicMock,
        mock_subprocess_run: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when scan times out (lines 149-151)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_subprocess_run.side_effect = subprocess.TimeoutExpired("gitleaks", 300)

        linter = GitleaksLinter()
        result = linter.run(files=None)

        assert result.success is False
        assert result.message == GITLEAKS_TIMEOUT_MSG
        captured = capsys.readouterr()
        assert GITLEAKS_TIMEOUT_MSG in captured.err

    @patch("scripts.dev.linter.linters.gitleaks.subprocess.run")
    @patch("scripts.dev.linter.linters.gitleaks.GITLEAKS_CONFIG")
    @patch("scripts.dev.linter.linters.gitleaks.get_executable")
    def test_run_file_not_found_during_execution(
        self,
        mock_get_exe: MagicMock,
        mock_gitleaks_config: MagicMock,
        mock_subprocess_run: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when FileNotFoundError during execution (lines 152-155)."""
        mock_get_exe.return_value = "/usr/bin/gitleaks"
        mock_gitleaks_config.exists.return_value = True
        mock_gitleaks_config.read_text.return_value = ""
        mock_subprocess_run.side_effect = FileNotFoundError()

        linter = GitleaksLinter()
        result = linter.run(files=None)

        assert result.success is False
        assert result.message == GITLEAKS_CLI_NOT_FOUND
