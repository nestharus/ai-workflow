"""Fixtures for evidence JSON repair evaluation."""

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
        artifact_type=ArtifactType.EVIDENCE_JSON,
        invalid_output=(
            '{\n  "sources": [\n    {"file_id": "alpha", "sections": ["INTRO"]}\n  ]\n}\n'
        ),
        expected_errors=[{"type": "unknown_file_reference"}],
        allowlists=_allowlists(),
        description="Invalid file_id in evidence JSON entry.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.EVIDENCE_JSON,
        invalid_output=(
            '{\n  "sources": [\n    {"file_id": "F0001", "sections": ["MISSING"]}\n  ]\n}\n'
        ),
        expected_errors=[{"type": "unknown_section_reference"}],
        allowlists=_allowlists(),
        description="Invented section in evidence JSON entry.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.EVIDENCE_JSON,
        invalid_output=('{\n  "sources": [\n    {"file_id": "F0001", "sections": []}\n  ]\n}\n'),
        expected_errors=[{"type": "missing_citation"}],
        allowlists=_allowlists(),
        description="Evidence entry missing section citations.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.EVIDENCE_JSON,
        invalid_output=(
            "Here is the corrected JSON:\n"
            "{\n"
            '  "sources": [\n'
            '    {"file_id": "F0001", "sections": ["INTRO"]}\n'
            "  ]\n"
            "}\n"
        ),
        expected_errors=[{"type": "stray_preamble"}],
        allowlists=_allowlists(),
        description="Stray preamble before JSON payload.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.EVIDENCE_JSON,
        invalid_output=(
            '{\n  "sources": [\n    {"file_id": "F0001", "sections": ["INTRO"]}\n  ]\n}\n```\n'
        ),
        expected_errors=[{"type": "trailing_fence"}],
        allowlists=_allowlists(),
        description="Trailing code fence after JSON payload.",
    ),
    RepairFixture(
        artifact_type=ArtifactType.EVIDENCE_JSON,
        invalid_output=(
            '{\n  "sources": [\n    {"file_id": "F0001", "sections": ["INTRO, REQS"]}\n  ]\n}\n'
        ),
        expected_errors=[{"type": "compound_pointer"}],
        allowlists=_allowlists(),
        description="Compound pointer packed into a section string.",
    ),
]
