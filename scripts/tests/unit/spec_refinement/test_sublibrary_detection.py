from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from spec_manager.refinement.workflows.sublibrary_detection import (
    _build_sublibrary_spec,
    _recursive_refinement,
    detect_sublibraries,
)
from spec_manager.refinement.workspace import Phase, WorkspaceManager


def _fake_run_agent(output: str):
    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return output

    return _run_agent


def _setup_workspace(fs, monkeypatch, complete_spec: bool = True) -> tuple[WorkspaceManager, Path]:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")
    manager = WorkspaceManager(run_id="run1", input_folder=input_dir)
    manager.initialize(force=True)

    if complete_spec:
        manager.start_phase(Phase.SPEC_BUILDING)
        manager.complete_phase(Phase.SPEC_BUILDING, outputs={"libraries_built": 1})

    lib_dir = manager.structure.libraries_dir / "lib_001"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "charter.md").write_text(
        "# Library Charter: lib_001\n\n## Intent\nTest\n\n## Boundaries\nTest\n\n"
        "## Responsibilities\n- A\n",
        encoding="utf-8",
    )
    (lib_dir / "spec.md").write_text("# Library Spec: lib_001\n", encoding="utf-8")
    (lib_dir / "evidence.json").write_text(json.dumps({"sources": []}), encoding="utf-8")
    return manager, lib_dir


def _sublibrary_output(overlap: bool = False) -> str:
    if overlap:
        payload = {
            "sub_libraries": [
                {
                    "sub_lib_id": "sub_001",
                    "charter": {
                        "intent": "One",
                        "boundaries": "A",
                        "responsibilities": ["Alpha"],
                    },
                    "evidence_partition": ["F0001::INTRO", "F0001::DETAILS"],
                    "interface_impact": "Calls B",
                    "justification": "Separates capability A",
                },
                {
                    "sub_lib_id": "sub_002",
                    "charter": {
                        "intent": "Two",
                        "boundaries": "B",
                        "responsibilities": ["Beta"],
                    },
                    "evidence_partition": ["F0001::INTRO"],
                    "interface_impact": "Consumes A",
                    "justification": "Separates capability B",
                },
            ]
        }
    else:
        payload = {
            "sub_libraries": [
                {
                    "sub_lib_id": "sub_001",
                    "charter": {
                        "intent": "Sub capability",
                        "boundaries": "Isolated workflow",
                        "responsibilities": ["Do thing"],
                    },
                    "evidence_partition": ["F0001::INTRO"],
                    "interface_impact": "Exposes a clean API",
                    "justification": "Improves maintainability",
                }
            ]
        }
    return json.dumps(payload)


def test_detect_sublibraries_creates_subdir(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    with patch(
        "spec_manager.refinement.workflows.sublibrary_detection.run_agent",
        side_effect=_fake_run_agent(_sublibrary_output()),
    ):
        result = detect_sublibraries("run1", max_depth=1)

    sub_dir = Path("/repo/runs/run1/libraries/lib_001/sublibraries/sub_001")
    assert sub_dir.exists()
    assert (sub_dir / "charter.md").exists()
    assert (sub_dir / "evidence.json").exists()
    assert (sub_dir / "interface_notes.md").exists()
    assert result["sublibraries_created"] == 1


def test_detect_sublibraries_requires_spec_building(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch, complete_spec=False)

    try:
        detect_sublibraries("run1", max_depth=1)
    except RuntimeError as exc:
        assert "Spec building must be completed" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when spec building is incomplete")


def test_sublibrary_overlap_validation_skips_creation(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    with patch(
        "spec_manager.refinement.workflows.sublibrary_detection.run_agent",
        side_effect=_fake_run_agent(_sublibrary_output(overlap=True)),
    ):
        result = detect_sublibraries("run1", max_depth=1)

    assert result["sublibraries_created"] == 0
    assert any(issue["type"] == "evidence_overlap" for issue in result["issues"])

    sublibraries_dir = Path("/repo/runs/run1/libraries/lib_001/sublibraries")
    assert not sublibraries_dir.exists()


def test_recursive_refinement_respects_max_depth(fs, monkeypatch) -> None:
    manager, _ = _setup_workspace(fs, monkeypatch)

    with patch(
        "spec_manager.refinement.workflows.sublibrary_detection._find_sublibraries_at_depth",
        side_effect=AssertionError("Should not be called at max depth"),
    ):
        _recursive_refinement(manager, max_depth=1, current_depth=1)


def test_sublibrary_gap_isolated(fs, monkeypatch) -> None:
    manager, lib_dir = _setup_workspace(fs, monkeypatch)

    sub_lib_dir = lib_dir / "sublibraries" / "sub_001"
    sub_lib_dir.mkdir(parents=True, exist_ok=True)
    (sub_lib_dir / "charter.md").write_text(
        "# Sub-Library Charter: sub_001\n\n## Intent\nTest\n\n## Boundaries\nTest\n\n"
        "## Responsibilities\n- A\n",
        encoding="utf-8",
    )
    evidence_payload = {
        "sources": [
            {
                "file_id": "F0001",
                "sections": ["INTRO"],
                "confidence": 1.0,
                "rationale": "Seed",
            }
        ]
    }
    (sub_lib_dir / "evidence.json").write_text(
        json.dumps(evidence_payload, indent=2), encoding="utf-8"
    )

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        if agent_name == "glm-library-spec-integrator":
            return json.dumps(
                [
                    {
                        "op": "add",
                        "section": "Requirements",
                        "bullet_index": None,
                        "content": "Own keyword workflows",
                        "citations": ["[F0001::INTRO]"],
                    }
                ]
            )
        if agent_name == "chatgpt-library-spec-gap-judge":
            payload = {"gaps": [], "total_gaps": 0, "file_id": "F0001"}
            return json.dumps(payload)
        raise AssertionError(f"Unexpected agent: {agent_name}")

    with patch(
        "spec_manager.refinement.workflows.sublibrary_detection.run_agent",
        side_effect=_run_agent,
    ):
        _build_sublibrary_spec(manager, sub_lib_dir)

    assert (sub_lib_dir / "gaps.md").exists()
    assert not (Path("/repo/runs/run1/libraries/sub_001") / "gaps.md").exists()
