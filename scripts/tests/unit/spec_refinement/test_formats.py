"""Unit tests for spec_manager.refinement.formats parsing utilities.

All functions under test are pure parsing/formatting logic -- no LLM calls, no
filesystem access, no network I/O.  Each test constructs its own input string
and asserts the expected structured output.
"""

from __future__ import annotations

import json
import textwrap

import pytest
from spec_manager.refinement.formats import (
    EVIDENCE_POINTER_RE,
    ArchitectureCandidate,
    FileSummary,
    LibraryCharter,
    _extract_file_id,
    _extract_json_payload,
    _extract_pointers,
    _extract_sections,
    _parse_named_items,
    _split_name_intent,
    _strip_evidence,
    parse_architecture_mapping,
    parse_architecture_proposal,
    parse_architecture_selection,
    parse_evidence_mapper_output,
    parse_evidence_spotcheck_output,
    parse_file_summary,
    parse_gap_judge_output,
    parse_library_synthesis,
)

# ---------------------------------------------------------------------------
# 1. EVIDENCE_POINTER_RE
# ---------------------------------------------------------------------------


class TestEvidencePointerRegex:
    """Tests for the compiled regex that matches [FILE_ID::SECTION] pointers."""

    def test_matches_simple_pointer(self) -> None:
        """A standard evidence pointer should produce two capture groups."""
        match = EVIDENCE_POINTER_RE.search("[F0001::INTRO]")
        assert match is not None
        assert match.group(1) == "F0001"
        assert match.group(2) == "INTRO"

    def test_matches_pointer_with_hyphens(self) -> None:
        """File IDs and section names containing hyphens should still match."""
        match = EVIDENCE_POINTER_RE.search("[my-file::section-one]")
        assert match is not None
        assert match.group(1) == "my-file"
        assert match.group(2) == "section-one"

    def test_matches_pointer_with_dots(self) -> None:
        """Dots inside the brackets should be accepted by the non-greedy group."""
        match = EVIDENCE_POINTER_RE.search("[file.v2::sec.1]")
        assert match is not None
        assert match.group(1) == "file.v2"
        assert match.group(2) == "sec.1"

    def test_finds_multiple_pointers(self) -> None:
        """Multiple pointers in the same string should all be found."""
        text = "[a::X] some text [b::Y] more [c::Z]"
        matches = EVIDENCE_POINTER_RE.findall(text)
        assert matches == [("a", "X"), ("b", "Y"), ("c", "Z")]

    def test_no_match_on_single_colon(self) -> None:
        """A single colon should not produce a match -- the separator is '::'."""
        assert EVIDENCE_POINTER_RE.search("[file:section]") is None

    def test_no_match_on_empty_brackets(self) -> None:
        """Empty brackets should not match."""
        assert EVIDENCE_POINTER_RE.search("[::section]") is None
        assert EVIDENCE_POINTER_RE.search("[file::]") is None

    def test_nested_brackets_still_match_inner(self) -> None:
        """Double brackets like '[[file::section]]' still match the inner pointer.

        The character class forbids '[' and ']' inside the capture groups, so
        the regex skips the leading '[' and matches '[file::section]' starting
        at position 1.
        """
        match = EVIDENCE_POINTER_RE.search("[[file::section]]")
        assert match is not None
        assert match.group(0) == "[file::section]"
        assert match.group(1) == "file"
        assert match.group(2) == "section"

    def test_no_match_plain_text(self) -> None:
        """Ordinary text without bracket/colon patterns should produce no matches."""
        assert EVIDENCE_POINTER_RE.search("just some text") is None

    def test_match_with_spaces_in_section(self) -> None:
        """Spaces inside file ID or section name should still match."""
        match = EVIDENCE_POINTER_RE.search("[file 001::Section Name]")
        assert match is not None
        assert match.group(1) == "file 001"
        assert match.group(2) == "Section Name"


# ---------------------------------------------------------------------------
# 2. _extract_json_payload
# ---------------------------------------------------------------------------


class TestExtractJsonPayload:
    """Tests for the internal helper that strips metadata from agent outputs."""

    def test_plain_json_object(self) -> None:
        """A bare JSON object string should pass through unchanged."""
        raw = '{"key": "value"}'
        assert _extract_json_payload(raw) == raw

    def test_plain_json_array(self) -> None:
        """A bare JSON array string should pass through unchanged."""
        raw = '[{"a": 1}]'
        assert _extract_json_payload(raw) == raw

    def test_strips_agent_exec_lines(self) -> None:
        """Lines starting with '[agent-exec]' should be removed."""
        raw = '[agent-exec] starting\n{"key": "value"}\n[agent-exec] done'
        result = _extract_json_payload(raw)
        assert json.loads(result) == {"key": "value"}

    def test_strips_fenced_code_block(self) -> None:
        """JSON inside a markdown fenced code block should be extracted."""
        raw = '```json\n{"a": 1}\n```'
        result = _extract_json_payload(raw)
        assert json.loads(result) == {"a": 1}

    def test_strips_fenced_code_block_no_lang(self) -> None:
        """Fenced block without a language tag should also be handled."""
        raw = '```\n{"b": 2}\n```'
        result = _extract_json_payload(raw)
        assert json.loads(result) == {"b": 2}

    def test_json_embedded_in_prose(self) -> None:
        """JSON preceded by non-JSON prose should still be extracted."""
        raw = 'Here is the result:\n{"file_id": "f1", "confidence": 0.9}'
        result = _extract_json_payload(raw)
        assert json.loads(result)["file_id"] == "f1"

    def test_array_embedded_in_prose(self) -> None:
        """An array preceded by prose should be extracted by finding '['."""
        raw = 'Output:\n[{"x": 1}]'
        result = _extract_json_payload(raw)
        assert json.loads(result) == [{"x": 1}]

    def test_empty_string_passthrough(self) -> None:
        """An empty string should be returned as-is."""
        assert _extract_json_payload("") == ""

    def test_whitespace_only_passthrough(self) -> None:
        """Whitespace-only input should be returned as empty."""
        assert _extract_json_payload("   \n  ") == ""

    def test_combined_agent_exec_and_fence(self) -> None:
        """Both agent-exec lines and fenced blocks together."""
        raw = '[agent-exec] started\n```json\n{"status": "ok"}\n```\n[agent-exec] finished'
        result = _extract_json_payload(raw)
        assert json.loads(result) == {"status": "ok"}

    def test_prefers_object_when_before_array(self) -> None:
        """When { appears before [, the object should be extracted."""
        raw = '{"a": [1,2,3]}'
        result = _extract_json_payload(raw)
        assert json.loads(result) == {"a": [1, 2, 3]}

    def test_prefers_array_when_before_object(self) -> None:
        """When [ appears before {, the array should be extracted."""
        raw = '[{"a": 1}]'
        result = _extract_json_payload(raw)
        assert json.loads(result) == [{"a": 1}]

    def test_no_json_delimiters(self) -> None:
        """Input with no { or [ should be returned as-is after stripping."""
        raw = "just text"
        assert _extract_json_payload(raw) == "just text"


