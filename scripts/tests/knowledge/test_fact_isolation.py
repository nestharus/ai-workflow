"""Tests for scripts.knowledge.fact_isolation module."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from scripts.knowledge import fact_isolation
from scripts.knowledge.fact_isolation import (
    ISOLATION_CSV_COLUMNS,
    IterativeMovementRecord,
    ValidationResult,
    compute_semantic_similarity,
    isolate_entity_facts_main,
    parse_args,
    prepare_movement_records,
    read_extraction_results,
    validate_isolation,
    write_isolation_records,
)

# CSV column header for fact extraction records
FACT_CSV_COLUMNS = [
    "fact_id",
    "source_sentence",
    "entity",
    "fact_text",
    "rewritten_sentence",
    "iteration",
    "confidence",
    "extracted_at",
]


def _make_fact_row(
    fact_id: str = "fact-1",
    source_sentence: str = "Test sentence with entity.",
    entity: str = "entity",
    fact_text: str = "entity is a test",
    rewritten_sentence: str = "Test sentence.",
    iteration: str = "1",
    confidence: str = "0.95",
    extracted_at: str = "20240101T120000Z",
) -> str:
    """Create a CSV row for the extractions table."""
    return ",".join(
        [
            fact_id,
            f'"{source_sentence}"',
            entity,
            f'"{fact_text}"',
            f'"{rewritten_sentence}"',
            iteration,
            confidence,
            extracted_at,
        ]
    )


@pytest.fixture
def mock_qwen_model() -> tuple[MagicMock, MagicMock]:
    """Create mock Qwen model and tokenizer for testing."""
    import numpy as np

    mock_model = MagicMock()
    mock_tokenizer = MagicMock()

    # Mock tokenizer output
    mock_tokenizer.return_value = {
        "input_ids": MagicMock(),
        "attention_mask": MagicMock(),
    }

    # Mock model output with embeddings that produce high similarity
    mock_output = MagicMock()
    mock_output.last_hidden_state = MagicMock()
    # Return 768-dimensional embeddings
    mock_output.last_hidden_state.cpu.return_value.numpy.return_value = np.random.rand(2, 10, 768)
    mock_model.return_value = mock_output

    return mock_model, mock_tokenizer


class TestReadExtractionResults:
    """Tests for read_extraction_results function."""

    def test_reads_facts_for_sentence_and_entity(self, tmp_path: Path) -> None:
        """Should read facts filtered by source_sentence and entity.

        DuckDB requires real filesystem.
        """
        facts_dir = tmp_path / ".knowledge" / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        header = ",".join(FACT_CSV_COLUMNS)
        row1 = _make_fact_row(
            fact_id="fact-1",
            source_sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            fact_text="FastAPI is a web framework",
            rewritten_sentence="Test sentence.",
            iteration="1",
        )
        csv_path.write_text(f"{header}\n{row1}\n")

        result = read_extraction_results(csv_path, "Test sentence with FastAPI.", "FastAPI")

        assert len(result) == 1
        assert result[0]["fact_id"] == "fact-1"
        assert result[0]["entity"] == "FastAPI"

    def test_filters_by_entity(self, tmp_path: Path) -> None:
        """Should only return facts for the specified entity.

        DuckDB requires real filesystem.
        """
        facts_dir = tmp_path / ".knowledge" / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        header = ",".join(FACT_CSV_COLUMNS)
        row1 = _make_fact_row(
            fact_id="fact-1",
            source_sentence="Test sentence.",
            entity="FastAPI",
            iteration="1",
        )
        row2 = _make_fact_row(
            fact_id="fact-2",
            source_sentence="Test sentence.",
            entity="Django",
            iteration="1",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = read_extraction_results(csv_path, "Test sentence.", "FastAPI")

        assert len(result) == 1
        assert result[0]["entity"] == "FastAPI"

    def test_orders_by_iteration(self, tmp_path: Path) -> None:
        """Should order results by iteration number.

        DuckDB requires real filesystem.
        """
        facts_dir = tmp_path / ".knowledge" / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        header = ",".join(FACT_CSV_COLUMNS)
        # Insert in reverse order to test sorting
        row2 = _make_fact_row(fact_id="fact-2", iteration="2")
        row1 = _make_fact_row(fact_id="fact-1", iteration="1")
        csv_path.write_text(f"{header}\n{row2}\n{row1}\n")

        result = read_extraction_results(csv_path, "Test sentence with entity.", "entity")

        assert len(result) == 2
        assert result[0]["iteration"] == "1"
        assert result[1]["iteration"] == "2"

    def test_returns_empty_for_no_matches(self, tmp_path: Path) -> None:
        """Should return empty list when no facts match.

        DuckDB requires real filesystem.
        """
        facts_dir = tmp_path / ".knowledge" / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        header = ",".join(FACT_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        result = read_extraction_results(csv_path, "Test sentence.", "NonexistentEntity")

        assert result == []

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        """Should return empty list when CSV file doesn't exist."""
        csv_path = tmp_path / "nonexistent.csv"

        result = read_extraction_results(csv_path, "Test sentence.", "entity")

        assert result == []

    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        """Should return empty list when CSV file is empty."""
        facts_dir = tmp_path / ".knowledge" / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"
        csv_path.write_text("")

        result = read_extraction_results(csv_path, "Test sentence.", "entity")

        assert result == []

    def test_logs_warning_on_duckdb_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should log warning to stderr on DuckDB error."""
        facts_dir = tmp_path / ".knowledge" / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"
        csv_path.write_text("invalid csv content without proper headers\n")

        with patch.object(duckdb, "execute", side_effect=duckdb.Error("Test error")):
            result = read_extraction_results(csv_path, "Test sentence.", "entity")

        assert result == []
        captured = capsys.readouterr()
        assert "Warning: DuckDB error" in captured.err
        assert "Test error" in captured.err


class TestComputeSemanticSimilarity:
    """Tests for compute_semantic_similarity function."""

    def test_computes_similarity(self, mock_qwen_model: tuple[MagicMock, MagicMock]) -> None:
        """Should compute cosine similarity between sentences."""
        model, tokenizer = mock_qwen_model

        with (
            patch.object(fact_isolation, "embed_keywords") as mock_embed,
            patch.object(fact_isolation, "compute_cosine_similarity") as mock_cosine,
        ):
            import numpy as np

            mock_embed.return_value = np.array([[1.0, 0.0], [0.9, 0.1]])
            mock_cosine.return_value = np.array([[1.0, 0.95], [0.95, 1.0]])

            result = compute_semantic_similarity("original", "reconstructed", model, tokenizer)

            assert result == 0.95
            mock_embed.assert_called_once()
            mock_cosine.assert_called_once()


class TestValidateIsolation:
    """Tests for validate_isolation function."""

    def test_validation_with_semantic_similarity(
        self, mock_qwen_model: tuple[MagicMock, MagicMock]
    ) -> None:
        """Should compute semantic similarity and set information_preserved accordingly."""
        model, tokenizer = mock_qwen_model
        facts = [
            {"fact_id": "1", "fact_text": "FastAPI is a framework", "iteration": "1"},
        ]

        with patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.98):
            result = validate_isolation(
                facts, "Test sentence.", "FastAPI", "Original sentence.", model, tokenizer
            )

        assert result["entity_absent"] is True
        assert result["information_preserved"] is True
        assert result["semantic_similarity"] == 0.98
        assert result["extraction_complete"] is True
        assert result["total_facts"] == 1

    def test_validation_low_similarity(self, mock_qwen_model: tuple[MagicMock, MagicMock]) -> None:
        """Should set information_preserved to False when similarity < 0.95."""
        model, tokenizer = mock_qwen_model
        facts = [
            {"fact_id": "1", "fact_text": "FastAPI is a framework", "iteration": "1"},
        ]

        with patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.80):
            result = validate_isolation(
                facts, "Test sentence.", "FastAPI", "Original sentence.", model, tokenizer
            )

        assert result["information_preserved"] is False
        assert result["semantic_similarity"] == 0.80
        assert result["extraction_complete"] is False

    def test_validation_entity_present(self, mock_qwen_model: tuple[MagicMock, MagicMock]) -> None:
        """Should return failure when entity is still in residual."""
        model, tokenizer = mock_qwen_model
        facts = [
            {"fact_id": "1", "fact_text": "FastAPI is a framework", "iteration": "1"},
        ]

        with patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.98):
            result = validate_isolation(
                facts, "Test sentence with FastAPI.", "FastAPI", "Original.", model, tokenizer
            )

        assert result["entity_absent"] is False
        assert result["extraction_complete"] is False

    def test_validation_case_insensitive(
        self, mock_qwen_model: tuple[MagicMock, MagicMock]
    ) -> None:
        """Should check entity absence case-insensitively."""
        model, tokenizer = mock_qwen_model
        facts = [
            {"fact_id": "1", "fact_text": "fastapi is a framework", "iteration": "1"},
        ]

        with patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.98):
            result = validate_isolation(
                facts, "Test sentence with FASTAPI.", "FastAPI", "Original.", model, tokenizer
            )

        assert result["entity_absent"] is False

    def test_validation_no_facts(self) -> None:
        """Should return incomplete when no facts extracted."""
        result = validate_isolation([], "Test sentence.", "FastAPI", "Original.", None, None)

        assert result["entity_absent"] is True
        assert result["extraction_complete"] is False
        assert result["information_preserved"] is False
        assert result["semantic_similarity"] == 0.0
        assert result["total_facts"] == 0

    def test_validation_no_model(self) -> None:
        """Should handle case when model is not provided."""
        facts = [
            {"fact_id": "1", "fact_text": "FastAPI is a framework", "iteration": "1"},
        ]

        result = validate_isolation(facts, "Test sentence.", "FastAPI", "Original.", None, None)

        # Without model, information_preserved should be False
        assert result["information_preserved"] is False
        assert result["semantic_similarity"] == 0.0

    def test_validation_result_structure(
        self, mock_qwen_model: tuple[MagicMock, MagicMock]
    ) -> None:
        """Should return ValidationResult with all required fields."""
        model, tokenizer = mock_qwen_model
        facts = [{"fact_id": "1", "fact_text": "test", "iteration": "1"}]

        with patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.96):
            result = validate_isolation(facts, "residual", "entity", "original", model, tokenizer)

        assert "extraction_complete" in result
        assert "entity_absent" in result
        assert "information_preserved" in result
        assert "semantic_similarity" in result
        assert "total_facts" in result
        assert isinstance(result, dict)


class TestPrepareMovementRecords:
    """Tests for prepare_movement_records function."""

    def test_single_fact_record_with_fact_id(self) -> None:
        """Should create movement record with fact_id for single fact."""
        facts = [
            {
                "fact_id": "uuid-1234",
                "iteration": "1",
                "fact_text": "FastAPI is a framework",
                "rewritten_sentence": "Test sentence.",
            },
        ]

        records = prepare_movement_records(facts, "Test sentence with FastAPI.", "FastAPI")

        assert len(records) == 1
        assert records[0]["fact_id"] == "uuid-1234"
        assert records[0]["iteration"] == 1
        assert records[0]["before_sentence"] == "Test sentence with FastAPI."
        assert records[0]["isolated_fact"] == "FastAPI is a framework"
        assert records[0]["after_sentence"] == "Test sentence."
        assert records[0]["entity"] == "FastAPI"

    def test_multiple_facts_chain(self) -> None:
        """Should chain before/after sentences across iterations."""
        facts = [
            {
                "fact_id": "uuid-1",
                "iteration": "1",
                "fact_text": "FastAPI is fast",
                "rewritten_sentence": "API uses Python for web.",
            },
            {
                "fact_id": "uuid-2",
                "iteration": "2",
                "fact_text": "FastAPI uses Python",
                "rewritten_sentence": "API for web.",
            },
        ]

        records = prepare_movement_records(
            facts, "FastAPI is fast and uses Python for web.", "FastAPI"
        )

        assert len(records) == 2
        # First iteration
        assert records[0]["fact_id"] == "uuid-1"
        assert records[0]["before_sentence"] == "FastAPI is fast and uses Python for web."
        assert records[0]["after_sentence"] == "API uses Python for web."
        # Second iteration - before should be first's after
        assert records[1]["fact_id"] == "uuid-2"
        assert records[1]["before_sentence"] == "API uses Python for web."
        assert records[1]["after_sentence"] == "API for web."

    def test_empty_facts_list(self) -> None:
        """Should return empty list for no facts."""
        records = prepare_movement_records([], "Test sentence.", "FastAPI")

        assert records == []

    def test_movement_record_structure(self) -> None:
        """Should include all required fields in movement record."""
        facts = [
            {
                "fact_id": "test-id",
                "iteration": "1",
                "fact_text": "test fact",
                "rewritten_sentence": "rewritten",
            },
        ]

        records = prepare_movement_records(facts, "original", "entity")

        assert len(records) == 1
        record = records[0]
        assert "fact_id" in record
        assert "iteration" in record
        assert "before_sentence" in record
        assert "isolated_fact" in record
        assert "after_sentence" in record
        assert "entity" in record

    def test_handles_missing_fields_gracefully(self) -> None:
        """Should handle missing fields with empty defaults."""
        facts = [
            {"iteration": "1"},  # Missing fact_id, fact_text and rewritten_sentence
        ]

        records = prepare_movement_records(facts, "original", "entity")

        assert len(records) == 1
        assert records[0]["fact_id"] == ""
        assert records[0]["isolated_fact"] == ""
        assert records[0]["after_sentence"] == ""


class TestWriteIsolationRecords:
    """Tests for write_isolation_records function."""

    def test_writes_records_to_csv(self, tmp_path: Path) -> None:
        """Should write isolation records to CSV file."""
        csv_path = tmp_path / "isolation.csv"
        records: list[IterativeMovementRecord] = [
            {
                "fact_id": "fact-1",
                "iteration": 1,
                "entity": "FastAPI",
                "before_sentence": "Original sentence with FastAPI.",
                "isolated_fact": "FastAPI is a framework",
                "after_sentence": "Original sentence.",
            },
        ]

        write_isolation_records(csv_path, records)

        assert csv_path.exists()
        content = csv_path.read_text()
        assert "fact_id" in content
        assert "fact-1" in content
        assert "FastAPI" in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if needed."""
        csv_path = tmp_path / "nested" / "dir" / "isolation.csv"
        records: list[IterativeMovementRecord] = [
            {
                "fact_id": "fact-1",
                "iteration": 1,
                "entity": "Test",
                "before_sentence": "before",
                "isolated_fact": "fact",
                "after_sentence": "after",
            },
        ]

        write_isolation_records(csv_path, records)

        assert csv_path.exists()

    def test_does_not_write_empty_records(self, tmp_path: Path) -> None:
        """Should not create file for empty records list."""
        csv_path = tmp_path / "isolation.csv"

        write_isolation_records(csv_path, [])

        assert not csv_path.exists()

    def test_csv_contains_all_columns(self, tmp_path: Path) -> None:
        """Should write CSV with all required columns."""
        csv_path = tmp_path / "isolation.csv"
        records: list[IterativeMovementRecord] = [
            {
                "fact_id": "fact-1",
                "iteration": 1,
                "entity": "Test",
                "before_sentence": "before",
                "isolated_fact": "fact",
                "after_sentence": "after",
            },
        ]

        write_isolation_records(csv_path, records)

        content = csv_path.read_text()
        for col in ISOLATION_CSV_COLUMNS:
            assert col in content


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_sentence(self) -> None:
        """Should require --sentence argument."""
        with pytest.raises(SystemExit):
            parse_args(["--entity", "FastAPI"])

    def test_requires_entity(self) -> None:
        """Should require --entity argument."""
        with pytest.raises(SystemExit):
            parse_args(["--sentence", "Test sentence."])

    def test_parses_required_args(self) -> None:
        """Should parse --sentence and --entity arguments."""
        args = parse_args(["--sentence", "Test sentence.", "--entity", "FastAPI"])

        assert args.sentence == "Test sentence."
        assert args.entity == "FastAPI"

    def test_default_knowledge_path(self) -> None:
        """Should default knowledge-path to .knowledge."""
        args = parse_args(["--sentence", "Test.", "--entity", "X"])

        assert args.knowledge_path == Path(".knowledge")

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(
            ["--sentence", "Test.", "--entity", "X", "--knowledge-path", "custom/.knowledge"]
        )

        assert args.knowledge_path == Path("custom/.knowledge")

    def test_dry_run_flag(self) -> None:
        """Should parse --dry-run flag."""
        args = parse_args(["--sentence", "Test.", "--entity", "X", "--dry-run"])

        assert args.dry_run is True

    def test_dry_run_default_false(self) -> None:
        """Should default dry_run to False."""
        args = parse_args(["--sentence", "Test.", "--entity", "X"])

        assert args.dry_run is False

    def test_default_model(self) -> None:
        """Should default model to Qwen/Qwen3-Embedding-0.6B."""
        args = parse_args(["--sentence", "Test.", "--entity", "X"])

        assert args.model == "Qwen/Qwen3-Embedding-0.6B"

    def test_custom_model(self) -> None:
        """Should parse --model argument."""
        args = parse_args(
            ["--sentence", "Test.", "--entity", "X", "--model", "Qwen/Qwen3-Embedding-8B"]
        )

        assert args.model == "Qwen/Qwen3-Embedding-8B"

    def test_default_output_none(self) -> None:
        """Should default output to None."""
        args = parse_args(["--sentence", "Test.", "--entity", "X"])

        assert args.output is None

    def test_custom_output_path(self) -> None:
        """Should parse --output argument."""
        args = parse_args(["--sentence", "Test.", "--entity", "X", "--output", "custom/output.csv"])

        assert args.output == Path("custom/output.csv")


