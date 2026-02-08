"""Tests for spec_manager.core.compat module.

Tests for atom ID parsing and upgrade utilities supporting both
legacy (v1) and new (v2) formats.
"""

from __future__ import annotations

import pytest
from spec_manager.core.compat import (
    DEFAULT_LEGACY_REV_ID,
    LEGACY_ATOM_PATTERN,
    NEW_ATOM_PATTERN,
    ParsedAtomId,
    extract_file_uid,
    extract_line_no,
    extract_rev_id,
    is_legacy_format,
    is_new_format,
    parse_atom_id,
    upgrade_atom_id,
)


class TestParseAtomId:
    """Tests for parse_atom_id function."""

    def test_parse_legacy_atom_id(self) -> None:
        """ATOM-F0001-L0042 -> rev_id=R0001."""
        result = parse_atom_id("ATOM-F0001-L0042")
        assert result.file_uid == "F0001"
        assert result.rev_id == DEFAULT_LEGACY_REV_ID
        assert result.line_no == 42
        assert result.format == "v1"

    def test_parse_new_atom_id(self) -> None:
        """ATOM-F0001-R0002-L0042 parsed correctly."""
        result = parse_atom_id("ATOM-F0001-R0002-L0042")
        assert result.file_uid == "F0001"
        assert result.rev_id == "R0002"
        assert result.line_no == 42
        assert result.format == "v2"

    def test_parse_invalid_atom_id_raises(self) -> None:
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid atom ID format"):
            parse_atom_id("INVALID-ID")

    def test_parse_empty_string_raises(self) -> None:
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid atom ID format"):
            parse_atom_id("")

    def test_parse_legacy_line_number_zero_padded(self) -> None:
        """Legacy format with line number 1 is L0001."""
        result = parse_atom_id("ATOM-F0001-L0001")
        assert result.line_no == 1

    def test_parse_new_format_line_number_zero_padded(self) -> None:
        """New format with line number 1 is L0001."""
        result = parse_atom_id("ATOM-F0001-R0001-L0001")
        assert result.line_no == 1

    def test_parse_high_line_number(self) -> None:
        """High line numbers are parsed correctly."""
        result = parse_atom_id("ATOM-F0001-R0001-L9999")
        assert result.line_no == 9999

    def test_parse_high_file_uid(self) -> None:
        """High file UIDs are parsed correctly."""
        result = parse_atom_id("ATOM-F9999-R0001-L0001")
        assert result.file_uid == "F9999"

    def test_parse_high_rev_id(self) -> None:
        """High revision IDs are parsed correctly."""
        result = parse_atom_id("ATOM-F0001-R9999-L0001")
        assert result.rev_id == "R9999"


class TestUpgradeAtomId:
    """Tests for upgrade_atom_id function."""

    def test_upgrade_legacy_to_new(self) -> None:
        """Legacy format converted to new."""
        upgraded = upgrade_atom_id("ATOM-F0001-L0042")
        assert upgraded == "ATOM-F0001-R0001-L0042"

    def test_upgrade_new_format_unchanged(self) -> None:
        """New format returned unchanged."""
        original = "ATOM-F0001-R0002-L0042"
        upgraded = upgrade_atom_id(original)
        assert upgraded == original

    def test_upgrade_invalid_raises(self) -> None:
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid atom ID format"):
            upgrade_atom_id("INVALID-ID")

    def test_upgrade_preserves_line_number(self) -> None:
        """Line number is preserved in upgrade."""
        upgraded = upgrade_atom_id("ATOM-F0001-L0123")
        assert upgraded.endswith("-L0123")

    def test_upgrade_uses_default_rev_id(self) -> None:
        """Upgrade uses DEFAULT_LEGACY_REV_ID."""
        upgraded = upgrade_atom_id("ATOM-F0001-L0001")
        assert "-R0001-" in upgraded


class TestIsLegacyFormat:
    """Tests for is_legacy_format function."""

    def test_legacy_format_returns_true(self) -> None:
        """Legacy format is detected."""
        assert is_legacy_format("ATOM-F0001-L0042") is True

    def test_new_format_returns_false(self) -> None:
        """New format is not legacy."""
        assert is_legacy_format("ATOM-F0001-R0001-L0042") is False

    def test_invalid_format_returns_false(self) -> None:
        """Invalid format is not legacy."""
        assert is_legacy_format("INVALID-ID") is False


class TestIsNewFormat:
    """Tests for is_new_format function."""

    def test_new_format_returns_true(self) -> None:
        """New format is detected."""
        assert is_new_format("ATOM-F0001-R0001-L0042") is True

    def test_legacy_format_returns_false(self) -> None:
        """Legacy format is not new."""
        assert is_new_format("ATOM-F0001-L0042") is False

    def test_invalid_format_returns_false(self) -> None:
        """Invalid format is not new."""
        assert is_new_format("INVALID-ID") is False


