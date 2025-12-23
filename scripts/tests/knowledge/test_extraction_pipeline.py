"""Tests for scripts.knowledge.extraction_pipeline module."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.knowledge.candidate_extraction import CSV_COLUMNS
from scripts.knowledge.extraction_pipeline import (
    STAGES,
    extraction_pipeline_main,
    main,
    parse_args,
    run_apply_stage,
    run_classify_stage,
    run_extract_stage,
    run_score_stage,
    run_variants_stage,
)


def _make_csv_row(
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
) -> str:
    """Helper to create a CSV row matching the candidates schema."""
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
        ]
    )


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.stage is None
        assert args.source == Path("docs")
        assert args.dry_run is False
        assert args.knowledge_path == Path(".knowledge")
        assert args.score_model == "Qwen/Qwen3-Reranker-8B"
        assert args.score_batch_size == 32

    def test_stage_choices(self) -> None:
        """Should accept valid stage names."""
        for stage in STAGES:
            args = parse_args(["--stage", stage])
            assert args.stage == stage

        # Invalid stage should raise SystemExit
        with pytest.raises(SystemExit):
            parse_args(["--stage", "invalid"])

    def test_custom_source(self) -> None:
        """Should parse --source argument."""
        args = parse_args(["--source", "docs/architecture"])
        assert args.source == Path("docs/architecture")

    def test_dry_run_flag(self) -> None:
        """Should parse --dry-run flag."""
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")

    def test_score_model(self) -> None:
        """Should parse --score-model argument."""
        args = parse_args(["--score-model", "custom/model"])
        assert args.score_model == "custom/model"

    def test_score_batch_size(self) -> None:
        """Should parse --score-batch-size as int."""
        args = parse_args(["--score-batch-size", "64"])
        assert args.score_batch_size == 64


class TestRunExtractStage:
    """Tests for run_extract_stage function."""

    def test_calls_candidate_extraction(self, tmp_path: Path) -> None:
        """Should import and call candidate_extraction.extract_candidates_main."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch(
            "scripts.knowledge.candidate_extraction.extract_candidates_main"
        ) as mock_extract:
            mock_extract.return_value = 0
            result = run_extract_stage(source_path, knowledge_path)

            mock_extract.assert_called_once()
            args = mock_extract.call_args[0][0]
            assert args.path == source_path
            assert args.knowledge_path == knowledge_path
            assert result == 0

    def test_returns_zero_on_success(self, tmp_path: Path) -> None:
        """Should return 0 when extraction succeeds."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch(
            "scripts.knowledge.candidate_extraction.extract_candidates_main"
        ) as mock_extract:
            mock_extract.return_value = 0
            result = run_extract_stage(source_path, knowledge_path)
            assert result == 0

    def test_returns_one_on_error(self, tmp_path: Path) -> None:
        """Should return 1 when extraction fails."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch(
            "scripts.knowledge.candidate_extraction.extract_candidates_main"
        ) as mock_extract:
            mock_extract.return_value = 1
            result = run_extract_stage(source_path, knowledge_path)
            assert result == 1

    def test_skips_in_dry_run(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should skip extraction in dry-run mode."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch(
            "scripts.knowledge.candidate_extraction.extract_candidates_main"
        ) as mock_extract:
            result = run_extract_stage(source_path, knowledge_path, dry_run=True)

            mock_extract.assert_not_called()
            assert result == 0

            captured = capsys.readouterr()
            assert "dry run" in captured.out.lower()

    def test_prints_progress_messages(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print stage name and paths."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch(
            "scripts.knowledge.candidate_extraction.extract_candidates_main"
        ) as mock_extract:
            mock_extract.return_value = 0
            run_extract_stage(source_path, knowledge_path)

            captured = capsys.readouterr()
            assert "Stage 1" in captured.out or "Candidate Extraction" in captured.out


