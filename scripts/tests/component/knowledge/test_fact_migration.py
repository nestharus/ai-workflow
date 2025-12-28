import json
from pathlib import Path
from typing import TYPE_CHECKING
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

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestFactMigrationCsvColumns:
    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "task_id" in FACT_MIGRATION_CSV_COLUMNS
        assert "original_file_ref" in FACT_MIGRATION_CSV_COLUMNS
        assert "pattern_name" in FACT_MIGRATION_CSV_COLUMNS
        assert "status" in FACT_MIGRATION_CSV_COLUMNS
        assert "created_at" in FACT_MIGRATION_CSV_COLUMNS
        assert "validated_at" in FACT_MIGRATION_CSV_COLUMNS
        assert "element_id" in FACT_MIGRATION_CSV_COLUMNS
        assert "entity_count" in FACT_MIGRATION_CSV_COLUMNS
        assert "fact_count" in FACT_MIGRATION_CSV_COLUMNS


class TestReadYamlElementText:
    def test_reads_text_from_element(self, fs: FakeFilesystem) -> None:
        """Should read text field from YAML element by ID."""
        yaml_content = """
items:
  - id: factory.create_app
    text: Factory function for creating FastAPI app instances.
  - id: factory.setup
    text: Setup function for app configuration.
"""
        fs.create_file("/test/doc.yml", contents=yaml_content)

        result = read_yaml_element_text(Path("/test/doc.yml"), "factory.create_app")

        assert result == "Factory function for creating FastAPI app instances."

    def test_returns_none_for_missing_element(self, fs: FakeFilesystem) -> None:
        """Should return None when element ID not found."""
        yaml_content = """
items:
  - id: other.element
    text: Some text.
"""
        fs.create_file("/test/doc.yml", contents=yaml_content)

        result = read_yaml_element_text(Path("/test/doc.yml"), "nonexistent")

        assert result is None

    def test_returns_none_for_missing_file(self) -> None:
        """Should return None when file doesn't exist."""
        result = read_yaml_element_text(Path("/nonexistent/doc.yml"), "any.id")
        assert result is None

    def test_returns_none_for_invalid_yaml(self, fs: FakeFilesystem) -> None:
        """Should return None for invalid YAML content."""
        fs.create_file("/test/doc.yml", contents="invalid: yaml: content:")

        result = read_yaml_element_text(Path("/test/doc.yml"), "any.id")

        assert result is None


class TestFindElementById:
    def test_finds_element_in_dict(self) -> None:
        """Should find element in a dict."""
        data = {"id": "target", "text": "found"}

        result = _find_element_by_id(data, "target")

        assert result is not None
        assert result["text"] == "found"

    def test_finds_element_in_nested_dict(self) -> None:
        """Should find element in nested dict."""
        data = {"items": {"nested": {"id": "target", "text": "found"}}}

        result = _find_element_by_id(data, "target")

        assert result is not None
        assert result["text"] == "found"

    def test_finds_element_in_list(self) -> None:
        """Should find element in list."""
        data = [{"id": "other"}, {"id": "target", "text": "found"}]

        result = _find_element_by_id(data, "target")

        assert result is not None
        assert result["text"] == "found"

    def test_returns_none_for_missing_element(self) -> None:
        """Should return None when element not found."""
        data = {"id": "other", "text": "not found"}

        result = _find_element_by_id(data, "target")

        assert result is None

    def test_handles_primitive_data(self) -> None:
        """Should handle primitive types gracefully."""
        assert _find_element_by_id("string", "target") is None
        assert _find_element_by_id(123, "target") is None
        assert _find_element_by_id(None, "target") is None


class TestExtractEntitiesFromText:
    def test_extracts_snake_case(self) -> None:
        """Should extract snake_case identifiers."""
        text = "Use create_app function in app/core/factory.py"

        result = extract_entities_from_text(text)

        assert "create_app" in result

    def test_extracts_camel_case(self) -> None:
        """Should extract CamelCase identifiers."""
        text = "The FastAPI instance is created by AppFactory."

        result = extract_entities_from_text(text)

        assert "FastAPI" in result
        assert "AppFactory" in result

    def test_deduplicates_entities(self) -> None:
        """Should deduplicate extracted entities."""
        text = "FastAPI is great. FastAPI is fast."

        result = extract_entities_from_text(text)

        assert result.count("FastAPI") == 1

    def test_preserves_order(self) -> None:
        """Should preserve extraction order."""
        text = "create_app uses FastAPI to build app_instance"

        result = extract_entities_from_text(text)

        assert result.index("create_app") < result.index("FastAPI")

    def test_returns_empty_for_no_entities(self) -> None:
        """Should return empty list when no entities found."""
        text = "no entities here"

        result = extract_entities_from_text(text)

        assert result == []


class TestQueryFactsForTask:
    def test_queries_facts_by_source_sentence(self, tmp_path: Path) -> None:
        """Should query facts matching source sentence.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "extractions.csv"
        csv_content = (
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Test sentence,Entity1,Fact about Entity1,Sentence,"
            "1,0.95,20240101T120000Z\n"
            "fact-2,Test sentence,Entity1,Another fact,Sentence,"
            "2,0.90,20240101T120000Z\n"
            "fact-3,Different sentence,Entity2,Other fact,Sentence,"
            "1,0.88,20240101T120000Z\n"
        )
        csv_path.write_text(csv_content)

        result = query_facts_for_task(csv_path, "Test sentence")

        assert len(result) == 2
        assert result[0]["fact_id"] == "fact-1"
        assert result[1]["fact_id"] == "fact-2"

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        """Should return empty list when file doesn't exist."""
        result = query_facts_for_task(tmp_path / "nonexistent.csv", "any")
        assert result == []

    def test_returns_empty_for_no_matches(self, tmp_path: Path) -> None:
        """Should return empty list when no matches found.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "extractions.csv"
        csv_content = (
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Other sentence,Entity1,Fact,Sentence,1,0.95,"
            "20240101T120000Z\n"
        )
        csv_path.write_text(csv_content)

        result = query_facts_for_task(csv_path, "Non-matching")

        assert result == []


class TestQueryAllFactsForElement:
    def test_queries_facts_with_like_matching(self, tmp_path: Path) -> None:
        """Should query facts using LIKE pattern.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "extractions.csv"
        csv_content = (
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Factory creates app,create_app,Fact1,Residual,1,0.95,"
            "20240101T120000Z\n"
            "fact-2,Factory creates app,FastAPI,Fact2,Residual,1,0.90,"
            "20240101T120000Z\n"
            "fact-3,Different sentence,Other,Fact3,Residual,1,0.88,"
            "20240101T120000Z\n"
        )
        csv_path.write_text(csv_content)

        result = query_all_facts_for_element(csv_path, "Factory creates")

        assert len(result) == 2

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        """Should return empty list when file doesn't exist."""
        result = query_all_facts_for_element(tmp_path / "nonexistent.csv", "any")
        assert result == []


