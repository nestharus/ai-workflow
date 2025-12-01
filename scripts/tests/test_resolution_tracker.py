"""Tests for scripts.resolution_tracker module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts import resolution_tracker
from scripts.resolution_tracker import (
    CSV_COLUMNS,
    ResolutionRecord,
    append_resolution,
    compute_file_hash,
    compute_text_hash,
    ensure_csv_exists,
    extract_text_for_id,
    is_already_resolved,
    main,
    parse_args,
    save_original_file,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestComputeTextHash:
    """Tests for compute_text_hash function."""

    def test_returns_hex_string(self) -> None:
        """Should return hexadecimal string."""
        result = compute_text_hash("test content")
        assert isinstance(result, str)
        assert all(c in "0123456789abcdef" for c in result)

    def test_same_input_same_hash(self) -> None:
        """Should return same hash for same input."""
        hash1 = compute_text_hash("test content")
        hash2 = compute_text_hash("test content")
        assert hash1 == hash2

    def test_different_input_different_hash(self) -> None:
        """Should return different hash for different input."""
        hash1 = compute_text_hash("content 1")
        hash2 = compute_text_hash("content 2")
        assert hash1 != hash2

    def test_strips_whitespace(self) -> None:
        """Should strip whitespace before hashing."""
        hash1 = compute_text_hash("  test  ")
        hash2 = compute_text_hash("test")
        assert hash1 == hash2


class TestComputeFileHash:
    """Tests for compute_file_hash function."""

    def test_returns_hex_string(self, fs: FakeFilesystem) -> None:
        """Should return hexadecimal string."""
        fs.create_file("/test.txt", contents="test content")

        result = compute_file_hash(Path("/test.txt"))

        assert isinstance(result, str)
        assert all(c in "0123456789abcdef" for c in result)

    def test_raises_for_missing_file(self) -> None:
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            compute_file_hash(Path("/nonexistent.txt"))


class TestSaveOriginalFile:
    """Tests for save_original_file function."""

    def test_copies_file_with_timestamp(self, fs: FakeFilesystem) -> None:
        """Should copy file to originals directory with timestamp."""
        fs.create_dir("/knowledge")
        fs.create_file("/source/test.yml", contents="content")

        with patch.object(resolution_tracker, "utc_timestamp", return_value="20240101T120000Z"):
            result = save_original_file(Path("/source/test.yml"), Path("/knowledge"))

        assert result.exists()
        assert "20240101T120000Z" in result.name

    def test_raises_for_missing_source(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError when source doesn't exist."""
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()

        with pytest.raises(FileNotFoundError):
            save_original_file(tmp_path / "nonexistent.txt", knowledge)


class TestEnsureCsvExists:
    """Tests for ensure_csv_exists function."""

    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "resolutions" / "resolved.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in CSV_COLUMNS:
            assert col in content

    def test_does_not_overwrite_nonempty_file(self, tmp_path: Path) -> None:
        """Should not overwrite non-empty file.

        DuckDB requires real filesystem.
        """
        (tmp_path / "resolutions").mkdir(parents=True)
        csv_path = tmp_path / "resolutions" / "resolved.csv"
        csv_path.write_text("existing,content\n")

        ensure_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "existing,content" in content


class TestAppendResolution:
    """Tests for append_resolution function."""

    def test_appends_record(self, tmp_path: Path) -> None:
        """Should append resolution record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "resolutions").mkdir(parents=True)
        csv_path = tmp_path / "resolutions" / "resolved.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        record = ResolutionRecord(
            resolution_id="res-1",
            id="item-1",
            source_file="source.yml",
            split_file="split.yml",
            original_text_hash="abc123",
            split_text_hash="def456",
            source_file_hash="ghi789",
            split_file_hash="jkl012",
            resolved_at="20240101T120000Z",
        )

        append_resolution(csv_path, record)

        content = csv_path.read_text()
        assert "res-1" in content
        assert "item-1" in content


class TestIsAlreadyResolved:
    """Tests for is_already_resolved function."""

    def test_returns_true_for_existing_resolution(self, real_knowledge_path: Path) -> None:
        """Should return True when resolution exists.

        DuckDB requires real filesystem files.
        """
        csv_path = real_knowledge_path / "resolutions" / "resolved.csv"
        header = ",".join(CSV_COLUMNS)
        row = "res-1,item-1,source.yml,split.yml,abc,def,ghi,jkl,20240101T120000Z"
        csv_path.write_text(f"{header}\n{row}\n")

        result = is_already_resolved(csv_path, "item-1", "source.yml", "split.yml")

        assert result is True

    def test_returns_false_for_missing_resolution(self, real_knowledge_path: Path) -> None:
        """Should return False when resolution doesn't exist.

        DuckDB requires real filesystem files.
        """
        csv_path = real_knowledge_path / "resolutions" / "resolved.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        result = is_already_resolved(csv_path, "item-1", "source.yml", "split.yml")

        assert result is False

    def test_returns_false_for_missing_file(self, tmp_path: Path) -> None:
        """Should return False when CSV doesn't exist."""
        result = is_already_resolved(
            tmp_path / "nonexistent.csv", "item-1", "source.yml", "split.yml"
        )
        assert result is False

    def test_returns_false_for_empty_file(self, real_knowledge_path: Path) -> None:
        """Should return False for empty CSV file.

        DuckDB requires real filesystem files.
        """
        csv_path = real_knowledge_path / "resolutions" / "resolved.csv"
        csv_path.write_text("")

        result = is_already_resolved(csv_path, "item-1", "source.yml", "split.yml")

        assert result is False


