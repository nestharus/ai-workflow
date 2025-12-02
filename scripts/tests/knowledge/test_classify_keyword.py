"""Tests for scripts.knowledge.classify_keyword module."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.knowledge.candidate_extraction import CSV_COLUMNS
from scripts.knowledge.classify_keyword import (
    classify_keyword_main,
    get_candidate_text,
    parse_args,
    update_candidate_classification,
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


class TestUpdateCandidateClassification:
    """Tests for update_candidate_classification function."""

    def test_returns_false_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        csv_path = tmp_path / "candidates.csv"
        result = update_candidate_classification(
            csv_path,
            candidate_id="cand-123",
            keep="true",
            confidence="0.9",
            reason="Test reason",
        )
        assert result is False

    def test_returns_false_for_nonexistent_candidate(self, tmp_path: Path) -> None:
        """Should return False when candidate_id not found."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        result = update_candidate_classification(
            csv_path,
            candidate_id="nonexistent-id",
            keep="true",
            confidence="0.9",
            reason="Test reason",
        )
        assert result is False

    def test_updates_classification_fields(self, tmp_path: Path) -> None:
        """Should update keep, confidence, reason, classified_at fields."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        result = update_candidate_classification(
            csv_path,
            candidate_id="cand-1",
            keep="true",
            confidence="0.94",
            reason="Central concept",
        )
        assert result is True

        # Verify the CSV was updated
        content = csv_path.read_text()
        assert "true" in content
        assert "0.94" in content
        assert "Central concept" in content

    def test_preserves_other_fields(self, tmp_path: Path) -> None:
        """Should not modify other candidate fields during update."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
            start_char="5",
            end_char="12",
            detected_at="2024-06-15T10:30:00Z",
            qwen_score="0.85",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        result = update_candidate_classification(
            csv_path,
            candidate_id="cand-1",
            keep="true",
            confidence="0.9",
            reason="Test",
        )
        assert result is True

        # Verify original fields preserved
        content = csv_path.read_text()
        assert "docs/test.yml" in content
        assert "elem1" in content
        assert "Test sentence" in content
        assert "FastAPI" in content
        assert "0.85" in content  # qwen_score preserved

    def test_handles_multiple_candidates(self, tmp_path: Path) -> None:
        """Should only update the specified candidate."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row1 = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence 1",
            "FastAPI",
        )
        row2 = _make_csv_row(
            "cand-2",
            "docs/test.yml",
            "elem2",
            "Test sentence 2",
            "Pydantic",
        )
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = update_candidate_classification(
            csv_path,
            candidate_id="cand-1",
            keep="true",
            confidence="0.9",
            reason="Updated",
        )
        assert result is True

        # Read back and verify only cand-1 was updated
        import duckdb

        conn = duckdb.connect()
        df = conn.execute(f"SELECT * FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)").fetchall()
        conn.close()

        # Row 0 should have keep='true', row 1 should have keep='' or None
        for row in df:
            if row[0] == "cand-1":  # candidate_id is first column
                assert row[8] == "true"  # keep column
            elif row[0] == "cand-2":
                # DuckDB returns None for empty strings
                assert row[8] in ("", None)  # keep column should be empty

    def test_sets_classified_at_timestamp(self, tmp_path: Path) -> None:
        """Should set classified_at to current UTC timestamp."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        result = update_candidate_classification(
            csv_path,
            candidate_id="cand-1",
            keep="true",
            confidence="0.9",
            reason="Test",
        )
        assert result is True

        # Verify classified_at has a timestamp
        import duckdb

        conn = duckdb.connect()
        result_row = conn.execute(
            f"""
            SELECT classified_at FROM read_csv_auto('{csv_path}', ALL_VARCHAR=TRUE)
            WHERE candidate_id = 'cand-1'
            """
        ).fetchone()
        conn.close()

        assert result_row is not None
        classified_at = result_row[0]
        # Should be ISO format timestamp
        assert classified_at is not None
        assert "T" in classified_at or "-" in classified_at


