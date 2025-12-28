from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.knowledge.document_ingestion import (
    PAGE_NUMBER_MAX_DIGITS,
    check_utf8_encoding,
    create_canonical_string,
    ingest_document,
    initialize_work_regions,
    validate_ingestion,
)
from scripts.tests.unit.knowledge.conftest import make_work_region

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem
    from pytest_mock import MockerFixture


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


class TestQAStep1NoFormatArtifacts:
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


class TestQAStep1UnexpectedConditions:
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


class TestQAStep1PdfNumberedLists:
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
