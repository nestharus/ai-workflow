"""QA Strategy Step 1 validation tests for document ingestion.

These tests validate the Step 1 requirements from QA_strategy.md lines 80-91:
- Expected: Canonical UTF-8 string produced
- Expected: Character offsets are valid indices into canonical string
- Expected: No format artifacts remain (PDF control chars, JSON syntax)
- Expected: Valid UTF-8 encoding after normalization

Unexpected conditions (STOP + REPORT):
- Encoding errors that cannot be recovered
- Offset out of bounds
- Format artifacts remain after processing
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.knowledge.atomic_fact_models import WorkRegion
from scripts.knowledge.document_ingestion import (
    check_utf8_encoding,
    create_canonical_string,
    ingest_document,
    initialize_work_regions,
    validate_ingestion,
)
from scripts.tests.knowledge.conftest import make_work_region

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem
    from pytest_mock import MockerFixture

# Maximum number of digits for standalone page number detection (matches
# _PAGE_NUMBER_PATTERN in document_ingestion.py which uses \d{1,4})
PAGE_NUMBER_MAX_DIGITS: int = 4


def is_page_number(text: str) -> bool:
    """Check if text is a standalone page number artifact.

    A page number artifact is defined as a string that:
    - Is non-empty after stripping whitespace
    - Contains only digits
    - Has at most PAGE_NUMBER_MAX_DIGITS digits

    Args:
        text: The text to check (will be stripped of whitespace).

    Returns:
        True if text appears to be a page number artifact, False otherwise.
    """
    stripped = text.strip() if text else ""
    return bool(stripped and stripped.isdigit() and len(stripped) <= PAGE_NUMBER_MAX_DIGITS)


class TestQAStep1CanonicalStringProduced:
    """Tests for QA Step 1: Canonical UTF-8 string production."""

    def test_qa_step1_canonical_string_produced(self, fs: FakeFilesystem) -> None:
        """Verify canonical UTF-8 string is produced from text document.

        QA Step 1 Expected: Canonical UTF-8 string produced.
        Input: Sample text document with various characters.
        Assert: canonical_string is valid UTF-8, non-empty.
        """
        # Create sample text file with various characters
        test_content = "Hello, World!\nThis is a test document.\nWith multiple lines."
        test_file = Path("/test/sample.txt")
        fs.create_file(str(test_file), contents=test_content)

        canonical, doc_id, _, _, validation = ingest_document(test_file)

        # Assert canonical string is non-empty
        assert canonical, "Canonical string should not be empty and must be valid UTF-8"

        # Assert valid UTF-8 encoding using production validation output
        assert validation["encoding_valid"] is True, (
            "Encoding validation should pass for valid UTF-8 content"
        )

        # Assert doc_id is generated
        assert doc_id.startswith("text_"), "Doc ID should start with format prefix"


class TestQAStep1ValidCharacterOffsets:
    """Tests for QA Step 1: Valid character offsets."""

    def test_qa_step1_valid_character_offsets(self, fs: FakeFilesystem) -> None:
        """Verify character offsets are valid indices into canonical string.

        QA Step 1 Expected: Character offsets are valid indices into canonical string.
        Input: Sample document.
        Assert: All work region offsets within bounds [0, len(canonical_string)].
        Assert: region start < region end.
        """
        test_content = "Sample document content for testing offsets."
        test_file = Path("/test/offsets.txt")
        fs.create_file(str(test_file), contents=test_content)

        canonical, _, regions, _, _ = ingest_document(test_file)

        # Assert all work region offsets satisfy the validator contract:
        # 0 <= start < end <= len(canonical)
        # This ensures regions are non-empty and within bounds
        for region in regions:
            assert 0 <= region.start_char < len(canonical), (
                f"Region start_char {region.start_char} out of bounds [0, {len(canonical)})"
            )
            assert 0 < region.end_char <= len(canonical), (
                f"Region end_char {region.end_char} out of bounds (0, {len(canonical)}]"
            )
            # Assert start < end (valid region)
            assert region.start_char < region.end_char, (
                f"Region start {region.start_char} should be less than end {region.end_char}"
            )


class TestQAStep1NoFormatArtifacts:
    """Tests for QA Step 1: No format artifacts remain."""

    def test_qa_step1_no_format_artifacts_pdf(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Verify PDF format artifacts are removed from canonical string.

        QA Step 1 Expected: No format artifacts remain.
        Input: PDF with form feed chars, page numbers at page boundaries.
        Assert: Canonical string contains no form feed chars, no isolated page numbers.
        Mock: pypdf.PdfReader to return text with artifacts.

        Note: Page numbers are placed at actual page boundaries (first/last line)
        to match typical PDF structure. Numbered list content in the middle of
        pages is preserved.
        """
        # Create a fake PDF file (content doesn't matter, we mock the reader)
        test_file = Path("/test/document.pdf")
        fs.create_file(str(test_file), contents=b"fake pdf content")

        # Mock pypdf.PdfReader with multiple pages that have page numbers at boundaries
        # Page 1: page number "1" at the very first line (top-of-page placement)
        mock_page1 = mocker.MagicMock()
        mock_page1.extract_text.return_value = "1\nFirst page content\nMore text here.\f"

        # Page 2: page number "2" at the very last line (bottom-of-page placement)
        mock_page2 = mocker.MagicMock()
        mock_page2.extract_text.return_value = "Second page content\nActual text here.\n2"

        mock_reader = mocker.MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        canonical, _, _, _, _ = ingest_document(test_file)

        # Assert canonical string is non-empty (guards against content being stripped)
        assert canonical and len(canonical) > 0, (
            "Canonical string should be non-empty after PDF ingestion"
        )

        # Assert no form feed characters
        assert "\f" not in canonical, "Canonical string should not contain form feed (\\f)"

        # Assert no isolated page numbers at page boundaries
        # Page numbers "1" and "2" should be removed since they're at page edges
        lines = canonical.split("\n")
        for i, line in enumerate(lines):
            if is_page_number(line):
                stripped = line.strip()
                pytest.fail(
                    f"Line {i} appears to be a page number artifact "
                    f"(<= {PAGE_NUMBER_MAX_DIGITS} digits): '{stripped}'"
                )

    def test_qa_step1_no_format_artifacts_json(self, fs: FakeFilesystem) -> None:
        """Verify JSON structural syntax is removed from canonical string.

        QA Step 1 Expected: No JSON structural syntax (braces/brackets).
        Input: JSON file with nested structure.
        Assert: Canonical string contains only extracted scalar values, no JSON delimiters.

        Note: Quotes are not explicitly tested because extracted string values may
        legitimately contain quotation marks as part of their content.
        """
        json_content = {
            "title": "Test Document",
            "content": "This is the main content.",
            "metadata": {"author": "Test Author", "version": 1.0},
            "items": ["First item", "Second item"],
        }
        test_file = Path("/test/document.json")
        fs.create_file(str(test_file), contents=json.dumps(json_content, indent=2))

        canonical, _, _, _, _ = ingest_document(test_file)

        # Assert no JSON syntax characters remain
        assert "{" not in canonical, "Canonical string should not contain JSON braces"
        assert "}" not in canonical, "Canonical string should not contain JSON braces"
        assert "[" not in canonical, "Canonical string should not contain JSON brackets"
        assert "]" not in canonical, "Canonical string should not contain JSON brackets"

        # Assert string values are extracted
        assert "Test Document" in canonical, "Should contain title string value"
        assert "This is the main content." in canonical, "Should contain content string value"
        assert "Test Author" in canonical, "Should contain author string value"
        assert "First item" in canonical, "Should contain first item string value"
        assert "Second item" in canonical, "Should contain second item string value"


