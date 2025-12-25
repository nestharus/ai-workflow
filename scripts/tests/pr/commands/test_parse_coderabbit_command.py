"""Tests for parse_coderabbit_command module."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.pr.commands.parse_coderabbit_command import (
    _parse_line_spec,
    _parse_section,
    parse_coderabbit_command,
)


class TestParseLineSpec:
    """Tests for the _parse_line_spec helper function."""

    def test_parses_line_range(self) -> None:
        """Test parsing 'Line: X to Y' format."""
        start, end = _parse_line_spec("Line: 1 to 10")
        assert start == 1
        assert end == 10

    def test_parses_line_range_large_numbers(self) -> None:
        """Test parsing line range with large numbers."""
        start, end = _parse_line_spec("Line: 100 to 250")
        assert start == 100
        assert end == 250

    def test_parses_single_line(self) -> None:
        """Test parsing 'Line: X' format."""
        start, end = _parse_line_spec("Line: 5")
        assert start == 5
        assert end == 5

    def test_returns_none_for_invalid_format(self) -> None:
        """Test that invalid format returns None tuple."""
        start, end = _parse_line_spec("Invalid line format")
        assert start is None
        assert end is None

    def test_handles_extra_whitespace(self) -> None:
        """Test handling of extra whitespace in line spec."""
        start, end = _parse_line_spec("Line:  43  to  135")
        assert start == 43
        assert end == 135


class TestParseSection:
    """Tests for the _parse_section helper function."""

    def test_parses_complete_section(self) -> None:
        """Test parsing a complete section with all fields."""
        section = """
File: tools/__init__.py
Line: 1 to 2
Type: nitpick

Prompt for AI Agent:
Add a short module docstring at the top describing the purpose.
"""
        result = _parse_section(section, 0)

        assert result is not None
        assert result["index"] == 0
        assert result["origin"] == "CODERABBIT"
        assert result["path"] == "tools/__init__.py"
        assert result["line"] == 1
        assert result["start_line"] == 1
        assert result["end_line"] == 2
        assert result["type"] == "nitpick"
        assert "Add a short module docstring" in result["content"]
        assert result["comments"][0]["author"] == "coderabbit"

    def test_parses_single_line_section(self) -> None:
        """Test parsing a section with single line number."""
        section = """
File: app/core/settings.py
Line: 24
Type: potential_issue

Prompt for AI Agent:
Fix the security issue.
"""
        result = _parse_section(section, 5)

        assert result is not None
        assert result["line"] == 24
        assert result["start_line"] == 24
        assert result["end_line"] == 24

    def test_returns_none_for_section_without_file(self) -> None:
        """Test that section without File: returns None."""
        section = """
Line: 1 to 10
Type: nitpick

Prompt for AI Agent:
Some content here.
"""
        result = _parse_section(section, 0)
        assert result is None

    def test_returns_none_for_section_without_prompt(self) -> None:
        """Test that section without Prompt content returns None."""
        section = """
File: some/file.py
Line: 1
Type: nitpick

Prompt for AI Agent:
"""
        result = _parse_section(section, 0)
        assert result is None

    def test_returns_none_for_empty_section(self) -> None:
        """Test that empty section returns None."""
        result = _parse_section("", 0)
        assert result is None

    def test_preserves_multiline_content(self) -> None:
        """Test that multiline prompt content is preserved."""
        section = """
File: app/file.py
Line: 10
Type: potential_issue

