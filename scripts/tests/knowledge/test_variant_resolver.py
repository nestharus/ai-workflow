"""Tests for scripts.knowledge.variant_resolver module."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import numpy as np
import pytest

from scripts.knowledge.variant_resolver import (
    VARIANT_COLUMNS,
    VariantRecord,
    append_variant,
    apply_variant_decisions,
    apply_variant_decisions_main,
    apply_variant_decisions_to_yaml,
    apply_variants_to_yaml_file,
    compute_cosine_similarity,
    ensure_variants_csv_exists,
    get_yaml_files_with_keywords,
    is_variant_tracked,
    load_existing_pairs,
    main_apply,
    main_track,
    parse_apply_args,
    parse_args,
    track_variants_main,
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
        # Skip if torch is not available - avoid pytest.importorskip which segfaults on Python 3.14
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        from scripts.knowledge.variant_resolver import embed_keywords

        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        mock_output = MagicMock()
        mock_output.last_hidden_state = MagicMock()
        mock_output.last_hidden_state.size.return_value = (2, 5, 768)

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


class TestIsVariantTrackedErrorHandling:
    """Tests for is_variant_tracked error handling."""

    def test_returns_false_on_duckdb_error(self, tmp_path: Path) -> None:
        """Should return False when duckdb query fails."""
        csv_path = tmp_path / "variant_candidates.csv"
        # Create a file with invalid content to trigger duckdb error
        csv_path.write_text("invalid,csv,content\n")

        with patch("scripts.knowledge.variant_resolver.duckdb.execute") as mock_execute:
            mock_execute.side_effect = duckdb.Error("Query failed")
            result = is_variant_tracked(csv_path, "term_a", "term_b")

        assert result is False


class TestLoadExistingPairsErrorHandling:
    """Tests for load_existing_pairs error handling."""

    def test_returns_empty_on_duckdb_error(self, tmp_path: Path) -> None:
        """Should return empty set when duckdb query fails."""
        csv_path = tmp_path / "variant_candidates.csv"
        csv_path.write_text("invalid content\n")

        with patch("scripts.knowledge.variant_resolver.duckdb.execute") as mock_execute:
            mock_execute.side_effect = duckdb.Error("Query failed")
            result = load_existing_pairs(csv_path)

        assert result == set()


class TestGetYamlFilesWithKeywordsErrorHandling:
    """Tests for get_yaml_files_with_keywords error handling."""

    def test_returns_empty_on_duckdb_error(self, tmp_path: Path) -> None:
        """Should return empty set when duckdb query fails."""
        csv_path = tmp_path / "keywords.csv"
        csv_path.write_text("invalid content\n")

        with patch("scripts.knowledge.variant_resolver.duckdb.execute") as mock_execute:
            mock_execute.side_effect = duckdb.Error("Query failed")
            result = get_yaml_files_with_keywords(csv_path)

        assert result == set()


class TestApplyVariantDecisionsAdditional:
    """Additional tests for apply_variant_decisions function."""

    def test_handles_duckdb_error(self, tmp_path: Path) -> None:
        """Should return empty dict when duckdb query fails."""
        keywords_csv = tmp_path / "keywords.csv"
        variants_csv = tmp_path / "variants.csv"
        keywords_csv.write_text("keyword\nterm_a\n")
        variants_csv.write_text("invalid data\n")

        with patch("scripts.knowledge.variant_resolver.duckdb.execute") as mock_execute:
            mock_execute.side_effect = duckdb.Error("Query failed")
            result = apply_variant_decisions(keywords_csv, variants_csv)

        assert result == {}

    def test_maps_both_keywords_to_canonical(self, tmp_path: Path) -> None:
        """Should map both keyword_a and keyword_b to canonical when neither is canonical."""
        keywords_csv = tmp_path / "keywords.csv"
        variants_csv = tmp_path / "variants.csv"
        keywords_csv.write_text("keyword\nterm_a\nterm_b\n")
        header = ",".join(VARIANT_COLUMNS)
        # canonical is neither term_a nor term_b
        variants_csv.write_text(
            f"{header}\npair-1,term_a,term_b,0.9,true,preferred_term,reason,true\n"
        )

        result = apply_variant_decisions(keywords_csv, variants_csv, dry_run=True)

        assert result == {"term_a": "preferred_term", "term_b": "preferred_term"}

    def test_does_not_map_canonical_to_itself(self, tmp_path: Path) -> None:
        """Should not map canonical keyword to itself."""
        keywords_csv = tmp_path / "keywords.csv"
        variants_csv = tmp_path / "variants.csv"
        keywords_csv.write_text("keyword\nterm_a\nterm_b\n")
        header = ",".join(VARIANT_COLUMNS)
        # keyword_a is the canonical, so only term_b should be mapped
        variants_csv.write_text(f"{header}\npair-1,term_a,term_b,0.9,true,term_a,reason,true\n")

        result = apply_variant_decisions(keywords_csv, variants_csv, dry_run=True)

        # Only term_b should be in mapping, not term_a
        assert result == {"term_b": "term_a"}
        assert "term_a" not in result

    def test_skips_pairs_without_canonical(self, tmp_path: Path) -> None:
        """Should skip pairs where canonical is empty."""
        keywords_csv = tmp_path / "keywords.csv"
        variants_csv = tmp_path / "variants.csv"
        keywords_csv.write_text("keyword\nterm_a\nterm_b\n")
        header = ",".join(VARIANT_COLUMNS)
        # Empty canonical should be skipped
        variants_csv.write_text(f"{header}\npair-1,term_a,term_b,0.9,true,,reason,true\n")

        result = apply_variant_decisions(keywords_csv, variants_csv, dry_run=True)

        assert result == {}

    def test_returns_mapping_when_keywords_csv_missing(self, tmp_path: Path) -> None:
        """Should return mapping even when keywords.csv doesn't exist (for dry_run)."""
        keywords_csv = tmp_path / "keywords.csv"  # doesn't exist
        variants_csv = tmp_path / "variants.csv"
        header = ",".join(VARIANT_COLUMNS)
        variants_csv.write_text(f"{header}\npair-1,term_a,term_b,0.9,true,term_a,reason,true\n")

        # In dry_run mode, should just return mapping
        result = apply_variant_decisions(keywords_csv, variants_csv, dry_run=True)
        assert result == {"term_b": "term_a"}

        # In non-dry_run mode with missing keywords_csv, returns mapping without applying
        result = apply_variant_decisions(keywords_csv, variants_csv, dry_run=False)
        assert result == {"term_b": "term_a"}


