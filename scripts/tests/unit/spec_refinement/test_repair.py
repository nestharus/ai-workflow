from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.spec_refinement.workflows.repair import (
    ArtifactType,
    _build_repair_prompt,
    _format_allowlists,
    _select_repair_agent,
    repair_artifact,
)


class _DummyManager:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path


def test_select_repair_agent_mapping() -> None:
    assert _select_repair_agent(ArtifactType.SUMMARY) == "repair-summary"
    assert _select_repair_agent(ArtifactType.CHARTER) == "repair-charter"
    assert _select_repair_agent(ArtifactType.LIBRARY_LABELS) == "repair-library-labels"
    assert _select_repair_agent(ArtifactType.SPEC) == "repair-spec"
    assert _select_repair_agent(ArtifactType.EVIDENCE_JSON) == "repair-evidence-json"
    assert (
        _select_repair_agent(ArtifactType.ARCHITECTURE_SELECTION) == "repair-architecture-selection"
    )
    assert _select_repair_agent(ArtifactType.ARCHITECTURE_MAPPING) == "repair-architecture-mapping"


def test_repair_artifact_calls_agent_with_prompt() -> None:
    manager = _DummyManager(Path("/workspace"))
    errors = [
        {
            "type": "missing_evidence_pointers",
            "message": "No evidence pointers found.",
            "file_id": "file_001",
        }
    ]

    with patch(
        "scripts.spec_refinement.workflows.repair.run_agent",
        return_value="fixed",
    ) as mock_run:
        result = repair_artifact(
            output="bad output",
            errors=errors,
            allowlists={"file_ids": ["file_001"]},
            artifact_type=ArtifactType.SUMMARY,
            manager=manager,
        )

    assert result == "fixed"
    assert mock_run.call_args.kwargs["agent_name"] == "repair-summary"
    prompt = mock_run.call_args.kwargs["prompt"]
    assert "INVALID OUTPUT" in prompt
    assert "bad output" in prompt
    assert "1. [missing_evidence_pointers] No evidence pointers found." in prompt
    assert "file_ids: file_001" in prompt


def test_repair_artifact_skips_when_no_errors() -> None:
    manager = _DummyManager(Path("/workspace"))

    with patch("scripts.spec_refinement.workflows.repair.run_agent") as mock_run:
        result = repair_artifact(
            output="ok",
            errors=[],
            allowlists={},
            artifact_type=ArtifactType.SUMMARY,
            manager=manager,
        )

    assert result == "ok"
    mock_run.assert_not_called()


def test_repair_artifact_propagates_exception() -> None:
    manager = _DummyManager(Path("/workspace"))

    with patch(
        "scripts.spec_refinement.workflows.repair.run_agent",
        side_effect=RuntimeError("boom"),
    ), pytest.raises(RuntimeError, match="boom"):
        repair_artifact(
            output="bad",
            errors=[{"type": "bad", "message": "oops"}],
            allowlists={},
            artifact_type=ArtifactType.SUMMARY,
            manager=manager,
        )


def test_build_repair_prompt_formats_errors_and_allowlists() -> None:
    errors = [
        {
            "type": "invalid_pointer",
            "message": "Pointer invalid.",
            "file_id": "file_001",
            "context": {"section": "INTRO"},
            "lines": ["line1", "line2"],
        }
    ]
    allowlists = {
        "file_ids": ["file_001", "file_002"],
        "sections": {"file_001": ["INTRO", "DETAILS"]},
    }

    prompt = _build_repair_prompt(
        output="bad",
        errors=errors,
        allowlists=allowlists,
        artifact_type=ArtifactType.SUMMARY,
    )

    assert "1. [invalid_pointer] Pointer invalid." in prompt
    assert "file_id=file_001" in prompt
    assert 'context={"section": "INTRO"}' in prompt
    assert 'lines=["line1", "line2"]' in prompt
    assert "file_ids: file_001, file_002" in prompt
    assert "- file_001: INTRO, DETAILS" in prompt


def test_format_allowlists_handles_nested_and_empty() -> None:
    allowlists = {
        "library_ids": [],
        "sections": {"file_001": ["INTRO"], "file_002": []},
    }

    formatted = _format_allowlists(allowlists)

    assert "library_ids: None" in formatted
    assert "sections:" in formatted
    assert "- file_001: INTRO" in formatted
    assert "- file_002: None" in formatted
