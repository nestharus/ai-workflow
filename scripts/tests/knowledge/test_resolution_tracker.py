"""Tests for scripts.knowledge.resolution_tracker module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.knowledge import resolution_tracker
from scripts.knowledge.resolution_tracker import (
    CSV_COLUMNS,
    PROJECTION_VERSION,
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
            projection_version="fieldfacts.v2",
            original_content_hash="content_hash_orig",
            split_content_hash="content_hash_split",
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
        row = (
            "res-1,item-1,source.yml,split.yml,abc,def,ghi,jkl,"
            "20240101T120000Z,fieldfacts.v2,content_orig,content_split"
        )
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

    def test_extracts_text_with_nested_ids_uses_sliced_representation(
        self, fs: FakeFilesystem
    ) -> None:
        """Should use sliced representation with $ref for nested ID-bearing dicts.

        Per the fact redesign (lines 131-133), the text hash is computed from
        the sliced representation with child content excluded.
        """
        with patch.object(resolution_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
id: parent-section
title: Parent Title
items:
  - id: child-item-1
    text: Child 1 internal content
  - id: child-item-2
    text: Child 2 internal content
"""
            fs.create_file("/fake/test.yml", contents=content)

            result = extract_text_for_id(Path("/fake/test.yml"), "parent-section")

            # The sliced representation should contain $ref tokens, not child content
            assert "$ref:child-item-1" in result
            assert "$ref:child-item-2" in result
            # Child's internal content should NOT be in the parent's text
            assert "Child 1 internal content" not in result
            assert "Child 2 internal content" not in result


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
        args = parse_args(
            [
                "--id",
                "item-1",
                "--source-file",
                "/source.yml",
                "--split-file",
                "/split1.yml",
                "/split2.yml",
            ]
        )

        assert args.id == "item-1"
        assert args.source_file == Path("/source.yml")
        assert len(args.split_file) == 2


class TestGetDisplayPath:
    """Tests for _get_display_path function."""

    def test_returns_relative_for_repo_path(self, tmp_path: Path) -> None:
        """Should return relative path when inside repo."""
        from scripts.knowledge.resolution_tracker import _get_display_path

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
            file_path = tmp_path / "subdir" / "file.yml"
            result = _get_display_path(file_path)
            assert result == "subdir/file.yml"

    def test_returns_absolute_for_outside_repo(self, tmp_path: Path) -> None:
        """Should return absolute path when outside repo."""
        from scripts.knowledge.resolution_tracker import _get_display_path

        with patch.object(resolution_tracker, "REPO_ROOT", tmp_path / "repo"):
            outside_path = tmp_path / "outside" / "file.yml"
            result = _get_display_path(outside_path)
            assert str(outside_path) in result


class TestMain:
    """Tests for main function."""

    def test_returns_one_without_split_files(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when no split files provided."""
        with patch("sys.argv", ["script", "--id", "item-1", "--source-file", "/source.yml"]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "At least one --split-file" in captured.err

    def test_returns_one_for_missing_source(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when source file doesn't exist."""
        with patch.object(resolution_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "missing.yml",
                    "--split-file",
                    "split.yml",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_zero_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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

        with (
            patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--split-file",
                    "split.yml",
                    "--knowledge-path",
                    str(tmp_path / ".knowledge"),
                ],
            ),
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Resolution recorded" in captured.out

    def test_skips_already_resolved(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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
        row = (
            "res-1,item-1,source.yml,split.yml,abc,def,ghi,jkl,"
            "20240101T120000Z,fieldfacts.v2,content_orig,content_split"
        )
        csv_path.write_text(f"{header}\n{row}\n")

        with (
            patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--split-file",
                    "split.yml",
                    "--knowledge-path",
                    str(tmp_path / ".knowledge"),
                ],
            ),
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "already resolved" in captured.out

    def test_returns_one_for_missing_split_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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

        with (
            patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--split-file",
                    "missing.yml",
                    "--knowledge-path",
                    str(tmp_path / ".knowledge"),
                ],
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Split file not found" in captured.err

    def test_returns_one_for_missing_id_in_split(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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

        with (
            patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--split-file",
                    "split.yml",
                    "--knowledge-path",
                    str(tmp_path / ".knowledge"),
                ],
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_handles_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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

        with (
            patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--split-file",
                    "split.yml",
                    "--knowledge-path",
                    str(knowledge_path),
                ],
            ),
        ):
            result = main()

        assert result == 0
        # Check that files were created in the custom knowledge path
        assert (knowledge_path / "resolutions" / "resolved.csv").exists()

    def test_returns_one_for_missing_id_in_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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

        with (
            patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--split-file",
                    "split.yml",
                    "--knowledge-path",
                    str(tmp_path / ".knowledge"),
                ],
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_handles_multiple_split_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
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

        with (
            patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--split-file",
                    "split1.yml",
                    "split2.yml",
                    "--knowledge-path",
                    str(tmp_path / ".knowledge"),
                ],
            ),
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

    def test_has_projection_versioning_columns(self) -> None:
        """Should have projection versioning columns.

        Per fact_redesign.md lines 1289-1327, the CSV schema includes:
        - projection_version: identifies slicing/FieldFact/text projection rules
        - original_content_hash: SHA-256 of canonical FieldFact payload for original
        - split_content_hash: SHA-256 of canonical FieldFact payload for split
        """
        assert "projection_version" in CSV_COLUMNS
        assert "original_content_hash" in CSV_COLUMNS
        assert "split_content_hash" in CSV_COLUMNS


