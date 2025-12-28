"""Tests for scripts.prd.chunker module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

# _get_line_number_at_offset is a private function that is critical for accurate
# line-number tracking in chunk metadata. We test it directly to ensure correctness
# of edge cases (empty content, offset clamping) that are difficult to verify through
# the public API alone. Note: This is an implementation detail that may change
# without being considered a breaking API change.
from scripts.prd.chunker import _get_line_number_at_offset, chunk_file, main

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestChunkFileValidation:
    """Tests for chunk_file parameter validation."""

    def test_chunk_size_must_be_positive_for_fixed_mode(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError when chunk_size is not positive for fixed mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content\n\nSome text.")

        with pytest.raises(ValueError, match="chunk_size must be a positive integer"):
            chunk_file(input_file, output_dir, mode="fixed", chunk_size=0)

    def test_chunk_size_negative_for_fixed_mode(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError when chunk_size is negative for fixed mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content\n\nSome text.")

        with pytest.raises(ValueError, match="chunk_size must be a positive integer"):
            chunk_file(input_file, output_dir, mode="fixed", chunk_size=-100)

    def test_min_size_must_be_positive_for_paragraphs_mode(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError when min_size is not positive for paragraphs mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content\n\nSome text.")

        with pytest.raises(ValueError, match="min_size must be a positive integer"):
            chunk_file(input_file, output_dir, mode="paragraphs", min_size=0)

    def test_min_size_negative_for_paragraphs_mode(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError when min_size is negative for paragraphs mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content\n\nSome text.")

        with pytest.raises(ValueError, match="min_size must be a positive integer"):
            chunk_file(input_file, output_dir, mode="paragraphs", min_size=-50)

    def test_valid_chunk_size_for_fixed_mode(self, fs: FakeFilesystem) -> None:
        """Should succeed when chunk_size is a positive integer for fixed mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content\n\nSome text here.")

        result = chunk_file(input_file, output_dir, mode="fixed", chunk_size=200, overlap=50)

        assert result.mode == "fixed"
        assert result.total_chunks >= 1

    def test_valid_min_size_for_paragraphs_mode(self, fs: FakeFilesystem) -> None:
        """Should succeed when min_size is a positive integer for paragraphs mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="First paragraph.\n\nSecond paragraph.")

        result = chunk_file(input_file, output_dir, mode="paragraphs", min_size=10)

        assert result.mode == "paragraphs"
        assert result.total_chunks >= 1

    def test_headers_mode_does_not_validate_chunk_size(self, fs: FakeFilesystem) -> None:
        """Should not raise error for headers mode regardless of chunk_size value."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Header\n\nContent under header.")

        # chunk_size is ignored for headers mode, so even invalid values should work
        result = chunk_file(input_file, output_dir, mode="headers", chunk_size=0)

        assert result.mode == "headers"

    def test_file_not_found_error(self, fs: FakeFilesystem) -> None:
        """Should raise FileNotFoundError when input file does not exist."""
        input_file = Path("/test/nonexistent.md")
        output_dir = Path("/test/output")
        fs.create_dir("/test")

        with pytest.raises(FileNotFoundError, match="Input file not found"):
            chunk_file(input_file, output_dir, mode="headers")

    def test_invalid_mode_error(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError for invalid chunking mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="Test content")

        with pytest.raises(ValueError, match="Invalid chunking mode"):
            chunk_file(input_file, output_dir, mode="invalid")  # type: ignore[arg-type]

    def test_overlap_zero_is_allowed_for_fixed_mode(self, fs: FakeFilesystem) -> None:
        """Should succeed when overlap is zero for fixed mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content\n\nSome text here.")

        result = chunk_file(input_file, output_dir, mode="fixed", chunk_size=2000, overlap=0)

        assert result.mode == "fixed"
        assert result.total_chunks >= 1

    def test_overlap_negative_for_fixed_mode(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError when overlap is negative for fixed mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content\n\nSome text.")

        with pytest.raises(ValueError, match="overlap must be a non-negative integer"):
            chunk_file(input_file, output_dir, mode="fixed", chunk_size=2000, overlap=-50)

    @pytest.mark.parametrize(
        ("chunk_size", "overlap"),
        [
            (100, 100),  # overlap == chunk_size
            (100, 150),  # overlap > chunk_size
        ],
    )
    def test_overlap_must_be_less_than_chunk_size(
        self, fs: FakeFilesystem, chunk_size: int, overlap: int
    ) -> None:
        """Should raise ValueError when overlap >= chunk_size for fixed mode."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content\n\nSome text.")

        with pytest.raises(ValueError, match=r"overlap.*must be less than chunk_size"):
            chunk_file(input_file, output_dir, mode="fixed", chunk_size=chunk_size, overlap=overlap)


