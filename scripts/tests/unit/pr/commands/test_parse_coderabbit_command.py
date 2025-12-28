from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.pr.commands.parse_coderabbit_command import (
    _parse_line_spec,
    _parse_section,
    parse_coderabbit_command,
)


class TestParseCoderabbitCommand:
    def test_handles_write_error_with_cleanup(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that write errors clean up already-created files and return error."""
        review_content = """
============================================================================
File: file1.py
Line: 1
Type: nitpick

Prompt for AI Agent:
First comment.


============================================================================
File: file2.py
Line: 5
Type: nitpick

Prompt for AI Agent:
Second comment.


============================================================================
"""
        review_file = tmp_path / "test.review.coderabbit"
        review_file.write_text(review_content)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Mock tempfile.NamedTemporaryFile to fail on second call
        call_count = 0
        original_ntf = __import__("tempfile").NamedTemporaryFile

        def mock_ntf(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise PermissionError("Mock permission denied")
            return original_ntf(*args, **kwargs)

        with patch("tempfile.NamedTemporaryFile", side_effect=mock_ntf):
            result = parse_coderabbit_command(review_file, output_dir)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Failed to write task file" in captured.out
        # First file should be cleaned up
        assert not (output_dir / "coderabbit_0.json").exists()
        assert not (output_dir / "coderabbit_1.json").exists()

    def test_handles_oserror_during_write(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that OSError during write is handled properly."""
        review_content = """
============================================================================
File: app/main.py
Line: 1
Type: nitpick

Prompt for AI Agent:
Test content.


============================================================================
"""
        review_file = tmp_path / "test.review.coderabbit"
        review_file.write_text(review_content)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Mock to raise OSError
        with patch("tempfile.NamedTemporaryFile", side_effect=OSError("Disk full")):
            result = parse_coderabbit_command(review_file, output_dir)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Failed to write task file" in captured.out
        assert "Disk full" in captured.out
