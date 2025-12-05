"""Tests for scripts.knowledge.movement_tracker module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import duckdb
import numpy as np
import pytest

from scripts.knowledge import movement_tracker
from scripts.knowledge.movement_tracker import (
    CSV_COLUMNS,
    ITERATIVE_CSV_COLUMNS,
    IterativeMovementRecord,
    MovementRecord,
    append_iterative_movement,
    append_movement,
    compute_similarity_score,
    ensure_csv_exists,
    ensure_iterative_csv_exists,
    main,
    parse_args,
    parse_query_iterative_args,
    parse_record_iterative_args,
    query_iterative_movements,
    query_iterative_movements_main,
    record_iterative_movement_main,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestCsvColumns:
    """Tests for CSV_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "movement_id" in CSV_COLUMNS
        assert "element_id" in CSV_COLUMNS
        assert "source_file" in CSV_COLUMNS
        assert "target_file" in CSV_COLUMNS
        assert "reason" in CSV_COLUMNS
        assert "coverage_description" in CSV_COLUMNS
        assert "before_sentence" in CSV_COLUMNS
        assert "after_sentence_source" in CSV_COLUMNS
        assert "target_before_sentence" in CSV_COLUMNS
        assert "target_after_sentence" in CSV_COLUMNS
        assert "moved_at" in CSV_COLUMNS