class TestIsolateEntityFactsMain:
    """Tests for isolate_entity_facts_main function."""

    def test_calls_fact_extraction(self, tmp_path: Path) -> None:
        """Should call fact_extraction.extract_facts_main."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract:
            mock_extract.return_value = 0

            result = isolate_entity_facts_main(args)

            mock_extract.assert_called_once()
            assert result == 0

    def test_returns_one_on_extraction_error(self, tmp_path: Path) -> None:
        """Should return 1 when fact extraction fails."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        args = argparse.Namespace(
            sentence="Test sentence.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract:
            mock_extract.return_value = 1

            result = isolate_entity_facts_main(args)

            assert result == 1

    def test_dry_run_returns_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 0 in dry-run mode after successful extraction."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract:
            mock_extract.return_value = 0

            result = isolate_entity_facts_main(args)

            assert result == 0
            captured = capsys.readouterr()
            assert "dry run" in captured.out.lower()
            assert "Success (dry run)" in captured.out

    def test_dry_run_skips_validation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should skip validation and CSV read in dry-run mode."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract:
            mock_extract.return_value = 0

            isolate_entity_facts_main(args)

            captured = capsys.readouterr()
            assert "(dry run - skipping CSV read)" in captured.out
            assert "(dry run - skipping validation)" in captured.out
            assert "(dry run - skipping output)" in captured.out

    def test_returns_two_on_incomplete_extraction(self, tmp_path: Path) -> None:
        """Should return 2 when extraction is incomplete."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        # Create CSV with fact but entity still in residual
        header = ",".join(FACT_CSV_COLUMNS)
        row = _make_fact_row(
            source_sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            fact_text="FastAPI is fast",
            rewritten_sentence="Test sentence with FastAPI still here.",  # Entity still present
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with (
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch.object(fact_isolation, "load_qwen_embedding_model") as mock_load,
            patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.98),
        ):
            mock_extract.return_value = 0
            mock_load.return_value = (MagicMock(), MagicMock())

            result = isolate_entity_facts_main(args)

            assert result == 2

    def test_returns_zero_on_complete_extraction(self, tmp_path: Path) -> None:
        """Should return 0 when extraction is complete and validated."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        # Create CSV with fact and entity absent from residual
        header = ",".join(FACT_CSV_COLUMNS)
        row = _make_fact_row(
            source_sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            fact_text="FastAPI is a framework",
            rewritten_sentence="Test sentence.",  # Entity absent
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with (
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch.object(fact_isolation, "load_qwen_embedding_model") as mock_load,
            patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.98),
        ):
            mock_extract.return_value = 0
            mock_load.return_value = (MagicMock(), MagicMock())

            result = isolate_entity_facts_main(args)

            assert result == 0

    def test_writes_isolation_records_csv(self, tmp_path: Path) -> None:
        """Should write isolation records to output CSV."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"
        output_path = tmp_path / "output.csv"

        header = ",".join(FACT_CSV_COLUMNS)
        row = _make_fact_row(
            fact_id="test-fact-id",
            source_sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            fact_text="FastAPI is a framework",
            rewritten_sentence="Test sentence.",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=output_path,
        )

        with (
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch.object(fact_isolation, "load_qwen_embedding_model") as mock_load,
            patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.98),
        ):
            mock_extract.return_value = 0
            mock_load.return_value = (MagicMock(), MagicMock())

            isolate_entity_facts_main(args)

            assert output_path.exists()
            content = output_path.read_text()
            assert "test-fact-id" in content
            assert "FastAPI" in content

    def test_prints_report_header(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print report header with entity and sentence."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract:
            mock_extract.return_value = 0

            isolate_entity_facts_main(args)

            captured = capsys.readouterr()
            assert "Fact Isolation Report" in captured.out
            assert "FastAPI" in captured.out

    def test_prints_validation_status_with_similarity(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print validation status with similarity score in report."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        header = ",".join(FACT_CSV_COLUMNS)
        row = _make_fact_row(
            source_sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            fact_text="FastAPI is fast",
            rewritten_sentence="Test sentence.",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with (
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch.object(fact_isolation, "load_qwen_embedding_model") as mock_load,
            patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.97),
        ):
            mock_extract.return_value = 0
            mock_load.return_value = (MagicMock(), MagicMock())

            isolate_entity_facts_main(args)

            captured = capsys.readouterr()
            assert "Validation:" in captured.out
            assert "Entity absent" in captured.out
            assert "similarity: 0.97" in captured.out

    def test_handles_absolute_knowledge_path(self, tmp_path: Path) -> None:
        """Should handle absolute knowledge path."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        args = argparse.Namespace(
            sentence="Test sentence.",
            entity="FastAPI",
            knowledge_path=knowledge_path.resolve(),  # Absolute path
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract:
            mock_extract.return_value = 0

            result = isolate_entity_facts_main(args)

            assert result == 0

    def test_handles_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should resolve relative knowledge path from REPO_ROOT."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        args = argparse.Namespace(
            sentence="Test sentence.",
            entity="FastAPI",
            knowledge_path=Path(".knowledge"),  # Relative path
            dry_run=True,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with (
            patch.object(fact_isolation, "REPO_ROOT", tmp_path),
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
        ):
            mock_extract.return_value = 0

            result = isolate_entity_facts_main(args)

            assert result == 0

    def test_handles_relative_output_path(self, tmp_path: Path) -> None:
        """Resolve relative output path from REPO_ROOT (covers line 428, branches [425, 428])."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        # Create CSV with extraction results
        header = ",".join(FACT_CSV_COLUMNS)
        row = _make_fact_row(
            source_sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            fact_text="FastAPI is a framework",
            rewritten_sentence="Test sentence.",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=Path("relative/output.csv"),  # Relative path
        )

        with (
            patch.object(fact_isolation, "REPO_ROOT", tmp_path),
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch.object(fact_isolation, "load_qwen_embedding_model") as mock_load,
            patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.98),
        ):
            mock_extract.return_value = 0
            mock_load.return_value = (MagicMock(), MagicMock())

            isolate_entity_facts_main(args)

            # Should resolve to REPO_ROOT / relative/output.csv
            expected_output = tmp_path / "relative" / "output.csv"
            assert expected_output.exists()

    def test_handles_embedding_model_load_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle embedding model load failure (covers lines 492-493)."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        header = ",".join(FACT_CSV_COLUMNS)
        row = _make_fact_row(
            source_sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            fact_text="FastAPI is fast",
            rewritten_sentence="Test sentence.",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with (
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch.object(fact_isolation, "load_qwen_embedding_model") as mock_load,
        ):
            mock_extract.return_value = 0
            mock_load.side_effect = Exception("Model load failed")

            isolate_entity_facts_main(args)

            # Should continue with validation but without semantic similarity
            captured = capsys.readouterr()
            assert "Could not load embedding model" in captured.err

    def test_prints_empty_residual_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print (empty) when residual is empty (covers line 513, branch [510,513])."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        # Create a CSV with empty string for rewritten_sentence (residual)
        # Note: Empty string in CSV should be represented properly
        header = ",".join(FACT_CSV_COLUMNS)
        # Create row with empty residual - need to quote empty string properly
        row_parts = [
            "fact-1",  # fact_id
            '"FastAPI is a framework."',  # source_sentence
            "FastAPI",  # entity
            '"FastAPI is a framework"',  # fact_text
            '""',  # rewritten_sentence - empty string quoted
            "1",  # iteration
            "0.95",  # confidence
            "20240101T120000Z",  # extracted_at
        ]
        row = ",".join(row_parts)
        csv_path.write_text(f"{header}\n{row}\n")

        args = argparse.Namespace(
            sentence="FastAPI is a framework.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        mock_movement_record = {
            "fact_id": "fact-12345678",
            "iteration": 1,
            "entity": "FastAPI",
            "before_sentence": "FastAPI is a framework.",
            "isolated_fact": "FastAPI is a framework",
            "after_sentence": "",
        }

        with (
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch.object(fact_isolation, "load_qwen_embedding_model") as mock_load,
            patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.98),
            patch.object(fact_isolation, "validate_isolation") as mock_validate,
            patch.object(
                fact_isolation, "prepare_movement_records", return_value=[mock_movement_record]
            ),
            patch.object(fact_isolation, "write_isolation_records"),
        ):
            mock_extract.return_value = 0
            mock_load.return_value = (MagicMock(), MagicMock())
            mock_validate.return_value = ValidationResult(
                extraction_complete=True,
                entity_absent=True,
                information_preserved=True,
                semantic_similarity=0.98,
                total_facts=1,
            )

            isolate_entity_facts_main(args)

            captured = capsys.readouterr()
            # The test verifies "(empty)" is printed for empty residual
            assert "Residual: (empty)" in captured.out


class TestMainFunction:
    """Tests for main entry point function."""

    def test_main_calls_isolate_entity_facts_main(self, tmp_path: Path) -> None:
        """Should parse args and call isolate_entity_facts_main."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        with (
            patch.object(fact_isolation, "REPO_ROOT", tmp_path),
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch(
                "sys.argv",
                [
                    "script",
                    "--sentence",
                    "Test sentence.",
                    "--entity",
                    "FastAPI",
                    "--knowledge-path",
                    str(knowledge_path),
                    "--dry-run",
                ],
            ),
        ):
            mock_extract.return_value = 0

            from scripts.knowledge.fact_isolation import main

            result = main()

            assert result == 0
            mock_extract.assert_called_once()