class TestParagraphModeLineNumbers:
    """Tests for accurate line number calculation in paragraphs mode."""

    def test_paragraph_mode_with_standard_separators(self, fs: FakeFilesystem) -> None:
        """Should compute correct line numbers with standard \\n\\n separators."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        # Standard double newline separators
        content = "Line 1\nLine 2\n\nLine 4\nLine 5"
        fs.create_file(str(input_file), contents=content)

        result = chunk_file(input_file, output_dir, mode="paragraphs", min_size=1)

        # Should create 2 chunks: lines 1-2 and lines 4-5
        assert result.total_chunks == 2
        assert result.chunks[0].start_line == 1
        assert result.chunks[0].end_line == 2
        assert result.chunks[1].start_line == 4
        assert result.chunks[1].end_line == 5

    def test_paragraph_mode_with_variable_length_separators(self, fs: FakeFilesystem) -> None:
        """Should compute correct line numbers with variable-length separators."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        # Variable-length separators: \n  \n (with spaces) and \n\t\n (with tab)
        content = "Line 1\nLine 2\n  \nLine 4\nLine 5\n\t\nLine 7"
        fs.create_file(str(input_file), contents=content)

        result = chunk_file(input_file, output_dir, mode="paragraphs", min_size=1)

        # Should create 3 chunks with accurate line numbers
        assert result.total_chunks == 3
        assert result.chunks[0].start_line == 1
        assert result.chunks[0].end_line == 2
        assert result.chunks[1].start_line == 4
        assert result.chunks[1].end_line == 5
        assert result.chunks[2].start_line == 7
        assert result.chunks[2].end_line == 7

    def test_paragraph_mode_with_multiple_blank_lines(self, fs: FakeFilesystem) -> None:
        """Should compute correct line numbers with multiple blank lines."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        # Multiple blank lines between paragraphs
        content = "Line 1\n\n\n\nLine 5\nLine 6"
        fs.create_file(str(input_file), contents=content)

        result = chunk_file(input_file, output_dir, mode="paragraphs", min_size=1)

        # Should create 2 chunks
        assert result.total_chunks == 2
        assert result.chunks[0].start_line == 1
        assert result.chunks[0].end_line == 1
        assert result.chunks[1].start_line == 5
        assert result.chunks[1].end_line == 6

    def test_paragraph_mode_single_paragraph(self, fs: FakeFilesystem) -> None:
        """Should handle content with no paragraph separators."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        content = "Line 1\nLine 2\nLine 3"
        fs.create_file(str(input_file), contents=content)

        result = chunk_file(input_file, output_dir, mode="paragraphs", min_size=1)

        assert result.total_chunks == 1
        assert result.chunks[0].start_line == 1
        assert result.chunks[0].end_line == 3


class TestGetLineNumberAtOffset:
    """Tests for _get_line_number_at_offset helper function."""

    def test_empty_content_returns_line_1(self) -> None:
        """Should return line 1 for empty content regardless of offset."""
        assert _get_line_number_at_offset("", 0) == 1
        assert _get_line_number_at_offset("", 10) == 1
        assert _get_line_number_at_offset("", -5) == 1

    def test_offset_clamped_to_valid_range(self) -> None:
        """Should clamp offset to valid range [0, len(content)]."""
        content = "Line 1\nLine 2\nLine 3"
        # Offset beyond content length should be clamped to len(content)
        assert _get_line_number_at_offset(content, 100) == 3
        # Negative offset should be clamped to 0
        assert _get_line_number_at_offset(content, -10) == 1

    def test_offset_at_end_of_content(self) -> None:
        """Should return correct line for offset == len(content) (end-of-file position)."""
        content = "Line 1\nLine 2\nLine 3"
        # offset == len(content) is the "point just past the last character"
        # This should return line 3, not be incorrectly clamped
        assert _get_line_number_at_offset(content, len(content)) == 3

    def test_offset_at_end_of_multiline_content_with_trailing_newline(self) -> None:
        """Should return correct line for end-of-file with trailing newline."""
        content = "Line 1\nLine 2\n"
        # With trailing newline, offset == len(content) should be line 3
        # (the implicit empty line after the trailing newline)
        assert _get_line_number_at_offset(content, len(content)) == 3

    def test_offset_at_start_of_content(self) -> None:
        """Should return line 1 for offset at start of content."""
        content = "Line 1\nLine 2"
        assert _get_line_number_at_offset(content, 0) == 1

    def test_offset_on_second_line(self) -> None:
        """Should return correct line number for offset on second line."""
        content = "Line 1\nLine 2"
        # Offset 7 is 'L' in 'Line 2'
        assert _get_line_number_at_offset(content, 7) == 2


