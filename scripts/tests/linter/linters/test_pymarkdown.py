"""Tests for scripts.dev.linter.linters.pymarkdown module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.pymarkdown import PymarkdownLinter


class TestPymarkdownLinterInit:
    """Tests for PymarkdownLinter class attributes."""

    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = PymarkdownLinter()
        assert linter.name == "pymarkdown"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = PymarkdownLinter()
        assert linter.supports_file_filtering is True


class TestPymarkdownLinterRunWithFiles:
    """Tests for PymarkdownLinter.run with file filtering."""

    @patch("scripts.dev.linter.linters.pymarkdown.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.pymarkdown.run_checked")
    @patch("scripts.dev.linter.linters.pymarkdown.is_path_included")
    @patch("scripts.dev.linter.linters.pymarkdown.load_yaml_config")
    @patch("scripts.dev.linter.linters.pymarkdown.get_executable")
    def test_run_with_markdown_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with Markdown files specified."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"included_paths": ["README.md", "docs/**/*.md"]}
        mock_is_included.return_value = True  # All paths included

        linter = PymarkdownLinter()
        result = linter.run(files=["README.md", "docs/guide.md", "config.yaml"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/usr/bin/uv" in call_args
        assert "run" in call_args
        assert "pymarkdown" in call_args
        assert "-c" in call_args
        assert "scan" in call_args
        assert "config.yaml" not in call_args

    @patch("scripts.dev.linter.linters.pymarkdown.is_path_included")
    @patch("scripts.dev.linter.linters.pymarkdown.load_yaml_config")
    @patch("scripts.dev.linter.linters.pymarkdown.get_executable")
    def test_run_with_no_markdown_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no Markdown files in list."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"included_paths": ["README.md", "docs/**/*.md"]}
        mock_is_included.return_value = True

        linter = PymarkdownLinter()
        result = linter.run(files=["config.yaml", "test.py"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Markdown files to check with pymarkdown" in captured.out


class TestPymarkdownLinterRunWithoutFiles:
    """Tests for PymarkdownLinter.run without file filtering."""

    @patch("scripts.dev.linter.linters.pymarkdown.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.pymarkdown.run_checked")
    @patch("scripts.dev.linter.linters.pymarkdown.load_yaml_config")
    @patch("scripts.dev.linter.linters.pymarkdown.get_executable")
    def test_run_full_scan(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run without files (full scan)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {
            "included_paths": ["README.md", "docs/**/*.md"],
        }

        linter = PymarkdownLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "-r" in call_args  # Recursive flag for full scan
        assert "README.md" in call_args
        assert "docs/**/*.md" in call_args


class TestPymarkdownLinterIncludedPaths:
    """Tests for PymarkdownLinter.run with include patterns."""

    @patch("scripts.dev.linter.linters.pymarkdown.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.pymarkdown.run_checked")
    @patch("scripts.dev.linter.linters.pymarkdown.load_yaml_config")
    @patch("scripts.dev.linter.linters.pymarkdown.get_executable")
    def test_run_with_included_paths(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with included_paths patterns."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {
            "included_paths": ["docs/architecture/*.md", "docs/development/*.md"],
        }

        linter = PymarkdownLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "-r" in call_args
        # Check that included_paths are in the command
        assert "docs/architecture/*.md" in call_args
        assert "docs/development/*.md" in call_args

    @patch("scripts.dev.linter.linters.pymarkdown.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.pymarkdown.run_checked")
    @patch("scripts.dev.linter.linters.pymarkdown.is_path_included")
    @patch("scripts.dev.linter.linters.pymarkdown.load_yaml_config")
    @patch("scripts.dev.linter.linters.pymarkdown.get_executable")
    def test_run_with_files_filters_by_included_paths(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with files filters using included_paths patterns."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {
            "included_paths": ["README.md", "docs/**/*.md"],
        }
        mock_is_included.return_value = True

        linter = PymarkdownLinter()
        result = linter.run(files=["README.md"])

        assert result.success is True
        mock_run_checked.assert_called_once()
