import json
from pathlib import Path

import pytest

from scripts.pr.commands.file_hash_command import (
    _hash_file,
    file_hash_command,
    file_hash_compare_command,
)


class TestHashFile:
    def test_hashes_file_content(self, tmp_path: Path) -> None:
        """Test that file content is hashed."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        file_hash, error = _hash_file(test_file)

        assert file_hash
        assert error is None
        assert len(file_hash) == 32  # blake2b with digest_size=16 produces 32 hex chars

    def test_different_content_produces_different_hash(self, tmp_path: Path) -> None:
        """Test that different content produces different hashes."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content a")
        file2.write_text("content b")

        hash1, _ = _hash_file(file1)
        hash2, _ = _hash_file(file2)

        assert hash1 != hash2

    def test_same_content_produces_same_hash(self, tmp_path: Path) -> None:
        """Test that same content produces same hash."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("same content")
        file2.write_text("same content")

        hash1, _ = _hash_file(file1)
        hash2, _ = _hash_file(file2)

        assert hash1 == hash2

    def test_returns_empty_hash_with_error_for_missing_file(self, tmp_path: Path) -> None:
        """Test that missing file returns empty hash with error message."""
        missing = tmp_path / "missing.txt"

        file_hash, error = _hash_file(missing)

        assert file_hash == ""
        assert error is not None
        assert error.strip() != ""
        # Verify error mentions the missing filename (platform-agnostic)
        assert missing.name in error


class TestFileHashCompareCommand:
    def test_identical_files_return_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that identical hash files return exit code 0."""
        hashes = {"file1.txt": "abc123", "file2.txt": "def456"}
        file1 = tmp_path / "before.json"
        file2 = tmp_path / "after.json"
        file1.write_text(json.dumps(hashes))
        file2.write_text(json.dumps(hashes))

        result = file_hash_compare_command(file1, file2)

        assert result == 0
        captured = capsys.readouterr()
        assert "IDENTICAL" in captured.out

    def test_different_files_return_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that different hash files return exit code 1."""
        file1 = tmp_path / "before.json"
        file2 = tmp_path / "after.json"
        file1.write_text(json.dumps({"file.txt": "abc123"}))
        file2.write_text(json.dumps({"file.txt": "def456"}))

        result = file_hash_compare_command(file1, file2)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "DIFFERENT"
        assert "file.txt" in output["changed"]

    def test_reports_added_files(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that added files are reported."""
        file1 = tmp_path / "before.json"
        file2 = tmp_path / "after.json"
        file1.write_text(json.dumps({"existing.txt": "abc123"}))
        file2.write_text(json.dumps({"existing.txt": "abc123", "new.txt": "def456"}))

        result = file_hash_compare_command(file1, file2)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "new.txt" in output["added"]

    def test_reports_deleted_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that deleted files are reported."""
        file1 = tmp_path / "before.json"
        file2 = tmp_path / "after.json"
        file1.write_text(json.dumps({"kept.txt": "abc123", "removed.txt": "def456"}))
        file2.write_text(json.dumps({"kept.txt": "abc123"}))

        result = file_hash_compare_command(file1, file2)

        assert result == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "removed.txt" in output["deleted"]

    def test_missing_file_returns_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that missing file returns exit code 2."""
        existing = tmp_path / "exists.json"
        existing.write_text(json.dumps({}))
        missing = tmp_path / "missing.json"

        result = file_hash_compare_command(existing, missing)

        assert result == 2
        captured = capsys.readouterr()
        assert "File not found" in captured.err

    def test_invalid_json_returns_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that invalid JSON returns exit code 2."""
        valid = tmp_path / "valid.json"
        invalid = tmp_path / "invalid.json"
        valid.write_text(json.dumps({}))
        invalid.write_text("not valid json")

        result = file_hash_compare_command(valid, invalid)

        assert result == 2
        captured = capsys.readouterr()
        assert "Invalid JSON" in captured.err
