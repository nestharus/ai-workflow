"""Tests for scripts.knowledge.candidate_extraction module."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.knowledge.candidate_extraction import (
    CSV_COLUMNS,
    CandidateRecord,
    append_candidate,
    ensure_csv_exists,
    is_candidate_tracked,
    parse_args,
)


class TestCsvColumns:
    """Tests for CSV_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "candidate_id" in CSV_COLUMNS
        assert "term" in CSV_COLUMNS
        assert "source_file" in CSV_COLUMNS
        assert "source_element_id" in CSV_COLUMNS
        assert "extraction_method" in CSV_COLUMNS
        assert "pos_tags" in CSV_COLUMNS
        assert "confidence_score" in CSV_COLUMNS
        assert "extracted_at" in CSV_COLUMNS


class TestEnsureCsvExists:
    """Tests for ensure_csv_exists function."""

    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "keywords" / "candidates.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in CSV_COLUMNS:
            assert col in content

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Should not overwrite existing CSV with data."""
        csv_path = tmp_path / "keywords" / "candidates.csv"
        csv_path.parent.mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\nid1,term1,file1,elem1,method1,tags1,0.9,2024-01-01\n")

        ensure_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "id1" in content
        assert "term1" in content


class TestAppendCandidate:
    """Tests for append_candidate function."""

    def test_appends_record(self, tmp_path: Path) -> None:
        """Should append candidate record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "keywords").mkdir(parents=True)
        csv_path = tmp_path / "keywords" / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        record = CandidateRecord(
            candidate_id="cand-1",
            term="FastAPI",
            source_file="docs/test.yml",
            source_element_id="test.section",
            extraction_method="noun_phrase",
            pos_tags="NN",
            confidence_score="0.95",
            extracted_at="20240101T120000Z",
        )

        append_candidate(csv_path, record)

        content = csv_path.read_text()
        assert "cand-1" in content
        assert "FastAPI" in content


class TestIsCandidateTracked:
    """Tests for is_candidate_tracked function."""

    def test_returns_false_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        csv_path = tmp_path / "candidates.csv"
        result = is_candidate_tracked(csv_path, "term", "file.yml")
        assert result is False

    def test_returns_false_for_missing_candidate(self, tmp_path: Path) -> None:
        """Should return False when candidate not found."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\ncand-1,other,other.yml,elem,method,tags,0.9,2024-01-01\n")

        result = is_candidate_tracked(csv_path, "FastAPI", "docs/test.yml")
        assert result is False

    def test_returns_true_for_existing_candidate(self, tmp_path: Path) -> None:
        """Should return True when candidate exists."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\ncand-1,FastAPI,docs/test.yml,elem,method,tags,0.9,2024-01-01\n")

        result = is_candidate_tracked(csv_path, "FastAPI", "docs/test.yml")
        assert result is True


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.source == Path("docs")
        assert args.output is None
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_source(self) -> None:
        """Should parse --source argument."""
        args = parse_args(["--source", "custom/docs"])
        assert args.source == Path("custom/docs")

    def test_custom_output(self) -> None:
        """Should parse --output argument."""
        args = parse_args(["--output", "output.csv"])
        assert args.output == Path("output.csv")

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")
