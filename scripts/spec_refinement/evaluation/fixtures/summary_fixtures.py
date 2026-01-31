"""Fixtures for summary repair evaluation."""

from __future__ import annotations

from scripts.spec_refinement.evaluation.fixtures import RepairFixture
from scripts.spec_refinement.workflows.repair import ArtifactType


def _allowlists() -> dict[str, object]:
    return {
        "file_id": "file_001",
        "file_ids": ["file_001", "file_002"],
        "sections": {
            "file_001": ["INTRO", "REQS", "OVERVIEW"],
            "file_002": ["SETUP", "CONFIG"],
        },
    }


FIXTURES: list[RepairFixture] = [
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [alpha::INTRO]\n\n"
            "## Components\n"
            "- Component A | Does Y | Evidence: [file_001::REQS]\n\n"
            "## Workflows\n"
            "- Flow A | Does Z | Evidence: [file_001::OVERVIEW]\n\n"
            "## Candidate Responsibilities\n"
            "- Own intake | Evidence: [file_001::INTRO]\n\n"
            "## Dependencies\n"
            "- None\n\n"
            "## Evidence Map\n"
            "- INTRO: [file_001::INTRO]\n"
            "- REQS: [file_001::REQS]\n"
        ),
        expected_errors=[{"type": "unknown_file_reference"}],
        allowlists=_allowlists(),
        description="Invalid file ID in evidence pointer.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [file_001::INTRO]\n\n"
            "## Components\n"
            "- Component A | Does Y | Evidence: [file_001::SECURITY]\n\n"
            "## Workflows\n"
            "- Flow A | Does Z | Evidence: [file_001::OVERVIEW]\n\n"
            "## Candidate Responsibilities\n"
            "- Own intake | Evidence: [file_001::INTRO]\n\n"
            "## Dependencies\n"
            "- None\n\n"
            "## Evidence Map\n"
            "- INTRO: [file_001::INTRO]\n"
            "- REQS: [file_001::REQS]\n"
        ),
        expected_errors=[{"type": "unknown_section_reference"}],
        allowlists=_allowlists(),
        description="Invented section label in component evidence.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence:\n\n"
            "## Components\n"
            "- Component A | Does Y | Evidence: [file_001::REQS]\n\n"
            "## Workflows\n"
            "- Flow A | Does Z | Evidence: [file_001::OVERVIEW]\n\n"
            "## Candidate Responsibilities\n"
            "- Own intake | Evidence: [file_001::INTRO]\n\n"
            "## Dependencies\n"
            "- None\n\n"
            "## Evidence Map\n"
            "- INTRO: [file_001::INTRO]\n"
            "- REQS: [file_001::REQS]\n"
        ),
        expected_errors=[{"type": "malformed_evidence_pointer"}],
        allowlists=_allowlists(),
        description="Missing evidence pointer after Evidence label.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "Here is the corrected summary:\n\n"
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [file_001::INTRO]\n"
        ),
        expected_errors=[{"type": "stray_preamble"}],
        allowlists=_allowlists(),
        description="Stray preamble before summary heading.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [file_001::INTRO]\n\n"
            "## Components\n"
            "- Component A | Does Y | Evidence: [file_001::REQS]\n\n"
            "## Workflows\n"
            "- Flow A | Does Z | Evidence: [file_001::OVERVIEW]\n\n"
            "## Candidate Responsibilities\n"
            "- Own intake | Evidence: [file_001::INTRO]\n\n"
            "## Dependencies\n"
            "- None\n\n"
            "## Evidence Map\n"
            "- INTRO: [file_001::INTRO]\n"
            "- REQS: [file_001::REQS]\n"
            "```\n"
        ),
        expected_errors=[{"type": "trailing_fence"}],
        allowlists=_allowlists(),
        description="Trailing fence after summary output.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [file_001::INTRO, file_001::REQS]\n\n"
            "## Components\n"
            "- Component A | Does Y | Evidence: [file_001::REQS]\n"
        ),
        expected_errors=[{"type": "compound_pointer"}],
        allowlists=_allowlists(),
        description="Compound pointer with comma-separated sections.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [file_001::INTRO]\n\n"
            "## Components\n"
            "- Component A | Does Y | Evidence: [file_001::REQS]\n\n"
            "## Workflows\n"
            "- Flow A | Does Z | Evidence: [file_001::OVERVIEW]\n\n"
            "## Candidate Responsibilities\n"
            "- Own intake | Evidence: [file_001::INTRO]\n\n"
            "## Dependencies\n"
            "- None\n\n"
            "## Evidence Map\n"
            "- INTRO: [file_999::INTRO]\n"
            "- REQS: [file_001::REQS]\n"
        ),
        expected_errors=[{"type": "unknown_file_reference"}],
        allowlists=_allowlists(),
        description="Invalid file ID in evidence map.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [file_001::INTRO]\n\n"
            "## Components\n"
            "- Component A | Does Y | Evidence: [file_001::REQS]\n\n"
            "## Workflows\n"
            "- Flow A | Does Z | Evidence: [file_001::OVERVIEW]\n\n"
            "## Candidate Responsibilities\n"
            "- Own intake | Evidence: [file_001::INTRO]\n\n"
            "## Dependencies\n"
            "- None\n\n"
            "## Evidence Map\n"
            "- INTRO: [file_001::INTRO]\n"
            "- MISSING: [file_001::MISSING]\n"
        ),
        expected_errors=[{"type": "unknown_section_reference"}],
        allowlists=_allowlists(),
        description="Invented section in evidence map.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [file_001::INTRO]\n\n"
            "## Components\n"
            "- Component A | Does Y | Evidence: [file_001::REQS]\n\n"
            "## Workflows\n"
            "- Flow A | Does Z | Evidence: [file_001::OVERVIEW]\n\n"
            "## Candidate Responsibilities\n"
            "- Own intake | Evidence:\n\n"
            "## Dependencies\n"
            "- None\n\n"
            "## Evidence Map\n"
            "- INTRO: [file_001::INTRO]\n"
            "- REQS: [file_001::REQS]\n"
        ),
        expected_errors=[{"type": "malformed_evidence_pointer"}],
        allowlists=_allowlists(),
        description="Missing citation in responsibilities section.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "Note: corrected output follows.\n\n"
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [file_001::INTRO]\n"
        ),
        expected_errors=[{"type": "stray_preamble"}],
        allowlists=_allowlists(),
        description="Preamble line before header.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Algorithms\n"
            "- Algo A | Does X | Evidence: [file_001::INTRO]\n\n"
            "```\n"
        ),
        expected_errors=[{"type": "trailing_fence"}],
        allowlists=_allowlists(),
        description="Summary ends with lone code fence.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.SUMMARY,
        invalid_output=(
            "# File Summary: file_001\n"
            "File ID: file_001\n\n"
            "## Evidence Map\n"
            "- INTRO: [file_001::INTRO, file_001::REQS]\n"
        ),
        expected_errors=[{"type": "compound_pointer"}],
        allowlists=_allowlists(),
        description="Compound pointer in evidence map entry.",
    ),
]