class TestGetCandidateText:
    """Tests for get_candidate_text function."""

    def test_returns_none_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return None when CSV doesn't exist."""
        csv_path = tmp_path / "candidates.csv"
        result = get_candidate_text(csv_path, "cand-123")
        assert result is None

    def test_returns_none_for_nonexistent_candidate(self, tmp_path: Path) -> None:
        """Should return None when candidate not found."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        result = get_candidate_text(csv_path, "nonexistent-id")
        assert result is None

    def test_returns_candidate_text(self, tmp_path: Path) -> None:
        """Should return the candidate_text field for matching candidate."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence about FastAPI framework",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        result = get_candidate_text(csv_path, "cand-1")
        assert result == "FastAPI"

    def test_handles_empty_csv(self, tmp_path: Path) -> None:
        """Should return None for empty CSV file."""
        csv_path = tmp_path / "candidates.csv"
        csv_path.write_text("")

        result = get_candidate_text(csv_path, "cand-1")
        assert result is None


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_id(self) -> None:
        """Should require --id argument (raises SystemExit)."""
        with pytest.raises(SystemExit):
            parse_args(["--keep", "true", "--confidence", "0.9", "--reason", "Test"])

    def test_requires_keep(self) -> None:
        """Should require --keep argument."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "cand-1", "--confidence", "0.9", "--reason", "Test"])

    def test_requires_confidence(self) -> None:
        """Should require --confidence argument."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "cand-1", "--keep", "true", "--reason", "Test"])

    def test_requires_reason(self) -> None:
        """Should require --reason argument."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "cand-1", "--keep", "true", "--confidence", "0.9"])

    def test_keep_choices(self) -> None:
        """Should only accept 'true' or 'false' for --keep."""
        args = parse_args(
            ["--id", "cand-1", "--keep", "true", "--confidence", "0.9", "--reason", "Test"]
        )
        assert args.keep == "true"

        args = parse_args(
            ["--id", "cand-1", "--keep", "false", "--confidence", "0.9", "--reason", "Test"]
        )
        assert args.keep == "false"

        # Invalid choice should raise SystemExit
        with pytest.raises(SystemExit):
            parse_args(
                ["--id", "cand-1", "--keep", "maybe", "--confidence", "0.9", "--reason", "Test"]
            )

    def test_confidence_type(self) -> None:
        """Should parse --confidence as float."""
        args = parse_args(
            ["--id", "cand-1", "--keep", "true", "--confidence", "0.85", "--reason", "Test"]
        )
        assert args.confidence == 0.85
        assert isinstance(args.confidence, float)

    def test_default_knowledge_path(self) -> None:
        """Should default knowledge_path to Path('.knowledge')."""
        args = parse_args(
            ["--id", "cand-1", "--keep", "true", "--confidence", "0.9", "--reason", "Test"]
        )
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "true",
                "--confidence",
                "0.9",
                "--reason",
                "Test",
                "--knowledge-path",
                "custom/.knowledge",
            ]
        )
        assert args.knowledge_path == Path("custom/.knowledge")


class TestClassifyKeywordMain:
    """Tests for classify_keyword_main function."""

    def test_returns_error_for_missing_csv(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when candidates.csv doesn't exist."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir(parents=True)

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "true",
                "--confidence",
                "0.9",
                "--reason",
                "Test",
                "--knowledge-path",
                str(knowledge_path),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "Candidates CSV not found" in captured.err

    def test_returns_error_for_nonexistent_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when candidate not found."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--id",
                "nonexistent-id",
                "--keep",
                "true",
                "--confidence",
                "0.9",
                "--reason",
                "Test",
                "--knowledge-path",
                str(knowledge_path),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_error_for_invalid_confidence_high(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when confidence > 1.0."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "true",
                "--confidence",
                "1.5",
                "--reason",
                "Test",
                "--knowledge-path",
                str(knowledge_path),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "between 0.0 and 1.0" in captured.err

    def test_returns_error_for_invalid_confidence_low(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when confidence < 0.0."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "true",
                "--confidence",
                "-0.5",
                "--reason",
                "Test",
                "--knowledge-path",
                str(knowledge_path),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "between 0.0 and 1.0" in captured.err

    def test_returns_success_for_valid_classification(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and update CSV for valid input."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence about FastAPI",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "true",
                "--confidence",
                "0.94",
                "--reason",
                "Central concept in documentation",
                "--knowledge-path",
                str(knowledge_path),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 0

        # Verify CSV was updated
        content = csv_path.read_text()
        assert "true" in content
        assert "0.94" in content

    def test_prints_confirmation_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print candidate details after successful classification."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "true",
                "--confidence",
                "0.9",
                "--reason",
                "Important term",
                "--knowledge-path",
                str(knowledge_path),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Classified candidate: cand-1" in captured.out
        assert "Text: FastAPI" in captured.out
        assert "Keep: true" in captured.out
        assert "Confidence: 0.9" in captured.out
        assert "Reason: Important term" in captured.out

    def test_handles_absolute_knowledge_path(self, tmp_path: Path) -> None:
        """Should resolve absolute knowledge paths correctly."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "false",
                "--confidence",
                "0.87",
                "--reason",
                "Too generic",
                "--knowledge-path",
                str(knowledge_path.resolve()),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 0

    def test_handles_relative_knowledge_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should resolve relative paths from REPO_ROOT."""
        # Create the knowledge directory under tmp_path
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        # Patch REPO_ROOT to tmp_path
        monkeypatch.setattr("scripts.knowledge.classify_keyword.REPO_ROOT", tmp_path)

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "true",
                "--confidence",
                "0.9",
                "--reason",
                "Test",
                "--knowledge-path",
                ".knowledge",
            ]
        )

        result = classify_keyword_main(args)
        assert result == 0

    def test_keep_false_classification(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle keep='false' classification correctly."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "the",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "false",
                "--confidence",
                "0.95",
                "--reason",
                "Common English word, not a keyword",
                "--knowledge-path",
                str(knowledge_path),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Keep: false" in captured.out

        # Verify CSV contains false
        content = csv_path.read_text()
        assert "false" in content

    def test_boundary_confidence_zero(self, tmp_path: Path) -> None:
        """Should accept confidence=0.0 as valid."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "false",
                "--confidence",
                "0.0",
                "--reason",
                "No confidence",
                "--knowledge-path",
                str(knowledge_path),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 0

    def test_boundary_confidence_one(self, tmp_path: Path) -> None:
        """Should accept confidence=1.0 as valid."""
        knowledge_path = tmp_path / ".knowledge"
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--id",
                "cand-1",
                "--keep",
                "true",
                "--confidence",
                "1.0",
                "--reason",
                "Full confidence",
                "--knowledge-path",
                str(knowledge_path),
            ]
        )

        result = classify_keyword_main(args)
        assert result == 0