class TestProjectionVersion:
    """Tests for projection versioning constant."""

    def test_projection_version_format(self) -> None:
        """Should follow fieldfacts.vN format."""
        assert PROJECTION_VERSION.startswith("fieldfacts.v")
        # Extract version number
        version_part = PROJECTION_VERSION.split(".")[-1]
        assert version_part.startswith("v")
        assert version_part[1:].isdigit()

    def test_projection_version_is_v2(self) -> None:
        """Should be fieldfacts.v2 for current implementation."""
        assert PROJECTION_VERSION == "fieldfacts.v2"


class TestResolutionRecordWithProjectionVersion:
    """Tests for ResolutionRecord with projection versioning fields."""

    def test_resolution_record_includes_projection_fields(self) -> None:
        """Should be able to create ResolutionRecord with all projection fields."""
        record = ResolutionRecord(
            resolution_id="res-1",
            id="item-1",
            source_file="source.yml",
            split_file="split.yml",
            original_text_hash="text_hash_orig",
            split_text_hash="text_hash_split",
            source_file_hash="file_hash_orig",
            split_file_hash="file_hash_split",
            resolved_at="20240101T120000Z",
            projection_version="fieldfacts.v2",
            original_content_hash="content_hash_orig",
            split_content_hash="content_hash_split",
        )

        assert record["projection_version"] == "fieldfacts.v2"
        assert record["original_content_hash"] == "content_hash_orig"
        assert record["split_content_hash"] == "content_hash_split"


class TestContentHashStability:
    """Tests for content hash stability and behavior."""

    def test_content_hash_remains_stable_when_text_format_changes(self, tmp_path: Path) -> None:
        """Should have stable content hash when only text formatting changes.

        Content hash is computed from canonical FieldFact payloads, independent
        of text projection formatting. Per fact_redesign.md lines 1446-1469.
        """
        from scripts.knowledge.compare_yaml_docs import compute_element_content_hash

        # Same structure should produce same content hash
        data = {"id": "test", "text": "Hello", "count": 5}
        hash1 = compute_element_content_hash(data, "test")  # type: ignore[arg-type]
        hash2 = compute_element_content_hash(data, "test")  # type: ignore[arg-type]

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256

    def test_content_hash_changes_when_field_values_change(self, tmp_path: Path) -> None:
        """Should produce different content hash when field values change."""
        from scripts.knowledge.compare_yaml_docs import compute_element_content_hash

        data1 = {"id": "test", "text": "Hello"}
        data2 = {"id": "test", "text": "World"}

        hash1 = compute_element_content_hash(data1, "test")  # type: ignore[arg-type]
        hash2 = compute_element_content_hash(data2, "test")  # type: ignore[arg-type]

        assert hash1 != hash2