class TestQAStep1EncodingValid:
    """Tests for QA Step 1: Valid UTF-8 encoding."""

    def test_qa_step1_encoding_valid(self, fs: FakeFilesystem) -> None:
        """Verify valid UTF-8 encoding after normalization.

        QA Step 1 Expected: Valid UTF-8 encoding after normalization.
        Input: Document with mixed Unicode (combining characters, emoji, etc.).
        Assert: Canonical string encodes/decodes as UTF-8 without errors.
        Assert: NFC normalization applied.
        """
        # Text with combining characters (e should combine with acute accent)
        # Also includes emoji and various Unicode
        combining_text = "cafe\u0301"  # e + combining acute accent
        full_content = f"Unicode test: {combining_text}\nEmoji: \U0001f600\nSymbols: \u2022 \u2013 \u201c\u201d"
        test_file = Path("/test/unicode.txt")
        fs.create_file(str(test_file), contents=full_content)

        canonical, _, _, _, _ = ingest_document(test_file)

        # Assert UTF-8 encode/decode without errors
        try:
            encoded = canonical.encode("utf-8")
            decoded = encoded.decode("utf-8")
            assert decoded == canonical, "UTF-8 round-trip should preserve content"
        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            pytest.fail(f"UTF-8 encoding error: {e}")

        # Assert NFC normalization is applied
        # In NFC, e + combining acute accent becomes e-acute (single char)
        assert canonical == unicodedata.normalize("NFC", canonical), (
            "Canonical string should be NFC normalized"
        )

        # Verify the combining character was normalized
        # cafe\u0301 (5 chars) should become caf\u00e9 (4 chars) in NFC
        assert "caf\u00e9" in canonical, (
            "Combining characters should be normalized to composed form"
        )


