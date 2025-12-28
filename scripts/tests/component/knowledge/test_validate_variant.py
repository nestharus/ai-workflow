import argparse
from pathlib import Path

import pytest

from scripts.knowledge.validate_variant import (
    get_variant_by_id,
    main,
    parse_args,
    update_variant_validation,
    validate_variant_main,
)
from scripts.knowledge.variant_resolver import VARIANT_COLUMNS


class TestGetVariantById:
    def test_returns_none_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return None when CSV doesn't exist."""
        csv_path = tmp_path / "variant_candidates.csv"
        result = get_variant_by_id(csv_path, "pair-1")
        assert result is None

    def test_returns_none_for_missing_variant(self, tmp_path: Path) -> None:
        """Should return None when variant pair not found."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.9,,,,\n")

        result = get_variant_by_id(csv_path, "pair-999")
        assert result is None

    def test_returns_variant(self, tmp_path: Path) -> None:
        """Should return variant pair when found."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.9,,,,\n")

        result = get_variant_by_id(csv_path, "pair-1")
        assert result is not None
        assert result["pair_id"] == "pair-1"
        assert result["keyword_a"] == "API"
        assert result["keyword_b"] == "Application Programming Interface"


class TestUpdateVariantValidation:
    def test_returns_false_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        csv_path = tmp_path / "variant_candidates.csv"
        result = update_variant_validation(
            csv_path, "pair-1", merge="true", canonical="API", reason="test"
        )
        assert result is False

    def test_updates_merge_decision(self, tmp_path: Path) -> None:
        """Should update merge, canonical, reason, and validated fields."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.9,,,,\n")

        result = update_variant_validation(
            csv_path,
            "pair-1",
            merge="true",
            canonical="API",
            reason="Abbreviation; API more common.",
        )
        assert result is True

        content = csv_path.read_text()
        assert "true" in content
        assert "API" in content
        assert "Abbreviation" in content

    def test_updates_reject_decision(self, tmp_path: Path) -> None:
        """Should update merge=false decision."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,auth,authz,0.85,,,,\n")

        result = update_variant_validation(
            csv_path,
            "pair-1",
            merge="false",
            canonical="",
            reason="Different concepts: authentication vs authorization.",
        )
        assert result is True

        content = csv_path.read_text()
        assert "false" in content
        assert "Different concepts" in content


class TestParseArgs:
    def test_requires_id(self) -> None:
        """Should require --id argument."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_requires_merge(self) -> None:
        """Should require --merge argument."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "pair-1"])

    def test_requires_canonical(self) -> None:
        """Should require --canonical argument."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "pair-1", "--merge", "true"])

    def test_requires_reason(self) -> None:
        """Should require --reason argument."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "pair-1", "--merge", "true", "--canonical", "API"])

    def test_merge_choices(self) -> None:
        """Should only accept true or false for --merge."""
        with pytest.raises(SystemExit):
            parse_args(
                [
                    "--id",
                    "pair-1",
                    "--merge",
                    "maybe",
                    "--canonical",
                    "API",
                    "--reason",
                    "test",
                ]
            )

    def test_merge_true(self) -> None:
        """Should parse --merge true."""
        args = parse_args(
            [
                "--id",
                "pair-1",
                "--merge",
                "true",
                "--canonical",
                "API",
                "--reason",
                "Abbreviation",
            ]
        )
        assert args.pair_id == "pair-1"
        assert args.merge == "true"
        assert args.canonical == "API"
        assert args.reason == "Abbreviation"

    def test_merge_false(self) -> None:
        """Should parse --merge false."""
        args = parse_args(
            [
                "--id",
                "pair-1",
                "--merge",
                "false",
                "--canonical",
                "",
                "--reason",
                "Different concepts",
            ]
        )
        assert args.merge == "false"
        assert args.canonical == ""

    def test_default_knowledge_path(self) -> None:
        """Should have default knowledge path."""
        args = parse_args(
            [
                "--id",
                "pair-1",
                "--merge",
                "true",
                "--canonical",
                "API",
                "--reason",
                "test",
            ]
        )
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(
            [
                "--id",
                "pair-1",
                "--merge",
                "true",
                "--canonical",
                "API",
                "--reason",
                "test",
                "--knowledge-path",
                "custom/.knowledge",
            ]
        )
        assert args.knowledge_path == Path("custom/.knowledge")


