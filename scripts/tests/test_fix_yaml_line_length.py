"""Tests for fix_yaml_line_length module."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.fix_yaml_line_length import (
    fix_yaml_file,
    main,
    wrap_text_preserving_indent,
)


class TestWrapTextPreservingIndent:
    """Tests for wrap_text_preserving_indent function."""

    def test_wrap_long_text(self) -> None:
        """Should wrap text that exceeds max_length."""
        # Create text that exceeds 120 characters when combined with indent
        long_text = "word " * 30  # ~150 characters
        base_indent = "    "
        result = wrap_text_preserving_indent(long_text.strip(), base_indent, max_length=120)

        lines = result.split("\n")
        for line in lines:
            assert len(line) <= 120

    def test_preserve_base_indent(self) -> None:
        """Should apply base indent to all lines."""
        text = "word " * 30
        base_indent = "        "  # 8 spaces
        result = wrap_text_preserving_indent(text.strip(), base_indent, max_length=80)

        lines = result.split("\n")
        for line in lines:
            assert line.startswith(base_indent)

    def test_short_text_not_wrapped(self) -> None:
        """Should not wrap text shorter than max_length."""
        text = "short text"
        base_indent = "  "
        result = wrap_text_preserving_indent(text, base_indent, max_length=120)

        assert result == "  short text"
        assert "\n" not in result

    def test_empty_text(self) -> None:
        """Should handle empty text."""
        result = wrap_text_preserving_indent("", "  ", max_length=120)
        assert result == ""

    def test_single_word_exceeds_max(self) -> None:
        """Should handle single word that exceeds max_length."""
        # Single very long word cannot be wrapped
        long_word = "a" * 150
        result = wrap_text_preserving_indent(long_word, "  ", max_length=120)

        # Should contain the word even though it exceeds max
        assert long_word in result

    def test_branch_word_fits_on_current_line(self) -> None:
        """Test the branch where adding a word fits on the current line."""
        text = "one two"
        base_indent = "  "
        result = wrap_text_preserving_indent(text, base_indent, max_length=120)

        # Should be single line since it fits
        assert result == "  one two"

    def test_branch_word_causes_wrap(self) -> None:
        """Test the branch where adding a word causes wrap to new line."""
        # Use exact sizes to trigger wrap
        text = "aaa bbb ccc"  # Each word is 3 chars
        base_indent = ""
        # max_length = 6 means "aaa bbb" (7 chars) won't fit
        result = wrap_text_preserving_indent(text, base_indent, max_length=7)

        lines = result.split("\n")
        assert len(lines) >= 2
        assert lines[0] == "aaa bbb"

    def test_last_word_added_to_line(self) -> None:
        """Test the branch where the last word is added."""
        text = "one"
        result = wrap_text_preserving_indent(text, "  ", max_length=120)

        assert result == "  one"


class TestFixYamlFile:
    """Tests for fix_yaml_file function."""

    def test_fix_long_line_in_block_scalar(self, tmp_path: Path) -> None:
        """Should wrap long lines in block scalars."""
        long_text = "word " * 30  # Very long line
        yaml_content = f"""description: |
  {long_text.strip()}
other: value
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True
        assert num_fixes == 1  # File was changed

        content = yaml_file.read_text()
        lines = content.split("\n")
        for line in lines:
            # All lines should now be <= 120 characters
            assert len(line) <= 120

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        """Should not modify file in dry run mode."""
        long_text = "word " * 30
        yaml_content = f"""description: |
  {long_text.strip()}
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        original_content = yaml_file.read_text()
        success, num_fixes = fix_yaml_file(yaml_file, dry_run=True)

        assert success is True
        assert num_fixes == 1
        # File should not be modified
        assert yaml_file.read_text() == original_content

    def test_no_changes_needed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Should report no changes when file is fine."""
        yaml_content = """key: value
other: data
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True
        assert num_fixes == 0

        captured = capsys.readouterr()
        assert "No changes needed" in captured.out

    def test_fix_long_key_value_line(self, tmp_path: Path) -> None:
        """Should convert long key: value lines to block scalars."""
        long_value = "word " * 30
        yaml_content = f"description: {long_value.strip()}\n"
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True
        assert num_fixes == 1

        content = yaml_file.read_text()
        assert "description: |" in content

    def test_handles_file_read_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle file read errors gracefully."""
        non_existent = tmp_path / "nonexistent.yml"

        success, num_fixes = fix_yaml_file(non_existent)

        assert success is False
        assert num_fixes == 0

        captured = capsys.readouterr()
        assert "Error processing" in captured.out

    def test_multiple_block_scalars(self, tmp_path: Path) -> None:
        """Should handle multiple block scalar fields."""
        long_text = "word " * 30
        yaml_content = f"""text: |
  {long_text.strip()}
rule: |
  {long_text.strip()}
content: |
  short content
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True
        # Should fix two long lines
        assert num_fixes == 1

    def test_various_block_scalar_fields(self, tmp_path: Path) -> None:
        """Should recognize various block scalar field names."""
        long_text = "word " * 30
        yaml_content = f"""text: |
  {long_text.strip()}
rule: |
  Short content here
content: |
  Short content
description: |
  Short
definition: |
  Short
note: |
  Short
example: |
  Short
analysis: |
  Short
