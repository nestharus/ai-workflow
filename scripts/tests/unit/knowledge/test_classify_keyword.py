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
    projection_version: str = "fieldfacts.v2",
    source_field_path: str = "",
    source_scope_path: str = "",
    field_role: str = "",
    artifact_kind: str = "",
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
            projection_version,
            source_field_path,
            source_scope_path,
            field_role,
            artifact_kind,
        ]
    )


class TestClassifyKeywordMain:
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

    def test_returns_error_when_update_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return 1 when update_candidate_classification returns False."""
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

        # Mock update_candidate_classification to return False
        from scripts.knowledge import classify_keyword

        monkeypatch.setattr(
            classify_keyword, "update_candidate_classification", lambda *args, **kwargs: False
        )

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
        assert "Failed to update candidate" in captured.err


class TestMain:
    def test_main_calls_parse_args_and_classify_keyword_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should call parse_args and classify_keyword_main."""
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

        # Import main function
        # Patch sys.argv
        import sys

        from scripts.knowledge.classify_keyword import main

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "script",
                "--id",
                "cand-1",
                "--keep",
                "true",
                "--confidence",
                "0.9",
                "--reason",
                "Test reason",
                "--knowledge-path",
                str(knowledge_path),
            ],
        )

        result = main()
        assert result == 0
