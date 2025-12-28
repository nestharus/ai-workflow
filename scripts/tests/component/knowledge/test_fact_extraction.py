from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.knowledge.fact_extraction import (
    CSV_COLUMNS,
    FactExtractorError,
    FactRecord,
    append_fact_batch,
    compute_pairwise_similarity,
    ensure_csv_exists,
    extract_facts_inline,
    extract_facts_main,
    get_existing_facts,
    invoke_fact_extractor,
    main,
    parse_args,
    validate_fact_extraction,
)


class TestCsvColumns:
    def test_has_required_core_columns(self) -> None:
        """Should have all required core columns."""
        assert "fact_id" in CSV_COLUMNS
        assert "source_sentence" in CSV_COLUMNS
        assert "entity" in CSV_COLUMNS
        assert "fact_text" in CSV_COLUMNS
        assert "rewritten_sentence" in CSV_COLUMNS
        assert "iteration" in CSV_COLUMNS
        assert "confidence" in CSV_COLUMNS
        assert "extracted_at" in CSV_COLUMNS

    def test_has_extended_provenance_columns(self) -> None:
        """Should have extended provenance columns for artifact-level extraction."""
        assert "source_file" in CSV_COLUMNS
        assert "source_element_id" in CSV_COLUMNS
        assert "artifact_id" in CSV_COLUMNS
        assert "span_id" in CSV_COLUMNS
        assert "pass_id" in CSV_COLUMNS
        assert "extraction_model" in CSV_COLUMNS


class TestEnsureCsvExists:
    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row."""
        csv_path = tmp_path / "facts" / "extractions.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in CSV_COLUMNS:
            assert col in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if they don't exist."""
        csv_path = tmp_path / "nested" / "path" / "extractions.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        assert csv_path.parent.exists()

    def test_does_not_overwrite_existing_with_data(self, tmp_path: Path) -> None:
        """Should not overwrite existing CSV with data."""
        csv_path = tmp_path / "facts" / "extractions.csv"
        csv_path.parent.mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(
            f"{header}\nfact-1,sentence,entity,fact,rewritten,1,0.9,2024-01-01,,,,,,,,,,,,\n"
        )

        ensure_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "fact-1" in content

    def test_recreates_empty_csv(self, tmp_path: Path) -> None:
        """Should create header for empty CSV file."""
        csv_path = tmp_path / "facts" / "extractions.csv"
        csv_path.parent.mkdir(parents=True)
        csv_path.write_text("")

        ensure_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "fact_id" in content


