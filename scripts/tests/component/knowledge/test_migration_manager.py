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


class TestCsvColumns:
    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "task_id" in CSV_COLUMNS
        assert "original_file_ref" in CSV_COLUMNS
        assert "pattern_name" in CSV_COLUMNS
        assert "status" in CSV_COLUMNS
        assert "created_at" in CSV_COLUMNS
        assert "validated_at" in CSV_COLUMNS


class TestEnsureCsvExists:
    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "migrations" / "tasks.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in CSV_COLUMNS:
            assert col in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if needed.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "migrations" / "tasks.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.parent.exists()

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Should not overwrite existing file.

        DuckDB requires real filesystem.
        """
        (tmp_path / "migrations").mkdir(parents=True)
        csv_path = tmp_path / "migrations" / "tasks.csv"
        csv_path.write_text("existing,content\n")

        ensure_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "existing,content" in content


class TestAppendTask:
    def test_appends_task_record(self, tmp_path: Path) -> None:
        """Should append task record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "migrations").mkdir(parents=True)
        csv_path = tmp_path / "migrations" / "tasks.csv"

        task = MigrationTask(
            task_id="test-id",
            original_file_ref="originals/test.yml",
            pattern_name="api-patterns",
            status="pending",
            created_at="20240101T120000Z",
            validated_at="",
        )

        append_task(csv_path, task)

        content = csv_path.read_text()
        assert "test-id" in content
        assert "api-patterns" in content


class TestGetTaskById:
    def test_finds_existing_task(self, real_knowledge_path: Path) -> None:
        """Should find task by ID.

        DuckDB requires real filesystem files.
        """
        csv_path = real_knowledge_path / "migrations" / "tasks.csv"

        # Create CSV with header and task
        header = ",".join(CSV_COLUMNS)
        row = "test-id,originals/test.yml,api-patterns,pending,20240101T120000Z,"
        csv_path.write_text(f"{header}\n{row}\n")

        result = get_task_by_id(csv_path, "test-id")

        assert result is not None
        assert result["task_id"] == "test-id"
        assert result["pattern_name"] == "api-patterns"

    def test_returns_none_for_missing_task(self, real_knowledge_path: Path) -> None:
        """Should return None when task not found.

        DuckDB requires real filesystem files.
        """
        csv_path = real_knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        result = get_task_by_id(csv_path, "nonexistent")

        assert result is None

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """Should return None when CSV file doesn't exist."""
        result = get_task_by_id(tmp_path / "nonexistent.csv", "test-id")
        assert result is None


class TestUpdateTaskStatus:
    def test_updates_existing_task(self, tmp_path: Path) -> None:
        """Should update status of existing task.

        DuckDB requires real filesystem.
        """
        (tmp_path / "migrations").mkdir(parents=True)
        csv_path = tmp_path / "migrations" / "tasks.csv"

        header = ",".join(CSV_COLUMNS)
        row = "test-id,originals/test.yml,api-patterns,pending,20240101T120000Z,"
        csv_path.write_text(f"{header}\n{row}\n")

        result = update_task_status(csv_path, "test-id", "completed", "20240102T120000Z")

        assert result is True
        content = csv_path.read_text()
        assert "completed" in content

    def test_returns_false_for_missing_task(self, tmp_path: Path) -> None:
        """Should return False when task not found.

        DuckDB requires real filesystem.
        """
        (tmp_path / "migrations").mkdir(parents=True)
        csv_path = tmp_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        result = update_task_status(csv_path, "nonexistent", "completed")

        assert result is False

    def test_returns_false_for_missing_file(self) -> None:
        """Should return False when file doesn't exist."""
        result = update_task_status(Path("/nonexistent.csv"), "test-id", "completed")
        assert result is False