class TestParseClassificationJson:
    def test_parses_valid_json(self, tmp_path: Path) -> None:
        """Should parse valid classification JSON."""
        json_path = tmp_path / "classification.json"
        json_path.write_text('{"classifications": [{"fact_id": "test"}]}')

        result = parse_classification_json(json_path)

        assert "classifications" in result
        assert len(result["classifications"]) == 1

    def test_accepts_facts_key(self, tmp_path: Path) -> None:
        """Should accept 'facts' key as alternative."""
        json_path = tmp_path / "classification.json"
        json_path.write_text('{"facts": [{"fact_id": "test"}]}')

        result = parse_classification_json(json_path)

        assert "facts" in result

    def test_raises_for_missing_file(self, tmp_path: Path) -> None:
        """Should raise ValueError for missing file."""
        with pytest.raises(ValueError, match="not found"):
            parse_classification_json(tmp_path / "nonexistent.json")

    def test_raises_for_invalid_json(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid JSON."""
        json_path = tmp_path / "invalid.json"
        json_path.write_text("not valid json")

        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_classification_json(json_path)

    def test_raises_for_non_object(self, tmp_path: Path) -> None:
        """Should raise TypeError when JSON is not an object."""
        json_path = tmp_path / "array.json"
        json_path.write_text('["array", "not", "object"]')

        with pytest.raises(TypeError, match="must be an object"):
            parse_classification_json(json_path)

    def test_raises_for_missing_required_key(self, tmp_path: Path) -> None:
        """Should raise ValueError when required keys missing."""
        json_path = tmp_path / "missing.json"
        json_path.write_text('{"other": "key"}')

        with pytest.raises(ValueError, match="must contain"):
            parse_classification_json(json_path)


class TestNormalizeClassifications:
    def test_normalizes_classifications_key(self) -> None:
        """Should extract list from 'classifications' key."""
        data = {"classifications": [{"fact_id": "f1", "domain": "fastapi", "pattern": "factory"}]}

        result = normalize_classifications(data)

        assert len(result) == 1
        assert result[0]["fact_id"] == "f1"

    def test_normalizes_facts_key(self) -> None:
        """Should extract list from 'facts' key if classifications missing."""
        data = {"facts": [{"fact_id": "f1", "domain": "python", "pattern": "general"}]}

        result = normalize_classifications(data)

        assert len(result) == 1
        assert result[0]["domain"] == "python"

    def test_raises_for_missing_key(self) -> None:
        """Should raise ValueError when neither key present."""
        data = {"other": "data"}

        with pytest.raises(ValueError, match="must contain"):
            normalize_classifications(data)

    def test_raises_for_non_list(self) -> None:
        """Should raise TypeError when classifications is not a list."""
        data = {"classifications": "not a list"}

        with pytest.raises(TypeError, match="must be a list"):
            normalize_classifications(data)

    def test_raises_for_empty_list(self) -> None:
        """Should raise ValueError when classifications list is empty."""
        data = {"classifications": []}

        with pytest.raises(ValueError, match="empty"):
            normalize_classifications(data)

    def test_raises_for_non_dict_item(self) -> None:
        """Should raise TypeError when item is not a dict."""
        data = {"classifications": ["not a dict"]}

        with pytest.raises(TypeError, match="must be an object"):
            normalize_classifications(data)

    def test_raises_for_missing_fact_id(self) -> None:
        """Should raise ValueError when fact_id is missing."""
        data = {"classifications": [{"domain": "fastapi", "pattern": "factory"}]}

        with pytest.raises(ValueError, match="missing required fields"):
            normalize_classifications(data)

    def test_raises_for_missing_domain(self) -> None:
        """Should raise ValueError when domain is missing."""
        data = {"classifications": [{"fact_id": "f1", "pattern": "factory"}]}

        with pytest.raises(ValueError, match="missing required fields"):
            normalize_classifications(data)

    def test_raises_for_missing_pattern(self) -> None:
        """Should raise ValueError when pattern is missing."""
        data = {"classifications": [{"fact_id": "f1", "domain": "fastapi"}]}

        with pytest.raises(ValueError, match="missing required fields"):
            normalize_classifications(data)

    def test_raises_for_empty_fact_id(self) -> None:
        """Should raise ValueError when fact_id is empty."""
        data = {"classifications": [{"fact_id": "", "domain": "fastapi", "pattern": "factory"}]}

        with pytest.raises(ValueError, match="must be a non-empty string"):
            normalize_classifications(data)

    def test_raises_for_empty_domain(self) -> None:
        """Should raise ValueError when domain is empty."""
        data = {"classifications": [{"fact_id": "f1", "domain": "", "pattern": "factory"}]}

        with pytest.raises(ValueError, match="must be a non-empty string"):
            normalize_classifications(data)

    def test_raises_for_empty_pattern(self) -> None:
        """Should raise ValueError when pattern is empty."""
        data = {"classifications": [{"fact_id": "f1", "domain": "fastapi", "pattern": ""}]}

        with pytest.raises(ValueError, match="must be a non-empty string"):
            normalize_classifications(data)

    def test_allows_optional_fields(self) -> None:
        """Should allow optional fields like scope and target_file."""
        data = {
            "classifications": [
                {
                    "fact_id": "f1",
                    "domain": "fastapi",
                    "pattern": "factory",
                    "scope": "PROJECT",
                    "target_file": "docs/test.yml",
                }
            ]
        }

        result = normalize_classifications(data)

        assert result[0]["scope"] == "PROJECT"
        assert result[0]["target_file"] == "docs/test.yml"


class TestCountInvariantFailures:
    def test_counts_low_similarity_movements(self, tmp_path: Path) -> None:
        """Should count movements with similarity below threshold.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "iterative_movements.csv"
        csv_content = (
            "iteration_id,fact_id,source_sentence,isolated_fact,"
            "residual_sentence,similarity_score,reason,moved_at,pass_id,"
            "span_id,artifact_id,schema_version\n"
            "iter-1,fact-1,Source,Fact,Residual,0.98,Migration,"
            "20240101T120000Z,,,,pass-span.v1\n"
            "iter-2,fact-2,Source,Fact,Residual,0.80,Migration,"
            "20240101T120000Z,,,,pass-span.v1\n"
            "iter-3,fact-3,Source,Fact,Residual,0.92,Migration,"
            "20240101T120000Z,,,,pass-span.v1\n"
        )
        csv_path.write_text(csv_content)

        result = count_invariant_failures(csv_path, ["fact-1", "fact-2", "fact-3"])

        # fact-2 (0.80) and fact-3 (0.92) are below 0.95 threshold
        assert result == 2

    def test_counts_zero_for_all_valid(self, tmp_path: Path) -> None:
        """Should return 0 when all movements satisfy threshold.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "iterative_movements.csv"
        csv_content = (
            "iteration_id,fact_id,source_sentence,isolated_fact,"
            "residual_sentence,similarity_score,reason,moved_at,pass_id,"
            "span_id,artifact_id,schema_version\n"
            "iter-1,fact-1,Source,Fact,Residual,0.98,Migration,"
            "20240101T120000Z,,,,pass-span.v1\n"
            "iter-2,fact-2,Source,Fact,Residual,0.96,Migration,"
            "20240101T120000Z,,,,pass-span.v1\n"
        )
        csv_path.write_text(csv_content)

        result = count_invariant_failures(csv_path, ["fact-1", "fact-2"])

        assert result == 0

    def test_returns_zero_for_empty_ids(self, tmp_path: Path) -> None:
        """Should return 0 for empty fact IDs list."""
        csv_path = tmp_path / "movements.csv"
        csv_path.write_text("header\n")

        result = count_invariant_failures(csv_path, [])

        assert result == 0

    def test_returns_zero_for_missing_file(self, tmp_path: Path) -> None:
        """Should return 0 when file doesn't exist."""
        result = count_invariant_failures(tmp_path / "nonexistent.csv", ["fact-1"])

        assert result == 0

    def test_only_counts_specified_fact_ids(self, tmp_path: Path) -> None:
        """Should only count failures for specified fact IDs.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "iterative_movements.csv"
        csv_content = (
            "iteration_id,fact_id,source_sentence,isolated_fact,residual_sentence,"
            "similarity_score,reason,moved_at,pass_id,span_id,artifact_id,schema_version\n"
            "iter-1,fact-1,Source,Fact,Residual,0.80,Migration,20240101T120000Z,,,,pass-span.v1\n"
            "iter-2,fact-2,Source,Fact,Residual,0.80,Migration,20240101T120000Z,,,,pass-span.v1\n"
            "iter-3,fact-3,Source,Fact,Residual,0.80,Migration,20240101T120000Z,,,,pass-span.v1\n"
        )
        csv_path.write_text(csv_content)

        # Only ask about fact-1
        result = count_invariant_failures(csv_path, ["fact-1"])

        assert result == 1

    def test_similarity_threshold_value(self) -> None:
        """Should use 0.95 as the threshold."""
        assert SIMILARITY_THRESHOLD == 0.95


class TestCountStoredFacts:
    def test_counts_stored_facts(self, tmp_path: Path) -> None:
        """Should count facts stored in YAML files."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        yaml_content = """facts:
  - fact_id: fact-1
    entity: Entity1
    fact_text: Fact text
  - fact_id: fact-2
    entity: Entity2
    fact_text: Another fact
"""
        (facts_dir / "test.facts.yml").write_text(yaml_content)

        result = count_stored_facts(facts_dir, ["fact-1", "fact-2", "fact-3"])

        assert result == 2

    def test_returns_zero_for_empty_ids(self, tmp_path: Path) -> None:
        """Should return 0 for empty fact IDs list."""
        result = count_stored_facts(tmp_path, [])
        assert result == 0


class TestCountTrackedMovements:
    def test_counts_tracked_movements(self, tmp_path: Path) -> None:
        """Should count movements tracked for fact IDs.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "iterative_movements.csv"
        csv_content = (
            "iteration_id,fact_id,source_sentence,isolated_fact,residual_sentence,"
            "similarity_score,reason,moved_at,pass_id,span_id,artifact_id,schema_version\n"
            "iter-1,fact-1,Source,Fact,Residual,0.95,Migration,20240101T120000Z,,,,pass-span.v1\n"
            "iter-2,fact-2,Source,Fact,Residual,0.92,Migration,20240101T120000Z,,,,pass-span.v1\n"
        )
        csv_path.write_text(csv_content)

        result = count_tracked_movements(csv_path, ["fact-1", "fact-3"])

        assert result == 1

    def test_returns_zero_for_empty_ids(self, tmp_path: Path) -> None:
        """Should return 0 for empty fact IDs list."""
        result = count_tracked_movements(tmp_path / "movements.csv", [])
        assert result == 0

    def test_returns_zero_for_missing_file(self, tmp_path: Path) -> None:
        """Should return 0 when file doesn't exist."""
        result = count_tracked_movements(tmp_path / "nonexistent.csv", ["fact-1"])
        assert result == 0


class TestCreateArgsNamespace:
    def test_creates_namespace_with_kwargs(self) -> None:
        """Should create namespace with provided kwargs."""
        result = _create_args_namespace(foo="bar", num=42)

        assert result.foo == "bar"
        assert result.num == 42


class TestEnsureFactMigrationCsvExists:
    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "migrations" / "fact_tasks.csv"

        ensure_fact_migration_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in FACT_MIGRATION_CSV_COLUMNS:
            assert col in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if needed.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "migrations" / "fact_tasks.csv"

        ensure_fact_migration_csv_exists(csv_path)

        assert csv_path.parent.exists()

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Should not overwrite existing file.

        DuckDB requires real filesystem.
        """
        (tmp_path / "migrations").mkdir(parents=True)
        csv_path = tmp_path / "migrations" / "fact_tasks.csv"
        csv_path.write_text("existing,content\n")

        ensure_fact_migration_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "existing,content" in content


class TestGetFactTasksCsvPath:
    def test_returns_correct_path(self, tmp_path: Path) -> None:
        """Should return path to migrations/fact_tasks.csv."""
        result = _get_fact_tasks_csv_path(tmp_path)
        assert result == tmp_path / "migrations" / "fact_tasks.csv"


class TestAppendFactMigrationTaskToCsv:
    def test_appends_task_record(self, tmp_path: Path) -> None:
        """Should append task record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "migrations").mkdir(parents=True)
        csv_path = tmp_path / "migrations" / "fact_tasks.csv"

        task = FactMigrationTask(
            task_id="test-id",
            original_file_ref="docs/test.yml",
            pattern_name="factory",
            status="pending",
            created_at="20240101T120000Z",
            validated_at="",
            element_id="factory.create_app",
            entity_count="2",
            fact_count="5",
        )

        _append_fact_migration_task_to_csv(csv_path, task)

        content = csv_path.read_text()
        assert "test-id" in content
        assert "factory.create_app" in content


