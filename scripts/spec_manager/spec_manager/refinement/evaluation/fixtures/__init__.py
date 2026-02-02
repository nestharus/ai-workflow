"""Fixture definitions for repair model evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from spec_manager.refinement.repair import ArtifactType


class FixtureCategory(str, Enum):
    """Categories of fixture for repair model evaluation."""

    INVALID_FILE_ID = "invalid_file_id"
    INVENTED_SECTION = "invented_section"
    MISSING_CITATION = "missing_citation"
    STRAY_PREAMBLE = "stray_preamble"
    TRAILING_FENCE = "trailing_fence"
    COMPOUND_POINTER = "compound_pointer"


@dataclass(frozen=True)
class RepairFixture:
    """Fixture data for repair model evaluation."""

    artifact_type: ArtifactType
    invalid_output: str
    expected_errors: list[dict[str, Any]]
    allowlists: dict[str, Any]
    description: str
    expected_valid_output: str | None = None