# ---------------------------------------------------------------------------
# 3. _extract_sections
# ---------------------------------------------------------------------------


class TestExtractSections:
    """Tests for markdown heading-based section splitting."""

    def test_level_2_headers(self) -> None:
        """Level-2 headers should split content into named sections."""
        md = textwrap.dedent("""\
            ## Alpha
            alpha body
            ## Beta
            beta body
        """)
        sections = _extract_sections(md, level=2)
        assert "Alpha" in sections
        assert "Beta" in sections
        assert "alpha body" in sections["Alpha"]
        assert "beta body" in sections["Beta"]

    def test_level_3_headers(self) -> None:
        """Level-3 headers should be extracted with level=3."""
        md = "### Foo\nfoo text\n### Bar\nbar text\n"
        sections = _extract_sections(md, level=3)
        assert "Foo" in sections
        assert "Bar" in sections

    def test_empty_content(self) -> None:
        """Empty content should produce an empty dict."""
        assert _extract_sections("", level=2) == {}

    def test_no_matching_headers(self) -> None:
        """Content without any headers at the requested level returns empty."""
        md = "# Top Level\nSome text\n"
        assert _extract_sections(md, level=2) == {}


# ---------------------------------------------------------------------------
# 4. _extract_file_id
# ---------------------------------------------------------------------------


class TestExtractFileId:
    """Tests for file ID extraction from summary headers."""

    def test_extracts_from_file_id_line(self) -> None:
        """A 'File ID: <value>' line should return the value."""
        content = "# Summary\nFile ID: F0042\n## Algorithms\n"
        assert _extract_file_id(content) == "F0042"

    def test_extracts_from_title_line(self) -> None:
        """Fallback to 'File Summary: <file_id>' pattern."""
        content = "# File Summary: my-file.py\n## Algorithms\n"
        assert _extract_file_id(content) == "my-file.py"

    def test_returns_unknown_when_absent(self) -> None:
        """Without any recognizable line, the result should be 'unknown'."""
        assert _extract_file_id("nothing useful here") == "unknown"

    def test_case_insensitive_file_id(self) -> None:
        """The 'file id' check is case-insensitive."""
        content = "FILE ID: upper_case_id\n"
        assert _extract_file_id(content) == "upper_case_id"


# ---------------------------------------------------------------------------
# 5. _extract_pointers
# ---------------------------------------------------------------------------


class TestExtractPointers:
    """Tests for evidence pointer extraction from text."""

    def test_single_pointer(self) -> None:
        """One pointer should produce a single-element list."""
        assert _extract_pointers("[f1::S1]") == ["[f1::S1]"]

    def test_multiple_pointers(self) -> None:
        """Multiple pointers should all be returned."""
        text = "See [a::X] and [b::Y]"
        assert _extract_pointers(text) == ["[a::X]", "[b::Y]"]

    def test_no_pointers(self) -> None:
        """Text without evidence pointers returns an empty list."""
        assert _extract_pointers("no pointers here") == []


# ---------------------------------------------------------------------------
# 6. _strip_evidence
# ---------------------------------------------------------------------------


class TestStripEvidence:
    """Tests for removing evidence pointers and labels from text."""

    def test_removes_pointer_and_label(self) -> None:
        """Both the pointer and 'Evidence:' label should be removed."""
        raw = "AlgoName | Does stuff | Evidence: [file::SEC]"
        cleaned = _strip_evidence(raw)
        assert "[file::SEC]" not in cleaned
        assert "Evidence" not in cleaned

    def test_plain_text_unchanged(self) -> None:
        """Text without pointers or labels should be essentially unchanged."""
        assert _strip_evidence("plain text") == "plain text"


# ---------------------------------------------------------------------------
# 7. _split_name_intent
# ---------------------------------------------------------------------------


class TestSplitNameIntent:
    """Tests for the name|intent delimiter splitting logic."""

    def test_pipe_delimiter(self) -> None:
        """Pipe character should split into name and intent."""
        name, intent = _split_name_intent("AlgoName | Does something")
        assert name == "AlgoName"
        assert intent == "Does something"

    def test_double_dash_delimiter(self) -> None:
        """Double dash ' -- ' should split name and intent."""
        name, intent = _split_name_intent("Component -- processes data")
        assert name == "Component"
        assert intent == "processes data"

    def test_single_dash_delimiter(self) -> None:
        """Single dash ' - ' should also work as a delimiter."""
        name, intent = _split_name_intent("Widget - renders UI")
        assert name == "Widget"
        assert intent == "renders UI"

    def test_colon_delimiter(self) -> None:
        """Colon-space ': ' should split name and intent."""
        name, intent = _split_name_intent("Runner: executes tasks")
        assert name == "Runner"
        assert intent == "executes tasks"

    def test_no_delimiter(self) -> None:
        """With no recognized delimiter, name equals the text and intent is empty."""
        name, intent = _split_name_intent("JustAName")
        assert name == "JustAName"
        assert intent == ""

    def test_empty_string(self) -> None:
        """Empty input should produce two empty strings."""
        name, intent = _split_name_intent("")
        assert name == ""
        assert intent == ""

    def test_pipe_takes_priority_over_dash(self) -> None:
        """Pipe should be checked first, even when a dash is also present."""
        name, intent = _split_name_intent("A | B - C")
        assert name == "A"
        assert "B - C" in intent

    def test_multiple_pipes(self) -> None:
        """Multiple pipes should join the second-and-later parts."""
        name, intent = _split_name_intent("X | Y | Z")
        assert name == "X"
        assert intent == "Y | Z"

    def test_pipe_with_empty_trailing(self) -> None:
        """A trailing pipe with only whitespace yields an empty intent."""
        name, intent = _split_name_intent("OnlyName |   ")
        assert name == "OnlyName"
        assert intent == ""


