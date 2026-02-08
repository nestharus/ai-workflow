"""Tests for EVID citation parsing and formatting (CON-0021).

Tests:
- test_parse_valid_bracketed_citation: Parse [EVID-F0001-R0001-L1-L25]
- test_parse_bare_evid: Parse EVID without brackets
- test_format_evid_citation: Format EVID as [EVID-...]
- test_validate_evid_format: Validate EVID string format
- test_extract_multiple_citations: Extract all citations from text
- test_build_evid: Build EVID from components
- test_roundtrip: Parse -> format -> parse roundtrip
"""

import pytest
from spec_manager.schemas.evid_citation import (
    build_evid,
    extract_evid_citations,
    format_evid_citation,
    parse_evid_citation,
    validate_evid_format,
)
from spec_manager.schemas.evidence_ranges import EVID_CITATION_PATTERN


class TestEvidCitationPattern:
    """Test EVID_CITATION_PATTERN regex."""

    def test_valid_bracketed_citation(self) -> None:
        """Test valid bracketed citation format."""
        match = EVID_CITATION_PATTERN.search("[EVID-F0001-R0001-L1-L25]")
        assert match is not None
        assert match.group(0) == "[EVID-F0001-R0001-L1-L25]"

    def test_citation_in_text(self) -> None:
        """Test finding citation within text."""
        text = "See [EVID-F0001-R0001-L10-L20] for details."
        match = EVID_CITATION_PATTERN.search(text)
        assert match is not None
        assert match.group(0) == "[EVID-F0001-R0001-L10-L20]"

    def test_multiple_citations(self) -> None:
        """Test finding multiple citations."""
        text = "Refs: [EVID-F0001-R0001-L1-L5] and [EVID-F0002-R0001-L10-L15]"
        matches = EVID_CITATION_PATTERN.findall(text)
        assert len(matches) == 2

    def test_no_match_without_brackets(self) -> None:
        """Test that bare EVID does not match citation pattern."""
        text = "EVID-F0001-R0001-L1-L25"
        match = EVID_CITATION_PATTERN.search(text)
        assert match is None


class TestParseEvidCitation:
    """Test parse_evid_citation function."""

    def test_parse_valid_bracketed_citation(self) -> None:
        """Test parsing valid bracketed citation."""
        citation = parse_evid_citation("[EVID-F0001-R0001-L1-L25]")
        assert citation is not None
        assert citation.evid == "EVID-F0001-R0001-L1-L25"
        assert citation.file_uid == "F0001"
        assert citation.rev_id == "R0001"
        assert citation.start_line == 1
        assert citation.end_line == 25

    def test_parse_bare_evid(self) -> None:
        """Test parsing bare EVID without brackets."""
        citation = parse_evid_citation("EVID-F0002-R0003-L100-L200")
        assert citation is not None
        assert citation.evid == "EVID-F0002-R0003-L100-L200"
        assert citation.file_uid == "F0002"
        assert citation.rev_id == "R0003"
        assert citation.start_line == 100
        assert citation.end_line == 200

    def test_parse_with_whitespace(self) -> None:
        """Test parsing with leading/trailing whitespace."""
        citation = parse_evid_citation("  [EVID-F0001-R0001-L1-L1]  ")
        assert citation is not None
        assert citation.evid == "EVID-F0001-R0001-L1-L1"

    def test_parse_invalid_returns_none(self) -> None:
        """Test that invalid citations return None."""
        invalid_citations = [
            "",
            "   ",
            "[F0001-R0001-L1-L25]",  # Missing EVID prefix
            "[EVID-F001-R0001-L1-L25]",  # Wrong file_uid format
            "[EVID-F0001-R001-L1-L25]",  # Wrong rev_id format
            "[LIB-0001::spec.md::SEC-F0001-0001]",  # Legacy format
            "[spec_snapshot/file.md::SEC-F0001-0001]",  # spec_snapshot format
            "random text",
        ]
        for text in invalid_citations:
            assert parse_evid_citation(text) is None, f"Expected None for: {text}"

    def test_bracketed_property(self) -> None:
        """Test the bracketed property of EvidCitation."""
        citation = parse_evid_citation("EVID-F0001-R0001-L5-L10")
        assert citation is not None
        assert citation.bracketed == "[EVID-F0001-R0001-L5-L10]"


