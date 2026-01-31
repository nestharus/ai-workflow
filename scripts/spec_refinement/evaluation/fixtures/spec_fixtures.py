"""Fixtures for spec repair evaluation."""

from __future__ import annotations

from scripts.spec_refinement.evaluation.fixtures import RepairFixture
from scripts.spec_refinement.workflows.repair import ArtifactType


def _allowlists() -> dict[str, object]:
    return {
        "lib_id": "lib_001",
        "file_ids": ["file_001", "file_002"],
        "sections": {
            "file_001": ["INTRO", "REQS"],
            "file_002": ["OVERVIEW"],
        },
    }


FIXTURES: list[RepairFixture] = [
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: lib_001\n\n"
            "## Boundaries\n"
            "- Covers core [alpha::INTRO]\n\n"
            "## Requirements\n"
            "- Must do X [file_001::REQS]\n\n"
            "## Constraints\n"
            "- Keep simple [file_002::OVERVIEW]\n\n"
            "## Dependencies\n"
            "- Depends on Y [file_001::INTRO]\n"
        ),
        expected_errors=[{"type": "unknown_file_reference"}],
        allowlists=_allowlists(),
        description="Invalid file ID in spec citations.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: lib_001\n\n"
            "## Boundaries\n"
            "- Covers core [file_001::MISSING]\n\n"
            "## Requirements\n"
            "- Must do X [file_001::REQS]\n\n"
            "## Constraints\n"
            "- Keep simple [file_002::OVERVIEW]\n\n"
            "## Dependencies\n"
            "- Depends on Y [file_001::INTRO]\n"
        ),
        expected_errors=[{"type": "unknown_section_reference"}],
        allowlists=_allowlists(),
        description="Invented section label in spec citation.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: lib_001\n\n"
            "## Boundaries\n"
            "- Covers core [file_001::INTRO]\n\n"
            "## Requirements\n"
            "- Must do X\n\n"
            "## Constraints\n"
            "- Keep simple [file_002::OVERVIEW]\n\n"
            "## Dependencies\n"
            "- Depends on Y [file_001::INTRO]\n"
        ),
        expected_errors=[{"type": "missing_citation"}],
        allowlists=_allowlists(),
        description="Missing citation in requirements bullet.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "Here is the updated spec:\n\n"
            "# Library Spec: lib_001\n\n"
            "## Boundaries\n"
            "- Covers core [file_001::INTRO]\n"
        ),
        expected_errors=[{"type": "stray_preamble"}],
        allowlists=_allowlists(),
        description="Stray preamble before spec heading.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: lib_001\n\n"
            "## Boundaries\n"
            "- Covers core [file_001::INTRO]\n\n"
            "## Requirements\n"
            "- Must do X [file_001::REQS]\n\n"
            "```\n"
        ),
        expected_errors=[{"type": "trailing_fence"}],
        allowlists=_allowlists(),
        description="Trailing fence after spec output.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SPEC,
        invalid_output=(
            "# Library Spec: lib_001\n\n"
            "## Boundaries\n"
            "- Covers core [file_001::INTRO, file_001::REQS]\n\n"
            "## Requirements\n"
            "- Must do X [file_001::REQS]\n"
        ),
        expected_errors=[{"type": "compound_pointer"}],
        allowlists=_allowlists(),
        description="Compound pointer in spec bullet.",
    ),
]
