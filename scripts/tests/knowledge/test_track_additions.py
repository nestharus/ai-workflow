"""Tests for scripts/knowledge/track_additions.py."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.knowledge import track_additions


class TestTrackAdditionsMain:
    """Tests for track_additions_main() function."""

    def test_track_additions_main_knowledge_path_not_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test track_additions_main() when knowledge path doesn't exist."""
        args = argparse.Namespace(
            pattern=None,
            knowledge_path=tmp_path / "nonexistent",
        )

        result = track_additions.track_additions_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Knowledge directory not found" in captured.err

    def test_track_additions_main_no_comparison_csvs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test track_additions_main() when no comparison CSVs exist."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        args = argparse.Namespace(
            pattern=None,
            knowledge_path=knowledge_path,
        )

        result = track_additions.track_additions_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_track_additions_main_comparison_query_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test track_additions_main() when comparison query fails."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        comparisons_dir = knowledge_path / "comparisons"
        comparisons_dir.mkdir()

        # Create an invalid CSV that will cause a query error
        (comparisons_dir / "test.csv").write_text("invalid csv content\nno,valid,columns")

        args = argparse.Namespace(
            pattern=None,
            knowledge_path=knowledge_path,
        )

        with patch.object(track_additions, "query_split_only_additions") as mock_query:
            mock_query.side_effect = track_additions.ComparisonQueryError(
                [comparisons_dir / "test.csv"]
            )
            result = track_additions.track_additions_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Could not read comparison CSVs" in captured.err

    def test_track_additions_main_no_additions_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test track_additions_main() when no additions are found."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        comparisons_dir = knowledge_path / "comparisons"
        comparisons_dir.mkdir()

        # Create a valid CSV with no split_only entries
        (comparisons_dir / "test.csv").write_text(
            "id,source_file,original_text,origin_type\ntest-id,test.yml,content,original_only\n"
        )

        args = argparse.Namespace(
            pattern=None,
            knowledge_path=knowledge_path,
        )

        result = track_additions.track_additions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No additions (split_only entries) found" in captured.out

    def test_track_additions_main_with_additions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test track_additions_main() successfully tracking additions."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        comparisons_dir = knowledge_path / "comparisons"
        comparisons_dir.mkdir()

        # Create a valid CSV with split_only entries
        (comparisons_dir / "test.csv").write_text(
            "id,source_file,original_text,origin_type\n"
            "new-element,target.yml,New content,split_only\n"
        )

        args = argparse.Namespace(
            pattern=None,
            knowledge_path=knowledge_path,
        )

        result = track_additions.track_additions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "tracked" in captured.out

    def test_track_additions_main_with_failed_paths_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test track_additions_main() warns about partial failures."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        comparisons_dir = knowledge_path / "comparisons"
        comparisons_dir.mkdir()

        args = argparse.Namespace(
            pattern=None,
            knowledge_path=knowledge_path,
        )

        with patch.object(track_additions, "query_split_only_additions") as mock_query:
            # Return results with some failed paths
            mock_query.return_value = (
                {
                    "test": [
                        {"element_id": "elem1", "target_file": "file.yml", "added_text": "text"}
                    ]
                },
                [comparisons_dir / "failed.csv"],  # One failed path
            )
            with patch.object(track_additions, "ensure_csv_exists"), patch.object(
                track_additions, "is_already_tracked", return_value=False
            ), patch.object(track_additions, "append_addition"):
                result = track_additions.track_additions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Failed to query" in captured.err

    def test_track_additions_main_branch_with_tracked_and_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test track_additions_main() handles both tracked and skipped additions (lines 345-349)."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        args = argparse.Namespace(
            pattern=None,
            knowledge_path=knowledge_path,
        )

        # Pattern with both tracked and skipped items
        pattern_additions = [
            {"element_id": "elem1", "target_file": "file1.yml", "added_text": "text1"},
            {"element_id": "elem2", "target_file": "file2.yml", "added_text": "text2"},
        ]

        call_count = [0]

        def mock_is_tracked(csv_path: Path, element_id: str, target_file: str) -> bool:
            call_count[0] += 1
            return call_count[0] == 1  # First is already tracked, second is new

        with patch.object(track_additions, "query_split_only_additions") as mock_query:
            mock_query.return_value = (
                {"pattern1": pattern_additions},
                [],  # No failed paths
            )
            with patch.object(track_additions, "ensure_csv_exists"), patch.object(
                track_additions, "is_already_tracked", side_effect=mock_is_tracked
            ), patch.object(track_additions, "append_addition"):
                result = track_additions.track_additions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        # Should show "1 tracked, 1 skipped"
        assert "tracked" in captured.out and "skipped" in captured.out

    def test_track_additions_main_branch_zero_tracked_zero_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test track_additions_main() when pattern has 0 tracked and 0 skipped (branch 345,349)."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        args = argparse.Namespace(
            pattern=None,
            knowledge_path=knowledge_path,
        )

        with patch.object(track_additions, "query_split_only_additions") as mock_query:
            # Return empty results for a pattern
            mock_query.return_value = (
                {"pattern1": []},  # Empty list - nothing to track or skip
                [],
            )
            result = track_additions.track_additions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        # Should show total: 0 tracked, 0 skipped but NOT the pattern line
        assert "Total: 0 additions tracked, 0 skipped" in captured.out
        # The pattern line should NOT be printed because neither tracked > 0 nor skipped > 0
        assert "pattern1:" not in captured.out


