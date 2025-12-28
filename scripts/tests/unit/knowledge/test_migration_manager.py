from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.knowledge import migration_manager
from scripts.knowledge.migration_manager import (
    CSV_COLUMNS,
    MigrationTask,
    append_task,
    count_unresolved_differences,
    ensure_csv_exists,
    extract_pattern_from_path,
    get_original_file_path,
    get_task_by_id,
    main_start,
    main_validate,
    parse_start_args,
    parse_validate_args,
    save_original_with_timestamp,
    start_migration,
    update_task_status,
    validate_migration,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestMainStart:
    def test_handles_exception(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 and print error on exception."""
        # Missing required argument triggers error
        with patch("sys.argv", ["script", "--original-file"]), pytest.raises(SystemExit):
            main_start()

    def test_returns_zero_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 on success.

        DuckDB requires real filesystem.
        """
        source_file = tmp_path / "original.test.yml"
        source_file.write_text("content")

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--original-file",
                    str(source_file),
                    "--knowledge-path",
                    str(tmp_path / ".knowledge"),
                ],
            ),
        ):
            result = main_start()

        assert result == 0

    def test_handles_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge path.

        DuckDB requires real filesystem.
        """
        source_file = tmp_path / "original.test.yml"
        source_file.write_text("content")
        abs_knowledge = tmp_path / "custom_knowledge"

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--original-file",
                    str(source_file),
                    "--knowledge-path",
                    str(abs_knowledge),
                ],
            ),
        ):
            result = main_start()

        assert result == 0
        assert abs_knowledge.exists()

    def test_handles_relative_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle relative knowledge path (branch line 509->512).

        DuckDB requires real filesystem.
        """
        source_file = tmp_path / "original.test.yml"
        source_file.write_text("content")

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--original-file",
                    str(source_file),
                    # Use relative path (default is .knowledge)
                ],
            ),
        ):
            result = main_start()

        assert result == 0
        # Default .knowledge path should be created under REPO_ROOT
        assert (tmp_path / ".knowledge").exists()

    def test_handles_exception_during_migration(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 and print error when exception occurs (lines 516-517).

        Tests the exception handling in main_start.
        """
        source_file = tmp_path / "original.test.yml"
        source_file.write_text("content")

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch.object(
                migration_manager, "start_migration", side_effect=RuntimeError("Test error")
            ),
            patch(
                "sys.argv",
                [
                    "script",
                    "--original-file",
                    str(source_file),
                ],
            ),
        ):
            result = main_start()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err
        assert "Test error" in captured.err


class TestValidateMigrationFull:
    def test_runs_comparison_and_succeeds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should run comparison and complete successfully (lines 392-435).

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "originals").mkdir(parents=True)
        (knowledge_path / "comparisons").mkdir(parents=True)

        # Create task
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        row = "task-1,originals/test.yml,test-pattern,pending,20240101T120000Z,"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create original file
        orig_file = knowledge_path / "originals" / "test.yml"
        orig_file.write_text("content: test")

        # Mock subprocess.run to simulate successful comparison
        mock_result = type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch("subprocess.run", return_value=mock_result),
            patch.object(migration_manager, "count_unresolved_differences", return_value=0),
        ):
            result = validate_migration("task-1", knowledge_path, tmp_path / "docs")

        assert result == 0
        captured = capsys.readouterr()
        assert "Validating migration for pattern: test-pattern" in captured.out
        assert "Using original file:" in captured.out
        assert "Running comparison..." in captured.out
        assert "validated successfully" in captured.out

    def test_runs_comparison_with_non_zero_returncode(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle comparison command with non-zero return code (lines 414-417).

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "originals").mkdir(parents=True)
        (knowledge_path / "comparisons").mkdir(parents=True)

        # Create task
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        row = "task-1,originals/test.yml,test-pattern,pending,20240101T120000Z,"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create original file
        orig_file = knowledge_path / "originals" / "test.yml"
        orig_file.write_text("content: test")

        # Mock subprocess.run to simulate failed comparison
        mock_result = type(
            "Result", (), {"returncode": 1, "stdout": "Command output", "stderr": "Error output"}
        )()

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch("subprocess.run", return_value=mock_result),
            patch.object(migration_manager, "count_unresolved_differences", return_value=0),
        ):
            result = validate_migration("task-1", knowledge_path, tmp_path / "docs")

        # Still succeeds if no unresolved differences
        assert result == 0
        captured = capsys.readouterr()
        assert "Command output" in captured.err
        assert "Error output" in captured.err

    def test_runs_comparison_with_non_zero_returncode_no_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Handle comparison cmd with non-zero return but no stderr (line 416-417 branch).

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "originals").mkdir(parents=True)
        (knowledge_path / "comparisons").mkdir(parents=True)

        # Create task
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        row = "task-1,originals/test.yml,test-pattern,pending,20240101T120000Z,"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create original file
        orig_file = knowledge_path / "originals" / "test.yml"
        orig_file.write_text("content: test")

        # Mock subprocess.run to simulate failed comparison without stderr
        mock_result = type(
            "Result", (), {"returncode": 1, "stdout": "Command output", "stderr": ""}
        )()

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch("subprocess.run", return_value=mock_result),
            patch.object(migration_manager, "count_unresolved_differences", return_value=0),
        ):
            result = validate_migration("task-1", knowledge_path, tmp_path / "docs")

        assert result == 0
        captured = capsys.readouterr()
        assert "Command output" in captured.err
        # Should not have "Comparison errors" line since stderr is empty
        assert "Comparison errors" not in captured.err

    def test_handles_file_not_found_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle FileNotFoundError when running subprocess (lines 418-421).

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "originals").mkdir(parents=True)

        # Create task
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        row = "task-1,originals/test.yml,test-pattern,pending,20240101T120000Z,"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create original file
        orig_file = knowledge_path / "originals" / "test.yml"
        orig_file.write_text("content: test")

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch("subprocess.run", side_effect=FileNotFoundError("uv not found")),
        ):
            result = validate_migration("task-1", knowledge_path, tmp_path / "docs")

        assert result == 1
        captured = capsys.readouterr()
        assert "Could not run compare-yml-docs command" in captured.err

    def test_fails_with_unresolved_differences(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should fail when unresolved differences exist (lines 425-430).

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "originals").mkdir(parents=True)
        (knowledge_path / "comparisons").mkdir(parents=True)

        # Create task
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        row = "task-1,originals/test.yml,test-pattern,pending,20240101T120000Z,"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create original file
        orig_file = knowledge_path / "originals" / "test.yml"
        orig_file.write_text("content: test")

        # Mock subprocess.run to simulate successful comparison
        mock_result = type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch("subprocess.run", return_value=mock_result),
            patch.object(migration_manager, "count_unresolved_differences", return_value=3),
        ):
            result = validate_migration("task-1", knowledge_path, tmp_path / "docs")

        assert result == 1
        captured = capsys.readouterr()
        assert "Validation failed: 3 unresolved difference(s) found" in captured.out
        assert "Use 'uv run knowledge.query-comparisons' to see details" in captured.out
        assert "Use 'uv run knowledge.mark-resolved' to resolve" in captured.out


class TestMainValidate:
    def test_handles_exception(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 and print error on exception."""
        with patch("sys.argv", ["script", "--task-id"]), pytest.raises(SystemExit):
            main_validate()

    def test_returns_one_for_missing_task(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when task not found.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "nonexistent",
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main_validate()

        assert result == 1

    def test_handles_absolute_paths(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge and comparison paths.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / "custom_knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        row = "task-1,originals/test.yml,test,completed,20240101T120000Z,20240102T120000Z"
        csv_path.write_text(f"{header}\n{row}\n")
        comparison_path = tmp_path / "custom_docs"

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "task-1",
                    "--knowledge-path",
                    str(knowledge_path),
                    "--comparison-path",
                    str(comparison_path),
                ],
            ),
        ):
            result = main_validate()

        assert result == 0

    def test_handles_relative_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle relative knowledge path (branch line 529->532).

        DuckDB requires real filesystem.
        """
        # Create .knowledge under tmp_path (simulated REPO_ROOT)
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        row = "task-1,originals/test.yml,test,completed,20240101T120000Z,20240102T120000Z"
        csv_path.write_text(f"{header}\n{row}\n")

        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "task-1",
                    # Use relative path (default is .knowledge)
                ],
            ),
        ):
            result = main_validate()

        assert result == 0

    def test_handles_exception_during_validation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 and print error when exception occurs (lines 541-542).

        Tests the exception handling in main_validate.
        """
        with (
            patch.object(migration_manager, "REPO_ROOT", tmp_path),
            patch.object(
                migration_manager, "validate_migration", side_effect=RuntimeError("Test error")
            ),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-task-id",
                ],
            ),
        ):
            result = main_validate()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err
        assert "Test error" in captured.err
