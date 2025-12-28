import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.dev.linter.base import (
    InvalidCommandError,
    LinterResult,
    filter_files_with_config,
    get_executable,
    run_checked,
)


class TestGetExecutable:
    def test_get_executable_found(self) -> None:
        """Test get_executable when executable exists."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/python"
            result = get_executable("python", "Python not found")
            assert result == "/usr/bin/python"
            mock_which.assert_called_once_with("python")

    def test_get_executable_not_found_raises_runtime_error(self) -> None:
        """Test get_executable raises RuntimeError when executable not found (lines 77-80)."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None  # Simulates executable not found
            with pytest.raises(RuntimeError) as exc_info:
                get_executable("nonexistent_tool", "Custom error: tool not found")
            assert str(exc_info.value) == "Custom error: tool not found"
            mock_which.assert_called_once_with("nonexistent_tool")

    def test_get_executable_not_found_with_different_messages(self) -> None:
        """Test get_executable with different error messages."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None

            # Test with detailed error message
            with pytest.raises(RuntimeError) as exc_info:
                get_executable(
                    "gitleaks", "gitleaks not found. Install with: brew install gitleaks"
                )
            assert "gitleaks not found" in str(exc_info.value)

    def test_get_executable_returns_string_path(self) -> None:
        """Test that get_executable returns a string path."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/ruff"
            result = get_executable("ruff", "ruff not found")
            assert isinstance(result, str)
            assert result == "/usr/local/bin/ruff"


class TestRunChecked:
    def test_run_checked_success(self) -> None:
        """Test run_checked with a successful command."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.return_value = 0
            run_checked(["echo", "hello"])
            mock_check_call.assert_called_once_with(["echo", "hello"], cwd=None)

    def test_run_checked_with_cwd(self) -> None:
        """Test run_checked with a working directory."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.return_value = 0
            cwd = Path("/tmp")
            run_checked(["ls", "-la"], cwd=cwd)
            mock_check_call.assert_called_once_with(["ls", "-la"], cwd=cwd)

    def test_run_checked_subprocess_error_propagates(self) -> None:
        """Test that subprocess errors propagate correctly."""
        with patch("subprocess.check_call") as mock_check_call:
            mock_check_call.side_effect = subprocess.CalledProcessError(1, "test")
            with pytest.raises(subprocess.CalledProcessError):
                run_checked(["failing_command"])


class TestFilterFilesWithConfig:
    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_config_file_not_found(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when config file is not found."""
        mock_load_yaml_config.side_effect = FileNotFoundError("Config not found")

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "mypy")

        assert files == []
        assert error is not None
        assert error.success is False
        assert error.message == "Config file not found"
        captured = capsys.readouterr()
        assert "Mypy config file not found" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_config_yaml_parse_error(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when config file has YAML parse errors."""
        mock_load_yaml_config.side_effect = yaml.YAMLError("invalid YAML syntax")

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "ruff")

        assert files == []
        assert error is not None
        assert error.success is False
        assert "Config parse error" in (error.message or "")
        captured = capsys.readouterr()
        assert "Failed to parse ruff config" in captured.out
        assert "invalid YAML syntax" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_config_permission_error(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when config file has permission issues."""
        mock_load_yaml_config.side_effect = PermissionError("Permission denied")

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "mypy")

        assert files == []
        assert error is not None
        assert error.success is False
        assert "Config permission error" in (error.message or "")
        captured = capsys.readouterr()
        assert "Permission denied reading mypy config" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_unexpected_exception_propagates(
        self,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test that unexpected exceptions propagate instead of being swallowed."""
        mock_load_yaml_config.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(RuntimeError, match="Unexpected error"):
            filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "ruff")

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_included_paths_invalid_type(
        self,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when included_paths is not a list."""
        mock_load_yaml_config.return_value = {"included_paths": "not-a-list"}

        files, error = filter_files_with_config(["test.py"], Path("/fake/config.yaml"), "mypy")

        assert files == []
        assert error is not None
        assert error.success is False
        assert error.message == "Invalid included_paths config"
        captured = capsys.readouterr()
        assert "Invalid included_paths in mypy config" in captured.out
        assert "expected list" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_no_included_paths_returns_all_files(
        self,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test when config has no included_paths - all files returned."""
        mock_load_yaml_config.return_value = {}

        files, error = filter_files_with_config(
            ["app/main.py", "tests/test_main.py"], Path("/fake/config.yaml"), "mypy"
        )

        assert files == ["app/main.py", "tests/test_main.py"]
        assert error is None

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_filters_files_by_included_paths(
        self,
        mock_is_included: MagicMock,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test filtering files with included_paths patterns."""
        mock_load_yaml_config.return_value = {"included_paths": ["app/**/*.py"]}
        mock_is_included.side_effect = lambda path, patterns: path.startswith("app/")

        files, error = filter_files_with_config(
            ["app/main.py", "tests/test_main.py", "app/utils.py"],
            Path("/fake/config.yaml"),
            "mypy",
        )

        assert files == ["app/main.py", "app/utils.py"]
        assert error is None

    @patch("scripts.dev.linter.base.load_yaml_config")
    @patch("scripts.dev.linter.base.is_path_included")
    def test_all_files_filtered_returns_empty_list(
        self,
        mock_is_included: MagicMock,
        mock_load_yaml_config: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test when all files are filtered out."""
        mock_load_yaml_config.return_value = {"included_paths": ["app/**/*.py"]}
        mock_is_included.return_value = False

        files, error = filter_files_with_config(
            ["tests/test_main.py", "tests/test_utils.py"],
            Path("/fake/config.yaml"),
            "mypy",
        )

        assert files == []
        assert error is None
        captured = capsys.readouterr()
        assert "No Python files match mypy included_paths filter" in captured.out

    @patch("scripts.dev.linter.base.load_yaml_config")
    def test_empty_included_paths_list_returns_all_files(
        self,
        mock_load_yaml_config: MagicMock,
    ) -> None:
        """Test when included_paths is empty list - all files returned."""
        mock_load_yaml_config.return_value = {"included_paths": []}

        files, error = filter_files_with_config(
            ["app/main.py", "tests/test_main.py"], Path("/fake/config.yaml"), "ruff"
        )

        assert files == ["app/main.py", "tests/test_main.py"]
        assert error is None
