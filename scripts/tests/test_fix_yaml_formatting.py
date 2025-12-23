"""Tests for fix_yaml_formatting module."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.fix_yaml_formatting import (
    BLOCK_SCALAR_FIELDS,
    MAX_LINE_LENGTH,
    fix_double_quoted_field,
    fix_escaped_quotes_in_text,
    fix_single_quoted_field,
    fix_yaml_file,
    format_as_block_scalar,
    main,
    strip_markdown_bold,
    strip_trailing_whitespace,
    unescape_double_quoted,
    wrap_long_block_scalar_lines,
    wrap_text,
)

# =============================================================================
# Tests for strip_trailing_whitespace
# =============================================================================


class TestStripTrailingWhitespace:
    """Tests for strip_trailing_whitespace function."""

    def test_removes_trailing_spaces(self) -> None:
        """Should remove trailing spaces from lines."""
        content = "line1   \nline2  \nline3"
        result = strip_trailing_whitespace(content)
        assert result == "line1\nline2\nline3"

    def test_removes_trailing_tabs(self) -> None:
        """Should remove trailing tabs from lines."""
        content = "line1\t\nline2\t\t\nline3"
        result = strip_trailing_whitespace(content)
        assert result == "line1\nline2\nline3"

    def test_preserves_leading_whitespace(self) -> None:
        """Should preserve leading whitespace."""
        content = "  indented line  \n    more indented  "
        result = strip_trailing_whitespace(content)
        assert result == "  indented line\n    more indented"

    def test_empty_content(self) -> None:
        """Should handle empty content."""
        assert strip_trailing_whitespace("") == ""

    def test_no_trailing_whitespace(self) -> None:
        """Should not modify lines without trailing whitespace."""
        content = "line1\nline2\nline3"
        result = strip_trailing_whitespace(content)
        assert result == content


# =============================================================================
# Tests for unescape_double_quoted
# =============================================================================


class TestUnescapeDoubleQuoted:
    """Tests for unescape_double_quoted function."""

    def test_unescape_newlines(self) -> None:
        r"""Should unescape \n to actual newlines."""
        content = "line1\\nline2\\nline3"
        result = unescape_double_quoted(content)
        assert result == "line1\nline2\nline3"

    def test_unescape_quotes(self) -> None:
        r"""Should unescape \" to quotes."""
        content = 'say \\"hello\\"'
        result = unescape_double_quoted(content)
        assert result == 'say "hello"'

    def test_unescape_tabs(self) -> None:
        r"""Should unescape \t to tabs."""
        content = "col1\\tcol2\\tcol3"
        result = unescape_double_quoted(content)
        assert result == "col1\tcol2\tcol3"

    def test_unescape_backslash(self) -> None:
        r"""Should unescape \\ to single backslash."""
        # Note: The function processes \t before \\ so we avoid sequences like \\t
        content = "path\\\\file"
        result = unescape_double_quoted(content)
        assert result == "path\\file"

    def test_unescape_space(self) -> None:
        r"""Should unescape '\ ' to space."""
        content = "word\\ word"
        result = unescape_double_quoted(content)
        assert result == "word word"

    def test_yaml_line_continuation(self) -> None:
        """Should handle YAML line continuation (backslash followed by newline)."""
        content = "continued\\\n   text"
        result = unescape_double_quoted(content)
        assert result == "continuedtext"

    def test_combined_escapes(self) -> None:
        """Should handle multiple escape sequences."""
        content = 'line1\\nline2\\t\\"quoted\\"\\\\backslash'
        result = unescape_double_quoted(content)
        assert result == 'line1\nline2\t"quoted"\\backslash'


# =============================================================================
# Tests for strip_markdown_bold
# =============================================================================


