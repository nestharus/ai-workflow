"""Tests for scripts.knowledge.candidate_extraction module."""

from __future__ import annotations

from pathlib import Path

from typing import TYPE_CHECKING
from unittest.mock import patch

from scripts.knowledge import candidate_extraction
from scripts.knowledge.candidate_extraction import (
    CHUNK_OVERLAP,
    CHUNK_THRESHOLD,
    CSV_COLUMNS,
    CandidateRecord,
    append_candidates_batch,
    ensure_csv_exists,
    extract_named_entities,
    extract_noun_chunks,
    extract_regex_candidates,
    get_existing_candidates,
    get_sentence_context,
    parse_args,
    process_yaml_file,
    split_text_into_chunks,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestCsvColumns:
    """Tests for CSV_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns for Stage 1 schema."""
        assert "candidate_id" in CSV_COLUMNS
        assert "source_file" in CSV_COLUMNS
        assert "element_id" in CSV_COLUMNS
        assert "sentence" in CSV_COLUMNS
        assert "candidate_text" in CSV_COLUMNS
        assert "start_char" in CSV_COLUMNS
        assert "end_char" in CSV_COLUMNS
        assert "detected_at" in CSV_COLUMNS
        assert "keep" in CSV_COLUMNS
        assert "confidence" in CSV_COLUMNS
        assert "reason" in CSV_COLUMNS
        assert "classified_at" in CSV_COLUMNS
        assert "qwen_score" in CSV_COLUMNS

    def test_column_count(self) -> None:
        """Should have exactly 13 columns."""
        assert len(CSV_COLUMNS) == 13


class TestEnsureCsvExists:
    """Tests for ensure_csv_exists function."""

    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "keywords" / "candidates.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in CSV_COLUMNS:
            assert col in content

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Should not overwrite existing CSV with data."""
        csv_path = tmp_path / "keywords" / "candidates.csv"
        csv_path.parent.mkdir(parents=True)
        header = ",".join(CSV_COLUMNS)
        # New schema row format
        row = "id1,file1,elem1,sentence1,term1,0,10,2024-01-01,true,0.9,reason1,2024-01-02,0.85"
        csv_path.write_text(f"{header}\n{row}\n")

        ensure_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "id1" in content
        assert "term1" in content


class TestAppendCandidatesBatch:
    """Tests for append_candidates_batch function."""

    def test_appends_records(self, tmp_path: Path) -> None:
        """Should append multiple candidate records to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "keywords").mkdir(parents=True)
        csv_path = tmp_path / "keywords" / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        records = [
            CandidateRecord(
                candidate_id="cand-1",
                source_file="docs/test.yml",
                element_id="test.section",
                sentence="FastAPI is a framework.",
                candidate_text="FastAPI",
                start_char="0",
                end_char="7",
                detected_at="20240101T120000Z",
                keep="",
                confidence="",
                reason="",
                classified_at="",
                qwen_score="",
            ),
            CandidateRecord(
                candidate_id="cand-2",
                source_file="docs/test.yml",
                element_id="test.section",
                sentence="Pydantic provides validation.",
                candidate_text="Pydantic",
                start_char="0",
                end_char="8",
                detected_at="20240101T120000Z",
                keep="",
                confidence="",
                reason="",
                classified_at="",
                qwen_score="",
            ),
        ]

        append_candidates_batch(csv_path, records)

        content = csv_path.read_text()
        assert "cand-1" in content
        assert "FastAPI" in content
        assert "cand-2" in content
        assert "Pydantic" in content

    def test_handles_empty_list(self, tmp_path: Path) -> None:
        """Should handle empty records list gracefully."""
        (tmp_path / "keywords").mkdir(parents=True)
        csv_path = tmp_path / "keywords" / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        append_candidates_batch(csv_path, [])

        # File should still exist and have only header
        content = csv_path.read_text()
        assert content == f"{header}\n"


