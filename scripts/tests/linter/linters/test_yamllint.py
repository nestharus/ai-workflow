"""Tests for scripts.dev.linter.linters.yamllint module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.yamllint import YamllintLinter


class TestYamllintLinterInit:
    """Tests for YamllintLinter class attributes."""

    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = YamllintLinter()
        assert linter.name == "yamllint"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = YamllintLinter()
        assert linter.supports_file_filtering is True


class TestYamllintLinterRunWithFiles:
    """Tests for YamllintLinter.run with file filtering."""

    @patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.yamllint.run_checked")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_with_yaml_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with YAML files specified."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"exclude_dirs": []}

        linter = YamllintLinter()
        result = linter.run(files=["config.yml", "data.yaml", "test.py"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/usr/bin/uv" in call_args
        assert "run" in call_args
        assert "yamllint" in call_args
        assert "-c" in call_args
        assert "config.yml" in call_args
        assert "data.yaml" in call_args
        assert "test.py" not in call_args

    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_with_no_yaml_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no YAML files in list."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"exclude_dirs": []}

        linter = YamllintLinter()
        result = linter.run(files=["test.py", "README.md"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No YAML files to check with yamllint" in captured.out


class TestYamllintLinterRunWithoutFiles:
    """Tests for YamllintLinter.run without file filtering."""

    @patch("scripts.dev.linter.linters.yamllint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.yamllint.run_checked")
    @patch("scripts.dev.linter.linters.yamllint.is_path_excluded")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_full_scan(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_excluded: MagicMock,
        mock_run_checked: MagicMock,
        mock_repo_root: MagicMock,
    ) -> None:
        """Test run without files (full scan)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"exclude_dirs": []}
        mock_is_excluded.return_value = False

        mock_yml_path = MagicMock(spec=Path)
        mock_yml_path.is_file.return_value = True
        mock_yml_path.__str__ = lambda self: "/repo/config.yml"

        mock_yaml_path = MagicMock(spec=Path)
        mock_yaml_path.is_file.return_value = True
        mock_yaml_path.__str__ = lambda self: "/repo/data.yaml"

        mock_repo_root.rglob.side_effect = [[mock_yml_path], [mock_yaml_path]]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = YamllintLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()


class TestYamllintLinterEmptyYamlFiles:
    """Tests for YamllintLinter.run when no YAML files found (branch at 53)."""

    @patch("scripts.dev.linter.linters.yamllint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.yamllint.run_checked")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_no_yaml_files_found_skips_run_checked(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_repo_root: MagicMock,
    ) -> None:
        """Test run when no YAML files found (branch 53 False)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"exclude_dirs": []}

        mock_repo_root.rglob.return_value = []
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = YamllintLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_not_called()  # Branch 53 False - no files = no call

    @patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.yamllint.run_checked")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_with_yaml_files_calls_run_checked(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with YAML files calls run_checked (branch 53 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"exclude_dirs": []}

        linter = YamllintLinter()
        result = linter.run(files=["config.yml"])

        assert result.success is True
        mock_run_checked.assert_called_once()  # Branch 53 True


class TestYamllintLinterExcludedPaths:
    """Tests for YamllintLinter.run with path exclusions."""

    @patch("scripts.dev.linter.linters.yamllint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.yamllint.run_checked")
    @patch("scripts.dev.linter.linters.yamllint.is_path_excluded")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_excludes_paths(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_excluded: MagicMock,
        mock_run_checked: MagicMock,
        mock_repo_root: MagicMock,
    ) -> None:
        """Test run excludes paths from is_path_excluded."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"exclude_dirs": ["node_modules"]}
        mock_is_excluded.return_value = True  # All paths excluded

        mock_yml_path = MagicMock(spec=Path)
        mock_yml_path.is_file.return_value = True

        mock_repo_root.rglob.side_effect = [[mock_yml_path], []]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = YamllintLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_not_called()  # All files excluded