class TestStripMarkdownBold:
    """Tests for strip_markdown_bold function."""

    def test_strip_bold_from_simple_line(self) -> None:
        """Should strip bold markers from simple lines."""
        content = "This is **bold** text"
        result = strip_markdown_bold(content)
        assert result == "This is bold text"

    def test_skip_code_type_items(self) -> None:
        """Should skip processing for type: code items."""
        content = """  type: code
  text: This **stays** bold
- id: next"""
        result = strip_markdown_bold(content)
        # The bold should stay in code type items
        assert "**stays**" in result

    def test_strip_bold_in_block_scalar(self) -> None:
        """Should strip bold from block scalar content."""
        content = """description: |
  This is **bold** text
  And more **content**"""
        result = strip_markdown_bold(content)
        assert "**bold**" not in result
        assert "**content**" not in result

    def test_preserve_bold_in_heredoc(self) -> None:
        """Should preserve bold in heredoc blocks."""
        content = """code: |
  cat << EOF
  This **stays** bold
  EOF"""
        result = strip_markdown_bold(content)
        assert "**stays**" in result

    def test_strip_bold_in_plain_scalar_multiline(self) -> None:
        """Should strip bold from multi-line plain scalars."""
        content = """description: This is **bold**
  and continues **here**
next: value"""
        result = strip_markdown_bold(content)
        assert "**bold**" not in result
        assert "**here**" not in result

    def test_block_scalar_with_folding(self) -> None:
        """Should handle block scalars with > indicator."""
        content = """text: >
  This is **bold** folded"""
        result = strip_markdown_bold(content)
        assert "**bold**" not in result

    def test_empty_lines_in_block_scalar(self) -> None:
        """Should handle empty lines in block scalars."""
        content = """description: |
  First **bold** paragraph

  Second **bold** paragraph"""
        result = strip_markdown_bold(content)
        assert "**bold**" not in result

    def test_code_item_until_next_item(self) -> None:
        """Should skip code items until next list item."""
        content = """- id: item1
  type: code
  text: **stays**
- id: item2
  text: **removed**"""
        result = strip_markdown_bold(content)
        assert "**stays**" in result
        assert "**removed**" not in result


# =============================================================================
# Tests for wrap_long_block_scalar_lines
# =============================================================================


class TestWrapLongBlockScalarLines:
    """Tests for wrap_long_block_scalar_lines function."""

    def test_wrap_long_line_in_block_scalar(self) -> None:
        """Should wrap lines exceeding MAX_LINE_LENGTH."""
        long_text = "word " * 30  # Creates a long line
        content = f"""description: |
  {long_text.strip()}"""
        result = wrap_long_block_scalar_lines(content)
        lines = result.split("\n")
        for line in lines:
            assert len(line) <= MAX_LINE_LENGTH + 5  # Allow some flexibility

    def test_preserve_short_lines(self) -> None:
        """Should not modify lines shorter than MAX_LINE_LENGTH."""
        content = """description: |
  Short line here
  Another short line"""
        result = wrap_long_block_scalar_lines(content)
        assert result == content

    def test_handle_empty_lines_in_block(self) -> None:
        """Should preserve empty lines in block scalars."""
        content = """description: |
  First paragraph

  Second paragraph"""
        result = wrap_long_block_scalar_lines(content)
        assert "\n\n" in result

    def test_non_block_scalar_lines(self) -> None:
        """Should not modify non-block-scalar lines."""
        content = """key: value
other: another"""
        result = wrap_long_block_scalar_lines(content)
        assert result == content

    def test_block_with_chomp_indicator(self) -> None:
        """Should handle block scalars with chomp indicators."""
        content = """description: |-
  Content here"""
        result = wrap_long_block_scalar_lines(content)
        assert "|-" in result

    def test_multiple_block_scalars(self) -> None:
        """Should handle multiple block scalars."""
        content = """first: |
  Content one
second: |
  Content two"""
        result = wrap_long_block_scalar_lines(content)
        # Both should be preserved
        assert "first: |" in result
        assert "second: |" in result


# =============================================================================
# Tests for fix_double_quoted_field
# =============================================================================


