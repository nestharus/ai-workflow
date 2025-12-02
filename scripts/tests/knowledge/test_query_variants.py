"""Tests for scripts.knowledge.query_variants module."""

from __future__ import annotations

from pathlib import Path

from scripts.knowledge.query_variants import (
    parse_args,
    query_variants,
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
        """Should return all variants when no filter applied."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "var-1,kw-1,API,0.95,docs/test.yml,2024-01-01,false,false\n"
            "var-2,kw-1,api,0.9,docs/test.yml,2024-01-01,true,false\n"
        )

        result = query_variants(csv_path)
        assert len(result) == 2

    def test_filters_by_keyword_id(self, tmp_path: Path) -> None:
        """Should filter by keyword ID."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "var-1,kw-1,API,0.95,docs/test.yml,2024-01-01,false,false\n"
            "var-2,kw-2,Framework,0.9,docs/test.yml,2024-01-01,false,false\n"
        )

        result = query_variants(csv_path, keyword_id="kw-1")
        assert len(result) == 1
        assert result[0]["variant_term"] == "API"

    def test_filters_by_validated(self, tmp_path: Path) -> None:
        """Should filter by validation status."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "var-1,kw-1,API,0.95,docs/test.yml,2024-01-01,false,false\n"
            "var-2,kw-1,api,0.9,docs/test.yml,2024-01-01,true,false\n"
        )

        result = query_variants(csv_path, validated_only=True)
        assert len(result) == 1
        assert result[0]["variant_term"] == "api"

    def test_filters_by_min_similarity(self, tmp_path: Path) -> None:
        """Should filter by minimum similarity score."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "var-1,kw-1,API,0.95,docs/test.yml,2024-01-01,false,false\n"
            "var-2,kw-1,api,0.8,docs/test.yml,2024-01-01,false,false\n"
        )

        result = query_variants(csv_path, min_similarity=0.9)
        assert len(result) == 1
        assert result[0]["variant_term"] == "API"

    def test_respects_limit(self, tmp_path: Path) -> None:
        """Should respect limit parameter."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "var-1,kw-1,API,0.95,docs/test.yml,2024-01-01,false,false\n"
            "var-2,kw-1,api,0.9,docs/test.yml,2024-01-01,false,false\n"
            "var-3,kw-1,Api,0.85,docs/test.yml,2024-01-01,false,false\n"
        )

        result = query_variants(csv_path, limit=2)
        assert len(result) == 2


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.keyword_id is None
        assert args.validated is False
        assert args.min_similarity is None
        assert args.limit is None
        assert args.knowledge_path == Path(".knowledge")

    def test_keyword_id(self) -> None:
        """Should parse --keyword-id argument."""
        args = parse_args(["--keyword-id", "kw-123"])
        assert args.keyword_id == "kw-123"

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

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")
