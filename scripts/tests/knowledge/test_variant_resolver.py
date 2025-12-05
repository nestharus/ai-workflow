"""Tests for scripts.knowledge.variant_resolver module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from scripts.knowledge.variant_resolver import (
    VARIANT_COLUMNS,
    VariantRecord,
    append_variant,
    apply_variant_decisions,
    apply_variants_to_yaml_file,
    compute_cosine_similarity,
    ensure_variants_csv_exists,
    get_yaml_files_with_keywords,
    is_variant_tracked,
    load_existing_pairs,
    parse_apply_args,
    parse_args,
)


class TestVariantColumns:
    """Tests for VARIANT_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns for pair-based schema."""
        assert "pair_id" in VARIANT_COLUMNS
        assert "keyword_a" in VARIANT_COLUMNS
        assert "keyword_b" in VARIANT_COLUMNS
        assert "similarity" in VARIANT_COLUMNS
        assert "merge" in VARIANT_COLUMNS
        assert "canonical" in VARIANT_COLUMNS
        assert "reason" in VARIANT_COLUMNS
        assert "validated" in VARIANT_COLUMNS

    def test_column_count(self) -> None:
        """Should have exactly 8 columns."""
        assert len(VARIANT_COLUMNS) == 8


class TestEnsureVariantsCsvExists:
    """Tests for ensure_variants_csv_exists function."""

    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "keywords" / "variant_candidates.csv"

        ensure_variants_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in VARIANT_COLUMNS:
            assert col in content

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Should not overwrite existing CSV with data."""
        csv_path = tmp_path / "keywords" / "variant_candidates.csv"
        csv_path.parent.mkdir(parents=True)
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,term_a,term_b,0.9,true,term_a,reason,true\n")

        ensure_variants_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "pair-1" in content
        assert "term_a" in content


class TestAppendVariant:
    """Tests for append_variant function."""

    def test_appends_record(self, tmp_path: Path) -> None:
        """Should append variant record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "keywords").mkdir(parents=True)
        csv_path = tmp_path / "keywords" / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\n")

        record = VariantRecord(
            pair_id="pair-1",
            keyword_a="connection management",
            keyword_b="connection manager",
            similarity="0.92",
            merge="",
            canonical="",
            reason="",
            validated="",
        )

        append_variant(csv_path, record)

        content = csv_path.read_text()
        assert "pair-1" in content
        assert "connection management" in content
        assert "connection manager" in content


class TestIsVariantTracked:
    """Tests for is_variant_tracked function."""

    def test_returns_false_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        csv_path = tmp_path / "variant_candidates.csv"
        result = is_variant_tracked(csv_path, "term_a", "term_b")
        assert result is False

    def test_returns_false_for_missing_variant(self, tmp_path: Path) -> None:
        """Should return False when variant pair not found."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,other_a,other_b,0.9,,,, \n")

        result = is_variant_tracked(csv_path, "term_a", "term_b")
        assert result is False

    def test_returns_true_for_existing_variant(self, tmp_path: Path) -> None:
        """Should return True when variant pair exists."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,term_a,term_b,0.9,,,,\n")

        result = is_variant_tracked(csv_path, "term_a", "term_b")
        assert result is True

    def test_returns_true_for_reversed_order(self, tmp_path: Path) -> None:
        """Should return True when pair exists in reversed order."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,term_b,term_a,0.9,,,,\n")

        result = is_variant_tracked(csv_path, "term_a", "term_b")
        assert result is True


class TestLoadExistingPairs:
    """Tests for load_existing_pairs function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty set when CSV doesn't exist."""
        csv_path = tmp_path / "variant_candidates.csv"
        result = load_existing_pairs(csv_path)
        assert result == set()

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty set for empty CSV."""
        csv_path = tmp_path / "variant_candidates.csv"
        csv_path.write_text("")
        result = load_existing_pairs(csv_path)
        assert result == set()

    def test_loads_pairs_as_frozensets(self, tmp_path: Path) -> None:
        """Should load pairs as frozensets for order-independent lookup."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\npair-1,term_a,term_b,0.9,,,,\npair-2,term_c,term_d,0.85,,,,\n"
        )

        result = load_existing_pairs(csv_path)

        assert len(result) == 2
        assert frozenset(["term_a", "term_b"]) in result
        assert frozenset(["term_c", "term_d"]) in result
        # Order-independent lookup
        assert frozenset(["term_b", "term_a"]) in result