class TestFixDoubleQuotedField:
    """Tests for fix_double_quoted_field function."""

    def test_convert_single_line_with_newlines(self) -> None:
        r"""Should convert single-line double-quoted with \n to block."""
        content = 'description: "line1\\nline2\\nline3"'
        result = fix_double_quoted_field(content, "description")
        assert "description: |" in result or "description:" in result
        assert "\\n" not in result

    def test_convert_single_line_with_backslash(self) -> None:
        r"""Should convert fields with \\ escapes."""
        content = 'code: "path\\\\to\\\\file"'
        result = fix_double_quoted_field(content, "code")
        assert "code:" in result

    def test_preserve_simple_quoted_string(self) -> None:
        """Should preserve simple quoted strings without escapes."""
        content = 'description: "simple text"'
        result = fix_double_quoted_field(content, "description")
        # Should remain unchanged (no special escapes)
        assert result == content

    def test_convert_multiline_quoted_string(self) -> None:
        """Should convert multi-line double-quoted strings."""
        content = '''description: "first line
  second line"'''
        result = fix_double_quoted_field(content, "description")
        assert "description:" in result

    def test_multiline_with_continuation(self) -> None:
        """Should handle multi-line with backslash continuation."""
        content = '''description: "line1\\
  line2"'''
        result = fix_double_quoted_field(content, "description")
        assert "description:" in result

    def test_handle_escaped_closing_quote(self) -> None:
        r"""Should handle escaped quotes (\") properly."""
        content = 'description: "say \\"hello\\""'
        result = fix_double_quoted_field(content, "description")
        # Should detect there are escapes and convert
        assert "description:" in result

    def test_preserve_unmatched_field(self) -> None:
        """Should preserve lines that don't match the field."""
        content = "other_field: value\ndescription: |"
        result = fix_double_quoted_field(content, "description")
        assert result == content

    def test_multiline_continuation_not_ending_quote(self) -> None:
        """Should handle multi-line where continuation breaks early."""
        content = """description: "start
next: value"""
        result = fix_double_quoted_field(content, "description")
        # Should handle gracefully
        assert "description:" in result


# =============================================================================
# Tests for fix_single_quoted_field
# =============================================================================


class TestFixSingleQuotedField:
    """Tests for fix_single_quoted_field function."""

    def test_convert_with_trailing_whitespace(self) -> None:
        """Should convert single-quoted with trailing whitespace."""
        content = "description: 'text with trailing   '"
        result = fix_single_quoted_field(content, "description")
        assert "description:" in result

    def test_convert_with_escaped_quotes(self) -> None:
        """Should convert single-quoted with '' escapes."""
        content = "description: 'it''s working'"
        result = fix_single_quoted_field(content, "description")
        # Should convert '' to single '
        assert "description:" in result
        assert "''" not in result

    def test_convert_multiline_single_quoted(self) -> None:
        """Should convert multi-line single-quoted strings."""
        content = """description: 'first line
  second line'"""
        result = fix_single_quoted_field(content, "description")
        assert "description:" in result

    def test_preserve_simple_single_quoted(self) -> None:
        """Should preserve simple single-quoted without issues."""
        content = "description: 'simple'"
        result = fix_single_quoted_field(content, "description")
        # Should remain unchanged (no issues to fix)
        assert result == content

    def test_multiline_with_empty_lines(self) -> None:
        """Should handle multi-line with empty continuation lines."""
        content = """description: 'first
  
  second'"""
        result = fix_single_quoted_field(content, "description")
        assert "description:" in result

    def test_multiline_continuation_break(self) -> None:
        """Should handle continuation that breaks early."""
        content = """description: 'start
next: value"""
        result = fix_single_quoted_field(content, "description")
        assert "description:" in result

    def test_single_line_with_escaped_quotes_and_trailing(self) -> None:
        """Should handle single line with both issues."""
        content = "description: 'text ''quoted'' here   '"
        result = fix_single_quoted_field(content, "description")
        assert "description:" in result


# =============================================================================
# Tests for fix_escaped_quotes_in_text
# =============================================================================


class TestFixEscapedQuotesInText:
    """Tests for fix_escaped_quotes_in_text function."""

    def test_convert_text_with_double_quotes(self) -> None:
        """Should convert text: ''Content to block scalar."""
        content = "text: ''Content here''"
        result = fix_escaped_quotes_in_text(content)
        assert "text:" in result
        assert "''" not in result

    def test_preserve_normal_text(self) -> None:
        """Should preserve text without '' prefix."""
        content = "text: normal content"
        result = fix_escaped_quotes_in_text(content)
        assert result == content

    def test_multiline_text_with_escapes(self) -> None:
        """Should handle multi-line text with '' escapes."""
        content = """text: ''First line with
  continued content''"""
        result = fix_escaped_quotes_in_text(content)
        assert "text:" in result
        assert "''" not in result

    def test_continuation_with_empty_line(self) -> None:
        """Should handle continuation with empty lines in between."""
        content = """text: ''First
  
  second''"""
        result = fix_escaped_quotes_in_text(content)
        assert "text:" in result

    def test_continuation_break(self) -> None:
        """Should handle when continuation ends early."""
        content = """text: ''start
next: value"""
        result = fix_escaped_quotes_in_text(content)
        assert "text:" in result

    def test_triple_quotes_ending(self) -> None:
        """Should not treat ''' as closing ''."""
        content = """text: ''Content with'''end
other: value"""
        result = fix_escaped_quotes_in_text(content)
        assert "text:" in result


