from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from spec_manager.refinement.repair import (
    ArtifactType,
    _build_repair_prompt,
    _format_allowlists,
    _select_repair_agent,
    get_repair_model,
    repair_artifact,
)


class _DummyManager:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path


def test_select_repair_agent_mapping() -> None:
    selection = _select_repair_agent(ArtifactType.SUMMARY, model_override="gpt-5.2-none")
    assert selection.agent_name == "repair-summary"
    assert selection.model_name == "gpt-5.2-none"

    selection = _select_repair_agent(ArtifactType.CHARTER, model_override="gpt-5.2-none")
    assert selection.agent_name == "repair-charter"

    selection = _select_repair_agent(ArtifactType.LIBRARY_LABELS, model_override="gpt-5.2-none")
    assert selection.agent_name == "repair-library-labels"

    selection = _select_repair_agent(ArtifactType.SPEC, model_override="gpt-5.2-none")
    assert selection.agent_name == "repair-spec"

    selection = _select_repair_agent(ArtifactType.SPEC_PATCHES, model_override="gpt-5.2-none")
    assert selection.agent_name == "repair-spec-patches"

    selection = _select_repair_agent(ArtifactType.EVIDENCE_JSON, model_override="gpt-5.2-none")
    assert selection.agent_name == "repair-evidence-json"

    selection = _select_repair_agent(
        ArtifactType.ARCHITECTURE_SELECTION, model_override="gpt-5.2-none"
    )
    assert selection.agent_name == "repair-architecture-selection"

    selection = _select_repair_agent(
        ArtifactType.ARCHITECTURE_MAPPING, model_override="gpt-5.2-none"
    )
    assert selection.agent_name == "repair-architecture-mapping"


def test_repair_artifact_calls_agent_with_prompt() -> None:
    manager = _DummyManager(Path("/workspace"))
    errors = [
        {
            "type": "missing_evidence_pointers",
            "message": "No evidence pointers found.",
            "file_id": "F0001",
        }
    ]

    with patch(
        "spec_manager.refinement.repair.run_agent",
        return_value="fixed",
    ) as mock_run:
        repaired, evidence = repair_artifact(
            output="bad output",
            errors=errors,
            allowlists={"file_ids": ["F0001"]},
            artifact_type=ArtifactType.SUMMARY,
            model_override=get_repair_model(),
            manager=manager,
        )

    assert repaired == "fixed"
    assert evidence and evidence[0]["type"] == "repair_agent_invoked"
    assert mock_run.call_args.kwargs["agent_name"] == "repair-summary"
    assert mock_run.call_args.kwargs["extra_env"]["REPAIR_MODEL"] == get_repair_model()
    prompt = mock_run.call_args.kwargs["prompt"]
    assert "INVALID OUTPUT" in prompt
    assert "bad output" in prompt
    assert "1. [missing_evidence_pointers] No evidence pointers found." in prompt
    assert "file_ids: F0001" in prompt


def test_repair_artifact_skips_when_no_errors() -> None:
    manager = _DummyManager(Path("/workspace"))

    with patch("spec_manager.refinement.repair.run_agent") as mock_run:
        repaired, evidence = repair_artifact(
            output="ok",
            errors=[],
            allowlists={},
            artifact_type=ArtifactType.SUMMARY,
            model_override=get_repair_model(),
            manager=manager,
        )

    assert repaired == "ok"
    assert evidence == []
    mock_run.assert_not_called()


def test_repair_artifact_propagates_exception() -> None:
    manager = _DummyManager(Path("/workspace"))

    with (
        patch(
            "spec_manager.refinement.repair.run_agent",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError, match="boom"),
    ):
        repair_artifact(
            output="bad",
            errors=[{"type": "bad", "message": "oops"}],
            allowlists={},
            artifact_type=ArtifactType.SUMMARY,
            model_override=get_repair_model(),
            manager=manager,
        )


def test_build_repair_prompt_formats_errors_and_allowlists() -> None:
    errors = [
        {
            "type": "invalid_pointer",
            "message": "Pointer invalid.",
            "file_id": "F0001",
            "context": {"section": "INTRO"},
            "lines": ["line1", "line2"],
        }
    ]
    allowlists = {
        "file_ids": ["F0001", "F0002"],
        "sections": {"F0001": ["INTRO", "DETAILS"]},
    }

    prompt = _build_repair_prompt(
        output="bad",
        errors=errors,
        allowlists=allowlists,
        artifact_type=ArtifactType.SUMMARY,
    )

    assert "1. [invalid_pointer] Pointer invalid." in prompt
    assert "file_id=F0001" in prompt
    assert 'context={"section": "INTRO"}' in prompt
    assert 'lines=["line1", "line2"]' in prompt
    assert "file_ids: F0001, F0002" in prompt
    assert "- F0001: INTRO, DETAILS" in prompt


def test_format_allowlists_handles_nested_and_empty() -> None:
    allowlists = {
        "library_ids": [],
        "sections": {"F0001": ["INTRO"], "F0002": []},
    }

    formatted = _format_allowlists(allowlists)

    assert "library_ids: None" in formatted
    assert "sections:" in formatted
    assert "- F0001: INTRO" in formatted
    assert "- F0002: None" in formatted