class TestComputeCosineSimilarity:
    """Tests for compute_cosine_similarity function."""

    def test_identical_vectors_have_similarity_one(self) -> None:
        """Should return 1.0 for identical vectors."""
        embeddings = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        result = compute_cosine_similarity(embeddings)
        assert result[0, 1] > 0.99
        assert result[1, 0] > 0.99

    def test_orthogonal_vectors_have_similarity_zero(self) -> None:
        """Should return 0.0 for orthogonal vectors."""
        embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
        result = compute_cosine_similarity(embeddings)
        assert abs(result[0, 1]) < 0.01
        assert abs(result[1, 0]) < 0.01

    def test_diagonal_is_one(self) -> None:
        """Should return 1.0 on diagonal (self-similarity)."""
        embeddings = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        result = compute_cosine_similarity(embeddings)
        assert result[0, 0] > 0.99
        assert result[1, 1] > 0.99


class TestApplyVariantDecisions:
    """Tests for apply_variant_decisions function."""

    def test_returns_empty_for_missing_variants_csv(self, tmp_path: Path) -> None:
        """Should return empty dict when variants CSV doesn't exist."""
        keywords_csv = tmp_path / "keywords.csv"
        variants_csv = tmp_path / "variants.csv"
        keywords_csv.write_text("keyword\nterm_a\nterm_b\n")

        result = apply_variant_decisions(keywords_csv, variants_csv)
        assert result == {}

    def test_returns_empty_when_no_validated_merges(self, tmp_path: Path) -> None:
        """Should return empty dict when no validated merges exist."""
        keywords_csv = tmp_path / "keywords.csv"
        variants_csv = tmp_path / "variants.csv"
        keywords_csv.write_text("keyword\nterm_a\nterm_b\n")
        header = ",".join(VARIANT_COLUMNS)
        variants_csv.write_text(f"{header}\npair-1,term_a,term_b,0.9,false,,reason,true\n")

        result = apply_variant_decisions(keywords_csv, variants_csv)
        assert result == {}

    def test_builds_mapping_for_validated_merges(self, tmp_path: Path) -> None:
        """Should build mapping from validated merge decisions."""
        keywords_csv = tmp_path / "keywords.csv"
        variants_csv = tmp_path / "variants.csv"
        keywords_csv.write_text("keyword\nterm_a\nterm_b\n")
        header = ",".join(VARIANT_COLUMNS)
        variants_csv.write_text(f"{header}\npair-1,term_a,term_b,0.9,true,term_a,reason,true\n")

        result = apply_variant_decisions(keywords_csv, variants_csv, dry_run=True)
        assert result == {"term_b": "term_a"}

    def test_applies_changes_to_keywords_csv(self, tmp_path: Path) -> None:
        """Should update keywords.csv with canonical forms."""
        keywords_csv = tmp_path / "keywords.csv"
        variants_csv = tmp_path / "variants.csv"
        keywords_csv.write_text("keyword\nterm_a\nterm_b\nterm_c\n")
        header = ",".join(VARIANT_COLUMNS)
        variants_csv.write_text(f"{header}\npair-1,term_a,term_b,0.9,true,term_a,reason,true\n")

        apply_variant_decisions(keywords_csv, variants_csv)

        content = keywords_csv.read_text()
        assert "term_a" in content
        assert content.count("term_a") >= 2
        assert "term_c" in content


class TestApplyVariantsToYamlFile:
    """Tests for apply_variants_to_yaml_file function."""

    def test_replaces_keywords_in_yaml(self, tmp_path: Path) -> None:
        """Should replace old keywords with canonical forms."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("""
id: test-element
keywords:
  - term_a
  - term_b
  - term_c