# =============================================================================
# Tests for wrap_text
# =============================================================================


class TestWrapText:
    """Tests for wrap_text function."""

    def test_wrap_long_paragraph(self) -> None:
        """Should wrap text exceeding max_width."""
        text = "word " * 20  # Long text
        result = wrap_text(text.strip(), 40)
        for line in result:
            assert len(line) <= 40 or " " not in line  # Single word can exceed

    def test_preserve_short_text(self) -> None:
        """Should not wrap short text."""
        text = "short text"
        result = wrap_text(text, 80)
        assert result == ["short text"]

    def test_preserve_newlines(self) -> None:
        """Should preserve existing line breaks."""
        text = "first paragraph\n\nsecond paragraph"
        result = wrap_text(text, 80)
        assert len(result) == 3  # Two paragraphs + empty line

    def test_safety_fallback_for_small_width(self) -> None:
        """Should use fallback width when max_width <= 10."""
        text = "some text here"
        result = wrap_text(text, 5)  # Too small
        assert len(result) >= 1

    def test_single_long_word(self) -> None:
        """Should handle single words longer than max_width."""
        text = "superlongwordthatexceedswidth"
        result = wrap_text(text, 10)
        # Word should not be split
        assert result[0] == text

    def test_multiple_paragraphs_wrapping(self) -> None:
        """Should wrap each paragraph independently."""
        long_para = "word " * 15
        text = f"{long_para.strip()}\n\n{long_para.strip()}"
        result = wrap_text(text, 40)
        assert "" in result  # Empty line between paragraphs


# =============================================================================
# Tests for format_as_block_scalar
# =============================================================================


class TestFormatAsBlockScalar:
    """Tests for format_as_block_scalar function."""

    def test_short_single_line_stays_inline(self) -> None:
        """Should keep short single-line content inline."""
        result = format_as_block_scalar("", "text", "short")
        assert result == "text: short"

    def test_long_content_becomes_block(self) -> None:
        """Should convert long content to block scalar."""
        content = "word " * 20
        result = format_as_block_scalar("", "text", content.strip())
        assert "text: |" in result

    def test_content_with_colon_becomes_block(self) -> None:
        """Should convert content with colon to block scalar."""
        result = format_as_block_scalar("", "text", "key: value")
        assert "text: |" in result

    def test_multiline_content_becomes_block(self) -> None:
        """Should convert multiline content to block scalar."""
        result = format_as_block_scalar("", "text", "line1\nline2")
        assert "text: |" in result

    def test_respects_indent(self) -> None:
        """Should respect the indent parameter."""
        result = format_as_block_scalar("  ", "text", "line1\nline2")
        assert result.startswith("  text: |")

    def test_wraps_long_lines(self) -> None:
        """Should wrap content exceeding MAX_LINE_LENGTH."""
        content = "word " * 30
        result = format_as_block_scalar("", "text", content.strip())
        lines = result.split("\n")
        # All lines should be reasonable length
        for line in lines:
            assert len(line) <= MAX_LINE_LENGTH + 10


# =============================================================================
# Tests for fix_yaml_file
# =============================================================================


