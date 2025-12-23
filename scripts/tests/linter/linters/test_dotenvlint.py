"""Tests for scripts.dev.linter.linters.dotenvlint module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.dotenvlint import DotenvlintLinter


class TestDotenvlintLinterInit:
    """Tests for DotenvlintLinter class attributes."""

    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = DotenvlintLinter()
        assert linter.name == "dotenvlint"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = DotenvlintLinter()
        assert linter.supports_file_filtering is True


class TestDotenvlintLinterRunWithFiles:
    """Tests for DotenvlintLinter.run with file filtering."""

    @patch("scripts.dev.linter.linters.dotenvlint.run_checked")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_with_env_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with .env files specified (line 38-44)."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {"exclude_dirs": []}

        linter = DotenvlintLinter()
        result = linter.run(files=[".env", ".env.local", "config.yaml"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/usr/bin/dotenv-linter" in call_args
        assert "check" in call_args
        assert ".env" in call_args
        assert ".env.local" in call_args
        assert "config.yaml" not in call_args  # Non-env files filtered out

    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_with_no_env_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no .env files in list (lines 41-43)."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {"exclude_dirs": []}

        linter = DotenvlintLinter()
        result = linter.run(files=["config.yaml", "test.py"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No .env files to check with dotenv-linter" in captured.out


class TestDotenvlintLinterRunWithoutFiles:
    """Tests for DotenvlintLinter.run without file filtering (glob mode)."""

    @patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.dotenvlint.run_checked")
    @patch("scripts.dev.linter.linters.dotenvlint.is_path_excluded")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_finds_env_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_excluded: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with glob mode finding .env files (lines 46-57, branch 52 True)."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {
            "targets": [".env"],
            "exclude_dirs": [],
            "exclude_patterns": [],
        }
        mock_is_excluded.return_value = False

        # Create a mock path that is_file returns True
        mock_path = MagicMock()
        mock_path.is_file.return_value = True
        mock_path.match.return_value = False  # Not excluded by pattern (branch 55 False)

        with patch.object(Path, "glob", return_value=[mock_path]):
            linter = DotenvlintLinter()
            result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()

    @patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.dotenvlint.is_path_excluded")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_path_excluded(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_excluded: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when path is excluded (branch 52 False - is_path_excluded True)."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {
            "targets": [".env"],
            "exclude_dirs": [],
            "exclude_patterns": [],
        }
        mock_is_excluded.return_value = True  # Path is excluded

        mock_path = MagicMock()
        mock_path.is_file.return_value = True

        with patch.object(Path, "glob", return_value=[mock_path]):
            linter = DotenvlintLinter()
            result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        # No env files found since it was excluded
        assert "No .env files found for dotenv-linter scan" in captured.out

    @patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.dotenvlint.is_path_excluded")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_pattern_excluded(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_excluded: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when path matches exclude pattern (branch 55 True)."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {
            "targets": [".env"],
            "exclude_dirs": [],
            "exclude_patterns": ["*.example"],
        }
        mock_is_excluded.return_value = False

        mock_path = MagicMock()
        mock_path.is_file.return_value = True
        mock_path.match.return_value = True  # Matches exclude pattern

        with patch.object(Path, "glob", return_value=[mock_path]):
            linter = DotenvlintLinter()
            result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No .env files found for dotenv-linter scan" in captured.out

    @patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_no_files_found(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no .env files found (lines 59-60)."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {
            "targets": [".env"],
            "exclude_dirs": [],
            "exclude_patterns": [],
        }

        with patch.object(Path, "glob", return_value=[]):
            linter = DotenvlintLinter()
            result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No .env files found for dotenv-linter scan" in captured.out

    @patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.dotenvlint.is_path_excluded")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_not_file(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_excluded: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when glob returns directory not file (branch 52 False via is_file)."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {
            "targets": [".env"],
            "exclude_dirs": [],
            "exclude_patterns": [],
        }
        mock_is_excluded.return_value = False

        mock_path = MagicMock()
        mock_path.is_file.return_value = False  # Not a file

        with patch.object(Path, "glob", return_value=[mock_path]):
            linter = DotenvlintLinter()
            result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No .env files found for dotenv-linter scan" in captured.out