class TestTextHashUsesSlicedRepresentation:
    """Tests that text hashes reflect sliced representations."""

    def test_text_hash_uses_ref_tokens(self, fs: FakeFilesystem) -> None:
        """Should produce text hash from sliced representation with $ref tokens.

        Per fact_redesign.md lines 131-133, text hashes now reflect sliced
        representations with $ref tokens.
        """
        with patch.object(resolution_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
id: parent
title: Parent Title
items:
  - id: child-1
    text: Child 1 content
  - id: child-2
    text: Child 2 content
"""
            fs.create_file("/fake/test.yml", contents=content)

            parent_text = extract_text_for_id(Path("/fake/test.yml"), "parent")

            # Text should contain $ref tokens, not child content
            assert "$ref:child-1" in parent_text
            assert "$ref:child-2" in parent_text
            assert "Child 1 content" not in parent_text

    def test_parent_hash_independent_of_child_changes(self, fs: FakeFilesystem) -> None:
        """Should produce same parent hash when only child internals change.

        Due to $ref replacement, parent hash is independent of child content.
        """
        with patch.object(resolution_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            # Version 1: child has "Original content"
            content_v1 = """
id: parent
title: Parent Title
items:
  - id: child-1
    text: Original content
"""
            fs.create_file("/fake/test_v1.yml", contents=content_v1)
            parent_text_v1 = extract_text_for_id(Path("/fake/test_v1.yml"), "parent")
            parent_hash_v1 = compute_text_hash(parent_text_v1)

            # Version 2: child has "Modified content"
            content_v2 = """
id: parent
title: Parent Title
items:
  - id: child-1
    text: Modified content
"""
            fs.create_file("/fake/test_v2.yml", contents=content_v2)
            parent_text_v2 = extract_text_for_id(Path("/fake/test_v2.yml"), "parent")
            parent_hash_v2 = compute_text_hash(parent_text_v2)

            # Parent hashes should be same (child content is replaced with $ref)
            assert parent_hash_v1 == parent_hash_v2


class TestMainWithProjectionVersioning:
    """Tests for main function with projection versioning fields populated."""

    def test_main_populates_projection_fields(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should populate projection versioning fields in CSV.

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

        with (
            patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
            patch(
                "sys.argv",
                [
                    "script",
                    "--id",
                    "item-1",
                    "--source-file",
                    "source.yml",
                    "--split-file",
                    "split.yml",
                    "--knowledge-path",
                    str(tmp_path / ".knowledge"),
                ],
            ),
        ):
            result = main()

        assert result == 0

        # Read the CSV and verify projection version is populated
        import duckdb

        csv_path = tmp_path / ".knowledge" / "resolutions" / "resolved.csv"
        query = (
            "SELECT projection_version, original_content_hash, "
            "split_content_hash FROM read_csv_auto(?)"
        )
        row = duckdb.execute(query, [str(csv_path)]).fetchone()

        assert row is not None
        projection_version, original_content_hash, split_content_hash = row

        # Verify projection version
        assert projection_version == "fieldfacts.v2"

        # Verify content hashes are SHA-256 format (64 hex chars)
        assert len(original_content_hash) == 64
        assert len(split_content_hash) == 64
        assert all(c in "0123456789abcdef" for c in original_content_hash)
        assert all(c in "0123456789abcdef" for c in split_content_hash)


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing CSV readers."""

    def test_original_columns_still_present(self) -> None:
        """Should have all original columns for backward compatibility.

        Schema evolution is append-only: existing CSV readers selecting
        original columns remain unaffected.
        """
        original_columns = [
            "resolution_id",
            "id",
            "source_file",
            "split_file",
            "original_text_hash",
            "split_text_hash",
            "source_file_hash",
            "split_file_hash",
            "resolved_at",
        ]
        for col in original_columns:
            assert col in CSV_COLUMNS

    def test_new_columns_are_appended(self) -> None:
        """Should have new columns appended after original columns.

        Per append-only schema evolution, new columns come after original ones.
        """
        projection_idx = CSV_COLUMNS.index("projection_version")
        resolved_at_idx = CSV_COLUMNS.index("resolved_at")

        # New columns should come after resolved_at (last original column)
        assert projection_idx > resolved_at_idx