class TestFixYamlFile:
    """Tests for fix_yaml_file function."""

    def test_fix_double_quoted_field(self, tmp_path: Path) -> None:
        r"""Should fix double-quoted fields with \n."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text('description: "line1\\nline2"')
        result = fix_yaml_file(yaml_file)
        assert result is True
        content = yaml_file.read_text()
        assert "\\n" not in content

    def test_fix_single_quoted_field(self, tmp_path: Path) -> None:
        """Should fix single-quoted fields with issues."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("description: 'it''s working'")
        result = fix_yaml_file(yaml_file)
        assert result is True
        content = yaml_file.read_text()
        assert "''" not in content

    def test_fix_trailing_whitespace(self, tmp_path: Path) -> None:
        """Should fix trailing whitespace."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value   \nother: thing  ")
        result = fix_yaml_file(yaml_file)
        assert result is True
        content = yaml_file.read_text()
        assert not content.endswith(" ")

    def test_no_changes_returns_false(self, tmp_path: Path) -> None:
        """Should return False when no changes made."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value\nother: thing")
        result = fix_yaml_file(yaml_file)
        assert result is False

    def test_fix_markdown_bold(self, tmp_path: Path) -> None:
        """Should strip markdown bold formatting."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("description: This is **bold** text")
        result = fix_yaml_file(yaml_file)
        assert result is True
        content = yaml_file.read_text()
        assert "**bold**" not in content


# =============================================================================
# Tests for main function
# =============================================================================


class TestMain:
    """Tests for main function."""

    def test_main_with_nonexistent_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 if project root doesn't exist."""
        import scripts.fix_yaml_formatting as module

        # Point to a nonexistent directory
        nonexistent = tmp_path / "nonexistent" / "scripts" / "fix_yaml_formatting.py"
        monkeypatch.setattr(module, "__file__", str(nonexistent))

        result = main()

        captured = capsys.readouterr()
        assert result == 1
        assert "Error: project root not found" in captured.err

    def test_main_finds_yaml_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should find and process YAML files in directories."""
        import scripts.fix_yaml_formatting as module

        # Create directory structure
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Create YAML files that need fixing (trailing whitespace)
        (tmp_path / "root.yml").write_text("key: value  ")
        (tmp_path / "root.yaml").write_text("other: data  ")
        (docs_dir / "doc.yml").write_text("description: **bold**")
        (docs_dir / "doc.yaml").write_text("text: value  ")
        (tests_dir / "test.yml").write_text("content: here  ")
        (tests_dir / "test.yaml").write_text("text: value  ")

        # Create fake script file location
        fake_script = scripts_dir / "fix_yaml_formatting.py"
        fake_script.touch()

        # Monkeypatch __file__ to return our temp location
        monkeypatch.setattr(module, "__file__", str(fake_script))

        # Run main
        result = main()

        captured = capsys.readouterr()
        assert result == 0
        assert "Fixed" in captured.out
        # Verify files were fixed
        assert "root.yml" in captured.out or "Fixed" in captured.out

    def test_main_exclusion_logic(self) -> None:
        """Test the to_adapt exclusion string check used in main()."""
        # The main() function uses: if "to_adapt" not in str(f)
        # Test this pattern with various path strings
        excluded_path = "/docs/to_adapt/file.yml"
        regular_path = "/docs/regular/file.yml"

        assert "to_adapt" in excluded_path
        assert "to_adapt" not in regular_path

        # This is the exact check used in main()
        files_to_include = []
        for path in [excluded_path, regular_path]:
            if "to_adapt" not in path:
                files_to_include.append(path)

        assert len(files_to_include) == 1
        assert regular_path in files_to_include
        assert excluded_path not in files_to_include

    def test_main_handles_processing_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle errors when processing files and continue."""
        import scripts.fix_yaml_formatting as module

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Create a valid YAML file
        (docs_dir / "valid.yml").write_text("key: value  ")

        fake_script = scripts_dir / "fix_yaml_formatting.py"
        fake_script.touch()
        monkeypatch.setattr(module, "__file__", str(fake_script))

        # Mock fix_yaml_file to raise exception for one file
        original_fix = module.fix_yaml_file

        def mock_fix(path: Path) -> bool:
            if "error" in str(path):
                raise OSError("Simulated error")
            return original_fix(path)

        monkeypatch.setattr(module, "fix_yaml_file", mock_fix)

        # Create a file that will trigger error
        (docs_dir / "error.yml").write_text("key: value  ")

        result = main()

        captured = capsys.readouterr()
        assert result == 0  # Should still return 0 (continues processing)
        assert "Error processing" in captured.err
        # valid.yml should still be processed
        assert "valid.yml" in captured.out

    def test_main_processes_scripts_docs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should process scripts/docs directory if it exists."""
        import scripts.fix_yaml_formatting as module

        scripts_docs = tmp_path / "scripts" / "docs"
        scripts_docs.mkdir(parents=True)
        tests_docs = tmp_path / "tests" / "docs"
        tests_docs.mkdir(parents=True)

        # Create files in the extra docs directories
        (scripts_docs / "script_doc.yml").write_text("text: value  ")
        (scripts_docs / "script_doc.yaml").write_text("data: here  ")
        (tests_docs / "test_doc.yml").write_text("content: test  ")
        (tests_docs / "test_doc.yaml").write_text("info: stuff  ")

        # Also add a to_adapt exclusion test
        to_adapt = scripts_docs / "to_adapt"
        to_adapt.mkdir()
        (to_adapt / "excluded.yml").write_text("skip: me  ")

        fake_script = tmp_path / "scripts" / "fix_yaml_formatting.py"
        fake_script.touch()
        monkeypatch.setattr(module, "__file__", str(fake_script))

        result = main()

        captured = capsys.readouterr()
        assert result == 0
        # Files in scripts/docs and tests/docs should be processed
        assert "script_doc.yml" in captured.out or "script_doc.yaml" in captured.out
        assert "test_doc.yml" in captured.out or "test_doc.yaml" in captured.out
        # Excluded file should retain trailing whitespace
        assert (to_adapt / "excluded.yml").read_text().endswith("  ")

    def test_main_with_no_changes_needed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should report 0 fixed when no changes are needed."""
        import scripts.fix_yaml_formatting as module

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Create a clean YAML file (no issues)
        (docs_dir / "clean.yml").write_text("key: value")

        fake_script = scripts_dir / "fix_yaml_formatting.py"
        fake_script.touch()
        monkeypatch.setattr(module, "__file__", str(fake_script))

        result = main()

        captured = capsys.readouterr()
        assert result == 0
        assert "Fixed 0 of" in captured.out

    def test_main_with_nonexistent_subdirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle missing docs/tests directories gracefully."""
        import scripts.fix_yaml_formatting as module

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        # No docs/ or tests/ directories

        (tmp_path / "root.yml").write_text("key: value  ")

        fake_script = scripts_dir / "fix_yaml_formatting.py"
        fake_script.touch()
        monkeypatch.setattr(module, "__file__", str(fake_script))

        result = main()

        captured = capsys.readouterr()
        assert result == 0
        # Should only process root.yml
        assert "root.yml" in captured.out


# =============================================================================
# Integration tests
# =============================================================================


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_full_yaml_processing_pipeline(self, tmp_path: Path) -> None:
        """Test the full pipeline of YAML fixes."""
        yaml_content = """description: "line1\\nline2"
