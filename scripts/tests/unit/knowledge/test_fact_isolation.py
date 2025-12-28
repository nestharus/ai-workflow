from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestComputeSemanticSimilarity:
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


class TestMainFunction:
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
