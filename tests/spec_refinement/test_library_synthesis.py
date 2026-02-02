from __future__ import annotations

import json
from pathlib import Path

from spec_manager.refinement.workflows.library_synthesis import synthesize_libraries
from spec_manager.refinement.workspace import Phase, WorkspaceManager


def _setup_workspace(fs, monkeypatch, run_id: str = "run_001") -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    specs_dir = base / "specs"
    fs.create_dir(specs_dir)
    (specs_dir / "alpha.md").write_text("# Alpha\n\n## Intro\nA\n", encoding="utf-8")
    (specs_dir / "beta.md").write_text("# Beta\n\n## Intro\nB\n", encoding="utf-8")
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("specs"))
    issues = manager.initialize(force=True)
    assert issues == []

    manager.start_phase(Phase.SUMMARIZATION)
    manager.complete_phase(Phase.SUMMARIZATION, outputs={"summaries_count": 2})

    (manager.structure.summaries_dir / "F0001.what.md").write_text(
        "# Summary\nEvidence: [F0001::INTRO]\n", encoding="utf-8"
    )
    (manager.structure.summaries_dir / "F0002.what.md").write_text(
        "# Summary\nEvidence: [F0002::INTRO]\n", encoding="utf-8"
    )

    return manager


def _library_output(lib_id: str, evidence_file: str) -> str:
    return (
        "## Library Index\n"
        f"- {lib_id}: Core Workflow Library\n\n"
        "## Library Charters\n"
        f"### {lib_id}\n"
        "#### Intent\n"
        "Own core workflow responsibilities.\n\n"
        "#### Boundaries\n"
        "Includes orchestrator and runner coordination.\n\n"
        "#### Responsibilities\n"
        "- Handle phase transitions\n\n"
        "#### Evidence\n"
        f"- [{evidence_file}::INTRO]\n\n"
        "#### Overlap Resolutions\n"
        "- Workflow vs orchestration -> Assign to lib_001\n"
    )


def _run_agent_success(
    *, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2
) -> str:
    if agent_name == "glm-file-library-labeler":
        label = "Alpha" if "F0001" in prompt else "Beta"
        return json.dumps(
            {
                "candidate_labels": [
                    {
                        "label": label,
                        "sections": ["[F0001::INTRO]"] if label == "Alpha" else ["[F0002::INTRO]"],
                        "confidence": 0.8,
                        "rationale": "Matches the summary.",
                    }
                ],
                "uncertain_labels": [],
            }
        )
    if agent_name == "opus-library-label-refiner":
        return json.dumps(
            [
                {
                    "lib_id": "lib_001",
                    "final_label": "Alpha",
                    "merged_from": ["Alpha"],
                    "split_notes": "",
                    "stable_internal_id": "lib_001",
                },
                {
                    "lib_id": "lib_002",
                    "final_label": "Beta",
                    "merged_from": ["Beta"],
                    "split_notes": "",
                    "stable_internal_id": "lib_002",
                },
            ]
        )
    if agent_name == "opus-library-synthesizer":
        lib_id = "lib_002" if "lib_002" in prompt else "lib_001"
        evidence_file = "F0001"
        return _library_output(lib_id, evidence_file)
    if agent_name == "glm-library-overlap-resolver":
        return json.dumps(
            {
                "decision": "assign_to_lib_A",
                "rationale": "Overlap belongs to library A.",
                "affected_files": ["F0001"],
            }
        )
    raise AssertionError(f"Unexpected agent: {agent_name}")


def test_synthesize_libraries_end_to_end_success(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_labeling.run_agent",
        _run_agent_success,
    )

    result = synthesize_libraries("run_001")

    libraries_dir = Path("/work/runs/run_001/libraries")
    assert (libraries_dir / "library_index.md").exists()
    assert (libraries_dir / "lib_001" / "charter.md").exists()
    assert (libraries_dir / "lib_002" / "charter.md").exists()

    assert result["libraries_created"] == 2
    outputs = result.get("outputs", {})
    assert outputs["libraries_count"] == 2
    assert "overlap_decisions" in outputs

    state = WorkspaceManager(run_id="run_001", input_folder=Path("specs")).state
    assert state.phases[Phase.LIBRARY_SYNTHESIS.value].status.value == "completed"


