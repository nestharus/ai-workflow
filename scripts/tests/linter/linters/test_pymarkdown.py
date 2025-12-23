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
    @patch("scripts.dev.linter.linters.pymarkdown.load_yaml_config")
    @patch("scripts.dev.linter.linters.pymarkdown.get_executable")
    def test_run_with_markdown_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with Markdown files specified (lines 35-49, branch 35 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"excludes": []}

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
        assert "README.md" in call_args
        assert "docs/guide.md" in call_args
        assert "config.yaml" not in call_args

    @patch("scripts.dev.linter.linters.pymarkdown.load_yaml_config")
    @patch("scripts.dev.linter.linters.pymarkdown.get_executable")
    def test_run_with_no_markdown_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no Markdown files in list (lines 36-39, branch 37 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"excludes": []}

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
        """Test run without files (full scan) (lines 50-61, branch 35 False)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {
            "targets": ["docs/", "*.md"],
            "excludes": [],
        }

        linter = PymarkdownLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "-r" in call_args  # Recursive flag for full scan
        assert "docs/" in call_args
        assert "*.md" in call_args


class TestPymarkdownLinterExcludes:
    """Tests for PymarkdownLinter.run with exclude patterns."""

    @patch("scripts.dev.linter.linters.pymarkdown.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.pymarkdown.run_checked")
    @patch("scripts.dev.linter.linters.pymarkdown.load_yaml_config")
    @patch("scripts.dev.linter.linters.pymarkdown.get_executable")
    def test_run_with_excludes(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with exclude patterns (lines 63-64)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {
            "targets": ["docs/"],
            "excludes": ["node_modules/", "*.generated.md"],
        }

        linter = PymarkdownLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "-e" in call_args
        # Check that exclude patterns are in the command
        e_indices = [i for i, arg in enumerate(call_args) if arg == "-e"]
        assert len(e_indices) == 2  # Two exclude patterns

    @patch("scripts.dev.linter.linters.pymarkdown.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.pymarkdown.run_checked")
    @patch("scripts.dev.linter.linters.pymarkdown.load_yaml_config")
    @patch("scripts.dev.linter.linters.pymarkdown.get_executable")
    def test_run_with_files_and_excludes(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with files and exclude patterns (branch 63 with files)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {
            "excludes": ["*.generated.md"],
        }

        linter = PymarkdownLinter()
        result = linter.run(files=["README.md"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "-e" in call_args
        assert "*.generated.md" in call_args