class TestAppendFactMigrationTask:
    def test_appends_task_via_wrapper(self, tmp_path: Path) -> None:
        """Should append task record via knowledge_path wrapper.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)

        task = FactMigrationTask(
            task_id="test-id",
            original_file_ref="docs/test.yml",
            pattern_name="factory",
            status="pending",
            created_at="20240101T120000Z",
            validated_at="",
            element_id="factory.create_app",
            entity_count="2",
            fact_count="5",
        )

        append_fact_migration_task(knowledge_path, task)

        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        content = csv_path.read_text()
        assert "test-id" in content
        assert "factory.create_app" in content


class TestGetFactMigrationTaskFromCsv:
    def test_finds_existing_task(self, tmp_path: Path) -> None:
        """Should find task by ID.

        DuckDB requires real filesystem.
        """
        (tmp_path / "migrations").mkdir(parents=True)
        csv_path = tmp_path / "migrations" / "fact_tasks.csv"

        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        result = _get_fact_migration_task_from_csv(csv_path, "test-id")

        assert result is not None
        assert result["task_id"] == "test-id"
        assert result["element_id"] == "factory.create_app"


class TestGetFactMigrationTaskById:
    def test_finds_existing_task_via_wrapper(self, tmp_path: Path) -> None:
        """Should find task by ID via knowledge_path wrapper.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"

        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        result = get_fact_migration_task_by_id(knowledge_path, "test-id")

        assert result is not None
        assert result["task_id"] == "test-id"
        assert result["element_id"] == "factory.create_app"

    def test_returns_none_for_missing_task(self, tmp_path: Path) -> None:
        """Should return None when task not found.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        result = get_fact_migration_task_by_id(knowledge_path, "nonexistent")

        assert result is None

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        """Should return None when CSV file doesn't exist."""
        knowledge_path = tmp_path / ".knowledge"
        result = get_fact_migration_task_by_id(knowledge_path, "test-id")
        assert result is None


