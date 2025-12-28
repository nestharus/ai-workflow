import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.knowledge import fact_migration
from scripts.knowledge.fact_migration import (
    FACT_MIGRATION_CSV_COLUMNS,
    SIMILARITY_THRESHOLD,
    FactMigrationTask,
    _append_fact_migration_task_to_csv,
    _create_args_namespace,
    _find_element_by_id,
    _get_fact_migration_task_from_csv,
    _get_fact_tasks_csv_path,
    _update_fact_migration_task_in_csv,
    append_fact_migration_task,
    classify_facts,
    count_invariant_failures,
    count_stored_facts,
    count_tracked_movements,
    ensure_fact_migration_csv_exists,
    extract_entities_from_text,
    get_fact_migration_task_by_id,
    main_classify_facts,
    main_move_facts,
    main_start_fact_migration,
    main_validate_fact_migration,
    move_facts,
    normalize_classifications,
    parse_classification_json,
    parse_classify_facts_args,
    parse_move_facts_args,
    parse_start_fact_migration_args,
    parse_validate_fact_migration_args,
    query_all_facts_for_element,
    query_facts_for_task,
    read_yaml_element_text,
    start_fact_migration,
    update_fact_migration_task,
    update_fact_migration_task_status,
    validate_fact_migration,
)


class TestMainStartFactMigration:
    def test_handles_missing_args(self) -> None:
        """Should exit when required arguments missing."""
        with patch("sys.argv", ["script", "--yaml-file"]), pytest.raises(SystemExit):
            main_start_fact_migration()

    def test_returns_one_for_missing_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when file doesn't exist."""
        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--yaml-file",
                    str(tmp_path / "nonexistent.yml"),
                    "--element-id",
                    "test",
                    "--knowledge-path",
                    str(tmp_path / ".knowledge"),
                ],
            ),
        ):
            result = main_start_fact_migration()

        assert result == 1


class TestMainClassifyFacts:
    def test_handles_missing_args(self) -> None:
        """Should exit when required arguments missing."""
        with patch("sys.argv", ["script"]), pytest.raises(SystemExit):
            main_classify_facts()

    def test_returns_one_for_missing_task(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when task not found.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
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
            result = main_classify_facts()

        assert result == 1


class TestMainMoveFacts:
    def test_handles_missing_args(self) -> None:
        """Should exit when required arguments missing."""
        with patch("sys.argv", ["script", "--task-id", "test"]), pytest.raises(SystemExit):
            main_move_facts()

    def test_returns_one_for_missing_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when classification file missing.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-id",
                    "--classification-file",
                    str(tmp_path / "nonexistent.json"),
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main_move_facts()

        assert result == 1


class TestMainValidateFactMigration:
    def test_handles_missing_args(self) -> None:
        """Should exit when required arguments missing."""
        with patch("sys.argv", ["script"]), pytest.raises(SystemExit):
            main_validate_fact_migration()

    def test_returns_one_for_missing_task(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when task not found.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
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
            result = main_validate_fact_migration()

        assert result == 1

    def test_returns_zero_for_completed_task(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 for completed task.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = (
            "test-id,docs/test.yml,factory,completed,"
            "20240101T120000Z,20240102T120000Z,factory.create_app,2,5"
        )
        csv_path.write_text(f"{header}\n{row}\n")

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-id",
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main_validate_fact_migration()

        assert result == 0


class TestMainStartFactMigrationExtended:
    def test_handles_absolute_paths(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute paths correctly."""
        yaml_file = tmp_path / "docs" / "test.yml"
        yaml_file.parent.mkdir(parents=True)
        yaml_content = """items:
  - id: test.element
    text: no entities
"""
        yaml_file.write_text(yaml_content)
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--yaml-file",
                    str(yaml_file),
                    "--element-id",
                    "test.element",
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main_start_fact_migration()

        assert result == 0

    def test_handles_exception(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should handle exceptions and return 1."""
        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--yaml-file",
                    "/path/to/file.yml",
                    "--element-id",
                    "test",
                ],
            ),
            patch.object(
                fact_migration, "start_fact_migration", side_effect=Exception("Test error")
            ),
        ):
            result = main_start_fact_migration()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err


class TestMainClassifyFactsExtended:
    def test_handles_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge path."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-id",
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main_classify_facts()

        assert result == 1  # Task not found

    def test_handles_exception(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should handle exceptions and return 1."""
        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-id",
                ],
            ),
            patch.object(fact_migration, "classify_facts", side_effect=Exception("Test error")),
        ):
            result = main_classify_facts()

        assert result == 1


class TestMainMoveFactsExtended:
    def test_handles_absolute_paths(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute paths correctly."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        classification_file = tmp_path / "class.json"
        classification_file.write_text('{"classifications": []}')

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-id",
                    "--classification-file",
                    str(classification_file),
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main_move_facts()

        assert result == 1  # Empty classifications

    def test_handles_exception(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should handle exceptions and return 1."""
        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-id",
                    "--classification-file",
                    "/path/to/class.json",
                ],
            ),
            patch.object(fact_migration, "move_facts", side_effect=Exception("Test error")),
        ):
            result = main_move_facts()

        assert result == 1


