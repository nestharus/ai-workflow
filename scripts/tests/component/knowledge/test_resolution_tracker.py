from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from scripts.knowledge import resolution_tracker
from scripts.knowledge.resolution_tracker import (
    CSV_COLUMNS,
    PROJECTION_VERSION,
    ResolutionRecord,
    append_resolution,
    ensure_csv_exists,
    is_already_resolved,
    parse_args,
    save_original_file,
)


class TestMain:
    def test_main_no_split_files(self, capsys: pytest.CaptureFixture) -> None:
        """Test main() when no split files are provided (lines 356-358)."""
        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=Path("test.yml"),
                split_file=[],  # No split files
                knowledge_path=Path(".knowledge"),
            )

            result = resolution_tracker.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "At least one --split-file is required" in captured.err

    def test_main_source_file_not_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() when source file doesn't exist (lines 367-369)."""
        split_file = tmp_path / "split.yml"
        split_file.write_text("id: test-id\nvalue: data")

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=Path("nonexistent.yml"),
                split_file=[split_file],
                knowledge_path=tmp_path / ".knowledge",
            )
            with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
                result = resolution_tracker.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Source file not found" in captured.err

    def test_main_source_file_outside_repo(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() when source file is outside repository (lines 371-373)."""
        # Create source file in a different directory
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        source_file = other_dir / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        split_file = tmp_path / "split.yml"
        split_file.write_text("id: test-id\nvalue: data")

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=source_file,  # Outside repo
                split_file=[split_file],
                knowledge_path=repo_root / ".knowledge",
            )
            with patch.object(resolution_tracker, "REPO_ROOT", repo_root):
                result = resolution_tracker.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Source file must be within repository" in captured.err

    def test_main_extract_text_value_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() when extract_text_for_id raises ValueError (lines 377-381)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: different-id\nvalue: data")

        split_file = tmp_path / "split.yml"
        split_file.write_text("id: different-id\nvalue: data")

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="nonexistent-id",  # ID not in file
                source_file=source_file.relative_to(tmp_path),
                split_file=[split_file],
                knowledge_path=Path(".knowledge"),
            )
            with patch.object(resolution_tracker, "REPO_ROOT", tmp_path):
                result = resolution_tracker.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_main_extract_text_file_not_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() when extract_text_for_id raises FileNotFoundError (lines 382-384)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        split_file = tmp_path / "split.yml"
        split_file.write_text("id: test-id\nvalue: data")

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=source_file.relative_to(tmp_path),
                split_file=[split_file],
                knowledge_path=Path(".knowledge"),
            )
            with (
                patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
                patch.object(resolution_tracker, "extract_text_for_id") as mock_extract,
            ):
                mock_extract.side_effect = FileNotFoundError("File not found")
                result = resolution_tracker.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: File not found" in captured.err

    def test_main_split_file_not_found(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test main() when split file doesn't exist (lines 407-409)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        # Create knowledge directory
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=source_file.relative_to(tmp_path),
                split_file=[tmp_path / "nonexistent_split.yml"],  # Doesn't exist
                knowledge_path=knowledge_path,
            )
            with (
                patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
                patch.object(resolution_tracker, "extract_text_for_id") as mock_extract,
                patch.object(resolution_tracker, "compute_element_content_hash") as mock_hash,
            ):
                mock_extract.return_value = "id: test-id\nvalue: data"
                mock_hash.return_value = "abc123"
                result = resolution_tracker.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Split file not found" in captured.err

    def test_main_split_file_outside_repo(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() when split file is outside repository (lines 411-413)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        # Create split file in a different directory
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        split_file = other_dir / "split.yml"
        split_file.write_text("id: test-id\nvalue: data")

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        repo_source = repo_root / "source.yml"
        repo_source.write_text("id: test-id\nvalue: data")

        knowledge_path = repo_root / ".knowledge"
        knowledge_path.mkdir()

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=Path("source.yml"),
                split_file=[split_file],  # Outside repo
                knowledge_path=knowledge_path,
            )
            with (
                patch.object(resolution_tracker, "REPO_ROOT", repo_root),
                patch.object(resolution_tracker, "extract_text_for_id") as mock_extract,
                patch.object(resolution_tracker, "compute_element_content_hash") as mock_hash,
            ):
                mock_extract.return_value = "id: test-id\nvalue: data"
                mock_hash.return_value = "abc123"
                result = resolution_tracker.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Split file must be within repository" in captured.err

    def test_main_split_extract_value_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() when split file extraction raises ValueError (lines 417-421)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        split_file = tmp_path / "split.yml"
        split_file.write_text("id: different-id\nvalue: data")  # Different ID

        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        call_count = [0]

        def mock_extract(file_path: Path, element_id: str) -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                return "id: test-id\nvalue: data"  # Source file OK
            raise ValueError(f"ID '{element_id}' not found in split file")

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=Path("source.yml"),
                split_file=[Path("split.yml")],
                knowledge_path=knowledge_path,
            )
            with (
                patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
                patch.object(resolution_tracker, "extract_text_for_id", side_effect=mock_extract),
                patch.object(resolution_tracker, "compute_element_content_hash") as mock_hash,
            ):
                mock_hash.return_value = "abc123"
                result = resolution_tracker.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err

    def test_main_split_extract_file_not_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() when split file extraction raises FileNotFoundError (lines 422-424)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        split_file = tmp_path / "split.yml"
        split_file.write_text("id: test-id\nvalue: data")

        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        call_count = [0]

        def mock_extract(file_path: Path, element_id: str) -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                return "id: test-id\nvalue: data"  # Source file OK
            raise FileNotFoundError("Split file disappeared")

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=Path("source.yml"),
                split_file=[Path("split.yml")],
                knowledge_path=knowledge_path,
            )
            with (
                patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
                patch.object(resolution_tracker, "extract_text_for_id", side_effect=mock_extract),
                patch.object(resolution_tracker, "compute_element_content_hash") as mock_hash,
            ):
                mock_hash.return_value = "abc123"
                result = resolution_tracker.main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


class TestEnsureCsvExists:
    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that parent directories are created if they don't exist."""
        csv_path = tmp_path / "nested" / "deep" / "resolved.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.parent.exists()
        assert csv_path.exists()

    def test_creates_csv_with_headers(self, tmp_path: Path) -> None:
        """Test that CSV is created with proper column headers."""
        csv_path = tmp_path / "resolved.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        # Check that headers are present
        for col in CSV_COLUMNS:
            assert col in content

    def test_does_not_overwrite_existing_csv(self, tmp_path: Path) -> None:
        """Test that existing CSV with content is not overwritten."""
        csv_path = tmp_path / "resolved.csv"
        # Create a CSV with existing content
        csv_path.write_text("resolution_id,id,source_file\nabc,test,source.yml\n")
        original_content = csv_path.read_text()

        ensure_csv_exists(csv_path)

        # Content should be unchanged
        assert csv_path.read_text() == original_content

    def test_recreates_empty_csv(self, tmp_path: Path) -> None:
        """Test that empty CSV file gets headers added."""
        csv_path = tmp_path / "resolved.csv"
        csv_path.write_text("")  # Empty file

        ensure_csv_exists(csv_path)

        content = csv_path.read_text()
        # Should now have headers
        assert "resolution_id" in content


class TestAppendResolution:
    def test_appends_record_to_csv(self, tmp_path: Path) -> None:
        """Test that resolution record is appended to CSV."""
        csv_path = tmp_path / "resolved.csv"
        ensure_csv_exists(csv_path)

        record = ResolutionRecord(
            resolution_id="uuid-123",
            id="test-element",
            source_file="source.yml",
            split_file="split.yml",
            original_text_hash="hash1",
            split_text_hash="hash2",
            source_file_hash="hash3",
            split_file_hash="hash4",
            resolved_at="2024-01-15T10:30:00Z",
            projection_version=PROJECTION_VERSION,
            original_content_hash="hash5",
            split_content_hash="hash6",
        )

        append_resolution(csv_path, record)

        # Verify record was added
        conn = duckdb.connect()
        result = conn.execute(f"SELECT * FROM read_csv_auto('{csv_path}')").fetchall()
        conn.close()

        assert len(result) == 1
        # Find columns by index
        assert "uuid-123" in str(result[0])
        assert "test-element" in str(result[0])

    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        """Test that multiple records can be appended."""
        csv_path = tmp_path / "resolved.csv"
        ensure_csv_exists(csv_path)

        for i in range(3):
            record = ResolutionRecord(
                resolution_id=f"uuid-{i}",
                id=f"element-{i}",
                source_file="source.yml",
                split_file=f"split{i}.yml",
                original_text_hash=f"hash{i}",
                split_text_hash=f"hash{i}",
                source_file_hash=f"hash{i}",
                split_file_hash=f"hash{i}",
                resolved_at=f"2024-01-{15 + i}T10:30:00Z",
                projection_version=PROJECTION_VERSION,
                original_content_hash=f"hash{i}",
                split_content_hash=f"hash{i}",
            )
            append_resolution(csv_path, record)

        # Verify all records were added
        conn = duckdb.connect()
        result = conn.execute(f"SELECT COUNT(*) FROM read_csv_auto('{csv_path}')").fetchone()
        conn.close()

        assert result is not None
        assert result[0] == 3


class TestIsAlreadyResolved:
    def test_returns_false_when_csv_does_not_exist(self, tmp_path: Path) -> None:
        """Test that function returns False when CSV doesn't exist."""
        csv_path = tmp_path / "nonexistent.csv"

        result = is_already_resolved(csv_path, "test-id", "source.yml", "split.yml")

        assert result is False

    def test_returns_false_when_csv_is_empty(self, tmp_path: Path) -> None:
        """Test that function returns False when CSV is empty."""
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("")

        result = is_already_resolved(csv_path, "test-id", "source.yml", "split.yml")

        assert result is False

    def test_returns_true_when_record_exists(self, tmp_path: Path) -> None:
        """Test that function returns True when matching record exists."""
        csv_path = tmp_path / "resolved.csv"
        ensure_csv_exists(csv_path)

        record = ResolutionRecord(
            resolution_id="uuid-123",
            id="test-element",
            source_file="source.yml",
            split_file="split.yml",
            original_text_hash="hash1",
            split_text_hash="hash2",
            source_file_hash="hash3",
            split_file_hash="hash4",
            resolved_at="2024-01-15T10:30:00Z",
            projection_version=PROJECTION_VERSION,
            original_content_hash="hash5",
            split_content_hash="hash6",
        )
        append_resolution(csv_path, record)

        result = is_already_resolved(csv_path, "test-element", "source.yml", "split.yml")

        assert result is True

    def test_returns_false_when_record_does_not_match(self, tmp_path: Path) -> None:
        """Test that function returns False when no matching record exists."""
        csv_path = tmp_path / "resolved.csv"
        ensure_csv_exists(csv_path)

        record = ResolutionRecord(
            resolution_id="uuid-123",
            id="different-element",
            source_file="different.yml",
            split_file="different-split.yml",
            original_text_hash="hash1",
            split_text_hash="hash2",
            source_file_hash="hash3",
            split_file_hash="hash4",
            resolved_at="2024-01-15T10:30:00Z",
            projection_version=PROJECTION_VERSION,
            original_content_hash="hash5",
            split_content_hash="hash6",
        )
        append_resolution(csv_path, record)

        result = is_already_resolved(csv_path, "test-element", "source.yml", "split.yml")

        assert result is False

    def test_handles_duckdb_error_gracefully(self, tmp_path: Path) -> None:
        """Test that function returns False on DuckDB errors (line 257-258)."""
        csv_path = tmp_path / "malformed.csv"
        # Write malformed CSV that will cause DuckDB error
        csv_path.write_text("not,a,valid\ncsv,with,wrong,columns")

        result = is_already_resolved(csv_path, "test-id", "source.yml", "split.yml")

        # Should return False on error, not raise exception
        assert result is False


class TestParseArgs:
    def test_parses_required_arguments(self) -> None:
        """Test parsing of required arguments."""
        args = parse_args(
            [
                "--id",
                "test-element",
                "--source-file",
                "source.yml",
                "--split-file",
                "split.yml",
            ]
        )

        assert args.id == "test-element"
        assert args.source_file == Path("source.yml")
        assert args.split_file == [Path("split.yml")]

    def test_parses_multiple_split_files(self) -> None:
        """Test parsing of multiple split files."""
        args = parse_args(
            [
                "--id",
                "test-element",
                "--source-file",
                "source.yml",
                "--split-file",
                "split1.yml",
                "split2.yml",
                "split3.yml",
            ]
        )

        assert args.split_file == [Path("split1.yml"), Path("split2.yml"), Path("split3.yml")]

    def test_parses_knowledge_path(self) -> None:
        """Test parsing of custom knowledge path."""
        args = parse_args(
            [
                "--id",
                "test-element",
                "--source-file",
                "source.yml",
                "--split-file",
                "split.yml",
                "--knowledge-path",
                "/custom/path/.knowledge",
            ]
        )

        assert args.knowledge_path == Path("/custom/path/.knowledge")

    def test_default_knowledge_path(self) -> None:
        """Test default value for knowledge path."""
        args = parse_args(
            [
                "--id",
                "test-element",
                "--source-file",
                "source.yml",
                "--split-file",
                "split.yml",
            ]
        )

        assert args.knowledge_path == Path(".knowledge")

    def test_default_empty_split_files(self) -> None:
        """Test default value for split files is empty list."""
        args = parse_args(
            [
                "--id",
                "test-element",
                "--source-file",
                "source.yml",
            ]
        )

        assert args.split_file == []

    def test_exits_on_missing_required_args(self) -> None:
        """Test that parser exits when required args are missing."""
        with pytest.raises(SystemExit):
            parse_args([])


class TestMainSuccessPath:
    def test_main_already_resolved_skips(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() skips when ID is already resolved (lines 426-428)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        split_file = tmp_path / "split.yml"
        split_file.write_text("id: test-id\nvalue: data")

        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir(parents=True)

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=Path("source.yml"),
                split_file=[Path("split.yml")],
                knowledge_path=knowledge_path,
            )
            with (
                patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
                patch.object(resolution_tracker, "extract_text_for_id") as mock_extract,
                patch.object(resolution_tracker, "compute_element_content_hash") as mock_hash,
                patch.object(resolution_tracker, "is_already_resolved") as mock_resolved,
            ):
                mock_extract.return_value = "id: test-id\nvalue: data"
                mock_hash.return_value = "abc123"
                mock_resolved.return_value = True
                result = resolution_tracker.main()

        assert result == 0
        captured = capsys.readouterr()
        assert "already resolved" in captured.out

    def test_main_success_creates_record(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() creates resolution record successfully (lines 430-470)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        split_file = tmp_path / "split.yml"
        split_file.write_text("id: test-id\nvalue: data")

        knowledge_path = tmp_path / ".knowledge"

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=Path("source.yml"),
                split_file=[Path("split.yml")],
                knowledge_path=knowledge_path,
            )
            with (
                patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
                patch.object(resolution_tracker, "extract_text_for_id") as mock_extract,
                patch.object(resolution_tracker, "compute_element_content_hash") as mock_hash,
                patch.object(resolution_tracker, "parse_yaml_file") as mock_parse_yaml,
            ):
                mock_extract.return_value = "id: test-id\nvalue: data"
                mock_hash.return_value = "abc123"
                mock_parse_yaml.return_value = {"id": "test-id"}
                result = resolution_tracker.main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Resolution recorded" in captured.out
        assert "(1 record)" in captured.out

        # Verify CSV was created
        csv_path = knowledge_path / "resolutions" / "resolved.csv"
        assert csv_path.exists()

    def test_main_success_multiple_split_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() handles multiple split files (lines 442-444, 468-470)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        split_files = []
        for i in range(3):
            sf = tmp_path / f"split{i}.yml"
            sf.write_text("id: test-id\nvalue: data")
            split_files.append(Path(f"split{i}.yml"))

        knowledge_path = tmp_path / ".knowledge"

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=Path("source.yml"),
                split_file=split_files,
                knowledge_path=knowledge_path,
            )
            with (
                patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
                patch.object(resolution_tracker, "extract_text_for_id") as mock_extract,
                patch.object(resolution_tracker, "compute_element_content_hash") as mock_hash,
                patch.object(resolution_tracker, "parse_yaml_file") as mock_parse_yaml,
            ):
                mock_extract.return_value = "id: test-id\nvalue: data"
                mock_hash.return_value = "abc123"
                mock_parse_yaml.return_value = {"id": "test-id"}
                result = resolution_tracker.main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Resolution recorded" in captured.out
        assert "(3 records)" in captured.out

    def test_main_with_absolute_knowledge_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() handles absolute knowledge path."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test-id\nvalue: data")

        split_file = tmp_path / "split.yml"
        split_file.write_text("id: test-id\nvalue: data")

        # Use absolute path for knowledge
        knowledge_path = tmp_path / "absolute_knowledge"

        with patch.object(resolution_tracker, "parse_args") as mock_parse:
            mock_parse.return_value = MagicMock(
                id="test-id",
                source_file=Path("source.yml"),
                split_file=[Path("split.yml")],
                knowledge_path=knowledge_path,  # absolute
            )
            with (
                patch.object(resolution_tracker, "REPO_ROOT", tmp_path),
                patch.object(resolution_tracker, "extract_text_for_id") as mock_extract,
                patch.object(resolution_tracker, "compute_element_content_hash") as mock_hash,
                patch.object(resolution_tracker, "parse_yaml_file") as mock_parse_yaml,
            ):
                mock_extract.return_value = "id: test-id\nvalue: data"
                mock_hash.return_value = "abc123"
                mock_parse_yaml.return_value = {"id": "test-id"}
                result = resolution_tracker.main()

        assert result == 0
