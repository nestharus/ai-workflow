"""Tests for scripts.knowledge.keyword_store module."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.knowledge.keyword_schema import KEYWORD_COLUMNS
from scripts.knowledge.keyword_store import (
    KeywordRecord,
    ReadCandidatesError,
    apply_keywords_main,
    apply_keywords_to_yaml_file,
    ensure_keywords_csv_exists,
    get_all_keywords,
    get_keywords_for_file,
    main_apply,
    parse_args,
    read_kept_candidates,
    upsert_keywords_csv,
)


class TestGetKeywordsForFile:
    """Tests for get_keywords_for_file function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty list when CSV doesn't exist."""
        csv_path = tmp_path / "keywords.csv"
        result = get_keywords_for_file(csv_path, "docs/test.yml")
        assert result == []

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV."""
        csv_path = tmp_path / "keywords.csv"
        csv_path.write_text("")
        result = get_keywords_for_file(csv_path, "docs/test.yml")
        assert result == []

    def test_returns_keywords_for_file(self, tmp_path: Path) -> None:
        """Should return keywords matching source file."""
        csv_path = tmp_path / "keywords.csv"
        header = ",".join(KEYWORD_COLUMNS)
        # CSV rows: keyword,source_file,element_id,snippet,first_detected,last_updated
        csv_path.write_text(
            f"{header}\n"
            "FastAPI,docs/test.yml,elem-1,snippet1,2024-01-01,2024-01-01\n"
            "Pydantic,docs/other.yml,elem-2,snippet2,2024-01-01,2024-01-01\n"
        )

        result = get_keywords_for_file(csv_path, "docs/test.yml")
        assert len(result) == 1
        assert result[0]["keyword"] == "FastAPI"
        assert result[0]["source_file"] == "docs/test.yml"
        assert result[0]["element_id"] == "elem-1"

    def test_returns_empty_for_no_match(self, tmp_path: Path) -> None:
        """Should return empty list when no keywords match."""
        csv_path = tmp_path / "keywords.csv"
        header = ",".join(KEYWORD_COLUMNS)
        csv_path.write_text(
            f"{header}\nFastAPI,docs/test.yml,elem-1,snippet1,2024-01-01,2024-01-01\n"
        )

        result = get_keywords_for_file(csv_path, "docs/nonexistent.yml")
        assert result == []


class TestGetAllKeywords:
    """Tests for get_all_keywords function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty list when CSV doesn't exist."""
        csv_path = tmp_path / "keywords.csv"
        result = get_all_keywords(csv_path)
        assert result == []

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV."""
        csv_path = tmp_path / "keywords.csv"
        csv_path.write_text("")
        result = get_all_keywords(csv_path)
        assert result == []

    def test_returns_all_keywords(self, tmp_path: Path) -> None:
        """Should return all keywords."""
        csv_path = tmp_path / "keywords.csv"
        header = ",".join(KEYWORD_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "FastAPI,docs/test.yml,elem-1,snippet1,2024-01-01,2024-01-01\n"
            "Pydantic,docs/other.yml,elem-2,snippet2,2024-01-01,2024-01-01\n"
        )

        result = get_all_keywords(csv_path)
        assert len(result) == 2
        assert result[0]["keyword"] == "FastAPI"
        assert result[1]["keyword"] == "Pydantic"


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.dry_run is False
        assert args.knowledge_path == Path(".knowledge")

    def test_dry_run(self) -> None:
        """Should parse --dry-run flag."""
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")


class TestReadKeptCandidates:
    """Tests for read_kept_candidates function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty list when CSV doesn't exist."""
        csv_path = tmp_path / "candidates.csv"
        result = read_kept_candidates(csv_path)
        assert result == []

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV."""
        csv_path = tmp_path / "candidates.csv"
        csv_path.write_text("")
        result = read_kept_candidates(csv_path)
        assert result == []

    def test_raises_error_for_malformed_csv(self, tmp_path: Path) -> None:
        """Should raise ReadCandidatesError for malformed CSV."""
        csv_path = tmp_path / "candidates.csv"
        # Write malformed CSV that DuckDB can't parse
        csv_path.write_text('this is not valid csv\n"unclosed quote')

        with pytest.raises(ReadCandidatesError):
            read_kept_candidates(csv_path)


class TestApplyKeywordsToYamlFile:
    """Tests for apply_keywords_to_yaml_file function."""

    def test_returns_empty_set_for_parse_failure(self, tmp_path: Path) -> None:
        """Should return empty updated_element_ids set when YAML parse fails."""
        yaml_path = tmp_path / "invalid.yml"
        yaml_path.write_text("invalid: yaml: content: [")

        element_keywords = {"elem-1": ["keyword1"]}
        count, updates, updated_ids = apply_keywords_to_yaml_file(yaml_path, element_keywords)

        assert count == 0
        assert updates == []
        assert updated_ids == set()

    def test_returns_empty_set_for_missing_file(self, tmp_path: Path) -> None:
        """Should return empty updated_element_ids set when file doesn't exist."""
        yaml_path = tmp_path / "nonexistent.yml"

        element_keywords = {"elem-1": ["keyword1"]}
        count, updates, updated_ids = apply_keywords_to_yaml_file(yaml_path, element_keywords)

        assert count == 0
        assert updates == []
        assert updated_ids == set()

    def test_returns_updated_element_ids_on_success(self, tmp_path: Path) -> None:
        """Should return set of successfully updated element IDs."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test item\n")

        element_keywords = {"elem-1": ["keyword1", "keyword2"]}
        count, updates, updated_ids = apply_keywords_to_yaml_file(yaml_path, element_keywords)

        assert count == 1
        assert "elem-1" in updated_ids
        assert len(updates) == 1


class TestApplyKeywordsMain:
    """Tests for apply_keywords_main function."""

    def test_returns_error_for_missing_candidates_csv(self, tmp_path: Path) -> None:
        """Should return 1 when candidates.csv doesn't exist."""
        args = argparse.Namespace(
            knowledge_path=tmp_path,
            dry_run=False,
        )

        result = apply_keywords_main(args)
        assert result == 1

    def test_returns_error_for_malformed_candidates_csv(self, tmp_path: Path) -> None:
        """Should return 1 when candidates.csv is malformed."""
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        candidates_csv = keywords_dir / "candidates.csv"
        # Write malformed CSV
        candidates_csv.write_text('this is not valid csv\n"unclosed quote')

        args = argparse.Namespace(
            knowledge_path=tmp_path,
            dry_run=False,
        )

        result = apply_keywords_main(args)
        assert result == 1

    def test_returns_success_for_no_kept_candidates(self, tmp_path: Path) -> None:
        """Should return 0 when no kept candidates found."""
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        candidates_csv = keywords_dir / "candidates.csv"
        # Write valid CSV with no kept candidates
        candidates_csv.write_text(
            "candidate_id,source_file,element_id,sentence,candidate_text,"
            "start_char,end_char,detected_at,keep,confidence,reason,classified_at,qwen_score,"
            "projection_version,source_field_path,source_scope_path,field_role,artifact_kind\n"
            "c1,docs/test.yml,elem-1,sentence,keyword1,0,7,2024-01-01,false,0.5,noise,,,"
            "fieldfacts.v2,,,,\n"
        )

        args = argparse.Namespace(
            knowledge_path=tmp_path,
            dry_run=False,
        )

        result = apply_keywords_main(args)
        assert result == 0

    def test_does_not_index_keywords_for_failed_yaml_file(self, tmp_path: Path) -> None:
        """Should not add index records for files that failed to parse/write."""
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()

        # Create candidates CSV with kept candidate
        candidates_csv = keywords_dir / "candidates.csv"
        candidates_csv.write_text(
            "candidate_id,source_file,element_id,sentence,candidate_text,"
            "start_char,end_char,detected_at,keep,confidence,reason,classified_at,qwen_score,"
            "projection_version,source_field_path,source_scope_path,field_role,artifact_kind\n"
            "c1,nonexistent.yml,elem-1,sentence,keyword1,0,7,2024-01-01,true,0.9,good,,,"
            "fieldfacts.v2,,,,\n"
        )

        args = argparse.Namespace(
            knowledge_path=tmp_path,
            dry_run=False,
        )

        # Mock REPO_ROOT to use tmp_path
        with patch("scripts.knowledge.keyword_store.REPO_ROOT", tmp_path):
            result = apply_keywords_main(args)

        # Should succeed but not create any keyword records
        assert result == 0

        # keywords.csv should not exist or be empty (no records created)
        keywords_csv = keywords_dir / "keywords.csv"
        if keywords_csv.exists():
            keywords = get_all_keywords(keywords_csv)
            assert len(keywords) == 0

    def test_handles_absolute_knowledge_path(self, tmp_path: Path) -> None:
        """Should handle absolute knowledge path correctly (line 447)."""
        # Use absolute path for knowledge_path
        knowledge_path = tmp_path.resolve()
        keywords_dir = knowledge_path / "keywords"
        keywords_dir.mkdir()
        candidates_csv = keywords_dir / "candidates.csv"
        # Write valid CSV with no kept candidates
        candidates_csv.write_text(
            "candidate_id,source_file,element_id,sentence,candidate_text,"
            "start_char,end_char,detected_at,keep,confidence,reason,classified_at,qwen_score,"
            "projection_version,source_field_path,source_scope_path,field_role,artifact_kind\n"
            "c1,docs/test.yml,elem-1,sentence,keyword1,0,7,2024-01-01,false,0.5,noise,,,"
            "fieldfacts.v2,,,,\n"
        )

        args = argparse.Namespace(
            knowledge_path=knowledge_path,  # Absolute path
            dry_run=False,
        )

        result = apply_keywords_main(args)
        assert result == 0

    def test_dry_run_prints_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print dry run message when dry_run is True (line 471)."""
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        candidates_csv = keywords_dir / "candidates.csv"
        # Write valid CSV with a kept candidate
        candidates_csv.write_text(
            "candidate_id,source_file,element_id,sentence,candidate_text,"
            "start_char,end_char,detected_at,keep,confidence,reason,classified_at,qwen_score,"
            "projection_version,source_field_path,source_scope_path,field_role,artifact_kind\n"
            "c1,docs/test.yml,elem-1,sentence,keyword1,0,7,2024-01-01,true,0.9,good,,,"
            "fieldfacts.v2,,,,\n"
        )

        args = argparse.Namespace(
            knowledge_path=tmp_path,
            dry_run=True,
        )

        with patch("scripts.knowledge.keyword_store.REPO_ROOT", tmp_path):
            result = apply_keywords_main(args)

        captured = capsys.readouterr()
        assert "(dry run - no changes will be made)" in captured.out
        assert result == 0

    def test_skips_element_not_in_updated_ids(self, tmp_path: Path) -> None:
        """Should skip indexing keywords for elements not in updated_element_ids (line 512)."""
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()

        # Create a YAML file with an element
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test item\n")

        # Create candidates CSV with kept candidate for a non-existent element
        candidates_csv = keywords_dir / "candidates.csv"
        candidates_csv.write_text(
            "candidate_id,source_file,element_id,sentence,candidate_text,"
            "start_char,end_char,detected_at,keep,confidence,reason,classified_at,qwen_score,"
            "projection_version,source_field_path,source_scope_path,field_role,artifact_kind\n"
            "c1,test.yml,elem-nonexistent,sentence,keyword1,0,7,2024-01-01,true,0.9,good,,,"
            "fieldfacts.v2,,,,\n"
        )

        args = argparse.Namespace(
            knowledge_path=tmp_path,
            dry_run=False,
        )

        with patch("scripts.knowledge.keyword_store.REPO_ROOT", tmp_path):
            result = apply_keywords_main(args)

        # Should succeed but no keywords indexed (element not found)
        assert result == 0
        keywords_csv = keywords_dir / "keywords.csv"
        if keywords_csv.exists():
            keywords = get_all_keywords(keywords_csv)
            assert len(keywords) == 0

    def test_finds_matching_snippet_from_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should find matching snippet from candidate (branch 519->524)."""
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()

        # Create a YAML file with an element
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test item\n")

        # Create candidates CSV with kept candidate including specific sentence
        candidates_csv = keywords_dir / "candidates.csv"
        candidates_csv.write_text(
            "candidate_id,source_file,element_id,sentence,candidate_text,"
            "start_char,end_char,detected_at,keep,confidence,reason,classified_at,qwen_score,"
            "projection_version,source_field_path,source_scope_path,field_role,artifact_kind\n"
            "c1,test.yml,elem-1,This is the test sentence,keyword1,0,7,2024-01-01,true,0.9,good,,,"
            "fieldfacts.v2,,,,\n"
        )

        args = argparse.Namespace(
            knowledge_path=tmp_path,
            dry_run=False,
        )

        with patch("scripts.knowledge.keyword_store.REPO_ROOT", tmp_path):
            result = apply_keywords_main(args)

        # Should succeed and create keyword record with snippet
        assert result == 0
        keywords_csv = keywords_dir / "keywords.csv"
        keywords = get_all_keywords(keywords_csv)
        assert len(keywords) == 1
        assert keywords[0]["snippet"] == "This is the test sentence"


