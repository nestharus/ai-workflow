import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.knowledge.validate_variant import (
    get_variant_by_id,
    main,
    parse_args,
    update_variant_validation,
    validate_variant_main,
)
from scripts.knowledge.variant_resolver import VARIANT_COLUMNS


class TestValidateVariantMain:
    def test_handles_relative_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should resolve relative knowledge path against REPO_ROOT.

        This covers lines 172-173 (else branch) where path is relative.
        """
        keywords_dir = tmp_path / ".knowledge" / "keywords"
        keywords_dir.mkdir(parents=True)
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.95,,,,\n")

        with patch("scripts.knowledge.validate_variant.REPO_ROOT", tmp_path):
            args = argparse.Namespace(
                knowledge_path=Path(".knowledge"),  # Relative path
                pair_id="pair-1",
                merge="true",
                canonical="API",
                reason="Abbreviation common",
            )

            result = validate_variant_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Validated pair 'pair-1'" in captured.out

    def test_returns_one_on_update_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when update fails.

        This covers lines 203-204 where update_variant_validation returns False.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.95,,,,\n")

        with patch(
            "scripts.knowledge.validate_variant.update_variant_validation", return_value=False
        ):
            args = argparse.Namespace(
                knowledge_path=tmp_path.resolve(),
                pair_id="pair-1",
                merge="true",
                canonical="API",
                reason="Test",
            )

            result = validate_variant_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Failed to update" in captured.err


class TestMainFunction:
    def test_main_calls_validate_variant_main(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should parse args and call validate_variant_main.

        This covers lines 213-214.
        """
        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        csv_path = keywords_dir / "variant_candidates.csv"
        header = ",".join(VARIANT_COLUMNS)
        csv_path.write_text(f"{header}\npair-1,API,Application Programming Interface,0.95,,,,\n")

        with patch(
            "sys.argv",
            [
                "script",
                "--id",
                "pair-1",
                "--merge",
                "true",
                "--canonical",
                "API",
                "--reason",
                "Abbreviation",
                "--knowledge-path",
                str(tmp_path),
            ],
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Validated pair 'pair-1'" in captured.out