def test_synthesize_libraries_invalid_labels(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    def _run_agent_invalid_labels(
        *, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2
    ) -> str:
        if agent_name == "glm-file-library-labeler":
            return json.dumps(
                {
                    "candidate_labels": [
                        {
                            "label": "Alpha",
                            "sections": ["[F0001::INTRO]"],
                            "confidence": 0.8,
                            "rationale": "Matches.",
                        }
                    ],
                    "uncertain_labels": [],
                }
            )
        if agent_name == "opus-library-label-refiner":
            return json.dumps(
                [
                    {
                        "lib_id": "lib_bad",
                        "final_label": "Alpha",
                        "merged_from": ["Alpha"],
                        "split_notes": "",
                        "stable_internal_id": "lib_bad",
                    }
                ]
            )
        if agent_name == "opus-library-synthesizer":
            return _library_output("lib_001", "F0001")
        if agent_name == "glm-library-overlap-resolver":
            return json.dumps(
                {
                    "decision": "assign_to_lib_A",
                    "rationale": "Overlap belongs to library A.",
                    "affected_files": ["F0001"],
                }
            )
        raise AssertionError(f"Unexpected agent: {agent_name}")

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_labeling.run_agent",
        _run_agent_invalid_labels,
    )

    result = synthesize_libraries("run_001")

    assert result["libraries_created"] == 0
    assert result["issues"][0]["type"] == "label_refinement_failed"


def test_synthesize_libraries_overlap_resolution_failure(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    def _run_agent_overlap_failure(
        *, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2
    ) -> str:
        if agent_name == "glm-file-library-labeler":
            return json.dumps(
                {
                    "candidate_labels": [
                        {
                            "label": "Alpha",
                            "sections": ["[F0001::INTRO]"],
                            "confidence": 0.8,
                            "rationale": "Matches.",
                        }
                    ],
                    "uncertain_labels": [],
                }
            )
        if agent_name == "opus-library-label-refiner":
            return json.dumps(
                [
                    {
                        "lib_id": "lib_001",
                        "final_label": "Alpha",
                        "merged_from": ["Alpha"],
                        "split_notes": "",
                        "stable_internal_id": "lib_001",
                    },
                    {
                        "lib_id": "lib_002",
                        "final_label": "Beta",
                        "merged_from": ["Beta"],
                        "split_notes": "",
                        "stable_internal_id": "lib_002",
                    },
                ]
            )
        if agent_name == "opus-library-synthesizer":
            lib_id = "lib_002" if "lib_002" in prompt else "lib_001"
            return _library_output(lib_id, "F0001")
        if agent_name == "glm-library-overlap-resolver":
            return "not-json"
        raise AssertionError(f"Unexpected agent: {agent_name}")

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_labeling.run_agent",
        _run_agent_overlap_failure,
    )

    result = synthesize_libraries("run_001")

    assert any(issue["type"] == "overlap_resolution_failed" for issue in result["issues"])


def test_synthesize_libraries_charter_generation_error(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    def _run_agent_bad_charter(
        *, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2
    ) -> str:
        if agent_name == "glm-file-library-labeler":
            return json.dumps(
                {
                    "candidate_labels": [
                        {
                            "label": "Alpha",
                            "sections": ["[F0001::INTRO]"],
                            "confidence": 0.8,
                            "rationale": "Matches.",
                        }
                    ],
                    "uncertain_labels": [],
                }
            )
        if agent_name == "opus-library-label-refiner":
            return json.dumps(
                [
                    {
                        "lib_id": "lib_001",
                        "final_label": "Alpha",
                        "merged_from": ["Alpha"],
                        "split_notes": "",
                        "stable_internal_id": "lib_001",
                    }
                ]
            )
        if agent_name == "opus-library-synthesizer":
            return "bad output"
        if agent_name == "glm-library-overlap-resolver":
            return json.dumps(
                {
                    "decision": "assign_to_lib_A",
                    "rationale": "Overlap belongs to library A.",
                    "affected_files": ["F0001"],
                }
            )
        raise AssertionError(f"Unexpected agent: {agent_name}")

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_labeling.run_agent",
        _run_agent_bad_charter,
    )

    result = synthesize_libraries("run_001")

    assert result["libraries_created"] == 0
    assert any(issue["type"] == "parse_error" for issue in result["issues"])
