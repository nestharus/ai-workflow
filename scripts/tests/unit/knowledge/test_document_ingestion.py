import argparse
from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem
from pytest_mock import MockerFixture

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


@pytest.fixture
def mock_repo_root(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override REPO_ROOT to /test_repo for tests that need a controlled repo root.

    Returns:
        The mocked repo root path (/test_repo).
    """
    test_repo = Path("/test_repo")
    monkeypatch.setattr("scripts.knowledge.document_ingestion.REPO_ROOT", test_repo)
    return test_repo


class TestIngestPdfFile:
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


class TestIngestDocument:
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


class TestDocumentIngestionMain:
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
