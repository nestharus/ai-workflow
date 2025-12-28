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


class TestIsVariantTrackedErrorHandling:
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
    def test_returns_empty_on_duckdb_error(self, tmp_path: Path) -> None:
        """Should return empty set when duckdb query fails."""
        csv_path = tmp_path / "variant_candidates.csv"
        csv_path.write_text("invalid content\n")

        with patch("scripts.knowledge.variant_resolver.duckdb.execute") as mock_execute:
            mock_execute.side_effect = duckdb.Error("Query failed")
            result = load_existing_pairs(csv_path)

        assert result == set()


class TestGetYamlFilesWithKeywordsErrorHandling:
    def test_returns_empty_on_duckdb_error(self, tmp_path: Path) -> None:
        """Should return empty set when duckdb query fails."""
        csv_path = tmp_path / "keywords.csv"
        csv_path.write_text("invalid content\n")

        with patch("scripts.knowledge.variant_resolver.duckdb.execute") as mock_execute:
            mock_execute.side_effect = duckdb.Error("Query failed")
            result = get_yaml_files_with_keywords(csv_path)

        assert result == set()


class TestApplyVariantDecisionsAdditional:
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


class TestApplyVariantDecisionsToYaml:
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