# ---------------------------------------------------------------------------
# 8. _parse_named_items
# ---------------------------------------------------------------------------


class TestParseNamedItems:
    """Tests for parsing bullet lists into name/intent/evidence dicts."""

    def test_parses_bullet_with_evidence(self) -> None:
        """A bullet with a pipe separator and evidence pointer."""
        section = "- AlgoX | computes Y | Evidence: [f1::SEC]\n"
        items = _parse_named_items(section)
        assert len(items) == 1
        assert items[0]["name"] == "AlgoX"
        assert "computes Y" in items[0]["intent"]
        assert items[0]["evidence"] == ["[f1::SEC]"]

    def test_parses_asterisk_bullets(self) -> None:
        """Asterisk-prefixed bullets should be parsed identically."""
        section = "* Widget | renders UI\n"
        items = _parse_named_items(section)
        assert len(items) == 1
        assert items[0]["name"] == "Widget"

    def test_skips_non_bullet_lines(self) -> None:
        """Lines without '-' or '*' prefix should be ignored."""
        section = "Some paragraph\n- Actual item\nAnother paragraph\n"
        items = _parse_named_items(section)
        assert len(items) == 1
        assert items[0]["name"] == "Actual item"

    def test_empty_section(self) -> None:
        """An empty section produces an empty list."""
        assert _parse_named_items("") == []

    def test_multiple_items(self) -> None:
        """Multiple bullets should all be parsed."""
        section = "- A | first\n- B | second\n- C | third\n"
        items = _parse_named_items(section)
        assert len(items) == 3
        assert [item["name"] for item in items] == ["A", "B", "C"]

    def test_item_without_evidence(self) -> None:
        """Items without evidence pointers should have an empty evidence list."""
        section = "- PlainItem | does stuff\n"
        items = _parse_named_items(section)
        assert items[0]["evidence"] == []


# ---------------------------------------------------------------------------
# 9. parse_file_summary
# ---------------------------------------------------------------------------


def _make_full_summary(file_id: str = "F0001", section: str = "INTRO") -> str:
    """Build a realistic file summary markdown string for testing."""
    return (
        f"# File Summary: {file_id}\n"
        f"File ID: {file_id}\n\n"
        "## Algorithms\n"
        f"- Algo | Does something | Evidence: [{file_id}::{section}]\n\n"
        "## Components\n"
        f"- Component | Holds data | Evidence: [{file_id}::{section}]\n\n"
        "## Workflows\n"
        f"- Workflow | Runs tasks | Evidence: [{file_id}::{section}]\n\n"
        "## Candidate Responsibilities\n"
        f"- Owns spec updates | Evidence: [{file_id}::{section}]\n\n"
        "## Dependencies\n"
        "- dep-one\n"
        "- dep-two\n\n"
        "## Evidence Map\n"
        f"- {section}: [{file_id}::{section}]\n"
    )


class TestParseFileSummary:
    """Tests for parse_file_summary() end-to-end parsing."""

    def test_full_summary(self) -> None:
        """A complete summary should populate all FileSummary fields."""
        result = parse_file_summary(_make_full_summary())
        assert isinstance(result, FileSummary)
        assert result.file_id == "F0001"
        assert len(result.algorithms) == 1
        assert result.algorithms[0]["name"] == "Algo"
        assert len(result.components) == 1
        assert result.components[0]["name"] == "Component"
        assert len(result.workflows) == 1
        assert result.workflows[0]["name"] == "Workflow"
        assert len(result.candidate_responsibilities) == 1
        assert result.dependencies == ["dep-one", "dep-two"]
        assert "INTRO" in result.evidence_map

    def test_evidence_pointers_extracted(self) -> None:
        """Evidence pointers in items should be properly captured."""
        result = parse_file_summary(_make_full_summary())
        assert result.algorithms[0]["evidence"] == ["[F0001::INTRO]"]

    def test_empty_content(self) -> None:
        """Empty input should produce a FileSummary with defaults."""
        result = parse_file_summary("")
        assert result.file_id == "unknown"
        assert result.algorithms == []
        assert result.components == []
        assert result.workflows == []
        assert result.candidate_responsibilities == []
        assert result.dependencies == []
        assert result.evidence_map == {}

    def test_missing_sections(self) -> None:
        """Content with only a file ID and no sections should not raise."""
        content = "File ID: F0099\n\nNo sections here.\n"
        result = parse_file_summary(content)
        assert result.file_id == "F0099"
        assert result.algorithms == []

    def test_uppercase_section_names(self) -> None:
        """Uppercase section names (ALGORITHMS, COMPONENTS, etc.) should work."""
        content = (
            "File ID: F0010\n\n"
            "## ALGORITHMS\n"
            "- Sorter | sorts data\n\n"
            "## COMPONENTS\n"
            "- Store | stores data\n\n"
            "## WORKFLOWS\n"
            "- Pipeline | runs steps\n\n"
            "## CANDIDATE RESPONSIBILITIES\n"
            "- Manages config\n\n"
            "## DEPENDENCIES\n"
            "- numpy\n\n"
            "## EVIDENCE MAP\n"
            "- CONFIG: [F0010::CONFIG]\n"
        )
        result = parse_file_summary(content)
        assert result.file_id == "F0010"
        assert len(result.algorithms) == 1
        assert result.algorithms[0]["name"] == "Sorter"
        assert len(result.components) == 1
        assert len(result.workflows) == 1
        assert len(result.candidate_responsibilities) == 1
        assert result.dependencies == ["numpy"]
        assert "CONFIG" in result.evidence_map

    def test_multiple_algorithms(self) -> None:
        """Multiple bullet items under Algorithms should all be parsed."""
        content = (
            "File ID: F0020\n\n## Algorithms\n- Algo1 | first\n- Algo2 | second\n- Algo3 | third\n"
        )
        result = parse_file_summary(content)
        assert len(result.algorithms) == 3
        names = [a["name"] for a in result.algorithms]
        assert names == ["Algo1", "Algo2", "Algo3"]

    def test_comma_separated_dependencies(self) -> None:
        """Dependencies as a comma-separated line (no bullets) should be split."""
        content = "File ID: F0030\n\n## Dependencies\nnumpy, pandas, requests\n"
        result = parse_file_summary(content)
        assert result.dependencies == ["numpy", "pandas", "requests"]