""")
        mapping = {"term_b": "term_a"}

        replacements, _updates = apply_variants_to_yaml_file(yaml_file, mapping, dry_run=False)

        assert replacements == 1
        content = yaml_file.read_text()
        assert "term_a" in content
        assert "term_c" in content

    def test_dry_run_does_not_modify_file(self, tmp_path: Path) -> None:
        """Should not modify file in dry run mode."""
        yaml_file = tmp_path / "test.yml"
        original_content = """
id: test-element
keywords:
  - term_a
  - term_b
"""
        yaml_file.write_text(original_content)
        mapping = {"term_b": "term_a"}

        replacements, updates = apply_variants_to_yaml_file(yaml_file, mapping, dry_run=True)

        assert replacements == 1
        assert len(updates) == 1
        # File should be unchanged
        content = yaml_file.read_text()
        assert "term_b" in content

    def test_returns_zero_for_no_matches(self, tmp_path: Path) -> None:
        """Should return 0 replacements when no keywords match."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("""
id: test-element
keywords:
  - term_x
  - term_y
""")
        mapping = {"term_a": "canonical"}

        replacements, updates = apply_variants_to_yaml_file(yaml_file, mapping, dry_run=False)

        assert replacements == 0
        assert len(updates) == 0


class TestGetYamlFilesWithKeywords:
    """Tests for get_yaml_files_with_keywords function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty set when CSV doesn't exist."""
        csv_path = tmp_path / "keywords.csv"
        result = get_yaml_files_with_keywords(csv_path)
        assert result == set()

    def test_returns_distinct_source_files(self, tmp_path: Path) -> None:
        """Should return distinct source files from keywords.csv."""
        csv_path = tmp_path / "keywords.csv"
        csv_path.write_text(
            "keyword,source_file,element_id,snippet,first_detected,last_updated\n"
            "term_a,docs/file1.yml,elem-1,snippet,2024-01-01,2024-01-01\n"
            "term_b,docs/file1.yml,elem-2,snippet,2024-01-01,2024-01-01\n"
            "term_c,docs/file2.yml,elem-3,snippet,2024-01-01,2024-01-01\n"
        )

        result = get_yaml_files_with_keywords(csv_path)

        assert result == {"docs/file1.yml", "docs/file2.yml"}


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.threshold == 0.85
        assert args.model == "Qwen/Qwen3-Embedding-8B"
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_threshold(self) -> None:
        """Should parse --threshold argument."""
        args = parse_args(["--threshold", "0.9"])
        assert args.threshold == 0.9

    def test_similarity_threshold_alias(self) -> None:
        """Should parse --similarity-threshold as alias for --threshold."""
        args = parse_args(["--similarity-threshold", "0.92"])
        assert args.threshold == 0.92

    def test_custom_model(self) -> None:
        """Should parse --model argument."""
        args = parse_args(["--model", "custom/model"])
        assert args.model == "custom/model"

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")


class TestParseApplyArgs:
    """Tests for parse_apply_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_apply_args([])
        assert args.knowledge_path == Path(".knowledge")
        assert args.dry_run is False

    def test_dry_run_flag(self) -> None:
        """Should parse --dry-run flag."""
        args = parse_apply_args(["--dry-run"])
        assert args.dry_run is True

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_apply_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")


class TestEmbedKeywords:
    """Tests for embed_keywords function (with mocked model)."""

    def test_returns_correct_shape(self) -> None:
        """Should return embeddings with correct shape."""
        from scripts.knowledge.variant_resolver import embed_keywords

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_output = MagicMock()
        mock_output.last_hidden_state = MagicMock()
        mock_output.last_hidden_state.size.return_value = (2, 5, 768)

        import torch

        mock_output.last_hidden_state = torch.rand(2, 5, 768)
        mock_model.return_value = mock_output

        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5], [1, 2, 3, 0, 0]]),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1], [1, 1, 1, 0, 0]]),
        }

        keywords = ["term_a", "term_b"]
        result = embed_keywords(keywords, mock_model, mock_tokenizer)

        assert result.shape[0] == 2
        assert result.shape[1] == 768