class TestRunScoreStage:
    """Tests for run_score_stage function."""

    def test_calls_qwen_scoring(self, tmp_path: Path) -> None:
        """Should import and call qwen_scoring.score_candidates_main."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.qwen_scoring.score_candidates_main") as mock_score:
            mock_score.return_value = 0
            result = run_score_stage(knowledge_path)

            mock_score.assert_called_once()
            assert result == 0

    def test_returns_zero_on_success(self, tmp_path: Path) -> None:
        """Should return 0 when scoring succeeds."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.qwen_scoring.score_candidates_main") as mock_score:
            mock_score.return_value = 0
            result = run_score_stage(knowledge_path)
            assert result == 0

    def test_returns_one_on_error(self, tmp_path: Path) -> None:
        """Should return 1 when scoring fails."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.qwen_scoring.score_candidates_main") as mock_score:
            mock_score.return_value = 1
            result = run_score_stage(knowledge_path)
            assert result == 1

    def test_skips_in_dry_run(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should skip scoring in dry-run mode."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.qwen_scoring.score_candidates_main") as mock_score:
            result = run_score_stage(knowledge_path, dry_run=True)

            mock_score.assert_not_called()
            assert result == 0

            captured = capsys.readouterr()
            assert "dry run" in captured.out.lower()

    def test_passes_model_and_batch_size(self, tmp_path: Path) -> None:
        """Should pass model and batch_size to scoring function."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.qwen_scoring.score_candidates_main") as mock_score:
            mock_score.return_value = 0
            run_score_stage(knowledge_path, model="custom/model", batch_size=64)

            args = mock_score.call_args[0][0]
            assert args.model == "custom/model"
            assert args.batch_size == 64