# ---------------------------------------------------------------------------
# 10. parse_library_synthesis
# ---------------------------------------------------------------------------


def _make_synthesis_content(
    *,
    lib_count: int = 1,
    include_index: bool = True,
    overlap: str = "Workflow vs orchestration -> Assign to lib_001",
) -> str:
    """Build a realistic library synthesis markdown."""
    parts: list[str] = []
    if include_index:
        parts.append("## Library Index\n")
        for i in range(1, lib_count + 1):
            parts.append(f"- lib_{i:03d}: Library {i} intent\n")
        parts.append("\n")

    parts.append("## Library Charters\n\n")
    for i in range(1, lib_count + 1):
        lib_id = f"lib_{i:03d}"
        parts.append(f"### {lib_id}\n\n")
        parts.append(f"#### Intent\nOwn capability {i}.\n\n")
        parts.append(f"#### Boundaries\nScope for library {i}.\n\n")
        parts.append("#### Responsibilities\n")
        parts.append(f"- Handle task {i}\n")
        parts.append(f"- Coordinate action {i}\n\n")
        parts.append("#### Evidence\n")
        parts.append(f"- [F{i:04d}::INTRO]\n")
        parts.append(f"- [F{i:04d}::DETAILS]\n\n")
        parts.append("#### Overlap Resolutions\n")
        parts.append(f"- {overlap}\n\n")

    return "".join(parts)


class TestParseLibrarySynthesis:
    """Tests for parse_library_synthesis() end-to-end parsing."""

    def test_single_library(self) -> None:
        """A single library charter should be parsed correctly."""
        content = _make_synthesis_content(lib_count=1)
        charters, index_content = parse_library_synthesis(content)
        assert len(charters) == 1
        assert charters[0].lib_id == "lib_001"
        assert "Own capability 1" in charters[0].intent
        assert len(charters[0].responsibilities) == 2
        assert "Library Index" in index_content

    def test_multiple_libraries(self) -> None:
        """Multiple libraries should each produce a separate charter."""
        content = _make_synthesis_content(lib_count=3)
        charters, _index_content = parse_library_synthesis(content)
        assert len(charters) == 3
        lib_ids = [c.lib_id for c in charters]
        assert lib_ids == ["lib_001", "lib_002", "lib_003"]

    def test_index_content_format(self) -> None:
        """The returned index content should be valid markdown with a heading."""
        content = _make_synthesis_content(lib_count=2)
        _, index_content = parse_library_synthesis(content)
        assert index_content.startswith("# Library Index")
        assert "lib_001" in index_content
        assert "lib_002" in index_content

    def test_evidence_sources_grouped(self) -> None:
        """Evidence sources should be grouped by file_id with sorted sections."""
        content = _make_synthesis_content(lib_count=1)
        charters, _ = parse_library_synthesis(content)
        sources = charters[0].evidence_sources
        assert len(sources) == 1
        assert sources[0]["file_id"] == "F0001"
        assert sorted(sources[0]["sections"]) == ["DETAILS", "INTRO"]

    def test_overlap_resolutions_parsed(self) -> None:
        """Overlap resolutions with '->' should have description and decision."""
        content = _make_synthesis_content(overlap="X -> Y")
        charters, _ = parse_library_synthesis(content)
        overlaps = charters[0].overlap_resolutions
        assert len(overlaps) == 1
        assert overlaps[0]["description"] == "X"
        assert overlaps[0]["decision"] == "Y"

    def test_no_overlap_resolutions(self) -> None:
        """'None' overlap text should produce an empty list."""
        content = _make_synthesis_content(overlap="None")
        charters, _ = parse_library_synthesis(content)
        assert charters[0].overlap_resolutions == []

    def test_generated_index_when_missing(self) -> None:
        """When no Library Index section exists, the index should be generated."""
        content = _make_synthesis_content(lib_count=2, include_index=False)
        charters, index_content = parse_library_synthesis(content)
        assert len(charters) == 2
        assert "# Library Index" in index_content
        assert "lib_001" in index_content
        assert "lib_002" in index_content

    def test_empty_content(self) -> None:
        """Empty content should produce empty charters and a stub index."""
        charters, index_content = parse_library_synthesis("")
        assert charters == []
        assert "Library Index" in index_content

    def test_charter_fields_populated(self) -> None:
        """All LibraryCharter fields should be populated from markdown."""
        content = _make_synthesis_content(lib_count=1)
        charters, _ = parse_library_synthesis(content)
        charter = charters[0]
        assert isinstance(charter, LibraryCharter)
        assert charter.lib_id == "lib_001"
        assert charter.intent != ""
        assert charter.boundaries != ""
        assert len(charter.responsibilities) > 0
        assert len(charter.evidence_sources) > 0