class TestTypedDicts:
    """Tests for TypedDict definitions."""

    def test_iterative_movement_record_type(self) -> None:
        """Should define correct structure for IterativeMovementRecord including fact_id."""
        record: IterativeMovementRecord = {
            "fact_id": "uuid-1234",
            "iteration": 1,
            "before_sentence": "before",
            "isolated_fact": "fact",
            "after_sentence": "after",
            "entity": "entity",
        }

        assert record["fact_id"] == "uuid-1234"
        assert record["iteration"] == 1
        assert record["before_sentence"] == "before"
        assert record["isolated_fact"] == "fact"
        assert record["after_sentence"] == "after"
        assert record["entity"] == "entity"

    def test_validation_result_type(self) -> None:
        """Should define correct structure for ValidationResult including semantic_similarity."""
        result: ValidationResult = {
            "extraction_complete": True,
            "entity_absent": True,
            "information_preserved": True,
            "semantic_similarity": 0.98,
            "total_facts": 2,
        }

        assert result["extraction_complete"] is True
        assert result["entity_absent"] is True
        assert result["information_preserved"] is True
        assert result["semantic_similarity"] == 0.98
        assert result["total_facts"] == 2


class TestIntegration:
    """Integration tests for fact isolation workflow."""

    def test_full_workflow_with_mock_extraction(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should complete full workflow: extract -> read -> validate -> report."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        # Pre-populate CSV with extraction results
        header = ",".join(FACT_CSV_COLUMNS)
        row1 = _make_fact_row(
            fact_id="fact-1",
            source_sentence="Mount endpoints using create_app in factory.py.",
            entity="create_app",
            fact_text="create_app is located in factory.py",
            rewritten_sentence="Mount endpoints using in factory.py.",
            iteration="1",
            confidence="0.95",
        )
        row2 = _make_fact_row(
            fact_id="fact-2",
            source_sentence="Mount endpoints using create_app in factory.py.",
            entity="create_app",
            fact_text="create_app is used to mount endpoints",
            rewritten_sentence="Mount in factory.py.",
            iteration="2",
            confidence="0.92",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        args = argparse.Namespace(
            sentence="Mount endpoints using create_app in factory.py.",
            entity="create_app",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with (
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch.object(fact_isolation, "load_qwen_embedding_model") as mock_load,
            patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.97),
        ):
            mock_extract.return_value = 0
            mock_load.return_value = (MagicMock(), MagicMock())

            result = isolate_entity_facts_main(args)

            # Should complete successfully (entity absent from final residual)
            assert result == 0

            captured = capsys.readouterr()
            # Verify report contains expected sections
            assert "Fact Isolation Report" in captured.out
            assert "create_app" in captured.out
            assert "Validation:" in captured.out
            assert "Movement Records Prepared: 2" in captured.out
            assert "Success" in captured.out

    def test_workflow_with_no_facts_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle case where no facts are found in CSV."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"

        # Empty CSV (header only)
        header = ",".join(FACT_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=None,
        )

        with patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract:
            mock_extract.return_value = 0

            result = isolate_entity_facts_main(args)

            # Should return 2 (incomplete - no facts found but not an error)
            assert result == 2

            captured = capsys.readouterr()
            assert "No facts found" in captured.out or "Partial success" in captured.out

    def test_isolation_csv_contains_fact_ids(self, tmp_path: Path) -> None:
        """Should write isolation records with fact_id linking to extractions."""
        knowledge_path = tmp_path / ".knowledge"
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)
        csv_path = facts_dir / "extractions.csv"
        output_path = tmp_path / "isolation.csv"

        header = ",".join(FACT_CSV_COLUMNS)
        row = _make_fact_row(
            fact_id="linking-fact-id",
            source_sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            fact_text="FastAPI is a framework",
            rewritten_sentence="Test sentence.",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = argparse.Namespace(
            sentence="Test sentence with FastAPI.",
            entity="FastAPI",
            knowledge_path=knowledge_path,
            dry_run=False,
            model="Qwen/Qwen3-Embedding-0.6B",
            output=output_path,
        )

        with (
            patch.object(fact_isolation.fact_extraction, "extract_facts_main") as mock_extract,
            patch.object(fact_isolation, "load_qwen_embedding_model") as mock_load,
            patch.object(fact_isolation, "compute_semantic_similarity", return_value=0.98),
        ):
            mock_extract.return_value = 0
            mock_load.return_value = (MagicMock(), MagicMock())

            isolate_entity_facts_main(args)

            # Verify isolation CSV contains fact_id
            assert output_path.exists()
            content = output_path.read_text()
            assert "linking-fact-id" in content
            assert "fact_id" in content  # Column header