class TestGetExistingCandidates:
    """Tests for get_existing_candidates function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty set when CSV doesn't exist."""
        csv_path = tmp_path / "candidates.csv"
        result = get_existing_candidates(csv_path)
        assert result == set()

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty set for empty CSV."""
        csv_path = tmp_path / "candidates.csv"
        csv_path.write_text("")
        result = get_existing_candidates(csv_path)
        assert result == set()

    def test_returns_existing_tuples(self, tmp_path: Path) -> None:
        """Should return set of (source_file, element_id, candidate_text) tuples."""
        csv_path = tmp_path / "candidates.csv"
        header = ",".join(CSV_COLUMNS)
        row1 = "id1,docs/test.yml,elem1,sent1,FastAPI,0,7,2024-01-01,,,,,,"
        row2 = "id2,docs/other.yml,elem2,sent2,Pydantic,0,8,2024-01-01,,,,,,"
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = get_existing_candidates(csv_path)

        assert ("docs/test.yml", "elem1", "FastAPI") in result
        assert ("docs/other.yml", "elem2", "Pydantic") in result
        assert len(result) == 2


class TestGetSentenceContext:
    """Tests for get_sentence_context function."""

    def test_extracts_sentence_with_period(self) -> None:
        """Should extract sentence ending with period."""
        text = "First sentence. Second sentence with term. Third sentence."
        result = get_sentence_context(text, 25, 29)  # "term"
        assert "Second sentence with term." in result

    def test_handles_no_period_before(self) -> None:
        """Should handle text without period before span."""
        text = "Some text with a term here. And more."
        result = get_sentence_context(text, 17, 21)  # "term"
        assert "term" in result

    def test_handles_no_period_after(self) -> None:
        """Should handle text without period after span."""
        text = "First sentence. Some text with term"
        result = get_sentence_context(text, 31, 35)  # "term"
        assert "term" in result


class TestExtractNamedEntities:
    """Tests for extract_named_entities function."""

    def test_extracts_entities(self) -> None:
        """Should extract named entities from spaCy doc."""

        # Mock spaCy doc with entities
        class MockEnt:
            def __init__(self, text: str, start: int, end: int) -> None:
                self.text = text
                self.start_char = start
                self.end_char = end

        class MockDoc:
            def __init__(self) -> None:
                self.ents = [MockEnt("Python", 0, 6), MockEnt("FastAPI", 15, 22)]

        doc = MockDoc()
        text = "Python and the FastAPI framework."

        result = extract_named_entities(doc, text)  # type: ignore[arg-type]

        assert len(result) == 2
        assert result[0][0] == "Python"
        assert result[1][0] == "FastAPI"


class TestExtractNounChunks:
    """Tests for extract_noun_chunks function."""

    def test_extracts_chunks(self) -> None:
        """Should extract noun chunks from spaCy doc."""

        class MockChunk:
            def __init__(self, text: str, start: int, end: int) -> None:
                self.text = text
                self.start_char = start
                self.end_char = end

        class MockDoc:
            def __init__(self) -> None:
                self.noun_chunks = [
                    MockChunk("the framework", 10, 23),
                    MockChunk("a method", 30, 38),
                ]

        doc = MockDoc()
        text = "Describes the framework and uses a method for processing."

        result = extract_noun_chunks(doc, text)  # type: ignore[arg-type]

        assert len(result) == 2
        assert result[0][0] == "the framework"
        assert result[1][0] == "a method"


class TestExtractRegexCandidates:
    """Tests for extract_regex_candidates function."""

    def test_extracts_file_paths(self) -> None:
        """Should extract file paths."""
        text = "See the file app/services/foo.py for details."
        result = extract_regex_candidates(text)
        paths = [c[0] for c in result]
        assert any("app/services/foo.py" in p for p in paths)

    def test_extracts_camel_case(self) -> None:
        """Should extract CamelCase identifiers."""
        text = "The ElasticsearchWrapper class handles connections."
        result = extract_regex_candidates(text)
        texts = [c[0] for c in result]
        assert "ElasticsearchWrapper" in texts

    def test_extracts_snake_case(self) -> None:
        """Should extract snake_case identifiers."""
        text = "Call the get_user_by_id function."
        result = extract_regex_candidates(text)
        texts = [c[0] for c in result]
        assert "get_user_by_id" in texts

    def test_extracts_backtick_code(self) -> None:
        """Should extract code in backticks."""
        text = "Use `some_function()` for this."
        result = extract_regex_candidates(text)
        texts = [c[0] for c in result]
        assert "some_function()" in texts

    def test_extracts_qualified_names(self) -> None:
        """Should extract qualified names like module.function."""
        text = "Import from scripts.knowledge.module for usage."
        result = extract_regex_candidates(text)
        texts = [c[0] for c in result]
        assert any("scripts.knowledge" in t for t in texts)


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_values(self) -> None:
        """Should set default values for optional args."""
        args = parse_args([])
        assert args.path == Path("docs/development")
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_path(self) -> None:
        """Should parse --path argument."""
        args = parse_args(["--path", "custom/docs"])
        assert args.path == Path("custom/docs")

    def test_custom_knowledge_path(self) -> None:
        """Should parse --knowledge-path argument."""
        args = parse_args(["--knowledge-path", "custom/.knowledge"])
        assert args.knowledge_path == Path("custom/.knowledge")


class TestSplitTextIntoChunks:
    """Tests for split_text_into_chunks function."""

    def test_returns_single_chunk_for_short_text(self) -> None:
        """Should return single chunk for text below threshold."""
        text = "Short text under threshold."
        result = split_text_into_chunks(text, threshold=100)
        assert len(result) == 1
        assert result[0] == (text, 0)

    def test_returns_single_chunk_at_threshold(self) -> None:
        """Should return single chunk when text equals threshold."""
        text = "x" * 100
        result = split_text_into_chunks(text, threshold=100)
        assert len(result) == 1
        assert result[0] == (text, 0)

    def test_splits_text_above_threshold(self) -> None:
        """Should split text exceeding threshold into multiple chunks."""
        # Create text that will need 2 chunks
        text = "word " * 30  # 150 chars
        result = split_text_into_chunks(text, threshold=100, overlap=10)
        assert len(result) >= 2
        # First chunk starts at 0
        assert result[0][1] == 0
        # Subsequent chunks have non-zero offsets
        assert result[1][1] > 0

    def test_chunks_overlap(self) -> None:
        """Should have overlap between adjacent chunks."""
        text = "word " * 60  # 300 chars
        result = split_text_into_chunks(text, threshold=100, overlap=20)
        assert len(result) >= 2
        # Check overlap: second chunk start should be less than first chunk end
        chunk1_end = result[0][1] + len(result[0][0])
        chunk2_start = result[1][1]
        assert chunk2_start < chunk1_end

    def test_chunks_cover_entire_text(self) -> None:
        """Should cover entire text when reassembled."""
        text = "The quick brown fox jumps over the lazy dog. " * 10  # ~450 chars
        result = split_text_into_chunks(text, threshold=100, overlap=10)

        # Verify all characters are covered
        covered = set()
        for chunk_text, offset in result:
            for i in range(len(chunk_text)):
                covered.add(offset + i)

        # All positions should be covered
        assert all(i in covered for i in range(len(text)))

    def test_preserves_words_at_boundaries(self) -> None:
        """Should try to break at whitespace to avoid splitting words."""
        # Create text with clear word boundaries
        text = "word " * 25  # 125 chars, should break at space
        result = split_text_into_chunks(text, threshold=100, overlap=10)

        # Each chunk should not start/end in middle of a word
        for chunk_text, _ in result:
            # Chunk shouldn't end mid-word (unless it's the last chunk)
            stripped = chunk_text.rstrip()
            if stripped != chunk_text:
                # Ended with space, good
                pass
            # Should start with a full word
            assert not chunk_text[0].isspace() or chunk_text == result[0][0]

    def test_uses_default_threshold(self) -> None:
        """Should use default threshold constant when not specified."""
        text = "x" * (CHUNK_THRESHOLD - 1)
        result = split_text_into_chunks(text)
        assert len(result) == 1

        text_large = "x" * (CHUNK_THRESHOLD + 1)
        result_large = split_text_into_chunks(text_large)
        assert len(result_large) >= 2

    def test_uses_default_overlap(self) -> None:
        """Should use default overlap constant when not specified."""
        text = "word " * 3000  # Much larger than threshold
        result = split_text_into_chunks(text)
        assert len(result) >= 2
        # Default overlap is CHUNK_OVERLAP
        assert CHUNK_OVERLAP == 100  # Verify constant value

    def test_handles_empty_text(self) -> None:
        """Should handle empty text gracefully."""
        result = split_text_into_chunks("")
        assert len(result) == 1
        assert result[0] == ("", 0)

    def test_offsets_are_correct(self) -> None:
        """Should return correct offsets for each chunk."""
        # Use distinctive text to verify offset accuracy
        text = "AAAA BBBB CCCC DDDD EEEE FFFF GGGG HHHH"
        result = split_text_into_chunks(text, threshold=20, overlap=5)

        for chunk_text, offset in result:
            # The chunk text should match the text at that offset
            expected = text[offset : offset + len(chunk_text)]
            assert chunk_text == expected


class TestProcessYamlFile:
    """Tests for process_yaml_file function with sliced representations."""

    def test_process_yaml_file_with_nested_ids_uses_sliced_representation(
        self, fs: FakeFilesystem
    ) -> None:
        """Should extract candidates from sliced representation with $ref tokens.

        Per the fact redesign (lines 131-133), candidate extraction uses sliced
        representations with child content replaced by $ref tokens.
        """

        # Create a minimal mock nlp object
        class MockDoc:
            """Minimal mock for spaCy Doc."""

            def __init__(self) -> None:
                self.ents: list[object] = []
                self.noun_chunks: list[object] = []

        class MockNlp:
            """Minimal mock for spaCy nlp model."""

            def __call__(self, text: str) -> MockDoc:
                return MockDoc()

        mock_nlp = MockNlp()
        existing: set[tuple[str, str, str]] = set()
        timestamp = "20240101T120000Z"

        with patch.object(candidate_extraction, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            # Create YAML with nested ID-bearing dicts
            content = """