# ---------------------------------------------------------------------------
# 11. parse_evidence_mapper_output
# ---------------------------------------------------------------------------


class TestParseEvidenceMapperOutput:
    """Tests for parse_evidence_mapper_output() JSON parsing."""

    def test_valid_output(self) -> None:
        """All required fields present should return the parsed dict."""
        payload = {
            "file_id": "F0001",
            "relevant_sections": ["INTRO", "DETAILS"],
            "confidence": 0.95,
            "rationale": "Strong match on algorithms.",
        }
        result = parse_evidence_mapper_output(json.dumps(payload))
        assert result["file_id"] == "F0001"
        assert result["confidence"] == 0.95
        assert len(result["relevant_sections"]) == 2

    def test_missing_file_id(self) -> None:
        """Missing 'file_id' should raise ValueError."""
        payload = {"relevant_sections": [], "confidence": 0.5, "rationale": "x"}
        with pytest.raises(ValueError, match="file_id"):
            parse_evidence_mapper_output(json.dumps(payload))

    def test_missing_relevant_sections(self) -> None:
        """Missing 'relevant_sections' should raise ValueError."""
        payload = {"file_id": "f", "confidence": 0.5, "rationale": "x"}
        with pytest.raises(ValueError, match="relevant_sections"):
            parse_evidence_mapper_output(json.dumps(payload))

    def test_missing_confidence(self) -> None:
        """Missing 'confidence' should raise ValueError."""
        payload = {"file_id": "f", "relevant_sections": [], "rationale": "x"}
        with pytest.raises(ValueError, match="confidence"):
            parse_evidence_mapper_output(json.dumps(payload))

    def test_missing_rationale(self) -> None:
        """Missing 'rationale' should raise ValueError."""
        payload = {"file_id": "f", "relevant_sections": [], "confidence": 0.5}
        with pytest.raises(ValueError, match="rationale"):
            parse_evidence_mapper_output(json.dumps(payload))

    def test_invalid_json(self) -> None:
        """Malformed JSON should raise json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            parse_evidence_mapper_output("{not valid json}")

    def test_with_agent_exec_prefix(self) -> None:
        """Agent-exec metadata should be stripped before parsing."""
        payload = {
            "file_id": "f1",
            "relevant_sections": ["A"],
            "confidence": 0.8,
            "rationale": "Good.",
        }
        raw = f"[agent-exec] started\n{json.dumps(payload)}\n[agent-exec] done"
        result = parse_evidence_mapper_output(raw)
        assert result["file_id"] == "f1"

    def test_with_fenced_code_block(self) -> None:
        """JSON wrapped in a fenced code block should be extracted."""
        payload = {
            "file_id": "f2",
            "relevant_sections": ["B"],
            "confidence": 0.7,
            "rationale": "OK.",
        }
        raw = f"```json\n{json.dumps(payload)}\n```"
        result = parse_evidence_mapper_output(raw)
        assert result["file_id"] == "f2"


# ---------------------------------------------------------------------------
# 12. parse_gap_judge_output
# ---------------------------------------------------------------------------


class TestParseGapJudgeOutput:
    """Tests for parse_gap_judge_output() JSON parsing."""

    def test_valid_output(self) -> None:
        """All required fields present should return the parsed dict."""
        payload = {
            "gaps": [{"description": "Missing retry logic"}],
            "total_gaps": 1,
            "file_id": "F0001",
        }
        result = parse_gap_judge_output(json.dumps(payload))
        assert result["total_gaps"] == 1
        assert len(result["gaps"]) == 1
        assert result["file_id"] == "F0001"

    def test_zero_gaps(self) -> None:
        """Zero gaps should be valid and parseable."""
        payload = {"gaps": [], "total_gaps": 0, "file_id": "F0001"}
        result = parse_gap_judge_output(json.dumps(payload))
        assert result["total_gaps"] == 0
        assert result["gaps"] == []

    def test_missing_gaps(self) -> None:
        """Missing 'gaps' field should raise ValueError."""
        payload = {"total_gaps": 0, "file_id": "f"}
        with pytest.raises(ValueError, match="gaps"):
            parse_gap_judge_output(json.dumps(payload))

    def test_missing_total_gaps(self) -> None:
        """Missing 'total_gaps' field should raise ValueError."""
        payload = {"gaps": [], "file_id": "f"}
        with pytest.raises(ValueError, match="total_gaps"):
            parse_gap_judge_output(json.dumps(payload))

    def test_missing_file_id(self) -> None:
        """Missing 'file_id' field should raise ValueError."""
        payload = {"gaps": [], "total_gaps": 0}
        with pytest.raises(ValueError, match="file_id"):
            parse_gap_judge_output(json.dumps(payload))

    def test_invalid_json(self) -> None:
        """Malformed JSON should raise json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            parse_gap_judge_output("not json")

    def test_with_agent_exec_prefix(self) -> None:
        """Agent-exec metadata should be stripped before parsing."""
        payload = {"gaps": [], "total_gaps": 0, "file_id": "f1"}
        raw = f"[agent-exec] log\n{json.dumps(payload)}"
        result = parse_gap_judge_output(raw)
        assert result["file_id"] == "f1"


# ---------------------------------------------------------------------------
# 13. parse_evidence_spotcheck_output
# ---------------------------------------------------------------------------


