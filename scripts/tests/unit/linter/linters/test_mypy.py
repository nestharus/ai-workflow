from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.base import LinterResult
from scripts.dev.linter.linters.mypy import MypyLinter


class TestMypyLinterRunWithFiles:
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.run_checked")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_with_python_files(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
        mock_filter: MagicMock,
    ) -> None:
        """Test run with Python files specified (lines 30-46, branch 30 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (["app/main.py", "app/utils.py"], None)

        linter = MypyLinter()
        result = linter.run(files=["app/main.py", "config.yaml", "app/utils.py"])

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "/usr/bin/uv" in call_args
        assert "run" in call_args
        assert "mypy" in call_args
        assert "app/main.py" in call_args
        assert "app/utils.py" in call_args

    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_with_no_python_files(
        self,
        mock_get_exe: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when no Python files in list (lines 31-34, branch 32 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"

        linter = MypyLinter()
        result = linter.run(files=["config.yaml", "README.md"])

        assert result.success is True
        captured = capsys.readouterr()
        assert "No Python files to check with mypy" in captured.out

    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_all_files_excluded_test_dirs(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test run when all files are in excluded test dirs (lines 38-45, branch 43 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = ([], None)

        linter = MypyLinter()
        result = linter.run(
            files=[
                "tests/test_main.py",
                "scripts/tests/test_utils.py",
            ]
        )

        assert result.success is True


class TestMypyLinterConfigErrors:
    @patch("scripts.dev.linter.linters.mypy.run_checked")
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_config_file_not_found(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run when config file is not found."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (
            [],
            LinterResult(success=False, message="Config file not found"),
        )

        linter = MypyLinter()
        result = linter.run(files=["test.py"])

        assert result.success is False
        assert result.message == "Config file not found"
        mock_run_checked.assert_not_called()

    @patch("scripts.dev.linter.linters.mypy.run_checked")
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_config_parse_error(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run when config file has parse errors."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (
            [],
            LinterResult(success=False, message="Config load error: YAML parse error"),
        )

        linter = MypyLinter()
        result = linter.run(files=["test.py"])

        assert result.success is False
        assert "Config load error" in (result.message or "")
        mock_run_checked.assert_not_called()

    @patch("scripts.dev.linter.linters.mypy.run_checked")
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_included_paths_invalid_type(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run when included_paths is not a list."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (
            [],
            LinterResult(success=False, message="Invalid included_paths config"),
        )

        linter = MypyLinter()
        result = linter.run(files=["test.py"])

        assert result.success is False
        assert result.message == "Invalid included_paths config"
        mock_run_checked.assert_not_called()


class TestMypyLinterRunWithoutFiles:
    @patch("scripts.dev.linter.linters.mypy.run_checked")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_full_repo_scan(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
    ) -> None:
        """Test run without files (full repo scan) (lines 47-48, branch 30 False)."""
        mock_get_exe.return_value = "/usr/bin/uv"

        linter = MypyLinter()
        result = linter.run(files=None)

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert call_args == ["/usr/bin/uv", "run", "mypy"]


class TestMypyLinterMixedFiles:
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.run_checked")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_mixed_test_and_app_files(
        self,
        mock_get_exe: MagicMock,
        mock_run_checked: MagicMock,
        mock_filter: MagicMock,
    ) -> None:
        """Test run with mix of test and app files (lines 38-42)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (["app/main.py", "scripts/dev/utils.py"], None)

        linter = MypyLinter()
        result = linter.run(
            files=[
                "tests/test_main.py",  # Should be filtered
                "app/main.py",  # Should be included
                "scripts/dev/utils.py",  # Should be included
            ]
        )

        assert result.success is True
        mock_run_checked.assert_called_once()
        call_args = mock_run_checked.call_args[0][0]
        assert "app/main.py" in call_args
        assert "scripts/dev/utils.py" in call_args
        assert "tests/test_main.py" not in call_args