class TestApplyKeywordsToYamlFileExtended:
    """Extended tests for apply_keywords_to_yaml_file function."""

    def test_element_not_found_adds_to_updates(self, tmp_path: Path) -> None:
        """Should add update message when element not found (lines 223-224)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test item\n")

        # Request keyword for non-existent element
        element_keywords = {"elem-nonexistent": ["keyword1"]}
        count, updates, updated_ids = apply_keywords_to_yaml_file(yaml_path, element_keywords)

        assert count == 0
        assert len(updates) == 1
        assert "elem-nonexistent" in updates[0]
        assert "not found" in updates[0]
        assert updated_ids == set()

    def test_handles_non_list_existing_keywords(self, tmp_path: Path) -> None:
        """Should handle non-list existing keywords field (line 229)."""
        yaml_path = tmp_path / "test.yml"
        # Element has keywords as string instead of list
        yaml_path.write_text("items:\n  - id: elem-1\n    keywords: not-a-list\n    text: Test\n")

        element_keywords = {"elem-1": ["keyword1"]}
        count, _updates, updated_ids = apply_keywords_to_yaml_file(yaml_path, element_keywords)

        assert count == 1
        assert "elem-1" in updated_ids
        # Verify file was updated with list
        content = yaml_path.read_text()
        assert "keyword1" in content

    def test_skips_duplicate_keywords(self, tmp_path: Path) -> None:
        """Should skip keywords that already exist (branch 235->220)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text(
            "items:\n  - id: elem-1\n    keywords:\n      - existing_keyword\n    text: Test\n"
        )

        element_keywords = {"elem-1": ["existing_keyword"]}  # Already exists
        count, _updates, updated_ids = apply_keywords_to_yaml_file(yaml_path, element_keywords)

        # No updates because keyword already exists
        assert count == 0
        assert updated_ids == set()

    def test_returns_empty_on_write_failure(self, tmp_path: Path) -> None:
        """Should return empty set when file write fails (lines 253-257)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test item\n")

        element_keywords = {"elem-1": ["keyword1"]}

        with patch("scripts.knowledge.keyword_store.Path.write_text") as mock_write:
            mock_write.side_effect = OSError("Permission denied")
            count, updates, updated_ids = apply_keywords_to_yaml_file(yaml_path, element_keywords)

        assert count == 0
        assert updates == []
        assert updated_ids == set()


class TestEnsureKeywordsCsvExists:
    """Tests for ensure_keywords_csv_exists function."""

    def test_creates_csv_when_missing(self, tmp_path: Path) -> None:
        """Should create CSV with headers when file doesn't exist."""
        csv_path = tmp_path / "keywords" / "keywords.csv"

        ensure_keywords_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        # Should contain header with all columns
        for col in KEYWORD_COLUMNS:
            assert col in content

    def test_creates_csv_when_empty(self, tmp_path: Path) -> None:
        """Should create CSV with headers when file is empty."""
        csv_path = tmp_path / "keywords" / "keywords.csv"
        csv_path.parent.mkdir(parents=True)
        csv_path.write_text("")  # Empty file

        ensure_keywords_csv_exists(csv_path)

        content = csv_path.read_text()
        for col in KEYWORD_COLUMNS:
            assert col in content

    def test_does_not_overwrite_existing_csv(self, tmp_path: Path) -> None:
        """Should not overwrite existing non-empty CSV (branch 90->-80)."""
        csv_path = tmp_path / "keywords" / "keywords.csv"
        csv_path.parent.mkdir(parents=True)
        header = ",".join(KEYWORD_COLUMNS)
        original_content = f"{header}\nkeyword1,file.yml,elem-1,snippet,2024-01-01,2024-01-01\n"
        csv_path.write_text(original_content)

        ensure_keywords_csv_exists(csv_path)

        # Content should be unchanged
        assert csv_path.read_text() == original_content