class TestParseEvidenceSpotcheckOutput:
    """Tests for parse_evidence_spotcheck_output() JSON parsing."""

    def test_valid_output(self) -> None:
        """All required fields present should return the parsed dict."""
        payload = {"missing_sections": ["INTRO"], "scan_complete": True}
        result = parse_evidence_spotcheck_output(json.dumps(payload))
        assert result["scan_complete"] is True
        assert result["missing_sections"] == ["INTRO"]

    def test_no_missing_sections(self) -> None:
        """Empty missing_sections should be valid."""
        payload = {"missing_sections": [], "scan_complete": True}
        result = parse_evidence_spotcheck_output(json.dumps(payload))
        assert result["missing_sections"] == []

    def test_missing_missing_sections(self) -> None:
        """Missing 'missing_sections' field should raise ValueError."""
        payload = {"scan_complete": True}
        with pytest.raises(ValueError, match="missing_sections"):
            parse_evidence_spotcheck_output(json.dumps(payload))

    def test_missing_scan_complete(self) -> None:
        """Missing 'scan_complete' field should raise ValueError."""
        payload = {"missing_sections": []}
        with pytest.raises(ValueError, match="scan_complete"):
            parse_evidence_spotcheck_output(json.dumps(payload))

    def test_invalid_json(self) -> None:
        """Malformed JSON should raise json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            parse_evidence_spotcheck_output("{{bad}}")

    def test_scan_incomplete(self) -> None:
        """scan_complete=false should be returned as-is."""
        payload = {"missing_sections": ["SEC1", "SEC2"], "scan_complete": False}
        result = parse_evidence_spotcheck_output(json.dumps(payload))
        assert result["scan_complete"] is False
        assert len(result["missing_sections"]) == 2


# ---------------------------------------------------------------------------
# 14. parse_architecture_proposal
# ---------------------------------------------------------------------------


def _make_valid_candidate(
    arch_id: str = "arch_001",
    pattern: str = "Monolith",
) -> dict:
    """Build a valid architecture candidate dict for testing."""
    return {
        "arch_id": arch_id,
        "pattern": pattern,
        "description": f"A {pattern} architecture.",
        "components": [{"name": "core", "role": "main"}],
        "communication": "sync",
        "deployment": "single-node",
        "citations": ["[f1::INTRO]"],
        "tradeoffs": {
            "advantages": ["simple"],
            "disadvantages": ["scalability"],
        },
    }


class TestParseArchitectureProposal:
    """Tests for parse_architecture_proposal() JSON parsing."""

    def test_single_valid_candidate(self) -> None:
        """A single valid candidate in an array should return one ArchitectureCandidate."""
        data = [_make_valid_candidate()]
        result = parse_architecture_proposal(json.dumps(data))
        assert len(result) == 1
        assert isinstance(result[0], ArchitectureCandidate)
        assert result[0].arch_id == "arch_001"
        assert result[0].pattern == "Monolith"

    def test_multiple_valid_candidates(self) -> None:
        """Multiple valid candidates should all be parsed."""
        data = [
            _make_valid_candidate("arch_001", "Monolith"),
            _make_valid_candidate("arch_002", "Microservices"),
            _make_valid_candidate("arch_003", "Modular Monolith"),
        ]
        result = parse_architecture_proposal(json.dumps(data))
        assert len(result) == 3
        ids = [c.arch_id for c in result]
        assert ids == ["arch_001", "arch_002", "arch_003"]

    def test_not_an_array(self) -> None:
        """A JSON object instead of array should raise TypeError."""
        with pytest.raises(TypeError, match="JSON array"):
            parse_architecture_proposal('{"arch_id": "a"}')

    def test_candidate_not_dict(self) -> None:
        """An array element that is not a dict should raise ValueError."""
        with pytest.raises(ValueError, match="not_object"):
            parse_architecture_proposal('["not a dict"]')

    def test_missing_required_field(self) -> None:
        """A candidate missing a required field should raise ValueError."""
        candidate = _make_valid_candidate()
        del candidate["pattern"]
        with pytest.raises(ValueError, match="missing_pattern"):
            parse_architecture_proposal(json.dumps([candidate]))

    def test_components_not_list(self) -> None:
        """Non-list 'components' should raise ValueError."""
        candidate = _make_valid_candidate()
        candidate["components"] = "not a list"
        with pytest.raises(ValueError, match="components_not_list"):
            parse_architecture_proposal(json.dumps([candidate]))

    def test_citations_not_list(self) -> None:
        """Non-list 'citations' should raise ValueError."""
        candidate = _make_valid_candidate()
        candidate["citations"] = "not a list"
        with pytest.raises(ValueError, match="citations_not_list"):
            parse_architecture_proposal(json.dumps([candidate]))

    def test_tradeoffs_not_dict(self) -> None:
        """Non-dict 'tradeoffs' should raise ValueError."""
        candidate = _make_valid_candidate()
        candidate["tradeoffs"] = "not a dict"
        with pytest.raises(ValueError, match="tradeoffs_not_object"):
            parse_architecture_proposal(json.dumps([candidate]))

    def test_tradeoffs_advantages_not_list(self) -> None:
        """Tradeoffs with non-list 'advantages' should raise ValueError."""
        candidate = _make_valid_candidate()
        candidate["tradeoffs"]["advantages"] = "string"
        with pytest.raises(ValueError, match="tradeoffs_advantages_not_list"):
            parse_architecture_proposal(json.dumps([candidate]))

    def test_tradeoffs_disadvantages_not_list(self) -> None:
        """Tradeoffs with non-list 'disadvantages' should raise ValueError."""
        candidate = _make_valid_candidate()
        candidate["tradeoffs"]["disadvantages"] = 42
        with pytest.raises(ValueError, match="tradeoffs_disadvantages_not_list"):
            parse_architecture_proposal(json.dumps([candidate]))

    def test_invalid_json(self) -> None:
        """Malformed JSON should raise json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            parse_architecture_proposal("[{broken")

    def test_empty_array(self) -> None:
        """An empty JSON array should return an empty list with no errors."""
        result = parse_architecture_proposal("[]")
        assert result == []

    def test_candidate_fields_trimmed(self) -> None:
        """Whitespace in string fields should be stripped."""
        candidate = _make_valid_candidate()
        candidate["arch_id"] = "  arch_padded  "
        candidate["pattern"] = "  Padded Pattern  "
        result = parse_architecture_proposal(json.dumps([candidate]))
        assert result[0].arch_id == "arch_padded"
        assert result[0].pattern == "Padded Pattern"

    def test_multiple_errors_joined(self) -> None:
        """Multiple validation errors should be joined with semicolons."""
        candidate = _make_valid_candidate()
        del candidate["arch_id"]
        del candidate["pattern"]
        with pytest.raises(ValueError) as exc_info:
            parse_architecture_proposal(json.dumps([candidate]))
        error_msg = str(exc_info.value)
        assert "missing_arch_id" in error_msg
        assert "missing_pattern" in error_msg
        assert ";" in error_msg