class TestQAStep1UnexpectedConditions:
    """Tests for QA Step 1 unexpected conditions (STOP + REPORT scenarios)."""

    def test_qa_step1_encoding_happy_path(self) -> None:
        """Verify encoding validation passes for valid UTF-8 strings.

        QA Step 1 Expected: Valid UTF-8 encoding after normalization.
        Input: Standard UTF-8 string with work regions.
        Assert: validate_ingestion returns encoding_valid=True.

        Note: In Python 3, all str objects are valid Unicode by design,
        so this test verifies the validation logic correctly returns True
        for well-formed input.
        """
        canonical = "Valid UTF-8 string"
        regions = [make_work_region(len(canonical))]

        result = validate_ingestion(canonical, regions)

        assert result["encoding_valid"] is True, "Valid UTF-8 should pass encoding validation"

    def test_qa_step1_unexpected_encoding_error(self, mocker: MockerFixture) -> None:
        """Verify STOP + REPORT for encoding errors.

        QA Step 1 Unexpected: Encoding errors that cannot be recovered.
        Input: Mock check_utf8_encoding to return False.
        Assert: validate_ingestion returns encoding_valid=False.

        Note: In Python 3, all str objects are valid Unicode by design, so we cannot
        create a string that fails UTF-8 encoding. We mock the check_utf8_encoding
        helper function to simulate an encoding failure.
        """
        canonical = "Test string"
        regions = [make_work_region(len(canonical))]

        # Mock check_utf8_encoding to return False, simulating an encoding error
        mocker.patch(
            "scripts.knowledge.document_ingestion.check_utf8_encoding",
            return_value=False,
        )

        result = validate_ingestion(canonical, regions)

        assert result["encoding_valid"] is False, "Encoding error should cause encoding_valid=False"
        # Verify other validations still work correctly
        assert result["offsets_valid"] is True
        assert result["artifacts_removed"] is True

    def test_qa_step1_unexpected_offset_out_of_bounds(self) -> None:
        """Verify STOP + REPORT for offset out of bounds.

        QA Step 1 Unexpected: Offset out of bounds.
        Input: Manually create work region with invalid offsets.
        Assert: validate_ingestion returns offsets_valid=False.
        """
        canonical = "Short text"
        # Create region with end_char beyond string length
        invalid_regions = [
            make_work_region(
                1000,  # Way beyond string length
                region_id="invalid_region",
            )
        ]

        result = validate_ingestion(canonical, invalid_regions)

        assert result["offsets_valid"] is False, (
            "Offsets beyond string length should fail validation"
        )

    def test_qa_step1_unexpected_format_artifacts_remain(self) -> None:
        """Verify STOP + REPORT for format artifacts remaining.

        QA Step 1 Unexpected: Format artifacts remain after processing.
        Input: Canonical string with form feed or null bytes that weren't removed.
        Assert: validate_ingestion returns artifacts_removed=False.
        """
        # String with form feed character (artifact that should have been removed)
        canonical_with_artifact = "Text with\f form feed artifact"
        regions = [make_work_region(len(canonical_with_artifact))]

        result = validate_ingestion(canonical_with_artifact, regions)

        assert result["artifacts_removed"] is False, (
            "String with form feed should fail artifact validation"
        )

        # Also test null byte detection
        canonical_with_null = "Text with\x00 null byte"
        regions_null = [make_work_region(len(canonical_with_null))]

        result_null = validate_ingestion(canonical_with_null, regions_null)

        assert result_null["artifacts_removed"] is False, (
            "String with null byte should fail artifact validation"
        )


