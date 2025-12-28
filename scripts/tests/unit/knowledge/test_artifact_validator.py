from scripts.knowledge.artifact_validator import (
    ValidationResult,
    _compute_hash,
    _normalize_whitespace,
    _validate_exact_normalized,
    _validate_normalized_diff,
    _validate_normalized_rows_by_discriminator,
    _validate_normalized_text,
    _validate_structure_and_leaf_text,
    get_comparator_for_artifact_kind,
    load_validation_results,
    validate_artifact,
    write_validation_result,
)


class TestValidateNormalizedText:
    def test_similar_text_passes_with_mocked_embeddings(self) -> None:
        """Verify similar text passes with high similarity using mocked embeddings."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Mock embeddings with high similarity between similar texts
        mock_embeddings = np.array([[0.9, 0.1], [0.85, 0.15]])
        # Return 2x2 similarity matrix (symmetric, diagonal=1.0, off-diagonal=0.92)
        mock_similarity = np.array([[1.0, 0.92], [0.92, 1.0]])

        # Patch using the function import path (where from-import binds the name)
        # Since the import happens inside the function, we need to patch where it's defined
        with (
            patch(
                "scripts.knowledge.variant_resolver.load_qwen_embedding_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.knowledge.variant_resolver.embed_keywords", return_value=mock_embeddings
            ),
            patch(
                "scripts.knowledge.variant_resolver.compute_cosine_similarity",
                return_value=mock_similarity,
            ),
        ):
            similarity, passed, _mismatch = _validate_normalized_text(
                "The quick brown fox jumps.",
                "The quick brown fox jumped.",  # Similar but not identical
            )

            assert similarity == 0.92
            assert passed is True

    def test_embedding_based_similarity(self) -> None:
        """Verify embedding-based similarity is used when available."""
        from unittest.mock import MagicMock, patch

        import numpy as np

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Mock embeddings with high similarity
        mock_embeddings = np.array([[0.9, 0.1], [0.85, 0.15]])
        # Return 2x2 similarity matrix (symmetric, diagonal=1.0, off-diagonal=0.95)
        mock_similarity = np.array([[1.0, 0.95], [0.95, 1.0]])

        # Patch at the source module (variant_resolver) where the functions are defined
        with (
            patch(
                "scripts.knowledge.variant_resolver.load_qwen_embedding_model",
                return_value=(mock_model, mock_tokenizer),
            ),
            patch(
                "scripts.knowledge.variant_resolver.embed_keywords", return_value=mock_embeddings
            ),
            patch(
                "scripts.knowledge.variant_resolver.compute_cosine_similarity",
                return_value=mock_similarity,
            ),
        ):
            similarity, passed, _ = _validate_normalized_text(
                "Source text content", "Rendered text content"
            )

            assert similarity == 0.95
            assert passed is True

    def test_fallback_on_embedding_failure_different_text(self) -> None:
        """Verify fallback to character-level comparison when embeddings unavailable."""
        from unittest.mock import patch

        # Force ImportError to trigger fallback to character-set similarity
        # Patch at the source module (variant_resolver) where the functions are defined
        with patch(
            "scripts.knowledge.variant_resolver.load_qwen_embedding_model",
            side_effect=ImportError("No embeddings"),
        ):
            # Test with texts that share some characters but aren't identical
            similarity, passed, mismatch = _validate_normalized_text("abc def ghi", "abc xyz ghi")

            # Character-set (Jaccard) similarity: intersection / union
            # source chars: {a,b,c, ,d,e,f,g,h,i}
            # rendered chars: {a,b,c, ,x,y,z,g,h,i}
            # intersection: {a,b,c, ,g,h,i} = 7
            # union: {a,b,c, ,d,e,f,g,h,i,x,y,z} = 13
            # similarity = 7/13 ≈ 0.538
            assert 0.5 < similarity < 0.6
            assert passed is False
            assert "character fallback" in mismatch.lower()