class TestQuerySplitOnlyAdditions:
    """Tests for query_split_only_additions() function."""

    def test_query_all_files_fail(self, tmp_path: Path) -> None:
        """Test ComparisonQueryError raised when all files fail."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        comparisons_dir = knowledge_path / "comparisons"
        comparisons_dir.mkdir()

        # Create an invalid CSV
        bad_csv = comparisons_dir / "bad.csv"
        bad_csv.write_text("invalid content")

        with pytest.raises(track_additions.ComparisonQueryError):
            track_additions.query_split_only_additions(knowledge_path)


class TestValidateAdditionMain:
    """Tests for validate_addition_main() function."""

    def test_validate_addition_main_csv_not_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test validate_addition_main() when additions CSV doesn't exist (lines 379-381)."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        args = argparse.Namespace(
            id="test-id",
            validated=True,
            in_scope=False,
            meaningful=False,
            knowledge_path=knowledge_path,
        )

        result = track_additions.validate_addition_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Additions CSV not found" in captured.err

    def test_validate_addition_main_with_absolute_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test validate_addition_main() with absolute knowledge_path (lines 372-373)."""
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

        args = argparse.Namespace(
            id="test-uuid",
            validated=True,
            in_scope=True,
            meaningful=True,
            knowledge_path=knowledge_path.resolve(),  # Use absolute path
        )

        result = track_additions.validate_addition_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Updated addition" in captured.out

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

    def test_validate_addition_main_id_not_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test validate_addition_main() when addition ID doesn't exist (lines 395-397)."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        additions_dir = knowledge_path / "additions"
        additions_dir.mkdir()

        # Create additions CSV with a different record
        additions_csv = additions_dir / "additions.csv"
        additions_csv.write_text(
            "addition_id,element_id,target_file,added_text,detected_at,validated,in_scope,meaningful\n"
            "other-uuid,elem1,file.yml,text,20240101T120000Z,false,false,false\n"
        )

        args = argparse.Namespace(
            id="nonexistent-id",
            validated=True,
            in_scope=False,
            meaningful=False,
            knowledge_path=knowledge_path,
        )

        result = track_additions.validate_addition_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_validate_addition_main_update_all_flags(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test validate_addition_main() updating all validation flags (lines 402-410)."""
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

        args = argparse.Namespace(
            id="test-uuid",
            validated=True,
            in_scope=True,
            meaningful=True,
            knowledge_path=knowledge_path,
        )

        result = track_additions.validate_addition_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Updated addition 'test-uuid'" in captured.out
        assert "validated: true" in captured.out
        assert "in_scope: true" in captured.out
        assert "meaningful: true" in captured.out

    def test_validate_addition_main_no_updates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test validate_addition_main() with no flags set (line 412 branch - update_parts empty)."""
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

        args = argparse.Namespace(
            id="test-uuid",
            validated=False,
            in_scope=False,
            meaningful=False,
            knowledge_path=knowledge_path,
        )

        result = track_additions.validate_addition_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Updated addition 'test-uuid'" in captured.out
        # Should still show the current values (unchanged)
        assert "validated: false" in captured.out


class TestParseTrackArgs:
    """Tests for parse_track_args() function."""

    def test_parse_track_args_default(self) -> None:
        """Test parse_track_args() with no arguments (lines 447-460)."""
        args = track_additions.parse_track_args([])

        assert args.pattern is None
        assert args.knowledge_path == Path(".knowledge")

    def test_parse_track_args_with_pattern(self) -> None:
        """Test parse_track_args() with --pattern argument (lines 450-452)."""
        args = track_additions.parse_track_args(["--pattern", "api-patterns"])

        assert args.pattern == "api-patterns"
        assert args.knowledge_path == Path(".knowledge")

    def test_parse_track_args_with_knowledge_path(self) -> None:
        """Test parse_track_args() with --knowledge-path argument (lines 454-459)."""
        args = track_additions.parse_track_args(["--knowledge-path", "/custom/path"])

        assert args.pattern is None
        assert args.knowledge_path == Path("/custom/path")

    def test_parse_track_args_with_all_options(self) -> None:
        """Test parse_track_args() with all arguments."""
        args = track_additions.parse_track_args(
            [
                "--pattern",
                "test-pattern",
                "--knowledge-path",
                "/custom/knowledge",
            ]
        )

        assert args.pattern == "test-pattern"
        assert args.knowledge_path == Path("/custom/knowledge")


class TestParseValidateArgs:
    """Tests for parse_validate_args() function."""

    def test_parse_validate_args_required_id(self) -> None:
        """Test parse_validate_args() with only required --id (lines 472-502)."""
        args = track_additions.parse_validate_args(["--id", "test-uuid"])

        assert args.id == "test-uuid"
        assert args.validated is False
        assert args.in_scope is False
        assert args.meaningful is False
        assert args.knowledge_path == Path(".knowledge")

    def test_parse_validate_args_with_validated(self) -> None:
        """Test parse_validate_args() with --validated flag (lines 480-483)."""
        args = track_additions.parse_validate_args(["--id", "test-uuid", "--validated"])

        assert args.id == "test-uuid"
        assert args.validated is True

    def test_parse_validate_args_with_in_scope(self) -> None:
        """Test parse_validate_args() with --in-scope flag (lines 485-489)."""
        args = track_additions.parse_validate_args(["--id", "test-uuid", "--in-scope"])

        assert args.id == "test-uuid"
        assert args.in_scope is True

    def test_parse_validate_args_with_meaningful(self) -> None:
        """Test parse_validate_args() with --meaningful flag (lines 491-494)."""
        args = track_additions.parse_validate_args(["--id", "test-uuid", "--meaningful"])

        assert args.id == "test-uuid"
        assert args.meaningful is True

    def test_parse_validate_args_with_knowledge_path(self) -> None:
        """Test parse_validate_args() with --knowledge-path (lines 496-500)."""
        args = track_additions.parse_validate_args(
            ["--id", "test-uuid", "--knowledge-path", "/custom/path"]
        )

        assert args.id == "test-uuid"
        assert args.knowledge_path == Path("/custom/path")

    def test_parse_validate_args_with_all_flags(self) -> None:
        """Test parse_validate_args() with all optional flags."""
        args = track_additions.parse_validate_args(
            [
                "--id",
                "test-uuid",
                "--validated",
                "--in-scope",
                "--meaningful",
                "--knowledge-path",
                "/custom/path",
            ]
        )

        assert args.id == "test-uuid"
        assert args.validated is True
        assert args.in_scope is True
        assert args.meaningful is True
        assert args.knowledge_path == Path("/custom/path")


class TestMainEntryPoints:
    """Tests for main_track() and main_validate() entry points."""

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


class TestIsAlreadyTracked:
    """Tests for is_already_tracked() function."""

    def test_is_already_tracked_csv_empty(self, tmp_path: Path) -> None:
        """Test is_already_tracked() returns False when CSV is empty (line 132)."""
        csv_path = tmp_path / "additions.csv"
        csv_path.write_text("")  # Empty file

        result = track_additions.is_already_tracked(csv_path, "elem1", "file.yml")

        assert result is False

    def test_is_already_tracked_csv_not_exists(self, tmp_path: Path) -> None:
        """Test is_already_tracked() returns False when CSV doesn't exist (line 131)."""
        csv_path = tmp_path / "nonexistent.csv"

        result = track_additions.is_already_tracked(csv_path, "elem1", "file.yml")

        assert result is False

    def test_is_already_tracked_duckdb_error(self, tmp_path: Path) -> None:
        """Test is_already_tracked() returns False on DuckDB error (lines 146-147)."""
        csv_path = tmp_path / "invalid.csv"
        csv_path.write_text("invalid,csv,content\nno,matching,columns")

        result = track_additions.is_already_tracked(csv_path, "elem1", "file.yml")

        assert result is False

    def test_is_already_tracked_found(self, tmp_path: Path) -> None:
        """Test is_already_tracked() returns True when record exists."""
        csv_path = tmp_path / "additions.csv"
        csv_path.write_text(
            "addition_id,element_id,target_file,added_text,detected_at,validated,in_scope,meaningful\n"
            "uuid1,elem1,file.yml,text,20240101T120000Z,false,false,false\n"
        )

        result = track_additions.is_already_tracked(csv_path, "elem1", "file.yml")

        assert result is True

    def test_is_already_tracked_not_found(self, tmp_path: Path) -> None:
        """Test is_already_tracked() returns False when record doesn't exist."""
        csv_path = tmp_path / "additions.csv"
        csv_path.write_text(
            "addition_id,element_id,target_file,added_text,detected_at,validated,in_scope,meaningful\n"
            "uuid1,elem1,file.yml,text,20240101T120000Z,false,false,false\n"
        )

        result = track_additions.is_already_tracked(csv_path, "other-elem", "other-file.yml")

        assert result is False


class TestGetComparisonCsvPaths:
    """Tests for get_comparison_csv_paths() function."""

    def test_get_comparison_csv_paths_with_pattern_exists(self, tmp_path: Path) -> None:
        """Test get_comparison_csv_paths() with specific pattern that exists (lines 168-169)."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        comparisons_dir = knowledge_path / "comparisons"
        comparisons_dir.mkdir()

        # Create the specific pattern CSV
        pattern_csv = comparisons_dir / "api-patterns.csv"
        pattern_csv.write_text("id,source_file,original_text,origin_type\n")

        result = track_additions.get_comparison_csv_paths(knowledge_path, pattern="api-patterns")

        assert len(result) == 1
        assert result[0] == pattern_csv

    def test_get_comparison_csv_paths_with_pattern_not_exists(self, tmp_path: Path) -> None:
        """Test get_comparison_csv_paths() with specific pattern that doesn't exist (line 169)."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        comparisons_dir = knowledge_path / "comparisons"
        comparisons_dir.mkdir()

        result = track_additions.get_comparison_csv_paths(knowledge_path, pattern="nonexistent")

        assert result == []

    def test_get_comparison_csv_paths_no_comparisons_dir(self, tmp_path: Path) -> None:
        """Test get_comparison_csv_paths() when comparisons directory doesn't exist."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        # Don't create comparisons directory

        result = track_additions.get_comparison_csv_paths(knowledge_path)

        assert result == []

    def test_get_comparison_csv_paths_all_csvs(self, tmp_path: Path) -> None:
        """Test get_comparison_csv_paths() returns all CSVs when no pattern specified."""
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        comparisons_dir = knowledge_path / "comparisons"
        comparisons_dir.mkdir()

        # Create multiple CSV files
        (comparisons_dir / "pattern1.csv").write_text("id\n")
        (comparisons_dir / "pattern2.csv").write_text("id\n")

        result = track_additions.get_comparison_csv_paths(knowledge_path)

        assert len(result) == 2