class TestEnsureCsvExists:
    """Tests for ensure_csv_exists function."""

    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "movements" / "movements.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in CSV_COLUMNS:
            assert col in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if needed.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "movements" / "movements.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.parent.exists()

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Should not overwrite existing non-empty file.

        DuckDB requires real filesystem.
        """
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "movements.csv"
        csv_path.write_text("existing,content\n")

        ensure_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "existing,content" in content


class TestAppendMovement:
    """Tests for append_movement function."""

    def test_appends_record(self, tmp_path: Path) -> None:
        """Should append movement record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "movements.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        record = MovementRecord(
            movement_id="move-1",
            element_id="item-1",
            source_file="source.yml",
            target_file="target.yml",
            reason="Restructuring",
            coverage_description="Moving item description",
            before_sentence="Original sentence",
            after_sentence_source="New sentence in source",
            target_before_sentence="Target before",
            target_after_sentence="Target after with new content",
            moved_at="20240101T120000Z",
        )

        append_movement(csv_path, record)

        content = csv_path.read_text()
        assert "move-1" in content
        assert "item-1" in content
        assert "Restructuring" in content


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_all_arguments(self) -> None:
        """Should require all mandatory arguments."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments correctly."""
        args = parse_args(
            [
                "--id",
                "item-1",
                "--source-file",
                "/source.yml",
                "--target-file",
                "/target.yml",
                "--reason",
                "Restructuring",
                "--coverage",
                "Coverage description",
                "--before-text",
                "Before sentence",
                "--after-text-source",
                "After sentence",
                "--target-before",
                "Target before",
                "--target-after",
                "Target after",
            ]
        )

        assert args.id == "item-1"
        assert args.source_file == Path("/source.yml")
        assert args.target_file == Path("/target.yml")
        assert args.reason == "Restructuring"
        assert args.coverage == "Coverage description"

    def test_default_knowledge_path(self) -> None:
        """Should default to .knowledge directory."""
        args = parse_args(
            [
                "--id",
                "item-1",
                "--source-file",
                "/source.yml",
                "--target-file",
                "/target.yml",
                "--reason",
                "Reason",
                "--coverage",
                "Coverage",
                "--before-text",
                "Before",
                "--after-text-source",
                "After",
                "--target-before",
                "Target before",
                "--target-after",
                "Target after",
            ]
        )

        assert args.knowledge_path == Path(".knowledge")


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_missing_source(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when source file doesn't exist."""
        with patch.object(movement_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "missing.yml",
                    "--target-file",
                    "target.yml",
                    "--reason",
                    "Reason",
                    "--coverage",
                    "Coverage",
                    "--before-text",
                    "Before",
                    "--after-text-source",
                    "After",
                    "--target-before",
                    "Target before",
                    "--target-after",
                    "Target after",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_missing_target(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when target file doesn't exist."""
        with patch.object(movement_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/source.yml", contents="content")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--target-file",
                    "missing.yml",
                    "--reason",
                    "Reason",
                    "--coverage",
                    "Coverage",
                    "--before-text",
                    "Before",
                    "--after-text-source",
                    "After",
                    "--target-before",
                    "Target before",
                    "--target-after",
                    "Target after",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_zero_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and print success message.

        DuckDB requires real filesystem.
        """
        (tmp_path / "source.yml").write_text("content")
        (tmp_path / "target.yml").write_text("content")

        with (
            patch.object(movement_tracker, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--target-file",
                    "target.yml",
                    "--reason",
                    "Reason",
                    "--coverage",
                    "Coverage",
                    "--before-text",
                    "Before",
                    "--after-text-source",
                    "After",
                    "--target-before",
                    "Target before",
                    "--target-after",
                    "Target after",
                ],
            ),
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Movement recorded" in captured.out


class TestIterativeCsvColumns:
    """Tests for ITERATIVE_CSV_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "iteration_id" in ITERATIVE_CSV_COLUMNS
        assert "fact_id" in ITERATIVE_CSV_COLUMNS
        assert "source_sentence" in ITERATIVE_CSV_COLUMNS
        assert "isolated_fact" in ITERATIVE_CSV_COLUMNS
        assert "residual_sentence" in ITERATIVE_CSV_COLUMNS
        assert "similarity_score" in ITERATIVE_CSV_COLUMNS
        assert "reason" in ITERATIVE_CSV_COLUMNS
        assert "moved_at" in ITERATIVE_CSV_COLUMNS


class TestEnsureIterativeCsvExists:
    """Tests for ensure_iterative_csv_exists function."""

    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "movements" / "iterative_movements.csv"

        ensure_iterative_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in ITERATIVE_CSV_COLUMNS:
            assert col in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if needed.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "movements" / "iterative_movements.csv"

        ensure_iterative_csv_exists(csv_path)

        assert csv_path.parent.exists()

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Should not overwrite existing non-empty file.

        DuckDB requires real filesystem.
        """
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"
        csv_path.write_text("existing,content\n")

        ensure_iterative_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "existing,content" in content


class TestComputeSimilarityScore:
    """Tests for compute_similarity_score function."""

    def test_computes_similarity_for_identical_sentences(self) -> None:
        """Should return high similarity for identical content."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Mock embeddings that are identical (similarity = 1.0)
        identical_embeddings = np.array([[1.0, 0.0], [1.0, 0.0]])

        with patch(
            "scripts.knowledge.movement_tracker.embed_keywords",
            return_value=identical_embeddings,
        ):
            score = compute_similarity_score(
                "The app uses FastAPI.",
                "The app uses FastAPI.",
                "",
                mock_model,
                mock_tokenizer,
            )

        assert score == pytest.approx(1.0, abs=0.01)

    def test_computes_similarity_for_different_sentences(self) -> None:
        """Should return lower similarity for different content."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Mock embeddings that are orthogonal (similarity = 0.0)
        different_embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])

        with patch(
            "scripts.knowledge.movement_tracker.embed_keywords",
            return_value=different_embeddings,
        ):
            score = compute_similarity_score(
                "The app uses FastAPI.",
                "Something completely different.",
                "",
                mock_model,
                mock_tokenizer,
            )

        assert score == pytest.approx(0.0, abs=0.01)

    def test_handles_empty_residual(self) -> None:
        """Should handle empty residual sentence correctly."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        identical_embeddings = np.array([[1.0, 0.0], [1.0, 0.0]])

        with patch(
            "scripts.knowledge.movement_tracker.embed_keywords",
            return_value=identical_embeddings,
        ) as mock_embed:
            compute_similarity_score(
                "The app uses FastAPI.",
                "The app uses FastAPI.",
                "",
                mock_model,
                mock_tokenizer,
            )

            # Verify fact only is passed (no residual)
            call_args = mock_embed.call_args[0]
            assert call_args[0][1] == "The app uses FastAPI."


class TestAppendIterativeMovement:
    """Tests for append_iterative_movement function."""

    def test_appends_record(self, tmp_path: Path) -> None:
        """Should append iterative movement record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"
        header = ",".join(ITERATIVE_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        record = IterativeMovementRecord(
            iteration_id="iter-1",
            fact_id="fact-1",
            source_sentence="Original sentence",
            isolated_fact="Extracted fact",
            residual_sentence="Remaining sentence",
            similarity_score="0.9800",
            reason="Fact extraction",
            moved_at="20240101T120000Z",
        )

        append_iterative_movement(csv_path, record)

        content = csv_path.read_text()
        assert "iter-1" in content
        assert "fact-1" in content
        assert "Fact extraction" in content


class TestQueryIterativeMovements:
    """Tests for query_iterative_movements function."""

    def test_queries_by_entity(self, tmp_path: Path) -> None:
        """Should query movements by entity in source_sentence."""
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"

        # Create CSV with test data
        header = ",".join(ITERATIVE_CSV_COLUMNS)
        rows = [
            header,
            (
                "iter-1,fact-1,create_app is in factory.py,create_app is a function,"
                "factory.py,0.98,Fact extraction,20240101T120000Z,,,,pass-span.v1"
            ),
            (
                "iter-2,fact-2,Other sentence,Other fact,Other residual,0.95,Fact extraction,"
                "20240101T120001Z,,,,pass-span.v1"
            ),
        ]
        csv_path.write_text("\n".join(rows) + "\n")

        results = query_iterative_movements(csv_path, entity="create_app")

        assert len(results) == 1
        assert results[0]["fact_id"] == "fact-1"

    def test_queries_by_fact_id(self, tmp_path: Path) -> None:
        """Should query movements by exact fact_id."""
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"

        header = ",".join(ITERATIVE_CSV_COLUMNS)
        rows = [
            header,
            (
                "iter-1,fact-1,Sentence one,Fact one,Residual one,0.98,Fact extraction,"
                "20240101T120000Z,,,,pass-span.v1"
            ),
            (
                "iter-2,fact-2,Sentence two,Fact two,Residual two,0.95,Fact extraction,"
                "20240101T120001Z,,,,pass-span.v1"
            ),
        ]
        csv_path.write_text("\n".join(rows) + "\n")

        results = query_iterative_movements(csv_path, fact_id="fact-2")

        assert len(results) == 1
        assert results[0]["iteration_id"] == "iter-2"

    def test_returns_empty_for_no_matches(self, tmp_path: Path) -> None:
        """Should return empty list when no matches found."""
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"

        header = ",".join(ITERATIVE_CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        results = query_iterative_movements(csv_path, entity="nonexistent")

        assert results == []

    def test_returns_all_when_no_filters(self, tmp_path: Path) -> None:
        """Should return all records when no filters provided."""
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"

        header = ",".join(ITERATIVE_CSV_COLUMNS)
        rows = [
            header,
            (
                "iter-1,fact-1,Sentence one,Fact one,Residual one,0.98,Fact extraction,"
                "20240101T120000Z,,,,pass-span.v1"
            ),
            (
                "iter-2,fact-2,Sentence two,Fact two,Residual two,0.95,Fact extraction,"
                "20240101T120001Z,,,,pass-span.v1"
            ),
        ]
        csv_path.write_text("\n".join(rows) + "\n")

        results = query_iterative_movements(csv_path)

        assert len(results) == 2

    def test_logs_duckdb_error_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should log DuckDB errors to stderr instead of silently failing."""
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"
        # Write malformed CSV to trigger DuckDB error
        csv_path.write_text("not,valid,csv,format\n")

        with patch(
            "scripts.knowledge.movement_tracker.duckdb.execute",
            side_effect=duckdb.Error("Simulated DuckDB error"),
        ):
            results = query_iterative_movements(csv_path, entity="test")

        assert results == []
        captured = capsys.readouterr()
        assert "Error querying iterative movements" in captured.err
        assert "Simulated DuckDB error" in captured.err


class TestParseRecordIterativeArgs:
    """Tests for parse_record_iterative_args function."""

    def test_requires_mandatory_arguments(self) -> None:
        """Should require all mandatory arguments."""
        with pytest.raises(SystemExit):
            parse_record_iterative_args([])

    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments correctly."""
        args = parse_record_iterative_args(
            [
                "--fact-id",
                "uuid-123",
                "--before",
                "Original sentence",
                "--fact",
                "Extracted fact",
                "--after",
                "Residual sentence",
                "--reason",
                "Custom reason",
                "--model",
                "Qwen/Qwen3-Embedding-8B",
            ]
        )

        assert args.fact_id == "uuid-123"
        assert args.before == "Original sentence"
        assert args.fact == "Extracted fact"
        assert args.after == "Residual sentence"
        assert args.reason == "Custom reason"
        assert args.model == "Qwen/Qwen3-Embedding-8B"

    def test_default_values(self) -> None:
        """Should use default values for optional arguments."""
        args = parse_record_iterative_args(
            [
                "--fact-id",
                "uuid-123",
                "--before",
                "Original",
                "--fact",
                "Fact",
                "--after",
                "After",
            ]
        )

        assert args.reason == "Fact extraction"
        assert args.knowledge_path == Path(".knowledge")
        assert args.model == "Qwen/Qwen3-Embedding-0.6B"


class TestParseQueryIterativeArgs:
    """Tests for parse_query_iterative_args function."""

    def test_parses_entity_argument(self) -> None:
        """Should parse entity argument correctly."""
        args = parse_query_iterative_args(["--entity", "create_app"])

        assert args.entity == "create_app"
        assert args.fact_id is None

    def test_parses_fact_id_argument(self) -> None:
        """Should parse fact-id argument correctly."""
        args = parse_query_iterative_args(["--fact-id", "uuid-123"])

        assert args.fact_id == "uuid-123"
        assert args.entity is None

    def test_default_knowledge_path(self) -> None:
        """Should default to .knowledge directory."""
        args = parse_query_iterative_args(["--entity", "test"])

        assert args.knowledge_path == Path(".knowledge")

    def test_parses_verbose_flag(self) -> None:
        """Should parse --verbose flag correctly."""
        args = parse_query_iterative_args(["--entity", "test", "--verbose"])

        assert args.verbose is True

    def test_parses_verbose_short_flag(self) -> None:
        """Should parse -v short flag correctly."""
        args = parse_query_iterative_args(["--entity", "test", "-v"])

        assert args.verbose is True

    def test_verbose_defaults_to_false(self) -> None:
        """Should default verbose to False when not provided."""
        args = parse_query_iterative_args(["--entity", "test"])

        assert args.verbose is False


class TestRecordIterativeMovementMain:
    """Tests for record_iterative_movement_main function."""

    def test_returns_zero_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and record movement on success."""
        args = MagicMock()
        args.knowledge_path = tmp_path
        args.fact_id = "uuid-123"
        args.before = "Original sentence"
        args.fact = "Extracted fact"
        args.after = "Residual"
        args.reason = "Fact extraction"
        args.model = "test-model"
        # Set extended columns to None to trigger legacy behavior
        args.pass_id = None
        args.span_id = None
        args.artifact_id = None

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with (
            patch(
                "scripts.knowledge.movement_tracker.load_qwen_embedding_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.knowledge.movement_tracker.compute_similarity_score",
                return_value=0.98,
            ),
        ):
            result = record_iterative_movement_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Iterative movement recorded" in captured.out
        assert "0.98" in captured.out

    def test_returns_two_for_low_similarity(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 2 when similarity < 0.95 (validation failure)."""
        args = MagicMock()
        args.knowledge_path = tmp_path
        args.fact_id = "uuid-123"
        args.before = "Original sentence"
        args.fact = "Extracted fact"
        args.after = "Residual"
        args.reason = "Fact extraction"
        args.model = "test-model"
        # Set extended columns to None to trigger legacy behavior
        args.pass_id = None
        args.span_id = None
        args.artifact_id = None

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with (
            patch(
                "scripts.knowledge.movement_tracker.load_qwen_embedding_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.knowledge.movement_tracker.compute_similarity_score",
                return_value=0.85,
            ),
        ):
            result = record_iterative_movement_main(args)

        assert result == 2
        captured = capsys.readouterr()
        assert "VALIDATION FAILED" in captured.err
        assert "0.85" in captured.err
        # Record should still be persisted
        assert "Iterative movement recorded" in captured.out

    def test_returns_one_on_model_load_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when model loading fails."""
        args = MagicMock()
        args.knowledge_path = tmp_path
        args.model = "nonexistent-model"

        with patch(
            "scripts.knowledge.movement_tracker.load_qwen_embedding_model",
            side_effect=Exception("Model not found"),
        ):
            result = record_iterative_movement_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error loading model" in captured.err


class TestQueryIterativeMovementsMain:
    """Tests for query_iterative_movements_main function."""

    def test_returns_zero_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and display results on success."""
        # Create test CSV
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"
        header = ",".join(ITERATIVE_CSV_COLUMNS)
        rows = [
            header,
            (
                "iter-1,fact-1,Sentence with create_app,Fact,Residual,0.98,Fact extraction,"
                "20240101T120000Z,,,,pass-span.v1"
            ),
        ]
        csv_path.write_text("\n".join(rows) + "\n")

        args = MagicMock()
        args.knowledge_path = tmp_path
        args.entity = "create_app"
        args.fact_id = None
        args.verbose = False

        result = query_iterative_movements_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "iter-1" in captured.out
        # In compact mode, source_sentence is shown truncated
        assert "Sentence with create_app" in captured.out

    def test_returns_one_when_no_filters(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when no entity or fact_id provided."""
        args = MagicMock()
        args.entity = None
        args.fact_id = None

        result = query_iterative_movements_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "At least one of" in captured.err

    def test_prints_results_in_tabular_format(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print results in compact tabular format with headers."""
        # Create test CSV
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"
        header = ",".join(ITERATIVE_CSV_COLUMNS)
        rows = [
            header,
            (
                "iter-1,fact-1,Sentence one,Fact one,Residual one,0.98,Reason one,"
                "20240101T120000Z,,,,pass-span.v1"
            ),
            (
                "iter-2,fact-2,Sentence two,Fact two,Residual two,0.95,Reason two,"
                "20240101T120001Z,,,,pass-span.v1"
            ),
        ]
        csv_path.write_text("\n".join(rows) + "\n")

        args = MagicMock()
        args.knowledge_path = tmp_path
        args.entity = None
        args.fact_id = "fact-1"
        args.verbose = False

        result = query_iterative_movements_main(args)

        assert result == 0
        captured = capsys.readouterr()
        # Check compact table headers include extraction chain columns
        assert "iteration_id" in captured.out
        assert "similarity" in captured.out
        assert "source_sentence" in captured.out
        assert "isolated_fact" in captured.out
        # Check record count
        assert "1 record(s)" in captured.out

    def test_prints_verbose_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print full extraction chain details in verbose mode."""
        # Create test CSV
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "iterative_movements.csv"
        header = ",".join(ITERATIVE_CSV_COLUMNS)
        rows = [
            header,
            (
                "iter-1,fact-1,Full source sentence here,Extracted fact text,"
                "Residual after extraction,0.98,Fact extraction,"
                "20240101T120000Z,,,,pass-span.v1"
            ),
        ]
        csv_path.write_text("\n".join(rows) + "\n")

        args = MagicMock()
        args.knowledge_path = tmp_path
        args.entity = "source"
        args.fact_id = None
        args.verbose = True

        result = query_iterative_movements_main(args)

        assert result == 0
        captured = capsys.readouterr()
        # Verbose mode shows full details with labels
        assert "--- Record 1 ---" in captured.out
        assert "iteration_id:" in captured.out
        assert "fact_id:" in captured.out
        assert "source_sentence:" in captured.out
        assert "isolated_fact:" in captured.out
        assert "residual_sentence:" in captured.out
        # Full text should be visible
        assert "Full source sentence here" in captured.out
        assert "Extracted fact text" in captured.out
        assert "Residual after extraction" in captured.out