code: |
  Short
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True

    def test_preserves_empty_lines_in_block(self, tmp_path: Path) -> None:
        """Should preserve empty lines within block scalars."""
        yaml_content = """description: |
  First paragraph

  Second paragraph
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True
        content = yaml_file.read_text()
        # Empty line should be preserved
        assert "\n\n" in content

    def test_non_block_scalar_long_line(self, tmp_path: Path) -> None:
        """Should handle long lines that are not block scalars."""
        # Line that's too long but not a recognizable pattern
        long_line = "x" * 150
        yaml_content = f"data: [{long_line}]\n"
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True
        # Should not crash, but also not try to wrap the array notation

    def test_block_scalar_indentation_tracking(self, tmp_path: Path) -> None:
        """Should correctly track block scalar indentation."""
        yaml_content = """items:
  - id: item1
    description: |
      Content that is short
next_field: value
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True
        content = yaml_file.read_text()
        assert "next_field: value" in content


class TestMain:
    """Tests for main function."""

    def test_main_with_specific_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should process specific files when provided."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value\n")

        monkeypatch.setattr("sys.argv", ["fix_yaml_line_length", str(yaml_file)])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Processing 1 YAML files" in captured.out
        assert "No changes needed" in captured.out

    def test_main_dry_run_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should show dry run mode message."""
        long_text = "word " * 30
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(f"description: {long_text}\n")

        original = yaml_file.read_text()

        monkeypatch.setattr("sys.argv", ["fix_yaml_line_length", "--dry-run", str(yaml_file)])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "DRY RUN MODE" in captured.out
        # File should not be modified
        assert yaml_file.read_text() == original

    def test_main_finds_docs_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should find YAML files in docs/ directory."""
        # Create docs directory structure
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "test.yml").write_text("key: value\n")

        # Point the script to look in our temp directory
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["fix_yaml_line_length"])

        # Mock __file__ to point to a scripts directory in tmp_path
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        import scripts.fix_yaml_line_length as module

        monkeypatch.setattr(module, "__file__", str(scripts_dir / "fix_yaml_line_length.py"))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Processing" in captured.out

    def test_main_no_docs_directory_uses_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should try current directory if docs/ not found from script location."""
        # Create docs in tmp_path (current directory)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "test.yml").write_text("key: value\n")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["fix_yaml_line_length"])

        # Point __file__ to a location where parent/docs doesn't exist
        fake_location = tmp_path / "other" / "location" / "scripts"
        fake_location.mkdir(parents=True)

        import scripts.fix_yaml_line_length as module

        monkeypatch.setattr(module, "__file__", str(fake_location / "fix_yaml_line_length.py"))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Processing" in captured.out

    def test_main_no_docs_directory_exits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should exit with error if no docs/ directory found."""
        # No docs directory anywhere
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["fix_yaml_line_length"])

        # Point __file__ to a location where parent/docs doesn't exist
        fake_location = tmp_path / "other" / "scripts"
        fake_location.mkdir(parents=True)

        import scripts.fix_yaml_line_length as module

        monkeypatch.setattr(module, "__file__", str(fake_location / "fix_yaml_line_length.py"))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "docs/ directory not found" in captured.out

    def test_main_no_yaml_files_exits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should exit if no YAML files found."""
        # Create empty docs directory
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["fix_yaml_line_length"])

        # Point __file__ so docs_dir is found
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        import scripts.fix_yaml_line_length as module

        monkeypatch.setattr(module, "__file__", str(scripts_dir / "fix_yaml_line_length.py"))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "No YAML files found" in captured.out

    def test_main_with_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should return exit code 1 if there are errors."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value\n")

        monkeypatch.setattr("sys.argv", ["fix_yaml_line_length", str(yaml_file)])

        # Mock fix_yaml_file to return an error
        import scripts.fix_yaml_line_length as module

        original_fix = module.fix_yaml_file

        def mock_fix(path: Path, dry_run: bool = False) -> tuple[bool, int]:
            return (False, 0)

        monkeypatch.setattr(module, "fix_yaml_file", mock_fix)

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    def test_main_summary_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should show summary with counts."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value\n")

        monkeypatch.setattr("sys.argv", ["fix_yaml_line_length", str(yaml_file)])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Summary:" in captured.out
        assert "Files processed:" in captured.out
        assert "Files changed:" in captured.out
        assert "Errors:" in captured.out

    def test_main_success_exit_code(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should exit with code 0 on success."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value\n")

        monkeypatch.setattr("sys.argv", ["fix_yaml_line_length", str(yaml_file)])

        # main() calls sys.exit(0) on success, so we need to catch it
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0


class TestIntegration:
    """Integration tests for the fix_yaml_line_length module."""

    def test_full_pipeline(self, tmp_path: Path) -> None:
        """Test full processing pipeline with various content types."""
        yaml_content = """# YAML file with various patterns
text: |
  This is a very long line that should be wrapped because it exceeds the maximum line length of 120 characters when written out fully in the file here.
rule: |
  Short content that doesn't need wrapping
content: |
  Another very long line of content that should be wrapped to fit within the maximum line length constraint for the file format.
description: Short description
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True
        assert num_fixes == 1  # File was changed

        content = yaml_file.read_text()
        lines = content.split("\n")
        for line in lines:
            assert len(line) <= 120

    def test_nested_structure(self, tmp_path: Path) -> None:
        """Test with nested YAML structure."""
        long_text = "word " * 30
        yaml_content = f"""sections:
  - id: section1
    items:
      - id: item1
        text: |
          {long_text.strip()}
  - id: section2
    content: short
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        success, _num_fixes = fix_yaml_file(yaml_file)

        assert success is True
        content = yaml_file.read_text()
        # Structure should be preserved
        assert "sections:" in content
        assert "- id: section1" in content
        assert "- id: section2" in content