class TestUpdateFactMigrationTaskInCsv:
    def test_updates_existing_task(self, tmp_path: Path) -> None:
        """Should update task fields.

        DuckDB requires real filesystem.
        """
        (tmp_path / "migrations").mkdir(parents=True)
        csv_path = tmp_path / "migrations" / "fact_tasks.csv"

        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        result = _update_fact_migration_task_in_csv(csv_path, "test-id", {"status": "completed"})

        assert result is True
        content = csv_path.read_text()
        assert "completed" in content


class TestUpdateFactMigrationTask:
    def test_updates_via_wrapper(self, tmp_path: Path) -> None:
        """Should update task via knowledge_path wrapper.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"

        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        result = update_fact_migration_task(knowledge_path, "test-id", {"status": "completed"})

        assert result is True
        content = csv_path.read_text()
        assert "completed" in content

    def test_returns_false_for_missing_task(self, tmp_path: Path) -> None:
        """Should return False when task not found.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        result = update_fact_migration_task(knowledge_path, "nonexistent", {"status": "completed"})

        assert result is False

    def test_returns_false_for_missing_file(self, tmp_path: Path) -> None:
        """Should return False when file doesn't exist."""
        knowledge_path = tmp_path / ".knowledge"
        result = update_fact_migration_task(knowledge_path, "test-id", {"status": "completed"})
        assert result is False


class TestUpdateFactMigrationTaskStatus:
    def test_updates_status_only(self, tmp_path: Path) -> None:
        """Should update just the status field.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"

        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        result = update_fact_migration_task_status(knowledge_path, "test-id", "in_progress")

        assert result is True
        content = csv_path.read_text()
        assert "in_progress" in content

    def test_updates_status_and_validated_at(self, tmp_path: Path) -> None:
        """Should update status and validated_at fields.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"

        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        result = update_fact_migration_task_status(
            knowledge_path, "test-id", "completed", "20240102T120000Z"
        )

        assert result is True
        content = csv_path.read_text()
        assert "completed" in content
        assert "20240102T120000Z" in content


class TestParseStartFactMigrationArgs:
    def test_requires_yaml_file(self) -> None:
        """Should require --yaml-file argument."""
        with pytest.raises(SystemExit):
            parse_start_fact_migration_args(["--element-id", "factory.create_app"])

    def test_requires_element_id(self) -> None:
        """Should require --element-id argument."""
        with pytest.raises(SystemExit):
            parse_start_fact_migration_args(["--yaml-file", "/path/to/file.yml"])

    def test_parses_required_args(self) -> None:
        """Should parse required arguments."""
        args = parse_start_fact_migration_args(
            ["--yaml-file", "/path/to/file.yml", "--element-id", "factory.create_app"]
        )
        assert args.yaml_file == Path("/path/to/file.yml")
        assert args.element_id == "factory.create_app"

    def test_default_knowledge_path(self) -> None:
        """Should default to .knowledge directory."""
        args = parse_start_fact_migration_args(["--yaml-file", "/file.yml", "--element-id", "test"])
        assert args.knowledge_path == Path(".knowledge")


class TestParseClassifyFactsArgs:
    def test_requires_task_id(self) -> None:
        """Should require --task-id argument."""
        with pytest.raises(SystemExit):
            parse_classify_facts_args([])

    def test_parses_task_id(self) -> None:
        """Should parse --task-id argument."""
        args = parse_classify_facts_args(["--task-id", "test-uuid"])
        assert args.task_id == "test-uuid"


class TestParseMoveFactsArgs:
    def test_requires_task_id(self) -> None:
        """Should require --task-id argument."""
        with pytest.raises(SystemExit):
            parse_move_facts_args(["--classification-file", "/path/to/file.json"])

    def test_requires_classification_file(self) -> None:
        """Should require --classification-file argument."""
        with pytest.raises(SystemExit):
            parse_move_facts_args(["--task-id", "test-uuid"])

    def test_parses_required_args(self) -> None:
        """Should parse required arguments."""
        args = parse_move_facts_args(
            ["--task-id", "test-uuid", "--classification-file", "/path/to/file.json"]
        )
        assert args.task_id == "test-uuid"
        assert args.classification_file == Path("/path/to/file.json")

    def test_parses_dry_run(self) -> None:
        """Should parse --dry-run flag."""
        args = parse_move_facts_args(
            ["--task-id", "test-uuid", "--classification-file", "/file.json", "--dry-run"]
        )
        assert args.dry_run is True


class TestParseValidateFactMigrationArgs:
    def test_requires_task_id(self) -> None:
        """Should require --task-id argument."""
        with pytest.raises(SystemExit):
            parse_validate_fact_migration_args([])

    def test_parses_task_id(self) -> None:
        """Should parse --task-id argument."""
        args = parse_validate_fact_migration_args(["--task-id", "test-uuid"])
        assert args.task_id == "test-uuid"