class TestQAStep1FullPipeline:
    """Tests for QA Step 1 full pipeline validation."""

    def test_qa_step1_full_pipeline_text_validates(self, fs: FakeFilesystem) -> None:
        """Verify full pipeline validates for text files.

        QA Step 1: Run full ingest_document pipeline on text file.
        Input: Real text file content.
        Assert: All validation results are True.
        """
        test_content = """# Sample Document

This is a sample document for testing the ingestion pipeline.
It contains multiple paragraphs with various content.

## Section 1

First section content with some technical terms like API and UTF-8.

## Section 2

Second section with more content.
- Bullet point 1
- Bullet point 2

The end of the document.
"""
        test_file = Path("/test/real_document.txt")
        fs.create_file(str(test_file), contents=test_content)

        _, _, _, _, validation = ingest_document(test_file)

        # Assert all validations pass
        assert validation["encoding_valid"] is True, "Encoding should be valid"
        assert validation["offsets_valid"] is True, "Offsets should be valid"
        assert validation["artifacts_removed"] is True, "Artifacts should be removed"

        # Verify all validations passed
        all_valid = all(validation.values())
        assert all_valid, f"All validations should pass, got: {validation}"

    def test_qa_step1_full_pipeline_json_validates(self, fs: FakeFilesystem) -> None:
        """Verify full pipeline validates for JSON files.

        QA Step 1: Run full ingest_document pipeline on JSON file.
        Input: Real JSON file with nested structure.
        Assert: All validation results are True.
        """
        json_content = {
            "document": {
                "title": "JSON Test Document",
                "version": "1.0",
                "sections": [
                    {
                        "id": "section-1",
                        "heading": "Introduction",
                        "content": "This is the introduction section.",
                    },
                    {
                        "id": "section-2",
                        "heading": "Main Content",
                        "content": "This is the main content with technical details.",
                        "items": [
                            "First nested item",
                            "Second nested item with more text",
                        ],
                    },
                ],
            },
            "metadata": {
                "author": "Test Author",
                "created": "2025-01-15",
                "tags": ["test", "json", "validation"],
            },
        }
        test_file = Path("/test/real_document.json")
        fs.create_file(str(test_file), contents=json.dumps(json_content, indent=2))

        canonical, _, _, _, validation = ingest_document(test_file)

        # Assert all validations pass
        assert validation["encoding_valid"] is True, "Encoding should be valid"
        assert validation["offsets_valid"] is True, "Offsets should be valid"
        assert validation["artifacts_removed"] is True, "Artifacts should be removed"

        # Verify all validations passed
        all_valid = all(validation.values())
        assert all_valid, f"All validations should pass, got: {validation}"

        # Verify string content was extracted (no JSON syntax)
        assert "JSON Test Document" in canonical, "Title should be extracted"
        assert "Introduction" in canonical, "Section heading should be extracted"
        assert "{" not in canonical, "JSON braces should not be in canonical string"