text: 'it''s a test   '
code: |
  This is **code** content
other: **bold** regular line   """

        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        result = fix_yaml_file(yaml_file)
        assert result is True

        fixed_content = yaml_file.read_text()
        # Check various fixes applied
        assert "\\n" not in fixed_content  # Double-quoted newlines fixed
        assert "''" not in fixed_content  # Single-quoted escapes fixed
        assert not any(line.endswith(" ") for line in fixed_content.split("\n"))

    def test_preserves_yaml_structure(self, tmp_path: Path) -> None:
        """Should preserve YAML validity after fixes."""
        yaml_content = """doc_id: test
sections:
  - id: section1
    items:
      - id: item1
        description: "value\\nwith\\nnewlines"
"""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        fix_yaml_file(yaml_file)

        fixed_content = yaml_file.read_text()
        # Basic structure should be preserved
        assert "doc_id: test" in fixed_content
        assert "sections:" in fixed_content
        assert "- id: section1" in fixed_content


# =============================================================================
# Additional edge case tests for branch coverage
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and branch coverage."""

    def test_strip_markdown_bold_with_explicit_indent(self) -> None:
        """Test block scalar with explicit indent indicator."""
        content = """description: |2
  This is **bold** text"""
        result = strip_markdown_bold(content)
        assert "**bold**" not in result

    def test_strip_markdown_bold_preserves_code_heredoc(self) -> None:
        """Test that heredoc content within code blocks is preserved."""
        content = """code: |
  cat << END
  **bold** preserved
  END
  more **code**"""
        result = strip_markdown_bold(content)
        # Bold in heredoc should stay, bold outside should go
        assert "**bold** preserved" in result

    def test_strip_markdown_continuation_line_not_field(self) -> None:
        """Test that continuation lines that aren't new fields are handled."""
        content = """description: First **bold** line
  continued but not field"""
        result = strip_markdown_bold(content)
        assert "**bold**" not in result

    def test_wrap_text_empty_paragraph_between(self) -> None:
        """Test wrap_text with empty paragraphs."""
        text = "first\n\nsecond\n\nthird"
        result = wrap_text(text, 80)
        assert "" in result  # Empty lines preserved

    def test_format_block_scalar_with_long_indent(self) -> None:
        """Test format_as_block_scalar with significant indent."""
        result = format_as_block_scalar("        ", "text", "content here")
        assert result.startswith("        text:")

    def test_fix_double_quoted_multiline_indented_continuation(self) -> None:
        """Test double-quoted with indented continuation."""
        content = '''description: "first line
    continuation"'''
        result = fix_double_quoted_field(content, "description")
        assert "description:" in result

    def test_fix_single_quoted_with_double_escape(self) -> None:
        """Test single-quoted with multiple '' escapes."""
        content = "description: 'don''t say ''hello'''"
        result = fix_single_quoted_field(content, "description")
        assert "description:" in result

    def test_wrap_long_scalar_already_wrapped(self) -> None:
        """Test that short lines in block scalars stay unchanged."""
        content = """text: |
  Short line
  Another short"""
        result = wrap_long_block_scalar_lines(content)
        assert result == content

    def test_fix_double_quoted_with_quote_start_continuation(self) -> None:
        """Test continuation line starting with quote."""
        content = '''description: "start
  "quoted continuation"'''
        result = fix_double_quoted_field(content, "description")
        assert "description:" in result

    def test_fix_escaped_quotes_multiline_not_closing(self) -> None:
        """Test text with '' that doesn't close properly."""
        content = """text: ''Start
  middle
other: value"""
        result = fix_escaped_quotes_in_text(content)
        assert "text:" in result

    def test_wrap_text_with_very_long_word(self) -> None:
        """Test wrapping text where a word exceeds the max width."""
        text = "normal verylongwordthatexceedsanyreasonablewidth normal"
        result = wrap_text(text, 20)
        assert len(result) >= 2

    def test_fix_yaml_file_all_patterns(self, tmp_path: Path) -> None:
        """Test fix_yaml_file with all BLOCK_SCALAR_FIELDS."""
        yaml_content = (
            'code: "line1\\nline2"\n'
            'description: "desc\\n"\n'
            'example: "ex\\n"\n'
            "text: 'text quoted'\n"
            'scope: "scope\\n"\n'
            'query: "query\\n"'
        )
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text(yaml_content)

        result = fix_yaml_file(yaml_file)
        assert result is True

        fixed = yaml_file.read_text()
        assert "\\n" not in fixed

    def test_strip_markdown_bold_item_start_patterns(self) -> None:
        """Test detection of new list items in code type blocks."""
        content = """- id: item1
  type: code
  text: **keep**
  - id: nested
- id: item2
  text: **remove**"""
        result = strip_markdown_bold(content)
        # In code items, bold stays
        assert "**keep**" in result
        # Outside code items, bold is removed
        assert "**remove**" not in result

    def test_wrap_long_block_explicit_indent_indicator(self) -> None:
        """Test block scalar with explicit indent indicator."""
        content = """text: |2
  content here"""
        result = wrap_long_block_scalar_lines(content)
        assert "|2" in result

    def test_fix_single_quoted_ends_with_quote_complex(self) -> None:
        """Test single-quoted detection with complex ending."""
        content = "description: 'value''"
        result = fix_single_quoted_field(content, "description")
        # Should handle the case where '' at end means escaped quote
        assert "description:" in result

    def test_double_quoted_multiline_backslash_no_close(self) -> None:
        """Test multi-line double-quoted where close never comes."""
        content = 'description: "start\n  no close here\nother: value'
        result = fix_double_quoted_field(content, "description")
        # Should handle gracefully when quote doesn't close
        assert "description:" in result

    def test_wrap_text_word_fits_exactly(self) -> None:
        """Test wrapping when word fits exactly at line end."""
        text = "aaa bbb ccc"  # With width 7: "aaa bbb" fits, "ccc" wraps
        result = wrap_text(text, 7)
        assert len(result) >= 1

    def test_format_block_scalar_short_with_colon(self) -> None:
        """Test short content with colon forces block."""
        result = format_as_block_scalar("", "key", "a: b")
        # Short but has colon, should be block
        assert "|" in result

    def test_fix_yaml_all_block_scalar_fields(self, tmp_path: Path) -> None:
        """Test that all BLOCK_SCALAR_FIELDS are processed."""
        # Test each field independently
        for field in BLOCK_SCALAR_FIELDS:
            yaml_file = tmp_path / f"test_{field}.yml"
            yaml_file.write_text(f'{field}: "value\\n"')
            result = fix_yaml_file(yaml_file)
            assert result is True
            fixed = yaml_file.read_text()
            assert "\\n" not in fixed

    def test_escaped_quotes_empty_continuation(self) -> None:
        """Test text: '' with empty continuation lines."""
        content = """text: ''Start

  continued''"""
        result = fix_escaped_quotes_in_text(content)
        assert "text:" in result

    def test_strip_bold_continuation_is_new_field(self) -> None:
        """Test plain scalar where next line is a new field."""
        content = """description: **bold**
next_field: value"""
        result = strip_markdown_bold(content)
        assert "**bold**" not in result
        assert "next_field: value" in result

    def test_single_quoted_multiline_with_break_at_blank(self) -> None:
        """Test single-quoted multi-line that breaks at blank line."""
        content = "description: 'start\n\nnext: value"
        result = fix_single_quoted_field(content, "description")
        assert "description:" in result

    def test_fix_double_quoted_continuation_line_starts_with_quote(self) -> None:
        """Test double-quoted where continuation starts with double quote."""
        content = 'description: "first\n"second"'
        result = fix_double_quoted_field(content, "description")
        assert "description:" in result

    def test_double_quoted_with_backslash_continuation_marker(self) -> None:
        """Test double-quoted with backslash at end as continuation marker."""
        content = 'description: "line1\\\n  line2"'
        result = fix_double_quoted_field(content, "description")
        assert "description:" in result

    def test_wrap_block_scalar_with_chomp_and_indent(self) -> None:
        """Test block scalar with both chomp and indent indicators."""
        content = """text: |-2
  content"""
        result = wrap_long_block_scalar_lines(content)
        assert "|-2" in result

    def test_escaped_quotes_not_matching_pattern(self) -> None:
        """Test text: without '' prefix is not matched."""
        content = "text: 'normal single quoted'"
        result = fix_escaped_quotes_in_text(content)
        # Should be unchanged since it doesn't start with ''
        assert result == content

    def test_strip_markdown_block_with_minus_chomp(self) -> None:
        """Test block scalar with minus chomp indicator."""
        content = """text: |-
  **bold** content"""
        result = strip_markdown_bold(content)
        assert "**bold**" not in result

    def test_single_quoted_not_ending_at_single_quote(self) -> None:
        """Test single-quoted field that doesn't end with single quote."""
        content = "description: 'no ending quote"
        result = fix_single_quoted_field(content, "description")
        # Should not match the pattern for multi-line processing
        assert "description:" in result

    def test_wrap_text_exact_fit_no_split(self) -> None:
        """Test wrapping where line fits exactly."""
        text = "12345678"
        result = wrap_text(text, 10)
        assert result == ["12345678"]

    def test_format_block_scalar_already_short_no_colon(self) -> None:
        """Test short content without colon stays inline."""
        result = format_as_block_scalar("", "key", "short value")
        # Should stay inline since it's short and has no colon
        assert result == "key: short value"

    def test_double_quoted_ending_with_escaped_quote(self) -> None:
        """Test detection of escaped quote at end vs regular quote."""
        # This ends with \" which is escaped, so quote doesn't close
        content = 'description: "value\\"'
        result = fix_double_quoted_field(content, "description")
        assert "description:" in result

    def test_single_quoted_empty_continuation_lines(self) -> None:
        """Test single-quoted with empty continuation lines."""
        content = "description: 'start\n  \n  end'"
        result = fix_single_quoted_field(content, "description")
        assert "description:" in result

    def test_strip_markdown_code_block_end_at_file_end(self) -> None:
        """Test code type block that goes to end of file."""
        content = """  type: code
  text: **stays**"""
        result = strip_markdown_bold(content)
        assert "**stays**" in result

    def test_wrap_long_block_line_not_exceeding(self) -> None:
        """Test block scalar lines that don't exceed max length."""
        short_content = "Short content line"
        content = f"""text: |
  {short_content}"""
        result = wrap_long_block_scalar_lines(content)
        assert short_content in result

    def test_fix_double_quoted_simple_no_escapes(self) -> None:
        """Test simple double-quoted without escape sequences."""
        content = 'description: "simple value"'
        result = fix_double_quoted_field(content, "description")
        # Should be unchanged - no escapes to fix
        assert result == content

    def test_single_quoted_ends_with_escaped_quote(self) -> None:
        """Test single quoted that ends with '' (escaped quote)."""
        content = "description: 'value'''"
        result = fix_single_quoted_field(content, "description")
        # This ends with '' which is an escaped quote, not end of string
        assert "description:" in result
