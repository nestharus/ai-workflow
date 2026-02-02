"""Fixtures for spec repair evaluation."""

from __future__ import annotations

from spec_manager.refinement.evaluation.fixtures import RepairFixture
from spec_manager.refinement.repair import ArtifactType


def _allowlists() -> dict[str, object]:
    return {
        "lib_id": "LIB-0001",
        "file_ids": ["F0001", "F0002"],
        "sections": {
            "F0001": ["INTRO", "REQS"],
            "F0002": ["OVERVIEW"],
        },
    }


FIXTURES: list[RepairFixture] = [
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: LIB-0001\n\n"
            "## Boundaries\n"
            "- Covers core [alpha::INTRO]\n\n"
            "## Requirements\n"
            "- Must do X [F0001::REQS]\n\n"
            "## Constraints\n"
            "- Keep simple [F0002::OVERVIEW]\n\n"
            "## Dependencies\n"
            "- Depends on Y [F0001::INTRO]\n"
        ),
        expected_errors=[{"type": "unknown_file_reference"}],
        allowlists=_allowlists(),
        description="Invalid file ID in spec citations.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: LIB-0001\n\n"
            "## Boundaries\n"
            "- Covers core [F0001::MISSING]\n\n"
            "## Requirements\n"
            "- Must do X [F0001::REQS]\n\n"
            "## Constraints\n"
            "- Keep simple [F0002::OVERVIEW]\n\n"
            "## Dependencies\n"
            "- Depends on Y [F0001::INTRO]\n"
        ),
        expected_errors=[{"type": "unknown_section_reference"}],
        allowlists=_allowlists(),
        description="Invented section label in spec citation.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: LIB-0001\n\n"
            "## Boundaries\n"
            "- Covers core [F0001::INTRO]\n\n"
            "## Requirements\n"
            "- Must do X\n\n"
            "## Constraints\n"
            "- Keep simple [F0002::OVERVIEW]\n\n"
            "## Dependencies\n"
            "- Depends on Y [F0001::INTRO]\n"
        ),
        expected_errors=[{"type": "missing_citation"}],
        allowlists=_allowlists(),
        description="Missing citation in requirements bullet.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "Here is the updated spec:\n\n"
            "# Library Spec: LIB-0001\n\n"
            "## Boundaries\n"
            "- Covers core [F0001::INTRO]\n"
        ),
        expected_errors=[{"type": "stray_preamble"}],
        allowlists=_allowlists(),
        description="Stray preamble before spec heading.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: LIB-0001\n\n"
            "## Boundaries\n"
            "- Covers core [F0001::INTRO]\n\n"
            "## Requirements\n"
            "- Must do X [F0001::REQS]\n\n"
            "```\n"
        ),
        expected_errors=[{"type": "trailing_fence"}],
        allowlists=_allowlists(),
        description="Trailing fence after spec output.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: LIB-0001\n\n"
            "## Boundaries\n"
            "- Covers core [F0001::INTRO, F0001::REQS]\n\n"
            "## Requirements\n"
            "- Must do X [F0001::REQS]\n"
        ),
        expected_errors=[{"type": "compound_pointer"}],
        allowlists=_allowlists(),
        description="Compound pointer in spec bullet.",
    ),
]