class TestCreateCanonicalString:
    """Unit tests for create_canonical_string function."""

    def test_nfc_normalization_applied(self) -> None:
        """Verify NFC normalization is applied to input text."""
        # e + combining acute = cafe with combining accent (5 chars)
        input_text = "cafe\u0301"  # Should become caf\u00e9 (4 chars)

        result, _ = create_canonical_string(input_text)

        # Verify NFC normalization
        assert result == unicodedata.normalize("NFC", input_text)
        assert "caf\u00e9" in result, "Should contain composed e-acute character"

    def test_whitespace_normalization(self) -> None:
        """Verify whitespace is normalized (multiple spaces collapsed)."""
        input_text = "Word   with    multiple   spaces"

        result, _ = create_canonical_string(input_text)

        assert "   " not in result, "Multiple spaces should be collapsed"
        assert result == "Word with multiple spaces"

    def test_line_ending_normalization(self) -> None:
        """Verify line endings are normalized to LF."""
        input_text = "Line 1\r\nLine 2\rLine 3\nLine 4"

        result, _ = create_canonical_string(input_text)

        assert "\r\n" not in result, "CRLF should be normalized"
        assert "\r" not in result, "CR should be normalized"
        assert result == "Line 1\nLine 2\nLine 3\nLine 4"

    def test_control_characters_removed(self) -> None:
        """Verify control characters are removed except LF and TAB.

        Note: TABs are preserved as whitespace but then normalized (collapsed with
        spaces) to a single space character per the whitespace normalization step.
        """
        # Include various control characters
        input_text = "Text\x00with\x01control\x02chars\t\nbut\fkeep\ttab\nand\nnewline"

        result, _ = create_canonical_string(input_text)

        # Null, SOH, STX should be removed
        assert "\x00" not in result, "Null byte should be removed"
        assert "\x01" not in result, "SOH should be removed"
        assert "\x02" not in result, "STX should be removed"
        assert "\f" not in result, "Form feed should be removed"

        # LF should be preserved
        assert "\n" in result, "Newline should be preserved"

        # TABs are preserved initially but normalized to spaces along with other whitespace
        # The important thing is they're not removed as control chars but treated as whitespace
        # "keep\ttab" becomes "keep tab" (tab collapsed with adjacent text)
        assert "keep tab" in result, "Tab should be treated as whitespace (normalized to space)"

    def test_strip_leading_trailing_whitespace(self) -> None:
        """Verify leading and trailing whitespace is stripped."""
        input_text = "   \n  Content here  \n   "

        result, _ = create_canonical_string(input_text)

        assert not result.startswith(" "), "Leading spaces should be stripped"
        assert not result.endswith(" "), "Trailing spaces should be stripped"
        assert not result.startswith("\n"), "Leading newlines should be stripped"
        assert not result.endswith("\n"), "Trailing newlines should be stripped"
        assert result == "Content here"


class TestCheckUtf8Encoding:
    """Unit tests for check_utf8_encoding function."""

    def test_valid_ascii_string_passes(self) -> None:
        """Verify simple ASCII string passes encoding check."""
        result = check_utf8_encoding("Hello, World!")
        assert result is True

    def test_valid_unicode_string_passes(self) -> None:
        """Verify Unicode string with various characters passes."""
        text = "Unicode: \u00e9\u00e8\u00ea \U0001f600 \u2022 \u2013"
        result = check_utf8_encoding(text)
        assert result is True

    def test_empty_string_passes(self) -> None:
        """Verify empty string passes encoding check."""
        result = check_utf8_encoding("")
        assert result is True

    def test_nfc_normalized_string_passes(self) -> None:
        """Verify NFC normalized string passes encoding check."""
        text = unicodedata.normalize("NFC", "caf\u00e9")
        result = check_utf8_encoding(text)
        assert result is True


