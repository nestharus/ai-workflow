"""Tests for scripts.knowledge.keyword_schema module."""

from __future__ import annotations

from scripts.knowledge.keyword_schema import KEYWORD_COLUMNS, make_empty_keyword_row


class TestKeywordColumns:
    """Tests for KEYWORD_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "keyword" in KEYWORD_COLUMNS
        assert "source_file" in KEYWORD_COLUMNS
        assert "element_id" in KEYWORD_COLUMNS
        assert "snippet" in KEYWORD_COLUMNS
        assert "first_detected" in KEYWORD_COLUMNS
        assert "last_updated" in KEYWORD_COLUMNS

    def test_column_count(self) -> None:
        """Should have exactly 6 columns."""
        assert len(KEYWORD_COLUMNS) == 6


class TestMakeEmptyKeywordRow:
    """Tests for make_empty_keyword_row function."""

    def test_returns_dict_with_all_columns(self) -> None:
        """Should return dict with all KEYWORD_COLUMNS keys."""
        row = make_empty_keyword_row()

        for col in KEYWORD_COLUMNS:
            assert col in row

    def test_all_values_are_empty_strings(self) -> None:
        """Should set all values to empty strings (covers line 32)."""
        row = make_empty_keyword_row()

        for col in KEYWORD_COLUMNS:
            assert row[col] == ""

    def test_returns_new_dict_each_call(self) -> None:
        """Should return a new dict each call (not shared)."""
        row1 = make_empty_keyword_row()
        row2 = make_empty_keyword_row()

        assert row1 is not row2

        # Modifying one should not affect the other
        row1["keyword"] = "test"
        assert row2["keyword"] == ""
