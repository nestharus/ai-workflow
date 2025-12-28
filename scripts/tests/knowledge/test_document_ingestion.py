"""Unit tests for document_ingestion module."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem
from pytest_mock import MockerFixture

from scripts.dev.utils import REPO_ROOT
from scripts.knowledge import document_ingestion
from scripts.knowledge.atomic_fact_models import WorkRegion
from scripts.knowledge.document_ingestion import (
    DEFAULT_CHUNK_SIZE,
    PAGE_NUMBER_ADJACENCY_GAP,
    PyPdfError,
    _extract_position_from_ijson_error,
    _get_repo_relative_stem,
    _get_sentence_boundaries,
    _get_sentence_boundaries_fallback,
    _has_isolated_page_numbers,
    _normalize_file_path,
    create_canonical_string,
    document_ingestion_main,
    expand_input_paths,
    ingest_document,
    ingest_json_file,
    ingest_pdf_file,
    ingest_text_file,
    initialize_work_regions,
    is_text_file,
    parse_args,
    validate_ingestion,
)
from scripts.tests.knowledge.conftest import make_work_region


@pytest.fixture
def mock_repo_root(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override REPO_ROOT to /test_repo for tests that need a controlled repo root.

    Returns:
        The mocked repo root path (/test_repo).
    """
    test_repo = Path("/test_repo")
    monkeypatch.setattr("scripts.knowledge.document_ingestion.REPO_ROOT", test_repo)
    return test_repo


class TestNormalizeFilePath:
    """Tests for _normalize_file_path function."""

    def test_normalize_absolute_path(self, fs: FakeFilesystem) -> None:
        """Absolute paths are resolved without changing directory."""
        abs_path = Path("/some/absolute/path/file.txt")
        fs.create_file(str(abs_path), contents="test")

        result = _normalize_file_path(abs_path)

        assert result.is_absolute()
        assert result == abs_path.resolve()

    def test_normalize_relative_path(self, fs: FakeFilesystem) -> None:
        """Relative paths are resolved against REPO_ROOT."""
        # Create a file relative to REPO_ROOT
        rel_path = Path("test_dir/file.txt")
        full_path = REPO_ROOT / rel_path
        fs.create_file(str(full_path), contents="test")

        result = _normalize_file_path(rel_path)

        assert result.is_absolute()
        assert result == full_path.resolve()

    def test_normalize_path_resolves_symlinks(self, fs: FakeFilesystem) -> None:
        """Normalized paths resolve to canonical form."""
        # Create a path with .. components
        abs_path = Path("/some/path/../other/file.txt")
        fs.create_file("/some/other/file.txt", contents="test")

        result = _normalize_file_path(abs_path)

        assert result.is_absolute()
        # The .. should be resolved out
        assert ".." not in str(result)


class TestGetRepoRelativeStem:
    """Tests for _get_repo_relative_stem function."""

    def test_get_stem_from_path(self) -> None:
        """Get file stem from a path."""
        path = Path("/some/path/to/document.txt")
        assert _get_repo_relative_stem(path) == "document"

    def test_get_stem_from_path_with_multiple_dots(self) -> None:
        """Get file stem from a path with multiple dots."""
        path = Path("/some/path/to/document.test.txt")
        assert _get_repo_relative_stem(path) == "document.test"


class TestIngestTextFile:
    """Tests for ingest_text_file function."""

    def test_ingest_text_file_valid_utf8(self, fs: FakeFilesystem) -> None:
        """Create text file with UTF-8 content, verify raw text and doc_id format."""
        # Create a UTF-8 text file
        content = "Hello, world! This is a test file.\nWith multiple lines."
        file_path = Path("/test_data/sample.txt")
        fs.create_file(str(file_path), contents=content)

        raw_text, doc_id = ingest_text_file(file_path)

        # Verify raw text matches
        assert raw_text == content

        # Verify doc_id format: text_{stem}_{timestamp}
        # Use regex to match the whole doc_id and extract timestamp for validation
        doc_id_pattern = re.compile(r"^text_sample_(\d{8}T\d{6}Z)$")
        match = doc_id_pattern.match(doc_id)
        assert match is not None, f"doc_id '{doc_id}' does not match expected pattern"
        # Validate extracted timestamp conforms to YYYYMMDDTHHMMSSZ format
        timestamp_str = match.group(1)
        # strptime raises ValueError if format is invalid, no assertion needed
        datetime.strptime(timestamp_str, "%Y%m%dT%H%M%SZ")

    def test_ingest_text_file_latin1_fallback(self, fs: FakeFilesystem) -> None:
        """Create text file with latin-1 encoding that fails UTF-8, verify fallback works."""
        # Latin-1 specific character that would fail UTF-8
        latin1_content = b"Caf\xe9 au lait"  # "Cafe au lait" with e-acute
        file_path = Path("/test_data/latin1.txt")
        fs.create_file(str(file_path), contents=latin1_content)

        raw_text, doc_id = ingest_text_file(file_path)

        # Verify fallback to latin-1 worked
        assert "Caf" in raw_text
        assert doc_id.startswith("text_latin1_")


