from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.spec_refinement.workflows.formats import LibraryCharter
from scripts.spec_refinement.workflows.library_labeling import (
    aggregate_labels,
    detect_overlaps,
    generate_library_charter,
    label_file_to_libraries,
    refine_library_labels,
    resolve_overlap,
)
from scripts.spec_refinement.workspace import WorkspaceManager


def _setup_workspace(fs, monkeypatch, run_id: str = "run_001") -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    specs_dir = base / "specs"
    fs.create_dir(specs_dir)
    (specs_dir / "alpha.md").write_text(
        "# Alpha\n\n## Intro\nDetails.\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("specs"))
    issues = manager.initialize(force=True)
    assert issues == []
    summary_path = manager.structure.summaries_dir / "F0001.what.md"
    summary_path.write_text("# Summary\n", encoding="utf-8")
    return manager


def _library_output(evidence_section: str = "INTRO") -> str:
    return (
        "## Library Index\n"
        "- lib_001: Core Workflow Library\n\n"
        "## Library Charters\n"
        "### lib_001\n"
        "#### Intent\n"
        "Own core workflow responsibilities.\n\n"
        "#### Boundaries\n"
        "Includes orchestrator and runner coordination.\n\n"
        "#### Responsibilities\n"
        "- Handle phase transitions\n\n"
        "#### Evidence\n"
        f"- [F0001::{evidence_section}]\n\n"
        "#### Overlap Resolutions\n"
        "- Workflow vs orchestration -> Assign to lib_001\n"
    )


def test_label_file_to_libraries_parses_json(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    summary_path = manager.structure.summaries_dir / "F0001.what.md"

    payload = {
        "file_id": "F0001",
        "candidate_labels": [
            {
                "label": "Request Intake",
                "sections": ["[F0001::INTRO]"],
                "confidence": 0.8,
                "rationale": "Direct mention of intake responsibilities.",
            }
        ],
        "uncertain_labels": [],
    }

    with patch(
        "scripts.spec_refinement.workflows.library_labeling.run_agent",
        return_value=json.dumps(payload),
    ):
        result = label_file_to_libraries("F0001", summary_path, manager)

    assert result["candidate_labels"][0]["label"] == "Request Intake"
    assert result["uncertain_labels"] == []


def test_label_file_to_libraries_repairs_invalid_json(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    summary_path = manager.structure.summaries_dir / "F0001.what.md"

    repaired_payload = {
        "file_id": "F0001",
        "candidate_labels": [],
        "uncertain_labels": [{"label": "Rate Limiting", "rationale": "Unclear."}],
    }

    with (
        patch(
            "scripts.spec_refinement.workflows.library_labeling.run_agent",
            return_value="not-json",
        ),
        patch(
            "scripts.spec_refinement.workflows.library_labeling.repair_artifact",
            return_value=json.dumps(repaired_payload),
        ) as mock_repair,
    ):
        result = label_file_to_libraries("F0001", summary_path, manager)

    assert mock_repair.called
    assert result["uncertain_labels"][0]["label"] == "Rate Limiting"


def test_aggregate_labels_clusters_by_similarity() -> None:
    file_labels = {
        "F0001": {
            "candidate_labels": [
                {"label": "Core", "sections": ["[F0001::INTRO]"]},
                {"label": "Workflow", "sections": ["[F0001::INTRO]"]},
            ],
            "uncertain_labels": [],
        },
        "F0002": {
            "candidate_labels": [{"label": "Workflow", "sections": ["[F0002::INTRO]"]}],
            "uncertain_labels": [],
        },
    }

    aggregated = aggregate_labels(file_labels)

    clusters = aggregated["label_clusters"]
    assert len(clusters) == 1
    assert set(clusters[0]["labels"]) == {"Core", "Workflow"}


def test_refine_library_labels_writes_output(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)
    label_clusters = {"label_clusters": [], "singleton_labels": [], "metadata": {}}

    with patch(
        "scripts.spec_refinement.workflows.library_labeling.run_agent",
        return_value=json.dumps(
            [
                {
                    "lib_id": "lib_001",
                    "final_label": "Core",
                    "merged_from": ["Core"],
                    "split_notes": "",
                    "stable_internal_id": "lib_001",
                }
            ]
        ),
    ):
        result = refine_library_labels(label_clusters, manager)

    refined_path = manager.structure.libraries_dir / "refined_labels.json"
    assert refined_path.exists()
    assert result[0]["lib_id"] == "lib_001"


def test_generate_library_charter_uses_repair_gate(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    lib_def = {"lib_id": "lib_001", "final_label": "Core", "merged_from": ["Core"]}
    file_labels = {
        "F0001": {
            "candidate_labels": [{"label": "Core", "sections": ["[F0001::INTRO]"]}],
            "uncertain_labels": [],
        }
    }
    summaries = {"F0001": "# Summary"}

    with (
        patch(
            "scripts.spec_refinement.workflows.library_labeling.run_agent",
            return_value=_library_output("UNKNOWN"),
        ),
        patch(
            "scripts.spec_refinement.workflows.library_labeling.repair_artifact",
            return_value=_library_output("INTRO"),
        ) as mock_repair,
    ):
        result = generate_library_charter(lib_def, file_labels, summaries, manager)

    assert mock_repair.called
    charter = result["charter"]
    assert isinstance(charter, LibraryCharter)
    assert charter.evidence_sources[0]["sections"] == ["INTRO"]


def test_detect_overlaps_scores_pairs() -> None:
    charters = [
        LibraryCharter(
            lib_id="lib_001",
            intent="A",
            boundaries="",
            responsibilities=[],
            evidence_sources=[{"file_id": "F0001", "sections": ["INTRO"]}],
            overlap_resolutions=[],
        ),
        LibraryCharter(
            lib_id="lib_002",
            intent="B",
            boundaries="",
            responsibilities=[],
            evidence_sources=[{"file_id": "F0001", "sections": ["INTRO"]}],
            overlap_resolutions=[],
        ),
    ]

    overlaps = detect_overlaps(charters)
    assert overlaps[0][0] == "lib_001"
    assert overlaps[0][1] == "lib_002"
    assert overlaps[0][2] > 0.3


def test_resolve_overlap_parses_output(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    charters = {
        "lib_001": LibraryCharter(
            lib_id="lib_001",
            intent="A",
            boundaries="",
            responsibilities=[],
            evidence_sources=[{"file_id": "F0001", "sections": ["INTRO"]}],
            overlap_resolutions=[],
        ),
        "lib_002": LibraryCharter(
            lib_id="lib_002",
            intent="B",
            boundaries="",
            responsibilities=[],
            evidence_sources=[{"file_id": "F0001", "sections": ["INTRO"]}],
            overlap_resolutions=[],
        ),
    }

    with patch(
        "scripts.spec_refinement.workflows.library_labeling.run_agent",
        return_value=json.dumps(
            {
                "decision": "assign_to_lib_A",
                "rationale": "A owns the shared files.",
                "affected_files": ["F0001"],
            }
        ),
    ):
        result = resolve_overlap("lib_001", "lib_002", charters, manager, overlap_score=0.5)

    assert result["decision"] == "assign_to_lib_A"
