"""Tests for aggregate_tasks_command module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.pr.commands.aggregate_tasks_command import (
    GLOBAL_TASKS_KEY,
    TASK_PATTERNS,
    aggregate_tasks_command,
)


class TestAggregateTasksCommand:
    """Tests for the aggregate_tasks_command function."""

    def test_returns_error_for_missing_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that missing input directory returns error code."""
        missing_dir = tmp_path / "missing"

        result = aggregate_tasks_command(missing_dir)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Input directory not found" in captured.err
        assert str(missing_dir) in captured.err

    def test_returns_error_for_empty_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that empty directory returns error code."""
        input_dir = tmp_path / "empty"
        input_dir.mkdir()

        result = aggregate_tasks_command(input_dir)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: No task files found" in captured.err
        # Check that searched patterns are mentioned
        for pattern in TASK_PATTERNS:
            assert pattern in captured.err

    def test_aggregates_coderabbit_tasks_by_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test aggregating coderabbit task files by file path."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Create task files for same file
        (input_dir / "coderabbit_0.json").write_text(
            json.dumps({"path": "app/main.py", "content": "Task 1"})
        )
        (input_dir / "coderabbit_1.json").write_text(
            json.dumps({"path": "app/main.py", "content": "Task 2"})
        )
        (input_dir / "coderabbit_2.json").write_text(
            json.dumps({"path": "app/utils.py", "content": "Task 3"})
        )

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["task_count"] == 3
        assert "app/main.py" in output["files"]
        assert "app/utils.py" in output["files"]
        assert len(output["tasks_by_file"]["app/main.py"]) == 2
        assert len(output["tasks_by_file"]["app/utils.py"]) == 1

    def test_aggregates_thread_tasks(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test aggregating thread task files."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        (input_dir / "thread_0.json").write_text(
            json.dumps({"path": "app/service.py", "content": "Thread task"})
        )

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["task_count"] == 1
        assert "app/service.py" in output["files"]
        assert "thread_0.json" in output["tasks_by_file"]["app/service.py"]

    def test_aggregates_local_tasks(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test aggregating local task files."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        (input_dir / "local_0.json").write_text(
            json.dumps({"path": "scripts/main.py", "content": "Local task"})
        )

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["task_count"] == 1
        assert "scripts/main.py" in output["files"]

    def test_groups_tasks_without_path_under_global(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that tasks without path field go to __global__ bucket."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Task without path
        (input_dir / "local_0.json").write_text(json.dumps({"content": "Global task without path"}))
        # Task with path
        (input_dir / "local_1.json").write_text(
            json.dumps({"path": "app/main.py", "content": "File-specific task"})
        )

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["task_count"] == 2
        assert GLOBAL_TASKS_KEY not in output["files"]  # Global not in files list
        assert GLOBAL_TASKS_KEY in output["tasks_by_file"]
        assert "local_0.json" in output["tasks_by_file"][GLOBAL_TASKS_KEY]

    def test_handles_malformed_json_with_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that malformed JSON files are skipped with warning."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Valid task
        (input_dir / "coderabbit_0.json").write_text(
            json.dumps({"path": "app/main.py", "content": "Valid"})
        )
        # Invalid JSON
        (input_dir / "coderabbit_1.json").write_text("not valid json")

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: Invalid JSON in file" in captured.err
        assert "coderabbit_1.json" in captured.err
        output = json.loads(captured.out)
        assert output["task_count"] == 1

    def test_handles_unreadable_file_with_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that unreadable files are skipped with distinct warning message."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Valid task
        (input_dir / "coderabbit_0.json").write_text(
            json.dumps({"path": "app/main.py", "content": "Valid"})
        )
        # Create a file that will fail to read (a directory with .json name)
        unreadable = input_dir / "coderabbit_1.json"
        unreadable.mkdir()

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning: Failed to read file" in captured.err
        assert "coderabbit_1.json" in captured.err
        output = json.loads(captured.out)
        assert output["task_count"] == 1

    def test_sorts_files_alphabetically(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that output files list is sorted alphabetically."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Create tasks in non-alphabetical order
        (input_dir / "coderabbit_0.json").write_text(json.dumps({"path": "z_last.py"}))
        (input_dir / "coderabbit_1.json").write_text(json.dumps({"path": "a_first.py"}))
        (input_dir / "coderabbit_2.json").write_text(json.dumps({"path": "m_middle.py"}))

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["files"] == ["a_first.py", "m_middle.py", "z_last.py"]

    def test_ignores_other_json_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that other JSON files are ignored."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Task file that should be found
        (input_dir / "coderabbit_0.json").write_text(json.dumps({"path": "app/main.py"}))
        # Other JSON that should be ignored
        (input_dir / "config.json").write_text(json.dumps({"setting": "value"}))
        (input_dir / "other.json").write_text(json.dumps({"data": "ignored"}))

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["task_count"] == 1

    def test_handles_mixed_task_types(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test aggregating mixed task file types for same file."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        (input_dir / "coderabbit_0.json").write_text(
            json.dumps({"path": "app/main.py", "origin": "CODERABBIT"})
        )
        (input_dir / "thread_0.json").write_text(
            json.dumps({"path": "app/main.py", "origin": "THREAD"})
        )
        (input_dir / "local_0.json").write_text(
            json.dumps({"path": "app/main.py", "origin": "LOCAL"})
        )

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["task_count"] == 3
        assert len(output["tasks_by_file"]["app/main.py"]) == 3
        # Check all task files are present
        task_filenames = output["tasks_by_file"]["app/main.py"]
        assert "coderabbit_0.json" in task_filenames
        assert "thread_0.json" in task_filenames
        assert "local_0.json" in task_filenames

    def test_sorts_task_filenames_within_each_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that task filenames within each file's list are sorted alphabetically."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Create tasks in reverse alphabetical order
        (input_dir / "thread_9.json").write_text(json.dumps({"path": "app/main.py"}))
        (input_dir / "local_5.json").write_text(json.dumps({"path": "app/main.py"}))
        (input_dir / "coderabbit_1.json").write_text(json.dumps({"path": "app/main.py"}))

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        # Task filenames should be sorted alphabetically
        assert output["tasks_by_file"]["app/main.py"] == [
            "coderabbit_1.json",
            "local_5.json",
            "thread_9.json",
        ]

    def test_files_only_outputs_plain_list(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that --files-only outputs just file paths, one per line."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        (input_dir / "coderabbit_0.json").write_text(json.dumps({"path": "z_last.py"}))
        (input_dir / "coderabbit_1.json").write_text(json.dumps({"path": "a_first.py"}))
        (input_dir / "coderabbit_2.json").write_text(json.dumps({"path": "m_middle.py"}))

        result = aggregate_tasks_command(input_dir, files_only=True)

        assert result == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert lines == ["a_first.py", "m_middle.py", "z_last.py"]

    def test_files_only_excludes_global_tasks(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that --files-only excludes tasks without path."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        (input_dir / "coderabbit_0.json").write_text(json.dumps({"path": "app/main.py"}))
        (input_dir / "local_0.json").write_text(json.dumps({"content": "Global task"}))

        result = aggregate_tasks_command(input_dir, files_only=True)

        assert result == 0
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert lines == ["app/main.py"]
        assert "__global__" not in captured.out

    def test_handles_non_dict_json_with_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that non-dict JSON values are treated as global tasks with warning."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Valid dict task
        (input_dir / "coderabbit_0.json").write_text(
            json.dumps({"path": "app/main.py", "content": "Valid"})
        )
        # JSON array (not a dict)
        (input_dir / "coderabbit_1.json").write_text(json.dumps(["item1", "item2"]))
        # JSON string (not a dict)
        (input_dir / "coderabbit_2.json").write_text(json.dumps("just a string"))
        # JSON number (not a dict)
        (input_dir / "coderabbit_3.json").write_text(json.dumps(42))

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()

        # Check warnings for each non-dict type
        assert "Warning: Expected JSON object in coderabbit_1.json" in captured.err
        assert "got list" in captured.err
        assert "Warning: Expected JSON object in coderabbit_2.json" in captured.err
        assert "got str" in captured.err
        assert "Warning: Expected JSON object in coderabbit_3.json" in captured.err
        assert "got int" in captured.err

        # Verify they are treated as global tasks
        output = json.loads(captured.out)
        assert output["task_count"] == 4
        assert GLOBAL_TASKS_KEY in output["tasks_by_file"]
        global_tasks = output["tasks_by_file"][GLOBAL_TASKS_KEY]
        assert "coderabbit_1.json" in global_tasks
        assert "coderabbit_2.json" in global_tasks
        assert "coderabbit_3.json" in global_tasks

    def test_handles_non_string_path_with_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that non-string path values are treated as global tasks with warning."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()

        # Valid string path
        (input_dir / "coderabbit_0.json").write_text(
            json.dumps({"path": "app/main.py", "content": "Valid"})
        )
        # Integer path (not a string)
        (input_dir / "coderabbit_1.json").write_text(
            json.dumps({"path": 123, "content": "Integer path"})
        )
        # List path (not a string)
        (input_dir / "coderabbit_2.json").write_text(
            json.dumps({"path": ["app", "main.py"], "content": "List path"})
        )
        # Empty string path (should be treated as global)
        (input_dir / "coderabbit_3.json").write_text(
            json.dumps({"path": "", "content": "Empty path"})
        )
        # Whitespace-only path (should be treated as global)
        (input_dir / "coderabbit_4.json").write_text(
            json.dumps({"path": "   ", "content": "Whitespace path"})
        )

        result = aggregate_tasks_command(input_dir)

        assert result == 0
        captured = capsys.readouterr()

        # Check warnings for invalid path types
        assert "Warning: Invalid 'path' in coderabbit_1.json" in captured.err
        assert "expected non-empty string, got int=123" in captured.err
        assert "Warning: Invalid 'path' in coderabbit_2.json" in captured.err
        assert "expected non-empty string, got list=" in captured.err

        # Verify output
        output = json.loads(captured.out)
        assert output["task_count"] == 5

        # Valid path should work
        assert "app/main.py" in output["files"]
        assert "coderabbit_0.json" in output["tasks_by_file"]["app/main.py"]

        # Invalid/empty paths should be in global bucket
        assert GLOBAL_TASKS_KEY in output["tasks_by_file"]
        global_tasks = output["tasks_by_file"][GLOBAL_TASKS_KEY]
        assert "coderabbit_1.json" in global_tasks  # int path
        assert "coderabbit_2.json" in global_tasks  # list path
        assert "coderabbit_3.json" in global_tasks  # empty string
        assert "coderabbit_4.json" in global_tasks  # whitespace-only