class TestExtractTextForId:
    """Tests for extract_text_for_id function."""

    def test_extracts_text_for_existing_id(self, fs: FakeFilesystem) -> None:
        """Should extract text for existing ID."""
        with patch.object(resolution_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
items:
  - id: item-1
    text: Item text content
"""
            fs.create_file("/fake/test.yml", contents=content)

            result = extract_text_for_id(Path("/fake/test.yml"), "item-1")

            assert "Item text content" in result

    def test_raises_for_missing_id(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError for missing ID."""
        with patch.object(resolution_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
items:
  - id: item-1
    text: Text
"""
            fs.create_file("/fake/test.yml", contents=content)

            with pytest.raises(ValueError) as exc_info:
                extract_text_for_id(Path("/fake/test.yml"), "nonexistent")

            assert "not found" in str(exc_info.value)


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_id(self) -> None:
        """Should require --id argument."""
        with pytest.raises(SystemExit):
            parse_args(["--source-file", "/source.yml"])

    def test_requires_source_file(self) -> None:
        """Should require --source-file argument."""
        with pytest.raises(SystemExit):
            parse_args(["--id", "item-1"])

    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments correctly."""
        # nargs="*" means multiple values after single --split-file
        args = parse_args([
            "--id", "item-1",
            "--source-file", "/source.yml",
            "--split-file", "/split1.yml", "/split2.yml",
        ])

        assert args.id == "item-1"
        assert args.source_file == Path("/source.yml")
        assert len(args.split_file) == 2


class TestGetDisplayPath:
    """Tests for _get_display_path function."""

    def test_returns_relative_for_repo_path(self, tmp_path: Path) -> None:
        """Should return relative path when inside repo."""
        from scripts.resolution_tracker import _get_display_path

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
            file_path = tmp_path / "subdir" / "file.yml"
            result = _get_display_path(file_path)
            assert result == "subdir/file.yml"

    def test_returns_absolute_for_outside_repo(self, tmp_path: Path) -> None:
        """Should return absolute path when outside repo."""
        from scripts.resolution_tracker import _get_display_path

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path / "repo"):
            outside_path = tmp_path / "outside" / "file.yml"
            result = _get_display_path(outside_path)
            assert str(outside_path) in result


class TestMain:
    """Tests for main function."""

    def test_returns_one_without_split_files(self, capsys: pytest.CaptureFixture) -> None:
        """Should return 1 when no split files provided."""
        with patch("sys.argv", ["script", "--id", "item-1", "--source-file", "/source.yml"]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "At least one --split-file" in captured.err

    def test_returns_one_for_missing_source(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when source file doesn't exist."""
        with patch.object(resolution_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch(
                "sys.argv",
                ["script", "--id", "item-1", "--source-file", "missing.yml", "--split-file", "split.yml"],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_zero_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 0 and create record on success.

        DuckDB requires real filesystem.
        """
        source_content = """
items:
  - id: item-1
    text: Original text
"""
        split_content = """
items:
  - id: item-1
    text: Split text
"""
        (tmp_path / "source.yml").write_text(source_content)
        (tmp_path / "split.yml").write_text(split_content)

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "source.yml",
                    "--split-file", "split.yml",
                    "--knowledge-path", str(tmp_path / ".knowledge"),
                ],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Resolution recorded" in captured.out

    def test_skips_already_resolved(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should skip already resolved items.

        DuckDB requires real filesystem.
        """
        source_content = """
items:
  - id: item-1
    text: Original text
"""
        split_content = """
items:
  - id: item-1
    text: Split text
"""
        (tmp_path / "source.yml").write_text(source_content)
        (tmp_path / "split.yml").write_text(split_content)

        # Create existing resolution
        (tmp_path / ".knowledge" / "resolutions").mkdir(parents=True)
        csv_path = tmp_path / ".knowledge" / "resolutions" / "resolved.csv"
        header = ",".join(CSV_COLUMNS)
        row = "res-1,item-1,source.yml,split.yml,abc,def,ghi,jkl,20240101T120000Z"
        csv_path.write_text(f"{header}\n{row}\n")

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "source.yml",
                    "--split-file", "split.yml",
                    "--knowledge-path", str(tmp_path / ".knowledge"),
                ],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "already resolved" in captured.out

    def test_returns_one_for_missing_split_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when split file doesn't exist.

        DuckDB requires real filesystem.
        """
        source_content = """
items:
  - id: item-1
    text: Original text
"""
        (tmp_path / "source.yml").write_text(source_content)

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "source.yml",
                    "--split-file", "missing.yml",
                    "--knowledge-path", str(tmp_path / ".knowledge"),
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Split file not found" in captured.err

    def test_returns_one_for_missing_id_in_split(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when ID not found in split file.

        DuckDB requires real filesystem.
        """
        source_content = """
items:
  - id: item-1
    text: Original text
"""
        split_content = """
items:
  - id: other-id
    text: Different item
"""
        (tmp_path / "source.yml").write_text(source_content)
        (tmp_path / "split.yml").write_text(split_content)

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "source.yml",
                    "--split-file", "split.yml",
                    "--knowledge-path", str(tmp_path / ".knowledge"),
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_handles_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should handle absolute knowledge path.

        DuckDB requires real filesystem.
        """
        source_content = """
items:
  - id: item-1
    text: Original text
"""
        split_content = """
items:
  - id: item-1
    text: Split text
"""
        (tmp_path / "source.yml").write_text(source_content)
        (tmp_path / "split.yml").write_text(split_content)
        knowledge_path = tmp_path / "custom_knowledge"

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "source.yml",
                    "--split-file", "split.yml",
                    "--knowledge-path", str(knowledge_path),
                ],
            ):
                result = main()

        assert result == 0
        # Check that files were created in the custom knowledge path
        assert (knowledge_path / "resolutions" / "resolved.csv").exists()

    def test_returns_one_for_missing_id_in_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when ID not found in source file.

        DuckDB requires real filesystem.
        """
        source_content = """
items:
  - id: other-id
    text: Different item
"""
        (tmp_path / "source.yml").write_text(source_content)
        (tmp_path / "split.yml").write_text("content")

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "source.yml",
                    "--split-file", "split.yml",
                    "--knowledge-path", str(tmp_path / ".knowledge"),
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_handles_multiple_split_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should handle multiple split files.

        DuckDB requires real filesystem.
        """
        source_content = """
items:
  - id: item-1
    text: Original text
"""
        split_content = """
items:
  - id: item-1
    text: Split text
"""
        (tmp_path / "source.yml").write_text(source_content)
        (tmp_path / "split1.yml").write_text(split_content)
        (tmp_path / "split2.yml").write_text(split_content)

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "source.yml",
                    "--split-file", "split1.yml", "split2.yml",
                    "--knowledge-path", str(tmp_path / ".knowledge"),
                ],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "2 records" in captured.out


class TestIsAlreadyResolvedErrors:
    """Tests for is_already_resolved error handling."""

    def test_returns_false_on_duckdb_error(self, tmp_path: Path) -> None:
        """Should return False when DuckDB raises an error.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "resolutions" / "resolved.csv"
        (tmp_path / "resolutions").mkdir(parents=True)
        # Write malformed CSV that will cause DuckDB to fail
        csv_path.write_text("bad,csv,format\nno,match,here")

        result = is_already_resolved(csv_path, "item-1", "source.yml", "split.yml")

        assert result is False


class TestCsvColumns:
    """Tests for CSV_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "resolution_id" in CSV_COLUMNS
        assert "id" in CSV_COLUMNS
        assert "source_file" in CSV_COLUMNS
        assert "split_file" in CSV_COLUMNS
        assert "original_text_hash" in CSV_COLUMNS
        assert "split_text_hash" in CSV_COLUMNS
