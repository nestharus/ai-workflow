"""Projection schemas for DS-PROJ-0001 and DS-PROJ-0002.

This module defines schemas for:
- Pin: Mapping from projection offset to authoritative L1 ID (DS-PROJ-0002)
- ProjectionArtifact: L2 document with embedded pins (DS-PROJ-0001)
- ProjectionPolicy: Configuration for projection generation

Phase 7 Work Item 1: Projection Generation with Pins
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Pin ID pattern: PIN-####
_PIN_ID_PATTERN = re.compile(r"^PIN-\d{4}$")

# Inline pin format: [@pin:PIN-0001 target:LIBRARY:LIB-0003]
PIN_INLINE_PATTERN = re.compile(
    r"\[@pin:(?P<pin_id>PIN-\d{4})\s+target:(?P<kind>[A-Z_]+):(?P<id>[A-Z0-9-]+)\]"
)


class Pin(BaseModel):
    """DS-PROJ-0002 compliant pin.

    A pin maps a specific offset in a projection artifact to an
    authoritative L1 entity (library, element, or atom range).

    Attributes:
        pin_id: Unique identifier (PIN-####)
        from_projection_offset: Character offset in projection content
        target_id: ID of the target entity (LIB-####, DTL-LIB-####-####, etc.)
        target_kind: Type of target (LIBRARY, ELEMENT, ATOM_RANGE)
        target_path: Optional file path for the target
    """

    pin_id: str
    from_projection_offset: int = Field(ge=0)
    target_id: str
    target_kind: Literal["LIBRARY", "ELEMENT", "ATOM_RANGE"]
    target_path: str | None = None

    @field_validator("pin_id")
    @classmethod
    def validate_pin_id(cls, value: str) -> str:
        """Validate pin ID format."""
        if not _PIN_ID_PATTERN.fullmatch(value):
            raise ValueError(f"pin_id must match PIN-#### format, got: {value}")
        return value


class ProjectionArtifact(BaseModel):
    """DS-PROJ-0001 compliant projection artifact.

    A projection artifact is a generated L2 document (plan.md, tasks.md, etc.)
    that contains pins mapping content back to authoritative L1 sources.

    Attributes:
        projection_id: Unique identifier for this projection
        kind: Type of projection artifact
        generated_from: Source type used to generate this projection
        content: The projection content with inline pins
        pins: List of Pin objects for offset-to-source mapping
        created_at: ISO8601 timestamp when projection was created
    """

    projection_id: str
    kind: Literal["PLAN_MD", "COMPOSITE_MD", "TASKS_MD", "ARCH_MD"]
    generated_from: Literal["LIBRARIES", "SPEC_INDEX", "EVIDENCE_GRAPH"]
    content: str
    pins: list[Pin] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def get_pin_by_id(self, pin_id: str) -> Pin | None:
        """Get a pin by its ID.

        Args:
            pin_id: The pin ID to look up

        Returns:
            Pin if found, None otherwise
        """
        for pin in self.pins:
            if pin.pin_id == pin_id:
                return pin
        return None

    def get_pins_by_target(self, target_id: str) -> list[Pin]:
        """Get all pins pointing to a specific target.

        Args:
            target_id: The target ID to filter by

        Returns:
            List of pins pointing to this target
        """
        return [pin for pin in self.pins if pin.target_id == target_id]

    def get_pins_by_kind(self, target_kind: str) -> list[Pin]:
        """Get all pins of a specific kind.

        Args:
            target_kind: The target kind to filter by

        Returns:
            List of pins of this kind
        """
        return [pin for pin in self.pins if pin.target_kind == target_kind]

    def get_target_ids(self) -> set[str]:
        """Get all unique target IDs referenced by pins.

        Returns:
            Set of target IDs
        """
        return {pin.target_id for pin in self.pins}


class ProjectionPolicy(BaseModel):
    """Configuration for projection generation.

    Attributes:
        include_pins: Whether to include inline pins in content
        pin_format: Format string for inline pins
        group_by_library: Whether to group content by library
        include_metadata: Whether to include metadata headers
        strip_internal_ids: Whether to strip internal-only IDs
    """

    include_pins: bool = True
    pin_format: str = "[@pin:{pin_id} target:{kind}:{id}]"
    group_by_library: bool = True
    include_metadata: bool = True
    strip_internal_ids: bool = False

    def format_pin(self, pin: Pin) -> str:
        """Format a pin as an inline string.

        Args:
            pin: The Pin to format

        Returns:
            Formatted pin string
        """
        return self.pin_format.format(
            pin_id=pin.pin_id,
            kind=pin.target_kind,
            id=pin.target_id,
        )


def parse_inline_pins(content: str) -> list[Pin]:
    """Parse inline pins from projection content.

    Extracts pins in format: [@pin:PIN-#### target:KIND:ID]

    Args:
        content: Projection content with inline pins

    Returns:
        List of parsed Pin objects
    """
    pins: list[Pin] = []

    for match in PIN_INLINE_PATTERN.finditer(content):
        pin = Pin(
            pin_id=match.group("pin_id"),
            from_projection_offset=match.start(),
            target_id=match.group("id"),
            target_kind=match.group("kind"),  # type: ignore[arg-type]
        )
        pins.append(pin)

    return pins


def strip_inline_pins(content: str) -> str:
    """Strip inline pins from projection content.

    Removes all [@pin:...] markers from content.

    Args:
        content: Projection content with inline pins

    Returns:
        Content with pins removed
    """
    return PIN_INLINE_PATTERN.sub("", content)


def validate_pins_against_content(artifact: ProjectionArtifact) -> list[str]:
    """Validate that all pins have valid offsets in content.

    Args:
        artifact: ProjectionArtifact to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []
    content_len = len(artifact.content)

    for pin in artifact.pins:
        if pin.from_projection_offset >= content_len:
            errors.append(
                f"Pin {pin.pin_id} offset {pin.from_projection_offset} "
                f"exceeds content length {content_len}"
            )

    return errors


__all__ = [
    "PIN_INLINE_PATTERN",
    "Pin",
    "ProjectionArtifact",
    "ProjectionPolicy",
    "parse_inline_pins",
    "strip_inline_pins",
    "validate_pins_against_content",
]