class TestExtractPatternFromPath:
    def test_extracts_from_original_file(self) -> None:
        """Should extract pattern from original.*.yml file."""
        result = extract_pattern_from_path(Path("original.api-patterns.yml"))
        assert result == "api-patterns"

    def test_extracts_from_simple_file(self) -> None:
        """Should extract pattern from simple file name."""
        result = extract_pattern_from_path(Path("api-patterns.yml"))
        assert result == "api-patterns"

    def test_extracts_from_file_ending_in_yml(self) -> None:
        """Should handle pattern names ending in .yml."""
        # This tests the edge case where stem itself ends with .yml
        # original.patterns.yml.yml -> stem is "original.patterns.yml"
        # After removing "original." -> "patterns.yml"
        # Since it ends with ".yml", Path("patterns.yml").stem = "patterns"
        result = extract_pattern_from_path(Path("original.patterns.yml.yml"))
        assert result == "patterns"

    def test_extracts_from_file_ending_in_yaml(self) -> None:
        """Should handle pattern names ending in .yaml."""
        result = extract_pattern_from_path(Path("original.patterns.yaml"))
        assert result == "patterns"


class TestSaveOriginalWithTimestamp:
    def test_copies_file_with_timestamp(self, fs: FakeFilesystem) -> None:
        """Should copy file to originals with timestamp prefix."""
        fs.create_dir("/knowledge/originals")
        fs.create_file("/source/test.yml", contents="content")

        with patch.object(migration_manager, "utc_timestamp", return_value="20240101T120000Z"):
            result = save_original_with_timestamp(
                Path("/source/test.yml"), Path("/knowledge"), "api-patterns"
            )

        assert "20240101T120000Z" in result
        assert "api-patterns" in result


class TestCountUnresolvedDifferences:
    def test_counts_unresolved(self, real_knowledge_path: Path) -> None:
        """Should count unresolved differences.

        DuckDB requires real filesystem files.
        """
        # Create comparison CSV
        comparison_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text1,split.yml,text1-mod
source.yml,item-2,original,text2,split.yml,text2-mod
"""
        csv_path = real_knowledge_path / "comparisons" / "api-patterns.csv"
        csv_path.write_text(comparison_content)

        result = count_unresolved_differences(real_knowledge_path, "api-patterns")

        assert result == 2

    def test_returns_zero_when_no_comparisons(self, tmp_path: Path) -> None:
        """Should return 0 when no comparison files exist."""
        result = count_unresolved_differences(tmp_path, "api-patterns")

        assert result == 0

    def test_returns_zero_when_no_matching_files(self, real_knowledge_path: Path) -> None:
        """Should return 0 when no comparison files match pattern.

        DuckDB requires real filesystem files.
        """
        # Create comparison CSV with different pattern
        comparison_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text1,split.yml,text1-mod
"""
        csv_path = real_knowledge_path / "comparisons" / "other-patterns.csv"
        csv_path.write_text(comparison_content)

        result = count_unresolved_differences(real_knowledge_path, "api-patterns")

        assert result == 0

    def test_excludes_resolved_differences(self, real_knowledge_path: Path) -> None:
        """Should exclude resolved differences from count.

        DuckDB requires real filesystem files.
        """
        # Create comparison CSV
        comparison_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text1,split.yml,text1-mod
source.yml,item-2,original,text2,split.yml,text2-mod
"""
        comp_csv = real_knowledge_path / "comparisons" / "api-patterns.csv"
        comp_csv.write_text(comparison_content)

        # Create resolution CSV that resolves item-1
        res_content = """resolution_id,id,source_file,split_file,original_text_hash,\