class TestStartFactMigration:
    def test_returns_one_for_missing_yaml(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when YAML file doesn't exist."""
        fs.create_dir("/knowledge")

        result = start_fact_migration(
            Path("/nonexistent.yml"), "factory.create_app", Path("/knowledge")
        )

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_missing_element(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when element ID not found."""
        yaml_content = """items:
  - id: other.element
    text: Some text.
"""
        fs.create_file("/test/doc.yml", contents=yaml_content)
        fs.create_dir("/knowledge")

        result = start_fact_migration(Path("/test/doc.yml"), "nonexistent", Path("/knowledge"))

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err


class TestStartFactMigrationSuccess:
    def test_creates_task_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should create task on success.

        DuckDB requires real filesystem.
        """
        yaml_file = tmp_path / "docs" / "test.yml"
        yaml_file.parent.mkdir(parents=True)
        yaml_content = """items:
  - id: factory.create_app
    text: The create_app function builds a FastAPI instance.
"""
        yaml_file.write_text(yaml_content)
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)

        # Mock fact extraction to avoid running full extraction
        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch.object(fact_migration.fact_extraction, "extract_facts_main", return_value=0),
        ):
            result = start_fact_migration(yaml_file, "factory.create_app", knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "Starting fact migration" in captured.out
        assert (knowledge_path / "migrations" / "fact_tasks.csv").exists()


class TestClassifyFacts:
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

        result = classify_facts("nonexistent", knowledge_path)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_prints_instructions_for_valid_task(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print sub-agent instructions for valid task.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "facts").mkdir(parents=True)

        # Create task
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create YAML file
        yaml_dir = tmp_path / "docs"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "test.yml"
        yaml_file.write_text("""items:
  - id: factory.create_app
    text: Test element text
""")

        # Create extractions CSV with facts
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        extractions_content = (
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Test element text,create_app,Fact about create_app,"
            "Residual,1,0.95,20240101T120000Z\n"
        )
        extractions_csv.write_text(extractions_content)

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = classify_facts("test-id", knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "knowledge-analyzer" in captured.out
        assert "sub-agent" in captured.out.lower()


class TestMoveFacts:
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

        classification_file = tmp_path / "class.json"
        classification_file.write_text('{"classifications": []}')

        result = move_facts("nonexistent", classification_file, knowledge_path)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_missing_classification_file(
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

        result = move_facts("test-id", tmp_path / "nonexistent.json", knowledge_path)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_dry_run_does_not_modify(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should not modify files in dry run mode.

        DuckDB requires real filesystem.
        """
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
        extractions_csv.write_text("""fact_id,source_sentence,entity,fact_text,rewritten_sentence,iteration,confidence,extracted_at
fact-1,Test element text,create_app,Fact,Residual,1,0.95,20240101T120000Z
""")

        # Create classification JSON
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

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = move_facts("test-id", classification_file, knowledge_path, dry_run=True)

        assert result == 0
        captured = capsys.readouterr()
        assert "Dry run" in captured.out
        # Verify no fact YAML file was created
        assert not (knowledge_path / "facts" / "fastapi.factory.facts.yml").exists()


class TestValidateFactMigration:
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

        result = validate_fact_migration("nonexistent", knowledge_path)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_zero_for_completed_task(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 for already completed task.

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

        result = validate_fact_migration("test-id", knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "already completed" in captured.out


class TestReadYamlElementTextExtended:
    def test_reads_element_without_text_field(self, fs: FakeFilesystem) -> None:
        """Should return None when element exists but has no text field."""
        yaml_content = """
items:
  - id: factory.create_app
    description: No text field here
"""
        fs.create_file("/test/doc.yml", contents=yaml_content)

        result = read_yaml_element_text(Path("/test/doc.yml"), "factory.create_app")

        # element.get("text") returns None when no text field
        assert result is None


class TestExtractEntitiesFromTextExtended:
    def test_extracts_both_snake_and_camel_case(self) -> None:
        """Should extract both snake_case and CamelCase and return unique entities."""
        text = "The create_app function returns FastAPI, use get_user_by_id for UserModel"

        result = extract_entities_from_text(text)

        # Verify all entities found
        assert "create_app" in result
        assert "get_user_by_id" in result
        assert "FastAPI" in result
        assert "UserModel" in result
        # Check no duplicates
        assert len(result) == len(set(result))


class TestQueryFactsForTaskExtended:
    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV file."""
        csv_path = tmp_path / "extractions.csv"
        csv_path.write_text("")  # Empty file

        result = query_facts_for_task(csv_path, "any sentence")

        assert result == []

    def test_handles_duckdb_error(self, tmp_path: Path) -> None:
        """Should return empty list when DuckDB query fails."""
        csv_path = tmp_path / "extractions.csv"
        # Write invalid CSV content that will cause DuckDB error
        csv_path.write_text("invalid csv content that's not valid")

        result = query_facts_for_task(csv_path, "any sentence")

        assert result == []


class TestQueryAllFactsForElementExtended:
    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV file."""
        csv_path = tmp_path / "extractions.csv"
        csv_path.write_text("")  # Empty file

        result = query_all_facts_for_element(csv_path, "any text")

        assert result == []

    def test_handles_duckdb_error(self, tmp_path: Path) -> None:
        """Should return empty list when DuckDB query fails."""
        csv_path = tmp_path / "extractions.csv"
        # Write malformed content
        csv_path.write_text("malformed csv")

        result = query_all_facts_for_element(csv_path, "test")

        assert result == []

    def test_returns_facts_matching_element(self, tmp_path: Path) -> None:
        """Should return facts matching element text."""
        csv_path = tmp_path / "extractions.csv"
        csv_content = (
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Factory creates app with config,create_app,Fact1,Residual,1,0.95,"
            "20240101T120000Z\n"
        )
        csv_path.write_text(csv_content)

        result = query_all_facts_for_element(csv_path, "Factory creates")

        assert len(result) == 1
        assert result[0]["fact_id"] == "fact-1"


class TestCountStoredFactsExtended:
    def test_counts_facts_from_multiple_files(self, tmp_path: Path) -> None:
        """Should count facts from multiple YAML files."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        # First file with 2 facts
        yaml1 = """facts:
  - fact_id: fact-1
    entity: Entity1
    fact_text: Fact text 1
  - fact_id: fact-2
    entity: Entity2
    fact_text: Fact text 2
"""
        (facts_dir / "domain1.facts.yml").write_text(yaml1)

        # Second file with 1 fact
        yaml2 = """facts:
  - fact_id: fact-3
    entity: Entity3
    fact_text: Fact text 3
"""
        (facts_dir / "domain2.facts.yml").write_text(yaml2)

        result = count_stored_facts(facts_dir, ["fact-1", "fact-2", "fact-3", "fact-4"])

        assert result == 3

    def test_handles_invalid_yaml_file(self, tmp_path: Path) -> None:
        """Should skip invalid YAML files gracefully."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        # Valid file
        yaml_valid = """facts:
  - fact_id: fact-1
    entity: Entity1
    fact_text: Valid fact
"""
        (facts_dir / "valid.facts.yml").write_text(yaml_valid)

        # Invalid YAML file
        (facts_dir / "invalid.facts.yml").write_text("invalid: yaml: content:")

        result = count_stored_facts(facts_dir, ["fact-1"])

        assert result == 1

    def test_handles_non_dict_yaml(self, tmp_path: Path) -> None:
        """Should skip YAML files that don't contain a dict."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        # YAML with list at top level instead of dict
        (facts_dir / "list.facts.yml").write_text("- item1\n- item2\n")

        result = count_stored_facts(facts_dir, ["fact-1"])

        assert result == 0

    def test_handles_non_list_facts(self, tmp_path: Path) -> None:
        """Should skip files where 'facts' is not a list."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        # YAML with facts as string instead of list
        yaml_content = """facts: "not a list"
"""
        (facts_dir / "test.facts.yml").write_text(yaml_content)

        result = count_stored_facts(facts_dir, ["fact-1"])

        assert result == 0

    def test_handles_non_dict_fact_items(self, tmp_path: Path) -> None:
        """Should skip fact items that aren't dicts."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        yaml_content = """facts:
  - just_a_string
  - fact_id: fact-1
    entity: Entity1
    fact_text: Valid fact
"""
        (facts_dir / "test.facts.yml").write_text(yaml_content)

        result = count_stored_facts(facts_dir, ["fact-1", "just_a_string"])

        assert result == 1


class TestCountTrackedMovementsExtended:
    def test_counts_movements_for_multiple_facts(self, tmp_path: Path) -> None:
        """Should count movements for multiple fact IDs."""
        csv_path = tmp_path / "iterative_movements.csv"
        csv_content = (
            "iteration_id,fact_id,source_sentence,isolated_fact,residual_sentence,"
            "similarity_score,reason,moved_at,pass_id,span_id,artifact_id,schema_version\n"
            "iter-1,fact-1,Source1,Fact1,Residual1,0.95,Migration,20240101T120000Z,,,,pass-span.v1\n"
            "iter-2,fact-2,Source2,Fact2,Residual2,0.92,Migration,20240101T120000Z,,,,pass-span.v1\n"
            "iter-3,fact-3,Source3,Fact3,Residual3,0.90,Migration,20240101T120000Z,,,,pass-span.v1\n"
        )
        csv_path.write_text(csv_content)

        result = count_tracked_movements(csv_path, ["fact-1", "fact-2"])

        assert result == 2


class TestCountInvariantFailuresExtended:
    def test_uses_python_fallback_on_duckdb_error(self, tmp_path: Path) -> None:
        """Should fall back to Python when DuckDB query fails.

        The DuckDB query with UNNEST may fail on certain CSV formats.
        """
        csv_path = tmp_path / "iterative_movements.csv"
        # Create a valid CSV that can be read by movement_tracker
        csv_content = (
            "iteration_id,fact_id,source_sentence,isolated_fact,residual_sentence,"
            "similarity_score,reason,moved_at,pass_id,span_id,artifact_id,schema_version\n"
            "iter-1,fact-1,Source,Fact,Residual,0.80,Migration,20240101T120000Z,,,,pass-span.v1\n"
        )
        csv_path.write_text(csv_content)

        # Even if DuckDB fails with UNNEST, Python fallback should work
        result = count_invariant_failures(csv_path, ["fact-1"])

        # fact-1 has 0.80 which is below 0.95
        assert result == 1


class TestEnsureFactMigrationCsvExistsExtended:
    def test_calls_existing_file(self, tmp_path: Path) -> None:
        """Should not overwrite existing file with content."""
        (tmp_path / "migrations").mkdir(parents=True)
        csv_path = tmp_path / "migrations" / "fact_tasks.csv"
        csv_path.write_text("existing,content,here\ndata,data,data\n")

        ensure_fact_migration_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "existing,content,here" in content


class TestStartFactMigrationExtended:
    def test_handles_no_entities(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should handle case when no entities are found in text."""
        yaml_file = tmp_path / "docs" / "test.yml"
        yaml_file.parent.mkdir(parents=True)
        yaml_content = """items:
  - id: test.element
    text: no entities here just plain text
"""
        yaml_file.write_text(yaml_content)
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = start_fact_migration(yaml_file, "test.element", knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "No entities found" in captured.out

    def test_handles_long_element_text(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should truncate long element text in output."""
        yaml_file = tmp_path / "docs" / "test.yml"
        yaml_file.parent.mkdir(parents=True)
        long_text = "The create_app function " + "x" * 200  # > 100 chars
        yaml_content = f"""items:
  - id: factory.create_app
    text: {long_text}
"""
        yaml_file.write_text(yaml_content)
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch.object(fact_migration.fact_extraction, "extract_facts_main", return_value=0),
        ):
            result = start_fact_migration(yaml_file, "factory.create_app", knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert '..."' in captured.out  # Truncated with ...

    def test_handles_incomplete_extraction(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 2 when extraction is incomplete."""
        yaml_file = tmp_path / "docs" / "test.yml"
        yaml_file.parent.mkdir(parents=True)
        yaml_content = """items:
  - id: factory.create_app
    text: The create_app function builds FastAPI
"""
        yaml_file.write_text(yaml_content)
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch.object(fact_migration.fact_extraction, "extract_facts_main", return_value=2),
        ):
            result = start_fact_migration(yaml_file, "factory.create_app", knowledge_path)

        assert result == 2
        captured = capsys.readouterr()
        assert "Incomplete extractions:" in captured.out

    def test_handles_extraction_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle extraction errors."""
        yaml_file = tmp_path / "docs" / "test.yml"
        yaml_file.parent.mkdir(parents=True)
        yaml_content = """items:
  - id: factory.create_app
    text: The create_app function
"""
        yaml_file.write_text(yaml_content)
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch.object(fact_migration.fact_extraction, "extract_facts_main", return_value=1),
        ):
            result = start_fact_migration(yaml_file, "factory.create_app", knowledge_path)

        # Still returns 0 because no incomplete extractions
        assert result == 0
        captured = capsys.readouterr()
        assert "Error extracting" in captured.err

    def test_handles_element_id_without_dot(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle element_id without a dot (for pattern_name)."""
        yaml_file = tmp_path / "docs" / "test.yml"
        yaml_file.parent.mkdir(parents=True)
        yaml_content = """items:
  - id: simpletask
    text: no entities
"""
        yaml_file.write_text(yaml_content)
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = start_fact_migration(yaml_file, "simpletask", knowledge_path)

        assert result == 0

    def test_handles_file_outside_repo_root(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle YAML file outside REPO_ROOT (ValueError path)."""
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

        # Use a different REPO_ROOT that doesn't contain yaml_file
        with patch.object(fact_migration, "REPO_ROOT", Path("/different/root")):
            result = start_fact_migration(yaml_file, "test.element", knowledge_path)

        assert result == 0


class TestClassifyFactsExtended:
    def test_handles_missing_element_text(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn when element text cannot be read."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "facts").mkdir(parents=True)

        # Create task pointing to non-existent file
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = (
            "test-id,docs/nonexistent.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        )
        csv_path.write_text(f"{header}\n{row}\n")

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = classify_facts("test-id", knowledge_path)

        # Returns 1 because no facts found
        assert result == 1
        captured = capsys.readouterr()
        assert "Could not read element text" in captured.out
        assert "No facts found" in captured.out

    def test_prints_facts_with_confidence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print facts with their confidence scores."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "facts").mkdir(parents=True)

        # Create task
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,2"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create YAML file
        yaml_dir = tmp_path / "docs"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "test.yml"
        yaml_file.write_text("""items:
  - id: factory.create_app
    text: Test element text
""")

        # Create extractions with multiple facts
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        extractions_content = (
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Test element text,create_app,First fact about create_app,"
            "Residual,1,0.95,20240101T120000Z\n"
            "fact-2,Test element text,FastAPI,Second fact about FastAPI,"
            "Residual,1,0.88,20240101T120000Z\n"
        )
        extractions_csv.write_text(extractions_content)

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = classify_facts("test-id", knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "Extracted Facts:" in captured.out
        assert "[create_app]" in captured.out
        assert "[FastAPI]" in captured.out
        assert "Confidence:" in captured.out
        assert "0.95" in captured.out


class TestMoveFactsExtended:
    def test_handles_invalid_classification_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 for invalid classification JSON."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create classification file with empty list (which raises ValueError)
        classification_file = tmp_path / "classification.json"
        classification_file.write_text('{"classifications": []}')

        result = move_facts("test-id", classification_file, knowledge_path)

        assert result == 1
        captured = capsys.readouterr()
        assert "empty" in captured.err.lower()

    def test_handles_classification_without_fact_id(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn when classification missing fact_id."""
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

        # Create classification with missing fact_id (but valid required fields)
        classification_file = tmp_path / "classification.json"
        classification_file.write_text(
            json.dumps(
                {
                    "classifications": [
                        {"fact_id": "", "domain": "fastapi", "pattern": "factory"}  # empty fact_id
                    ]
                }
            )
        )

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = move_facts("test-id", classification_file, knowledge_path)

        # Returns 1 because of validation error
        assert result == 1

    def test_handles_fact_not_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn when fact not found in extractions."""
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

        # Create extractions CSV (empty - no facts)
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
        )

        # Create classification with fact_id that doesn't exist
        classification_file = tmp_path / "classification.json"
        classification_file.write_text(
            json.dumps(
                {
                    "classifications": [
                        {"fact_id": "nonexistent-id", "domain": "fastapi", "pattern": "factory"}
                    ]
                }
            )
        )

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = move_facts("test-id", classification_file, knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "Fact not found for ID" in captured.out

    def test_moves_facts_successfully(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should move facts and track movements successfully."""
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

        # Create extractions CSV with a fact
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Test element text,create_app,Fact about create_app,"
            "Residual,1,0.95,20240101T120000Z\n"
        )

        # Create classification
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

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = move_facts("test-id", classification_file, knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "Stored to:" in captured.out
        assert "Movement tracked:" in captured.out
        assert "Facts stored: 1" in captured.out
        # Verify fact YAML was created
        assert (knowledge_path / "facts" / "fastapi.factory.facts.yml").exists()


class TestValidateFactMigrationExtended:
    def test_validates_with_all_issues(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should report all validation issues."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "movements").mkdir(parents=True)

        # Create task with expected facts
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create YAML file
        yaml_dir = tmp_path / "docs"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "test.yml"
        yaml_file.write_text("""items:
  - id: factory.create_app
    text: Test element text
""")

        # Create extractions CSV with facts
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Test element text,create_app,Fact1,Residual,1,0.95,20240101T120000Z\n"
            "fact-2,Test element text,FastAPI,Fact2,Residual,1,0.90,20240101T120000Z\n"
        )

        # No stored facts, no movements -> validation fails
        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = validate_fact_migration("test-id", knowledge_path)

        assert result == 1
        captured = capsys.readouterr()
        assert "Not all facts stored" in captured.out
        assert "Not all movements tracked" in captured.out
        assert "Validation failed" in captured.out

    def test_validates_successfully(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should validate successfully when all facts are stored and tracked."""
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

        # Create extractions CSV with a fact
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Test element text,create_app,Fact about create_app,"
            "Residual,1,0.95,20240101T120000Z\n"
        )

        # Create stored fact
        fact_yaml = """facts:
  - fact_id: fact-1
    entity: create_app
    fact_text: Fact about create_app
"""
        (knowledge_path / "facts" / "fastapi.factory.facts.yml").write_text(fact_yaml)

        # Create movement tracking
        movements_csv = knowledge_path / "movements" / "iterative_movements.csv"
        movements_csv.write_text(
            "iteration_id,fact_id,source_sentence,isolated_fact,residual_sentence,"
            "similarity_score,reason,moved_at,pass_id,span_id,artifact_id,schema_version\n"
            "iter-1,fact-1,Test element text,Fact about create_app,Residual,"
            "0.98,Migration,20240101T120000Z,,,,pass-span.v1\n"
        )

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = validate_fact_migration("test-id", knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        assert "validated successfully" in captured.out

    def test_handles_no_facts_when_expected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should report when no facts found but some expected."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "facts").mkdir(parents=True)

        # Create task expecting 5 facts
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = "test-id,docs/test.yml,factory,pending,20240101T120000Z,,factory.create_app,2,5"
        csv_path.write_text(f"{header}\n{row}\n")

        # Create YAML file
        yaml_dir = tmp_path / "docs"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "test.yml"
        yaml_file.write_text("""items:
  - id: factory.create_app
    text: Test element text
""")

        # Empty extractions CSV (no facts)
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
        )

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = validate_fact_migration("test-id", knowledge_path)

        assert result == 1
        captured = capsys.readouterr()
        assert "No facts found in extractions.csv" in captured.out

    def test_handles_invariant_failures(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should report invariant failures."""
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
            "fact-1,Test element text,create_app,Fact about create_app,"
            "Residual,1,0.95,20240101T120000Z\n"
        )

        # Create stored fact
        fact_yaml = """facts:
  - fact_id: fact-1
    entity: create_app
    fact_text: Fact about create_app
"""
        (knowledge_path / "facts" / "fastapi.factory.facts.yml").write_text(fact_yaml)

        # Create movement with LOW similarity (invariant failure)
        movements_csv = knowledge_path / "movements" / "iterative_movements.csv"
        movements_csv.write_text(
            "iteration_id,fact_id,source_sentence,isolated_fact,residual_sentence,"
            "similarity_score,reason,moved_at,pass_id,span_id,artifact_id,schema_version\n"
            "iter-1,fact-1,Test element text,Fact about create_app,Residual,"
            "0.50,Migration,20240101T120000Z,,,,pass-span.v1\n"  # 0.50 < 0.95
        )

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = validate_fact_migration("test-id", knowledge_path)

        assert result == 1
        captured = capsys.readouterr()
        assert "Invariant violations" in captured.out


class TestParseStartFactMigrationArgsExtended:
    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments including knowledge-path."""
        args = parse_start_fact_migration_args(
            [
                "--yaml-file",
                "/path/to/file.yml",
                "--element-id",
                "factory.create_app",
                "--knowledge-path",
                "/custom/path",
            ]
        )
        assert args.yaml_file == Path("/path/to/file.yml")
        assert args.element_id == "factory.create_app"
        assert args.knowledge_path == Path("/custom/path")


class TestParseClassifyFactsArgsExtended:
    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments including knowledge-path."""
        args = parse_classify_facts_args(
            ["--task-id", "test-uuid", "--knowledge-path", "/custom/path"]
        )
        assert args.task_id == "test-uuid"
        assert args.knowledge_path == Path("/custom/path")


class TestParseMoveFactsArgsExtended:
    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments including knowledge-path and dry-run."""
        args = parse_move_facts_args(
            [
                "--task-id",
                "test-uuid",
                "--classification-file",
                "/path/to/class.json",
                "--knowledge-path",
                "/custom/path",
                "--dry-run",
            ]
        )
        assert args.task_id == "test-uuid"
        assert args.classification_file == Path("/path/to/class.json")
        assert args.knowledge_path == Path("/custom/path")
        assert args.dry_run is True


class TestParseValidateFactMigrationArgsExtended:
    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments including knowledge-path."""
        args = parse_validate_fact_migration_args(
            ["--task-id", "test-uuid", "--knowledge-path", "/custom/path"]
        )
        assert args.task_id == "test-uuid"
        assert args.knowledge_path == Path("/custom/path")


class TestIntegrationWorkflow:
    def test_full_workflow_with_mocks(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should complete full workflow with mocked extraction.

        DuckDB requires real filesystem.
        """
        # Setup directory structure
        yaml_dir = tmp_path / "docs"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "test.yml"
        yaml_file.write_text("""items:
  - id: factory.create_app
    text: The create_app function builds a FastAPI instance.
""")

        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "movements").mkdir(parents=True)

        # Step 1: Start migration with mocked extraction
        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch.object(fact_migration.fact_extraction, "extract_facts_main", return_value=0),
        ):
            result = start_fact_migration(yaml_file, "factory.create_app", knowledge_path)

        assert result == 0

        # Get task ID from output
        captured = capsys.readouterr()
        assert "Created task:" in captured.out

        # Verify task was created
        tasks_csv = knowledge_path / "migrations" / "fact_tasks.csv"
        assert tasks_csv.exists()

    def test_handles_multiple_entities(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle multiple entities in element text.

        DuckDB requires real filesystem.
        """
        yaml_dir = tmp_path / "docs"
        yaml_dir.mkdir(parents=True)
        yaml_file = yaml_dir / "test.yml"
        yaml_file.write_text("""items:
  - id: factory.create_app
    text: The create_app function uses FastAPI and AppRouter to build.
""")

        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "migrations").mkdir(parents=True)

        with (
            patch.object(fact_migration, "REPO_ROOT", tmp_path),
            patch.object(fact_migration.fact_extraction, "extract_facts_main", return_value=0),
        ):
            result = start_fact_migration(yaml_file, "factory.create_app", knowledge_path)

        assert result == 0
        captured = capsys.readouterr()
        # Should find multiple entities
        assert "create_app" in captured.out
        assert "FastAPI" in captured.out


class TestCountInvariantFailuresFallback:
    def test_falls_back_to_python_on_duckdb_unnest_error(self, tmp_path: Path) -> None:
        """Should fall back to Python when DuckDB UNNEST fails (lines 1237-1240)."""
        csv_path = tmp_path / "iterative_movements.csv"
        # Create a valid CSV that can be read by movement_tracker
        csv_content = (
            "iteration_id,fact_id,source_sentence,isolated_fact,residual_sentence,"
            "similarity_score,reason,moved_at,pass_id,span_id,artifact_id,schema_version\n"
            "iter-1,fact-1,Source,Fact,Residual,0.80,Migration,20240101T120000Z,,,,pass-span.v1\n"
            "iter-2,fact-2,Source,Fact,Residual,0.92,Migration,20240101T120000Z,,,,pass-span.v1\n"
        )
        csv_path.write_text(csv_content)

        # Mock DuckDB to raise an error to trigger fallback
        import duckdb

        original_execute = duckdb.execute

        def mock_execute(query: str, *args: object, **kwargs: object) -> object:
            # If it's the count query with UNNEST, fail
            if "UNNEST" in query and "similarity_score" in query:
                raise duckdb.Error("UNNEST not supported for this query")
            return original_execute(query, *args, **kwargs)

        with patch.object(duckdb, "execute", mock_execute):
            # Should still work via Python fallback
            result = count_invariant_failures(csv_path, ["fact-1", "fact-2"])

        # Both facts have scores below 0.95 threshold
        assert result == 2


class TestMoveFactsSuccessfulStore:
    def test_tracks_movement_on_successful_store(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should track movement when fact is successfully stored."""
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

        # Create extractions CSV with a fact
        extractions_csv = knowledge_path / "facts" / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "fact-1,Test element text,create_app,Fact about create_app,"
            "Residual,1,0.95,20240101T120000Z\n"
        )

        # Create classification
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

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = move_facts("test-id", classification_file, knowledge_path)

        assert result == 0

        # Verify movement was tracked
        movements_csv = knowledge_path / "movements" / "iterative_movements.csv"
        assert movements_csv.exists()
        content = movements_csv.read_text()
        assert "fact-1" in content

        # Verify fact was stored
        fact_yaml_path = knowledge_path / "facts" / "fastapi.factory.facts.yml"
        assert fact_yaml_path.exists()


class TestMoveFactsWithMissingElementText:
    def test_handles_missing_element_text(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle case when element text is None."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "migrations").mkdir(parents=True)
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "movements").mkdir(parents=True)

        # Create task pointing to nonexistent YAML
        csv_path = knowledge_path / "migrations" / "fact_tasks.csv"
        header = ",".join(FACT_MIGRATION_CSV_COLUMNS)
        row = (
            "test-id,docs/nonexistent.yml,factory,pending,20240101T120000Z,,factory.create_app,1,1"
        )
        csv_path.write_text(f"{header}\n{row}\n")

        # Create classification
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

        with patch.object(fact_migration, "REPO_ROOT", tmp_path):
            result = move_facts("test-id", classification_file, knowledge_path)

        # Should still succeed (just no facts to process)
        assert result == 0
        captured = capsys.readouterr()
        # Will warn about fact not found since facts list is empty
        assert "Fact not found for ID" in captured.out
