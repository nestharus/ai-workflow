from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.spec_refinement.workflows.formats import LibraryCharter
from scripts.spec_refinement.workflows.library_synthesis import synthesize_libraries
from scripts.spec_refinement.workspace import Phase, WorkspaceManager


def _setup_workspace(fs, monkeypatch, summarize: bool = True) -> WorkspaceManager:
    fs.create_dir("/repo")
    monkeypatch.chdir("/repo")
    input_dir = Path("/repo/specs")
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "a.md").write_text("## Intro\n[INTRO]\n", encoding="utf-8")
    manager = WorkspaceManager(run_id="run1", input_folder=input_dir)
    manager.initialize(force=True)

    if summarize:
        manager.start_phase(Phase.SUMMARIZATION)
        manager.complete_phase(Phase.SUMMARIZATION, outputs={"summaries_count": 1})
        summary_path = manager.structure.summaries_dir / "F0001.what.md"
        summary_path.write_text("# Summary\n", encoding="utf-8")

    return manager


def _charter(evidence_section: str = "INTRO") -> LibraryCharter:
    return LibraryCharter(
        lib_id="lib_001",
        intent="Core Workflow Library",
        boundaries="Includes orchestrator and runner coordination.",
        responsibilities=["Handle phase transitions", "Coordinate summaries"],
        evidence_sources=[{"file_id": "F0001", "sections": [evidence_section]}],
        overlap_resolutions=[{"description": "Workflow vs orchestration", "decision": "Assign"}],
    )


def test_synthesize_libraries_success(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    with (
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.label_all_files",
            return_value={
                "file_labels": {"F0001": {"candidate_labels": [], "uncertain_labels": []}}
            },
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.aggregate_labels",
            return_value={"label_clusters": [], "singleton_labels": [], "metadata": {}},
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.refine_library_labels",
            return_value=[{"lib_id": "lib_001", "final_label": "Core", "merged_from": []}],
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.generate_all_charters",
            return_value=[_charter()],
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.resolve_all_overlaps",
            return_value=[],
        ),
    ):
        result = synthesize_libraries("run1")

    libraries_dir = Path("/repo/runs/run1/libraries")
    assert (libraries_dir / "library_index.md").exists()

    lib_dir = libraries_dir / "lib_001"
    assert (lib_dir / "charter.md").exists()
    assert (lib_dir / "evidence.json").exists()
    assert (lib_dir / "gaps.md").exists()
    assert (lib_dir / "decisions.md").exists()

    assert result["libraries_created"] == 1


def test_synthesize_libraries_overlap_resolution_outputs(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    with (
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.label_all_files",
            return_value={
                "file_labels": {"F0001": {"candidate_labels": [], "uncertain_labels": []}}
            },
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.aggregate_labels",
            return_value={"label_clusters": [], "singleton_labels": [], "metadata": {}},
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.refine_library_labels",
            return_value=[{"lib_id": "lib_001", "final_label": "Core", "merged_from": []}],
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.generate_all_charters",
            return_value=[_charter()],
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.resolve_all_overlaps",
            return_value=[
                {
                    "lib_id_a": "lib_001",
                    "lib_id_b": "lib_002",
                    "decision": "assign_to_lib_A",
                    "rationale": "Overlap belongs to lib_001",
                    "affected_files": ["F0001"],
                    "overlap_score": 0.5,
                }
            ],
        ),
    ):
        result = synthesize_libraries("run1")

    outputs = result.get("outputs", {})
    assert "overlap_decisions" in outputs
    assert outputs["overlap_decisions"][0]["decision"] == "assign_to_lib_A"


def test_synthesize_libraries_evidence_validation(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch)

    with (
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.label_all_files",
            return_value={
                "file_labels": {"F0001": {"candidate_labels": [], "uncertain_labels": []}}
            },
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.aggregate_labels",
            return_value={"label_clusters": [], "singleton_labels": [], "metadata": {}},
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.refine_library_labels",
            return_value=[{"lib_id": "lib_001", "final_label": "Core", "merged_from": []}],
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.generate_all_charters",
            return_value=[_charter("UNKNOWN")],
        ),
        patch(
            "scripts.spec_refinement.workflows.library_synthesis.resolve_all_overlaps",
            return_value=[],
        ),
    ):
        result = synthesize_libraries("run1")

    assert any(issue["type"] == "unknown_section_reference" for issue in result["issues"])


def test_synthesize_libraries_phase_dependency(fs, monkeypatch) -> None:
    _setup_workspace(fs, monkeypatch, summarize=False)

    try:
        synthesize_libraries("run1")
    except RuntimeError as exc:
        assert "Summarization phase" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when summarization is incomplete")
