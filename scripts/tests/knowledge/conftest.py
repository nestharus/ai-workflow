"""Shared fixtures and utilities for knowledge extraction tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Golden keywords that must be extracted from the test fixture.
# These terms MUST be captured by the extraction pipeline to ensure zero false negatives.
# NOTE: Only include terms that regex patterns can capture without NLP:
# - CamelCase identifiers (e.g., ElasticsearchWrapper, ConnectionManager)
# - snake_case identifiers (e.g., connection_pool_size)
# - File paths (e.g., app/infrastructure/db_connections.py)
# Multi-word phrases like "connection management" require spaCy NLP to extract.
GOLDEN_KEYWORDS = {
    "ElasticsearchWrapper",
    "ConnectionManager",
    "connection_pool_size",
    "app/infrastructure/db_connections.py",
    "scripts/knowledge/candidate_extraction.py",
}


@pytest.fixture
def golden_keywords() -> set[str]:
    """Return the set of golden keywords for validation.

    Returns:
        Set of keywords that must be extracted from the test fixture.
    """
    return GOLDEN_KEYWORDS.copy()


@pytest.fixture
def golden_keywords_fixture_path() -> Path:
    """Return the path to the golden keywords test fixture.

    Returns:
        Path to the golden_keywords_test.yml fixture file.
    """
    return Path(__file__).parent / "fixtures" / "golden_keywords_test.yml"


@pytest.fixture
def mock_qwen_reranker() -> MagicMock:
    """Create a mock Qwen reranker model for testing.

    Returns:
        Mock model that returns random scores between 0.5 and 1.0.
    """
    mock_model = MagicMock()
    mock_model.return_value = MagicMock()
    # Return random scores for testing
    mock_model.return_value.logits = MagicMock()
    mock_model.return_value.logits.item.return_value = 0.85
    return mock_model


@pytest.fixture
def mock_qwen_embedder() -> tuple[MagicMock, MagicMock]:
    """Create mock Qwen embedding model and tokenizer for testing.

    Returns:
        Tuple of (mock_model, mock_tokenizer) that return random embeddings.
    """
    import numpy as np

    mock_model = MagicMock()
    mock_tokenizer = MagicMock()

    # Mock tokenizer output
    mock_tokenizer.return_value = {
        "input_ids": MagicMock(),
        "attention_mask": MagicMock(),
    }

    # Mock model output with random embeddings
    mock_output = MagicMock()
    mock_output.last_hidden_state = MagicMock()
    # Return 768-dimensional embeddings (standard BERT size)
    mock_output.last_hidden_state.cpu.return_value.numpy.return_value = np.random.rand(2, 10, 768)
    mock_model.return_value = mock_output

    return mock_model, mock_tokenizer


def make_candidate_row(
    candidate_id: str,
    source_file: str,
    element_id: str,
    sentence: str,
    candidate_text: str,
    start_char: str = "0",
    end_char: str = "10",
    detected_at: str = "2024-01-01T00:00:00Z",
    keep: str = "",
    confidence: str = "",
    reason: str = "",
    classified_at: str = "",
    qwen_score: str = "",
    projection_version: str = "fieldfacts.v2",
    source_field_path: str = "",
    source_scope_path: str = "",
    field_role: str = "",
    artifact_kind: str = "",
) -> str:
    """Create a CSV row for the candidates table.

    Args:
        candidate_id: UUID of the candidate.
        source_file: Path to source YAML file.
        element_id: YAML element ID.
        sentence: Source sentence containing the candidate.
        candidate_text: The extracted keyword candidate.
        start_char: Start character offset (default: "0").
        end_char: End character offset (default: "10").
        detected_at: Detection timestamp (default: "2024-01-01T00:00:00Z").
        keep: Classification decision (default: "").
        confidence: Confidence score (default: "").
        reason: Classification reason (default: "").
        classified_at: Classification timestamp (default: "").
        qwen_score: Qwen relevance score (default: "").
        projection_version: Text projection version (default: "fieldfacts.v2").
        source_field_path: FieldFact.field_path (default: "").
        source_scope_path: FieldFact.scope_path (default: "").
        field_role: FieldFact.role (default: "").
        artifact_kind: FieldFact.artifact_kind (default: "").

    Returns:
        CSV row string matching the candidates schema.
    """
    return ",".join(
        [
            candidate_id,
            source_file,
            element_id,
            sentence,
            candidate_text,
            start_char,
            end_char,
            detected_at,
            keep,
            confidence,
            reason,
            classified_at,
            qwen_score,
            projection_version,
            source_field_path,
            source_scope_path,
            field_role,
            artifact_kind,
        ]
    )
