"""Fixtures for architecture repair evaluation."""

from __future__ import annotations

from spec_manager.refinement.evaluation.fixtures import RepairFixture
from spec_manager.refinement.repair import ArtifactType


def _allowlists() -> dict[str, object]:
    return {
        "library_ids": ["LIB-0001"],
        "library_files": {
            "LIB-0001": {
                "spec.md": ["CONSTRAINTS", "RISKS", "CONSTRAINTS,RISKS"],
                "charter.md": ["INTENT"],
            }
        },
    }


FIXTURES: list[RepairFixture] = [
    RepairFixture(
        artifact_type=ArtifactType.ARCHITECTURE_SELECTION,
        invalid_output="Decision uses [LIB-0999::spec.md::CONSTRAINTS] for latency.",
        expected_errors=[{"type": "unknown_library"}],
        allowlists=_allowlists(),
        description="Unknown library in architecture citation.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.ARCHITECTURE_SELECTION,
        invalid_output="Decision uses [LIB-0001::spec.md::MISSING] for latency.",
        expected_errors=[{"type": "unknown_section_reference"}],
        allowlists=_allowlists(),
        description="Invented section in architecture citation.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.ARCHITECTURE_SELECTION,
        invalid_output="Decision prefers layered design for simplicity.",
        expected_errors=[{"type": "missing_citations"}],
        allowlists=_allowlists(),
        description="Architecture rationale missing citations.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.ARCHITECTURE_SELECTION,
        invalid_output=(
            "Here is the rationale:\n\nDecision uses [LIB-0001::spec.md::CONSTRAINTS] for latency."
        ),
        expected_errors=[{"type": "stray_preamble"}],
        allowlists=_allowlists(),
        description="Stray preamble before architecture rationale.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.ARCHITECTURE_SELECTION,
        invalid_output=("Decision uses [LIB-0001::spec.md::CONSTRAINTS] for latency.\n```\n"),
        expected_errors=[{"type": "trailing_fence"}],
        allowlists=_allowlists(),
        description="Trailing fence after architecture rationale.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.ARCHITECTURE_SELECTION,
        invalid_output=("Decision uses [LIB-0001::spec.md::CONSTRAINTS,RISKS] for latency."),
        expected_errors=[{"type": "compound_pointer"}],
        allowlists=_allowlists(),
        description="Compound pointer in architecture citation.",
    ),
]
