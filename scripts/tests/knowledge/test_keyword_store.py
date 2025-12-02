"""Tests for scripts.knowledge.keyword_store module."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.knowledge.keyword_schema import KEYWORD_COLUMNS
from scripts.knowledge.keyword_store import (
    ReadCandidatesError,
    apply_keywords_main,
    apply_keywords_to_yaml_file,
    get_all_keywords,
    get_keywords_for_file,
    parse_args,
    read_kept_candidates,
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
            "start_char,end_char,detected_at,keep,confidence,reason,classified_at,qwen_score\n"
            "c1,docs/test.yml,elem-1,sentence,keyword1,0,7,2024-01-01,false,0.5,noise,,\n"
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
            "start_char,end_char,detected_at,keep,confidence,reason,classified_at,qwen_score\n"
            "c1,nonexistent.yml,elem-1,sentence,keyword1,0,7,2024-01-01,true,0.9,good,,\n"
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
