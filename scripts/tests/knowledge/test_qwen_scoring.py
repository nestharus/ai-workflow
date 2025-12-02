"""Tests for scripts.knowledge.qwen_scoring module."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.knowledge.candidate_extraction import CSV_COLUMNS
from scripts.knowledge.qwen_scoring import (
    get_unscored_candidates,
    parse_args,
    update_candidate_score,
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
        """Should return candidates with empty confidence score."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "cand-1,FastAPI,docs/test.yml,elem1,noun_phrase,NN,,2024-01-01\n"
            "cand-2,Pydantic,docs/test.yml,elem2,named_entity,NNP,0.9,2024-01-01\n"
        )

        result = get_unscored_candidates(csv_path)
        assert len(result) == 1
        assert result[0]["term"] == "FastAPI"

    def test_returns_empty_when_all_scored(self, tmp_path: Path) -> None:
        """Should return empty list when all candidates are scored."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "cand-1,FastAPI,docs/test.yml,elem1,noun_phrase,NN,0.95,2024-01-01\n"
            "cand-2,Pydantic,docs/test.yml,elem2,named_entity,NNP,0.9,2024-01-01\n"
        )

        result = get_unscored_candidates(csv_path)
        assert result == []


class TestUpdateCandidateScore:
    """Tests for update_candidate_score function."""

    def test_returns_false_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        csv_path = tmp_path / "candidates.csv"
        result = update_candidate_score(csv_path, "cand-1", 0.95)
        assert result is False

    def test_updates_score(self, tmp_path: Path) -> None:
        """Should update candidate score in CSV."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "cand-1,FastAPI,docs/test.yml,elem1,noun_phrase,NN,,2024-01-01\n"
        )

        result = update_candidate_score(csv_path, "cand-1", 0.95)
        assert result is True

        content = csv_path.read_text()
        assert "0.95" in content


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.ids is None
        assert args.model == "Qwen/Qwen3-Embedding-0.6B"
        assert args.batch_size == 32
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_ids(self) -> None:
        """Should parse --ids argument with multiple values."""
        args = parse_args(["--ids", "cand-1", "cand-2"])
        assert args.ids == ["cand-1", "cand-2"]

    def test_custom_model(self) -> None:
        """Should parse --model argument."""
        args = parse_args(["--model", "custom/model"])
        assert args.model == "custom/model"

    def test_custom_batch_size(self) -> None:
        """Should parse --batch-size argument."""
        args = parse_args(["--batch-size", "64"])
        assert args.batch_size == 64

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")
