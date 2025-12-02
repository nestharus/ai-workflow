"""Tests for scripts.knowledge.validate_variant module."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.knowledge.validate_variant import (
    delete_variant,
    get_variant_by_id,
    parse_args,
    update_variant_validation,
)
from scripts.knowledge.variant_resolver import VARIANT_COLUMNS


class TestGetVariantById:
    """Tests for get_variant_by_id function."""

    def test_returns_none_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return None when CSV doesn't exist."""
        csv_path = tmp_path / "variant_candidates.csv"
        result = get_variant_by_id(csv_path, "var-1")
        assert result is None

    def test_returns_none_for_missing_variant(self, tmp_path: Path) -> None:
        """Should return None when variant not found."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\nvar-1,kw-1,API,0.9,file.yml,2024-01-01,false,false\n")

        result = get_variant_by_id(csv_path, "var-999")
        assert result is None

    def test_returns_variant(self, tmp_path: Path) -> None:
        """Should return variant when found."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\nvar-1,kw-1,API,0.9,file.yml,2024-01-01,false,false\n")

        result = get_variant_by_id(csv_path, "var-1")
        assert result is not None
        assert result["variant_id"] == "var-1"
        assert result["variant_term"] == "API"


class TestUpdateVariantValidation:
    """Tests for update_variant_validation function."""

    def test_returns_false_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        csv_path = tmp_path / "variant_candidates.csv"
        result = update_variant_validation(csv_path, "var-1", validated=True)
        assert result is False

    def test_updates_validation_status(self, tmp_path: Path) -> None:
        """Should update validated field."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\nvar-1,kw-1,API,0.9,file.yml,2024-01-01,false,false\n")

        result = update_variant_validation(csv_path, "var-1", validated=True)
        assert result is True

        content = csv_path.read_text()
        assert "true" in content

    def test_updates_canonical_status(self, tmp_path: Path) -> None:
        """Should update is_canonical field."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\nvar-1,kw-1,API,0.9,file.yml,2024-01-01,false,false\n")

        result = update_variant_validation(csv_path, "var-1", validated=True, is_canonical=True)
        assert result is True

        content = csv_path.read_text()
        # Both validated and is_canonical should be true
        assert content.count("true") >= 2


class TestDeleteVariant:
    """Tests for delete_variant function."""

    def test_returns_false_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        csv_path = tmp_path / "variant_candidates.csv"
        result = delete_variant(csv_path, "var-1")
        assert result is False

    def test_deletes_variant(self, tmp_path: Path) -> None:
        """Should delete variant from CSV."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "var-1,kw-1,API,0.9,file.yml,2024-01-01,false,false\n"
            "var-2,kw-1,api,0.85,file.yml,2024-01-01,false,false\n"
        )

        result = delete_variant(csv_path, "var-1")
        assert result is True

        content = csv_path.read_text()
        assert "var-1" not in content
        assert "var-2" in content


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_id(self) -> None:
        """Should require --id argument."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_requires_accept_or_reject(self) -> None:
        """Should require --accept or --reject."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "var-1"])

    def test_accept_and_reject_mutually_exclusive(self) -> None:
        """Should not allow both --accept and --reject."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "var-1", "--accept", "--reject"])

    def test_accept_flag(self) -> None:
        """Should parse --accept flag."""
        args = parse_args(["--id", "var-1", "--accept"])
        assert args.variant_id == "var-1"
        assert args.accept is True
        assert args.reject is False

    def test_reject_flag(self) -> None:
        """Should parse --reject flag."""
        args = parse_args(["--id", "var-1", "--reject"])
        assert args.variant_id == "var-1"
        assert args.accept is False
        assert args.reject is True

    def test_canonical_flag(self) -> None:
        """Should parse --canonical flag."""
        args = parse_args(["--id", "var-1", "--accept", "--canonical"])
        assert args.canonical is True

    def test_default_knowledge_path(self) -> None:
        """Should have default knowledge path."""
        args = parse_args(["--id", "var-1", "--accept"])
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--id", "var-1", "--accept", "--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")
