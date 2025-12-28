import argparse
from pathlib import Path

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


class TestRunClassifyStage:
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


class TestExtractionPipelineMain:
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