class TestExtractFileUid:
    """Tests for extract_file_uid function."""

    def test_extract_from_legacy(self) -> None:
        """Extract file UID from legacy format."""
        assert extract_file_uid("ATOM-F0001-L0042") == "F0001"

    def test_extract_from_new(self) -> None:
        """Extract file UID from new format."""
        assert extract_file_uid("ATOM-F0002-R0003-L0042") == "F0002"

    def test_extract_raises_for_invalid(self) -> None:
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid atom ID format"):
            extract_file_uid("INVALID-ID")


class TestExtractRevId:
    """Tests for extract_rev_id function."""

    def test_extract_from_legacy_returns_default(self) -> None:
        """Legacy format returns default revision ID."""
        assert extract_rev_id("ATOM-F0001-L0042") == DEFAULT_LEGACY_REV_ID

    def test_extract_from_new(self) -> None:
        """Extract revision ID from new format."""
        assert extract_rev_id("ATOM-F0001-R0005-L0042") == "R0005"

    def test_extract_raises_for_invalid(self) -> None:
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid atom ID format"):
            extract_rev_id("INVALID-ID")


class TestExtractLineNo:
    """Tests for extract_line_no function."""

    def test_extract_from_legacy(self) -> None:
        """Extract line number from legacy format."""
        assert extract_line_no("ATOM-F0001-L0042") == 42

    def test_extract_from_new(self) -> None:
        """Extract line number from new format."""
        assert extract_line_no("ATOM-F0001-R0001-L0123") == 123

    def test_extract_raises_for_invalid(self) -> None:
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid atom ID format"):
            extract_line_no("INVALID-ID")


class TestParsedAtomId:
    """Tests for ParsedAtomId dataclass."""

    def test_atom_id_property_reconstructs_v2_format(self) -> None:
        """atom_id property reconstructs in v2 format."""
        parsed = ParsedAtomId(
            file_uid="F0001",
            rev_id="R0001",
            line_no=42,
            format="v1",
        )
        assert parsed.atom_id == "ATOM-F0001-R0001-L0042"

    def test_atom_id_property_preserves_v2_format(self) -> None:
        """atom_id property preserves v2 format values."""
        parsed = ParsedAtomId(
            file_uid="F0002",
            rev_id="R0003",
            line_no=99,
            format="v2",
        )
        assert parsed.atom_id == "ATOM-F0002-R0003-L0099"

    def test_atom_id_zero_pads_line_number(self) -> None:
        """atom_id zero-pads line number to 4 digits."""
        parsed = ParsedAtomId(
            file_uid="F0001",
            rev_id="R0001",
            line_no=1,
            format="v2",
        )
        assert parsed.atom_id.endswith("-L0001")


class TestPatterns:
    """Tests for regex patterns."""

    def test_legacy_pattern_matches_valid(self) -> None:
        """LEGACY_ATOM_PATTERN matches valid legacy IDs."""
        match = LEGACY_ATOM_PATTERN.fullmatch("ATOM-F0001-L0042")
        assert match is not None
        assert match.group("file_id") == "F0001"
        assert match.group("line_no") == "0042"

    def test_legacy_pattern_rejects_new_format(self) -> None:
        """LEGACY_ATOM_PATTERN does not match new format."""
        match = LEGACY_ATOM_PATTERN.fullmatch("ATOM-F0001-R0001-L0042")
        assert match is None

    def test_new_pattern_matches_valid(self) -> None:
        """NEW_ATOM_PATTERN matches valid new IDs."""
        match = NEW_ATOM_PATTERN.fullmatch("ATOM-F0001-R0002-L0042")
        assert match is not None
        assert match.group("file_uid") == "F0001"
        assert match.group("rev_id") == "R0002"
        assert match.group("line_no") == "0042"

    def test_new_pattern_rejects_legacy_format(self) -> None:
        """NEW_ATOM_PATTERN does not match legacy format."""
        match = NEW_ATOM_PATTERN.fullmatch("ATOM-F0001-L0042")
        assert match is None

    def test_patterns_require_exact_digit_counts(self) -> None:
        """Patterns require exactly 4 digits for each component."""
        # Wrong digit count for file_uid
        assert LEGACY_ATOM_PATTERN.fullmatch("ATOM-F001-L0042") is None
        assert NEW_ATOM_PATTERN.fullmatch("ATOM-F001-R0001-L0042") is None

        # Wrong digit count for line_no
        assert LEGACY_ATOM_PATTERN.fullmatch("ATOM-F0001-L042") is None
        assert NEW_ATOM_PATTERN.fullmatch("ATOM-F0001-R0001-L042") is None

        # Wrong digit count for rev_id
        assert NEW_ATOM_PATTERN.fullmatch("ATOM-F0001-R001-L0042") is None
