from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestSaveOriginalFile:
    def test_creates_originals_directory(self, tmp_path: Path) -> None:
        """Test that originals directory is created if it doesn't exist."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("id: test\nvalue: data")

        knowledge_path = tmp_path / "knowledge"
        # knowledge_path and originals don't exist yet

        with patch("scripts.knowledge.resolution_tracker.utc_timestamp") as mock_ts:
            mock_ts.return_value = "2024-01-15T10-30-00Z"
            result = save_original_file(source_file, knowledge_path)

        assert (knowledge_path / "originals").exists()
        assert result.exists()
        assert result.name == "2024-01-15T10-30-00Z-source.yml"
        assert result.read_text() == "id: test\nvalue: data"

    def test_copies_file_with_timestamp(self, tmp_path: Path) -> None:
        """Test that file is copied with timestamped name."""
        source_file = tmp_path / "my_document.yaml"
        source_file.write_text("content: important data")

        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()

        with patch("scripts.knowledge.resolution_tracker.utc_timestamp") as mock_ts:
            mock_ts.return_value = "2024-06-20T14-45-30Z"
            result = save_original_file(source_file, knowledge_path)

        expected_path = knowledge_path / "originals" / "2024-06-20T14-45-30Z-my_document.yaml"
        assert result == expected_path
        assert result.read_text() == "content: important data"

    def test_preserves_file_content_exactly(self, tmp_path: Path) -> None:
        """Test that file content is preserved exactly during copy."""
        content = "id: test-element\ndescription: Line 1\n  Line 2\n"
        source_file = tmp_path / "test.yml"
        source_file.write_text(content)

        knowledge_path = tmp_path / ".knowledge"

        with patch("scripts.knowledge.resolution_tracker.utc_timestamp") as mock_ts:
            mock_ts.return_value = "2024-01-01T00-00-00Z"
            result = save_original_file(source_file, knowledge_path)

        assert result.read_text() == content
