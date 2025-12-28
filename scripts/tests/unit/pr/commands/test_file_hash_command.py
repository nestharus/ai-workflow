import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.pr.commands.file_hash_command import (
    _hash_file,
    file_hash_command,
    file_hash_compare_command,
)


class TestFileHashCommand:
    def test_reads_files_from_stdin(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that files are read from stdin and hashed."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        stdin_content = f"{file1}\n{file2}\n"
        with patch("sys.stdin", StringIO(stdin_content)):
            result = file_hash_command()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        # Keys are resolved absolute paths
        assert str(file1.resolve()) in output
        assert str(file2.resolve()) in output

    def test_skips_empty_lines(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that empty lines are skipped."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("content")

        stdin_content = f"\n{file1}\n\n"
        with patch("sys.stdin", StringIO(stdin_content)):
            result = file_hash_command()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert len(output) == 1

    def test_skips_missing_files_with_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that missing files are skipped with a notice."""
        existing = tmp_path / "exists.txt"
        existing.write_text("content")
        missing = tmp_path / "missing.txt"

        stdin_content = f"{existing}\n{missing}\n"
        with patch("sys.stdin", StringIO(stdin_content)):
            result = file_hash_command()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        # Keys are resolved absolute paths
        assert str(existing.resolve()) in output
        assert str(missing.resolve()) not in output
        # Verify notice was logged to stderr (lower severity than errors)
        assert "Notice:" in captured.err
        assert "path does not exist" in captured.err
        assert str(missing) in captured.err

    def test_resolves_relative_paths_with_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that relative paths are resolved against root."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        stdin_content = "file.txt\n"
        with patch("sys.stdin", StringIO(stdin_content)):
            result = file_hash_command(root=tmp_path)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        # Keys are resolved absolute paths
        assert str(file_path.resolve()) in output

    def test_outputs_sorted_keys(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that output JSON has sorted keys."""
        file_z = tmp_path / "z.txt"
        file_a = tmp_path / "a.txt"
        file_m = tmp_path / "m.txt"
        file_z.write_text("z")
        file_a.write_text("a")
        file_m.write_text("m")

        stdin_content = "z.txt\na.txt\nm.txt\n"
        with patch("sys.stdin", StringIO(stdin_content)):
            result = file_hash_command(root=tmp_path)

        assert result == 0
        captured = capsys.readouterr()
        # Parse JSON and verify keys are in sorted order
        output = json.loads(captured.out)
        output_keys = list(output.keys())
        # Build expected sorted keys using resolved absolute paths
        expected_keys = sorted(
            [
                str(file_a.resolve()),
                str(file_m.resolve()),
                str(file_z.resolve()),
            ]
        )
        assert output_keys == expected_keys

    def test_skips_files_with_empty_hash_and_logs_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that files with empty hash (unreadable) are skipped and error is logged."""
        good_file = tmp_path / "good.txt"
        bad_file = tmp_path / "bad.txt"
        good_file.write_text("content")
        bad_file.write_text("content")

        def mock_hash(p: Path) -> tuple[str, str | None]:
            # Return error for bad.txt, valid hash for good.txt
            if p.name == "bad.txt":
                return "", "Permission denied"
            return "abc123", None

        stdin_content = f"{good_file}\n{bad_file}\n"
        with (
            patch("sys.stdin", StringIO(stdin_content)),
            patch(
                "scripts.pr.commands.file_hash_command._hash_file",
                side_effect=mock_hash,
            ),
        ):
            result = file_hash_command()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        # Keys are resolved absolute paths
        assert str(good_file.resolve()) in output
        assert str(bad_file.resolve()) not in output
        # Verify error message was logged to stderr (higher severity than notices)
        assert "Error:" in captured.err
        assert "Permission denied" in captured.err
        assert str(bad_file) in captured.err

    def test_deduplicates_same_file_via_different_paths(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that same file passed via relative and absolute paths is deduplicated."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        # Pass the same file via both relative and absolute paths
        stdin_content = f"file.txt\n{file_path}\n"
        with patch("sys.stdin", StringIO(stdin_content)):
            result = file_hash_command(root=tmp_path)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        # Only one entry should exist (deduplicated by resolved path)
        assert len(output) == 1
        assert str(file_path.resolve()) in output

    def test_deduplicates_missing_files_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that duplicate missing paths only produce one notice."""
        missing = tmp_path / "missing.txt"

        # Pass the same missing file multiple times
        stdin_content = f"{missing}\n{missing}\n{missing}\n"
        with patch("sys.stdin", StringIO(stdin_content)):
            result = file_hash_command()

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        # No entries should exist since file is missing
        assert len(output) == 0
        # Only one notice should be printed (not three)
        notice_count = captured.err.count("Notice:")
        assert notice_count == 1


class TestFileHashCompareCommand:
    def test_io_error_returns_two(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that I/O errors return exit code 2."""
        file1 = tmp_path / "file1.json"
        file2 = tmp_path / "file2.json"
        file1.write_text(json.dumps({}))
        file2.write_text(json.dumps({}))

        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            result = file_hash_compare_command(file1, file2)

        assert result == 2
        captured = capsys.readouterr()
        assert "I/O error reading file" in captured.err