Prompt for AI Agent:
First line of the prompt.
Second line of the prompt.
Third line with more details.
"""
        result = _parse_section(section, 0)

        assert result is not None
        assert "First line" in result["content"]
        assert "Second line" in result["content"]
        assert "Third line" in result["content"]


class TestParseCoderabbitCommand:
    """Tests for the parse_coderabbit_command function."""

    def test_returns_error_for_missing_file(self, tmp_path: Path) -> None:
        """Test that missing review file returns error code."""
        missing_file = tmp_path / "missing.review.coderabbit"
        output_dir = tmp_path / "output"

        result = parse_coderabbit_command(missing_file, output_dir)

        assert result == 1

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        """Test that output directory is created if it doesn't exist."""
        review_file = tmp_path / "test.review.coderabbit"
        review_file.write_text("Review completed")
        output_dir = tmp_path / "new_output_dir"

        parse_coderabbit_command(review_file, output_dir)

        assert output_dir.exists()

    def test_cleans_existing_coderabbit_files(self, tmp_path: Path) -> None:
        """Test that existing coderabbit_*.json files are cleaned."""
        review_file = tmp_path / "test.review.coderabbit"
        review_file.write_text("Review completed")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create existing files
        (output_dir / "coderabbit_0.json").write_text("{}")
        (output_dir / "coderabbit_1.json").write_text("{}")
        (output_dir / "other_file.json").write_text("{}")

        parse_coderabbit_command(review_file, output_dir)

        # coderabbit files should be removed, other files preserved
        assert not (output_dir / "coderabbit_0.json").exists()
        assert not (output_dir / "coderabbit_1.json").exists()
        assert (output_dir / "other_file.json").exists()

    def test_parses_single_comment(self, tmp_path: Path) -> None:
        """Test parsing a review with a single comment."""
        review_content = """Starting CodeRabbit review...

============================================================================
File: app/main.py
Line: 10
Type: nitpick

Prompt for AI Agent:
Add a docstring to this function.


============================================================================
Review completed
"""
        review_file = tmp_path / "test.review.coderabbit"
        review_file.write_text(review_content)
        output_dir = tmp_path / "output"

        result = parse_coderabbit_command(review_file, output_dir)

        assert result == 0
        task_file = output_dir / "coderabbit_0.json"
        assert task_file.exists()

        content = json.loads(task_file.read_text())
        assert content["path"] == "app/main.py"
        assert content["line"] == 10
        assert "Add a docstring" in content["content"]

    def test_parses_multiple_comments(self, tmp_path: Path) -> None:
        """Test parsing a review with multiple comments."""
        review_content = """Starting CodeRabbit review...

============================================================================
File: file1.py
Line: 1
Type: nitpick

Prompt for AI Agent:
First comment.


============================================================================
File: file2.py
Line: 5 to 10
Type: potential_issue

Prompt for AI Agent:
Second comment.


============================================================================
File: file3.py
Line: 20
Type: nitpick

Prompt for AI Agent:
Third comment.


============================================================================
Review completed
"""
        review_file = tmp_path / "test.review.coderabbit"
        review_file.write_text(review_content)
        output_dir = tmp_path / "output"

        result = parse_coderabbit_command(review_file, output_dir)

        assert result == 0
        assert (output_dir / "coderabbit_0.json").exists()
        assert (output_dir / "coderabbit_1.json").exists()
        assert (output_dir / "coderabbit_2.json").exists()

        # Check sequential indexing
        for i in range(3):
            content = json.loads((output_dir / f"coderabbit_{i}.json").read_text())
            assert content["index"] == i

    def test_skips_header_sections(self, tmp_path: Path) -> None:
        """Test that header sections without prompts are skipped."""
        review_content = """Starting CodeRabbit review in plain text mode...

Connecting to review service
Setting up
Analyzing
Reviewing

============================================================================
File: app/main.py
Line: 10
Type: nitpick

Prompt for AI Agent:
Add a docstring.


============================================================================
Review completed
"""
        review_file = tmp_path / "test.review.coderabbit"
        review_file.write_text(review_content)
        output_dir = tmp_path / "output"

        result = parse_coderabbit_command(review_file, output_dir)

        assert result == 0
        # Only one task file should exist (for the actual comment)
        assert (output_dir / "coderabbit_0.json").exists()
        assert not (output_dir / "coderabbit_1.json").exists()

    def test_handles_utf8_content(self, tmp_path: Path) -> None:
        """Test handling of UTF-8 content in review files."""
        review_content = """
============================================================================
File: app/i18n.py
Line: 5
Type: nitpick

Prompt for AI Agent:
Update the translations: 中文 日本語 한국어


============================================================================
"""
        review_file = tmp_path / "test.review.coderabbit"
        review_file.write_text(review_content, encoding="utf-8")
        output_dir = tmp_path / "output"

        result = parse_coderabbit_command(review_file, output_dir)

        assert result == 0
        content = json.loads((output_dir / "coderabbit_0.json").read_text())
        assert "中文" in content["content"]

    def test_prints_summary(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that summary is printed."""
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

        parse_coderabbit_command(review_file, output_dir)

        captured = capsys.readouterr()
        assert "Parsed 1 review comments" in captured.out
        assert "Tasks created: 1" in captured.out

    def test_json_structure_matches_expected_format(self, tmp_path: Path) -> None:
        """Test that JSON output structure matches expected format."""
        review_content = """
============================================================================
File: app/service.py
Line: 15 to 25
Type: potential_issue

Prompt for AI Agent:
Fix the security vulnerability in the authentication logic.


============================================================================
"""
        review_file = tmp_path / "test.review.coderabbit"
        review_file.write_text(review_content)
        output_dir = tmp_path / "output"

        parse_coderabbit_command(review_file, output_dir)

        content = json.loads((output_dir / "coderabbit_0.json").read_text())

        # Check all required fields exist
        assert "index" in content
        assert "origin" in content
        assert "path" in content
        assert "line" in content
        assert "start_line" in content
        assert "end_line" in content
        assert "type" in content
        assert "content" in content
        assert "comments" in content

        # Check structure matches pr-comment-handler expectations
        assert content["origin"] == "CODERABBIT"
        assert isinstance(content["comments"], list)
        assert len(content["comments"]) == 1
        assert "body" in content["comments"][0]
        assert "author" in content["comments"][0]

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

    def test_atomic_write_success(self, tmp_path: Path) -> None:
        """Test that atomic write creates files correctly."""
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

        result = parse_coderabbit_command(review_file, output_dir)

        assert result == 0
        task_file = output_dir / "coderabbit_0.json"
        assert task_file.exists()
        # Verify content is valid JSON
        content = json.loads(task_file.read_text())
        assert content["path"] == "app/main.py"
        # Verify no temp files left behind
        temp_files = list(output_dir.glob("*.tmp"))
        assert len(temp_files) == 0
