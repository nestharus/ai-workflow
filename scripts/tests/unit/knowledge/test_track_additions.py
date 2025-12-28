import argparse
from pathlib import Path

import pytest

from scripts.knowledge import track_additions


class TestValidateAdditionMain:
    def test_validate_addition_main_with_relative_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test validate_addition_main() with relative knowledge_path (line 375)."""
        # Create knowledge directory structure
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        additions_dir = knowledge_path / "additions"
        additions_dir.mkdir()

        # Create additions CSV with a record
        additions_csv = additions_dir / "additions.csv"
        additions_csv.write_text(
            "addition_id,element_id,target_file,added_text,detected_at,validated,in_scope,meaningful\n"
            "test-uuid,elem1,file.yml,text,20240101T120000Z,false,false,false\n"
        )

        # Mock REPO_ROOT to be the tmp_path
        monkeypatch.setattr(track_additions, "REPO_ROOT", tmp_path)

        args = argparse.Namespace(
            id="test-uuid",
            validated=True,
            in_scope=False,
            meaningful=False,
            knowledge_path=Path(".knowledge"),  # Relative path
        )

        result = track_additions.validate_addition_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Updated addition" in captured.out


class TestMainEntryPoints:
    def test_main_track_calls_parse_and_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test main_track() parses args and calls track_additions_main (lines 511-512)."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        comparisons_dir = knowledge_path / "comparisons"
        comparisons_dir.mkdir()

        # Create a valid CSV with no split_only entries
        (comparisons_dir / "test.csv").write_text("id,source_file,original_text,origin_type\n")

        # Mock sys.argv for parse_track_args
        monkeypatch.setattr(
            "sys.argv", ["track-additions", "--knowledge-path", str(knowledge_path)]
        )

        result = track_additions.main_track()

        assert result == 0

    def test_main_validate_calls_parse_and_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main_validate() parses args and calls validate_addition_main (lines 521-522)."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        additions_dir = knowledge_path / "additions"
        additions_dir.mkdir()

        # Create additions CSV with a record
        additions_csv = additions_dir / "additions.csv"
        additions_csv.write_text(
            "addition_id,element_id,target_file,added_text,detected_at,validated,in_scope,meaningful\n"
            "test-uuid,elem1,file.yml,text,20240101T120000Z,false,false,false\n"
        )

        # Mock sys.argv for parse_validate_args
        monkeypatch.setattr(
            "sys.argv",
            [
                "validate-addition",
                "--id",
                "test-uuid",
                "--validated",
                "--knowledge-path",
                str(knowledge_path),
            ],
        )

        result = track_additions.main_validate()

        assert result == 0
        captured = capsys.readouterr()
        assert "Updated addition" in captured.out
