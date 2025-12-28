from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.linters.dotenvlint import DotenvlintLinter


class TestDotenvlintLinterRunWithFiles:
    @patch("scripts.dev.linter.linters.dotenvlint.is_path_included")
    @patch("scripts.dev.linter.linters.dotenvlint.run_checked")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_with_env_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_run_checked: MagicMock,
        mock_is_included: MagicMock,
    ) -> None:
        """Test run with .env files specified."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {"included_paths": [".env.example", "app/.env.example"]}
        mock_is_included.return_value = True

        linter = DotenvlintLinter()
        result = linter.run(files=[".env", ".env.local", "config.yaml"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/usr/bin/dotenv-linter" in call_args
        assert "check" in call_args
        assert "config.yaml" not in call_args  # Non-env files filtered out

    @patch("scripts.dev.linter.linters.dotenvlint.is_path_included")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_with_no_env_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no .env files in list."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {"included_paths": [".env.example", "app/.env.example"]}
        mock_is_included.return_value = True

        linter = DotenvlintLinter()
        result = linter.run(files=["config.yaml", "test.py"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No .env files to check with dotenv-linter" in captured.out


class TestDotenvlintLinterRunWithoutFiles:
    @patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.dotenvlint.run_checked")
    @patch("scripts.dev.linter.linters.dotenvlint.is_path_included")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_finds_env_files(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_run_checked: MagicMock,
        mock_repo_root: MagicMock,
    ) -> None:
        """Test run with glob mode finding .env files."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {
            "included_paths": [".env.example", "app/.env.example"],
        }
        mock_is_included.return_value = True

        # Create a mock path that is_file returns True
        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.relative_to.return_value = Path(".env.example")
        mock_path.__str__ = lambda self: "/fake/repo/.env.example"

        mock_repo_root.rglob.return_value = [mock_path]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = DotenvlintLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()

    @patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.dotenvlint.is_path_included")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_path_not_included(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_is_included: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when path is not in included_paths."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {
            "included_paths": [".env.example"],
        }
        mock_is_included.return_value = False  # Path not in included_paths

        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = True
        mock_path.relative_to.return_value = Path(".venv/.env")

        mock_repo_root.rglob.return_value = [mock_path]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = DotenvlintLinter()
        result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No .env files found for dotenv-linter scan" in captured.out

    @patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_no_files_found(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no .env files found."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {
            "included_paths": [".env.example"],
        }

        mock_repo_root.rglob.return_value = []
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = DotenvlintLinter()
        result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No .env files found for dotenv-linter scan" in captured.out

    @patch("scripts.dev.linter.linters.dotenvlint.REPO_ROOT")
    @patch("scripts.dev.linter.linters.dotenvlint.load_yaml_config")
    @patch("scripts.dev.linter.linters.dotenvlint.get_executable")
    def test_run_not_file(
        self,
        mock_get_exe: MagicMock,
        mock_load_config: MagicMock,
        mock_repo_root: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when rglob returns directory not file."""
        mock_get_exe.return_value = "/usr/bin/dotenv-linter"
        mock_load_config.return_value = {
            "included_paths": [".env.example"],
        }

        mock_path = MagicMock(spec=Path)
        mock_path.is_file.return_value = False  # Not a file

        mock_repo_root.rglob.return_value = [mock_path]
        mock_repo_root.__truediv__ = lambda self, x: Path(x)

        linter = DotenvlintLinter()
        result = linter.run(files=None)

        assert result.success is True
        captured = capsys.readouterr()
        assert "No .env files found for dotenv-linter scan" in captured.out