class TestMainApply:
    """Tests for main_apply function."""

    def test_calls_parse_args_and_apply_keywords_main(self) -> None:
        """Should call parse_args and apply_keywords_main (lines 554-555)."""
        with patch("scripts.knowledge.keyword_store.parse_args") as mock_parse:
            mock_args = MagicMock()
            mock_parse.return_value = mock_args
            with patch("scripts.knowledge.keyword_store.apply_keywords_main") as mock_apply:
                mock_apply.return_value = 0

                result = main_apply()

        mock_parse.assert_called_once()
        mock_apply.assert_called_once_with(mock_args)
        assert result == 0

    def test_returns_error_code_from_apply_keywords_main(self) -> None:
        """Should return error code from apply_keywords_main."""
        with patch("scripts.knowledge.keyword_store.parse_args") as mock_parse:
            mock_args = MagicMock()
            mock_parse.return_value = mock_args
            with patch("scripts.knowledge.keyword_store.apply_keywords_main") as mock_apply:
                mock_apply.return_value = 1  # Error

                result = main_apply()

        assert result == 1


class TestUpsertKeywordsCsv:
    """Tests for upsert_keywords_csv function."""

    def test_returns_zero_for_empty_records(self, tmp_path: Path) -> None:
        """Should return 0 when records list is empty (line 280)."""
        csv_path = tmp_path / "keywords.csv"

        result = upsert_keywords_csv(csv_path, [])

        assert result == 0

    def test_inserts_new_record(self, tmp_path: Path) -> None:
        """Should insert new keyword record."""
        csv_path = tmp_path / "keywords.csv"
        records = [
            KeywordRecord(
                keyword="FastAPI",
                source_file="docs/test.yml",
                element_id="elem-1",
                snippet="Test snippet",
                first_detected="2024-01-01",
                last_updated="2024-01-01",
            )
        ]

        result = upsert_keywords_csv(csv_path, records)

        assert result == 1
        keywords = get_all_keywords(csv_path)
        assert len(keywords) == 1
        assert keywords[0]["keyword"] == "FastAPI"

    def test_updates_existing_record(self, tmp_path: Path) -> None:
        """Should update existing record's last_updated (lines 307, 312)."""
        csv_path = tmp_path / "keywords.csv"
        header = ",".join(KEYWORD_COLUMNS)
        csv_path.write_text(
            f"{header}\nFastAPI,docs/test.yml,elem-1,old snippet,2024-01-01,2024-01-01\n"
        )

        # Update with new timestamp
        records = [
            KeywordRecord(
                keyword="FastAPI",
                source_file="docs/test.yml",
                element_id="elem-1",
                snippet="new snippet",
                first_detected="2024-01-01",
                last_updated="2024-12-01",
            )
        ]

        result = upsert_keywords_csv(csv_path, records)

        assert result == 1
        keywords = get_all_keywords(csv_path)
        assert len(keywords) == 1
        assert keywords[0]["last_updated"] == "2024-12-01"
        assert keywords[0]["snippet"] == "new snippet"

    def test_handles_multiple_records(self, tmp_path: Path) -> None:
        """Should handle multiple records in single call."""
        csv_path = tmp_path / "keywords.csv"
        records = [
            KeywordRecord(
                keyword="FastAPI",
                source_file="docs/test.yml",
                element_id="elem-1",
                snippet="snippet1",
                first_detected="2024-01-01",
                last_updated="2024-01-01",
            ),
            KeywordRecord(
                keyword="Pydantic",
                source_file="docs/test.yml",
                element_id="elem-2",
                snippet="snippet2",
                first_detected="2024-01-01",
                last_updated="2024-01-01",
            ),
        ]

        result = upsert_keywords_csv(csv_path, records)

        assert result == 2
        keywords = get_all_keywords(csv_path)
        assert len(keywords) == 2
