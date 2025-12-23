"""Tests for import_local_tasks_command module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.pr.commands.import_local_tasks_command import import_local_tasks_command


class TestImportLocalTasksCommand:
    """Tests for the import_local_tasks_command function."""

    def test_creates_output_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Test that output directory is created if it doesn't exist."""
        output_dir = tmp_path / "new_dir"
        assert not output_dir.exists()

        result = import_local_tasks_command(output_dir, [])

        assert output_dir.exists()
        assert result == 0

    def test_imports_single_body_file(self, tmp_path: Path) -> None:
        """Test importing a single body file."""
        output_dir = tmp_path / "output"
        body_file = tmp_path / "task1.txt"
        body_file.write_text("Task content here")

        result = import_local_tasks_command(output_dir, [body_file])

        # Check JSON file was created
        task_file = output_dir / "local_0.json"
        assert task_file.exists()
        content = json.loads(task_file.read_text())
        assert content["index"] == 0
        assert content["origin"] == "LOCAL"
        assert content["content"] == "Task content here"
        assert content["comments"][0]["body"] == "Task content here"
        assert content["comments"][0]["author"] == "local"

        # Check body file was deleted
        assert not body_file.exists()
        assert result == 0

    def test_imports_multiple_body_files(self, tmp_path: Path) -> None:
        """Test importing multiple body files."""
        output_dir = tmp_path / "output"
        body_files = []
        for i in range(3):
            body_file = tmp_path / f"task{i}.txt"
            body_file.write_text(f"Task {i} content")
            body_files.append(body_file)

        result = import_local_tasks_command(output_dir, body_files)

        for i in range(3):
            task_file = output_dir / f"local_{i}.json"
            assert task_file.exists()
            content = json.loads(task_file.read_text())
            assert content["index"] == i
            assert content["content"] == f"Task {i} content"

        # Check all body files were deleted
        for body_file in body_files:
            assert not body_file.exists()

        assert result == 0

    def test_skips_missing_body_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that missing body files are skipped with warning."""
        output_dir = tmp_path / "output"
        existing_file = tmp_path / "exists.txt"
        existing_file.write_text("Existing content")
        missing_file = tmp_path / "missing.txt"

        result = import_local_tasks_command(output_dir, [missing_file, existing_file])

        # Only one task should be created (for index 1)
        assert not (output_dir / "local_0.json").exists()  # Missing file was at index 0
        assert (output_dir / "local_1.json").exists()

        captured = capsys.readouterr()
        assert "Warning: Body file not found" in captured.err
        assert result == 0

    def test_strips_whitespace_from_body_content(self, tmp_path: Path) -> None:
        """Test that body content whitespace is stripped."""
        output_dir = tmp_path / "output"
        body_file = tmp_path / "task.txt"
        body_file.write_text("  \n  Content with whitespace  \n  ")

        result = import_local_tasks_command(output_dir, [body_file])

        task_file = output_dir / "local_0.json"
        content = json.loads(task_file.read_text())
        assert content["content"] == "Content with whitespace"
        assert result == 0

    def test_handles_empty_body_file(self, tmp_path: Path) -> None:
        """Test handling of empty body file."""
        output_dir = tmp_path / "output"
        body_file = tmp_path / "empty.txt"
        body_file.write_text("")

        result = import_local_tasks_command(output_dir, [body_file])

        task_file = output_dir / "local_0.json"
        assert task_file.exists()
        content = json.loads(task_file.read_text())
        assert content["content"] == ""
        assert result == 0

    def test_prints_summary(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that summary is printed at the end."""
        output_dir = tmp_path / "output"
        body_files = [tmp_path / f"task{i}.txt" for i in range(3)]
        for f in body_files:
            f.write_text("content")

        result = import_local_tasks_command(output_dir, body_files)

        captured = capsys.readouterr()
        assert "Imported 3 local task(s)" in captured.out
        assert result == 0

    def test_prints_created_and_deleted_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that created and deleted files are printed."""
        output_dir = tmp_path / "output"
        body_file = tmp_path / "task.txt"
        body_file.write_text("content")

        result = import_local_tasks_command(output_dir, [body_file])

        captured = capsys.readouterr()
        assert "Created:" in captured.out
        assert "local_0.json" in captured.out
        assert "Deleted:" in captured.out
        assert "task.txt" in captured.out
        assert result == 0

    def test_returns_zero_for_empty_input(self, tmp_path: Path) -> None:
        """Test that command returns 0 for empty input list."""
        output_dir = tmp_path / "output"

        result = import_local_tasks_command(output_dir, [])

        assert result == 0

    def test_handles_utf8_content(self, tmp_path: Path) -> None:
        """Test handling of UTF-8 content in body files."""
        output_dir = tmp_path / "output"
        body_file = tmp_path / "unicode.txt"
        body_file.write_text("Unicode content: \u4e2d\u6587 \u00e9\u00e8")

        result = import_local_tasks_command(output_dir, [body_file])

        task_file = output_dir / "local_0.json"
        content = json.loads(task_file.read_text())
        assert "\u4e2d\u6587" in content["content"]
        assert result == 0
