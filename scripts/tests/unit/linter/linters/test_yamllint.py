from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.yamllint import YamllintLinter


class TestYamllintLinterRunWithFiles:
    @patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.yamllint.run_checked")
    @patch("scripts.dev.linter.linters.yamllint.is_path_included")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_with_yaml_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with YAML files specified."""
        mock_get_exe.return_value = "/usr/bin/yamllint"
        mock_load_config.return_value = {"included_paths": ["**/*.yaml", "**/*.yml"]}
        mock_is_included.return_value = True  # All YAML files included

        linter = YamllintLinter()
        result = linter.run(files=["config.yml", "data.yaml", "test.py"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/usr/bin/yamllint" in call_args
        assert "-c" in call_args
        assert "test.py" not in call_args

    @patch("scripts.dev.linter.linters.yamllint.is_path_included")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_with_no_yaml_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no YAML files in list."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"included_paths": ["**/*.yaml", "**/*.yml"]}
        mock_is_included.return_value = True

        linter = YamllintLinter()
        result = linter.run(files=["test.py", "README.md"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No YAML files" in captured.out


class TestYamllintLinterRunWithoutFiles:
    @patch("scripts.dev.linter.linters.yamllint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.yamllint.run_checked")
    @patch("scripts.dev.linter.linters.yamllint.is_path_included")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_full_scan(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_run_checked: MagicMock,
        mock_repo_root: MagicMock,
    ) -> None:
        """Test run without files (full scan)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"included_paths": ["**/*.yaml", "**/*.yml"]}
        mock_is_included.return_value = True  # All paths included

        mock_yml_path = MagicMock(spec=Path)
        mock_yml_path.is_file.return_value = True
        mock_yml_path.__str__ = lambda self: "/repo/config.yml"
        mock_yml_path.relative_to.return_value = Path("config.yml")

        mock_yaml_path = MagicMock(spec=Path)
        mock_yaml_path.is_file.return_value = True
        mock_yaml_path.__str__ = lambda self: "/repo/data.yaml"
        mock_yaml_path.relative_to.return_value = Path("data.yaml")

        mock_repo_root.rglob.side_effect = [[mock_yml_path], [mock_yaml_path]]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = YamllintLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()


class TestYamllintLinterEmptyYamlFiles:
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
        """Test run when no YAML files found."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"included_paths": ["**/*.yaml", "**/*.yml"]}

        mock_repo_root.rglob.return_value = []
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = YamllintLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_not_called()

    @patch("scripts.dev.linter.linters.yamllint.REPO_ROOT", Path("/fake/repo"))
    @patch("scripts.dev.linter.linters.yamllint.run_checked")
    @patch("scripts.dev.linter.linters.yamllint.is_path_included")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_with_yaml_files_calls_run_checked(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run with YAML files calls run_checked."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"included_paths": ["**/*.yaml", "**/*.yml"]}
        mock_is_included.return_value = True

        linter = YamllintLinter()
        result = linter.run(files=["config.yml"])

        assert result.success is True
        mock_run_checked.assert_called_once()


class TestYamllintLinterIncludedPaths:
    @patch("scripts.dev.linter.linters.yamllint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.yamllint.run_checked")
    @patch("scripts.dev.linter.linters.yamllint.is_path_included")
    @patch("scripts.dev.linter.linters.yamllint.load_yaml_config")
    @patch("scripts.dev.linter.linters.yamllint.get_executable")
    def test_run_excludes_paths_not_matching_include_patterns(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_run_checked: MagicMock,
        mock_repo_root: MagicMock,
    ) -> None:
        """Test run excludes paths not matching include patterns."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_load_config.return_value = {"included_paths": ["app/**/*.yaml"]}
        mock_is_included.return_value = False  # All paths excluded (not in included_paths)

        mock_yml_path = MagicMock(spec=Path)
        mock_yml_path.is_file.return_value = True
        mock_yml_path.relative_to.return_value = Path("node_modules/test.yml")

        mock_repo_root.rglob.side_effect = [[mock_yml_path], []]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = YamllintLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_not_called()  # All files excluded by include patterns