class TestAppendFactBatch:
    def test_appends_single_record(self, tmp_path: Path) -> None:
        """Should append a single fact record to CSV."""
        csv_path = tmp_path / "facts" / "extractions.csv"
        csv_path.parent.mkdir(parents=True)
        ensure_csv_exists(csv_path)

        record = FactRecord(
            fact_id="fact-123",
            source_sentence="Test sentence about create_app.",
            entity="create_app",
            fact_text="create_app is a function",
            rewritten_sentence="Test sentence.",
            iteration="1",
            confidence="0.95",
            extracted_at="2024-01-01T00:00:00Z",
            source_file="",
            source_element_id="",
            source_field_path="",
            artifact_id="legacy:sentence:abc123",
            span_id="legacy:sentence",
            pass_id="fact-123",
            entity_mention="create_app",
            entity_id="create_app",
            extraction_model="legacy",
            rewrite_model="legacy",
            state_hash_before="",
            state_hash_after="",
        )

        append_fact_batch(csv_path, [record])

        content = csv_path.read_text()
        assert "fact-123" in content
        assert "create_app" in content

    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        """Should append multiple fact records in batch."""
        csv_path = tmp_path / "facts" / "extractions.csv"
        csv_path.parent.mkdir(parents=True)
        ensure_csv_exists(csv_path)

        records = [
            FactRecord(
                fact_id=f"fact-{i}",
                source_sentence=f"Test sentence {i}.",
                entity="entity",
                fact_text=f"Fact {i}",
                rewritten_sentence=f"Rewritten {i}.",
                iteration=str(i),
                confidence="0.9",
                extracted_at="2024-01-01T00:00:00Z",
                source_file="",
                source_element_id="",
                source_field_path="",
                artifact_id="legacy:sentence:abc",
                span_id="legacy:sentence",
                pass_id=f"fact-{i}",
                entity_mention="entity",
                entity_id="entity",
                extraction_model="legacy",
                rewrite_model="legacy",
                state_hash_before="",
                state_hash_after="",
            )
            for i in range(1, 4)
        ]

        append_fact_batch(csv_path, records)

        content = csv_path.read_text()
        assert "fact-1" in content
        assert "fact-2" in content
        assert "fact-3" in content

    def test_returns_early_for_empty_records(self, tmp_path: Path) -> None:
        """Should return early when records list is empty."""
        csv_path = tmp_path / "facts" / "extractions.csv"
        csv_path.parent.mkdir(parents=True)
        ensure_csv_exists(csv_path)

        original_content = csv_path.read_text()

        # This should not raise and should return immediately
        append_fact_batch(csv_path, [])

        # File should be unchanged
        assert csv_path.read_text() == original_content

    def test_handles_old_schema_csv(self, tmp_path: Path) -> None:
        """Should handle CSV with old schema (fewer columns) and add missing columns."""
        csv_path = tmp_path / "facts" / "extractions.csv"
        csv_path.parent.mkdir(parents=True)

        # Create CSV with only core columns (old schema)
        old_columns = [
            "fact_id",
            "source_sentence",
            "entity",
            "fact_text",
            "rewritten_sentence",
            "iteration",
            "confidence",
            "extracted_at",
        ]
        header = ",".join(old_columns)
        csv_path.write_text(f"{header}\nold-fact,sentence,entity,fact,rewritten,1,0.9,2024-01-01\n")

        record = FactRecord(
            fact_id="new-fact",
            source_sentence="New sentence.",
            entity="entity",
            fact_text="New fact",
            rewritten_sentence="New rewritten.",
            iteration="1",
            confidence="0.95",
            extracted_at="2024-01-02T00:00:00Z",
            source_file="",
            source_element_id="",
            source_field_path="",
            artifact_id="legacy:sentence:def456",
            span_id="legacy:sentence",
            pass_id="new-fact",
            entity_mention="entity",
            entity_id="entity",
            extraction_model="legacy",
            rewrite_model="legacy",
            state_hash_before="",
            state_hash_after="",
        )

        append_fact_batch(csv_path, [record])

        content = csv_path.read_text()
        assert "old-fact" in content
        assert "new-fact" in content
        # New schema columns should be present
        assert "artifact_id" in content