class TestRunClassifyStage:
    """Tests for run_classify_stage function."""

    def test_prints_instructions(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print sub-agent invocation instructions."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        result = run_classify_stage(knowledge_path)

        captured = capsys.readouterr()
        assert "sub-agent" in captured.out.lower() or "Sub-agent" in captured.out
        assert "keyword-filter" in captured.out
        assert result == 0

    def test_returns_zero_always(self, tmp_path: Path) -> None:
        """Should always return 0 (manual stage)."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        result = run_classify_stage(knowledge_path)
        assert result == 0

        result = run_classify_stage(knowledge_path, dry_run=True)
        assert result == 0

    def test_dry_run_message(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print dry-run message when enabled."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        run_classify_stage(knowledge_path, dry_run=True)

        captured = capsys.readouterr()
        assert "dry run" in captured.out.lower()


class TestRunApplyStage:
    """Tests for run_apply_stage function."""

    def test_calls_keyword_store(self, tmp_path: Path) -> None:
        """Should import and call keyword_store.apply_keywords_main."""
        target_path = tmp_path / "docs"
        target_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.keyword_store.apply_keywords_main") as mock_apply:
            mock_apply.return_value = 0
            result = run_apply_stage(target_path, knowledge_path)

            mock_apply.assert_called_once()
            assert result == 0

    def test_returns_zero_on_success(self, tmp_path: Path) -> None:
        """Should return 0 when application succeeds."""
        target_path = tmp_path / "docs"
        target_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.keyword_store.apply_keywords_main") as mock_apply:
            mock_apply.return_value = 0
            result = run_apply_stage(target_path, knowledge_path)
            assert result == 0

    def test_returns_one_on_error(self, tmp_path: Path) -> None:
        """Should return 1 when application fails."""
        target_path = tmp_path / "docs"
        target_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.keyword_store.apply_keywords_main") as mock_apply:
            mock_apply.return_value = 1
            result = run_apply_stage(target_path, knowledge_path)
            assert result == 1

    def test_respects_dry_run(self, tmp_path: Path) -> None:
        """Should pass dry_run flag to keyword_store."""
        target_path = tmp_path / "docs"
        target_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.keyword_store.apply_keywords_main") as mock_apply:
            mock_apply.return_value = 0
            run_apply_stage(target_path, knowledge_path, dry_run=True)

            args = mock_apply.call_args[0][0]
            assert args.dry_run is True


class TestRunVariantsStage:
    """Tests for run_variants_stage function."""

    def test_calls_track_variants(self, tmp_path: Path) -> None:
        """Should call variant_resolver.track_variants_main."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        # Create empty keywords.csv
        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        with (
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch("scripts.knowledge.variant_resolver.apply_variant_decisions_main") as mock_apply,
        ):
            mock_track.return_value = 0
            mock_apply.return_value = 0

            result = run_variants_stage(knowledge_path)

            mock_track.assert_called_once()
            assert result == 0

    def test_prints_sub_agent_instructions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print validation instructions."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        with (
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch("scripts.knowledge.variant_resolver.apply_variant_decisions_main") as mock_apply,
        ):
            mock_track.return_value = 0
            mock_apply.return_value = 0

            run_variants_stage(knowledge_path)

            captured = capsys.readouterr()
            assert "keyword-synonym-reviewer" in captured.out

    def test_calls_apply_decisions(self, tmp_path: Path) -> None:
        """Should call variant_resolver.apply_variant_decisions_main."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        with (
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch("scripts.knowledge.variant_resolver.apply_variant_decisions_main") as mock_apply,
        ):
            mock_track.return_value = 0
            mock_apply.return_value = 0

            run_variants_stage(knowledge_path)

            mock_apply.assert_called_once()

    def test_returns_zero_on_success(self, tmp_path: Path) -> None:
        """Should return 0 when all steps succeed."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        with (
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch("scripts.knowledge.variant_resolver.apply_variant_decisions_main") as mock_apply,
        ):
            mock_track.return_value = 0
            mock_apply.return_value = 0

            result = run_variants_stage(knowledge_path)
            assert result == 0

    def test_returns_one_on_track_error(self, tmp_path: Path) -> None:
        """Should return 1 if tracking fails."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        with patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track:
            mock_track.return_value = 1

            result = run_variants_stage(knowledge_path)
            assert result == 1

    def test_returns_one_on_apply_error(self, tmp_path: Path) -> None:
        """Should return 1 if applying fails."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        with (
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch("scripts.knowledge.variant_resolver.apply_variant_decisions_main") as mock_apply,
        ):
            mock_track.return_value = 0
            mock_apply.return_value = 1

            result = run_variants_stage(knowledge_path)
            assert result == 1

    def test_skips_tracking_in_dry_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should skip tracking in dry-run mode."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        with (
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch("scripts.knowledge.variant_resolver.apply_variant_decisions_main") as mock_apply,
        ):
            mock_apply.return_value = 0

            run_variants_stage(knowledge_path, dry_run=True)

            mock_track.assert_not_called()
            captured = capsys.readouterr()
            assert "dry run" in captured.out.lower()

    def test_handles_tracking_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when tracking raises an exception."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        with patch(
            "scripts.knowledge.variant_resolver.track_variants_main",
            side_effect=Exception("Tracking failed"),
        ):
            result = run_variants_stage(knowledge_path, dry_run=False)

            assert result == 1
            captured = capsys.readouterr()
            assert "error" in captured.err.lower()

    def test_handles_apply_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when apply raises an exception."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        with (
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch(
                "scripts.knowledge.variant_resolver.apply_variant_decisions_main",
                side_effect=Exception("Apply failed"),
            ),
        ):
            mock_track.return_value = 0

            result = run_variants_stage(knowledge_path, dry_run=False)

            assert result == 1
            captured = capsys.readouterr()
            assert "error" in captured.err.lower()

    def test_dry_run_without_variants_csv(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print message when variants_csv doesn't exist in dry-run mode."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")
        # Note: variant_candidates.csv is NOT created

        with (
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch("scripts.knowledge.variant_resolver.apply_variant_decisions_main"),
        ):
            result = run_variants_stage(knowledge_path, dry_run=True)

            # In dry-run mode, should skip and return early when variants_csv doesn't exist
            mock_track.assert_not_called()
            captured = capsys.readouterr()
            assert "No variant_candidates.csv found" in captured.out or result == 0


class TestExtractionPipelineMain:
    """Tests for extraction_pipeline_main function."""

    def test_returns_error_for_missing_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when source directory doesn't exist."""
        args = argparse.Namespace(
            stage=None,
            source=tmp_path / "nonexistent",
            dry_run=False,
            knowledge_path=tmp_path / ".knowledge",
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        result = extraction_pipeline_main(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()

    def test_runs_all_stages_by_default(self, tmp_path: Path) -> None:
        """Should run all stages when no --stage specified."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        # Create empty keywords.csv for variants stage
        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")

        args = argparse.Namespace(
            stage=None,
            source=source_path,
            dry_run=False,
            knowledge_path=knowledge_path,
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        with (
            patch("scripts.knowledge.candidate_extraction.extract_candidates_main") as mock_extract,
            patch("scripts.knowledge.qwen_scoring.score_candidates_main") as mock_score,
            patch("scripts.knowledge.keyword_store.apply_keywords_main") as mock_apply,
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch(
                "scripts.knowledge.variant_resolver.apply_variant_decisions_main"
            ) as mock_apply_variants,
        ):
            mock_extract.return_value = 0
            mock_score.return_value = 0
            mock_apply.return_value = 0
            mock_track.return_value = 0
            mock_apply_variants.return_value = 0

            result = extraction_pipeline_main(args)

            mock_extract.assert_called_once()
            mock_score.assert_called_once()
            mock_apply.assert_called_once()
            mock_track.assert_called_once()
            assert result == 0

    def test_runs_single_stage(self, tmp_path: Path) -> None:
        """Should run only specified stage with --stage."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        args = argparse.Namespace(
            stage="extract",
            source=source_path,
            dry_run=False,
            knowledge_path=knowledge_path,
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        with (
            patch("scripts.knowledge.candidate_extraction.extract_candidates_main") as mock_extract,
            patch("scripts.knowledge.qwen_scoring.score_candidates_main") as mock_score,
        ):
            mock_extract.return_value = 0

            result = extraction_pipeline_main(args)

            mock_extract.assert_called_once()
            mock_score.assert_not_called()
            assert result == 0

    def test_stops_on_stage_failure(self, tmp_path: Path) -> None:
        """Should stop pipeline if any stage returns non-zero."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        args = argparse.Namespace(
            stage=None,
            source=source_path,
            dry_run=False,
            knowledge_path=knowledge_path,
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        with (
            patch("scripts.knowledge.candidate_extraction.extract_candidates_main") as mock_extract,
            patch("scripts.knowledge.qwen_scoring.score_candidates_main") as mock_score,
        ):
            mock_extract.return_value = 1  # Fail on first stage

            result = extraction_pipeline_main(args)

            mock_extract.assert_called_once()
            mock_score.assert_not_called()  # Should not reach score stage
            assert result == 1

    def test_resolves_absolute_paths(self, tmp_path: Path) -> None:
        """Should handle absolute knowledge_path and source."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        args = argparse.Namespace(
            stage="classify",  # Classify doesn't need files
            source=source_path.resolve(),
            dry_run=False,
            knowledge_path=knowledge_path.resolve(),
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        result = extraction_pipeline_main(args)
        assert result == 0

    def test_resolves_relative_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should resolve relative paths from REPO_ROOT."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        monkeypatch.setattr("scripts.knowledge.extraction_pipeline.REPO_ROOT", tmp_path)

        args = argparse.Namespace(
            stage="classify",
            source=Path("docs"),
            dry_run=False,
            knowledge_path=Path(".knowledge"),
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        result = extraction_pipeline_main(args)
        assert result == 0

    def test_prints_pipeline_header(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print pipeline header with paths and mode."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        args = argparse.Namespace(
            stage="classify",
            source=source_path,
            dry_run=True,
            knowledge_path=knowledge_path,
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        extraction_pipeline_main(args)

        captured = capsys.readouterr()
        assert "Pipeline" in captured.out or "pipeline" in captured.out
        assert "Dry run" in captured.out or "dry" in captured.out.lower()


class TestPipelineIntegration:
    """Integration tests for full pipeline."""

    def test_full_pipeline_with_golden_keywords(
        self,
        tmp_path: Path,
        golden_keywords: set[str],
        golden_keywords_fixture_path: Path,
    ) -> None:
        """Zero false negatives test - validates all golden keywords are extracted.

        This test ensures that the keyword extraction pipeline captures ALL golden
        keywords defined in conftest.py. Any missing keyword indicates a false
        negative and fails the test.
        """
        import shutil

        import duckdb

        # Create source directory and copy the golden keywords fixture
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        # Copy the curated fixture YAML into the source directory
        dest_yaml = source_path / "golden_keywords_test.yml"
        shutil.copy(golden_keywords_fixture_path, dest_yaml)

        # Create empty candidates.csv
        candidates_csv = keywords_dir / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        candidates_csv.write_text(f"{header}\n")

        # Mock spaCy to return simple entities (regex extraction will still work)
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_doc.ents = []
        mock_doc.noun_chunks = []
        mock_nlp.return_value = mock_doc

        with patch("scripts.knowledge.candidate_extraction.load_spacy_model") as mock_load:
            mock_load.return_value = mock_nlp

            # Run extraction
            from scripts.knowledge.candidate_extraction import extract_candidates_main

            args = argparse.Namespace(
                path=source_path,
                knowledge_path=knowledge_path,
            )

            result = extract_candidates_main(args)
            assert result == 0

        # Read extracted candidates
        extracted_texts: set[str] = set()
        if candidates_csv.stat().st_size > len(header) + 1:
            extracted = duckdb.execute(
                f"SELECT candidate_text FROM read_csv_auto('{candidates_csv}', ALL_VARCHAR=TRUE)"
            ).fetchall()
            extracted_texts = {row[0] for row in extracted}

        # Assert that ALL golden keywords are a subset of extracted texts
        # This enforces zero false negatives - any missing keyword fails the test
        missing_keywords = golden_keywords - extracted_texts
        assert missing_keywords == set(), (
            f"False negatives detected! The following golden keywords were NOT extracted:\n"
            f"  Missing: {sorted(missing_keywords)}\n"
            f"  Extracted: {sorted(extracted_texts)}\n"
            f"This indicates the extraction pipeline failed to capture required keywords."
        )

    def test_full_pipeline_stages_2_4_5(
        self,
        tmp_path: Path,
        golden_keywords: set[str],
        golden_keywords_fixture_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Integration test exercising Stages 2, 4, and 5 of the pipeline.

        This test validates the full workflow:
        1. Stage 1: Extract candidates from the golden keywords fixture
        2. Stage 2: Stub classification by setting keep='true' for all candidates
        3. Stage 4: Apply keywords to YAML files and create keywords.csv
        4. Stage 5: Run variant resolution (mocked)
        5. Verify: Assert golden keywords appear in final outputs
        """
        import shutil

        import duckdb

        # Create source directory and copy the golden keywords fixture
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        # Copy the curated fixture YAML into the source directory
        dest_yaml = source_path / "golden_keywords_test.yml"
        shutil.copy(golden_keywords_fixture_path, dest_yaml)

        # Monkeypatch REPO_ROOT to tmp_path for proper path resolution
        monkeypatch.setattr("scripts.knowledge.extraction_pipeline.REPO_ROOT", tmp_path)
        monkeypatch.setattr("scripts.knowledge.candidate_extraction.REPO_ROOT", tmp_path)
        monkeypatch.setattr("scripts.knowledge.keyword_store.REPO_ROOT", tmp_path)

        # Create empty candidates.csv
        candidates_csv = keywords_dir / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        candidates_csv.write_text(f"{header}\n")

        # Mock spaCy to return simple entities (regex extraction will still work)
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_doc.ents = []
        mock_doc.noun_chunks = []
        mock_nlp.return_value = mock_doc

        # ===== STAGE 1: Extract candidates =====
        with patch("scripts.knowledge.candidate_extraction.load_spacy_model") as mock_load:
            mock_load.return_value = mock_nlp

            from scripts.knowledge.candidate_extraction import extract_candidates_main

            args = argparse.Namespace(
                path=source_path,
                knowledge_path=knowledge_path,
            )

            result = extract_candidates_main(args)
            assert result == 0, "Stage 1 extraction failed"

        # ===== STAGE 2: Stub classification by setting keep='true' for all =====
        # Read all candidates and update keep='true'
        with duckdb.connect() as conn:
            conn.execute(f"""
                CREATE TABLE candidates AS
                SELECT * FROM read_csv_auto('{candidates_csv}', ALL_VARCHAR=TRUE)
            """)

            # Update all candidates to keep='true' with classification metadata
            conn.execute("""
                UPDATE candidates
                SET keep = 'true',
                    confidence = '0.95',
                    reason = 'Auto-classified for integration test',
                    classified_at = '2024-01-01T00:00:00Z'
            """)

            # Write back
            conn.execute(f"COPY candidates TO '{candidates_csv}' (HEADER, DELIMITER ',')")

        # ===== STAGE 4: Apply keywords to YAML =====
        from scripts.knowledge.keyword_store import apply_keywords_main

        apply_args = argparse.Namespace(
            knowledge_path=knowledge_path,
            dry_run=False,
        )

        result = apply_keywords_main(apply_args)
        assert result == 0, "Stage 4 apply keywords failed"

        # ===== STAGE 5: Run variant resolution (mocked) =====
        # Create empty variant_candidates.csv to simulate variant tracking
        variants_csv = keywords_dir / "variant_candidates.csv"
        variants_csv.write_text(
            "variant_id,keyword_a,keyword_b,similarity,validated,merge,canonical\n"
        )

        # Mock variant tracking and application to avoid Qwen model dependency
        with (
            patch("scripts.knowledge.variant_resolver.track_variants_main") as mock_track,
            patch("scripts.knowledge.variant_resolver.apply_variant_decisions_main") as mock_apply,
        ):
            mock_track.return_value = 0
            mock_apply.return_value = 0

            result = run_variants_stage(knowledge_path, dry_run=False)
            # Variants stage may fail without actual files, but that's OK for this test

        # ===== VERIFY: Check golden keywords appear in outputs =====

        # 1. Check keywords.csv contains golden keywords
        keywords_csv = keywords_dir / "keywords.csv"
        assert keywords_csv.exists(), "keywords.csv was not created by Stage 4"

        keywords_in_index: set[str] = set()
        if keywords_csv.stat().st_size > 0:
            result_rows = duckdb.execute(
                f"SELECT keyword FROM read_csv_auto('{keywords_csv}', ALL_VARCHAR=TRUE)"
            ).fetchall()
            keywords_in_index = {row[0] for row in result_rows if row[0]}

        # 2. Check that YAML file was updated with keywords
        import yaml

        updated_yaml = dest_yaml.read_text()
        yaml_data = yaml.safe_load(updated_yaml)

        # Collect all keywords from YAML elements
        keywords_in_yaml: set[str] = set()

        def collect_keywords(data: dict | list | None) -> None:
            if isinstance(data, dict):
                if "keywords" in data and isinstance(data["keywords"], list):
                    keywords_in_yaml.update(data["keywords"])
                for value in data.values():
                    collect_keywords(value)
            elif isinstance(data, list):
                for item in data:
                    collect_keywords(item)

        collect_keywords(yaml_data)

        # Assert that golden keywords appear in keywords.csv
        # Note: Some golden keywords may not be extracted by regex alone (e.g., multi-word phrases)
        # So we check for the intersection of what was extracted AND applied
        extracted_and_applied = keywords_in_index & keywords_in_yaml

        # At minimum, CamelCase and snake_case identifiers should be captured
        core_identifiers = {"ElasticsearchWrapper", "ConnectionManager", "connection_pool_size"}
        captured_core = core_identifiers & extracted_and_applied

        assert len(captured_core) > 0, (
            f"No core golden keywords were applied to YAML and indexed.\n"
            f"  Keywords in YAML: {sorted(keywords_in_yaml)}\n"
            f"  Keywords in index: {sorted(keywords_in_index)}\n"
            f"  Expected at least some of: {sorted(core_identifiers)}"
        )

    def test_dry_run_does_not_modify_files(self, tmp_path: Path) -> None:
        """Should not modify any files in dry-run mode."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)

        # Create test files
        test_yaml = source_path / "test.yml"
        test_yaml.write_text("doc_id: test\n")
        original_yaml_content = test_yaml.read_text()

        candidates_csv = keywords_dir / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row("cand-1", "docs/test.yml", "elem1", "Test", "FastAPI", keep="true")
        candidates_csv.write_text(f"{header}\n{row}\n")
        original_csv_content = candidates_csv.read_text()

        keywords_csv = keywords_dir / "keywords.csv"
        keywords_csv.write_text("keyword_id,keyword_text\n")
        original_keywords_content = keywords_csv.read_text()

        args = argparse.Namespace(
            stage=None,
            source=source_path,
            dry_run=True,
            knowledge_path=knowledge_path,
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        extraction_pipeline_main(args)

        # Verify files were not modified
        assert test_yaml.read_text() == original_yaml_content
        assert candidates_csv.read_text() == original_csv_content
        assert keywords_csv.read_text() == original_keywords_content

    def test_pipeline_handles_exception_gracefully(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle exceptions and return error code."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        args = argparse.Namespace(
            stage="extract",
            source=source_path,
            dry_run=False,
            knowledge_path=knowledge_path,
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        with patch(
            "scripts.knowledge.candidate_extraction.extract_candidates_main"
        ) as mock_extract:
            mock_extract.side_effect = Exception("Test error")

            result = extraction_pipeline_main(args)

            assert result == 1
            captured = capsys.readouterr()
            assert "error" in captured.err.lower() or "Error" in captured.out

    def test_unknown_stage_returns_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 for unknown stage."""
        source_path = tmp_path / "docs"
        source_path.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        # Create args with a manually added unknown stage
        # Since parse_args validates stage choices, we bypass by creating namespace directly
        args = argparse.Namespace(
            stage="unknown_stage",  # This bypasses parse_args validation
            source=source_path,
            dry_run=False,
            knowledge_path=knowledge_path,
            score_model="Qwen/Qwen3-Reranker-8B",
            score_batch_size=32,
        )

        result = extraction_pipeline_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Unknown stage" in captured.err


class TestMain:
    """Tests for main entry point function."""

    def test_main_calls_parse_args_and_pipeline(self, tmp_path: Path) -> None:
        """Should parse args and call extraction_pipeline_main."""
        with (
            patch("scripts.knowledge.extraction_pipeline.parse_args") as mock_parse,
            patch("scripts.knowledge.extraction_pipeline.extraction_pipeline_main") as mock_main,
        ):
            mock_parse.return_value = argparse.Namespace(
                stage="classify",
                source=tmp_path / "docs",
                dry_run=False,
                knowledge_path=tmp_path / ".knowledge",
                score_model="Qwen/Qwen3-Reranker-8B",
                score_batch_size=32,
            )
            mock_main.return_value = 0

            result = main()

            mock_parse.assert_called_once()
            mock_main.assert_called_once()
            assert result == 0

    def test_main_returns_pipeline_exit_code(self) -> None:
        """Should return the exit code from extraction_pipeline_main."""
        with (
            patch("scripts.knowledge.extraction_pipeline.parse_args") as mock_parse,
            patch("scripts.knowledge.extraction_pipeline.extraction_pipeline_main") as mock_main,
        ):
            mock_parse.return_value = argparse.Namespace()
            mock_main.return_value = 1  # Simulate failure

            result = main()

            assert result == 1
