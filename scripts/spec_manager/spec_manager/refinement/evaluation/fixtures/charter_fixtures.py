"""Fixtures for library charter repair evaluation."""

from __future__ import annotations

from spec_manager.refinement.evaluation.fixtures import RepairFixture
from spec_manager.refinement.repair import ArtifactType


def _allowlists() -> dict[str, object]:
    return {
        "file_ids": ["F0001", "F0002"],
        "sections": {
            "F0001": ["INTRO", "REQS", "INTRO,REQS"],
            "F0002": ["OVERVIEW"],
        },
    }


FIXTURES: list[RepairFixture] = [
    RepairFixture(
        artifact_type=ArtifactType.CHARTER,
        invalid_output=(
            "## Library Index\n"
            "- LIB-0001: Core services\n\n"
            "## Library Charters\n"
            "### LIB-0001\n"
            "#### Intent\n"
            "Provide core services.\n\n"
            "#### Boundaries\n"
            "Inside core.\n\n"
            "#### Responsibilities\n"
            "- Own service A\n\n"
            "#### Evidence\n"
            "- [alpha::INTRO]\n\n"
            "#### Overlap Resolutions\n"
            "- None\n"
        ),
        expected_errors=[{"type": "unknown_file_reference"}],
        allowlists=_allowlists(),
        description="Invalid file ID in charter evidence.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.CHARTER,
        invalid_output=(
            "## Library Index\n"
            "- LIB-0001: Core services\n\n"
            "## Library Charters\n"
            "### LIB-0001\n"
            "#### Intent\n"
            "Provide core services.\n\n"
            "#### Boundaries\n"
            "Inside core.\n\n"
            "#### Responsibilities\n"
            "- Own service A\n\n"
            "#### Evidence\n"
            "- [F0001::MISSING]\n\n"
            "#### Overlap Resolutions\n"
            "- None\n"
        ),
        expected_errors=[{"type": "unknown_section_reference"}],
        allowlists=_allowlists(),
        description="Invented section in charter evidence.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.CHARTER,
        invalid_output=(
            "## Library Index\n"
            "- LIB-0001: Core services\n\n"
            "## Library Charters\n"
            "### LIB-0001\n"
            "#### Intent\n"
            "Provide core services.\n\n"
            "#### Boundaries\n"
            "Inside core.\n\n"
            "#### Responsibilities\n"
            "- Own service A\n\n"
            "#### Evidence\n"
            "- Evidence TBD\n\n"
            "#### Overlap Resolutions\n"
            "- None\n"
        ),
        expected_errors=[{"type": "missing_citation"}],
        allowlists=_allowlists(),
        description="Evidence bullet missing citation pointer.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.CHARTER,
        invalid_output=(
            "Here is the charter output:\n\n"
            "## Library Index\n"
            "- LIB-0001: Core services\n\n"
            "### LIB-0001\n"
            "#### Intent\n"
            "Provide core services.\n"
        ),
        expected_errors=[{"type": "stray_preamble"}],
        allowlists=_allowlists(),
        description="Stray preamble before charter index.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.CHARTER,
        invalid_output=(
            "## Library Index\n"
            "- LIB-0001: Core services\n\n"
            "### LIB-0001\n"
            "#### Intent\n"
            "Provide core services.\n\n"
            "#### Evidence\n"
            "- [F0001::INTRO]\n\n"
            "```\n"
        ),
        expected_errors=[{"type": "trailing_fence"}],
        allowlists=_allowlists(),
        description="Trailing fence after charter output.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.CHARTER,
        invalid_output=(
            "## Library Index\n"
            "- LIB-0001: Core services\n\n"
            "### LIB-0001\n"
            "#### Intent\n"
            "Provide core services.\n\n"
            "#### Evidence\n"
            "- [F0001::INTRO,REQS]\n\n"
            "#### Overlap Resolutions\n"
            "- None\n"
        ),
        expected_errors=[{"type": "compound_pointer"}],
        allowlists=_allowlists(),
        description="Compound pointer in charter evidence.",
    ),
]