class TestFormatEvidCitation:
    """Test format_evid_citation function."""

    def test_format_valid_evid(self) -> None:
        """Test formatting valid EVID."""
        result = format_evid_citation("EVID-F0001-R0001-L1-L25")
        assert result == "[EVID-F0001-R0001-L1-L25]"

    def test_format_with_whitespace(self) -> None:
        """Test formatting with whitespace."""
        result = format_evid_citation("  EVID-F0001-R0001-L1-L1  ")
        assert result == "[EVID-F0001-R0001-L1-L1]"

    def test_format_invalid_raises(self) -> None:
        """Test that invalid EVID raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            format_evid_citation("invalid-evid")
        assert "Invalid EVID format" in str(exc_info.value)

    def test_format_empty_raises(self) -> None:
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError):
            format_evid_citation("")


class TestValidateEvidFormat:
    """Test validate_evid_format function."""

    def test_valid_formats(self) -> None:
        """Test valid EVID formats."""
        valid_evids = [
            "EVID-F0001-R0001-L1-L1",
            "EVID-F9999-R9999-L1-L99999",
            "EVID-F0001-R0001-L100-L200",
        ]
        for evid in valid_evids:
            assert validate_evid_format(evid) is True, f"Expected valid: {evid}"

    def test_invalid_formats(self) -> None:
        """Test invalid EVID formats."""
        invalid_evids = [
            "",
            "F0001-R0001-L1-L1",  # Missing EVID prefix
            "EVID-F001-R0001-L1-L1",  # Wrong file_uid
            "EVID-F0001-R001-L1-L1",  # Wrong rev_id
            "[EVID-F0001-R0001-L1-L1]",  # With brackets
            "evid-F0001-R0001-L1-L1",  # Wrong case
        ]
        for evid in invalid_evids:
            assert validate_evid_format(evid) is False, f"Expected invalid: {evid}"


class TestExtractEvidCitations:
    """Test extract_evid_citations function."""

    def test_extract_single_citation(self) -> None:
        """Test extracting single citation."""
        text = "Reference: [EVID-F0001-R0001-L1-L25]"
        citations = extract_evid_citations(text)
        assert len(citations) == 1
        assert citations[0].evid == "EVID-F0001-R0001-L1-L25"

    def test_extract_multiple_citations(self) -> None:
        """Test extracting multiple citations."""
        text = """
        See [EVID-F0001-R0001-L1-L10] for requirements.
        Also refer to [EVID-F0002-R0001-L5-L15] and [EVID-F0001-R0001-L20-L30].
        """
        citations = extract_evid_citations(text)
        assert len(citations) == 3
        evids = [c.evid for c in citations]
        assert "EVID-F0001-R0001-L1-L10" in evids
        assert "EVID-F0002-R0001-L5-L15" in evids
        assert "EVID-F0001-R0001-L20-L30" in evids

    def test_extract_no_citations(self) -> None:
        """Test extracting from text with no citations."""
        text = "No citations here, just [F0001::INTRO] legacy format."
        citations = extract_evid_citations(text)
        assert len(citations) == 0

    def test_extract_empty_text(self) -> None:
        """Test extracting from empty text."""
        citations = extract_evid_citations("")
        assert len(citations) == 0


class TestBuildEvid:
    """Test build_evid function."""

    def test_build_valid_evid(self) -> None:
        """Test building valid EVID."""
        evid = build_evid("F0001", "R0001", 1, 25)
        assert evid == "EVID-F0001-R0001-L1-L25"

    def test_build_single_line(self) -> None:
        """Test building single-line EVID."""
        evid = build_evid("F0001", "R0001", 5, 5)
        assert evid == "EVID-F0001-R0001-L5-L5"

    def test_build_invalid_file_uid_raises(self) -> None:
        """Test that invalid file_uid raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            build_evid("F001", "R0001", 1, 25)
        assert "file_uid" in str(exc_info.value)

    def test_build_invalid_rev_id_raises(self) -> None:
        """Test that invalid rev_id raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            build_evid("F0001", "R001", 1, 25)
        assert "rev_id" in str(exc_info.value)

    def test_build_invalid_start_line_raises(self) -> None:
        """Test that start_line < 1 raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            build_evid("F0001", "R0001", 0, 25)
        assert "start_line" in str(exc_info.value)

    def test_build_invalid_line_range_raises(self) -> None:
        """Test that end_line < start_line raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            build_evid("F0001", "R0001", 25, 10)
        assert "end_line" in str(exc_info.value)


class TestRoundtrip:
    """Test parse -> format -> parse roundtrip."""

    def test_roundtrip_from_evid(self) -> None:
        """Test roundtrip starting from bare EVID."""
        original = "EVID-F0001-R0001-L1-L25"
        formatted = format_evid_citation(original)
        parsed = parse_evid_citation(formatted)
        assert parsed is not None
        assert parsed.evid == original

    def test_roundtrip_from_bracketed(self) -> None:
        """Test roundtrip starting from bracketed citation."""
        original = "[EVID-F0002-R0003-L10-L20]"
        parsed = parse_evid_citation(original)
        assert parsed is not None
        formatted = format_evid_citation(parsed.evid)
        assert formatted == original

    def test_roundtrip_build_parse(self) -> None:
        """Test roundtrip: build -> format -> parse."""
        evid = build_evid("F0001", "R0001", 5, 15)
        formatted = format_evid_citation(evid)
        parsed = parse_evid_citation(formatted)
        assert parsed is not None
        assert parsed.file_uid == "F0001"
        assert parsed.rev_id == "R0001"
        assert parsed.start_line == 5
        assert parsed.end_line == 15
