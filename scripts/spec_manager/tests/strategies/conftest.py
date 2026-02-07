"""Shared fixtures for strategy tests."""

from __future__ import annotations

import pytest

from spec_manager.core.provenance import SourceLocation, TrackedUnit, UnitType


def make_unit(
    unit_id: str = "u1",
    content: str = "test content",
    unit_type: UnitType = UnitType.PROSE,
) -> TrackedUnit:
    """Create a TrackedUnit with all required fields for testing."""
    return TrackedUnit(
        id=unit_id,
        content=content,
        unit_type=unit_type,
        source=SourceLocation(file="test.txt", line_start=1, line_end=1),
        introduced_by="test",
    )