class TestEdgeCases:
    """Tests for edge cases: empty files, large files, and Unicode content."""

    def test_empty_file_handling(self, fs: FakeFilesystem) -> None:
        """Should handle empty input file without raising and return zero chunks."""
        input_file = Path("/test/empty.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="")

        result = chunk_file(input_file, output_dir, mode="fixed", chunk_size=100, overlap=10)

        assert result.total_chunks == 0
        assert result.chunks == []

    def test_empty_file_headers_mode(self, fs: FakeFilesystem) -> None:
        """Should return empty manifest for empty content in headers mode.

        Regression test: content.split("\\n") yields [""] for empty strings,
        which previously created a phantom chunk with empty content.
        """
        input_file = Path("/test/empty.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="")

        result = chunk_file(input_file, output_dir, mode="headers")

        assert result.total_chunks == 0
        assert result.chunks == []
        assert result.mode == "headers"
        # Verify no chunk files were written
        chunk_files = list(output_dir.glob("chunk_*.md"))
        assert chunk_files == []

    def test_whitespace_only_file_headers_mode(self, fs: FakeFilesystem) -> None:
        """Should return empty manifest for whitespace-only content in headers mode."""
        input_file = Path("/test/whitespace.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="   \n\n\t  \n  ")

        result = chunk_file(input_file, output_dir, mode="headers")

        assert result.total_chunks == 0
        assert result.chunks == []
        assert result.mode == "headers"

    def test_large_file_stress(self, fs: FakeFilesystem) -> None:
        """Should handle very large files and produce multiple chunks correctly."""
        input_file = Path("/test/large.md")
        output_dir = Path("/test/output")
        # Generate a large file with many lines
        line = "This is a test line with some content for stress testing.\n"
        num_lines = 5000
        content = line * num_lines
        fs.create_file(str(input_file), contents=content)

        result = chunk_file(input_file, output_dir, mode="fixed", chunk_size=500, overlap=50)

        # Should produce multiple chunks
        assert result.total_chunks > 1

        # Total character count from all chunks should match source length
        # (accounting for overlap between chunks)
        total_chunk_chars = sum(chunk.char_count for chunk in result.chunks)
        # Each chunk except the last overlaps by 'overlap' characters with the next
        # So total_chunk_chars >= len(content) due to overlap
        assert total_chunk_chars >= len(content)

    def test_unicode_content_preserved(self, fs: FakeFilesystem) -> None:
        """Should preserve diverse Unicode content in chunks."""
        input_file = Path("/test/unicode.md")
        output_dir = Path("/test/output")
        # Diverse Unicode: emoji, accented chars, CJK, Arabic, Cyrillic, Greek
        unicode_content = (
            "Hello World!\n\n"
            "Accented: caf\u00e9 r\u00e9sum\u00e9 na\u00efve \u00fc\u00f1\u00ed\u00e7\u00f8d\u00e9\n\n"
            "Emoji: \U0001f680 \u2764\ufe0f \u2b50 \u2705 \U0001f389\n\n"
            "CJK: \u4e2d\u6587 \u65e5\u672c\u8a9e \ud55c\uad6d\uc5b4\n\n"
            "Arabic: \u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645\n\n"
            "Cyrillic: \u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440\n\n"
            "Greek: \u03b1\u03b2\u03b3\u03b4 \u03a9\u03a3\u03a0\n"
        )
        fs.create_file(str(input_file), contents=unicode_content)

        result = chunk_file(input_file, output_dir, mode="paragraphs", min_size=10)

        # Should produce at least one chunk
        assert result.total_chunks >= 1

        # Read all chunk content to verify Unicode preservation
        all_chunk_content = "".join(
            (output_dir / chunk.file).read_text(encoding="utf-8") for chunk in result.chunks
        )

        # Verify specific Unicode characters are preserved across chunks
        # Emoji
        assert "\U0001f680" in all_chunk_content  # rocket emoji
        assert "\u2764" in all_chunk_content  # heart emoji (with or without variation selector)

        # Accented characters
        assert "caf\u00e9" in all_chunk_content  # cafe with accent
        assert "r\u00e9sum\u00e9" in all_chunk_content  # resume with accents

        # CJK characters
        assert "\u4e2d\u6587" in all_chunk_content  # Chinese
        assert "\u65e5\u672c\u8a9e" in all_chunk_content  # Japanese
        assert "\ud55c\uad6d\uc5b4" in all_chunk_content  # Korean

        # Arabic
        assert "\u0645\u0631\u062d\u0628\u0627" in all_chunk_content  # Arabic greeting

        # Cyrillic
        assert "\u041f\u0440\u0438\u0432\u0435\u0442" in all_chunk_content  # Russian "Privet"

        # Greek
        assert (
            "\u03b1\u03b2\u03b3\u03b4" in all_chunk_content
        )  # Greek letters alpha beta gamma delta


class TestMainExceptionHandling:
    """Tests for main function exception handling and structured error output."""

    def test_unexpected_exception_emits_structured_error(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should emit structured JSON error to stderr on unexpected exceptions."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Mock chunk_file to raise an unexpected exception
        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        # Check stderr for structured error output
        captured = capsys.readouterr()
        stderr_lines = captured.err.strip().split("\n")

        # The last line should be a JSON object with type and message
        last_line = stderr_lines[-1]
        error_info = json.loads(last_line)

        assert error_info["type"] == "RuntimeError"
        assert error_info["message"] == "Simulated unexpected error"

    def test_structured_error_contains_exception_type_and_message(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should include both exception type name and message in structured error."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Mock chunk_file to raise a custom exception type
        class CustomChunkerError(Exception):
            pass

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=CustomChunkerError("Custom error message"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        stderr_lines = captured.err.strip().split("\n")
        last_line = stderr_lines[-1]
        error_info = json.loads(last_line)

        assert error_info["type"] == "CustomChunkerError"
        assert error_info["message"] == "Custom error message"

    def test_traceback_not_printed_by_default(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should NOT print traceback by default for unexpected exceptions."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Ensure no debug environment variable is set
        monkeypatch.delenv("CHUNKER_DEBUG", raising=False)

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        # Should have JSON error but NO traceback
        assert "Traceback" not in captured.err
        assert '"type": "RuntimeError"' in captured.err
        assert '"message": "Simulated unexpected error"' in captured.err

    def test_traceback_printed_with_verbose_flag(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should print traceback when --verbose flag is provided."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Ensure no debug environment variable is set
        monkeypatch.delenv("CHUNKER_DEBUG", raising=False)

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                [
                    "chunker",
                    str(input_file),
                    "--output-dir",
                    str(output_dir),
                    "--mode",
                    "headers",
                    "--verbose",
                ],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        # Should have BOTH JSON error AND traceback
        assert "Traceback" in captured.err
        assert '"type": "RuntimeError"' in captured.err
        assert '"message": "Simulated unexpected error"' in captured.err

    @pytest.mark.parametrize("debug_value", ["1", "true", "yes", "TRUE", "Yes"])
    def test_traceback_printed_with_chunker_debug_env_var(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        debug_value: str,
    ) -> None:
        """Should print traceback when CHUNKER_DEBUG environment variable is set."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Set the debug environment variable
        monkeypatch.setenv("CHUNKER_DEBUG", debug_value)

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        # Should have BOTH JSON error AND traceback
        assert "Traceback" in captured.err
        assert '"type": "RuntimeError"' in captured.err

    def test_traceback_not_printed_with_invalid_debug_env_value(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should NOT print traceback when CHUNKER_DEBUG has invalid value."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Set the debug environment variable to an invalid value
        monkeypatch.setenv("CHUNKER_DEBUG", "false")

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        # Should have JSON error but NO traceback
        assert "Traceback" not in captured.err
        assert '"type": "RuntimeError"' in captured.err
