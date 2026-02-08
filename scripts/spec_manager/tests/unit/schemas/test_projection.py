"""Tests for projection schemas (DS-PROJ-0001, DS-PROJ-0002).

Tests:
- test_pin_validation: Pin ID format validation
- test_projection_artifact_basic: Basic artifact creation
- test_pin_format: Inline pin format
- test_parse_inline_pins: Parsing pins from content
- test_strip_inline_pins: Removing pins from content
- test_validate_pins_against_content: Offset validation
"""

from __future__ import annotations

import pytest
from spec_manager.schemas.projection import (
    PIN_INLINE_PATTERN,
    Pin,
    ProjectionArtifact,
    ProjectionPolicy,
    parse_inline_pins,
    strip_inline_pins,
    validate_pins_against_content,
)


class TestPin:
    """Test Pin schema."""

    def test_valid_pin(self) -> None:
        """Test valid pin creation."""
        pin = Pin(
            pin_id="PIN-0001",
            from_projection_offset=100,
            target_id="LIB-0003",
            target_kind="LIBRARY",
            target_path="libraries/auth.md",
        )
        assert pin.pin_id == "PIN-0001"
        assert pin.from_projection_offset == 100
        assert pin.target_id == "LIB-0003"
        assert pin.target_kind == "LIBRARY"

    def test_invalid_pin_id(self) -> None:
        """Test invalid pin ID raises error."""
        with pytest.raises(ValueError, match="PIN-####"):
            Pin(
                pin_id="INVALID",
                from_projection_offset=0,
                target_id="LIB-0001",
                target_kind="LIBRARY",
            )

    def test_negative_offset_rejected(self) -> None:
        """Test negative offset raises error."""
        with pytest.raises(ValueError):
            Pin(
                pin_id="PIN-0001",
                from_projection_offset=-1,
                target_id="LIB-0001",
                target_kind="LIBRARY",
            )

    def test_element_target_kind(self) -> None:
        """Test ELEMENT target kind."""
        pin = Pin(
            pin_id="PIN-0001",
            from_projection_offset=0,
            target_id="REQ-LIB-0001-0001",
            target_kind="ELEMENT",
        )
        assert pin.target_kind == "ELEMENT"

    def test_atom_range_target_kind(self) -> None:
        """Test ATOM_RANGE target kind."""
        pin = Pin(
            pin_id="PIN-0001",
            from_projection_offset=0,
            target_id="ATOM-F0001-R0001-L0001",
            target_kind="ATOM_RANGE",
        )
        assert pin.target_kind == "ATOM_RANGE"


class TestProjectionArtifact:
    """Test ProjectionArtifact schema."""

    def test_basic_artifact(self) -> None:
        """Test basic artifact creation."""
        artifact = ProjectionArtifact(
            projection_id="PROJ-001",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content="# Test Plan\n\nContent here.",
            pins=[],
        )
        assert artifact.projection_id == "PROJ-001"
        assert artifact.kind == "PLAN_MD"
        assert artifact.generated_from == "LIBRARIES"
        assert artifact.content == "# Test Plan\n\nContent here."
        assert artifact.pins == []

    def test_artifact_with_pins(self) -> None:
        """Test artifact with pins."""
        pins = [
            Pin(
                pin_id="PIN-0001",
                from_projection_offset=10,
                target_id="LIB-0001",
                target_kind="LIBRARY",
            ),
            Pin(
                pin_id="PIN-0002",
                from_projection_offset=50,
                target_id="REQ-LIB-0001-0001",
                target_kind="ELEMENT",
            ),
        ]
        artifact = ProjectionArtifact(
            projection_id="PROJ-002",
            kind="PLAN_MD",
            generated_from="SPEC_INDEX",
            content="Content with pins embedded.",
            pins=pins,
        )
        assert len(artifact.pins) == 2

    def test_get_pin_by_id(self) -> None:
        """Test get_pin_by_id method."""
        pin = Pin(
            pin_id="PIN-0001",
            from_projection_offset=0,
            target_id="LIB-0001",
            target_kind="LIBRARY",
        )
        artifact = ProjectionArtifact(
            projection_id="PROJ-003",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content="Test",
            pins=[pin],
        )

        found = artifact.get_pin_by_id("PIN-0001")
        assert found is not None
        assert found.target_id == "LIB-0001"

        not_found = artifact.get_pin_by_id("PIN-9999")
        assert not_found is None

    def test_get_pins_by_target(self) -> None:
        """Test get_pins_by_target method."""
        pins = [
            Pin(
                pin_id="PIN-0001",
                from_projection_offset=0,
                target_id="LIB-0001",
                target_kind="LIBRARY",
            ),
            Pin(
                pin_id="PIN-0002",
                from_projection_offset=10,
                target_id="LIB-0001",
                target_kind="LIBRARY",
            ),
            Pin(
                pin_id="PIN-0003",
                from_projection_offset=20,
                target_id="LIB-0002",
                target_kind="LIBRARY",
            ),
        ]
        artifact = ProjectionArtifact(
            projection_id="PROJ-004",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content="Content",
            pins=pins,
        )

        lib1_pins = artifact.get_pins_by_target("LIB-0001")
        assert len(lib1_pins) == 2

    def test_get_target_ids(self) -> None:
        """Test get_target_ids method."""
        pins = [
            Pin(
                pin_id="PIN-0001",
                from_projection_offset=0,
                target_id="LIB-0001",
                target_kind="LIBRARY",
            ),
            Pin(
                pin_id="PIN-0002",
                from_projection_offset=10,
                target_id="LIB-0001",
                target_kind="LIBRARY",
            ),
            Pin(
                pin_id="PIN-0003",
                from_projection_offset=20,
                target_id="LIB-0002",
                target_kind="LIBRARY",
            ),
        ]
        artifact = ProjectionArtifact(
            projection_id="PROJ-005",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content="Content",
            pins=pins,
        )

        target_ids = artifact.get_target_ids()
        assert target_ids == {"LIB-0001", "LIB-0002"}


