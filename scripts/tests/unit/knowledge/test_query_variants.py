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


class TestQueryVariantsMain:
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


class TestMain:
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
