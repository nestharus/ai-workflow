"""Tests for scripts.knowledge.query_keyword_candidates module."""

from __future__ import annotations

from pathlib import Path

from scripts.knowledge.candidate_extraction import CSV_COLUMNS
from scripts.knowledge.query_keyword_candidates import (
    parse_args,
    query_candidates,
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
        row1 = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "sent1",
            "FastAPI",
            "0",
            "7",
            "2024-01-02",
            "true",
            "0.9",
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
            "false",
            "0.8",
            "",
            "",
            "",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = query_candidates(csv_path)
        assert len(result) == 2

    def test_filters_by_keep(self, tmp_path: Path) -> None:
        """Should filter by keep status."""
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
            "true",
            "0.9",
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
            "false",
            "0.8",
            "",
            "",
            "",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = query_candidates(csv_path, keep="true")
        assert len(result) == 1
        assert result[0]["candidate_text"] == "FastAPI"

    def test_filters_by_source_prefix(self, tmp_path: Path) -> None:
        """Should filter by source file prefix."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row1 = _make_csv_row(
            "cand-1",
            "docs/arch/test.yml",
            "elem1",
            "sent1",
            "FastAPI",
            "0",
            "7",
            "2024-01-01",
            "",
            "0.9",
            "",
            "",
            "",
        )
        row2 = _make_csv_row(
            "cand-2",
            "docs/dev/test.yml",
            "elem2",
            "sent2",
            "Pydantic",
            "0",
            "8",
            "2024-01-01",
            "",
            "0.8",
            "",
            "",
            "",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = query_candidates(csv_path, source_prefix="docs/arch")
        assert len(result) == 1
        assert result[0]["candidate_text"] == "FastAPI"

    def test_filters_by_min_confidence(self, tmp_path: Path) -> None:
        """Should filter by minimum confidence score."""
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
            "0.95",
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
            "0.7",
            "",
            "",
            "",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = query_candidates(csv_path, min_confidence=0.9)
        assert len(result) == 1
        assert result[0]["candidate_text"] == "FastAPI"

    def test_filters_by_min_qwen_score(self, tmp_path: Path) -> None:
        """Should filter by minimum Qwen score."""
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
            "0.92",
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
            "0.6",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = query_candidates(csv_path, min_qwen_score=0.8)
        assert len(result) == 1
        assert result[0]["candidate_text"] == "FastAPI"

    def test_filters_unclassified(self, tmp_path: Path) -> None:
        """Should filter to only unclassified candidates."""
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
            "true",
            "0.9",
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

        result = query_candidates(csv_path, unclassified=True)
        assert len(result) == 1
        assert result[0]["candidate_text"] == "Pydantic"

    def test_respects_limit(self, tmp_path: Path) -> None:
        """Should respect limit parameter."""
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
            "2024-01-03",
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
            "2024-01-02",
            "",
            "",
            "",
            "",
            "",
        )
        row3 = _make_csv_row(
            "cand-3",
            "docs/test.yml",
            "elem3",
            "sent3",
            "DuckDB",
            "0",
            "6",
            "2024-01-01",
            "",
            "",
            "",
            "",
            "",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n{row3}\n")

        result = query_candidates(csv_path, limit=2)
        assert len(result) == 2


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.keep is None
        assert args.source is None
        assert args.min_confidence is None
        assert args.min_qwen_score is None
        assert args.unclassified is False
        assert args.limit is None
        assert args.knowledge_path == Path(".knowledge")

    def test_keep_choices(self) -> None:
        """Should accept valid keep choices."""
        args = parse_args(["--keep", "true"])
        assert args.keep == "true"

        args = parse_args(["--keep", "false"])
        assert args.keep == "false"

    def test_min_confidence(self) -> None:
        """Should parse --min-confidence as float."""
        args = parse_args(["--min-confidence", "0.85"])
        assert args.min_confidence == 0.85

    def test_min_qwen_score(self) -> None:
        """Should parse --min-qwen-score as float."""
        args = parse_args(["--min-qwen-score", "0.75"])
        assert args.min_qwen_score == 0.75

    def test_unclassified_flag(self) -> None:
        """Should parse --unclassified as boolean."""
        args = parse_args(["--unclassified"])
        assert args.unclassified is True

    def test_limit(self) -> None:
        """Should parse --limit as int."""
        args = parse_args(["--limit", "10"])
        assert args.limit == 10

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")
