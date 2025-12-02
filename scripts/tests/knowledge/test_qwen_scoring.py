"""Tests for scripts.knowledge.qwen_scoring module."""

from __future__ import annotations

from pathlib import Path

from scripts.knowledge.candidate_extraction import CSV_COLUMNS
from scripts.knowledge.qwen_scoring import (
    get_unscored_candidates,
    parse_args,
    update_candidate_scores_batch,
)


def _make_csv_row(
    candidate_id: str,
    source_file: str,
    element_id: str,
    sentence: str,
    candidate_text: str,
    start_char: str,
    end_char: str,
    detected_at: str,
    keep: str = "",
    confidence: str = "",
    reason: str = "",
    classified_at: str = "",
    qwen_score: str = "",
) -> str:
    """Helper to create a CSV row matching the new schema."""
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


class TestGetUnscoredCandidates:
    """Tests for get_unscored_candidates function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty list when CSV doesn't exist."""
        csv_path = tmp_path / "candidates.csv"
        result = get_unscored_candidates(csv_path)
        assert result == []

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV."""
        csv_path = tmp_path / "candidates.csv"
        csv_path.write_text("")
        result = get_unscored_candidates(csv_path)
        assert result == []

    def test_returns_unscored_candidates(self, tmp_path: Path) -> None:
        """Should return candidates with empty qwen_score."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row1 = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "sent1",
            "FastAPI",
            "0",
            "7",
            "2024-01-01",
            "",
            "",
            "",
            "",
            "",
        )
        row2 = _make_csv_row(
            "cand-2",
            "docs/test.yml",
            "elem2",
            "sent2",
            "Pydantic",
            "0",
            "8",
            "2024-01-01",
            "",
            "",
            "",
            "",
            "0.9",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = get_unscored_candidates(csv_path)
        assert len(result) == 1
        assert result[0]["candidate_text"] == "FastAPI"

    def test_returns_empty_when_all_scored(self, tmp_path: Path) -> None:
        """Should return empty list when all candidates have qwen_score."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row1 = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "sent1",
            "FastAPI",
            "0",
            "7",
            "2024-01-01",
            "",
            "",
            "",
            "",
            "0.95",
        )
        row2 = _make_csv_row(
            "cand-2",
            "docs/test.yml",
            "elem2",
            "sent2",
            "Pydantic",
            "0",
            "8",
            "2024-01-01",
            "",
            "",
            "",
            "",
            "0.9",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = get_unscored_candidates(csv_path)
        assert result == []


class TestUpdateCandidateScoresBatch:
    """Tests for update_candidate_scores_batch function."""

    def test_returns_false_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        csv_path = tmp_path / "candidates.csv"
        result = update_candidate_scores_batch(csv_path, {"cand-1": 0.95})
        assert result is False

    def test_returns_false_for_empty_scores(self, tmp_path: Path) -> None:
        """Should return False when scores dict is empty."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")
        result = update_candidate_scores_batch(csv_path, {})
        assert result is False

    def test_updates_qwen_scores_batch(self, tmp_path: Path) -> None:
        """Should update multiple candidate qwen_scores in CSV."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row1 = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "sent1",
            "FastAPI",
            "0",
            "7",
            "2024-01-01",
            "",
            "",
            "",
            "",
            "",
        )
        row2 = _make_csv_row(
            "cand-2",
            "docs/test.yml",
            "elem2",
            "sent2",
            "Pydantic",
            "0",
            "8",
            "2024-01-01",
            "",
            "",
            "",
            "",
            "",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = update_candidate_scores_batch(csv_path, {"cand-1": 0.95, "cand-2": 0.87})
        assert result is True

        content = csv_path.read_text()
        assert "0.95" in content
        assert "0.87" in content


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.model == "Qwen/Qwen3-Reranker-8B"
        assert args.batch_size == 32
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_model(self) -> None:
        """Should parse --model argument."""
        args = parse_args(["--model", "Qwen/Qwen3-Reranker-4B"])
        assert args.model == "Qwen/Qwen3-Reranker-4B"

    def test_custom_batch_size(self) -> None:
        """Should parse --batch-size argument."""
        args = parse_args(["--batch-size", "64"])
        assert args.batch_size == 64

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")