class TestGetExistingFacts:
    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty list when CSV doesn't exist."""
        csv_path = tmp_path / "extractions.csv"
        result = get_existing_facts(csv_path, "entity")
        assert result == []

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV."""
        csv_path = tmp_path / "extractions.csv"
        csv_path.write_text("")
        result = get_existing_facts(csv_path, "entity")
        assert result == []

    def test_returns_facts_for_entity(self, tmp_path: Path) -> None:
        """Should return facts matching the entity."""
        csv_path = tmp_path / "extractions.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        ensure_csv_exists(csv_path)

        record = FactRecord(
            fact_id="fact-1",
            source_sentence="Test sentence.",
            entity="test_entity",
            fact_text="Test fact",
            rewritten_sentence="Rewritten.",
            iteration="1",
            confidence="0.9",
            extracted_at="2024-01-01T00:00:00Z",
            source_file="",
            source_element_id="",
            source_field_path="",
            artifact_id="legacy:sentence:abc",
            span_id="legacy:sentence",
            pass_id="fact-1",
            entity_mention="test_entity",
            entity_id="test_entity",
            extraction_model="legacy",
            rewrite_model="legacy",
            state_hash_before="",
            state_hash_after="",
        )
        append_fact_batch(csv_path, [record])

        result = get_existing_facts(csv_path, "test_entity")

        assert len(result) == 1
        assert result[0]["entity"] == "test_entity"
        assert result[0]["fact_text"] == "Test fact"

    def test_returns_empty_for_no_matching_entity(self, tmp_path: Path) -> None:
        """Should return empty list when no facts match the entity."""
        csv_path = tmp_path / "extractions.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        ensure_csv_exists(csv_path)

        record = FactRecord(
            fact_id="fact-1",
            source_sentence="Test sentence.",
            entity="other_entity",
            fact_text="Test fact",
            rewritten_sentence="Rewritten.",
            iteration="1",
            confidence="0.9",
            extracted_at="2024-01-01T00:00:00Z",
            source_file="",
            source_element_id="",
            source_field_path="",
            artifact_id="legacy:sentence:abc",
            span_id="legacy:sentence",
            pass_id="fact-1",
            entity_mention="other_entity",
            entity_id="other_entity",
            extraction_model="legacy",
            rewrite_model="legacy",
            state_hash_before="",
            state_hash_after="",
        )
        append_fact_batch(csv_path, [record])

        result = get_existing_facts(csv_path, "nonexistent_entity")
        assert result == []


class TestComputePairwiseSimilarity:
    def test_returns_zero_for_wrong_number_of_texts(self) -> None:
        """Should return 0.0 when texts list doesn't have exactly 2 items."""
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Single text
        result = compute_pairwise_similarity(["single"], mock_model, mock_tokenizer)
        assert result == 0.0

        # Three texts
        result = compute_pairwise_similarity(["a", "b", "c"], mock_model, mock_tokenizer)
        assert result == 0.0

    def test_computes_similarity_for_two_texts(self) -> None:
        """Should compute similarity between two texts using embeddings."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Mock tokenizer output
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5], [1, 2, 3, 4, 5]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1], [1, 1, 1, 1, 1]]),
        }

        # Mock model output with similar embeddings
        mock_output = MagicMock()
        # Create identical embeddings to get high similarity
        embedding = torch.ones(2, 5, 768)
        mock_output.last_hidden_state = embedding
        mock_model.return_value = mock_output

        result = compute_pairwise_similarity(["text1", "text2"], mock_model, mock_tokenizer)

        # Should return a float similarity score
        assert isinstance(result, float)
        # Allow small floating point error (cosine similarity can slightly exceed 1.0)
        assert -0.01 <= result <= 1.01


class TestValidateFactExtraction:
    def test_returns_similarity_and_preserved_flag(self) -> None:
        """Should return tuple of similarity score and information_preserved flag."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        # Create similar embeddings to simulate high similarity (>=0.95)
        embedding = torch.ones(2, 3, 768)
        mock_output.last_hidden_state = embedding
        mock_model.return_value = mock_output

        similarity, preserved = validate_fact_extraction(
            original="Original sentence about entity.",
            facts=["entity is something"],
            residual="Original sentence.",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert isinstance(similarity, float)
        assert isinstance(preserved, bool)
        # Allow small floating point error (cosine similarity can slightly exceed 1.0)
        assert -0.01 <= similarity <= 1.01

    def test_handles_empty_residual(self) -> None:
        """Should handle empty residual sentence."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        similarity, _preserved = validate_fact_extraction(
            original="Entity does something.",
            facts=["Entity does something"],
            residual="",  # Empty residual
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert isinstance(similarity, float)


class TestExtractFactsInline:
    def test_extracts_location_pattern(self) -> None:
        """Should extract facts using 'entity in path' pattern."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        result = extract_facts_inline(
            sentence="Use create_app in app/core/factory.py for initialization.",
            entity="create_app",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert "entity" in result
        assert result["entity"] == "create_app"
        assert "facts" in result
        assert "validation" in result

    def test_extracts_using_pattern(self) -> None:
        """Should extract facts using 'using entity' pattern."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        result = extract_facts_inline(
            sentence="Mount versioned endpoints using create_app.",
            entity="create_app",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert "entity" in result
        assert "original_sentence" in result
        assert "residual_sentence" in result

    def test_handles_entity_not_in_sentence(self) -> None:
        """Should handle case where entity is not in sentence."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        result = extract_facts_inline(
            sentence="This sentence has no matching entity.",
            entity="nonexistent_entity",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert result["extraction_complete"] is True
        assert len(result["facts"]) == 0

    def test_returns_extraction_complete_flag(self) -> None:
        """Should set extraction_complete flag based on entity absence."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        result = extract_facts_inline(
            sentence="Test sentence.",
            entity="missing",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert "extraction_complete" in result
        assert isinstance(result["extraction_complete"], bool)


class TestParseArgs:
    def test_requires_sentence_argument(self) -> None:
        """Should require --sentence argument."""
        with pytest.raises(SystemExit):
            parse_args(["--entity", "test"])

    def test_requires_entity_argument(self) -> None:
        """Should require --entity argument."""
        with pytest.raises(SystemExit):
            parse_args(["--sentence", "Test sentence."])

    def test_parses_required_arguments(self) -> None:
        """Should parse required arguments."""
        args = parse_args(["--sentence", "Test sentence.", "--entity", "test_entity"])
        assert args.sentence == "Test sentence."
        assert args.entity == "test_entity"

    def test_default_knowledge_path(self) -> None:
        """Should use default knowledge path."""
        args = parse_args(["--sentence", "Test.", "--entity", "test"])
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(
            [
                "--sentence",
                "Test.",
                "--entity",
                "test",
                "--knowledge-path",
                "custom/.knowledge",
            ]
        )
        assert args.knowledge_path == Path("custom/.knowledge")

    def test_dry_run_flag(self) -> None:
        """Should parse --dry-run flag."""
        args = parse_args(["--sentence", "Test.", "--entity", "test", "--dry-run"])
        assert args.dry_run is True

    def test_default_dry_run_false(self) -> None:
        """Should default dry_run to False."""
        args = parse_args(["--sentence", "Test.", "--entity", "test"])
        assert args.dry_run is False

    def test_custom_model(self) -> None:
        """Should parse --model argument."""
        args = parse_args(
            [
                "--sentence",
                "Test.",
                "--entity",
                "test",
                "--model",
                "Qwen/Qwen3-Embedding-8B",
            ]
        )
        assert args.model == "Qwen/Qwen3-Embedding-8B"

    def test_default_model(self) -> None:
        """Should use default model."""
        args = parse_args(["--sentence", "Test.", "--entity", "test"])
        assert args.model == "Qwen/Qwen3-Embedding-0.6B"


class TestExtractFactsInlineEdgeCases:
    def test_extracts_multiple_facts_iteratively(self) -> None:
        """Should extract multiple facts through iteration."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        # Sentence with entity mentioned multiple times in extractable patterns
        result = extract_facts_inline(
            sentence="Use create_app in app/core/factory.py, also using create_app for setup.",
            entity="create_app",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert "facts" in result
        assert "total_iterations" in result
        assert result["total_iterations"] >= 0

    def test_handles_punctuation_in_path_extraction(self) -> None:
        """Should handle punctuation when extracting path patterns."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        result = extract_facts_inline(
            sentence="The function create_app in app/core/factory.py, and then continue.",
            entity="create_app",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert "facts" in result
        assert "validation" in result
        assert "entity_absent" in result["validation"]

    def test_stops_at_max_iterations(self) -> None:
        """Should stop extraction at max iterations limit."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        # A sentence that would potentially loop forever without max iterations
        result = extract_facts_inline(
            sentence="entity entity entity entity entity entity entity entity entity entity entity",
            entity="entity",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        # Should complete without infinite loop
        assert "total_iterations" in result
        assert result["total_iterations"] <= 10

    def test_handles_using_pattern_with_trailing_text(self) -> None:
        """Should handle 'using entity' pattern with trailing text."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        result = extract_facts_inline(
            sentence="Initialize the app using create_app and configure it.",
            entity="create_app",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert "facts" in result
        assert "residual_sentence" in result

    def test_handles_sentence_with_neither_pattern(self) -> None:
        """Should handle sentence where entity exists but no extractable pattern matches."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        # Entity present but no "in path" or "using entity" pattern
        result = extract_facts_inline(
            sentence="The create_app function is important.",
            entity="create_app",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert "facts" in result
        # May or may not extract depending on patterns, but should not error
        assert "extraction_complete" in result

    def test_extracts_fact_ending_with_period(self) -> None:
        """Should properly handle sentences ending with period in path extraction."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3], [1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.ones(2, 3, 768)
        mock_model.return_value = mock_output

        result = extract_facts_inline(
            sentence="Use create_app in app/core/factory.py.",
            entity="create_app",
            model=mock_model,
            tokenizer=mock_tokenizer,
        )

        assert "facts" in result
        # Check rewritten sentence formatting
        if result["facts"]:
            for fact in result["facts"]:
                rewritten = fact.get("rewritten_sentence", "")
                # Should not have " ." at the end
                assert not rewritten.endswith(" .")


class TestGetExistingFactsEdgeCases:
    def test_handles_duckdb_error(self, tmp_path: Path) -> None:
        """Should return empty list on DuckDB error."""
        csv_path = tmp_path / "extractions.csv"
        # Create an invalid CSV that would cause DuckDB error
        csv_path.write_text("this,is,not,valid\nbroken,csv")

        result = get_existing_facts(csv_path, "entity")
        assert result == []