class TestValidationWorkflow:
    def test_merge_workflow(self, tmp_path: Path) -> None:
        """Should complete merge workflow correctly."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.92,,,,\n")

        # Validate with merge=true
        result = update_variant_validation(
            csv_path,
            "pair-1",
            merge="true",
            canonical="API",
            reason="Abbreviation more common in codebase.",
        )
        assert result is True

        # Verify the record was updated
        variant = get_variant_by_id(csv_path, "pair-1")
        assert variant is not None
        assert variant["merge"] == "true"
        assert variant["canonical"] == "API"
        assert variant["reason"] == "Abbreviation more common in codebase."
        assert variant["validated"] == "true"

    def test_reject_workflow(self, tmp_path: Path) -> None:
        """Should complete reject workflow correctly."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,authentication,authorization,0.88,,,,\n")

        # Validate with merge=false
        result = update_variant_validation(
            csv_path,
            "pair-1",
            merge="false",
            canonical="",
            reason="Distinct security concepts.",
        )
        assert result is True

        # Verify the record was updated
        variant = get_variant_by_id(csv_path, "pair-1")
        assert variant is not None
        assert variant["merge"] == "false"
        assert variant["canonical"] == ""
        assert variant["reason"] == "Distinct security concepts."
        assert variant["validated"] == "true"

    def test_multiple_validations(self, tmp_path: Path) -> None:
        """Should handle multiple validations correctly."""
        csv_path = tmp_path / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(
            f"{header}\n"
            "pair-1,API,Application Programming Interface,0.92,,,,\n"
            "pair-2,auth,authz,0.85,,,,\n"
        )

        # Validate first pair (merge)
        update_variant_validation(
            csv_path, "pair-1", merge="true", canonical="API", reason="Abbreviation"
        )

        # Validate second pair (no merge)
        update_variant_validation(
            csv_path, "pair-2", merge="false", canonical="", reason="Different concepts"
        )

        # Verify both records
        variant1 = get_variant_by_id(csv_path, "pair-1")
        variant2 = get_variant_by_id(csv_path, "pair-2")

        assert variant1 is not None
        assert variant1["merge"] == "true"
        assert variant1["validated"] == "true"

        assert variant2 is not None
        assert variant2["merge"] == "false"
        assert variant2["validated"] == "true"


class TestValidateVariantMain:
    def test_returns_one_for_missing_csv(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when variants CSV doesn't exist.

        This covers lines 177-179 where CSV not found.
        """
        args = argparse.Namespace(
            knowledge_path=tmp_path,  # No keywords directory
            pair_id="pair-1",
            merge="true",
            canonical="API",
            reason="Test reason",
        )

        result = validate_variant_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_handles_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge path correctly.

        This covers lines 170-171 (then branch) where path.is_absolute() is True.
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
            pair_id="pair-1",
            merge="true",
            canonical="API",
            reason="Abbreviation common",
        )

        result = validate_variant_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Validated pair 'pair-1'" in captured.out

    def test_returns_one_for_missing_pair(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when pair ID not found.

        This covers lines 181-184 where variant is not found.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.95,,,,\n")

        args = argparse.Namespace(
            knowledge_path=tmp_path.resolve(),
            pair_id="pair-999",  # Non-existent pair
            merge="true",
            canonical="API",
            reason="Test",
        )

        result = validate_variant_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_successful_merge_validation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should successfully validate with merge=true and show output.

        This covers lines 186-201 success path.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.95,,,,\n")

        args = argparse.Namespace(
            knowledge_path=tmp_path.resolve(),
            pair_id="pair-1",
            merge="true",
            canonical="API",
            reason="Abbreviation is more common",
        )

        result = validate_variant_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Validated pair 'pair-1'" in captured.out
        assert "Keywords: 'API' / 'Application Programming Interface'" in captured.out
        assert "Merge: true" in captured.out
        assert "Canonical: 'API'" in captured.out
        assert "Reason: Abbreviation is more common" in captured.out

    def test_successful_reject_validation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should successfully validate with merge=false.

        This covers the else branch at line 198 where merge != 'true'.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,auth,authz,0.85,,,,\n")

        args = argparse.Namespace(
            knowledge_path=tmp_path.resolve(),
            pair_id="pair-1",
            merge="false",
            canonical="",
            reason="Different security concepts",
        )

        result = validate_variant_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Validated pair 'pair-1'" in captured.out
        assert "Merge: false" in captured.out
        # Should NOT show Canonical line when merge is false
        assert "Canonical:" not in captured.out
        assert "Reason: Different security concepts" in captured.out
