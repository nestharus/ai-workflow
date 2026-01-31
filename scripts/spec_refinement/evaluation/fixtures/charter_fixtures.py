"""Fixtures for library charter repair evaluation."""

from __future__ import annotations

from scripts.spec_refinement.evaluation.fixtures import RepairFixture
from scripts.spec_refinement.workflows.repair import ArtifactType


def _allowlists() -> dict[str, object]:
    return {
        "file_ids": ["file_001", "file_002"],
        "sections": {
            "file_001": ["INTRO", "REQS"],
            "file_002": ["OVERVIEW"],
        },
    }


FIXTURES: list[RepairFixture] = [
    RepairFixture(
        artifact_type=ArtifactType.CHARTER,
        invalid_output=(
            "## Library Index\n"
            "- lib_001: Core services\n\n"
            "## Library Charters\n"
            "### lib_001\n"
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
            "- lib_001: Core services\n\n"
            "## Library Charters\n"
            "### lib_001\n"
            "#### Intent\n"
            "Provide core services.\n\n"
            "#### Boundaries\n"
            "Inside core.\n\n"
            "#### Responsibilities\n"
            "- Own service A\n\n"
            "#### Evidence\n"
            "- [file_001::MISSING]\n\n"
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
            "- lib_001: Core services\n\n"
            "## Library Charters\n"
            "### lib_001\n"
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
            "- lib_001: Core services\n\n"
            "### lib_001\n"
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
            "- lib_001: Core services\n\n"
            "### lib_001\n"
            "#### Intent\n"
            "Provide core services.\n\n"
            "#### Evidence\n"
            "- [file_001::INTRO]\n\n"
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
            "- lib_001: Core services\n\n"
            "### lib_001\n"
            "#### Intent\n"
            "Provide core services.\n\n"
            "#### Evidence\n"
            "- [file_001::INTRO, file_001::REQS]\n\n"
            "#### Overlap Resolutions\n"
            "- None\n"
        ),
        expected_errors=[{"type": "compound_pointer"}],
        allowlists=_allowlists(),
        description="Compound pointer in charter evidence.",
    ),
]
