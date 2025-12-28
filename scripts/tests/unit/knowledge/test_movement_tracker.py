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


class TestMain:
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


class TestComputeSimilarityScore:
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


class TestQueryIterativeMovements:
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


class TestRecordIterativeMovementMain:
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


class TestRecordIterativeMovementMainExtended:
    def test_uses_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should use absolute knowledge path when provided."""
        abs_knowledge_path = tmp_path / "absolute_knowledge"
        args = MagicMock()
        # Use absolute path directly - tmp_path is already absolute
        args.knowledge_path = abs_knowledge_path
        args.fact_id = "uuid-abs"
        args.before = "Absolute test sentence"
        args.fact = "Absolute fact"
        args.after = "Absolute residual"
        args.reason = "Fact extraction"
        args.model = "test-model"
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
        # Verify CSV was created in absolute path
        csv_path = abs_knowledge_path / "movements" / "iterative_movements.csv"
        assert csv_path.exists()

    def test_uses_explicit_pass_span_artifact_ids(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should use explicit pass_id, span_id, artifact_id when provided."""
        args = MagicMock()
        args.knowledge_path = tmp_path
        args.fact_id = "uuid-explicit"
        args.before = "Artifact level sentence"
        args.fact = "Artifact level fact"
        args.after = "Artifact level residual"
        args.reason = "Artifact extraction"
        args.model = "test-model"
        # Provide explicit IDs for artifact-level extraction
        args.pass_id = "pass-001"
        args.span_id = "span-001"
        args.artifact_id = "artifact-001"

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

        # Verify the record contains explicit IDs
        csv_path = tmp_path / "movements" / "iterative_movements.csv"
        content = csv_path.read_text()
        assert "pass-001" in content
        assert "span-001" in content
        assert "artifact-001" in content


class TestMainExtended:
    def test_uses_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should use absolute knowledge path when provided."""
        # Create files
        (tmp_path / "source.yml").write_text("content")
        (tmp_path / "target.yml").write_text("content")
        abs_knowledge_path = tmp_path / "abs_knowledge"

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
                    "--knowledge-path",
                    str(abs_knowledge_path),
                ],
            ),
        ):
            result = main()

        assert result == 0
        # Verify CSV was created in absolute knowledge path
        csv_path = abs_knowledge_path / "movements" / "movements.csv"
        assert csv_path.exists()

    def test_returns_one_for_source_outside_repo(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when source file is outside repository."""
        with patch.object(movement_tracker, "REPO_ROOT", Path("/fake/repo")):
            fs.create_dir("/fake/repo")
            # Create source outside repo
            fs.create_file("/outside/source.yml", contents="content")
            # Create target inside repo
            fs.create_file("/fake/repo/target.yml", contents="content")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "/outside/source.yml",
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
        assert "must be within repository" in captured.err

    def test_returns_one_for_target_outside_repo(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when target file is outside repository."""
        with patch.object(movement_tracker, "REPO_ROOT", Path("/fake/repo")):
            fs.create_dir("/fake/repo")
            # Create source inside repo
            fs.create_file("/fake/repo/source.yml", contents="content")
            # Create target outside repo
            fs.create_file("/outside/target.yml", contents="content")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--target-file",
                    "/outside/target.yml",
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
        assert "must be within repository" in captured.err


class TestRecordIterativeMovementMainRelativePath:
    def test_uses_relative_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should resolve relative knowledge path via REPO_ROOT."""
        args = MagicMock()
        # Use relative path - must patch REPO_ROOT to resolve correctly
        args.knowledge_path = Path(".knowledge")
        args.fact_id = "uuid-rel"
        args.before = "Relative path sentence"
        args.fact = "Relative fact"
        args.after = "Relative residual"
        args.reason = "Fact extraction"
        args.model = "test-model"
        args.pass_id = None
        args.span_id = None
        args.artifact_id = None

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        with (
            patch.object(movement_tracker, "REPO_ROOT", tmp_path),
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
        # Verify CSV was created in relative path resolved via REPO_ROOT
        csv_path = tmp_path / ".knowledge" / "movements" / "iterative_movements.csv"
        assert csv_path.exists()


class TestMainRecordIterativeEntryPoint:
    def test_parses_args_and_calls_main(self) -> None:
        """Should parse args and call record_iterative_movement_main."""
        from scripts.knowledge.movement_tracker import main_record_iterative

        with (
            patch("scripts.knowledge.movement_tracker.parse_record_iterative_args") as mock_parse,
            patch(
                "scripts.knowledge.movement_tracker.record_iterative_movement_main",
                return_value=0,
            ) as mock_main,
        ):
            mock_args = MagicMock()
            mock_parse.return_value = mock_args

            result = main_record_iterative()

            mock_parse.assert_called_once()
            mock_main.assert_called_once_with(mock_args)
            assert result == 0


class TestMainQueryIterativeEntryPoint:
    def test_parses_args_and_calls_main(self) -> None:
        """Should parse args and call query_iterative_movements_main."""
        from scripts.knowledge.movement_tracker import main_query_iterative

        with (
            patch("scripts.knowledge.movement_tracker.parse_query_iterative_args") as mock_parse,
            patch(
                "scripts.knowledge.movement_tracker.query_iterative_movements_main",
                return_value=0,
            ) as mock_main,
        ):
            mock_args = MagicMock()
            mock_parse.return_value = mock_args

            result = main_query_iterative()

            mock_parse.assert_called_once()
            mock_main.assert_called_once_with(mock_args)
            assert result == 0
