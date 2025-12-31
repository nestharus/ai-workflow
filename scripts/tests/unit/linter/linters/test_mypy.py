from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.linter.base import LinterResult
from scripts.dev.linter.linters.mypy import MypyLinter, _parse_mypy_json


class TestMypyLinterRunWithFiles:
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.subprocess.run")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_with_python_files(
        self,
        mock_get_exe: MagicMock,
        mock_subprocess_run: MagicMock,
        mock_filter: MagicMock,
    ) -> None:
        """Test run with Python files specified (lines 30-46, branch 30 True)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (["app/main.py", "app/utils.py"], None)
        mock_subprocess_run.return_value = CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        linter = MypyLinter()
        result = linter.run(files=["app/main.py", "config.yaml", "app/utils.py"])

        assert result.success is True
        assert result.errors == []
        mock_subprocess_run.assert_called_once()
        call_args = mock_subprocess_run.call_args[0][0]
        assert "/usr/bin/uv" in call_args
        assert "run" in call_args
        assert "mypy" in call_args
        assert "--output=json" in call_args
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
    @patch("scripts.dev.linter.linters.mypy.subprocess.run")
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_config_file_not_found(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        mock_subprocess_run: MagicMock,
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
        mock_subprocess_run.assert_not_called()

    @patch("scripts.dev.linter.linters.mypy.subprocess.run")
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_config_parse_error(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        mock_subprocess_run: MagicMock,
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
        mock_subprocess_run.assert_not_called()

    @patch("scripts.dev.linter.linters.mypy.subprocess.run")
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_included_paths_invalid_type(
        self,
        mock_get_exe: MagicMock,
        mock_filter: MagicMock,
        mock_subprocess_run: MagicMock,
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
        mock_subprocess_run.assert_not_called()


class TestMypyLinterRunWithoutFiles:
    @patch("scripts.dev.linter.linters.mypy.subprocess.run")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_full_repo_scan(
        self,
        mock_get_exe: MagicMock,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """Test run without files (full repo scan) (lines 47-48, branch 30 False)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_subprocess_run.return_value = CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        linter = MypyLinter()
        result = linter.run(files=None)

        assert result.success is True
        assert result.errors == []
        mock_subprocess_run.assert_called_once()
        call_args = mock_subprocess_run.call_args[0][0]
        assert call_args == ["/usr/bin/uv", "run", "mypy", "--output=json"]


class TestMypyLinterMixedFiles:
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.subprocess.run")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_mixed_test_and_app_files(
        self,
        mock_get_exe: MagicMock,
        mock_subprocess_run: MagicMock,
        mock_filter: MagicMock,
    ) -> None:
        """Test run with mix of test and app files (lines 38-42)."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (["app/main.py", "scripts/dev/utils.py"], None)
        mock_subprocess_run.return_value = CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        linter = MypyLinter()
        result = linter.run(
            files=[
                "tests/test_main.py",  # Should be filtered
                "app/main.py",  # Should be included
                "scripts/dev/utils.py",  # Should be included
            ]
        )

        assert result.success is True
        assert result.errors == []
        mock_subprocess_run.assert_called_once()
        call_args = mock_subprocess_run.call_args[0][0]
        assert "app/main.py" in call_args
        assert "scripts/dev/utils.py" in call_args
        assert "tests/test_main.py" not in call_args


class TestMypyJsonParsing:
    def test_parse_empty_output(self) -> None:
        """Test parsing empty JSON output."""
        errors = _parse_mypy_json("")
        assert errors == []

    def test_parse_single_error(self) -> None:
        """Test parsing single mypy error."""
        json_output = '{"file": "test.py", "line": 10, "column": 5, "message": "Type error", "hint": null, "code": "assignment", "severity": "error"}'
        errors = _parse_mypy_json(json_output)

        assert len(errors) == 1
        error = errors[0]
        assert error.file == "test.py"
        assert error.line == 10
        assert error.column == 5
        assert error.code == "assignment"
        assert error.message == "Type error"
        assert error.context is None
        assert error.fix_available is False

    def test_parse_multiple_errors(self) -> None:
        """Test parsing multiple mypy errors."""
        json_output = """{"file": "test.py", "line": 10, "column": 5, "message": "Type error 1", "hint": null, "code": "assignment", "severity": "error"}
{"file": "test.py", "line": 20, "column": 8, "message": "Type error 2", "hint": "Consider using Optional", "code": "arg-type", "severity": "error"}"""
        errors = _parse_mypy_json(json_output)

        assert len(errors) == 2
        assert errors[0].line == 10
        assert errors[0].context is None
        assert errors[1].line == 20
        assert errors[1].context == "Consider using Optional"

    def test_parse_with_invalid_json(self) -> None:
        """Test parsing with malformed JSON lines."""
        json_output = """{"file": "test.py", "line": 10}
invalid json line
{"file": "test.py", "line": 20, "column": 5, "message": "Error", "code": "test", "severity": "error"}"""
        errors = _parse_mypy_json(json_output)

        # Should skip invalid line and parse valid one
        assert len(errors) == 1
        assert errors[0].line == 20

    def test_parse_filters_non_errors(self) -> None:
        """Test that non-error severities are filtered out."""
        json_output = """{"file": "test.py", "line": 10, "column": 5, "message": "Note", "code": "note", "severity": "note"}
{"file": "test.py", "line": 20, "column": 8, "message": "Error", "code": "test", "severity": "error"}"""
        errors = _parse_mypy_json(json_output)

        # Should only include error severity
        assert len(errors) == 1
        assert errors[0].line == 20


class TestMypyLinterWithErrors:
    @patch("scripts.dev.linter.linters.mypy.filter_files_with_config")
    @patch("scripts.dev.linter.linters.mypy.subprocess.run")
    @patch("scripts.dev.linter.linters.mypy.get_executable")
    def test_run_with_mypy_errors(
        self,
        mock_get_exe: MagicMock,
        mock_subprocess_run: MagicMock,
        mock_filter: MagicMock,
    ) -> None:
        """Test run when mypy reports errors."""
        mock_get_exe.return_value = "/usr/bin/uv"
        mock_filter.return_value = (["test.py"], None)

        # Simulate mypy JSON output with errors
        json_output = '{"file": "test.py", "line": 10, "column": 5, "message": "Type error", "hint": null, "code": "assignment", "severity": "error"}'
        mock_subprocess_run.return_value = CompletedProcess(
            args=[], returncode=1, stdout=json_output, stderr=""
        )

        linter = MypyLinter()
        result = linter.run(files=["test.py"])

        assert result.success is False
        assert len(result.errors) == 1
        assert result.errors[0].file == "test.py"
        assert result.errors[0].line == 10
        assert result.errors[0].code == "assignment"