class TestInitializeWorkRegions:
    """Unit tests for initialize_work_regions function."""

    def test_creates_single_region_spanning_document(self) -> None:
        """Verify a single work region is created spanning the entire document."""
        canonical = "Document content here"
        doc_id = "test_doc_123"

        regions = initialize_work_regions(canonical, doc_id)

        assert len(regions) == 1, "Should create exactly one region"
        assert regions[0].start_char == 0, "Region should start at 0"
        assert regions[0].end_char == len(canonical), "Region should end at string length"
        assert regions[0].doc_id == doc_id, "Region should have correct doc_id"
        assert regions[0].is_processed is False, "Region should be unprocessed initially"

    def test_region_id_includes_doc_id(self) -> None:
        """Verify region_id includes the doc_id."""
        canonical = "Content"
        doc_id = "test_doc_456"

        regions = initialize_work_regions(canonical, doc_id)

        assert doc_id in regions[0].region_id, "Region ID should contain doc_id"

    def test_created_at_timestamp_present(self) -> None:
        """Verify created_at timestamp is present and valid format."""
        canonical = "Content"
        doc_id = "test_doc"

        regions = initialize_work_regions(canonical, doc_id)

        assert regions[0].created_at is not None, "Region should have created_at field"
        # Should be ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ
        created_at = regions[0].created_at
        assert "T" in created_at, "Timestamp should be ISO 8601 format"
        assert created_at.endswith("Z"), "Timestamp should end with Z (UTC)"

    def test_chunk_size_zero_creates_single_region(self) -> None:
        """Verify chunk_size=0 creates a single region covering entire document.

        When chunk_size is set to 0, chunking is disabled and a single region
        should be returned regardless of document length. This tests that
        chunk_size=0 does not cause an infinite loop or unexpected behavior.
        """
        # Create a document larger than the default chunk size
        canonical = "This is a test sentence. " * 2000  # ~50000 chars
        doc_id = "test_doc_chunk_zero"

        regions = initialize_work_regions(canonical, doc_id, chunk_size=0)

        # Verify single region is created
        assert len(regions) == 1, "chunk_size=0 should create exactly one region"
        assert regions[0].start_char == 0, "Region should start at 0"
        assert regions[0].end_char == len(canonical), "Region should end at string length"
        assert regions[0].doc_id == doc_id, "Region should have correct doc_id"
        assert doc_id in regions[0].region_id, "Region ID should contain doc_id"
        assert regions[0].is_processed is False, "Region should be unprocessed initially"
        # Verify created_at is present and ISO 8601 formatted
        assert regions[0].created_at is not None, "Region should have created_at field"
        assert "T" in regions[0].created_at, "Timestamp should be ISO 8601 format"
        assert regions[0].created_at.endswith("Z"), "Timestamp should end with Z (UTC)"

    def test_large_document_produces_multiple_regions_with_sentence_boundaries(
        self,
    ) -> None:
        """Verify large documents produce multiple regions at sentence boundaries.

        For documents exceeding chunk_size, regions should be split at sentence
        boundaries (using NLTK) to preserve coherent text spans. Each region
        should be contiguous and non-overlapping.
        """
        # Create a document with clear sentence boundaries
        # Each sentence is ~50 chars, we'll use a small chunk_size to force splits
        sentences = [
            "This is the first sentence in our document.",
            "Here is another sentence with more content.",
            "A third sentence follows the previous ones.",
            "The fourth sentence adds additional context.",
            "Finally we have a fifth concluding sentence.",
        ]
        canonical = " ".join(sentences)
        doc_id = "test_doc_large"
        # Use small chunk_size to force multiple regions
        chunk_size = 100

        regions = initialize_work_regions(canonical, doc_id, chunk_size=chunk_size)

        # Should produce multiple regions
        assert len(regions) > 1, "Large document should produce multiple regions"

        # Verify regions are contiguous and non-overlapping
        for i in range(len(regions) - 1):
            assert regions[i].end_char == regions[i + 1].start_char, (
                f"Region {i} end ({regions[i].end_char}) should equal "
                f"region {i + 1} start ({regions[i + 1].start_char})"
            )

        # Verify first region starts at 0
        assert regions[0].start_char == 0, "First region should start at 0"

        # Verify last region ends at document length
        assert regions[-1].end_char == len(canonical), "Last region should end at document length"

        # Verify all regions have valid properties
        for idx, region in enumerate(regions):
            assert region.doc_id == doc_id, f"Region {idx} should have correct doc_id"
            assert doc_id in region.region_id, f"Region {idx} ID should contain doc_id"
            assert region.is_processed is False, f"Region {idx} should be unprocessed initially"
            assert region.created_at is not None, f"Region {idx} should have created_at field"
            assert "T" in region.created_at, f"Region {idx} timestamp should be ISO 8601 format"
            assert region.created_at.endswith("Z"), (
                f"Region {idx} timestamp should end with Z (UTC)"
            )
            # Verify valid offsets
            assert 0 <= region.start_char < region.end_char <= len(canonical), (
                f"Region {idx} offsets should be valid: "
                f"0 <= {region.start_char} < {region.end_char} <= {len(canonical)}"
            )

    def test_very_long_sentence_triggers_hard_split(self) -> None:
        """Verify sentences exceeding chunk_size are hard-split at chunk boundaries.

        When a single sentence exceeds chunk_size, the function should perform
        a hard split at the chunk_size boundary rather than creating an
        oversized region. This ensures memory safety by enforcing chunk limits.
        """
        # Create a very long sentence without periods (no sentence boundaries)
        # This forces a hard split since NLTK won't find any boundaries within
        long_sentence = "word " * 500  # ~2500 chars with no sentence break
        doc_id = "test_doc_hard_split"
        # Use small chunk_size to force hard split
        chunk_size = 100

        regions = initialize_work_regions(long_sentence, doc_id, chunk_size=chunk_size)

        # Should produce multiple regions due to hard split
        assert len(regions) > 1, "Very long sentence should produce multiple regions"

        # Verify no region exceeds chunk_size (except possibly the last one)
        for i, region in enumerate(regions[:-1]):
            region_size = region.end_char - region.start_char
            assert region_size <= chunk_size, (
                f"Region {i} size ({region_size}) should not exceed chunk_size ({chunk_size})"
            )

        # Verify regions are contiguous
        for i in range(len(regions) - 1):
            assert regions[i].end_char == regions[i + 1].start_char, (
                f"Region {i} end ({regions[i].end_char}) should equal "
                f"region {i + 1} start ({regions[i + 1].start_char})"
            )

        # Verify first region starts at 0 and last ends at document length
        assert regions[0].start_char == 0, "First region should start at 0"
        assert regions[-1].end_char == len(long_sentence), (
            "Last region should end at document length"
        )

        # Verify all regions have valid properties
        for idx, region in enumerate(regions):
            assert region.doc_id == doc_id, f"Region {idx} should have correct doc_id"
            assert doc_id in region.region_id, f"Region {idx} ID should contain doc_id"
            assert region.is_processed is False, f"Region {idx} should be unprocessed initially"
            assert region.created_at is not None, f"Region {idx} should have created_at field"
            assert "T" in region.created_at, f"Region {idx} timestamp should be ISO 8601 format"
            assert region.created_at.endswith("Z"), (
                f"Region {idx} timestamp should end with Z (UTC)"
            )


