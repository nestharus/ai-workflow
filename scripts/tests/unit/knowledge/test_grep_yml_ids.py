import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.knowledge import grep_yml_ids
from scripts.knowledge.grep_yml_ids import (
    MatchResult,
    _search_structure,
    _validate_yaml_result,
    format_json,
    format_table,
    main,
    parse_args,
    parse_yaml_file,
    search_yaml_files,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestParseYamlFile:
    def test_raises_valueerror_for_other_exceptions(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError for other parsing exceptions (covers lines 135-138)."""
        # Create a file that will cause an unexpected exception during read
        fs.create_file("/fake/test.yml", contents="key: value\n")

        with (
            patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")),
            patch(
                "pathlib.Path.read_text", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "test")
            ),
        ):
            with pytest.raises(ValueError) as exc_info:
                parse_yaml_file(Path("/fake/test.yml"))

            assert "Failed to parse" in str(exc_info.value)


class TestMain:
    def test_returns_one_for_invalid_path(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 for non-existent path."""
        with patch("sys.argv", ["script", "--id", "test", "--path", "/nonexistent"]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err

    def test_returns_one_for_file_path(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when path is a file, not directory."""
        fs.create_file("/test.yml", contents="id: test\n")

        with patch("sys.argv", ["script", "--id", "test", "--path", "/test.yml"]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_returns_one_for_no_matches(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when no matches found."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: other.id\n")

            with patch("sys.argv", ["script", "--id", "nonexistent", "--path", "/fake/docs"]):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "No matches found" in captured.out

    def test_returns_zero_for_matches(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 when matches found."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: test.id\n")

            with patch("sys.argv", ["script", "--id", "test.id", "--path", "/fake/docs"]):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "1 match" in captured.out

    def test_outputs_table_by_default(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should output table format by default."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: test.id\n")

            with patch("sys.argv", ["script", "--id", "test.id", "--path", "/fake/docs"]):
                main()

        captured = capsys.readouterr()
        assert "File:" in captured.out
        assert "Keys:" in captured.out

    def test_outputs_json_when_requested(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should output JSON format when requested."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: test.id\n")

            with patch(
                "sys.argv",
                ["script", "--id", "test.id", "--path", "/fake/docs", "--output", "json"],
            ):
                main()

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert len(parsed) == 1
        assert parsed[0]["element_id"] == "test.id"
        assert "object_data" in parsed[0]

    def test_exact_match_mode(self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]) -> None:
        """Should respect exact match mode."""
        with patch.object(grep_yml_ids, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/docs")
            fs.create_file("/fake/docs/test.yml", contents="id: url.prefix\n")

            # Partial match without --exact should find it
            with patch("sys.argv", ["script", "--id", "url", "--path", "/fake/docs"]):
                result_partial = main()

            # Exact match should not find it
            with patch("sys.argv", ["script", "--id", "url", "--path", "/fake/docs", "--exact"]):
                result_exact = main()

        assert result_partial == 0
        assert result_exact == 1