class TestApplyVariantsToYamlFileErrorHandling:
    """Additional tests for apply_variants_to_yaml_file error handling."""

    def test_handles_invalid_yaml(self, tmp_path: Path) -> None:
        """Should handle invalid YAML file gracefully."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("invalid: yaml: content: [[[")
        mapping = {"term_a": "canonical"}

        replacements, updates = apply_variants_to_yaml_file(yaml_file, mapping, dry_run=False)

        assert replacements == 0
        assert updates == []

    def test_handles_missing_file(self, tmp_path: Path) -> None:
        """Should handle missing file gracefully."""
        yaml_file = tmp_path / "nonexistent.yml"
        mapping = {"term_a": "canonical"}

        replacements, updates = apply_variants_to_yaml_file(yaml_file, mapping, dry_run=False)

        assert replacements == 0
        assert updates == []

    def test_handles_write_error(self, tmp_path: Path) -> None:
        """Should handle write errors gracefully."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("""
id: test-element
keywords:
  - term_a
  - term_b
""")
        mapping = {"term_b": "term_a"}

        with patch.object(Path, "write_text") as mock_write:
            mock_write.side_effect = OSError("Cannot write")
            replacements, updates = apply_variants_to_yaml_file(yaml_file, mapping, dry_run=False)

        # Should return 0 because write failed
        assert replacements == 0
        assert updates == []

    def test_handles_nested_elements_without_keyword_list(self, tmp_path: Path) -> None:
        """Should handle elements where keywords is not a list."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("""
id: test-element
keywords: single_keyword_not_list
nested:
  id: nested-element
  keywords:
    - term_a
    - term_b
