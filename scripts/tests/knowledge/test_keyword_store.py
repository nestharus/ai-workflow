"""Tests for scripts.knowledge.keyword_store module."""

from __future__ import annotations

from pathlib import Path

from scripts.knowledge.classify_keyword import KEYWORD_COLUMNS
from scripts.knowledge.keyword_store import (
    get_all_keywords,
    get_keywords_for_file,
    parse_args,
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
        csv_path.write_text(
            f"{header}\n"
            "kw-1,FastAPI,domain,web,cand-1,docs/test.yml,2024-01-01,notes1\n"
            "kw-2,Pydantic,domain,validation,cand-2,docs/other.yml,2024-01-01,notes2\n"
        )

        result = get_keywords_for_file(csv_path, "docs/test.yml")
        assert len(result) == 1
        assert result[0]["term"] == "FastAPI"

    def test_returns_empty_for_no_match(self, tmp_path: Path) -> None:
        """Should return empty list when no keywords match."""
        csv_path = tmp_path / "keywords.csv"
        header = ",".join(KEYWORD_COLUMNS)
        csv_path.write_text(
            f"{header}\nkw-1,FastAPI,domain,web,cand-1,docs/test.yml,2024-01-01,notes1\n"
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
            "kw-1,FastAPI,domain,web,cand-1,docs/test.yml,2024-01-01,notes1\n"
            "kw-2,Pydantic,domain,validation,cand-2,docs/other.yml,2024-01-01,notes2\n"
        )

        result = get_all_keywords(csv_path)
        assert len(result) == 2


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.target == Path("docs")
        assert args.dry_run is False
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_target(self) -> None:
        """Should parse --target argument."""
        args = parse_args(["--target", "custom/docs"])
        assert args.target == Path("custom/docs")

    def test_dry_run(self) -> None:
        """Should parse --dry-run flag."""
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")
