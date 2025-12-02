"""Tests for scripts.knowledge.variant_resolver module."""

from __future__ import annotations

from pathlib import Path

from scripts.knowledge.variant_resolver import (
    VARIANT_COLUMNS,
    VariantRecord,
    append_variant,
    ensure_variants_csv_exists,
    is_variant_tracked,
    parse_args,
)


class TestVariantColumns:
    """Tests for VARIANT_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "variant_id" in VARIANT_COLUMNS
        assert "keyword_id" in VARIANT_COLUMNS
        assert "variant_term" in VARIANT_COLUMNS
        assert "similarity_score" in VARIANT_COLUMNS
        assert "source_file" in VARIANT_COLUMNS
        assert "detected_at" in VARIANT_COLUMNS
        assert "validated" in VARIANT_COLUMNS
        assert "is_canonical" in VARIANT_COLUMNS


class TestEnsureVariantsCsvExists:
    """Tests for ensure_variants_csv_exists function."""

    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "keywords" / "variant_candidates.csv"

        ensure_variants_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in VARIANT_COLUMNS:
            assert col in content

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Should not overwrite existing CSV with data."""
        csv_path = tmp_path / "keywords" / "variant_candidates.csv"
        csv_path.parent.mkdir(parents=True)
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\nv1,kw1,term1,0.9,file1,2024-01-01,false,false\n")

        ensure_variants_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "v1" in content
        assert "term1" in content


class TestAppendVariant:
    """Tests for append_variant function."""

    def test_appends_record(self, tmp_path: Path) -> None:
        """Should append variant record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "keywords").mkdir(parents=True)
        csv_path = tmp_path / "keywords" / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\n")

        record = VariantRecord(
            variant_id="var-1",
            keyword_id="kw-1",
            variant_term="API",
            similarity_score="0.92",
            source_file="docs/test.yml",
            detected_at="20240101T120000Z",
            validated="false",
            is_canonical="false",
        )

        append_variant(csv_path, record)

        content = csv_path.read_text()
        assert "var-1" in content
        assert "API" in content


class TestIsVariantTracked:
    """Tests for is_variant_tracked function."""

    def test_returns_false_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        csv_path = tmp_path / "variant_candidates.csv"
        result = is_variant_tracked(csv_path, "kw-1", "API")
        assert result is False

    def test_returns_false_for_missing_variant(self, tmp_path: Path) -> None:
        """Should return False when variant not found."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\nvar-1,kw-1,other,0.9,file.yml,2024-01-01,false,false\n")

        result = is_variant_tracked(csv_path, "kw-1", "API")
        assert result is False

    def test_returns_true_for_existing_variant(self, tmp_path: Path) -> None:
        """Should return True when variant exists."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\nvar-1,kw-1,API,0.9,file.yml,2024-01-01,false,false\n")

        result = is_variant_tracked(csv_path, "kw-1", "API")
        assert result is True


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.keyword_id is None
        assert args.threshold == 0.85
        assert args.model == "Qwen/Qwen3-Embedding-0.6B"
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_keyword_id(self) -> None:
        """Should parse --keyword-id argument."""
        args = parse_args(["--keyword-id", "kw-123"])
        assert args.keyword_id == "kw-123"

    def test_custom_threshold(self) -> None:
        """Should parse --threshold argument."""
        args = parse_args(["--threshold", "0.9"])
        assert args.threshold == 0.9

    def test_custom_model(self) -> None:
        """Should parse --model argument."""
        args = parse_args(["--model", "custom/model"])
        assert args.model == "custom/model"

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")