""")
        mapping = {"term_b": "term_a"}

        replacements, updates = apply_variants_to_yaml_file(yaml_file, mapping, dry_run=False)

        assert replacements == 1
        assert len(updates) == 1

    def test_processes_list_elements(self, tmp_path: Path) -> None:
        """Should process elements in a list structure."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("""
- id: item1
  keywords:
    - term_a
    - term_b
- id: item2
  keywords:
    - term_c
""")
        mapping = {"term_b": "term_a"}

        replacements, _updates = apply_variants_to_yaml_file(yaml_file, mapping, dry_run=False)

        assert replacements == 1


class TestApplyVariantDecisionsToYaml:
    """Tests for apply_variant_decisions_to_yaml function."""

    def test_returns_zero_when_no_source_files(self, tmp_path: Path) -> None:
        """Should return 0 when no source files found."""
        keywords_csv = tmp_path / "keywords.csv"
        keywords_csv.write_text("")  # Empty file
        mapping = {"term_a": "canonical"}

        result = apply_variant_decisions_to_yaml(keywords_csv, mapping, dry_run=False)

        assert result == 0

    def test_skips_nonexistent_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should skip source files that don't exist."""
        keywords_csv = tmp_path / "keywords.csv"
        keywords_csv.write_text("keyword,source_file\nterm_a,nonexistent/file.yml\n")
        mapping = {"term_a": "canonical"}

        # Patch REPO_ROOT to use tmp_path
        monkeypatch.setattr("scripts.knowledge.variant_resolver.REPO_ROOT", tmp_path)

        result = apply_variant_decisions_to_yaml(keywords_csv, mapping, dry_run=False)

        assert result == 0

    def test_applies_to_existing_yaml_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should apply variant mappings to existing YAML files."""
        # Create source file
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        yaml_file = docs_dir / "test.yml"
        yaml_file.write_text("""
id: test-element
keywords:
  - term_a
  - term_b
""")

        # Create keywords CSV referencing the file
        keywords_csv = tmp_path / "keywords.csv"
        keywords_csv.write_text("keyword,source_file\nterm_a,docs/test.yml\nterm_b,docs/test.yml\n")

        mapping = {"term_b": "term_a"}

        # Patch REPO_ROOT to use tmp_path
        monkeypatch.setattr("scripts.knowledge.variant_resolver.REPO_ROOT", tmp_path)

        result = apply_variant_decisions_to_yaml(keywords_csv, mapping, dry_run=False)

        assert result == 1

    def test_dry_run_does_not_modify(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should not modify files in dry run mode."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        yaml_file = docs_dir / "test.yml"
        original_content = """
id: test-element
keywords:
  - term_a
  - term_b