class TestProjectionPolicy:
    """Test ProjectionPolicy configuration."""

    def test_default_policy(self) -> None:
        """Test default policy values."""
        policy = ProjectionPolicy()
        assert policy.include_pins is True
        assert policy.group_by_library is True
        assert policy.include_metadata is True

    def test_format_pin(self) -> None:
        """Test format_pin method."""
        policy = ProjectionPolicy()
        pin = Pin(
            pin_id="PIN-0001",
            from_projection_offset=0,
            target_id="LIB-0003",
            target_kind="LIBRARY",
        )

        formatted = policy.format_pin(pin)
        assert formatted == "[@pin:PIN-0001 target:LIBRARY:LIB-0003]"


class TestPinParsing:
    """Test inline pin parsing functions."""

    def test_parse_inline_pins(self) -> None:
        """Test parsing pins from content."""
        content = """# Plan

## Authentication [@pin:PIN-0001 target:LIBRARY:LIB-0001]

### REQ-0001 [@pin:PIN-0002 target:ELEMENT:REQ-LIB-0001-0001]

Some content here.
"""
        pins = parse_inline_pins(content)

        assert len(pins) == 2
        assert pins[0].pin_id == "PIN-0001"
        assert pins[0].target_kind == "LIBRARY"
        assert pins[0].target_id == "LIB-0001"
        assert pins[1].pin_id == "PIN-0002"
        assert pins[1].target_kind == "ELEMENT"

    def test_parse_no_pins(self) -> None:
        """Test parsing content with no pins."""
        content = "# Plan\n\nNo pins here."
        pins = parse_inline_pins(content)
        assert pins == []

    def test_strip_inline_pins(self) -> None:
        """Test stripping pins from content."""
        content = "Header [@pin:PIN-0001 target:LIBRARY:LIB-0001] text"
        stripped = strip_inline_pins(content)
        assert stripped == "Header  text"

    def test_pin_pattern_regex(self) -> None:
        """Test PIN_INLINE_PATTERN matches correctly."""
        valid = "[@pin:PIN-0001 target:LIBRARY:LIB-0001]"
        match = PIN_INLINE_PATTERN.fullmatch(valid)
        assert match is not None
        assert match.group("pin_id") == "PIN-0001"
        assert match.group("kind") == "LIBRARY"
        assert match.group("id") == "LIB-0001"


class TestValidation:
    """Test validation functions."""

    def test_validate_pins_valid(self) -> None:
        """Test validation passes for valid pins."""
        content = "0123456789"  # 10 chars
        pins = [
            Pin(
                pin_id="PIN-0001",
                from_projection_offset=5,
                target_id="LIB-0001",
                target_kind="LIBRARY",
            ),
        ]
        artifact = ProjectionArtifact(
            projection_id="PROJ-001",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content=content,
            pins=pins,
        )

        errors = validate_pins_against_content(artifact)
        assert errors == []

    def test_validate_pins_invalid_offset(self) -> None:
        """Test validation catches invalid offset."""
        content = "short"  # 5 chars
        pins = [
            Pin(
                pin_id="PIN-0001",
                from_projection_offset=100,
                target_id="LIB-0001",
                target_kind="LIBRARY",
            ),
        ]
        artifact = ProjectionArtifact(
            projection_id="PROJ-001",
            kind="PLAN_MD",
            generated_from="LIBRARIES",
            content=content,
            pins=pins,
        )

        errors = validate_pins_against_content(artifact)
        assert len(errors) == 1
        assert "PIN-0001" in errors[0]
        assert "exceeds content length" in errors[0]