# ---------------------------------------------------------------------------
# 15. parse_architecture_selection
# ---------------------------------------------------------------------------


class TestParseArchitectureSelection:
    """Tests for parse_architecture_selection() JSON parsing."""

    def test_valid_selection(self) -> None:
        """All required fields should return the parsed dict."""
        payload = {
            "selected_arch_id": "arch_002",
            "rationale": "Best balance of complexity and maintainability.",
            "rejected_architectures": [
                {"arch_id": "arch_001", "reason": "Too rigid."},
            ],
            "implementation_risks": ["Migration complexity."],
            "evolution_notes": "Consider splitting later.",
        }
        result = parse_architecture_selection(json.dumps(payload))
        assert result["selected_arch_id"] == "arch_002"
        assert len(result["rejected_architectures"]) == 1
        assert len(result["implementation_risks"]) == 1

    @pytest.mark.parametrize(
        "missing_field",
        [
            "selected_arch_id",
            "rationale",
            "rejected_architectures",
            "implementation_risks",
            "evolution_notes",
        ],
    )
    def test_missing_required_field(self, missing_field: str) -> None:
        """Each required field, when missing, should raise ValueError."""
        payload = {
            "selected_arch_id": "arch_002",
            "rationale": "Reason.",
            "rejected_architectures": [],
            "implementation_risks": [],
            "evolution_notes": "Notes.",
        }
        del payload[missing_field]
        with pytest.raises(ValueError, match=missing_field):
            parse_architecture_selection(json.dumps(payload))

    def test_invalid_json(self) -> None:
        """Malformed JSON should raise json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            parse_architecture_selection("{{bad}}")


# ---------------------------------------------------------------------------
# 16. parse_architecture_mapping
# ---------------------------------------------------------------------------


def _make_mapping_content(
    *,
    components: dict[str, list[str]] | None = None,
    dependencies: list[str] | None = None,
    unmapped: list[str] | None = None,
) -> str:
    """Build a realistic architecture mapping markdown string."""
    if components is None:
        components = {
            "CoreEngine": ["lib_001", "lib_002"],
            "DataLayer": ["lib_003"],
        }
    if dependencies is None:
        dependencies = ["CoreEngine -> DataLayer: data access"]
    if unmapped is None:
        unmapped = ["lib_099"]

    parts: list[str] = ["## Component Mappings\n\n"]
    for comp_name, libs in components.items():
        parts.append(f"### Component: {comp_name}\n\n")
        parts.append("**Libraries**\n")
        for lib in libs:
            parts.append(f"- {lib}: assigned\n")
        parts.append("\n")

    parts.append("## Cross-Component Dependencies\n")
    for dep in dependencies:
        parts.append(f"- {dep}\n")
    parts.append("\n")

    parts.append("## Unmapped Libraries\n")
    for lib in unmapped:
        parts.append(f"- {lib}\n")
    parts.append("\n")

    return "".join(parts)


class TestParseArchitectureMapping:
    """Tests for parse_architecture_mapping() markdown parsing."""

    def test_basic_mapping(self) -> None:
        """A complete mapping should parse components, dependencies, unmapped."""
        content = _make_mapping_content()
        result = parse_architecture_mapping(content)
        assert "CoreEngine" in result["component_mappings"]
        assert "DataLayer" in result["component_mappings"]
        assert result["component_mappings"]["CoreEngine"] == ["lib_001", "lib_002"]
        assert result["component_mappings"]["DataLayer"] == ["lib_003"]

    def test_dependencies_parsed(self) -> None:
        """Cross-component dependencies should be extracted."""
        content = _make_mapping_content(dependencies=["A -> B: reason", "B -> C: another"])
        result = parse_architecture_mapping(content)
        assert len(result["dependencies"]) == 2

    def test_unmapped_libraries_parsed(self) -> None:
        """Unmapped libraries should be listed."""
        content = _make_mapping_content(unmapped=["lib_050", "lib_060"])
        result = parse_architecture_mapping(content)
        assert result["unmapped_libraries"] == ["lib_050", "lib_060"]

    def test_none_unmapped(self) -> None:
        """'None' in unmapped section should produce empty list."""
        content = _make_mapping_content(unmapped=[])
        content += "## Unmapped Libraries\n- None (all libraries are mapped)\n"
        result = parse_architecture_mapping(content)
        assert result["unmapped_libraries"] == []

    def test_empty_content(self) -> None:
        """Empty content should produce empty structures."""
        result = parse_architecture_mapping("")
        assert result["component_mappings"] == {}
        assert result["dependencies"] == []
        assert result["unmapped_libraries"] == []

    def test_component_lines_populated(self) -> None:
        """component_lines should contain the raw library lines per component."""
        content = _make_mapping_content(
            components={"Engine": ["lib_001"]},
        )
        result = parse_architecture_mapping(content)
        assert "Engine" in result["component_lines"]
        assert len(result["component_lines"]["Engine"]) == 1

    def test_component_none_bullet_ignored(self) -> None:
        """Freeform bullets like '- None (...)' under Libraries should be ignored."""
        content = textwrap.dedent(
            """
            ## Component Mappings

            ### Component: API Contract (shared)

            **Libraries**:
            - None (this component defines the interface between lib_001 and lib_002)
            - lib_001: assigned

            ## Cross-Component Dependencies
            - A -> B: reason

            ## Unmapped Libraries
            - None (all libraries are mapped)
            """
        )
        result = parse_architecture_mapping(content)
        assert result["component_mappings"]["API Contract (shared)"] == ["lib_001"]
        assert result["component_lines"]["API Contract (shared)"] == ["- lib_001: assigned"]
        assert result["unmapped_libraries"] == []

    def test_na_unmapped_filtered(self) -> None:
        """'N/A' entries in unmapped section should be filtered out."""
        content = "## Unmapped Libraries\n- N/A\n- none\n"
        result = parse_architecture_mapping(content)
        assert result["unmapped_libraries"] == []

    def test_no_component_section(self) -> None:
        """Content with only unmapped section should still parse."""
        content = "## Unmapped Libraries\n- lib_orphan\n"
        result = parse_architecture_mapping(content)
        assert result["component_mappings"] == {}
        assert result["unmapped_libraries"] == ["lib_orphan"]

    def test_multiple_libraries_per_component(self) -> None:
        """A component with many libraries should collect them all."""
        libs = [f"lib_{i:03d}" for i in range(1, 6)]
        content = _make_mapping_content(
            components={"BigComp": libs},
            dependencies=[],
            unmapped=[],
        )
        result = parse_architecture_mapping(content)
        assert len(result["component_mappings"]["BigComp"]) == 5


# ---------------------------------------------------------------------------
# Edge cases and cross-cutting concerns
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge-case tests for robustness."""

    def test_extract_json_payload_nested_braces(self) -> None:
        """Nested braces inside the object should be handled correctly."""
        raw = '{"outer": {"inner": [1,2,3]}}'
        result = _extract_json_payload(raw)
        parsed = json.loads(result)
        assert parsed["outer"]["inner"] == [1, 2, 3]

    def test_extract_json_payload_trailing_text(self) -> None:
        """Text after the closing brace should be excluded."""
        raw = '{"a": 1}  trailing garbage'
        result = _extract_json_payload(raw)
        assert json.loads(result) == {"a": 1}

    def test_extract_json_payload_leading_text(self) -> None:
        """Text before the opening brace should be excluded."""
        raw = 'prefix text {"b": 2}'
        result = _extract_json_payload(raw)
        assert json.loads(result) == {"b": 2}

    def test_parse_named_items_mixed_delimiters(self) -> None:
        """Items using different delimiter styles in the same section."""
        section = (
            "- Pipe | intent one\n"
            "- Dash -- intent two\n"
            "- SingleDash - intent three\n"
            "- Colon: intent four\n"
        )
        items = _parse_named_items(section)
        assert len(items) == 4
        assert items[0]["name"] == "Pipe"
        assert items[1]["name"] == "Dash"
        assert items[2]["name"] == "SingleDash"
        assert items[3]["name"] == "Colon"

    def test_split_name_intent_whitespace_trimmed(self) -> None:
        """Whitespace around name and intent should be trimmed."""
        name, intent = _split_name_intent("  Name  |  Intent  ")
        assert name == "Name"
        assert intent == "Intent"

    def test_evidence_mapper_extra_fields_preserved(self) -> None:
        """Extra fields beyond the required ones should be preserved."""
        payload = {
            "file_id": "f1",
            "relevant_sections": ["A"],
            "confidence": 0.9,
            "rationale": "Good.",
            "extra_field": "bonus",
        }
        result = parse_evidence_mapper_output(json.dumps(payload))
        assert result["extra_field"] == "bonus"

    def test_gap_judge_extra_fields_preserved(self) -> None:
        """Extra fields beyond the required ones should be preserved."""
        payload = {
            "gaps": [],
            "total_gaps": 0,
            "file_id": "f1",
            "extra": True,
        }
        result = parse_gap_judge_output(json.dumps(payload))
        assert result["extra"] is True

    def test_spotcheck_extra_fields_preserved(self) -> None:
        """Extra fields beyond the required ones should be preserved."""
        payload = {
            "missing_sections": [],
            "scan_complete": True,
            "notes": "all good",
        }
        result = parse_evidence_spotcheck_output(json.dumps(payload))
        assert result["notes"] == "all good"

    def test_file_summary_frozen_dataclass(self) -> None:
        """FileSummary should be immutable (frozen dataclass)."""
        result = parse_file_summary(_make_full_summary())
        with pytest.raises(AttributeError):
            result.file_id = "new_id"  # type: ignore[misc]

    def test_library_charter_frozen_dataclass(self) -> None:
        """LibraryCharter should be immutable (frozen dataclass)."""
        content = _make_synthesis_content(lib_count=1)
        charters, _ = parse_library_synthesis(content)
        with pytest.raises(AttributeError):
            charters[0].lib_id = "new_id"  # type: ignore[misc]

    def test_architecture_candidate_frozen_dataclass(self) -> None:
        """ArchitectureCandidate should be immutable (frozen dataclass)."""
        data = [_make_valid_candidate()]
        result = parse_architecture_proposal(json.dumps(data))
        with pytest.raises(AttributeError):
            result[0].arch_id = "new_id"  # type: ignore[misc]

    def test_parse_file_summary_returns_correct_type(self) -> None:
        """Return type must be FileSummary."""
        result = parse_file_summary(_make_full_summary())
        assert type(result).__name__ == "FileSummary"

    def test_extract_sections_last_section_captures_to_end(self) -> None:
        """The last section should capture all remaining content."""
        md = "## First\nfirst body\n## Last\nlast body\nmore last body\n"
        sections = _extract_sections(md, level=2)
        assert "more last body" in sections["Last"]

    def test_evidence_pointer_at_end_of_line(self) -> None:
        """A pointer at the end of a bullet line should still be captured."""
        section = "- ItemName | does stuff [f1::SEC]\n"
        items = _parse_named_items(section)
        assert items[0]["evidence"] == ["[f1::SEC]"]

    def test_extract_file_id_prefers_file_id_line(self) -> None:
        """When both 'File ID:' and 'File Summary:' exist, File ID line wins."""
        content = "# File Summary: fallback_id\nFile ID: preferred_id\n"
        assert _extract_file_id(content) == "preferred_id"