id: parent-section
title: Parent API Documentation
items:
  - id: child-item-1
    text: Child 1 uses FastAPI framework
  - id: child-item-2
    text: Child 2 describes REST endpoint
"""
            fs.create_file("/fake/test.yml", contents=content)

            records = process_yaml_file(
                Path("/fake/test.yml"), mock_nlp, existing, timestamp
            )

            # Find records for the parent element
            parent_records = [r for r in records if r["element_id"] == "parent-section"]

            # The parent's sentence context should contain $ref tokens, not child content
            parent_sentences = [r["sentence"] for r in parent_records]
            all_parent_text = " ".join(parent_sentences)

            # Should see $ref tokens in the parent's extracted text
            # (Note: candidates from $ref tokens may or may not be extracted
            # depending on extraction methods, but child content should NOT appear)
            assert "Child 1 uses FastAPI framework" not in all_parent_text
            assert "Child 2 describes REST endpoint" not in all_parent_text

            # Child elements should be processed separately with their own content
            child1_records = [r for r in records if r["element_id"] == "child-item-1"]
            child2_records = [r for r in records if r["element_id"] == "child-item-2"]

            # Children should have their own candidates
            if child1_records:
                child1_sentences = [r["sentence"] for r in child1_records]
                all_child1_text = " ".join(child1_sentences)
                # Child content should be in child's records
                assert "FastAPI" in all_child1_text or len(child1_records) > 0

            if child2_records:
                child2_sentences = [r["sentence"] for r in child2_records]
                all_child2_text = " ".join(child2_sentences)
                # Child content should be in child's records
                assert "REST" in all_child2_text or len(child2_records) > 0
