"""Tests for scripts.dev.linter.linters.hadolint module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.hadolint import HadolintLinter


class TestHadolintLinterInit:
    """Tests for HadolintLinter class attributes."""

    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = HadolintLinter()
        assert linter.name == "hadolint"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = HadolintLinter()
        assert linter.supports_file_filtering is True


class TestHadolintLinterRunWithFiles:
    """Tests for HadolintLinter.run with file filtering."""

    @patch("scripts.dev.linter.linters.hadolint.run_checked")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_with_dockerfile_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with Dockerfile specified (lines 38-40, branch 38 True)."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"exclude_dirs": []}

        linter = HadolintLinter()
        result = linter.run(files=["Dockerfile", "README.md", "app/Dockerfile"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/usr/bin/hadolint" in call_args
        assert "--config" in call_args

    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_with_no_dockerfiles(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no Dockerfile in list (lines 48-49)."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"exclude_dirs": []}

        linter = HadolintLinter()
        result = linter.run(files=["config.yaml", "test.py"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Dockerfiles found for hadolint scan" in captured.out


class TestHadolintLinterRunWithoutFiles:
    """Tests for HadolintLinter.run without file filtering (glob mode)."""

    @patch("scripts.dev.linter.linters.hadolint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.hadolint.run_checked")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_finds_dockerfiles(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_repo_root: MagicMock,
    ) -> None:
        """Test run with glob mode finding Dockerfiles (lines 41-46, branch 38 False)."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"exclude_dirs": []}

        mock_dockerfile = MagicMock(spec=Path)
        mock_dockerfile.is_file.return_value = True
        mock_dockerfile.parents = []
        mock_dockerfile.__str__ = lambda self: "/repo/Dockerfile"

        mock_repo_root.rglob.return_value = [mock_dockerfile]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = HadolintLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()

    @patch("scripts.dev.linter.linters.hadolint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_no_dockerfiles_found(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no Dockerfiles found (lines 48-49)."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"exclude_dirs": []}

        mock_repo_root.rglob.return_value = []
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = HadolintLinter()
        result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Dockerfiles found for hadolint scan" in captured.out

    @patch("scripts.dev.linter.linters.hadolint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_dockerfile_in_excluded_dir(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when Dockerfile is in excluded directory (line 45 branch)."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        excluded_dir = Path("node_modules")
        mock_load_config.return_value = {"exclude_dirs": ["node_modules"]}

        mock_dockerfile = MagicMock(spec=Path)
        mock_dockerfile.is_file.return_value = True
        mock_dockerfile.parents = [excluded_dir]

        mock_repo_root.rglob.return_value = [mock_dockerfile]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = HadolintLinter()
        result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Dockerfiles found for hadolint scan" in captured.out

    @patch("scripts.dev.linter.linters.hadolint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_dockerfile_not_file(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when rglob returns directory (line 45 is_file False)."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"exclude_dirs": []}

        mock_dockerfile = MagicMock(spec=Path)
        mock_dockerfile.is_file.return_value = False
        mock_dockerfile.parents = []

        mock_repo_root.rglob.return_value = [mock_dockerfile]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = HadolintLinter()
        result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Dockerfiles found for hadolint scan" in captured.out


class TestHadolintLinterRunCheckedCall:
    """Tests for HadolintLinter.run run_checked call."""

    @patch("scripts.dev.linter.linters.hadolint.HADOLINT_CONFIG", Path("/repo/.hadolint.yaml"))
    @patch("scripts.dev.linter.linters.hadolint.run_checked")
    @patch("scripts.dev.linter.linters.hadolint.load_yaml_config")
    @patch("scripts.dev.linter.linters.hadolint.get_executable")
    def test_run_checked_call_structure(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run_checked is called with correct structure (lines 50-58)."""
        mock_get_exe.return_value = "/usr/bin/hadolint"
        mock_load_config.return_value = {"exclude_dirs": []}

        linter = HadolintLinter()
        result = linter.run(files=["Dockerfile"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert call_args[0] == "/usr/bin/hadolint"
        assert "--config" in call_args
        assert "/repo/.hadolint.yaml" in call_args
