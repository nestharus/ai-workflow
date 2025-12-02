"""Tests for scripts.knowledge.query_keyword_candidates module."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.knowledge.candidate_extraction import CSV_COLUMNS
from scripts.knowledge.query_keyword_candidates import (
    parse_args,
    query_candidates,
)


class TestQueryCandidates:
    """Tests for query_candidates function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty list when CSV doesn't exist."""
        csv_path = tmp_path / "candidates.csv"
        result = query_candidates(csv_path)
        assert result == []

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV."""
        csv_path = tmp_path / "candidates.csv"
        csv_path.write_text("")
        result = query_candidates(csv_path)
        assert result == []

    def test_returns_all_candidates(self, tmp_path: Path) -> None:
        """Should return all candidates when no filter applied."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "cand-1,FastAPI,docs/test.yml,elem1,noun_phrase,NN,0.9,2024-01-02\n"
            "cand-2,Pydantic,docs/test.yml,elem2,named_entity,NNP,0.8,2024-01-01\n"
        )

        result = query_candidates(csv_path)
        assert len(result) == 2

    def test_filters_by_method(self, tmp_path: Path) -> None:
        """Should filter by extraction method."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "cand-1,FastAPI,docs/test.yml,elem1,noun_phrase,NN,0.9,2024-01-01\n"
            "cand-2,Pydantic,docs/test.yml,elem2,named_entity,NNP,0.8,2024-01-01\n"
        )

        result = query_candidates(csv_path, method="noun_phrase")
        assert len(result) == 1
        assert result[0]["term"] == "FastAPI"

    def test_filters_by_source_prefix(self, tmp_path: Path) -> None:
        """Should filter by source file prefix."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "cand-1,FastAPI,docs/arch/test.yml,elem1,noun_phrase,NN,0.9,2024-01-01\n"
            "cand-2,Pydantic,docs/dev/test.yml,elem2,named_entity,NNP,0.8,2024-01-01\n"
        )

        result = query_candidates(csv_path, source_prefix="docs/arch")
        assert len(result) == 1
        assert result[0]["term"] == "FastAPI"

    def test_filters_by_min_confidence(self, tmp_path: Path) -> None:
        """Should filter by minimum confidence score."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "cand-1,FastAPI,docs/test.yml,elem1,noun_phrase,NN,0.95,2024-01-01\n"
            "cand-2,Pydantic,docs/test.yml,elem2,named_entity,NNP,0.7,2024-01-01\n"
        )

        result = query_candidates(csv_path, min_confidence=0.9)
        assert len(result) == 1
        assert result[0]["term"] == "FastAPI"

    def test_respects_limit(self, tmp_path: Path) -> None:
        """Should respect limit parameter."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "cand-1,FastAPI,docs/test.yml,elem1,noun_phrase,NN,0.9,2024-01-03\n"
            "cand-2,Pydantic,docs/test.yml,elem2,named_entity,NNP,0.8,2024-01-02\n"
            "cand-3,DuckDB,docs/test.yml,elem3,technical_term,NN,0.85,2024-01-01\n"
        )

        result = query_candidates(csv_path, limit=2)
        assert len(result) == 2


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.method is None
        assert args.source is None
        assert args.min_confidence is None
        assert args.limit is None
        assert args.knowledge_path == Path(".knowledge")

    def test_method_choices(self) -> None:
        """Should accept valid method choices."""
        args = parse_args(["--method", "noun_phrase"])
        assert args.method == "noun_phrase"

        args = parse_args(["--method", "named_entity"])
        assert args.method == "named_entity"

        args = parse_args(["--method", "technical_term"])
        assert args.method == "technical_term"

    def test_min_confidence(self) -> None:
        """Should parse --min-confidence as float."""
        args = parse_args(["--min-confidence", "0.85"])
        assert args.min_confidence == 0.85

    def test_limit(self) -> None:
        """Should parse --limit as int."""
        args = parse_args(["--limit", "10"])
        assert args.limit == 10

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")
