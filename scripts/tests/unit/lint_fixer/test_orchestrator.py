"""Unit tests for lint_fixer orchestrator YAML handling."""

import pytest

from scripts.lint_fixer.orchestrator import (
    extract_files_from_lint_output,
    filter_lint_output_for_files,
)


class TestExtractFilesFromLintOutput:
    """Tests for extract_files_from_lint_output function."""

    def test_extract_from_yaml_format(self) -> None:
        """Test extracting files from YAML format output."""
        yaml_output = """errors:
  - linter: ruff
    file: /path/to/file1.py
    line: 10
    column: 5
    code: E501
    message: Line too long
    fix_available: false
  - linter: mypy
    file: /path/to/file2.py
    line: 20
    column: 1
    code: error
    message: Type error
    fix_available: false
"""
        files = extract_files_from_lint_output(yaml_output)

        assert len(files) == 2
        assert "/path/to/file1.py" in files
        assert "/path/to/file2.py" in files

    def test_extract_from_yaml_empty_errors(self) -> None:
        """Test extracting from YAML with no errors."""
        yaml_output = "errors: []"
        files = extract_files_from_lint_output(yaml_output)

        assert files == []

    def test_extract_from_yaml_deduplicates(self) -> None:
        """Test that duplicate files are deduplicated."""
        yaml_output = """errors:
  - linter: ruff
    file: /path/to/file.py
    line: 10
    column: 5
    code: E501
    message: Error 1
    fix_available: false
  - linter: ruff
    file: /path/to/file.py
    line: 20
    column: 1
    code: E502
    message: Error 2
    fix_available: false
"""
        files = extract_files_from_lint_output(yaml_output)

        assert len(files) == 1
        assert "/path/to/file.py" in files

    def test_extract_from_legacy_text_format(self) -> None:
        """Test fallback to legacy text format parsing."""
        text_output = """file1.py:10:5: E501 Line too long
file2.py:20:1: error Type mismatch
"""
        files = extract_files_from_lint_output(text_output)

        assert len(files) == 2
        assert "file1.py" in files
        assert "file2.py" in files

    def test_extract_from_ruff_arrow_format(self) -> None:
        """Test parsing ruff's arrow format."""
        ruff_output = """   --> src/module.py:15:10
   --> src/other.py:25:1
"""
        files = extract_files_from_lint_output(ruff_output)

        assert len(files) == 2
        assert "src/module.py" in files
        assert "src/other.py" in files


class TestFilterLintOutputForFiles:
    """Tests for filter_lint_output_for_files function."""

    def test_filter_yaml_output(self) -> None:
        """Test filtering YAML format output."""
        yaml_output = """errors:
  - linter: ruff
    file: /path/to/file1.py
    line: 10
    column: 5
    code: E501
    message: Line too long
    fix_available: false
  - linter: mypy
    file: /path/to/file2.py
    line: 20
    column: 1
    code: error
    message: Type error
    fix_available: false
"""
        filtered = filter_lint_output_for_files(yaml_output, ["/path/to/file1.py"])

        assert "file1.py" in filtered
        assert "file2.py" not in filtered
        assert "E501" in filtered
        assert "Line too long" in filtered

    def test_filter_yaml_multiple_files(self) -> None:
        """Test filtering for multiple files."""
        yaml_output = """errors:
  - linter: ruff
    file: a.py
    line: 1
    column: 1
    code: E1
    message: Error A
    fix_available: false
  - linter: ruff
    file: b.py
    line: 2
    column: 1
    code: E2
    message: Error B
    fix_available: false
  - linter: ruff
    file: c.py
    line: 3
    column: 1
    code: E3
    message: Error C
    fix_available: false
"""
        filtered = filter_lint_output_for_files(yaml_output, ["a.py", "c.py"])

        assert "a.py" in filtered
        assert "c.py" in filtered
        assert "b.py" not in filtered

    def test_filter_yaml_no_matches(self) -> None:
        """Test filtering when no files match."""
        yaml_output = """errors:
  - linter: ruff
    file: other.py
    line: 1
    column: 1
    code: E1
    message: Error
    fix_available: false
"""
        filtered = filter_lint_output_for_files(yaml_output, ["nonexistent.py"])

        assert filtered == "errors: []"

    def test_filter_empty_file_list(self) -> None:
        """Test filtering with empty file list."""
        yaml_output = """errors:
  - linter: ruff
    file: file.py
    line: 1
    column: 1
    code: E1
    message: Error
    fix_available: false
"""
        filtered = filter_lint_output_for_files(yaml_output, [])

        assert filtered == ""

    def test_filter_preserves_multiline_message(self) -> None:
        """Test that multiline messages are preserved."""
        yaml_output = """errors:
  - linter: actionlint
    file: workflow.yml
    line: 9
    column: 11
    code: action
    message: |
      input "unknown" is not defined
      available inputs are "a", "b"
    fix_available: false
"""
        filtered = filter_lint_output_for_files(yaml_output, ["workflow.yml"])

        assert "workflow.yml" in filtered
        assert "unknown" in filtered

    def test_filter_legacy_text_fallback(self) -> None:
        """Test fallback to legacy text filtering."""
        text_output = """file1.py:10:5: E501 Line too long
file2.py:20:1: error Type mismatch
"""
        filtered = filter_lint_output_for_files(text_output, ["file1.py"])

        assert "file1.py" in filtered
        assert "file2.py" not in filtered


class TestOrchestratorYamlIntegration:
    """Integration tests for orchestrator YAML handling."""

    def test_extract_then_filter_roundtrip(self) -> None:
        """Test that extract -> filter works correctly."""
        yaml_output = """errors:
  - linter: ruff
    file: /app/main.py
    line: 10
    column: 5
    code: E501
    message: Line too long
    fix_available: false
  - linter: mypy
    file: /app/utils.py
    line: 20
    column: 1
    code: error
    message: Type error
    fix_available: false
  - linter: ruff
    file: /app/main.py
    line: 15
    column: 1
    code: E502
    message: Another error
    fix_available: true
    fix_message: Auto-fixable
"""
        # Extract all files
        all_files = extract_files_from_lint_output(yaml_output)
        assert len(all_files) == 2

        # Filter to just main.py
        filtered = filter_lint_output_for_files(yaml_output, ["/app/main.py"])

        # Extract from filtered output
        filtered_files = extract_files_from_lint_output(filtered)
        assert len(filtered_files) == 1
        assert "/app/main.py" in filtered_files

        # Verify both errors for main.py are present
        assert "E501" in filtered
        assert "E502" in filtered
        assert "utils.py" not in filtered