class TestMainValidateFactMigrationExtended:
    def test_handles_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge path."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-id",
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main_validate_fact_migration()

        assert result == 1  # Task not found

    def test_handles_exception(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should handle exceptions and return 1."""
        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-id",
                ],
            ),
            patch.object(
                fact_migration, "validate_fact_migration", side_effect=Exception("Test error")
            ),
        ):
            result = main_validate_fact_migration()

        assert result == 1


class TestMainStartFactMigrationRelativePath:
    def test_handles_relative_yaml_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should resolve relative yaml-file path via REPO_ROOT (line 847)."""
        # Create YAML file in tmp_path relative location
        yaml_file = tmp_path / "docs" / "test.yml"
        yaml_file.parent.mkdir(parents=True)
        yaml_content = """items:
  - id: test.element
    text: no entities
"""
        yaml_file.write_text(yaml_content)
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--yaml-file",
                    "docs/test.yml",  # Relative path
                    "--element-id",
                    "test.element",
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main_start_fact_migration()

        assert result == 0


class TestMainMoveFactsRelativePath:
    def test_handles_relative_classification_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should resolve relative classification-file path via REPO_ROOT (line 1187)."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "movements").mkdir(parents=True)

        # Create task
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,1,1"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create YAML file
        yaml_dir = tmp_path / "docs"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "test.yml"
        yaml_file.write_text("""items:
  - id: factory.create_app
    text: Test element text
""")

        # Create extractions CSV
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Test element text,create_app,Fact,Residual,1,0.95,20240101T120000Z\n"
        )

        # Create classification file at relative path
        classification_file = tmp_path / "classification.json"
        classification_file.write_text(
            json.dumps(
                {
                    "classifications": [
                        {"fact_id": "fact-1", "domain": "fastapi", "pattern": "factory"}
                    ]
                }
            )
        )

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--task-id",
                    "test-id",
                    "--classification-file",
                    "classification.json",  # Relative path
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main_move_facts()

        assert result == 0


class TestMoveFactsMissingFactIdInClassification:
    def test_warns_when_fact_id_is_none(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn when classification has None fact_id (line 1063-1065)."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "movements").mkdir(parents=True)

        # Create task
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,1,1"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create YAML file
        yaml_dir = tmp_path / "docs"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "test.yml"
        yaml_file.write_text("""items:
  - id: factory.create_app
    text: Test element text
""")

        # Create classification with None-like fact_id (valid but empty after parse)
        classification_file = tmp_path / "classification.json"
        # We can't easily create a None in JSON, but we can test with the code
        # directly by bypassing normalize_classifications
        valid_classification = {
            "classifications": [{"fact_id": "valid-id", "domain": "fastapi", "pattern": "factory"}]
        }
        classification_file.write_text(json.dumps(valid_classification))

        # Mock normalize_classifications to return classification with None fact_id
        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch(
                "scripts.knowledge.fact_migration.normalize_classifications",
                return_value=[{"fact_id": None, "domain": "fastapi", "pattern": "factory"}],
            ),
        ):
            result = move_facts("test-id", classification_file, knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "missing fact_id" in captured.out
