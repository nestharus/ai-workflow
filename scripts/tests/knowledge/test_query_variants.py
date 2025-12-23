"""Tests for scripts.knowledge.query_variants module."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.knowledge.query_variants import (
    main,
    parse_args,
    query_variants,
    query_variants_main,
)
from scripts.knowledge.variant_resolver import VARIANT_COLUMNS


class TestQueryVariants:
    """Tests for query_variants function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty list when CSV doesn't exist."""
        csv_path = tmp_path / "variant_candidates.csv"
        result = query_variants(csv_path)
        assert result == []

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV."""
        csv_path = tmp_path / "variant_candidates.csv"
        csv_path.write_text("")
        result = query_variants(csv_path)
        assert result == []

    def test_returns_all_variants(self, tmp_path: Path) -> None:
        """Should return all variant pairs when no filter applied."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "pair-1,API,Application Programming Interface,0.95,,,,\n"
            "pair-2,DB,database,0.9,true,database,abbreviation,true\n"
        )

        result = query_variants(csv_path)
        assert len(result) == 2

    def test_filters_by_unvalidated(self, tmp_path: Path) -> None:
        """Should filter to unvalidated pairs only."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "pair-1,API,Application Programming Interface,0.95,,,,\n"
            "pair-2,DB,database,0.9,true,database,abbreviation,true\n"
        )

        result = query_variants(csv_path, unvalidated_only=True)
        assert len(result) == 1
        assert result[0]["keyword_a"] == "API"

    def test_filters_by_validated(self, tmp_path: Path) -> None:
        """Should filter by validation status."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "pair-1,API,Application Programming Interface,0.95,,,,\n"
            "pair-2,DB,database,0.9,true,database,abbreviation,true\n"
        )

        result = query_variants(csv_path, validated_only=True)
        assert len(result) == 1
        assert result[0]["keyword_a"] == "DB"

    def test_filters_by_min_similarity(self, tmp_path: Path) -> None:
        """Should filter by minimum similarity score."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "pair-1,API,Application Programming Interface,0.95,,,,\n"
            "pair-2,DB,database,0.8,,,,\n"
        )

        result = query_variants(csv_path, min_similarity=0.9)
        assert len(result) == 1
        assert result[0]["keyword_a"] == "API"

    def test_respects_limit(self, tmp_path: Path) -> None:
        """Should respect limit parameter."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "pair-1,API,Application Programming Interface,0.95,,,,\n"
            "pair-2,DB,database,0.9,,,,\n"
            "pair-3,conn,connection,0.85,,,,\n"
        )

        result = query_variants(csv_path, limit=2)
        assert len(result) == 2


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.unvalidated is False
        assert args.validated is False
        assert args.min_similarity is None
        assert args.limit is None
        assert args.output_format == "text"
        assert args.knowledge_path == Path(".knowledge")

    def test_unvalidated_flag(self) -> None:
        """Should parse --unvalidated flag."""
        args = parse_args(["--unvalidated"])
        assert args.unvalidated is True

    def test_validated_flag(self) -> None:
        """Should parse --validated flag."""
        args = parse_args(["--validated"])
        assert args.validated is True

    def test_min_similarity(self) -> None:
        """Should parse --min-similarity as float."""
        args = parse_args(["--min-similarity", "0.85"])
        assert args.min_similarity == 0.85

    def test_limit(self) -> None:
        """Should parse --limit as int."""
        args = parse_args(["--limit", "10"])
        assert args.limit == 10

    def test_format_json(self) -> None:
        """Should parse --format json."""
        args = parse_args(["--format", "json"])
        assert args.output_format == "json"

    def test_format_text(self) -> None:
        """Should parse --format text."""
        args = parse_args(["--format", "text"])
        assert args.output_format == "text"

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")


class TestQueryVariantsMain:
    """Tests for query_variants_main function."""

    def test_returns_one_for_missing_csv(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when variants CSV doesn't exist.

        This covers lines 173-175 where CSV not found.
        """
        args = argparse.Namespace(
            knowledge_path=tmp_path,  # No keywords directory
            unvalidated=False,
            validated=False,
            min_similarity=None,
            limit=None,
            output_format="text",
        )

        result = query_variants_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_handles_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge path correctly.

        This covers lines 166-167 (then branch) where path.is_absolute() is True.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.95,,,,\n")

        # Use absolute path
        absolute_path = tmp_path.resolve()
        assert absolute_path.is_absolute()

        args = argparse.Namespace(
            knowledge_path=absolute_path,
            unvalidated=False,
            validated=False,
            min_similarity=None,
            limit=None,
            output_format="text",
        )

        result = query_variants_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Found 1 variant pair(s)" in captured.out

    def test_handles_relative_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should resolve relative knowledge path against REPO_ROOT.

        This covers lines 168-169 (else branch) where path is relative.
        """
        keywords_dir = tmp_path / ".knowledge" / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.95,,,,\n")

        with patch("scripts.knowledge.query_variants.REPO_ROOT", tmp_path):
            args = argparse.Namespace(
                knowledge_path=Path(".knowledge"),  # Relative path
                unvalidated=False,
                validated=False,
                min_similarity=None,
                limit=None,
                output_format="text",
            )

            result = query_variants_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Found 1 variant pair(s)" in captured.out

    def test_returns_zero_for_empty_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and print message for empty results.

        This covers lines 185-190.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\n")  # Empty CSV (header only)

        args = argparse.Namespace(
            knowledge_path=tmp_path.resolve(),
            unvalidated=False,
            validated=False,
            min_similarity=None,
            limit=None,
            output_format="text",
        )

        result = query_variants_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No variant pairs found" in captured.out

    def test_json_output_format_with_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should output JSON format when requested.

        This covers lines 192-193.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.95,,,,\n")

        args = argparse.Namespace(
            knowledge_path=tmp_path.resolve(),
            unvalidated=False,
            validated=False,
            min_similarity=None,
            limit=None,
            output_format="json",
        )

        result = query_variants_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert '"pair_id": "pair-1"' in captured.out or '"pair_id"' in captured.out

    def test_json_output_format_empty_results(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should output empty JSON array for no results.

        This covers lines 186-187.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\n")

        args = argparse.Namespace(
            knowledge_path=tmp_path.resolve(),
            unvalidated=False,
            validated=False,
            min_similarity=None,
            limit=None,
            output_format="json",
        )

        result = query_variants_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "[]" in captured.out

    def test_text_output_shows_merge_info(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should show merge, canonical, and reason in text output.

        This covers lines 201-205.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\npair-1,API,Application Programming Interface,0.95,true,API,Abbreviation is common,true\n"
        )

        args = argparse.Namespace(
            knowledge_path=tmp_path.resolve(),
            unvalidated=False,
            validated=False,
            min_similarity=None,
            limit=None,
            output_format="text",
        )

        result = query_variants_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Merge: true" in captured.out
        assert "Canonical: API" in captured.out
        assert "Reason: Abbreviation is common" in captured.out


class TestMain:
    """Tests for main function."""

    def test_main_calls_query_variants_main(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should parse args and call query_variants_main.

        This covers lines 218-219.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.95,,,,\n")

        with patch("sys.argv", ["script", "--knowledge-path", str(tmp_path)]):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Found 1 variant pair(s)" in captured.out
