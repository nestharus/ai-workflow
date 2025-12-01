"""Tests for scripts.track_additions module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts import track_additions
from scripts.track_additions import (
    CSV_COLUMNS,
    AdditionRecord,
    ComparisonQueryError,
    _get_display_path,
    append_addition,
    ensure_csv_exists,
    get_comparison_csv_paths,
    is_already_tracked,
    main_track,
    main_validate,
    parse_track_args,
    parse_validate_args,
    query_split_only_additions,
    track_additions_main,
    validate_addition_main,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestCsvColumns:
    """Tests for CSV_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "addition_id" in CSV_COLUMNS
        assert "element_id" in CSV_COLUMNS
        assert "target_file" in CSV_COLUMNS
        assert "added_text" in CSV_COLUMNS
        assert "detected_at" in CSV_COLUMNS
        assert "validated" in CSV_COLUMNS
        assert "in_scope" in CSV_COLUMNS
        assert "meaningful" in CSV_COLUMNS


class TestEnsureCsvExists:
    """Tests for ensure_csv_exists function."""

    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "additions" / "additions.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in CSV_COLUMNS:
            assert col in content


class TestAppendAddition:
    """Tests for append_addition function."""

    def test_appends_record(self, tmp_path: Path) -> None:
        """Should append addition record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "additions").mkdir(parents=True)
        csv_path = tmp_path / "additions" / "additions.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        record = AdditionRecord(
            addition_id="add-1",
            element_id="item-1",
            target_file="target.yml",
            added_text="New content",
            detected_at="20240101T120000Z",
            validated="false",
            in_scope="false",
            meaningful="false",
        )

        append_addition(csv_path, record)

        content = csv_path.read_text()
        assert "add-1" in content
        assert "item-1" in content


class TestIsAlreadyTracked:
    """Tests for is_already_tracked function."""

    def test_returns_true_for_existing(self, real_knowledge_path: Path) -> None:
        """Should return True when addition already tracked.

        DuckDB requires real filesystem files.
        """
        csv_path = real_knowledge_path / "additions" / "additions.csv"
        header = ",".join(CSV_COLUMNS)
        row = "add-1,item-1,target.yml,text,20240101T120000Z,false,false,false"
        csv_path.write_text(f"{header}\n{row}\n")

        result = is_already_tracked(csv_path, "item-1", "target.yml")

        assert result is True

    def test_returns_false_for_missing(self, real_knowledge_path: Path) -> None:
        """Should return False when addition not tracked.

        DuckDB requires real filesystem files.
        """
        csv_path = real_knowledge_path / "additions" / "additions.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        result = is_already_tracked(csv_path, "item-1", "target.yml")

        assert result is False

    def test_returns_false_for_missing_file(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        result = is_already_tracked(tmp_path / "nonexistent.csv", "item-1", "target.yml")
        assert result is False


class TestGetComparisonCsvPaths:
    """Tests for get_comparison_csv_paths function."""

    def test_finds_all_csvs(self, fs: FakeFilesystem) -> None:
        """Should find all CSV files in comparisons directory."""
        fs.create_dir("/knowledge/comparisons")
        fs.create_file("/knowledge/comparisons/api-patterns.csv", contents="")
        fs.create_file("/knowledge/comparisons/other-patterns.csv", contents="")

        result = get_comparison_csv_paths(Path("/knowledge"))

        assert len(result) == 2

    def test_filters_by_pattern(self, fs: FakeFilesystem) -> None:
        """Should filter by pattern name."""
        fs.create_dir("/knowledge/comparisons")
        fs.create_file("/knowledge/comparisons/api-patterns.csv", contents="")

        result = get_comparison_csv_paths(Path("/knowledge"), "api-patterns")

        assert len(result) == 1


class TestComparisonQueryError:
    """Tests for ComparisonQueryError exception."""

    def test_includes_failed_paths(self) -> None:
        """Should include failed paths in message."""
        error = ComparisonQueryError([Path("/path1.csv"), Path("/path2.csv")])
        assert "/path1.csv" in str(error)
        assert "/path2.csv" in str(error)


class TestQuerySplitOnlyAdditions:
    """Tests for query_split_only_additions function."""

    def test_raises_for_no_csv_files(self, fs: FakeFilesystem) -> None:
        """Should raise FileNotFoundError when no CSV files exist."""
        fs.create_dir("/knowledge")

        with pytest.raises(FileNotFoundError):
            query_split_only_additions(Path("/knowledge"))

    def test_finds_split_only_entries(self, real_knowledge_path: Path) -> None:
        """Should find entries with origin_type='split_only'.

        DuckDB requires real filesystem files.
        """
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
target.yml,item-1,split_only,new text,,
target.yml,item-2,original,existing,,
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        results, _ = query_split_only_additions(real_knowledge_path)

        assert "test" in results
        assert len(results["test"]) == 1
        assert results["test"][0]["element_id"] == "item-1"


class TestParseTrackArgs:
    """Tests for parse_track_args function."""

    def test_default_values(self) -> None:
        """Should have default values."""
        args = parse_track_args([])

        assert args.pattern is None
        assert args.knowledge_path == Path(".knowledge")

    def test_parses_pattern(self) -> None:
        """Should parse --pattern argument."""
        args = parse_track_args(["--pattern", "api-patterns"])
        assert args.pattern == "api-patterns"


class TestParseValidateArgs:
    """Tests for parse_validate_args function."""

    def test_requires_id(self) -> None:
        """Should require --id argument."""
        with pytest.raises(SystemExit):
            parse_validate_args([])

    def test_parses_id(self) -> None:
        """Should parse --id argument."""
        args = parse_validate_args(["--id", "add-1"])
        assert args.id == "add-1"

    def test_parses_validation_flags(self) -> None:
        """Should parse validation flag arguments."""
        args = parse_validate_args(
            [
                "--id",
                "add-1",
                "--validated",
                "--in-scope",
                "--meaningful",
            ]
        )

        assert args.validated is True
        assert args.in_scope is True
        assert args.meaningful is True


class TestTrackAdditionsMain:
    """Tests for track_additions_main function."""

    def test_returns_one_for_missing_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when knowledge directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"
        args = parse_track_args(["--knowledge-path", str(nonexistent)])

        result = track_additions_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_zero_when_no_additions_found(
        self, real_knowledge_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 with message when no additions found.

        DuckDB requires real filesystem files.
        """
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text,split.yml,text
"""
        csv_path = real_knowledge_path / "comparisons" / "test.csv"
        csv_path.write_text(csv_content)

        args = parse_track_args(["--knowledge-path", str(real_knowledge_path)])
        result = track_additions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No additions" in captured.out


class TestValidateAdditionMain:
    """Tests for validate_addition_main function."""

    def test_returns_one_for_missing_csv(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when additions CSV doesn't exist."""
        with patch.object(track_additions, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            args = parse_validate_args(["--id", "add-1"])
            result = validate_addition_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_missing_addition(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when addition ID not found.

        DuckDB requires real filesystem.
        """
        (tmp_path / ".knowledge" / "additions").mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        csv_path = tmp_path / ".knowledge" / "additions" / "additions.csv"
        csv_path.write_text(f"{header}\n")

        with patch.object(track_additions, "REPO_ROOT", tmp_path):
            args = parse_validate_args(["--id", "nonexistent"])
            result = validate_addition_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_updates_validation_flags(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should update validation flags on success.

        DuckDB requires real filesystem.
        """
        (tmp_path / ".knowledge" / "additions").mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        row = "add-1,item-1,target.yml,text,20240101T120000Z,false,false,false"
        csv_path = tmp_path / ".knowledge" / "additions" / "additions.csv"
        csv_path.write_text(f"{header}\n{row}\n")

        with patch.object(track_additions, "REPO_ROOT", tmp_path):
            args = parse_validate_args(["--id", "add-1", "--validated", "--in-scope"])
            result = validate_addition_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Updated" in captured.out


class TestEnsureCsvExistsExtended:
    """Extended tests for ensure_csv_exists function."""

    def test_skips_header_if_file_has_content(self, tmp_path: Path) -> None:
        """Should not recreate header if file already has content."""
        csv_path = tmp_path / "additions" / "additions.csv"
        csv_path.parent.mkdir(parents=True)
        csv_path.write_text("existing,content\nrow,data\n")

        ensure_csv_exists(csv_path)

        # File should be unchanged
        content = csv_path.read_text()
        assert "existing,content" in content


class TestIsAlreadyTrackedExtended:
    """Extended tests for is_already_tracked function."""

    def test_returns_false_on_duckdb_error(self, tmp_path: Path) -> None:
        """Should return False on DuckDB query error."""
        csv_path = tmp_path / "invalid.csv"
        csv_path.write_text("invalid content without proper csv structure][[")

        result = is_already_tracked(csv_path, "item-1", "target.yml")

        # Should return False on error
        assert result is False


class TestQuerySplitOnlyAdditionsExtended:
    """Extended tests for query_split_only_additions function."""

    def test_raises_comparison_query_error_when_all_fail(self, tmp_path: Path) -> None:
        """Should raise ComparisonQueryError when all files fail to query."""
        (tmp_path / "comparisons").mkdir(parents=True)
        # Create invalid CSV that will fail DuckDB parsing
        (tmp_path / "comparisons" / "test.csv").write_text("invalid[[[content")

        with pytest.raises(ComparisonQueryError):
            query_split_only_additions(tmp_path)

    def test_skips_rows_with_empty_element_id(self, tmp_path: Path) -> None:
        """Should skip rows with empty element_id."""
        (tmp_path / "comparisons").mkdir(parents=True)
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
target.yml,,split_only,new text,,
"""
        (tmp_path / "comparisons" / "test.csv").write_text(csv_content)

        results, _ = query_split_only_additions(tmp_path)

        # Should have no results since element_id is empty
        assert "test" not in results or len(results.get("test", [])) == 0

    def test_skips_rows_with_empty_target_file(self, tmp_path: Path) -> None:
        """Should skip rows with empty target_file."""
        (tmp_path / "comparisons").mkdir(parents=True)
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
,item-1,split_only,new text,,
"""
        (tmp_path / "comparisons" / "test.csv").write_text(csv_content)

        results, _ = query_split_only_additions(tmp_path)

        assert "test" not in results or len(results.get("test", [])) == 0


class TestGetDisplayPath:
    """Tests for _get_display_path function."""

    def test_returns_relative_path(self) -> None:
        """Should return path relative to REPO_ROOT."""
        from scripts.utils import REPO_ROOT

        test_path = REPO_ROOT / "some" / "file.txt"
        result = _get_display_path(test_path)

        assert result == "some/file.txt"

    def test_returns_absolute_path_when_outside_repo(self) -> None:
        """Should return absolute path when outside REPO_ROOT."""
        test_path = Path("/outside/repo/file.txt")
        result = _get_display_path(test_path)

        assert "/outside/repo/file.txt" in result


class TestTrackAdditionsMainExtended:
    """Extended tests for track_additions_main function."""

    def test_handles_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge path."""
        (tmp_path / "comparisons").mkdir(parents=True)
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text,split.yml,text
"""
        (tmp_path / "comparisons" / "test.csv").write_text(csv_content)

        args = parse_track_args(["--knowledge-path", str(tmp_path)])
        result = track_additions_main(args)

        assert result == 0

    def test_returns_one_for_file_not_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when no comparison files found."""
        tmp_path.mkdir(exist_ok=True)

        args = parse_track_args(["--knowledge-path", str(tmp_path)])
        result = track_additions_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err

    def test_tracks_new_additions(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should track new additions from split_only entries."""
        (tmp_path / "comparisons").mkdir(parents=True)
        (tmp_path / "additions").mkdir(parents=True)
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
target.yml,item-1,split_only,new text,,
target.yml,item-2,split_only,more text,,
"""
        (tmp_path / "comparisons" / "test.csv").write_text(csv_content)

        args = parse_track_args(["--knowledge-path", str(tmp_path)])
        result = track_additions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "tracked" in captured.out.lower()

        # Verify CSV was created
        additions_csv = tmp_path / "additions" / "additions.csv"
        assert additions_csv.exists()

    def test_skips_already_tracked_additions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should skip already tracked additions."""
        (tmp_path / "comparisons").mkdir(parents=True)
        (tmp_path / "additions").mkdir(parents=True)

        # Create comparison CSV with split_only entry
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
target.yml,item-1,split_only,new text,,
"""
        (tmp_path / "comparisons" / "test.csv").write_text(csv_content)

        # Pre-create additions CSV with the same item
        header = ",".join(CSV_COLUMNS)
        row = "add-1,item-1,target.yml,text,20240101T120000Z,false,false,false"
        (tmp_path / "additions" / "additions.csv").write_text(f"{header}\n{row}\n")

        args = parse_track_args(["--knowledge-path", str(tmp_path)])
        result = track_additions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "skipped" in captured.out.lower()

    def test_warns_about_partial_failures(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn when some but not all CSVs fail."""
        (tmp_path / "comparisons").mkdir(parents=True)
        (tmp_path / "additions").mkdir(parents=True)

        # Create one valid and one invalid CSV
        valid_content = """source_file,id,origin_type,original_text,split_file,split_text
target.yml,item-1,split_only,new text,,
"""
        (tmp_path / "comparisons" / "valid.csv").write_text(valid_content)
        (tmp_path / "comparisons" / "invalid.csv").write_text("bad[[[content")

        args = parse_track_args(["--knowledge-path", str(tmp_path)])
        result = track_additions_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning" in captured.err or "Failed" in captured.err


class TestValidateAdditionMainExtended:
    """Extended tests for validate_addition_main function."""

    def test_handles_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute knowledge path."""
        (tmp_path / "additions").mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        row = "add-1,item-1,target.yml,text,20240101T120000Z,false,false,false"
        csv_path = tmp_path / "additions" / "additions.csv"
        csv_path.write_text(f"{header}\n{row}\n")

        with patch.object(track_additions, "REPO_ROOT", Path("/different/root")):
            args = parse_validate_args(
                [
                    "--id",
                    "add-1",
                    "--knowledge-path",
                    str(tmp_path),
                ]
            )
            result = validate_addition_main(args)

        assert result == 0

    def test_updates_only_validated_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should update only validated flag when specified alone."""
        (tmp_path / ".knowledge" / "additions").mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        row = "add-1,item-1,target.yml,text,20240101T120000Z,false,false,false"
        csv_path = tmp_path / ".knowledge" / "additions" / "additions.csv"
        csv_path.write_text(f"{header}\n{row}\n")

        with patch.object(track_additions, "REPO_ROOT", tmp_path):
            args = parse_validate_args(["--id", "add-1", "--validated"])
            result = validate_addition_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "validated: true" in captured.out

    def test_updates_only_in_scope_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should update only in_scope flag when specified alone."""
        (tmp_path / ".knowledge" / "additions").mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        row = "add-1,item-1,target.yml,text,20240101T120000Z,false,false,false"
        csv_path = tmp_path / ".knowledge" / "additions" / "additions.csv"
        csv_path.write_text(f"{header}\n{row}\n")

        with patch.object(track_additions, "REPO_ROOT", tmp_path):
            args = parse_validate_args(["--id", "add-1", "--in-scope"])
            result = validate_addition_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "in_scope: true" in captured.out

    def test_updates_only_meaningful_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should update only meaningful flag when specified alone."""
        (tmp_path / ".knowledge" / "additions").mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        row = "add-1,item-1,target.yml,text,20240101T120000Z,false,false,false"
        csv_path = tmp_path / ".knowledge" / "additions" / "additions.csv"
        csv_path.write_text(f"{header}\n{row}\n")

        with patch.object(track_additions, "REPO_ROOT", tmp_path):
            args = parse_validate_args(["--id", "add-1", "--meaningful"])
            result = validate_addition_main(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "meaningful: true" in captured.out

    def test_no_update_when_no_flags(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should still succeed when no flags are specified."""
        (tmp_path / ".knowledge" / "additions").mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        row = "add-1,item-1,target.yml,text,20240101T120000Z,false,false,false"
        csv_path = tmp_path / ".knowledge" / "additions" / "additions.csv"
        csv_path.write_text(f"{header}\n{row}\n")

        with patch.object(track_additions, "REPO_ROOT", tmp_path):
            args = parse_validate_args(["--id", "add-1"])
            result = validate_addition_main(args)

        assert result == 0


class TestTrackAdditionsMainRelativePath:
    """Tests for track_additions_main with relative knowledge path."""

    def test_handles_relative_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should resolve relative knowledge path from REPO_ROOT."""
        (tmp_path / ".knowledge" / "comparisons").mkdir(parents=True)
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
source.yml,item-1,original,text,split.yml,text
"""
        (tmp_path / ".knowledge" / "comparisons" / "test.csv").write_text(csv_content)

        with patch.object(track_additions, "REPO_ROOT", tmp_path):
            # Use relative path (default)
            args = parse_track_args([])
            result = track_additions_main(args)

        assert result == 0

    def test_returns_one_for_comparison_query_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 and print error on ComparisonQueryError."""
        (tmp_path / ".knowledge" / "comparisons").mkdir(parents=True)
        # Create invalid CSV that will cause all queries to fail
        (tmp_path / ".knowledge" / "comparisons" / "bad.csv").write_text("[[invalid")

        with patch.object(track_additions, "REPO_ROOT", tmp_path):
            args = parse_track_args([])
            result = track_additions_main(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err

    def test_skips_empty_pattern_additions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should skip pattern with no additions (0 tracked, 0 skipped)."""
        (tmp_path / "comparisons").mkdir(parents=True)
        (tmp_path / "additions").mkdir(parents=True)

        # Pattern with split_only entry that has empty element_id (will be skipped)
        csv_content = """source_file,id,origin_type,original_text,split_file,split_text
,empty-id,split_only,text,,
"""
        (tmp_path / "comparisons" / "empty.csv").write_text(csv_content)

        args = parse_track_args(["--knowledge-path", str(tmp_path)])
        result = track_additions_main(args)

        # Should succeed but not print the pattern line since both counts are 0
        assert result == 0


class TestMainTrack:
    """Tests for main_track entry point."""

    def test_calls_track_additions_main(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should call track_additions_main with parsed args."""
        with (
            patch("sys.argv", ["script", "--knowledge-path", str(tmp_path)]),
            patch.object(track_additions, "REPO_ROOT", tmp_path),
        ):
            result = main_track()

        # Will return 1 because directory doesn't exist
        assert result == 1


class TestMainValidate:
    """Tests for main_validate entry point."""

    def test_calls_validate_addition_main(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should call validate_addition_main with parsed args."""
        with patch.object(track_additions, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch("sys.argv", ["script", "--id", "add-1"]):
                result = main_validate()

        # Will return 1 because CSV doesn't exist
        assert result == 1
