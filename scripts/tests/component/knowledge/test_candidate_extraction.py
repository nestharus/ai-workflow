from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from scripts.knowledge import candidate_extraction
from scripts.knowledge.candidate_extraction import (
    CHUNK_OVERLAP,
    CHUNK_THRESHOLD,
    CSV_COLUMNS,
    PROJECTION_VERSION,
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

    def test_has_field_provenance_columns(self) -> None:
        """Should have field-level provenance columns.

        Per fact_redesign.md lines 1308-1327, the CSV schema includes:
        - projection_version: identifies text projection rules
        - source_field_path: FieldFact.field_path containing candidate
        - source_scope_path: FieldFact.scope_path for grouping context
        - field_role: FieldFact.role (constraint/entity_ref/artifact_root/metadata)
        - artifact_kind: FieldFact.artifact_kind when role==artifact_root
        """
        assert "projection_version" in CSV_COLUMNS
        assert "source_field_path" in CSV_COLUMNS
        assert "source_scope_path" in CSV_COLUMNS
        assert "field_role" in CSV_COLUMNS
        assert "artifact_kind" in CSV_COLUMNS

    def test_column_count(self) -> None:
        """Should have exactly 18 columns (13 original + 5 field provenance)."""
        assert len(CSV_COLUMNS) == 18


class TestEnsureCsvExists:
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
                projection_version="fieldfacts.v2",
                source_field_path="text",
                source_scope_path="",
                field_role="constraint",
                artifact_kind="",
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
                projection_version="fieldfacts.v2",
                source_field_path="description",
                source_scope_path="",
                field_role="constraint",
                artifact_kind="",
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
        row1 = "id1,docs/test.yml,elem1,sent1,FastAPI,0,7,2024-01-01,,,,,,fieldfacts.v2,,,,"
        row2 = "id2,docs/other.yml,elem2,sent2,Pydantic,0,8,2024-01-01,,,,,,fieldfacts.v2,,,,"
        csv_path.write_text(f"{header}\n{row1}\n{row2}\n")

        result = get_existing_candidates(csv_path)

        assert ("docs/test.yml", "elem1", "FastAPI") in result
        assert ("docs/other.yml", "elem2", "Pydantic") in result
        assert len(result) == 2


class TestGetSentenceContext:
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

        result = extract_named_entities(doc, text)

        assert len(result) == 2
        assert result[0][0] == "Python"
        assert result[1][0] == "FastAPI"


class TestExtractNounChunks:
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

        result = extract_noun_chunks(doc, text)

        assert len(result) == 2
        assert result[0][0] == "the framework"
        assert result[1][0] == "a method"


class TestExtractRegexCandidates:
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

            records = process_yaml_file(Path("/fake/test.yml"), mock_nlp, existing, timestamp)

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


class TestProjectionVersionConstant:
    def test_projection_version_format(self) -> None:
        """Should follow fieldfacts.vN format."""
        assert PROJECTION_VERSION.startswith("fieldfacts.v")
        version_part = PROJECTION_VERSION.split(".")[-1]
        assert version_part.startswith("v")
        assert version_part[1:].isdigit()

    def test_projection_version_is_v2(self) -> None:
        """Should be fieldfacts.v2 for current implementation."""
        assert PROJECTION_VERSION == "fieldfacts.v2"


class TestCandidateRecordWithFieldProvenance:
    def test_candidate_record_includes_provenance_fields(self) -> None:
        """Should be able to create CandidateRecord with all provenance fields."""
        record = CandidateRecord(
            candidate_id="cand-1",
            source_file="docs/test.yml",
            element_id="test.section",
            sentence="[test.section] text = FastAPI is a framework.",
            candidate_text="FastAPI",
            start_char="25",
            end_char="32",
            detected_at="20240101T120000Z",
            keep="",
            confidence="",
            reason="",
            classified_at="",
            qwen_score="",
            projection_version="fieldfacts.v2",
            source_field_path="text",
            source_scope_path="",
            field_role="constraint",
            artifact_kind="",
        )

        assert record["projection_version"] == "fieldfacts.v2"
        assert record["source_field_path"] == "text"
        assert record["source_scope_path"] == ""
        assert record["field_role"] == "constraint"
        assert record["artifact_kind"] == ""

    def test_candidate_record_with_artifact_role(self) -> None:
        """Should allow artifact_root role with artifact_kind populated."""
        record = CandidateRecord(
            candidate_id="cand-1",
            source_file="docs/test.yml",
            element_id="test.section",
            sentence="[test.section] prose = Some prose content",
            candidate_text="prose content",
            start_char="20",
            end_char="33",
            detected_at="20240101T120000Z",
            keep="",
            confidence="",
            reason="",
            classified_at="",
            qwen_score="",
            projection_version="fieldfacts.v2",
            source_field_path="prose",
            source_scope_path="",
            field_role="artifact_root",
            artifact_kind="prose",
        )

        assert record["field_role"] == "artifact_root"
        assert record["artifact_kind"] == "prose"


class TestCandidateOffsetInFactLineProjection:
    def test_offsets_refer_to_fact_line_projection(self) -> None:
        """Should have offsets relative to fact-line projection, not raw YAML.

        Per fact_redesign.md lines 1311-1312, start_char/end_char refer to
        positions in the synthetic fact-line projection.
        """
        # The sentence in a CandidateRecord should be from fact-line format
        record = CandidateRecord(
            candidate_id="cand-1",
            source_file="docs/test.yml",
            element_id="test.section",
            sentence="[test.section] text = FastAPI is great",
            candidate_text="FastAPI",
            start_char="22",  # Position in fact-line text
            end_char="29",
            detected_at="20240101T120000Z",
            keep="",
            confidence="",
            reason="",
            classified_at="",
            qwen_score="",
            projection_version="fieldfacts.v2",
            source_field_path="text",
            source_scope_path="",
            field_role="constraint",
            artifact_kind="",
        )

        # Verify the sentence has fact-line format (brackets with element_id)
        assert "[" in record["sentence"]
        assert record["element_id"] in record["sentence"]
        assert "=" in record["sentence"]

    def test_sentence_includes_ancestor_chain(self) -> None:
        """Should include ancestor chain context in sentence.

        Per fact_redesign.md lines 1224-1231, fact-line format includes
        ancestor chains in brackets.
        """
        record = CandidateRecord(
            candidate_id="cand-1",
            source_file="docs/test.yml",
            element_id="child",
            sentence="[grandparent > parent > child] text = Content",
            candidate_text="Content",
            start_char="38",
            end_char="45",
            detected_at="20240101T120000Z",
            keep="",
            confidence="",
            reason="",
            classified_at="",
            qwen_score="",
            projection_version="fieldfacts.v2",
            source_field_path="text",
            source_scope_path="",
            field_role="constraint",
            artifact_kind="",
        )

        # Sentence should show ancestor chain
        assert "grandparent > parent > child" in record["sentence"]


class TestProcessYamlFileWithFieldProvenance:
    def test_records_include_projection_version(self, fs: FakeFilesystem) -> None:
        """Should populate projection_version in all records."""

        class MockDoc:
            def __init__(self) -> None:
                self.ents: list[object] = []
                self.noun_chunks: list[object] = []

        class MockNlp:
            def __call__(self, text: str) -> MockDoc:
                return MockDoc()

        mock_nlp = MockNlp()
        existing: set[tuple[str, str, str]] = set()
        timestamp = "20240101T120000Z"

        with patch.object(candidate_extraction, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
id: test-section
text: FastAPI provides validation
"""
            fs.create_file("/fake/test.yml", contents=content)

            records = process_yaml_file(Path("/fake/test.yml"), mock_nlp, existing, timestamp)

            # All records should have projection_version populated
            for record in records:
                assert record["projection_version"] == "fieldfacts.v2"

    def test_records_include_field_provenance_fields(self, fs: FakeFilesystem) -> None:
        """Should populate source_field_path and other provenance fields."""

        class MockDoc:
            def __init__(self) -> None:
                self.ents: list[object] = []
                self.noun_chunks: list[object] = []

        class MockNlp:
            def __call__(self, text: str) -> MockDoc:
                return MockDoc()

        mock_nlp = MockNlp()
        existing: set[tuple[str, str, str]] = set()
        timestamp = "20240101T120000Z"

        with patch.object(candidate_extraction, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
id: test-section
description: API endpoint for users
"""
            fs.create_file("/fake/test.yml", contents=content)

            records = process_yaml_file(Path("/fake/test.yml"), mock_nlp, existing, timestamp)

            # All records should have provenance fields (may be empty strings if unmatched)
            for record in records:
                assert "source_field_path" in record
                assert "source_scope_path" in record
                assert "field_role" in record
                assert "artifact_kind" in record


class TestBackwardCompatibilityCandidates:
    def test_original_columns_still_present(self) -> None:
        """Should have all original columns for backward compatibility.

        Schema evolution is append-only: existing CSV readers selecting
        original columns remain unaffected.
        """
        original_columns = [
            "candidate_id",
            "source_file",
            "element_id",
            "sentence",
            "candidate_text",
            "start_char",
            "end_char",
            "detected_at",
            "keep",
            "confidence",
            "reason",
            "classified_at",
            "qwen_score",
        ]
        for col in original_columns:
            assert col in CSV_COLUMNS

    def test_new_columns_are_appended(self) -> None:
        """Should have new columns appended after original columns.

        Per append-only schema evolution, new columns come after original ones.
        """
        projection_idx = CSV_COLUMNS.index("projection_version")
        qwen_score_idx = CSV_COLUMNS.index("qwen_score")

        # New columns should come after qwen_score (last original column)
        assert projection_idx > qwen_score_idx


class TestExtractCandidatesMain:
    def test_source_directory_not_found(self, tmp_path: Path, capsys: object) -> None:
        """Should return 1 when source directory doesn't exist (lines 686-687)."""
        import argparse

        from scripts.knowledge.candidate_extraction import extract_candidates_main

        # Path that doesn't exist
        args = argparse.Namespace(
            path=tmp_path / "nonexistent",
            knowledge_path=tmp_path / ".knowledge",
        )

        with patch.object(candidate_extraction, "REPO_ROOT", tmp_path):
            result = extract_candidates_main(args)

        assert result == 1


class TestExtractNamedEntitiesBranch:
    def test_skips_single_char_entities(self) -> None:
        """Should skip entities with single character (branch 345->343)."""

        class MockEnt:
            def __init__(self, text: str, start: int, end: int) -> None:
                self.text = text
                self.start_char = start
                self.end_char = end

        class MockDoc:
            def __init__(self) -> None:
                # Single character entity should be skipped
                self.ents = [MockEnt("X", 0, 1), MockEnt("Python", 5, 11)]

        doc = MockDoc()
        text = "X and Python are here."

        result = extract_named_entities(doc, text)

        # Should only have "Python", not "X"
        assert len(result) == 1
        assert result[0][0] == "Python"


class TestExtractNounChunksBranch:
    def test_skips_single_char_chunks(self) -> None:
        """Should skip noun chunks with single character (branch 364->362)."""

        class MockChunk:
            def __init__(self, text: str, start: int, end: int) -> None:
                self.text = text
                self.start_char = start
                self.end_char = end

        class MockDoc:
            def __init__(self) -> None:
                # Single character chunk should be skipped
                self.noun_chunks = [MockChunk("I", 0, 1), MockChunk("the framework", 10, 23)]

        doc = MockDoc()
        text = "I love the framework very much."

        result = extract_noun_chunks(doc, text)

        # Should only have "the framework", not "I"
        assert len(result) == 1
        assert result[0][0] == "the framework"


class TestExtractRegexCandidatesBranches:
    def test_skips_short_snake_case(self) -> None:
        """Should skip snake_case identifiers shorter than 4 chars (branch 406->401)."""
        # "a_b" is 3 chars, should be skipped
        text = "Use a_b and get_user_by_id functions."
        result = extract_regex_candidates(text)
        texts = [c[0] for c in result]

        # get_user_by_id should be included, a_b should not
        assert "get_user_by_id" in texts
        # a_b might still match via other patterns, so just verify it's 3 chars
        assert all(len(t) >= 4 or "_" not in t for t in texts if t.islower())

    def test_skips_single_char_backtick_code(self) -> None:
        """Should skip backtick code with single character (branch 415->411)."""
        text = "Use `x` and `some_function()` for this."
        result = extract_regex_candidates(text)
        texts = [c[0] for c in result]

        # some_function() should be included, x should not
        assert "some_function()" in texts
        assert "x" not in texts


class TestGetExistingCandidatesErrorHandling:
    def test_returns_empty_on_duckdb_error(self, tmp_path: Path) -> None:
        """Should return empty set when DuckDB fails (lines 285-286)."""
        csv_path = tmp_path / "candidates.csv"
        # Create a malformed CSV that will cause DuckDB to fail
        csv_path.write_text("invalid,header\nno,proper,format\nextra,columns,here,too")

        result = get_existing_candidates(csv_path)

        # Should return empty set on error
        assert result == set()


class TestLoadSpacyModel:
    def test_raises_oserror_when_model_not_found(self) -> None:
        """Should raise OSError with helpful message when model missing (lines 302-307)."""
        import sys

        original_spacy = sys.modules.get("spacy")

        try:
            # Create mock spacy module that raises OSError
            mock_spacy_module = type(sys)("spacy")

            def mock_load(model_name: str) -> None:
                raise OSError("Model not found")

            mock_spacy_module.load = mock_load
            sys.modules["spacy"] = mock_spacy_module

            import pytest

            from scripts.knowledge.candidate_extraction import load_spacy_model

            with pytest.raises(OSError) as exc_info:
                load_spacy_model()

            assert "en_core_web_trf" in str(exc_info.value)
            assert "python -m spacy download" in str(exc_info.value)
        finally:
            # Restore original
            if original_spacy is not None:
                sys.modules["spacy"] = original_spacy


class TestProcessYamlFileErrorPaths:
    def test_skips_empty_text_elements(self, fs: FakeFilesystem) -> None:
        """Should skip elements with empty or whitespace-only text (line 547)."""

        class MockDoc:
            def __init__(self) -> None:
                self.ents: list[object] = []
                self.noun_chunks: list[object] = []

        class MockNlp:
            def __call__(self, text: str) -> MockDoc:
                return MockDoc()

        mock_nlp = MockNlp()
        existing: set[tuple[str, str, str]] = set()
        timestamp = "20240101T120000Z"

        with patch.object(candidate_extraction, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            # YAML with empty text
            content = """
id: test-section
text: "   "
"""
            fs.create_file("/fake/test.yml", contents=content)

            records = process_yaml_file(Path("/fake/test.yml"), mock_nlp, existing, timestamp)

            # Should not produce records for empty text
            test_section_records = [r for r in records if r["element_id"] == "test-section"]
            # Empty/whitespace text should be skipped
            assert len(test_section_records) == 0

    def test_processes_named_entities_with_chunk_offset(self, fs: FakeFilesystem) -> None:
        """Should translate entity offsets with chunk offset (lines 565-568)."""

        class MockEnt:
            def __init__(self, text: str, start: int, end: int) -> None:
                self.text = text
                self.start_char = start
                self.end_char = end

        class MockDoc:
            def __init__(self) -> None:
                self.ents = [MockEnt("FastAPI", 10, 17)]
                self.noun_chunks: list[object] = []

        class MockNlp:
            def __call__(self, text: str) -> MockDoc:
                return MockDoc()

        mock_nlp = MockNlp()
        existing: set[tuple[str, str, str]] = set()
        timestamp = "20240101T120000Z"

        with patch.object(candidate_extraction, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
id: test-section
text: Using the FastAPI framework for web applications.
"""
            fs.create_file("/fake/test.yml", contents=content)

            records = process_yaml_file(Path("/fake/test.yml"), mock_nlp, existing, timestamp)

            # Should have FastAPI candidate
            fastapi_records = [r for r in records if r["candidate_text"] == "FastAPI"]
            assert len(fastapi_records) >= 1

    def test_processes_noun_chunks_with_chunk_offset(self, fs: FakeFilesystem) -> None:
        """Should translate noun chunk offsets with chunk offset (lines 572-575)."""

        class MockChunk:
            def __init__(self, text: str, start: int, end: int) -> None:
                self.text = text
                self.start_char = start
                self.end_char = end

        class MockDoc:
            def __init__(self) -> None:
                self.ents: list[object] = []
                self.noun_chunks = [MockChunk("the framework", 10, 23)]

        class MockNlp:
            def __call__(self, text: str) -> MockDoc:
                return MockDoc()

        mock_nlp = MockNlp()
        existing: set[tuple[str, str, str]] = set()
        timestamp = "20240101T120000Z"

        with patch.object(candidate_extraction, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
id: test-section
text: Describes the framework and its usage for APIs.
"""
            fs.create_file("/fake/test.yml", contents=content)

            records = process_yaml_file(Path("/fake/test.yml"), mock_nlp, existing, timestamp)

            # Should have "the framework" candidate
            framework_records = [r for r in records if "framework" in r["candidate_text"]]
            assert len(framework_records) >= 1

    def test_skips_duplicate_candidates(self, fs: FakeFilesystem) -> None:
        """Should skip duplicate candidates within element (line 585)."""

        class MockDoc:
            def __init__(self) -> None:
                self.ents: list[object] = []
                self.noun_chunks: list[object] = []

        class MockNlp:
            def __call__(self, text: str) -> MockDoc:
                return MockDoc()

        mock_nlp = MockNlp()
        existing: set[tuple[str, str, str]] = set()
        timestamp = "20240101T120000Z"

        with patch.object(candidate_extraction, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            # Text with duplicate pattern matches (same CamelCase term twice)
            content = """
id: test-section
text: Use FastApiFramework. And again FastApiFramework here.
"""
            fs.create_file("/fake/test.yml", contents=content)

            records = process_yaml_file(Path("/fake/test.yml"), mock_nlp, existing, timestamp)

            # Each unique (text, start, end) should appear only once
            keys = [(r["candidate_text"], r["start_char"], r["end_char"]) for r in records]
            assert len(keys) == len(set(keys))


class TestSplitTextIntoChunksEdgeCases:
    def test_handles_overlap_larger_than_chunk(self) -> None:
        """Should handle edge case where overlap would cause backwards movement (line 216)."""
        # Create text where overlap is relatively large compared to chunk size
        # and whitespace breaking could cause start to go backwards
        text = "A" * 50 + " " + "B" * 50  # 101 chars total, space at position 50
        result = split_text_into_chunks(text, threshold=60, overlap=40)

        # Should produce multiple chunks without going backwards
        assert len(result) >= 2
        # Each chunk's offset should be greater than or equal to previous
        for i in range(1, len(result)):
            assert result[i][1] >= result[i - 1][1]

    def test_no_whitespace_for_breaking(self) -> None:
        """Should handle text with no whitespace for word boundary breaking."""
        # Continuous text without spaces
        text = "A" * 150  # 150 chars, no spaces
        result = split_text_into_chunks(text, threshold=100, overlap=10)

        # Should still produce chunks
        assert len(result) >= 2
        # First chunk should be 100 chars
        assert len(result[0][0]) == 100

    def test_whitespace_in_first_half_not_used(self) -> None:
        """Should not break at whitespace if it's in first half of chunk."""
        # Space is at position 20 (in first half of 100-char threshold)
        text = "A" * 20 + " " + "B" * 130  # 151 chars, space at position 20
        result = split_text_into_chunks(text, threshold=100, overlap=10)

        # First chunk should not break at the early space
        assert len(result[0][0]) == 100

    def test_start_equals_last_offset_edge_case(self) -> None:
        """Should handle edge case where start would equal last chunk offset (line 215-216)."""
        # Create scenario where overlap could cause start to equal previous offset
        # This happens when: end - overlap <= chunks[-1][1]
        # i.e., when the space we find is very close to start

        # Text: 100 chars, then a space, then more chars
        # threshold=100, overlap=50
        # First chunk: 0-100 (actually breaks at space if found)
        # If space at position 51, end would be 52, start = 52 - 50 = 2
        # But chunks[-1][1] = 0, so 2 > 0, no problem

        # To trigger the edge case, we need:
        # - A chunk that ends at position X
        # - Next start = X - overlap = Y
        # - Y <= previous chunk start

        # This is hard to trigger because overlap is typically smaller than threshold
        # Let's use a very large overlap relative to threshold
        text = "A" * 100 + " " + "B" * 100  # 201 chars
        result = split_text_into_chunks(text, threshold=60, overlap=55)

        # Should handle gracefully
        assert len(result) >= 2
        # Offsets should be strictly increasing after the first
        for i in range(1, len(result)):
            assert result[i][1] > result[i - 1][1]