"""
        yaml_file.write_text(original_content)

        keywords_csv = tmp_path / "keywords.csv"
        keywords_csv.write_text("keyword,source_file\nterm_a,docs/test.yml\n")

        mapping = {"term_b": "term_a"}
        monkeypatch.setattr("scripts.knowledge.variant_resolver.REPO_ROOT", tmp_path)

        result = apply_variant_decisions_to_yaml(keywords_csv, mapping, dry_run=True)

        assert result == 1
        # File should be unchanged
        assert yaml_file.read_text() == original_content


class TestApplyVariantDecisionsMain:
    """Tests for apply_variant_decisions_main function."""

    def test_returns_error_when_keywords_csv_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when keywords.csv doesn't exist."""
        args = argparse.Namespace(knowledge_path=tmp_path, dry_run=False)
        (tmp_path / "keywords").mkdir(parents=True)
        # keywords.csv doesn't exist

        result = apply_variant_decisions_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Keywords CSV not found" in captured.err

    def test_returns_error_when_variants_csv_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when variants.csv doesn't exist."""
        args = argparse.Namespace(knowledge_path=tmp_path, dry_run=False)
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\nterm_a\n")
        # variants.csv doesn't exist

        result = apply_variant_decisions_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Variants CSV not found" in captured.err

    def test_returns_zero_when_no_merges(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 0 when no validated merge decisions exist."""
        args = argparse.Namespace(knowledge_path=tmp_path, dry_run=False)
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\nterm_a\n")
        header = ",".join(VARIANT_COLUMNS)
        (keywords_dir / "variant_candidates.csv").write_text(f"{header}\n")

        result = apply_variant_decisions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No validated merge decisions" in captured.out

    def test_applies_changes_successfully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Should apply changes and return 0."""
        args = argparse.Namespace(knowledge_path=tmp_path, dry_run=False)
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\nterm_a\nterm_b\n")
        header = ",".join(VARIANT_COLUMNS)
        (keywords_dir / "variant_candidates.csv").write_text(
            f"{header}\npair-1,term_a,term_b,0.9,true,term_a,reason,true\n"
        )

        monkeypatch.setattr("scripts.knowledge.variant_resolver.REPO_ROOT", tmp_path)

        result = apply_variant_decisions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Applied" in captured.out or "replacement" in captured.out

    def test_dry_run_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Should report changes without applying in dry run mode."""
        args = argparse.Namespace(knowledge_path=tmp_path, dry_run=True)
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\nterm_a\nterm_b\n")
        header = ",".join(VARIANT_COLUMNS)
        (keywords_dir / "variant_candidates.csv").write_text(
            f"{header}\npair-1,term_a,term_b,0.9,true,term_a,reason,true\n"
        )

        monkeypatch.setattr("scripts.knowledge.variant_resolver.REPO_ROOT", tmp_path)

        result = apply_variant_decisions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "dry run" in captured.out.lower()
        assert "Dry run - changes that would be applied" in captured.out

    def test_with_absolute_path(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Should handle absolute knowledge path correctly."""
        args = argparse.Namespace(knowledge_path=tmp_path.resolve(), dry_run=False)
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\nterm_a\n")
        header = ",".join(VARIANT_COLUMNS)
        (keywords_dir / "variant_candidates.csv").write_text(f"{header}\n")

        result = apply_variant_decisions_main(args)

        assert result == 0

    def test_reports_yaml_replacements(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Should report YAML file replacements made."""
        args = argparse.Namespace(knowledge_path=tmp_path, dry_run=False)
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)

        # Create a docs directory with a YAML file
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        yaml_file = docs_dir / "test.yml"
        yaml_file.write_text("""
id: test-element
keywords:
  - term_a
  - term_b
""")

        (keywords_dir / "keywords.csv").write_text(
            "keyword,source_file\nterm_a,docs/test.yml\nterm_b,docs/test.yml\n"
        )
        header = ",".join(VARIANT_COLUMNS)
        (keywords_dir / "variant_candidates.csv").write_text(
            f"{header}\npair-1,term_a,term_b,0.9,true,term_a,reason,true\n"
        )

        monkeypatch.setattr("scripts.knowledge.variant_resolver.REPO_ROOT", tmp_path)

        result = apply_variant_decisions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "replacement(s) in YAML files" in captured.out

    def test_reports_no_yaml_replacements_needed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Should report when no YAML replacements are needed."""
        args = argparse.Namespace(knowledge_path=tmp_path, dry_run=False)
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\nterm_a\nterm_b\n")
        header = ",".join(VARIANT_COLUMNS)
        (keywords_dir / "variant_candidates.csv").write_text(
            f"{header}\npair-1,term_a,term_b,0.9,true,term_a,reason,true\n"
        )

        monkeypatch.setattr("scripts.knowledge.variant_resolver.REPO_ROOT", tmp_path)

        result = apply_variant_decisions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No YAML keyword replacements needed" in captured.out


class TestTrackVariantsMain:
    """Tests for track_variants_main function."""

    def test_returns_error_when_keywords_csv_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when keywords.csv doesn't exist."""
        args = argparse.Namespace(
            knowledge_path=tmp_path,
            model="test/model",
            threshold=0.85,
        )
        (tmp_path / "keywords").mkdir(parents=True)
        # keywords.csv doesn't exist

        result = track_variants_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Keywords CSV not found" in captured.err

    def test_returns_zero_when_no_keywords(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 0 when keywords.csv is empty."""
        args = argparse.Namespace(
            knowledge_path=tmp_path,
            model="test/model",
            threshold=0.85,
        )
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\n")  # Header only

        result = track_variants_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No keywords found" in captured.out

    def test_returns_error_on_duckdb_read_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when reading keywords fails."""
        args = argparse.Namespace(
            knowledge_path=tmp_path,
            model="test/model",
            threshold=0.85,
        )
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\nterm_a\n")

        with patch("scripts.knowledge.variant_resolver.duckdb.execute") as mock_execute:
            mock_execute.side_effect = duckdb.Error("Read failed")
            result = track_variants_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error reading keywords" in captured.err

    def test_returns_error_on_model_load_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when model loading fails."""
        args = argparse.Namespace(
            knowledge_path=tmp_path,
            model="nonexistent/model",
            threshold=0.85,
        )
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\nterm_a\nterm_b\n")

        with patch("scripts.knowledge.variant_resolver.load_qwen_embedding_model") as mock_load:
            mock_load.side_effect = Exception("Model not found")
            result = track_variants_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error loading model" in captured.err

    def test_with_absolute_path(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Should handle absolute knowledge path correctly."""
        args = argparse.Namespace(
            knowledge_path=tmp_path.resolve(),
            model="test/model",
            threshold=0.85,
        )
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\n")  # Header only

        result = track_variants_main(args)

        assert result == 0

    def test_full_workflow_with_mocked_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Should complete full workflow with mocked embedding model."""
        try:
            import torch
        except ImportError:
            pytest.skip("torch not installed")

        args = argparse.Namespace(
            knowledge_path=tmp_path,
            model="test/model",
            threshold=0.80,
        )
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir(parents=True)
        (keywords_dir / "keywords.csv").write_text("keyword\nterm_a\nterm_b\nterm_c\n")

        # Mock the model and tokenizer
        mock_model = MagicMock()
        mock_tokenizer = MagicMock()

        # Create mock embeddings - make term_a and term_b similar, term_c different
        mock_output = MagicMock()
        mock_output.last_hidden_state = torch.rand(3, 5, 768)
        mock_model.return_value = mock_output
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 5]] * 3),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 1]] * 3),
        }

        with patch("scripts.knowledge.variant_resolver.load_qwen_embedding_model") as mock_load:
            mock_load.return_value = (mock_model, mock_tokenizer)

            # Mock embeddings that would result in high similarity
            with patch("scripts.knowledge.variant_resolver.embed_keywords") as mock_embed:
                # Create embeddings where first two are similar
                embeddings = np.array([[1.0, 0.0, 0.0], [0.99, 0.1, 0.0], [0.0, 1.0, 0.0]])
                mock_embed.return_value = embeddings

                result = track_variants_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Found" in captured.out
        assert "similar pairs" in captured.out


class TestMainTrack:
    """Tests for main_track entry point."""

    def test_calls_track_variants_main(self) -> None:
        """Should parse args and call track_variants_main."""
        with (
            patch("scripts.knowledge.variant_resolver.parse_args") as mock_parse,
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_main,
        ):
            mock_parse.return_value = argparse.Namespace(
                knowledge_path=Path(".knowledge"),
                model="test/model",
                threshold=0.85,
            )
            mock_main.return_value = 0

            result = main_track()

            mock_parse.assert_called_once()
            mock_main.assert_called_once()
            assert result == 0


class TestMainApply:
    """Tests for main_apply entry point."""

    def test_calls_apply_variant_decisions_main(self) -> None:
        """Should parse args and call apply_variant_decisions_main."""
        with (
            patch("scripts.knowledge.variant_resolver.parse_apply_args") as mock_parse,
            patch("scripts.knowledge.variant_resolver.apply_variant_decisions_main") as mock_main,
        ):
            mock_parse.return_value = argparse.Namespace(
                knowledge_path=Path(".knowledge"),
                dry_run=False,
            )
            mock_main.return_value = 0

            result = main_apply()

            mock_parse.assert_called_once()
            mock_main.assert_called_once()
            assert result == 0