class TestIngestPdfFile:
    """Tests for ingest_pdf_file function."""

    def test_ingest_pdf_file_extracts_text(self, fs: FakeFilesystem, mocker: MockerFixture) -> None:
        """Mock pypdf.PdfReader to return text with artifacts, verify extraction and artifact removal."""
        # Create mock page with text and artifacts
        mock_page = mocker.MagicMock()
        mock_page.extract_text.return_value = "Page 1 text\f123\nMore text"
        mock_reader = mocker.MagicMock()
        mock_reader.pages = [mock_page]
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        # Create a dummy PDF file (content doesn't matter since we mock)
        file_path = Path("/test_data/sample.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        raw_text, doc_id = ingest_pdf_file(file_path)

        # Verify form feed characters are removed
        assert "\f" not in raw_text
        # Verify the text content is present (minus artifacts)
        assert "Page 1 text" in raw_text
        assert "More text" in raw_text
        # Verify doc_id format
        assert doc_id.startswith("pdf_sample_")

    def test_ingest_pdf_file_preserves_numbered_list_content(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock PdfReader with numbered list content, verify digits are preserved."""
        # Create mock page with numbered list content (digit-only lines)
        mock_page = mocker.MagicMock()
        mock_page.extract_text.return_value = "Shopping list:\n1\nApples\n2\nBananas\n123\nOranges"
        mock_reader = mocker.MagicMock()
        mock_reader.pages = [mock_page]
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/numbered_list.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf")

        raw_text, doc_id = ingest_pdf_file(file_path)

        # Verify digit-only lines are preserved (not removed as page numbers)
        # This ensures legitimate numbered list content is retained
        assert "1" in raw_text
        assert "2" in raw_text
        assert "123" in raw_text
        assert "Apples" in raw_text
        assert "Bananas" in raw_text
        assert "Oranges" in raw_text
        assert doc_id.startswith("pdf_numbered_list_")

    def test_ingest_pdf_file_removes_explicit_page_patterns(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock PdfReader with 'Page X' patterns, verify they're removed."""
        # Create mock page with explicit page number patterns
        mock_page = mocker.MagicMock()
        mock_page.extract_text.return_value = (
            "Page 1\nFirst paragraph.\nPage 2 of 10\nSecond paragraph.\n- 5 -\nThird paragraph."
        )
        mock_reader = mocker.MagicMock()
        mock_reader.pages = [mock_page]
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/paged.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf")

        raw_text, doc_id = ingest_pdf_file(file_path)

        # Verify explicit page patterns are removed
        assert "Page 1" not in raw_text
        assert "Page 2 of 10" not in raw_text
        assert "- 5 -" not in raw_text
        # Verify content is preserved
        assert "First paragraph" in raw_text
        assert "Second paragraph" in raw_text
        assert "Third paragraph" in raw_text
        assert doc_id.startswith("pdf_paged_")

    def test_ingest_pdf_file_removes_repeated_headers(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock PDF with repeated 'Confidential' header across pages, verify removed."""
        # Create mock pages with repeated header "Confidential" on each page
        mock_pages = []
        for i in range(4):
            mock_page = mocker.MagicMock()
            mock_page.extract_text.return_value = (
                f"Confidential\nPage {i + 1} content here.\nMore text on page {i + 1}."
            )
            mock_pages.append(mock_page)

        mock_reader = mocker.MagicMock()
        mock_reader.pages = mock_pages
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/confidential.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        raw_text, doc_id = ingest_pdf_file(file_path)

        # Verify "Confidential" is removed (case-insensitive)
        assert "confidential" not in raw_text.lower()
        # Verify actual content is preserved
        assert "Page 1 content here" in raw_text
        assert "Page 2 content here" in raw_text
        assert "Page 3 content here" in raw_text
        assert "Page 4 content here" in raw_text
        assert doc_id.startswith("pdf_confidential_")

    def test_ingest_pdf_file_removes_repeated_footers(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock PDF with repeated footer across pages, verify removed."""
        # Create mock pages with repeated footer "Copyright 2025 Acme Corp"
        # Use unique middle content per page so it's not detected as artifact
        mock_pages = []
        for i in range(3):
            mock_page = mocker.MagicMock()
            mock_page.extract_text.return_value = (
                f"Page {i + 1} content.\nUnique text for page {i + 1}.\nCopyright 2025 Acme Corp"
            )
            mock_pages.append(mock_page)

        mock_reader = mocker.MagicMock()
        mock_reader.pages = mock_pages
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/footer.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        raw_text, _doc_id = ingest_pdf_file(file_path)

        # Verify footer is removed (case-insensitive)
        assert "copyright 2025 acme corp" not in raw_text.lower()
        # Verify actual content is preserved
        assert "Page 1 content" in raw_text
        assert "Unique text for page 1" in raw_text

    def test_ingest_pdf_file_single_page_unaffected(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock single-page PDF, verify no content removed due to repeated line detection."""
        mock_page = mocker.MagicMock()
        mock_page.extract_text.return_value = "Confidential\nImportant content here."

        mock_reader = mocker.MagicMock()
        mock_reader.pages = [mock_page]
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/single.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        raw_text, _doc_id = ingest_pdf_file(file_path)

        # Single page should not have repeated header detection applied
        # "Confidential" should still be present
        assert "Confidential" in raw_text
        assert "Important content here" in raw_text

    def test_ingest_pdf_file_varying_case_whitespace_headers(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock PDF with headers varying in case/whitespace, verify all removed."""
        mock_pages = [
            mocker.MagicMock(),
            mocker.MagicMock(),
            mocker.MagicMock(),
        ]
        # Same header with different case and whitespace
        mock_pages[0].extract_text.return_value = "CONFIDENTIAL\nPage 1 content."
        mock_pages[1].extract_text.return_value = "  Confidential  \nPage 2 content."
        mock_pages[2].extract_text.return_value = "confidential\nPage 3 content."

        mock_reader = mocker.MagicMock()
        mock_reader.pages = mock_pages
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/varying_case.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        raw_text, _doc_id = ingest_pdf_file(file_path)

        # All variations should be removed
        assert "confidential" not in raw_text.lower()
        # Content preserved
        assert "Page 1 content" in raw_text
        assert "Page 2 content" in raw_text
        assert "Page 3 content" in raw_text

    def test_ingest_pdf_file_odd_page_count_threshold(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock 5-page PDF, verify threshold uses ceiling for >=50% rule.

        With 5 pages, ceil(5/2) = 3, so a header appearing on only 2 pages (40%)
        should NOT be removed, while one appearing on 3+ pages (60%+) IS removed.
        """
        mock_pages = []
        for i in range(5):
            mock_page = mocker.MagicMock()
            # "Rare Header" appears on pages 1 and 2 only (2 out of 5 = 40%)
            # "Common Header" appears on pages 1, 2, and 3 (3 out of 5 = 60%)
            if i < 2:
                mock_page.extract_text.return_value = (
                    f"Rare Header\nCommon Header\nPage {i + 1} content."
                )
            elif i == 2:
                mock_page.extract_text.return_value = f"Common Header\nPage {i + 1} content."
            else:
                mock_page.extract_text.return_value = f"Page {i + 1} content."
            mock_pages.append(mock_page)

        mock_reader = mocker.MagicMock()
        mock_reader.pages = mock_pages
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/five_pages.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        raw_text, _doc_id = ingest_pdf_file(file_path)

        # "Rare Header" appears only 2 times (40%), should NOT be removed
        assert "rare header" in raw_text.lower()
        # "Common Header" appears 3 times (60%), should be removed
        assert "common header" not in raw_text.lower()
        # All page content preserved
        for i in range(5):
            assert f"Page {i + 1} content" in raw_text

    def test_ingest_pdf_file_streaming_mode_large_pdf(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock large PDF exceeding max_pages_to_cache, verify streaming two-pass approach works."""
        # Create 5 mock pages - set max_pages_to_cache=2 to trigger streaming mode
        mock_pages = []
        for i in range(5):
            mock_page = mocker.MagicMock()
            # Each page has a repeated header "REPEATED HEADER" plus unique content
            mock_page.extract_text.return_value = (
                f"REPEATED HEADER\nPage {i + 1} unique content here.\nEnd of page {i + 1}."
            )
            mock_pages.append(mock_page)

        mock_reader = mocker.MagicMock()
        mock_reader.pages = mock_pages
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/large.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        # Use max_pages_to_cache=2 to force streaming mode (5 pages > 2)
        raw_text, doc_id = ingest_pdf_file(file_path, max_pages_to_cache=2)

        # Verify repeated header is removed
        assert "repeated header" not in raw_text.lower()
        # Verify unique content from all pages is preserved
        for i in range(5):
            assert f"Page {i + 1} unique content here" in raw_text
            assert f"End of page {i + 1}" in raw_text
        assert doc_id.startswith("pdf_large_")

    def test_ingest_pdf_file_caching_mode_small_pdf(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock small PDF under max_pages_to_cache, verify single-pass caching works."""
        # Create 3 mock pages - set max_pages_to_cache=5 to use caching mode
        mock_pages = []
        for i in range(3):
            mock_page = mocker.MagicMock()
            mock_page.extract_text.return_value = f"Footer Text\nPage {i + 1} content.\nFooter Text"
            mock_pages.append(mock_page)

        mock_reader = mocker.MagicMock()
        mock_reader.pages = mock_pages
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/small.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        # Use max_pages_to_cache=5 to use caching mode (3 pages <= 5)
        raw_text, doc_id = ingest_pdf_file(file_path, max_pages_to_cache=5)

        # Verify repeated footer is removed
        assert "footer text" not in raw_text.lower()
        # Verify page content is preserved
        for i in range(3):
            assert f"Page {i + 1} content" in raw_text
        assert doc_id.startswith("pdf_small_")

    def test_ingest_pdf_file_default_max_pages_to_cache(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Verify default max_pages_to_cache is 1000."""
        mock_page = mocker.MagicMock()
        mock_page.extract_text.return_value = "Simple content"
        mock_reader = mocker.MagicMock()
        mock_reader.pages = [mock_page]
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/default.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        # Call without max_pages_to_cache - should use default of 1000
        # With 1 page, this will use caching mode (1 <= 1000)
        raw_text, doc_id = ingest_pdf_file(file_path)

        assert "Simple content" in raw_text
        assert doc_id.startswith("pdf_default_")


class TestExtractPositionFromIjsonError:
    """Tests for _extract_position_from_ijson_error function."""

    def test_python_backend_format_simple(self) -> None:
        """Extract position from Python backend 'at N' format."""
        msg = "Unexpected symbol 'key' at 1"
        assert _extract_position_from_ijson_error(msg) == 1

    def test_python_backend_format_larger_position(self) -> None:
        """Extract larger position value from Python backend format."""
        msg = "Unexpected symbol 'value' at 8"
        assert _extract_position_from_ijson_error(msg) == 8

    def test_python_backend_format_at_position_variant(self) -> None:
        """Extract position from 'at position N' format."""
        msg = "Error at 42 in the document"
        assert _extract_position_from_ijson_error(msg) == 42

    def test_python_backend_at_position_explicit_format(self) -> None:
        """Extract position from explicit 'at position N' error message format.

        This test verifies support for ijson error messages that use the
        'at position N' phrasing (e.g., 'Unexpected token at position 17').
        """
        msg = "Unexpected token at position 17"
        assert _extract_position_from_ijson_error(msg) == 17

    def test_yajl_backend_format_caret_marker(self) -> None:
        """Extract position from YAJL backend caret marker format."""
        # YAJL format: error message, content line, marker line with ^
        msg = (
            "lexical error: invalid char in json text.\n"
            "                               {key: value}\n"
            "                     (right here) ------^\n"
        )
        pos = _extract_position_from_ijson_error(msg)
        # The caret is at position 40, content starts at position 31
        # So the offset should be around 9 (40 - 31)
        assert 8 <= pos <= 10

    def test_yajl_backend_format_early_error(self) -> None:
        """Extract position from YAJL format with error near start."""
        msg = (
            "lexical error: invalid char in json text.\n"
            "                                      {key: value}\n"
            "                     (right here) ------^\n"
        )
        pos = _extract_position_from_ijson_error(msg)
        # Should extract a small positive position
        assert pos >= 0

    def test_incomplete_json_no_position(self) -> None:
        """Handle incomplete JSON error with no position info."""
        msg = "Incomplete JSON content"
        assert _extract_position_from_ijson_error(msg) == 0

    def test_empty_message(self) -> None:
        """Handle empty error message."""
        assert _extract_position_from_ijson_error("") == 0

    def test_no_position_info(self) -> None:
        """Handle message with no extractable position."""
        msg = "Some random error without position"
        assert _extract_position_from_ijson_error(msg) == 0

    def test_premature_eof_yajl(self) -> None:
        """Handle premature EOF error from YAJL backend."""
        msg = (
            "parse error: premature EOF\n"
            "                                       \n"
            "                     (right here) ------^\n"
        )
        # Should fall back to 0 since content line is empty
        pos = _extract_position_from_ijson_error(msg)
        assert pos == 0


class TestIngestJsonFile:
    """Tests for ingest_json_file function."""

    def test_ingest_json_file_flat_structure(self, fs: FakeFilesystem) -> None:
        """Create JSON with simple key-value pairs, verify keys and values extracted."""
        json_content = {
            "title": "Test Document",
            "description": "A sample description",
            "count": 42,
            "active": True,
        }
        file_path = Path("/test_data/flat.json")
        fs.create_file(str(file_path), contents=json.dumps(json_content))

        raw_text, doc_id = ingest_json_file(file_path)

        # Verify key-prefixed format: "key: value"
        assert "title: Test Document" in raw_text
        assert "description: A sample description" in raw_text
        # Verify non-strings are converted to string representation with key prefix
        assert "count: 42" in raw_text
        assert "active: true" in raw_text  # Boolean converted to lowercase
        # Verify doc_id format
        assert doc_id.startswith("json_flat_")

    def test_ingest_json_file_numeric_and_boolean_values(self, fs: FakeFilesystem) -> None:
        """Create JSON with numeric, boolean, and null values, verify keys preserved."""
        json_content = {
            "name": "Test",
            "count": 100,
            "price": 19.99,
            "enabled": True,
            "disabled": False,
            "optional": None,
        }
        file_path = Path("/test_data/scalar_values.json")
        fs.create_file(str(file_path), contents=json.dumps(json_content))

        raw_text, doc_id = ingest_json_file(file_path)

        # Verify all key-value pairs are in the canonical string
        assert "name: Test" in raw_text  # String
        assert "count: 100" in raw_text  # Integer
        assert "price: 19.99" in raw_text  # Float
        assert "enabled: true" in raw_text  # Boolean True -> "true"
        assert "disabled: false" in raw_text  # Boolean False -> "false"
        assert "optional: null" in raw_text  # None -> "null"
        assert doc_id.startswith("json_scalar_values_")

    def test_ingest_json_file_nested_structure(self, fs: FakeFilesystem) -> None:
        """Create nested JSON, verify keys extracted with values."""
        json_content = {
            "title": "Root Title",
            "metadata": {
                "author": "John Doe",
                "category": "Technical",
            },
            "sections": [
                {"heading": "Section 1", "content": "First section content"},
                {"heading": "Section 2", "content": "Second section content"},
            ],
        }
        file_path = Path("/test_data/nested.json")
        fs.create_file(str(file_path), contents=json.dumps(json_content))

        raw_text, doc_id = ingest_json_file(file_path)

        # Verify all key-value pairs from nested structure are extracted
        assert "title: Root Title" in raw_text
        assert "author: John Doe" in raw_text
        assert "category: Technical" in raw_text
        assert "heading: Section 1" in raw_text
        assert "content: First section content" in raw_text
        assert "heading: Section 2" in raw_text
        assert "content: Second section content" in raw_text
        # Verify doc_id format
        assert doc_id.startswith("json_nested_")

    def test_ingest_json_file_array_items(self, fs: FakeFilesystem) -> None:
        """Create JSON with root array, verify array items have 'item' prefix.

        Note: ijson uses 'item' as the path segment for array elements,
        not numeric indices. This is a limitation of the streaming parser
        that doesn't track array indices explicitly.
        """
        json_content = ["apple", "banana", "cherry"]
        file_path = Path("/test_data/array.json")
        fs.create_file(str(file_path), contents=json.dumps(json_content))

        raw_text, doc_id = ingest_json_file(file_path)

        # Verify array items have 'item' prefix (ijson's array element marker)
        assert "item: apple" in raw_text
        assert "item: banana" in raw_text
        assert "item: cherry" in raw_text
        assert doc_id.startswith("json_array_")


class TestLargeFileIngestion:
    """Tests for ingestion of large documents."""

    def test_ingest_large_text_file(self, fs: FakeFilesystem) -> None:
        """Verify large text file is ingested correctly.

        Creates a text file with many lines to test handling of larger files.
        """
        # Create a text file with 1000 lines
        lines = [f"Line {i}: This is test content for line number {i}." for i in range(1000)]
        content = "\n".join(lines)
        file_path = Path("/test_data/large.txt")
        fs.create_file(str(file_path), contents=content)

        raw_text, doc_id = ingest_text_file(file_path)

        # Verify all lines are present
        assert "Line 0:" in raw_text
        assert "Line 500:" in raw_text
        assert "Line 999:" in raw_text
        assert doc_id.startswith("text_large_")

    def test_ingest_large_json_file(self, fs: FakeFilesystem) -> None:
        """Verify large JSON file is ingested correctly with streaming.

        Creates a JSON file with many string values to test ijson streaming.
        """
        # Create JSON with many nested strings
        json_content = {
            "items": [
                {"id": str(i), "name": f"Item {i}", "description": f"Description for item {i}"}
                for i in range(100)
            ]
        }
        file_path = Path("/test_data/large.json")
        fs.create_file(str(file_path), contents=json.dumps(json_content))

        raw_text, doc_id = ingest_json_file(file_path)

        # Verify key-prefixed strings are extracted
        assert "name: Item 0" in raw_text
        assert "name: Item 50" in raw_text
        assert "name: Item 99" in raw_text
        assert "description: Description for item 0" in raw_text
        assert doc_id.startswith("json_large_")

    def test_ingest_deeply_nested_json(self, fs: FakeFilesystem) -> None:
        """Verify deeply nested JSON is handled by streaming parser.

        With ijson streaming, deep nesting is handled iteratively without
        recursion depth issues.
        """
        # Create deeply nested structure
        nested: dict = {"level": "0", "value": "deep_value_0"}
        current = nested
        for i in range(1, 50):
            current["child"] = {"level": str(i), "value": f"deep_value_{i}"}
            current = current["child"]

        file_path = Path("/test_data/deep.json")
        fs.create_file(str(file_path), contents=json.dumps(nested))

        raw_text, doc_id = ingest_json_file(file_path)

        # Verify deeply nested key-prefixed values are extracted
        assert "value: deep_value_0" in raw_text
        assert "value: deep_value_49" in raw_text
        assert doc_id.startswith("json_deep_")


class TestCreateCanonicalString:
    """Tests for create_canonical_string function."""

    def test_create_canonical_string_normalizes_unicode(self) -> None:
        """Input decomposed Unicode, verify NFC normalization."""
        # Decomposed form of "cafe" with combining acute accent
        decomposed = "cafe\u0301"  # e + combining acute accent
        composed = "caf\u00e9"  # e-acute precomposed

        result, offset_mapping = create_canonical_string(decomposed)

        # Should be normalized to NFC (composed form)
        assert result == composed
        # Offset mapping should be returned
        assert len(offset_mapping) == len(decomposed)

    def test_create_canonical_string_normalizes_whitespace(self) -> None:
        """Input multiple spaces/tabs, verify collapsed to single space."""
        text = "Hello    world\t\tthis  is   a test"

        result, offset_mapping = create_canonical_string(text)

        # Multiple spaces/tabs should be collapsed to single space
        assert result == "Hello world this is a test"
        # Offset mapping should be returned
        assert len(offset_mapping) == len(text)

    def test_create_canonical_string_normalizes_line_endings(self) -> None:
        """Input \\r\\n and \\r, verify normalized to \\n."""
        text = "Line one\r\nLine two\rLine three\nLine four"

        result, offset_mapping = create_canonical_string(text)

        # All line endings should be normalized to \n
        assert "\r" not in result
        assert result == "Line one\nLine two\nLine three\nLine four"
        # Offset mapping should be returned
        assert len(offset_mapping) == len(text)

    def test_create_canonical_string_removes_control_chars(self) -> None:
        """Input with control chars, verify removed (except \\n, \\t)."""
        # Control characters to remove
        text = "Hello\x00world\x01test\x02end\x03"

        result, offset_mapping = create_canonical_string(text)

        # Control chars should be removed
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x02" not in result
        assert "\x03" not in result
        assert result == "Helloworldtestend"
        # Offset mapping should be returned
        assert len(offset_mapping) == len(text)

    def test_offset_mapping_simple_ascii_correct(self) -> None:
        """Verify offset mapping is correct for simple ASCII text."""
        text = "Hello"

        result, offset_mapping = create_canonical_string(text)

        # For simple ASCII, mapping should be identity
        assert result == "Hello"
        assert offset_mapping == [0, 1, 2, 3, 4]

    def test_offset_mapping_crlf_correct(self) -> None:
        """Verify offset mapping is correct for CRLF normalization."""
        text = "A\r\nB"  # 4 chars: A, \r, \n, B

        result, offset_mapping = create_canonical_string(text)

        # Result should be "A\nB" (3 chars)
        assert result == "A\nB"
        # Mapping: A->0, \r->1 (maps to the \n), \n->-1 (absorbed), B->2
        assert offset_mapping[0] == 0  # A maps to 0
        assert offset_mapping[1] == 1  # \r maps to 1 (the \n position)
        assert offset_mapping[2] == -1  # Original \n is absorbed
        assert offset_mapping[3] == 2  # B maps to 2

    def test_offset_mapping_whitespace_collapse_correct(self) -> None:
        """Verify offset mapping is correct for whitespace collapse."""
        text = "A  B"  # 4 chars: A, space, space, B

        result, offset_mapping = create_canonical_string(text)

        # Result should be "A B" (3 chars)
        assert result == "A B"
        # Mapping: A->0, first space->1, second space->-1, B->2
        assert offset_mapping[0] == 0  # A maps to 0
        assert offset_mapping[1] == 1  # First space maps to 1
        assert offset_mapping[2] == -1  # Second space collapsed
        assert offset_mapping[3] == 2  # B maps to 2

    def test_offset_mapping_control_char_removal_correct(self) -> None:
        """Verify offset mapping is correct when control chars are removed."""
        text = "A\x00B"  # 3 chars: A, null, B

        result, offset_mapping = create_canonical_string(text)

        # Result should be "AB" (2 chars)
        assert result == "AB"
        # Mapping: A->0, \x00->-1 (removed), B->1
        assert offset_mapping[0] == 0  # A maps to 0
        assert offset_mapping[1] == -1  # Null byte removed
        assert offset_mapping[2] == 1  # B maps to 1


class TestInitializeWorkRegions:
    """Tests for initialize_work_regions function."""

    def test_initialize_work_regions_covers_entire_document(self) -> None:
        """Verify single region with start=0, end=len, is_processed=False."""
        canonical_string = "This is a test document with some content."
        doc_id = "test_doc_20250126T120000Z"

        regions = initialize_work_regions(canonical_string, doc_id)

        # Should return exactly one region
        assert len(regions) == 1

        region = regions[0]
        # Verify region covers entire document
        assert region.start_char == 0
        assert region.end_char == len(canonical_string)
        # Verify not processed
        assert region.is_processed is False
        # Verify doc_id
        assert region.doc_id == doc_id
        # Verify region_id format
        assert region.region_id == f"{doc_id}_region_0"
        # Verify created_at is set
        assert region.created_at is not None
        assert region.created_at.endswith("Z")

    def test_initialize_work_regions_chunks_large_document(self) -> None:
        """Verify large documents are split into multiple work regions."""
        # Create a document larger than the chunk size
        paragraphs = ["Paragraph " + str(i) + ". " * 100 for i in range(50)]
        canonical_string = "\n\n".join(paragraphs)  # ~10KB
        doc_id = "test_large_doc"

        # Use a small chunk size to force chunking
        regions = initialize_work_regions(canonical_string, doc_id, chunk_size=1000)

        # Should have multiple regions
        assert len(regions) > 1

        # Verify regions cover entire document without gaps
        assert regions[0].start_char == 0
        assert regions[-1].end_char == len(canonical_string)

        # Verify regions are contiguous
        for i in range(len(regions) - 1):
            assert regions[i].end_char == regions[i + 1].start_char

        # Verify region_id format is sequential
        for i, region in enumerate(regions):
            assert region.region_id == f"{doc_id}_region_{i}"

    def test_initialize_work_regions_chunk_size_zero_disables(self) -> None:
        """Verify chunk_size=0 disables chunking."""
        paragraphs = ["Paragraph " + str(i) + ". " * 100 for i in range(50)]
        canonical_string = "\n\n".join(paragraphs)
        doc_id = "test_no_chunk"

        regions = initialize_work_regions(canonical_string, doc_id, chunk_size=0)

        # Should have exactly one region
        assert len(regions) == 1
        assert regions[0].start_char == 0
        assert regions[0].end_char == len(canonical_string)

    def test_initialize_work_regions_empty_canonical_returns_no_regions(self) -> None:
        """Verify empty canonical string produces no regions.

        Empty documents should return an empty list rather than a zero-length
        region (start=0, end=0) which would fail validation (start < end required).
        """
        canonical_string = ""
        doc_id = "test_empty_doc"

        regions = initialize_work_regions(canonical_string, doc_id)

        # Should return empty list, not a single zero-length region
        assert len(regions) == 0
        assert regions == []

    def test_initialize_work_regions_non_overlapping(self) -> None:
        """Verify chunks are non-overlapping with no gaps or overlap.

        This test validates that regions are strictly contiguous:
        - No gaps: each region starts exactly where the previous one ended
        - No overlap: no character is covered by more than one region
        """
        # Create a document with distinct paragraphs that will be chunked
        paragraphs = [f"Paragraph {i}. " + "x" * 200 for i in range(20)]
        canonical_string = "\n\n".join(paragraphs)
        doc_id = "test_no_overlap"

        # Use small chunk size to force multiple chunks
        regions = initialize_work_regions(canonical_string, doc_id, chunk_size=500)

        # Should have multiple regions
        assert len(regions) > 1

        # Verify no gaps: each region starts exactly where the previous ended
        for i in range(len(regions) - 1):
            assert regions[i].end_char == regions[i + 1].start_char, (
                f"Gap detected between region {i} and {i + 1}: "
                f"region {i} ends at {regions[i].end_char}, "
                f"region {i + 1} starts at {regions[i + 1].start_char}"
            )

        # Verify no overlap: combined coverage equals document length exactly
        total_coverage = sum(r.end_char - r.start_char for r in regions)
        assert total_coverage == len(canonical_string), (
            f"Coverage mismatch: regions cover {total_coverage} chars, "
            f"document is {len(canonical_string)} chars"
        )

        # Verify each character is in exactly one region
        coverage = [0] * len(canonical_string)
        for region in regions:
            for i in range(region.start_char, region.end_char):
                coverage[i] += 1

        # Each character should be covered exactly once
        assert all(c == 1 for c in coverage), "Some characters covered multiple times or not at all"

    def test_initialize_work_regions_negative_chunk_size_raises(self) -> None:
        """Verify negative chunk_size raises ValueError."""
        canonical_string = "This is a test document."
        doc_id = "test_doc"

        with pytest.raises(ValueError, match="chunk_size must be non-negative"):
            initialize_work_regions(canonical_string, doc_id, chunk_size=-1)

    def test_initialize_work_regions_negative_large_chunk_size_raises(self) -> None:
        """Verify large negative chunk_size also raises ValueError."""
        canonical_string = "This is a test document."
        doc_id = "test_doc"

        with pytest.raises(ValueError, match="chunk_size must be non-negative"):
            initialize_work_regions(canonical_string, doc_id, chunk_size=-1000)

    def test_initialize_work_regions_no_sentence_boundaries(self) -> None:
        """Verify documents with no sentence boundaries are split at chunk_size intervals.

        When NLTK finds no sentence boundaries (e.g., single continuous stream of
        characters without punctuation), the chunking should fall back to splitting
        at chunk_size intervals instead of returning a single oversized region.
        """
        # Create a document with no sentence-ending punctuation
        # Using a continuous stream of 'x' characters that exceeds chunk_size
        chunk_size = 100
        # Create content that's 3.5x chunk_size (350 chars)
        canonical_string = "x" * 350
        doc_id = "test_no_sentences"

        regions = initialize_work_regions(canonical_string, doc_id, chunk_size=chunk_size)

        # Should have 4 regions: 100, 100, 100, 50
        assert len(regions) == 4

        # Verify each region length is <= chunk_size
        for region in regions:
            region_len = region.end_char - region.start_char
            assert region_len <= chunk_size, (
                f"Region {region.region_id} has length {region_len}, exceeds chunk_size {chunk_size}"
            )

        # Verify regions are contiguous and non-overlapping
        assert regions[0].start_char == 0
        assert regions[-1].end_char == len(canonical_string)
        for i in range(len(regions) - 1):
            assert regions[i].end_char == regions[i + 1].start_char

        # Verify specific region sizes
        assert regions[0].end_char - regions[0].start_char == 100
        assert regions[1].end_char - regions[1].start_char == 100
        assert regions[2].end_char - regions[2].start_char == 100
        assert regions[3].end_char - regions[3].start_char == 50

    def test_initialize_work_regions_single_very_long_sentence(self) -> None:
        """Verify a single very long sentence is split at chunk_size intervals.

        When a single sentence exceeds chunk_size and there are no intermediate
        sentence boundaries to split at, the chunking should split at chunk_size
        intervals to enforce the chunk limit.
        """
        chunk_size = 100
        # Create a single sentence that's 350 chars - ends with period
        # NLTK will return this as a single sentence
        long_sentence = "x" * 349 + "."
        doc_id = "test_long_sentence"

        regions = initialize_work_regions(long_sentence, doc_id, chunk_size=chunk_size)

        # Should have 4 regions: 100, 100, 100, 50
        assert len(regions) == 4

        # Verify each region length is <= chunk_size
        for region in regions:
            region_len = region.end_char - region.start_char
            assert region_len <= chunk_size, (
                f"Region {region.region_id} has length {region_len}, exceeds chunk_size {chunk_size}"
            )

        # Verify regions are contiguous and non-overlapping
        assert regions[0].start_char == 0
        assert regions[-1].end_char == len(long_sentence)
        for i in range(len(regions) - 1):
            assert regions[i].end_char == regions[i + 1].start_char

        # Verify total coverage equals document length
        total_coverage = sum(r.end_char - r.start_char for r in regions)
        assert total_coverage == len(long_sentence)

    def test_initialize_work_regions_mixed_long_and_short_sentences(self) -> None:
        """Verify mixed content with both long and short sentences handles correctly.

        Tests that:
        1. Short sentences are accumulated until chunk_size
        2. Long sentences exceeding chunk_size are split at chunk_size intervals
        3. After splitting a long sentence, the remainder is handled correctly
        """
        chunk_size = 100
        # Create: short sentence (20 chars) + very long sentence (200 chars) + short (20 chars)
        short1 = "Short sentence one. "  # 20 chars
        long_sent = "x" * 199 + ". "  # 201 chars - exceeds chunk_size
        short2 = "Short sentence two."  # 19 chars
        canonical_string = short1 + long_sent + short2  # Total: 240 chars
        doc_id = "test_mixed"

        regions = initialize_work_regions(canonical_string, doc_id, chunk_size=chunk_size)

        # Verify all regions are <= chunk_size (except possibly the last if it's
        # just the remainder)
        for region in regions:
            region_len = region.end_char - region.start_char
            assert region_len <= chunk_size, (
                f"Region {region.region_id} has length {region_len}, exceeds chunk_size {chunk_size}"
            )

        # Verify regions are contiguous and cover full document
        assert regions[0].start_char == 0
        assert regions[-1].end_char == len(canonical_string)
        for i in range(len(regions) - 1):
            assert regions[i].end_char == regions[i + 1].start_char


class TestValidateIngestion:
    """Tests for validate_ingestion function.

    Invariants enforced by these tests:

    Offset Mapping:
    - Valid offset values are within [0, canonical_len] or -1 (for removed chars)
    - Mappings must be monotonically increasing (ignoring -1 entries)
    - Mappings must cover the full range [0, canonical_len) - must start at 0 and
      reach canonical_len-1
    - Work region start/end positions must appear in the mapping (end at
      canonical_len is allowed without being in mapping)
    - offset_mapping=None is allowed and passes validation
    - Mappings with all -1 values or non-monotonic (scrambled) values are rejected

    Work Regions:
    - Empty documents with empty work_regions list are allowed
    - Region offsets must be within [0, len(canonical_string)]
    - Region start_char must be < end_char (zero-length regions are invalid)

    Artifact Detection:
    - Control characters (form feed, null byte) must be removed
    - JSON structural artifacts ({}, [], "key":) are detected only when
      source_is_json=True; scalar content with braces/brackets passes
    - PDF page-number artifacts ("Page X") are detected only when source_is_pdf=True

    Related contract for create_canonical_string:
    - Removes control characters (\\f, \\x00)
    - Extracts scalar values from JSON (removes structural syntax)
    - Handles PDF artifacts when source_is_pdf=True
    """

    def test_validate_ingestion_valid_input(self) -> None:
        """Valid string and regions, verify all True."""
        canonical_string = "This is a valid test string."
        work_regions = [make_work_region(len(canonical_string))]

        result = validate_ingestion(canonical_string, work_regions)

        assert result["encoding_valid"] is True
        assert result["offsets_valid"] is True
        assert result["artifacts_removed"] is True

    def test_validate_ingestion_invalid_offsets(self) -> None:
        """Regions with out-of-bounds offsets, verify offsets_valid=False."""
        canonical_string = "Short string."
        work_regions = [make_work_region(end_char=1000)]  # Out of bounds

        result = validate_ingestion(canonical_string, work_regions)

        assert result["offsets_valid"] is False

    def test_validate_ingestion_start_greater_than_end(self) -> None:
        """Regions with start_char > end_char, verify ValueError at creation time.

        make_work_region now validates this precondition and raises ValueError
        with an actionable error message.
        """
        with pytest.raises(ValueError) as exc_info:
            make_work_region(5, start_char=10)  # start > end is invalid

        # Verify error message mentions the constraint
        assert "end_char (5) must be strictly greater than start_char (10)" in str(exc_info.value)

    def test_validate_ingestion_empty_regions_list_passes(self) -> None:
        """Empty work_regions list should pass offsets_valid.

        This is the expected behavior for empty documents which produce no
        regions instead of a zero-length region.
        """
        canonical_string = ""  # Empty document
        work_regions: list[WorkRegion] = []  # No regions

        result = validate_ingestion(canonical_string, work_regions)

        assert result["encoding_valid"] is True
        assert result["offsets_valid"] is True  # No regions to validate
        assert result["artifacts_removed"] is True
        assert result["offset_mapping_valid"] is True

    def test_validate_ingestion_zero_length_region(self) -> None:
        """Regions with start_char == end_char (zero-length), verify ValueError at creation.

        QA Step 1 expectation: start < end, so zero-length regions are invalid.
        make_work_region now validates this precondition and raises ValueError.
        """
        with pytest.raises(ValueError) as exc_info:
            make_work_region(5, start_char=5)  # start == end is invalid

        # Verify error message mentions the constraint
        assert "end_char (5) must be strictly greater than start_char (5)" in str(exc_info.value)

    def test_validate_ingestion_format_artifacts_present(self) -> None:
        """String with \\f or \\x00, verify artifacts_removed=False."""
        # String with form feed character
        canonical_with_ff = "Text with\fform feed"
        work_regions = [make_work_region(len(canonical_with_ff))]

        result = validate_ingestion(canonical_with_ff, work_regions)

        assert result["artifacts_removed"] is False

        # String with null byte
        canonical_with_null = "Text with\x00null byte"
        work_regions_null = [make_work_region(len(canonical_with_null))]

        result_null = validate_ingestion(canonical_with_null, work_regions_null)

        assert result_null["artifacts_removed"] is False

    def test_validate_ingestion_json_artifacts_only_for_json_source(self) -> None:
        """JSON artifact checks only run when source_is_json=True.

        Text/PDF sources may legitimately contain quotes, colons, and brackets
        in prose, so these should not trigger false positives.
        """
        # Text with legitimate prose containing JSON-like characters
        prose_with_delimiters = 'She said: "Hello, world!" [emphasis mine]'
        work_regions = [make_work_region(len(prose_with_delimiters))]

        # Non-JSON source should pass (default source_is_json=False)
        result = validate_ingestion(prose_with_delimiters, work_regions)
        assert result["artifacts_removed"] is True

        # JSON source with unextracted JSON syntax should fail
        json_artifact = '{"key": "value", "nested": {"a": 1}}'
        work_regions_json = [make_work_region(len(json_artifact))]
        result_json = validate_ingestion(json_artifact, work_regions_json, source_is_json=True)
        assert result_json["artifacts_removed"] is False

    def test_validate_ingestion_json_structural_artifacts_detected(self) -> None:
        """JSON structural patterns should fail validation for JSON sources.

        Context-aware detection flags braces/brackets in structural positions
        (adjacent to colons, commas, at line boundaries) while allowing
        braces/brackets that appear inside scalar string content.
        """
        # Minimal JSON object with braces - structural pattern
        minimal_object = '{"a": 1}'
        result = validate_ingestion(
            minimal_object, [make_work_region(len(minimal_object))], source_is_json=True
        )
        assert result["artifacts_removed"] is False, (
            "Minimal JSON object with braces should fail for JSON sources"
        )

        # Empty JSON object - structural pattern
        empty_object = "{}"
        result = validate_ingestion(
            empty_object, [make_work_region(len(empty_object))], source_is_json=True
        )
        assert result["artifacts_removed"] is False, (
            "Empty JSON object {} should fail for JSON sources"
        )

        # Empty JSON array - structural pattern
        empty_array = "[]"
        result = validate_ingestion(
            empty_array, [make_work_region(len(empty_array))], source_is_json=True
        )
        assert result["artifacts_removed"] is False, (
            "Empty JSON array [] should fail for JSON sources"
        )

        # Quoted key pattern - definite JSON syntax
        quoted_key = 'field "name": value'
        result = validate_ingestion(
            quoted_key, [make_work_region(len(quoted_key))], source_is_json=True
        )
        assert result["artifacts_removed"] is False, (
            "Quoted key pattern should fail for JSON sources"
        )

        # Array with elements - structural pattern (comma followed by bracket)
        array_elements = "[1, 2, 3]"
        result = validate_ingestion(
            array_elements, [make_work_region(len(array_elements))], source_is_json=True
        )
        assert result["artifacts_removed"] is False, (
            "Array with elements should fail for JSON sources"
        )

        # Nested structure - colon followed by brace
        nested_json = 'key: {"nested": "value"}'
        result = validate_ingestion(
            nested_json, [make_work_region(len(nested_json))], source_is_json=True
        )
        assert result["artifacts_removed"] is False, (
            "Nested JSON structure should fail for JSON sources"
        )

        # Empty object on its own line in multi-line content should fail
        empty_obj_on_line = "some text\n{}\nmore text"
        result = validate_ingestion(
            empty_obj_on_line, [make_work_region(len(empty_obj_on_line))], source_is_json=True
        )
        assert result["artifacts_removed"] is False, (
            "Empty {} on its own line should fail for JSON sources"
        )

        # Empty array on its own line in multi-line content should fail
        empty_arr_on_line = "some text\n[]\nmore text"
        result = validate_ingestion(
            empty_arr_on_line, [make_work_region(len(empty_arr_on_line))], source_is_json=True
        )
        assert result["artifacts_removed"] is False, (
            "Empty [] on its own line should fail for JSON sources"
        )

        # Empty object with surrounding whitespace on its own line should fail
        empty_obj_whitespace = "content\n  {}  \nend"
        result = validate_ingestion(
            empty_obj_whitespace, [make_work_region(len(empty_obj_whitespace))], source_is_json=True
        )
        assert result["artifacts_removed"] is False, (
            "Empty {} with whitespace on its own line should fail for JSON sources"
        )

    def test_validate_ingestion_json_scalar_content_with_braces_passes(self) -> None:
        """Braces/brackets inside scalar string values should NOT fail validation.

        Scalar values extracted from JSON may legitimately contain brace/bracket
        characters (e.g., code descriptions, mathematical notation). These should
        pass validation because they are content, not JSON structure.
        """
        # Scalar content describing code with braces/brackets
        code_description = "description: This function returns array [1,2,3] from object {key}"
        result = validate_ingestion(
            code_description, [make_work_region(len(code_description))], source_is_json=True
        )
        assert result["artifacts_removed"] is True, (
            "Scalar content with inline braces/brackets should pass"
        )

        # Multiple extracted values, some containing braces in content
        extracted_values = (
            "title: Understanding JSON {basics}\n"
            "content: Arrays use [square brackets] and objects use {curly braces}\n"
            "author: John Doe"
        )
        result = validate_ingestion(
            extracted_values, [make_work_region(len(extracted_values))], source_is_json=True
        )
        assert result["artifacts_removed"] is True, (
            "Extracted values with inline braces/brackets in content should pass"
        )

        # Mathematical notation with brackets
        math_content = "formula: f(x) = {x | x > 0} and g(x) = [0, 1]"
        result = validate_ingestion(
            math_content, [make_work_region(len(math_content))], source_is_json=True
        )
        assert result["artifacts_removed"] is True, (
            "Mathematical notation with braces/brackets should pass"
        )

        # Clean extracted values should pass
        clean_values = "title: Test Document\nauthor: John Doe\nyear: 2025"
        result = validate_ingestion(
            clean_values, [make_work_region(len(clean_values))], source_is_json=True
        )
        assert result["artifacts_removed"] is True, (
            "Clean extracted values without JSON syntax should pass"
        )

        # Empty braces/brackets inside scalar content should pass (not on their own line)
        # This tests the fix for false positives when {} or [] appear mid-content
        empty_obj_in_content = "description: An empty object {} is used for initialization"
        result = validate_ingestion(
            empty_obj_in_content, [make_work_region(len(empty_obj_in_content))], source_is_json=True
        )
        assert result["artifacts_removed"] is True, "Empty {} inside scalar content should pass"

        empty_arr_in_content = "formula: The empty set is denoted as [] in this notation"
        result = validate_ingestion(
            empty_arr_in_content, [make_work_region(len(empty_arr_in_content))], source_is_json=True
        )
        assert result["artifacts_removed"] is True, "Empty [] inside scalar content should pass"

        # Multiple empty structures inside multi-line content should pass
        multi_empty_in_content = (
            "title: Understanding JSON Patterns\n"
            "content: Use {} for empty objects and [] for empty arrays\n"
            "note: The pattern {} is common in default values"
        )
        result = validate_ingestion(
            multi_empty_in_content,
            [make_work_region(len(multi_empty_in_content))],
            source_is_json=True,
        )
        assert result["artifacts_removed"] is True, (
            "Multiple empty {} and [] inside scalar content across lines should pass"
        )

    def test_validate_ingestion_numbered_content_passes_for_non_pdf(self) -> None:
        """Text with numbered list content should pass for non-PDF sources.

        Page-number artifact checks only run when source_is_pdf=True,
        so numbered content in text/JSON documents should not fail validation.
        """
        # Text with numbered content that could be mistaken for page numbers
        numbered_content = "Step 1: Open the file.\n1\n2\n3\nStep 2: Edit the content."
        work_regions = [make_work_region(len(numbered_content))]

        # Non-PDF source (default) should pass
        result = validate_ingestion(numbered_content, work_regions)
        assert result["artifacts_removed"] is True, (
            "Numbered content should pass for non-PDF sources"
        )

    def test_validate_ingestion_page_pattern_fails_for_pdf_source(self) -> None:
        """'Page X' pattern should fail validation for PDF sources.

        When source_is_pdf=True, explicit page-number patterns should be detected.
        """
        content_with_page_pattern = "Some content here.\nPage 42\nMore content."
        work_regions = [make_work_region(len(content_with_page_pattern))]

        # PDF source should fail due to "Page X" artifact
        result = validate_ingestion(content_with_page_pattern, work_regions, source_is_pdf=True)
        assert result["artifacts_removed"] is False, "'Page X' pattern should fail for PDF sources"

    def test_validate_ingestion_numbered_list_passes_for_pdf(self) -> None:
        """PDF with legitimate numbered list lines should pass validation.

        Bare numbers like '1', '2', '3' in a list context should not be flagged
        as page number artifacts, as they could be legitimate numbered list items.
        """
        # Content with numbered list items (bare numbers on lines)
        numbered_list_content = "Shopping list:\n1\nApples\n2\nBananas\n3\nOranges"
        work_regions = [make_work_region(len(numbered_list_content))]

        # PDF source with numbered list should pass validation
        result = validate_ingestion(numbered_list_content, work_regions, source_is_pdf=True)
        assert result["artifacts_removed"] is True, (
            "Numbered list content should pass for PDF sources"
        )

    def test_validate_ingestion_offset_mapping_valid(self) -> None:
        """Valid offset mapping should pass validation."""
        canonical_string = "Hello world"
        work_regions = [make_work_region(len(canonical_string))]
        # Valid mapping: values within [0, len(canonical_string)] or -1
        offset_mapping = [0, 1, 2, -1, 3, 4, 5, 6, 7, 8, 9, 10, 11]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is True

    def test_validate_ingestion_offset_mapping_out_of_bounds(self) -> None:
        """Offset mapping with value exceeding len(canonical_string) should fail."""
        canonical_string = "Hello"  # Length 5
        work_regions = [make_work_region(len(canonical_string))]
        # Invalid mapping: value 100 exceeds len(canonical_string)
        offset_mapping = [0, 1, 2, 3, 100]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is False

    def test_validate_ingestion_offset_mapping_negative_not_minus_one(self) -> None:
        """Offset mapping with negative value other than -1 should fail."""
        canonical_string = "Hello"
        work_regions = [make_work_region(len(canonical_string))]
        # Invalid mapping: -5 is not a valid value (only -1 is allowed for removed chars)
        offset_mapping = [0, 1, -5, 3, 4]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is False

    def test_validate_ingestion_offset_mapping_none_passes(self) -> None:
        """When offset_mapping is None, offset_mapping_valid should be True."""
        canonical_string = "Hello world"
        work_regions = [make_work_region(len(canonical_string))]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=None)

        assert result["offset_mapping_valid"] is True

    def test_validate_ingestion_offset_mapping_shorter_than_raw(self) -> None:
        """Offset mapping shorter than expected raw length should fail."""
        canonical_string = "Hello"  # Length 5
        work_regions = [make_work_region(len(canonical_string))]
        # Offset mapping has only 3 entries but expected_raw_length is 10
        offset_mapping = [0, 1, 2]

        result = validate_ingestion(
            canonical_string,
            work_regions,
            offset_mapping=offset_mapping,
            expected_raw_length=10,
        )

        assert result["offset_mapping_valid"] is False

    def test_validate_ingestion_offset_mapping_longer_than_raw(self) -> None:
        """Offset mapping longer than expected raw length should fail."""
        canonical_string = "Hello"  # Length 5
        work_regions = [make_work_region(len(canonical_string))]
        # Offset mapping has 10 entries but expected_raw_length is 5
        offset_mapping = [0, 1, 2, 3, 4, -1, -1, -1, -1, -1]

        result = validate_ingestion(
            canonical_string,
            work_regions,
            offset_mapping=offset_mapping,
            expected_raw_length=5,
        )

        assert result["offset_mapping_valid"] is False

    def test_validate_ingestion_offset_mapping_exact_length_passes(self) -> None:
        """Offset mapping with exact expected length should pass."""
        canonical_string = "Hello"  # Length 5
        work_regions = [make_work_region(len(canonical_string))]
        # Offset mapping matches expected_raw_length
        offset_mapping = [0, 1, 2, 3, 4]

        result = validate_ingestion(
            canonical_string,
            work_regions,
            offset_mapping=offset_mapping,
            expected_raw_length=5,
        )

        assert result["offset_mapping_valid"] is True

    def test_validate_ingestion_offset_mapping_no_expected_length_skips_check(self) -> None:
        """When expected_raw_length is None, length check is skipped."""
        canonical_string = "Hello"
        work_regions = [make_work_region(len(canonical_string))]
        # Offset mapping has 8 entries (different from canonical length 5)
        # but expected_raw_length is not provided so length check is skipped.
        # Mapping still covers full range [0, 4] and is monotonic.
        offset_mapping = [0, 1, -1, 2, -1, 3, -1, 4]  # 8 entries, covers 0-4

        result = validate_ingestion(
            canonical_string,
            work_regions,
            offset_mapping=offset_mapping,
            expected_raw_length=None,
        )

        assert result["offset_mapping_valid"] is True

    def test_validate_ingestion_offset_mapping_non_monotonic_fails(self) -> None:
        """Offset mapping with non-monotonic (scrambled) values should fail."""
        canonical_string = "Hello"  # Length 5
        work_regions = [make_work_region(len(canonical_string))]
        # Non-monotonic: 3 appears after 4 (decreasing)
        offset_mapping = [0, 1, 4, 3, 2]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is False

    def test_validate_ingestion_offset_mapping_coverage_min_not_zero_fails(self) -> None:
        """Offset mapping that doesn't start at 0 should fail coverage check."""
        canonical_string = "Hello"  # Length 5
        work_regions = [make_work_region(len(canonical_string))]
        # Mapping starts at 1, not 0 - doesn't cover first char position
        offset_mapping = [1, 2, 3, 4, 4]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is False

    def test_validate_ingestion_offset_mapping_coverage_max_too_low_fails(self) -> None:
        """Offset mapping that doesn't reach last char position should fail."""
        canonical_string = "Hello"  # Length 5, last position is 4
        work_regions = [make_work_region(len(canonical_string))]
        # Mapping max is 3, but canonical_len - 1 is 4
        offset_mapping = [0, 1, 2, 3, 3]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is False

    def test_validate_ingestion_offset_mapping_work_region_start_missing_fails(self) -> None:
        """Offset mapping missing work region start_char should fail."""
        canonical_string = "Hello"  # Length 5
        # Start at position 2
        work_regions = [make_work_region(len(canonical_string), start_char=2)]
        # Mapping covers 0, 1, 3, 4 but not 2 (the region start)
        offset_mapping = [0, 1, -1, 3, 4]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is False

    def test_validate_ingestion_offset_mapping_work_region_end_missing_fails(self) -> None:
        """Offset mapping missing work region end_char should fail (unless end_char == len)."""
        canonical_string = "Hello"  # Length 5
        # End at position 3 (exclusive), not at len
        work_regions = [make_work_region(end_char=3)]
        # Mapping covers 0, 1, 2, 4 but not 3 (the region end)
        offset_mapping = [0, 1, 2, -1, 4]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is False

    def test_validate_ingestion_offset_mapping_work_region_end_at_len_passes(self) -> None:
        """Work region end_char at canonical_len is allowed without being in mapping."""
        canonical_string = "Hello"  # Length 5
        # End at len(canonical_string), exclusive end
        work_regions = [make_work_region(end_char=5)]
        # Mapping covers 0-4 (the character positions), no value 5
        # This should pass because end_char=5 equals canonical_len
        offset_mapping = [0, 1, 2, 3, 4]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is True

    def test_validate_ingestion_offset_mapping_all_removed_non_empty_fails(self) -> None:
        """Non-empty canonical string with all mapping entries -1 should fail."""
        canonical_string = "Hello"  # Length 5
        work_regions = [make_work_region(len(canonical_string))]
        # All entries are -1 (all removed), but canonical string is non-empty
        offset_mapping = [-1, -1, -1, -1, -1]

        result = validate_ingestion(canonical_string, work_regions, offset_mapping=offset_mapping)

        assert result["offset_mapping_valid"] is False


class TestMakeWorkRegion:
    """Tests for make_work_region test helper function."""

    def test_make_work_region_end_char_required(self) -> None:
        """end_char is a required positional argument."""
        region = make_work_region(100)
        assert region.end_char == 100

    def test_make_work_region_with_start_char(self) -> None:
        """end_char with start_char creates valid region."""
        region = make_work_region(50, start_char=10)
        assert region.start_char == 10
        assert region.end_char == 50

    def test_make_work_region_with_all_kwargs(self) -> None:
        """All keyword arguments are set correctly."""
        region = make_work_region(
            100,
            region_id="my_region",
            doc_id="my_doc",
            start_char=25,
            is_processed=True,
            created_at="2025-06-15T12:00:00Z",
        )
        assert region.end_char == 100
        assert region.region_id == "my_region"
        assert region.doc_id == "my_doc"
        assert region.start_char == 25
        assert region.is_processed is True
        assert region.created_at == "2025-06-15T12:00:00Z"

    def test_make_work_region_end_char_must_be_greater_than_start_char(self) -> None:
        """end_char must be strictly greater than start_char."""
        with pytest.raises(
            ValueError, match=r"end_char \(5\) must be strictly greater than start_char \(10\)"
        ):
            make_work_region(5, start_char=10)

    def test_make_work_region_end_char_equal_to_start_char_raises(self) -> None:
        """end_char equal to start_char raises ValueError."""
        with pytest.raises(
            ValueError, match=r"end_char \(5\) must be strictly greater than start_char \(5\)"
        ):
            make_work_region(5, start_char=5)


class TestHasIsolatedPageNumbers:
    """Tests for _has_isolated_page_numbers function.

    INTENTIONAL COUPLING: These tests deliberately lock in the current PDF
    page-number heuristics and must be updated together with any changes to
    PAGE_NUMBER_ADJACENCY_GAP in document_ingestion.py. This coupling is
    intentional to ensure heuristic changes are reviewed together with their
    test implications. See the NOTE comment near PAGE_NUMBER_ADJACENCY_GAP
    in document_ingestion.py for the corresponding cross-reference.
    """

    def test_default_adjacency_gap_constant(self) -> None:
        """Verify PAGE_NUMBER_ADJACENCY_GAP has expected default value.

        This test intentionally locks the heuristic value. If this test fails,
        update both the assertion here AND the dependent tests below that rely
        on the default gap behavior (test_consecutive_numbers_within_default_gap_*).
        """
        assert PAGE_NUMBER_ADJACENCY_GAP == 4

    def test_consecutive_numbers_within_default_gap_not_isolated(self) -> None:
        """Numbers within default adjacency gap are treated as a sequence."""
        # Numbers with 3 lines between them (within default gap of 4)
        text = "1\nApples\nOranges\nBananas\n2\nGrapes\nMelons\nPears\n3"
        result = _has_isolated_page_numbers(text)
        assert result is False

    def test_consecutive_numbers_beyond_default_gap_are_isolated(self) -> None:
        """Numbers beyond default adjacency gap are treated as isolated."""
        # Numbers with 5 lines between them (beyond default gap of 4)
        text = "1\nA\nB\nC\nD\nE\n2\nF\nG\nH\nI\nJ\n3"
        result = _has_isolated_page_numbers(text)
        assert result is True

    def test_custom_adjacency_gap_small(self) -> None:
        """Smaller adjacency gap treats spaced numbers as isolated."""
        # Numbers with 3 lines between them
        text = "1\nApples\nOranges\nBananas\n2"
        # With gap of 2, these are isolated (4 lines apart > 2)
        result = _has_isolated_page_numbers(text, adjacency_gap=2)
        assert result is True

    def test_custom_adjacency_gap_large(self) -> None:
        """Larger adjacency gap treats widely spaced numbers as sequence."""
        # Numbers with 6 lines between them
        text = "1\nA\nB\nC\nD\nE\nF\n2\nG\nH\nI\nJ\nK\nL\n3"
        # With gap of 10, these are consecutive (within gap)
        result = _has_isolated_page_numbers(text, adjacency_gap=10)
        assert result is False

    def test_no_digit_lines_returns_false(self) -> None:
        """Text without digit-only lines returns False."""
        text = "Hello world\nThis is a test\nNo numbers here"
        result = _has_isolated_page_numbers(text)
        assert result is False

    def test_single_isolated_number_below_min_occurrences(self) -> None:
        """Single isolated number doesn't trigger detection (default min_occurrences=2)."""
        text = "Some text\n42\nMore text"
        result = _has_isolated_page_numbers(text)
        assert result is False

    def test_two_isolated_numbers_meets_min_occurrences(self) -> None:
        """Two isolated numbers triggers detection (default min_occurrences=2)."""
        text = "Some text\n42\nMore text\n99\nEnd"
        result = _has_isolated_page_numbers(text)
        assert result is True

    def test_custom_min_occurrences(self) -> None:
        """Custom min_occurrences changes threshold."""
        text = "Some text\n42\nMore text\n99\nEnd"
        # With min_occurrences=3, 2 isolated numbers don't trigger
        result = _has_isolated_page_numbers(text, min_occurrences=3)
        assert result is False

    def test_mixed_sequence_and_isolated(self) -> None:
        """Mix of consecutive sequence and isolated numbers."""
        # 1, 2, 3 form a sequence; 99 is isolated
        text = "1\nApple\n2\nBanana\n3\nCherry\n\n\n\n\n\n\n99"
        result = _has_isolated_page_numbers(text)
        # Only 99 is isolated, which is < 2, so False
        assert result is False


class TestIngestDocument:
    """Tests for ingest_document function."""

    def test_ingest_document_text_file_end_to_end(self, fs: FakeFilesystem) -> None:
        """Create text file, verify full pipeline."""
        content = "Hello, world!\r\nThis is a test.\r\n"
        file_path = Path("/test_data/doc.txt")
        fs.create_file(str(file_path), contents=content)

        canonical, doc_id, regions, offset_mapping, validation = ingest_document(file_path)

        # Verify canonical string is normalized
        assert "\r" not in canonical
        # Verify doc_id format
        assert doc_id.startswith("text_doc_")
        # Verify regions
        assert len(regions) == 1
        assert regions[0].start_char == 0
        assert regions[0].end_char == len(canonical)
        # Verify offset mapping is returned (length may vary due to line ending normalization)
        assert isinstance(offset_mapping, list)
        assert len(offset_mapping) > 0
        # Verify validation passes
        assert validation["encoding_valid"] is True
        assert validation["offsets_valid"] is True
        assert validation["artifacts_removed"] is True

    def test_ingest_document_json_file_end_to_end(self, fs: FakeFilesystem) -> None:
        """Create JSON file, verify full pipeline with key preservation."""
        json_content = {"title": "Test", "content": "Sample content here."}
        file_path = Path("/test_data/doc.json")
        fs.create_file(str(file_path), contents=json.dumps(json_content))

        canonical, doc_id, _, offset_mapping, validation = ingest_document(file_path)

        # Verify key-prefixed content is extracted
        assert "title: Test" in canonical
        assert "content: Sample content here" in canonical
        # Verify doc_id format
        assert doc_id.startswith("json_doc_")
        # Verify offset mapping is returned
        assert isinstance(offset_mapping, list)
        # Verify validation passes
        assert all(validation.values())

    def test_ingest_document_unsupported_format(self, fs: FakeFilesystem) -> None:
        """Create .docx file, verify ValueError raised."""
        file_path = Path("/test_data/doc.docx")
        fs.create_file(str(file_path), contents=b"dummy docx content")

        with pytest.raises(ValueError, match=r"Unsupported file format: \.docx"):
            ingest_document(file_path)

    def test_ingest_document_empty_text_file(self, fs: FakeFilesystem) -> None:
        """Create empty text file, verify canonical is empty and no regions are created."""
        file_path = Path("/test_data/empty.txt")
        fs.create_file(str(file_path), contents="")

        canonical, doc_id, regions, offset_mapping, validation = ingest_document(file_path)

        # Verify canonical string is empty
        assert canonical == ""
        # Verify doc_id format
        assert doc_id.startswith("text_empty_")
        # Verify offset mapping is empty for empty input
        assert offset_mapping == []
        # Verify regions - empty documents produce no regions
        assert len(regions) == 0
        # Verify validation - all checks pass for empty documents with no regions
        assert validation["encoding_valid"] is True
        assert validation["offsets_valid"] is True  # No regions to validate
        # artifacts_removed is True since empty string has no artifacts
        assert validation["artifacts_removed"] is True

    def test_ingest_document_pdf_no_extractable_text(
        self, fs: FakeFilesystem, mocker: MockerFixture
    ) -> None:
        """Mock PDF that yields empty text, verify canonical is empty and no regions are created."""
        # Create mock page with no extractable text
        mock_page = mocker.MagicMock()
        mock_page.extract_text.return_value = ""
        mock_reader = mocker.MagicMock()
        mock_reader.pages = [mock_page]
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        file_path = Path("/test_data/empty_content.pdf")
        fs.create_file(str(file_path), contents=b"dummy pdf content")

        canonical, doc_id, regions, offset_mapping, validation = ingest_document(file_path)

        # Verify canonical string is empty
        assert canonical == ""
        # Verify doc_id format
        assert doc_id.startswith("pdf_empty_content_")
        # Verify regions - empty documents produce no regions
        assert len(regions) == 0
        # Verify offset mapping is empty for empty input
        assert offset_mapping == []
        # Verify validation - all checks pass for empty documents with no regions
        assert validation["encoding_valid"] is True
        assert validation["offsets_valid"] is True  # No regions to validate
        assert validation["artifacts_removed"] is True

    def test_ingest_document_malformed_json(self, fs: FakeFilesystem) -> None:
        """Create .json file with invalid JSON, verify JSONDecodeError raised."""
        # Invalid JSON content (missing closing brace)
        malformed_json = '{"title": "Test", "incomplete": '
        file_path = Path("/test_data/malformed.json")
        fs.create_file(str(file_path), contents=malformed_json)

        with pytest.raises(json.JSONDecodeError):
            ingest_document(file_path)

    def test_ingest_document_malformed_json_preserves_cause(self, fs: FakeFilesystem) -> None:
        """Verify JSONDecodeError preserves original ijson exception as __cause__."""
        # Invalid JSON with syntax error
        malformed_json = "{key: value}"
        file_path = Path("/test_data/syntax_error.json")
        fs.create_file(str(file_path), contents=malformed_json)

        with pytest.raises(json.JSONDecodeError) as exc_info:
            ingest_document(file_path)

        # Verify the original ijson exception is preserved as __cause__
        assert exc_info.value.__cause__ is not None
        cause_type = type(exc_info.value.__cause__).__name__
        # Should be an ijson exception (IncompleteJSONError, UnexpectedSymbol, etc.)
        assert "Error" in cause_type or "Symbol" in cause_type

    def test_ingest_document_malformed_json_has_position(self, fs: FakeFilesystem) -> None:
        """Verify JSONDecodeError includes extracted position when available."""
        # Invalid JSON with syntax error at known position
        malformed_json = '{"key": value}'  # error at 'value' position (around 8)
        file_path = Path("/test_data/position_error.json")
        fs.create_file(str(file_path), contents=malformed_json)

        with pytest.raises(json.JSONDecodeError) as exc_info:
            ingest_document(file_path)

        # The pos attribute should be set (may be 0 if position couldn't be extracted,
        # or a positive value if extraction succeeded)
        assert hasattr(exc_info.value, "pos")
        assert isinstance(exc_info.value.pos, int)
        assert exc_info.value.pos >= 0

    def test_ingest_document_uses_chunking_by_default(self, fs: FakeFilesystem) -> None:
        """Verify ingest_document uses default chunk_size (not 0)."""
        # Create a document larger than the default chunk size
        paragraphs = [f"Paragraph {i}. " + "x" * 500 for i in range(100)]
        content = "\n\n".join(paragraphs)  # ~50KB document
        file_path = Path("/test_data/large_doc.txt")
        fs.create_file(str(file_path), contents=content)

        # Ingest with default chunk_size (should produce multiple regions)
        canonical, _doc_id, regions, _offset_mapping, validation = ingest_document(file_path)

        # Verify multiple work regions are created for large documents
        assert len(regions) > 1, (
            f"Expected multiple regions for large document, got {len(regions)}. "
            f"Document size: {len(canonical)} chars, default chunk size: {DEFAULT_CHUNK_SIZE}"
        )

        # Verify regions are contiguous and non-overlapping
        for i in range(len(regions) - 1):
            assert regions[i].end_char == regions[i + 1].start_char

        # Verify total coverage equals document length
        total_coverage = sum(r.end_char - r.start_char for r in regions)
        assert total_coverage == len(canonical)

        # Verify validation passes
        assert all(validation.values())

    def test_ingest_document_explicit_chunk_size(self, fs: FakeFilesystem) -> None:
        """Verify ingest_document respects explicit chunk_size parameter."""
        # Create a moderate-sized document
        paragraphs = [f"Paragraph {i}. " + "content " * 50 for i in range(20)]
        content = "\n\n".join(paragraphs)
        file_path = Path("/test_data/moderate_doc.txt")
        fs.create_file(str(file_path), contents=content)

        # Ingest with small chunk size to force chunking
        _canonical, _doc_id, regions, _, _validation = ingest_document(file_path, chunk_size=500)

        # Verify multiple regions are created
        assert len(regions) > 1

        # Verify each region is approximately chunk_size (allowing for boundary adjustment)
        for region in regions[:-1]:  # Exclude last region which may be smaller
            region_size = region.end_char - region.start_char
            # Region should be close to chunk size (within 50% margin for boundary adjustments)
            assert region_size <= 750  # 500 * 1.5

    def test_ingest_document_chunk_size_zero_disables_chunking(self, fs: FakeFilesystem) -> None:
        """Verify chunk_size=0 creates single region regardless of document size."""
        # Create a large document
        paragraphs = [f"Paragraph {i}. " + "x" * 500 for i in range(100)]
        content = "\n\n".join(paragraphs)
        file_path = Path("/test_data/large_doc_no_chunk.txt")
        fs.create_file(str(file_path), contents=content)

        # Ingest with chunk_size=0 to disable chunking
        canonical, _doc_id, regions, _, _validation = ingest_document(file_path, chunk_size=0)

        # Verify single region even for large document
        assert len(regions) == 1
        assert regions[0].start_char == 0
        assert regions[0].end_char == len(canonical)

    def test_ingest_document_multi_chunk_regions_contiguous(self, fs: FakeFilesystem) -> None:
        """Verify multi-chunk regions are strictly contiguous with no gaps or overlaps."""
        # Create document with distinct paragraphs
        paragraphs = [f"Paragraph {i}: " + "sentence " * 100 for i in range(50)]
        content = "\n\n".join(paragraphs)
        file_path = Path("/test_data/paragraphed_doc.txt")
        fs.create_file(str(file_path), contents=content)

        # Use small chunk size to force multiple chunks
        canonical, _doc_id, regions, _, _validation = ingest_document(file_path, chunk_size=1000)

        # Verify first region starts at 0
        assert regions[0].start_char == 0

        # Verify last region ends at document length
        assert regions[-1].end_char == len(canonical)

        # Verify no gaps: each region starts exactly where previous ended
        for i in range(len(regions) - 1):
            assert regions[i].end_char == regions[i + 1].start_char, (
                f"Gap between region {i} and {i + 1}: "
                f"region {i} ends at {regions[i].end_char}, "
                f"region {i + 1} starts at {regions[i + 1].start_char}"
            )

        # Verify total coverage equals document length
        total_coverage = sum(r.end_char - r.start_char for r in regions)
        assert total_coverage == len(canonical)

        # Verify each character is covered exactly once
        coverage = [0] * len(canonical)
        for region in regions:
            for j in range(region.start_char, region.end_char):
                coverage[j] += 1
        assert all(c == 1 for c in coverage), "Some chars covered multiple times or not at all"


class TestDocumentIngestionMain:
    """Tests for document_ingestion_main function."""

    def test_document_ingestion_main_success(
        self, fs: FakeFilesystem, mock_repo_root: Path
    ) -> None:
        """Create args and input file, verify outputs created, return 0."""
        # Create input file
        content = "Test document content."
        input_path = Path("/test_repo/input.txt")
        fs.create_file(str(input_path), contents=content)

        # Create output directory structure
        output_dir = Path("/test_repo/.tmp/ingestion")
        fs.create_dir(str(output_dir.parent))

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify success
        assert result == 0

        # Verify output files were created
        assert output_dir.exists()
        output_files = list(output_dir.iterdir())
        # Should have 4 files: canonical, work_regions, offset_mapping, validation
        assert len(output_files) == 4
        # Check file names
        file_names = [f.name for f in output_files]
        assert any("_canonical.txt" in name for name in file_names)
        assert any("_work_regions.json" in name for name in file_names)
        assert any("_offset_mapping.json" in name for name in file_names)
        assert any("_validation.json" in name for name in file_names)

    def test_document_ingestion_main_dry_run(
        self, fs: FakeFilesystem, mock_repo_root: Path
    ) -> None:
        """dry_run=True, verify no files created, return 0."""
        # Create input file
        content = "Test document content."
        input_path = Path("/test_repo/input.txt")
        fs.create_file(str(input_path), contents=content)

        output_dir = Path("/test_repo/.tmp/ingestion")

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=True,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify success
        assert result == 0
        # Verify output directory was NOT created
        assert not output_dir.exists()

    def test_document_ingestion_main_validate_only(
        self, fs: FakeFilesystem, mock_repo_root: Path
    ) -> None:
        """validate_only=True, verify no output files, return 0."""
        # Create input file
        content = "Test document content."
        input_path = Path("/test_repo/input.txt")
        fs.create_file(str(input_path), contents=content)

        output_dir = Path("/test_repo/.tmp/ingestion")

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=True,
        )

        result = document_ingestion_main(args)

        # Verify success
        assert result == 0
        # Verify output directory was NOT created
        assert not output_dir.exists()

    def test_document_ingestion_main_file_not_found(
        self, fs: FakeFilesystem, mock_repo_root: Path
    ) -> None:
        """Non-existent input, verify return 1."""
        input_path = Path("/test_repo/nonexistent.txt")
        output_dir = Path("/test_repo/.tmp/ingestion")

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify error return
        assert result == 1

    def test_document_ingestion_main_json_decode_error(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str], mock_repo_root: Path
    ) -> None:
        """Malformed JSON input, verify JSONDecodeError caught and return 1."""
        # Create malformed JSON file
        malformed_json = '{"key": "value", "incomplete": '
        input_path = Path("/test_repo/bad.json")
        fs.create_file(str(input_path), contents=malformed_json)

        output_dir = Path("/test_repo/.tmp/ingestion")

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify error return
        assert result == 1
        # Verify appropriate error message
        captured = capsys.readouterr()
        assert "Invalid JSON" in captured.err

    def test_document_ingestion_main_import_error(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        mocker: MockerFixture,
        mock_repo_root: Path,
    ) -> None:
        """Missing pypdf dependency, verify ImportError caught and return 1."""
        # Create a PDF file
        input_path = Path("/test_repo/sample.pdf")
        fs.create_file(str(input_path), contents=b"dummy pdf content")

        output_dir = Path("/test_repo/.tmp/ingestion")

        # Mock ingest_pdf_file to raise ImportError
        mocker.patch(
            "scripts.knowledge.document_ingestion.ingest_pdf_file",
            side_effect=ImportError("No module named 'pypdf'"),
        )

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify error return
        assert result == 1
        # Verify appropriate error message
        captured = capsys.readouterr()
        assert "Missing dependency" in captured.err

    def test_document_ingestion_main_permission_error(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        mocker: MockerFixture,
        mock_repo_root: Path,
    ) -> None:
        """File permission error, verify OSError caught and return 1."""
        # Create a text file
        input_path = Path("/test_repo/restricted.txt")
        fs.create_file(str(input_path), contents="test content")

        output_dir = Path("/test_repo/.tmp/ingestion")

        # Mock ingest_text_file to raise PermissionError (subclass of OSError)
        mocker.patch(
            "scripts.knowledge.document_ingestion.ingest_text_file",
            side_effect=PermissionError("Permission denied"),
        )

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify error return
        assert result == 1
        # Verify appropriate error message
        captured = capsys.readouterr()
        assert "File I/O error" in captured.err

    def test_document_ingestion_main_pypdf_error(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        mocker: MockerFixture,
        mock_repo_root: Path,
    ) -> None:
        """PDF parsing error from pypdf, verify caught and return 1."""
        # Create a PDF file
        input_path = Path("/test_repo/corrupt.pdf")
        fs.create_file(str(input_path), contents=b"corrupt pdf content")

        output_dir = Path("/test_repo/.tmp/ingestion")

        # Mock ingest_pdf_file to raise PyPdfError (the base pypdf exception class)
        # This tests that explicit exception catching works correctly
        mocker.patch(
            "scripts.knowledge.document_ingestion.ingest_pdf_file",
            side_effect=PyPdfError("Could not read PDF"),
        )

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify error return
        assert result == 1
        # Verify appropriate error message
        captured = capsys.readouterr()
        assert "PDF parsing error" in captured.err

    def test_document_ingestion_main_unexpected_exception_reraises(
        self, fs: FakeFilesystem, mocker: MockerFixture, mock_repo_root: Path
    ) -> None:
        """Unexpected exception type is re-raised, not swallowed."""
        # Create a text file
        input_path = Path("/test_repo/test.txt")
        fs.create_file(str(input_path), contents="test content")

        output_dir = Path("/test_repo/.tmp/ingestion")

        # Create a custom exception that should be re-raised
        class UnexpectedException(Exception):
            pass

        # Mock ingest_document to raise the unexpected exception
        mocker.patch(
            "scripts.knowledge.document_ingestion.ingest_document",
            side_effect=UnexpectedException("Unexpected error"),
        )

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        # The unexpected exception should be re-raised
        with pytest.raises(UnexpectedException, match="Unexpected error"):
            document_ingestion_main(args)

    def test_document_ingestion_main_validation_failure_stops_no_output(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        mock_repo_root: Path,
        mocker: MockerFixture,
    ) -> None:
        """Validation failure in normal mode, verify STOP+REPORT: return 1 and no files written.

        This tests the QA Strategy Step 1 requirement that validation failures should
        STOP + REPORT, meaning:
        1. The command returns non-zero
        2. Output artifacts are NOT written
        """
        # Mock PDF that produces content with page number artifacts.
        # The PDF ingestion removes some page numbers but isolated ones may remain.
        # We mock the PDF reader to return content with isolated page numbers.
        mock_page1 = mocker.MagicMock()
        mock_page1.extract_text.return_value = "Content from page.\n1\nMore content."
        mock_page2 = mocker.MagicMock()
        mock_page2.extract_text.return_value = "Second page content.\n42\nEnd."
        mock_reader = mocker.MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]
        mocker.patch("pypdf.PdfReader", return_value=mock_reader)

        input_path = Path("/test_repo/has_page_numbers.pdf")
        fs.create_file(str(input_path), contents=b"dummy pdf content")

        output_dir = Path("/test_repo/.tmp/ingestion")

        args = argparse.Namespace(
            input=[str(input_path)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify error return (STOP)
        assert result == 1

        # Verify appropriate error message (REPORT)
        captured = capsys.readouterr()
        assert "Validation failed" in captured.err
        assert "artifacts_removed: FAIL" in captured.err

        # Verify output directory was NOT created (no files written)
        assert not output_dir.exists()

    def test_document_ingestion_main_multiple_files(
        self, fs: FakeFilesystem, mock_repo_root: Path
    ) -> None:
        """Multiple input files, verify all processed and outputs created."""
        # Create multiple input files
        input_path1 = Path("/test_repo/doc1.txt")
        input_path2 = Path("/test_repo/doc2.txt")
        fs.create_file(str(input_path1), contents="Document 1 content.")
        fs.create_file(str(input_path2), contents="Document 2 content.")

        output_dir = Path("/test_repo/.tmp/ingestion")
        fs.create_dir(str(output_dir.parent))

        args = argparse.Namespace(
            input=[str(input_path1), str(input_path2)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify success
        assert result == 0

        # Verify output files were created for both documents
        assert output_dir.exists()
        output_files = list(output_dir.iterdir())
        # Should have 8 files: 4 per document
        assert len(output_files) == 8

    def test_document_ingestion_main_directory_input(
        self, fs: FakeFilesystem, mock_repo_root: Path
    ) -> None:
        """Directory input, verify all supported files in directory are processed."""
        # Create a directory with multiple files
        input_dir = Path("/test_repo/docs")
        fs.create_file(str(input_dir / "file1.txt"), contents="File 1 content.")
        fs.create_file(str(input_dir / "file2.md"), contents="File 2 content.")
        fs.create_file(str(input_dir / "file3.json"), contents='{"key": "value"}')

        output_dir = Path("/test_repo/.tmp/ingestion")

        args = argparse.Namespace(
            input=[str(input_dir)],
            output=str(output_dir),
            chunk_size=DEFAULT_CHUNK_SIZE,
            dry_run=False,
            validate_only=False,
        )

        result = document_ingestion_main(args)

        # Verify success
        assert result == 0

        # Verify output files were created for all three documents
        assert output_dir.exists()
        output_files = list(output_dir.iterdir())
        # Should have 12 files: 4 per document
        assert len(output_files) == 12


class TestIsTextFile:
    """Tests for is_text_file function."""

    def test_is_text_file_known_extension(self, fs: FakeFilesystem) -> None:
        """Known text extensions return True."""
        file_path = Path("/test_data/sample.txt")
        fs.create_file(str(file_path), contents="Hello, world!")

        assert is_text_file(file_path) is True

    def test_is_text_file_markdown_extension(self, fs: FakeFilesystem) -> None:
        """Markdown files return True."""
        file_path = Path("/test_data/readme.md")
        fs.create_file(str(file_path), contents="# Heading")

        assert is_text_file(file_path) is True

    def test_is_text_file_unknown_extension(self, fs: FakeFilesystem) -> None:
        """Unknown extensions return False."""
        file_path = Path("/test_data/sample.xyz")
        fs.create_file(str(file_path), contents="Some content")

        assert is_text_file(file_path) is False

    def test_is_text_file_no_extension_utf8_text(self, fs: FakeFilesystem) -> None:
        """File without extension, valid UTF-8, returns True."""
        file_path = Path("/test_data/LICENSE")
        fs.create_file(str(file_path), contents="MIT License\nCopyright 2025")

        assert is_text_file(file_path) is True

    def test_is_text_file_no_extension_non_utf8_text_no_null_bytes(
        self, fs: FakeFilesystem
    ) -> None:
        """File without extension, non-UTF-8 but no null bytes, returns True.

        This tests the fix for the latin-1 decode try/except issue.
        Latin-1 never raises UnicodeDecodeError, so the old code had
        unreachable error handling. The fix simplifies to check for null bytes.
        """
        # Non-UTF-8 bytes (latin-1 encoded text)
        latin1_content = b"Caf\xe9 au lait"  # Contains byte 0xe9 (e-acute in latin-1)
        file_path = Path("/test_data/NOTES")
        fs.create_file(str(file_path), contents=latin1_content)

        # Should return True because no null bytes, even though not valid UTF-8
        assert is_text_file(file_path) is True

    def test_is_text_file_no_extension_binary_with_null_bytes(self, fs: FakeFilesystem) -> None:
        """File without extension, binary content with null bytes, returns False."""
        # Binary content with null bytes
        binary_content = b"Some text\x00binary\x00content"
        file_path = Path("/test_data/BINARY")
        fs.create_file(str(file_path), contents=binary_content)

        assert is_text_file(file_path) is False

    def test_is_text_file_no_extension_null_bytes_after_1024(self, fs: FakeFilesystem) -> None:
        """File without extension, null bytes after first 1024 bytes, returns True.

        The null-byte check only examines the first 1024 bytes.
        """
        # Content with null byte at position > 1024
        content = b"A" * 1500 + b"\x00" + b"more content"
        file_path = Path("/test_data/MOSTLY_TEXT")
        fs.create_file(str(file_path), contents=content)

        # Should return True because null byte is beyond the first 1024 bytes checked
        assert is_text_file(file_path) is True

    def test_is_text_file_os_error(self, fs: FakeFilesystem) -> None:
        """OSError during read returns False."""
        file_path = Path("/test_data/nonexistent_file")
        # Don't create the file to cause an OSError

        assert is_text_file(file_path) is False

    def test_is_text_file_utf16_le_bom(self, fs: FakeFilesystem) -> None:
        """UTF-16 LE file with BOM returns True (even with null bytes)."""
        # UTF-16 LE BOM followed by "Hello" encoded as UTF-16 LE
        utf16_le_content = b"\xff\xfeH\x00e\x00l\x00l\x00o\x00"
        file_path = Path("/test_data/UTF16LE_FILE")
        fs.create_file(str(file_path), contents=utf16_le_content)

        # Should return True because BOM is recognized
        assert is_text_file(file_path) is True

    def test_is_text_file_utf16_be_bom(self, fs: FakeFilesystem) -> None:
        """UTF-16 BE file with BOM returns True (even with null bytes)."""
        # UTF-16 BE BOM followed by "Hello" encoded as UTF-16 BE
        utf16_be_content = b"\xfe\xff\x00H\x00e\x00l\x00l\x00o"
        file_path = Path("/test_data/UTF16BE_FILE")
        fs.create_file(str(file_path), contents=utf16_be_content)

        # Should return True because BOM is recognized
        assert is_text_file(file_path) is True

    def test_is_text_file_utf32_le_bom(self, fs: FakeFilesystem) -> None:
        """UTF-32 LE file with BOM returns True (even with null bytes)."""
        # UTF-32 LE BOM followed by "Hi" encoded as UTF-32 LE
        utf32_le_content = b"\xff\xfe\x00\x00H\x00\x00\x00i\x00\x00\x00"
        file_path = Path("/test_data/UTF32LE_FILE")
        fs.create_file(str(file_path), contents=utf32_le_content)

        # Should return True because BOM is recognized
        assert is_text_file(file_path) is True

    def test_is_text_file_utf32_be_bom(self, fs: FakeFilesystem) -> None:
        """UTF-32 BE file with BOM returns True (even with null bytes)."""
        # UTF-32 BE BOM followed by "Hi" encoded as UTF-32 BE
        utf32_be_content = b"\x00\x00\xfe\xff\x00\x00\x00H\x00\x00\x00i"
        file_path = Path("/test_data/UTF32BE_FILE")
        fs.create_file(str(file_path), contents=utf32_be_content)

        # Should return True because BOM is recognized
        assert is_text_file(file_path) is True

    def test_is_text_file_utf8_bom(self, fs: FakeFilesystem) -> None:
        """UTF-8 file with BOM returns True."""
        # UTF-8 BOM followed by "Hello"
        utf8_bom_content = b"\xef\xbb\xbfHello, world!"
        file_path = Path("/test_data/UTF8BOM_FILE")
        fs.create_file(str(file_path), contents=utf8_bom_content)

        # Should return True because BOM is recognized
        assert is_text_file(file_path) is True

    def test_is_text_file_bom_decode_failure_returns_false(self, fs: FakeFilesystem) -> None:
        """File with BOM but invalid encoding data returns False.

        When a file has a recognized BOM but the subsequent content cannot be
        decoded with that encoding, the function should return False instead
        of True. This tests the fix for the decode failure handling.
        """
        # UTF-16 LE BOM followed by invalid byte sequence that can't decode as UTF-16
        # UTF-16 LE expects pairs of bytes; an odd number of content bytes after BOM
        # will cause a decode error
        invalid_utf16_content = b"\xff\xfe" + b"\x00" * 3  # 3 bytes after BOM = incomplete
        file_path = Path("/test_data/INVALID_UTF16")
        fs.create_file(str(file_path), contents=invalid_utf16_content)

        # Should return False because decode fails even though BOM is recognized
        assert is_text_file(file_path) is False


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parse_args_valid_chunk_size(self) -> None:
        """Verify valid chunk_size values are accepted."""
        args = parse_args(["--input", "test.txt", "--chunk-size", "1000"])
        assert args.chunk_size == 1000

    def test_parse_args_chunk_size_zero_accepted(self) -> None:
        """Verify chunk_size=0 is accepted (disables chunking)."""
        args = parse_args(["--input", "test.txt", "--chunk-size", "0"])
        assert args.chunk_size == 0

    def test_parse_args_negative_chunk_size_rejected(self) -> None:
        """Verify negative chunk_size raises SystemExit (argparse error)."""
        with pytest.raises(SystemExit):
            parse_args(["--input", "test.txt", "--chunk-size", "-1"])

    def test_parse_args_large_negative_chunk_size_rejected(self) -> None:
        """Verify large negative chunk_size raises SystemExit."""
        with pytest.raises(SystemExit):
            parse_args(["--input", "test.txt", "--chunk-size", "-1000"])

    def test_parse_args_default_chunk_size(self) -> None:
        """Verify default chunk_size is DEFAULT_CHUNK_SIZE."""
        args = parse_args(["--input", "test.txt"])
        assert args.chunk_size == DEFAULT_CHUNK_SIZE


class TestExpandInputPaths:
    """Tests for expand_input_paths function."""

    def test_glob_pattern_filters_allowed_extensions(self, fs: FakeFilesystem) -> None:
        """Glob patterns should filter by allowed extensions like directory scanning."""
        base_path = Path("/test_data")
        fs.create_file("/test_data/file.txt", contents="text content")
        fs.create_file("/test_data/file.py", contents="python content")
        fs.create_file("/test_data/file.pdf", contents="pdf content")
        fs.create_file("/test_data/file.exe", contents="binary content")
        fs.create_file("/test_data/file.bin", contents="binary content")
        fs.create_file("/test_data/file.dll", contents="binary content")

        result = expand_input_paths(["*.txt", "*.py", "*.pdf", "*.exe", "*.bin"], base_path)

        # Should include .txt, .py, .pdf (allowed extensions)
        # Should exclude .exe, .bin (not in allowed extensions)
        result_names = {p.name for p in result}
        assert "file.txt" in result_names
        assert "file.py" in result_names
        assert "file.pdf" in result_names
        assert "file.exe" not in result_names
        assert "file.bin" not in result_names

    def test_glob_pattern_handles_no_extension_text_file(self, fs: FakeFilesystem) -> None:
        """Glob patterns should include extension-less files that are text."""
        base_path = Path("/test_data")
        # Create a text file without extension (like LICENSE, README)
        fs.create_file("/test_data/LICENSE", contents="MIT License text content")

        result = expand_input_paths(["LICENSE"], base_path)

        # Should include LICENSE since is_text_file would return True
        result_names = {p.name for p in result}
        assert "LICENSE" in result_names

    def test_glob_pattern_excludes_no_extension_binary_file(self, fs: FakeFilesystem) -> None:
        """Glob patterns should exclude extension-less files that are binary."""
        base_path = Path("/test_data")
        # Create a binary file without extension (has null bytes)
        fs.create_file("/test_data/BINARY", contents=b"\x00\x01\x02\x03binary")
        # Also create a text file to verify the glob works
        fs.create_file("/test_data/LICENSE", contents="MIT License")

        # Use glob pattern that matches both files
        result = expand_input_paths(["*"], base_path)

        # Should exclude BINARY since is_text_file would return False
        # Should include LICENSE since is_text_file would return True
        result_names = {p.name for p in result}
        assert "BINARY" not in result_names
        assert "LICENSE" in result_names

    def test_glob_pattern_star_filters_consistently(self, fs: FakeFilesystem) -> None:
        """Wildcard glob *.* should filter consistently with directory scan."""
        base_path = Path("/test_data")
        fs.create_file("/test_data/readme.md", contents="# Readme")
        fs.create_file("/test_data/script.py", contents="print('hello')")
        fs.create_file("/test_data/data.json", contents='{"key": "value"}')
        fs.create_file("/test_data/image.png", contents=b"\x89PNG\r\n\x1a\n")
        fs.create_file("/test_data/program.exe", contents=b"MZ binary")

        result = expand_input_paths(["*.*"], base_path)

        result_names = {p.name for p in result}
        # Allowed extensions should be included
        assert "readme.md" in result_names
        assert "script.py" in result_names
        assert "data.json" in result_names
        # Non-allowed extensions should be excluded
        assert "image.png" not in result_names
        assert "program.exe" not in result_names

    def test_glob_and_directory_scan_produce_same_results(self, fs: FakeFilesystem) -> None:
        """Glob pattern and directory scan should produce equivalent results."""
        base_path = Path("/")
        fs.create_file("/test_data/file.txt", contents="text")
        fs.create_file("/test_data/file.py", contents="python")
        fs.create_file("/test_data/file.exe", contents="binary")
        fs.create_file("/test_data/MAKEFILE", contents="make content")

        # Get results via directory scan
        dir_result = expand_input_paths(["test_data"], base_path)

        # Get results via glob pattern
        glob_result = expand_input_paths(["test_data/*"], base_path)

        # Both should produce the same set of files
        dir_names = {p.name for p in dir_result}
        glob_names = {p.name for p in glob_result}
        assert dir_names == glob_names

    def test_direct_file_filters_allowed_extensions(self, fs: FakeFilesystem) -> None:
        """Direct file paths should filter by allowed extensions like glob/directory."""
        base_path = Path("/test_data")
        fs.create_file("/test_data/file.txt", contents="text content")
        fs.create_file("/test_data/file.py", contents="python content")
        fs.create_file("/test_data/file.pdf", contents="pdf content")
        fs.create_file("/test_data/file.exe", contents="binary content")
        fs.create_file("/test_data/file.bin", contents="binary content")

        # Direct file paths (not glob patterns)
        result = expand_input_paths(
            ["file.txt", "file.py", "file.pdf", "file.exe", "file.bin"], base_path
        )

        # Should include .txt, .py, .pdf (allowed extensions)
        # Should exclude .exe, .bin (not in allowed extensions)
        result_names = {p.name for p in result}
        assert "file.txt" in result_names
        assert "file.py" in result_names
        assert "file.pdf" in result_names
        assert "file.exe" not in result_names
        assert "file.bin" not in result_names

    def test_direct_file_includes_no_extension_text_file(self, fs: FakeFilesystem) -> None:
        """Direct file paths should include extension-less files that are text."""
        base_path = Path("/test_data")
        fs.create_file("/test_data/LICENSE", contents="MIT License text content")

        result = expand_input_paths(["LICENSE"], base_path)

        result_names = {p.name for p in result}
        assert "LICENSE" in result_names

    def test_direct_file_excludes_no_extension_binary_file(self, fs: FakeFilesystem) -> None:
        """Direct file paths should exclude extension-less files that are binary."""
        base_path = Path("/test_data")
        fs.create_file("/test_data/BINARY", contents=b"\x00\x01\x02\x03binary")

        result = expand_input_paths(["BINARY"], base_path)

        # Should exclude BINARY since is_text_file would return False
        result_names = {p.name for p in result}
        assert "BINARY" not in result_names

    def test_direct_file_excludes_unsupported_extension(self, fs: FakeFilesystem) -> None:
        """Direct file paths should exclude files with unsupported extensions."""
        base_path = Path("/test_data")
        fs.create_file("/test_data/image.png", contents=b"\x89PNG\r\n\x1a\n")
        fs.create_file("/test_data/program.exe", contents=b"MZ binary")
        fs.create_file("/test_data/archive.zip", contents=b"PK\x03\x04")

        result = expand_input_paths(["image.png", "program.exe", "archive.zip"], base_path)

        # Should exclude all unsupported extensions
        assert len(result) == 0

    def test_direct_glob_directory_produce_same_results(self, fs: FakeFilesystem) -> None:
        """Direct file, glob pattern, and directory scan should all filter consistently."""
        base_path = Path("/")
        fs.create_file("/test_data/file.txt", contents="text")
        fs.create_file("/test_data/file.exe", contents="binary")

        # Get results via direct file paths
        direct_result = expand_input_paths(["test_data/file.txt", "test_data/file.exe"], base_path)

        # Get results via directory scan
        dir_result = expand_input_paths(["test_data"], base_path)

        # Get results via glob pattern
        glob_result = expand_input_paths(["test_data/*"], base_path)

        # All should produce the same set of files (only .txt, not .exe)
        direct_names = {p.name for p in direct_result}
        dir_names = {p.name for p in dir_result}
        glob_names = {p.name for p in glob_result}
        assert direct_names == dir_names == glob_names
        assert "file.txt" in direct_names
        assert "file.exe" not in direct_names


class TestSentenceBoundariesFallback:
    """Tests for the regex-based sentence boundary fallback function."""

    def test_fallback_handles_empty_text(self) -> None:
        """Fallback function handles empty text correctly."""
        result = _get_sentence_boundaries_fallback("")
        assert result == []

    def test_fallback_finds_basic_sentences(self) -> None:
        """Fallback function finds sentence boundaries with basic punctuation."""
        text = "First sentence. Second sentence. Third sentence."
        result = _get_sentence_boundaries_fallback(text)

        # Should find at least some boundaries
        assert len(result) > 0
        # Should not exceed text length
        assert all(b <= len(text) for b in result)