split_text_hash,source_file_hash,split_file_hash,resolved_at,projection_version,original_content_hash,split_content_hash
res-1,item-1,source.yml,split.yml,abc,def,ghi,jkl,20240101T120000Z,fieldfacts.v2,content_orig,content_split
"""
        res_csv = real_knowledge_path / "resolutions" / "resolved.csv"
        res_csv.write_text(res_content)

        result = count_unresolved_differences(real_knowledge_path, "api-patterns")

        assert result == 1  # Only item-2 is unresolved


class TestGetOriginalFilePath:
    def test_constructs_full_path(self) -> None:
        """Should construct full path from reference."""
        result = get_original_file_path(
            Path("/knowledge"), "originals/20240101T120000Z-api-patterns.yml"
        )

        assert "originals" in str(result)
        assert "api-patterns" in str(result)


class TestParseStartArgs:
    def test_requires_original_file(self) -> None:
        """Should require --original-file argument."""
        with pytest.raises(SystemExit):
            parse_start_args([])

    def test_parses_original_file(self) -> None:
        """Should parse --original-file argument."""
        args = parse_start_args(["--original-file", "/path/to/file.yml"])
        assert args.original_file == Path("/path/to/file.yml")

    def test_default_knowledge_path(self) -> None:
        """Should default to .knowledge directory."""
        args = parse_start_args(["--original-file", "/file.yml"])
        assert args.knowledge_path == Path(".knowledge")


class TestParseValidateArgs:
    def test_requires_task_id(self) -> None:
        """Should require --task-id argument."""
        with pytest.raises(SystemExit):
            parse_validate_args([])

    def test_parses_task_id(self) -> None:
        """Should parse --task-id argument."""
        args = parse_validate_args(["--task-id", "test-uuid"])
        assert args.task_id == "test-uuid"


class TestStartMigration:
    def test_returns_one_for_missing_file(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when original file doesn't exist."""
        fs.create_dir("/knowledge")

        result = start_migration(Path("/nonexistent.yml"), Path("/knowledge"))

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_non_file(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when path is not a file."""
        fs.create_dir("/knowledge")
        fs.create_dir("/source")

        result = start_migration(Path("/source"), Path("/knowledge"))

        assert result == 1
        captured = capsys.readouterr()
        assert "not a file" in captured.err


class TestStartMigrationSuccess:
    def test_creates_task_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should create task and save original on success.

        DuckDB requires real filesystem.
        """
        source_file = tmp_path / "original.api-patterns.yml"
        source_file.write_text("content: test")
        knowledge_path = tmp_path / ".knowledge"

        with patch.object(migration_manager, "REPO_ROOT", tmp_path):
            result = start_migration(source_file, knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "Migration task created" in captured.out
        assert "api-patterns" in captured.out
        # Check task was created
        assert (knowledge_path / "migrations" / "tasks.csv").exists()
        assert (knowledge_path / "originals").exists()

    def test_returns_one_for_file_outside_repo(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when file is outside repo.

        DuckDB requires real filesystem.
        """
        source_file = tmp_path / "outside" / "file.yml"
        (tmp_path / "outside").mkdir()
        source_file.write_text("content")
        knowledge_path = tmp_path / ".knowledge"

        # Set REPO_ROOT to a different path so source_file is outside
        with patch.object(migration_manager, "REPO_ROOT", tmp_path / "repo"):
            result = start_migration(source_file, knowledge_path)

        assert result == 1
        captured = capsys.readouterr()
        assert "must be within repository" in captured.err


class TestValidateMigration:
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

        result = validate_migration("nonexistent", knowledge_path, tmp_path / "docs")

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_zero_for_completed_task(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and skip validation for completed task.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        row = "task-1,originals/test.yml,test,completed,20240101T120000Z,20240102T120000Z"
        csv_path.write_text(f"{header}\n{row}\n")

        result = validate_migration("task-1", knowledge_path, tmp_path / "docs")

        assert result == 0
        captured = capsys.readouterr()
        assert "already completed" in captured.out

    def test_returns_one_for_missing_original(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when original file is missing.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "tasks.csv"
        header = ",".join(CSV_COLUMNS)
        row = "task-1,originals/missing.yml,test,pending,20240101T120000Z,"
        csv_path.write_text(f"{header}\n{row}\n")

        result = validate_migration("task-1", knowledge_path, tmp_path / "docs")

        assert result == 1
        captured = capsys.readouterr()
        assert "Original file not found" in captured.err


class TestCountUnresolvedDifferencesResultNone:
    def test_handles_empty_comparison_csv(self, real_knowledge_path: Path) -> None:
        """Should handle case where comparison CSV returns None result.

        This tests the branch at line 284 where result could be falsy.
        DuckDB requires real filesystem files.
        """
        # Create a comparison CSV with just headers (no data rows)
        comparison_content = """source_file,id,origin_type,original_text,split_file,split_text
"""
        csv_path = real_knowledge_path / "comparisons" / "api-patterns.csv"
        csv_path.write_text(comparison_content)

        result = count_unresolved_differences(real_knowledge_path, "api-patterns")

        # With no data rows, result should be 0
        assert result == 0
