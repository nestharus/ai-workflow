import json
from io import StringIO
from pathlib import Path
from unittest import mock

from scripts.knowledge.candidate_extraction import CSV_COLUMNS
from scripts.knowledge.query_keyword_candidates import (
    format_candidate_for_json,
    main,
    parse_args,
    query_candidates,
    query_candidates_main,
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
    projection_version: str = "fieldfacts.v2",
    source_field_path: str = "",
    source_scope_path: str = "",
    field_role: str = "",
    artifact_kind: str = "",
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
            projection_version,
            source_field_path,
            source_scope_path,
            field_role,
            artifact_kind,
        ]
    )


class TestQueryCandidatesMain:
    def test_returns_error_when_csv_missing(self, tmp_path: Path) -> None:
        """Should return 1 when CSV does not exist."""
        args = parse_args(
            [
                "--knowledge-path",
                str(tmp_path / ".knowledge"),
            ]
        )

        with mock.patch("sys.stderr", new_callable=StringIO):
            result = query_candidates_main(args)

        assert result == 1

    def test_json_output_format(self, tmp_path: Path) -> None:
        """Should output JSON array for --format json."""
        knowledge_path = tmp_path / ".knowledge" / "keywords"
        knowledge_path.mkdir(parents=True)
        csv_path = knowledge_path / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
            "0",
            "7",
            "2024-01-01",
            "",
            "0.9",
            "",
            "",
            "0.85",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--knowledge-path",
                str(tmp_path / ".knowledge"),
                "--format",
                "json",
            ]
        )

        with mock.patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = query_candidates_main(args)

        assert result == 0
        output = mock_stdout.getvalue()
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["candidate_text"] == "FastAPI"

    def test_jsonl_output_format(self, tmp_path: Path) -> None:
        """Should output JSON lines for --format jsonl."""
        knowledge_path = tmp_path / ".knowledge" / "keywords"
        knowledge_path.mkdir(parents=True)
        csv_path = knowledge_path / "candidates.csv"

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

        args = parse_args(
            [
                "--knowledge-path",
                str(tmp_path / ".knowledge"),
                "--format",
                "jsonl",
            ]
        )

        with mock.patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = query_candidates_main(args)

        assert result == 0
        output = mock_stdout.getvalue()
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) == 2
        # Each line should be valid JSON
        for line in lines:
            data = json.loads(line)
            assert "candidate_text" in data

    def test_text_output_format_no_candidates(self, tmp_path: Path) -> None:
        """Should show no candidates message for empty results."""
        knowledge_path = tmp_path / ".knowledge" / "keywords"
        knowledge_path.mkdir(parents=True)
        csv_path = knowledge_path / "candidates.csv"

        # Create CSV with header only
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        args = parse_args(
            [
                "--knowledge-path",
                str(tmp_path / ".knowledge"),
                "--format",
                "text",
            ]
        )

        with mock.patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = query_candidates_main(args)

        assert result == 0
        output = mock_stdout.getvalue()
        assert "No candidates found" in output

    def test_text_output_format_with_candidates(self, tmp_path: Path) -> None:
        """Should show formatted text output with candidates."""
        knowledge_path = tmp_path / ".knowledge" / "keywords"
        knowledge_path.mkdir(parents=True)
        csv_path = knowledge_path / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
            "cand-1",
            "docs/test.yml",
            "elem1",
            "Test sentence",
            "FastAPI",
            "0",
            "7",
            "2024-01-01",
            "true",
            "0.95",
            "",
            "",
            "0.88",
        )
        csv_path.write_text(f"{header}\n{row}\n")

        args = parse_args(
            [
                "--knowledge-path",
                str(tmp_path / ".knowledge"),
                "--format",
                "text",
            ]
        )

        with mock.patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = query_candidates_main(args)

        assert result == 0
        output = mock_stdout.getvalue()
        assert "Found 1 candidate(s)" in output
        assert "FastAPI" in output
        assert "docs/test.yml" in output
        assert "elem1" in output
        assert "true" in output
        assert "0.95" in output
        assert "0.88" in output

    def test_with_absolute_knowledge_path(self, tmp_path: Path) -> None:
        """Should handle absolute knowledge path correctly."""
        knowledge_path = tmp_path / ".knowledge" / "keywords"
        knowledge_path.mkdir(parents=True)
        csv_path = knowledge_path / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        row = _make_csv_row(
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
        csv_path.write_text(f"{header}\n{row}\n")

        # Use absolute path
        args = parse_args(
            [
                "--knowledge-path",
                str(tmp_path / ".knowledge"),
                "--format",
                "json",
            ]
        )

        with mock.patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = query_candidates_main(args)

        assert result == 0
        output = mock_stdout.getvalue()
        data = json.loads(output)
        assert len(data) == 1


class TestMain:
    def test_main_calls_query_candidates_main(self, tmp_path: Path) -> None:
        """Should call query_candidates_main with parsed args."""
        knowledge_path = tmp_path / ".knowledge" / "keywords"
        knowledge_path.mkdir(parents=True)
        csv_path = knowledge_path / "candidates.csv"

        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        # Mock sys.argv to provide arguments
        with (
            mock.patch(
                "sys.argv",
                ["prog", "--knowledge-path", str(tmp_path / ".knowledge"), "--format", "text"],
            ),
            mock.patch("sys.stdout", new_callable=StringIO),
        ):
            result = main()

        assert result == 0

    def test_main_returns_error_on_missing_csv(self, tmp_path: Path) -> None:
        """Should return 1 when CSV is missing."""
        # Mock sys.argv with non-existent path
        with (
            mock.patch("sys.argv", ["prog", "--knowledge-path", str(tmp_path / "nonexistent")]),
            mock.patch("sys.stderr", new_callable=StringIO),
        ):
            result = main()

        assert result == 1