class TestValidateIngestion:
    """Unit tests for validate_ingestion function."""

    def test_all_validations_pass_for_clean_input(self) -> None:
        """Verify all validations pass for clean input."""
        canonical = "Clean text content"
        regions = [make_work_region(len(canonical), region_id="region_0", doc_id="doc")]

        result = validate_ingestion(canonical, regions)

        assert result["encoding_valid"] is True
        assert result["offsets_valid"] is True
        assert result["artifacts_removed"] is True
        assert result["offset_mapping_valid"] is True

    def test_negative_start_offset_fails(self) -> None:
        """Verify negative start offset fails validation."""
        canonical = "Content"
        regions = [
            make_work_region(len(canonical), region_id="region_0", doc_id="doc", start_char=-1)
        ]

        result = validate_ingestion(canonical, regions)

        assert result["offsets_valid"] is False

    def test_end_beyond_length_fails(self) -> None:
        """Verify end offset beyond string length fails validation."""
        canonical = "Short"
        regions = [make_work_region(100, region_id="region_0", doc_id="doc")]

        result = validate_ingestion(canonical, regions)

        assert result["offsets_valid"] is False

    def test_form_feed_detected_as_artifact(self) -> None:
        """Verify form feed is detected as artifact."""
        canonical = "Text\fwith form feed"
        regions = [make_work_region(len(canonical), region_id="region_0", doc_id="doc")]

        result = validate_ingestion(canonical, regions)

        assert result["artifacts_removed"] is False

    def test_null_byte_detected_as_artifact(self) -> None:
        """Verify null byte is detected as artifact."""
        canonical = "Text\x00with null"
        regions = [make_work_region(len(canonical), region_id="region_0", doc_id="doc")]

        result = validate_ingestion(canonical, regions)

        assert result["artifacts_removed"] is False

    def test_empty_regions_list_passes(self) -> None:
        """Verify empty regions list passes offset validation."""
        canonical = "Content"
        regions: list[WorkRegion] = []

        result = validate_ingestion(canonical, regions)

        # Empty regions should pass offset validation (vacuous truth)
        assert result["offsets_valid"] is True

    def test_zero_length_region_fails(self) -> None:
        """Verify zero-length region (start == end) fails validation.

        QA Step 1 expectation: start < end, so zero-length regions are invalid.
        We construct the WorkRegion directly (bypassing make_work_region's
        validation) to test that validate_ingestion handles this case.
        """
        canonical = "Content"
        # Construct zero-length region directly, bypassing make_work_region helper
        zero_length_region = WorkRegion(
            region_id="region_0",
            doc_id="doc",
            start_char=3,
            end_char=3,  # Zero-length region (start == end)
            is_processed=False,
            created_at="2025-01-01T00:00:00Z",
        )

        result = validate_ingestion(canonical, [zero_length_region])

        # Zero-length regions should fail offset validation
        assert result["offsets_valid"] is False, (
            "Zero-length region (start == end) should fail offset validation"
        )

    def test_offset_mapping_invalid_fails(self) -> None:
        """Verify invalid offset mapping fails validation (STOP+REPORT scenario).

        QA Step 1 Unexpected: Offset mapping entries out of bounds should fail.
        """
        canonical = "Short"  # Length 5
        regions = [make_work_region(len(canonical), region_id="region_0", doc_id="doc")]
        # Invalid mapping: value 999 is out of bounds
        offset_mapping = [0, 1, 2, 999, 4]

        result = validate_ingestion(canonical, regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is False, (
            "Offset mapping with out-of-bounds value should fail validation"
        )

    def test_offset_mapping_with_removed_chars_valid(self) -> None:
        """Verify offset mapping with -1 (removed chars) passes validation."""
        canonical = "Hello"  # Length 5
        regions = [make_work_region(len(canonical), region_id="region_0", doc_id="doc")]
        # Valid mapping with -1 for removed characters
        offset_mapping = [0, -1, 1, -1, 2, 3, 4]

        result = validate_ingestion(canonical, regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is True


class TestQAStep1JsonScalarValues:
    """Tests for QA Step 1: JSON ingestion includes all scalar values."""

    def test_qa_step1_json_numeric_values_extracted(self, fs: FakeFilesystem) -> None:
        """Verify numeric values from JSON are included in canonical string.

        QA Step 1: JSON ingestion should extract all scalar values including numbers.
        """
        json_content = {
            "title": "Test Document",
            "count": 42,
            "price": 19.99,
            "year": 2025,
        }
        test_file = Path("/test/numeric.json")
        fs.create_file(str(test_file), contents=json.dumps(json_content))

        canonical, _, _, _, validation = ingest_document(test_file)

        # Verify numeric values are present in canonical string
        assert "42" in canonical, "Integer value should be in canonical string"
        assert "19.99" in canonical, "Float value should be in canonical string"
        assert "2025" in canonical, "Year value should be in canonical string"
        # Verify validation passes
        assert all(validation.values()), f"All validations should pass: {validation}"

    def test_qa_step1_json_boolean_and_null_extracted(self, fs: FakeFilesystem) -> None:
        """Verify boolean and null values from JSON are included in canonical string.

        QA Step 1: JSON ingestion should extract all scalar values including booleans and null.
        """
        json_content = {
            "name": "Test",
            "enabled": True,
            "disabled": False,
            "optional": None,
        }
        test_file = Path("/test/booleans.json")
        fs.create_file(str(test_file), contents=json.dumps(json_content))

        canonical, _, _, _, validation = ingest_document(test_file)

        # Verify boolean and null values are present
        assert "true" in canonical, "Boolean True should be 'true' in canonical string"
        assert "false" in canonical, "Boolean False should be 'false' in canonical string"
        assert "null" in canonical, "None should be 'null' in canonical string"
        # Verify validation passes
        assert all(validation.values()), f"All validations should pass: {validation}"


class TestQAStep1PdfNumberedLists:
    """Tests for QA Step 1: PDF with numbered lists should pass validation."""

    def test_qa_step1_pdf_numbered_list_passes(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Verify PDF with legitimate numbered list content passes validation.

        QA Step 1: Bare numbers in PDF content should not be flagged as page
        number artifacts when they could be legitimate numbered list items.
        """
        # Create mock PDF with numbered list content
        mock_page = mocker.MagicMock()
        mock_page.extract_text.return_value = (
            "Instructions:\n1\nOpen the application\n2\nClick settings\n3\nSave changes"
        )
        mock_reader = mocker.MagicMock()
        mock_reader.pages = [mock_page]
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        test_file = Path("/test/numbered_list.pdf")
        fs.create_file(str(test_file), contents=b"fake pdf content")

        _, _, _, _, validation = ingest_document(test_file)

        # Verify artifacts_removed is True (numbered list should not fail)
        assert validation["artifacts_removed"] is True, (
            "PDF with numbered list should pass artifact validation"
        )
        # Verify all validations pass
        assert validation["encoding_valid"] is True
        assert validation["offsets_valid"] is True
        assert validation["offset_mapping_valid"] is True
