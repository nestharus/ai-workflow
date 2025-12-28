"""Tests for scripts.dev.linter.linters.shellcheck module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.dev.linter.linters.shellcheck import ShellcheckLinter


class TestShellcheckLinterInit:
    """Tests for ShellcheckLinter class attributes."""

    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = ShellcheckLinter()
        assert linter.name == "shellcheck"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = ShellcheckLinter()
        assert linter.supports_file_filtering is True


class TestShellcheckLinterConfigLoading:
    """Tests for ShellcheckLinter.run config loading."""

    @patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG")
    @patch("scripts.dev.linter.linters.shellcheck.run_checked")
    @patch("scripts.dev.linter.linters.shellcheck.load_yaml_config")
    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_config_not_dict(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_config_path: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when config is not a dict (e.g., list or scalar from YAML)."""
        mock_get_exe.return_value = "/usr/bin/shellcheck"
        mock_config_path.exists.return_value = True
        mock_load_config.return_value = ["not", "a", "dict"]  # Non-dict config

        linter = ShellcheckLinter()
        result = linter.run(files=["test.sh"])

        # Should not crash with AttributeError, should succeed
        assert result.success is True
        mock_run_checked.assert_called_once()

    @patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG")
    @patch("scripts.dev.linter.linters.shellcheck.run_checked")
    @patch("scripts.dev.linter.linters.shellcheck.load_yaml_config")
    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_config_is_none(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_config_path: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when config is None."""
        mock_get_exe.return_value = "/usr/bin/shellcheck"
        mock_config_path.exists.return_value = True
        mock_load_config.return_value = None

        linter = ShellcheckLinter()
        result = linter.run(files=["test.sh"])

        assert result.success is True
        mock_run_checked.assert_called_once()

    @patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG")
    @patch("scripts.dev.linter.linters.shellcheck.load_yaml_config")
    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_config_yaml_error(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_config_path: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when config file is invalid YAML."""
        mock_get_exe.return_value = "/usr/bin/shellcheck"
        mock_config_path.exists.return_value = True
        mock_load_config.side_effect = yaml.YAMLError("Invalid YAML")

        linter = ShellcheckLinter()
        result = linter.run(files=["test.sh"])

        assert result.success is False
        assert "Invalid or unreadable" in (result.message or "")
        captured = capsys.readouterr()
        assert "Invalid or unreadable" in captured.err

    @patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG")
    @patch("scripts.dev.linter.linters.shellcheck.load_yaml_config")
    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_config_os_error(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_config_path: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when config file cannot be read (OSError)."""
        mock_get_exe.return_value = "/usr/bin/shellcheck"
        mock_config_path.exists.return_value = True
        mock_load_config.side_effect = OSError("Permission denied")

        linter = ShellcheckLinter()
        result = linter.run(files=["test.sh"])

        assert result.success is False
        assert "Invalid or unreadable" in (result.message or "")
        captured = capsys.readouterr()
        assert "Invalid or unreadable" in captured.err


class TestShellcheckLinterMissingExecutable:
    """Tests for ShellcheckLinter.run when shellcheck is not installed."""

    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_missing_shellcheck(
        self,
        mock_get_exe: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when shellcheck CLI is missing."""
        mock_get_exe.side_effect = RuntimeError("shellcheck CLI required to run lint")

        linter = ShellcheckLinter()
        result = linter.run(files=["test.sh"])

        assert result.success is False
        assert "shellcheck CLI required" in (result.message or "")
        captured = capsys.readouterr()
        assert "shellcheck CLI required" in captured.err


class TestShellcheckLinterRunWithFiles:
    """Tests for ShellcheckLinter.run with file filtering."""

    @patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", Path("/repo"))
    @patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG")
    @patch("scripts.dev.linter.linters.shellcheck.run_checked")
    @patch("scripts.dev.linter.linters.shellcheck.load_yaml_config")
    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_with_sh_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_config_path: MagicMock,
    ) -> None:
        """Test run with shell files specified."""
        mock_get_exe.return_value = "/usr/bin/shellcheck"
        mock_config_path.exists.return_value = True
        mock_load_config.return_value = {}  # No included_paths means all paths included

        linter = ShellcheckLinter()
        result = linter.run(files=["script.sh", "README.md", "deploy.sh"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/usr/bin/shellcheck" in call_args
        # Verify only .sh files were included with correct absolute paths
        assert "/repo/script.sh" in call_args
        assert "/repo/deploy.sh" in call_args
        assert "README.md" not in " ".join(call_args)

    @patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG")
    @patch("scripts.dev.linter.linters.shellcheck.load_yaml_config")
    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_with_no_sh_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_config_path: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no .sh files in list."""
        mock_get_exe.return_value = "/usr/bin/shellcheck"
        mock_config_path.exists.return_value = True
        mock_load_config.return_value = {}

        linter = ShellcheckLinter()
        result = linter.run(files=["config.yaml", "test.py"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No shell scripts to check" in captured.out


class TestShellcheckLinterDiscovery:
    """Tests for ShellcheckLinter.run file discovery (files=None)."""

    @patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT")
    @patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG")
    @patch("scripts.dev.linter.linters.shellcheck.run_checked")
    @patch("scripts.dev.linter.linters.shellcheck.load_yaml_config")
    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_discovers_sh_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_config_path: MagicMock,
        mock_repo_root: MagicMock,
    ) -> None:
        """Test run discovers .sh files when files=None."""
        mock_get_exe.return_value = "/usr/bin/shellcheck"
        mock_config_path.exists.return_value = True
        mock_load_config.return_value = {}

        # Mock rglob to return shell scripts
        mock_sh1 = MagicMock(spec=Path)
        mock_sh1.is_file.return_value = True
        mock_sh1.relative_to.return_value = Path("scripts/test.sh")
        mock_sh1.__str__.return_value = "/repo/scripts/test.sh"

        mock_sh2 = MagicMock(spec=Path)
        mock_sh2.is_file.return_value = True
        mock_sh2.relative_to.return_value = Path("deploy.sh")
        mock_sh2.__str__.return_value = "/repo/deploy.sh"

        mock_repo_root.rglob.return_value = [mock_sh1, mock_sh2]

        linter = ShellcheckLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/repo/scripts/test.sh" in call_args
        assert "/repo/deploy.sh" in call_args


class TestShellcheckLinterIncludedPaths:
    """Tests for ShellcheckLinter.run with included_paths filtering."""

    @patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", Path("/repo"))
    @patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG")
    @patch("scripts.dev.linter.linters.shellcheck.run_checked")
    @patch("scripts.dev.linter.linters.shellcheck.load_yaml_config")
    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_filters_by_included_paths(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_config_path: MagicMock,
    ) -> None:
        """Test run filters files by included_paths patterns."""
        mock_get_exe.return_value = "/usr/bin/shellcheck"
        mock_config_path.exists.return_value = True
        # Only include files under scripts/ directory
        mock_load_config.return_value = {"included_paths": ["scripts/**"]}

        linter = ShellcheckLinter()
        # Provide files from different directories - only scripts/*.sh should be included
        result = linter.run(files=["scripts/deploy.sh", "root.sh", "other/build.sh"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        # Only scripts/deploy.sh should be included
        assert "/repo/scripts/deploy.sh" in call_args
        assert "/repo/root.sh" not in call_args
        assert "/repo/other/build.sh" not in call_args

    @patch("scripts.dev.linter.linters.shellcheck.REPO_ROOT", Path("/repo"))
    @patch("scripts.dev.linter.linters.shellcheck.LINT_SHELLCHECK_CONFIG")
    @patch("scripts.dev.linter.linters.shellcheck.run_checked")
    @patch("scripts.dev.linter.linters.shellcheck.load_yaml_config")
    @patch("scripts.dev.linter.linters.shellcheck.get_executable")
    def test_run_all_filtered_out_by_included_paths(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_config_path: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when all files are filtered out by included_paths."""
        mock_get_exe.return_value = "/usr/bin/shellcheck"
        mock_config_path.exists.return_value = True
        # Only include files under nonexistent/ directory
        mock_load_config.return_value = {"included_paths": ["nonexistent/**"]}

        linter = ShellcheckLinter()
        result = linter.run(files=["scripts/deploy.sh", "root.sh"])

        assert result.success is True
        mock_run_checked.assert_not_called()
        captured = capsys.readouterr()
        assert "No shell scripts to check" in captured.out
