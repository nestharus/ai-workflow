"""Tests for scripts.utils module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from scripts import utils
from scripts.utils import (
    StdoutCaptureError,
    build_concat_parser,
    iter_directory_files,
    parse_concat_args,
    run_command_with_tee,
    utc_timestamp,
    write_concatenated_files,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestUtcTimestamp:
    """Tests for utc_timestamp function."""

    def test_returns_string(self) -> None:
        """Should return a string."""
        result = utc_timestamp()
        assert isinstance(result, str)

    def test_format_iso8601_basic(self) -> None:
        """Should return ISO 8601 basic format."""
        result = utc_timestamp()
        # Format: YYYYMMDDTHHMMSSZ
        assert len(result) == 16
        assert result[8] == "T"
        assert result[15] == "Z"

    def test_contains_only_valid_chars(self) -> None:
        """Should contain only digits, T, and Z."""
        result = utc_timestamp()
        allowed = set("0123456789TZ")
        assert all(c in allowed for c in result)


class TestRunCommandWithTee:
    """Tests for run_command_with_tee function."""

    def test_successful_command(self, fs: FakeFilesystem) -> None:
        """Should capture output and return exit code 0."""
        # pyfakefs doesn't intercept subprocess, so we need to mock it
        output_path = Path("/fake/output.txt")
        fs.create_dir("/fake")

        mock_stdout = MagicMock()
        mock_stdout.__iter__ = MagicMock(return_value=iter(["line1\n", "line2\n"]))

        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        mock_process.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_process):
            with patch("sys.stdout.write"):
                result = run_command_with_tee(["echo", "test"], output_path)

        assert result == 0

    def test_failed_command(self, fs: FakeFilesystem) -> None:
        """Should return non-zero exit code on failure."""
        output_path = Path("/fake/output.txt")
        fs.create_dir("/fake")

        mock_stdout = MagicMock()
        mock_stdout.__iter__ = MagicMock(return_value=iter([]))

        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        mock_process.wait.return_value = 1

        with patch("subprocess.Popen", return_value=mock_process):
            result = run_command_with_tee(["false"], output_path)

        assert result == 1

    def test_stdout_capture_error(self, fs: FakeFilesystem) -> None:
        """Should raise StdoutCaptureError when stdout is None."""
        output_path = Path("/fake/output.txt")
        fs.create_dir("/fake")

        mock_process = MagicMock()
        mock_process.stdout = None

        with patch("subprocess.Popen", return_value=mock_process):
            with pytest.raises(StdoutCaptureError):
                run_command_with_tee(["echo", "test"], output_path)

        mock_process.kill.assert_called_once()


class TestIterDirectoryFiles:
    """Tests for iter_directory_files function."""

    def test_recursive_search(self, fs: FakeFilesystem) -> None:
        """Should find files recursively."""
        # Patch REPO_ROOT to use fake filesystem
        with patch.object(utils, "REPO_ROOT", Path("/fake/repo")):
            fs.create_dir("/fake/repo/test_dir/subdir")
            fs.create_file("/fake/repo/test_dir/file1.py", contents="# file1")
            fs.create_file("/fake/repo/test_dir/subdir/file2.py", contents="# file2")

            result = iter_directory_files(Path("/fake/repo/test_dir"), recursive=True)

            assert len(result) == 2
            filenames = [p.name for p in result]
            assert "file1.py" in filenames
            assert "file2.py" in filenames

    def test_non_recursive_search(self, fs: FakeFilesystem) -> None:
        """Should find only top-level files when non-recursive."""
        with patch.object(utils, "REPO_ROOT", Path("/fake/repo")):
            fs.create_dir("/fake/repo/test_dir/subdir")
            fs.create_file("/fake/repo/test_dir/file1.py", contents="# file1")
            fs.create_file("/fake/repo/test_dir/subdir/file2.py", contents="# file2")

            result = iter_directory_files(Path("/fake/repo/test_dir"), recursive=False)

            assert len(result) == 1
            assert result[0].name == "file1.py"

    def test_excludes_pycache(self, fs: FakeFilesystem) -> None:
        """Should exclude __pycache__ directories."""
        with patch.object(utils, "REPO_ROOT", Path("/fake/repo")):
            fs.create_dir("/fake/repo/test_dir/__pycache__")
            fs.create_file("/fake/repo/test_dir/file1.py", contents="# file1")
            fs.create_file("/fake/repo/test_dir/__pycache__/cache.pyc", contents="bytecode")

            result = iter_directory_files(Path("/fake/repo/test_dir"), recursive=True)

            assert len(result) == 1
            assert result[0].name == "file1.py"

    def test_directory_not_found(self, fs: FakeFilesystem) -> None:
        """Should raise FileNotFoundError for non-existent directory."""
        with pytest.raises(FileNotFoundError) as exc_info:
            iter_directory_files(Path("/nonexistent"))

        assert "Directory not found" in str(exc_info.value)


class TestBuildConcatParser:
    """Tests for build_concat_parser function."""

    def test_creates_parser(self) -> None:
        """Should create an argument parser."""
        parser = build_concat_parser("app", Path("/default/output.txt"))
        assert parser is not None

    def test_parser_has_output_argument(self) -> None:
        """Should have --output argument."""
        parser = build_concat_parser("app", Path("/default/output.txt"))
        args = parser.parse_args(["--output", "/custom/output.txt"])
        assert args.output == Path("/custom/output.txt")

    def test_default_output(self) -> None:
        """Should use default output when not specified."""
        parser = build_concat_parser("app", Path("/default/output.txt"))
        args = parser.parse_args([])
        assert args.output == Path("/default/output.txt")


class TestParseConcatArgs:
    """Tests for parse_concat_args function."""

    def test_with_custom_output(self) -> None:
        """Should parse custom output path."""
        args = parse_concat_args("app", Path("/default.txt"), ["--output", "/custom.txt"])
        assert args.output == Path("/custom.txt")

    def test_with_default_output(self) -> None:
        """Should use default output when none provided."""
        args = parse_concat_args("app", Path("/default.txt"), [])
        assert args.output == Path("/default.txt")


class TestWriteConcatenatedFiles:
    """Tests for write_concatenated_files function."""

    def test_writes_files_with_headings(self, fs: FakeFilesystem) -> None:
        """Should write files with path headings."""
        with patch.object(utils, "REPO_ROOT", Path("/fake/repo")):
            fs.create_dir("/fake/repo/src")
            fs.create_file("/fake/repo/src/file1.py", contents="# content1\n")
            fs.create_file("/fake/repo/src/file2.py", contents="# content2\n")

            output_path = Path("/fake/repo/output.txt")
            files = [Path("/fake/repo/src/file1.py"), Path("/fake/repo/src/file2.py")]

            write_concatenated_files(files, output_path)

            content = output_path.read_text()
            assert "===== src/file1.py =====" in content
            assert "===== src/file2.py =====" in content
            assert "# content1" in content
            assert "# content2" in content

    def test_creates_parent_directories(self, fs: FakeFilesystem) -> None:
        """Should create parent directories if needed."""
        with patch.object(utils, "REPO_ROOT", Path("/fake/repo")):
            fs.create_dir("/fake/repo/src")
            fs.create_file("/fake/repo/src/file1.py", contents="# content\n")

            output_path = Path("/fake/repo/nested/deep/output.txt")
            files = [Path("/fake/repo/src/file1.py")]

            write_concatenated_files(files, output_path)

            assert output_path.exists()

    def test_excludes_output_file_from_list(self, fs: FakeFilesystem) -> None:
        """Should not include output file in concatenation."""
        with patch.object(utils, "REPO_ROOT", Path("/fake/repo")):
            fs.create_dir("/fake/repo/src")
            fs.create_file("/fake/repo/src/file1.py", contents="# content1\n")
            output_path = Path("/fake/repo/src/output.txt")
            fs.create_file(str(output_path), contents="old content")

            files = [Path("/fake/repo/src/file1.py"), output_path]

            write_concatenated_files(files, output_path)

            content = output_path.read_text()
            assert "old content" not in content
            assert "# content1" in content

    def test_adds_trailing_newline(self, fs: FakeFilesystem) -> None:
        """Should add trailing newline if content doesn't end with one."""
        with patch.object(utils, "REPO_ROOT", Path("/fake/repo")):
            fs.create_dir("/fake/repo/src")
            fs.create_file("/fake/repo/src/file1.py", contents="no trailing newline")

            output_path = Path("/fake/repo/output.txt")
            files = [Path("/fake/repo/src/file1.py")]

            write_concatenated_files(files, output_path)

            content = output_path.read_text()
            assert content.endswith("\n")


class TestStdoutCaptureError:
    """Tests for StdoutCaptureError exception."""

    def test_default_message(self) -> None:
        """Should have default message."""
        error = StdoutCaptureError()
        assert "Failed to capture stdout" in str(error)

    def test_custom_message(self) -> None:
        """Should accept custom message."""
        error = StdoutCaptureError("Custom error message")
        assert "Custom error message" in str(error)
