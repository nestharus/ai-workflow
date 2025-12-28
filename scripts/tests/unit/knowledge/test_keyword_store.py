import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


class TestApplyKeywordsMain:
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


class TestMainApply:
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
