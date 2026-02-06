from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from spec_manager.refinement.workflows.library_structure_review import (
    _build_boundary_judge_prompt,
    _build_split_planner_prompt,
    _judge_boundary_overlap,
    _plan_library_split,
    _validate_boundary_judge_output,
    _validate_split_planner_output,
)
from spec_manager.refinement.workspace import WorkspaceManager


def _setup_workspace(fs, monkeypatch, run_id: str = "run_001") -> WorkspaceManager:
    base = Path("/work")
    fs.create_dir(base)
    specs_dir = base / "specs"
    fs.create_dir(specs_dir)
    (specs_dir / "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    monkeypatch.chdir(base)

    manager = WorkspaceManager(run_id=run_id, input_folder=Path("specs"))
    issues = manager.initialize(force=True)
    assert issues == []
    return manager


def test_boundary_judge_prompt_structure() -> None:
    prompt = _build_boundary_judge_prompt(
        lib_a_id="LIB-0001",
        lib_b_id="LIB-0002",
        charter_a="Intent A. Responsibilities A.",
        charter_b="Intent B. Responsibilities B.",
        matched_elements=[
            {
                "element_a_id": "DTL-LIB-0001-0001",
                "element_a_text": "Handles intake and routing.",
                "element_b_id": "DTL-LIB-0002-0001",
                "element_b_text": "Routes requests into processing.",
                "similarity": 0.72,
            }
        ],
        architecture_context="Component map context.",
    )

    assert prompt.startswith("## OUTPUT CONTRACT (REQUIRED)")
    assert '"action": "merge|keep_separate|move_elements"' in prompt
    assert "Matched Elements (top 10):" in prompt
    assert "Pair 1: A DTL-LIB-0001-0001" in prompt
    assert "similarity=0.72" in prompt


def test_split_planner_prompt_structure() -> None:
    prompt = _build_split_planner_prompt(
        lib_id="LIB-0003",
        charter="Own ingestion and transformation responsibilities.",
        spec_excerpt="## Details\n- Must normalize input.\n\n## Constraints\n- Preserve IDs.",
        cluster_assignments={
            "DTL-LIB-0003-0001": 0,
            "CON-LIB-0003-0002": 0,
            "DTL-LIB-0003-0003": 1,
        },
        silhouette_score=0.42,
        num_clusters=2,
    )

    assert prompt.startswith("## OUTPUT CONTRACT (REQUIRED)")
    assert "Termination criteria" in prompt
    assert "Silhouette score: 0.420" in prompt
    assert "- Cluster 0" in prompt
    assert "- Cluster 1" in prompt
    assert "DTL-LIB-0003-0001" in prompt


def test_boundary_judge_output_validation() -> None:
    valid_merge = {
        "action": "merge",
        "rationale": "Overlap is substantial [LIB-0001::spec.md::DTL-LIB-0001-0001].",
        "elements_to_move": [],
        "target_lib": "LIB-0001",
        "confidence": 0.7,
    }
    valid_keep = {
        "action": "keep_separate",
        "rationale": "Intents differ [LIB-0002::charter.md].",
        "elements_to_move": [],
        "target_lib": "LIB-0002",
        "confidence": 0.55,
    }
    valid_move = {
        "action": "move_elements",
        "rationale": "Move the shared intake detail [LIB-0001::spec.md::DTL-LIB-0001-0001].",
        "elements_to_move": ["DTL-LIB-0001-0001"],
        "target_lib": "LIB-0002",
        "confidence": 0.82,
    }

    assert _validate_boundary_judge_output(valid_merge, "LIB-0001", "LIB-0002") == []
    assert _validate_boundary_judge_output(valid_keep, "LIB-0001", "LIB-0002") == []
    assert _validate_boundary_judge_output(valid_move, "LIB-0001", "LIB-0002") == []

    missing_action = {
        "rationale": "Missing action [LIB-0001::charter.md].",
        "confidence": 0.5,
    }
    invalid_element = {
        "action": "move_elements",
        "rationale": "Bad element id [LIB-0002::spec.md::DTL-LIB-0002-0001].",
        "elements_to_move": ["BAD-ID"],
        "target_lib": "LIB-0002",
        "confidence": 0.4,
    }

    assert _validate_boundary_judge_output(missing_action, "LIB-0001", "LIB-0002")
    assert _validate_boundary_judge_output(invalid_element, "LIB-0001", "LIB-0002")


def test_boundary_judge_rationale_citation_validation() -> None:
    no_citation = {
        "action": "merge",
        "rationale": "Overlap is substantial but no citation provided.",
        "elements_to_move": [],
        "target_lib": "LIB-0001",
        "confidence": 0.7,
    }
    errors = _validate_boundary_judge_output(no_citation, "LIB-0001", "LIB-0002")
    assert any("rationale must contain at least one citation" in e for e in errors)

    malformed_citation = {
        "action": "merge",
        "rationale": "Overlap [LIB-0001::spec.md] without element ID.",
        "elements_to_move": [],
        "target_lib": "LIB-0001",
        "confidence": 0.7,
    }
    errors = _validate_boundary_judge_output(malformed_citation, "LIB-0001", "LIB-0002")
    assert any("rationale must contain at least one citation" in e for e in errors)

    with_spec_citation = {
        "action": "keep_separate",
        "rationale": "See [LIB-0001::spec.md::CON-LIB-0001-0003] for constraint.",
        "elements_to_move": [],
        "target_lib": "LIB-0001",
        "confidence": 0.6,
    }
    assert _validate_boundary_judge_output(with_spec_citation, "LIB-0001", "LIB-0002") == []

    with_charter_citation = {
        "action": "keep_separate",
        "rationale": "Charter scopes differ [LIB-0002::charter.md].",
        "elements_to_move": [],
        "target_lib": "LIB-0001",
        "confidence": 0.6,
    }
    assert _validate_boundary_judge_output(with_charter_citation, "LIB-0001", "LIB-0002") == []

    with_detail_citation = {
        "action": "merge",
        "rationale": "Detail overlap [LIB-0001::spec.md::DTL-LIB-0001-0001].",
        "elements_to_move": [],
        "target_lib": "LIB-0001",
        "confidence": 0.7,
    }
    assert _validate_boundary_judge_output(with_detail_citation, "LIB-0001", "LIB-0002") == []

    with_analysis_citation = {
        "action": "merge",
        "rationale": "Analysis conflict [LIB-0001::spec.md::ANL-LIB-0001-0001].",
        "elements_to_move": [],
        "target_lib": "LIB-0001",
        "confidence": 0.7,
    }
    assert _validate_boundary_judge_output(with_analysis_citation, "LIB-0001", "LIB-0002") == []


def test_split_planner_output_validation() -> None:
    valid_output = {
        "split_groups": [
            {
                "group_id": 0,
                "proposed_name": "Intake",
                "charter_summary": "Own intake.",
                "element_ids": [
                    "DTL-LIB-0001-0001",
                    "DTL-LIB-0001-0002",
                    "CON-LIB-0001-0003",
                ],
                "justification": "Distinct intake details [LIB-0001::spec.md::DTL-LIB-0001-0001].",
            },
            {
                "group_id": 1,
                "proposed_name": "Processing",
                "charter_summary": "Own processing.",
                "element_ids": [
                    "DTL-LIB-0001-0004",
                    "DTL-LIB-0001-0005",
                    "CON-LIB-0001-0006",
                ],
                "justification": "Distinct processing details [LIB-0001::spec.md::DTL-LIB-0001-0004].",
            },
        ],
        "interface_notes": "Intake hands off to processing.",
        "confidence": 0.61,
    }
    empty_output = {
        "split_groups": [],
        "interface_notes": "",
        "confidence": 0.33,
    }
    invalid_output = {
        "split_groups": [
            {
                "group_id": 0,
                "proposed_name": "Too Small",
                "charter_summary": "Too few elements.",
                "element_ids": ["DTL-LIB-0001-0001", "BAD"],
                "justification": "Not enough evidence.",
            }
        ],
        "interface_notes": "",
        "confidence": 1.2,
    }

    assert _validate_split_planner_output(valid_output, "LIB-0001") == []
    assert _validate_split_planner_output(empty_output, "LIB-0001") == []
    assert _validate_split_planner_output(invalid_output, "LIB-0001")


def test_split_planner_justification_citation_validation() -> None:
    no_citation = {
        "split_groups": [
            {
                "group_id": 0,
                "proposed_name": "Intake",
                "charter_summary": "Own intake.",
                "element_ids": [
                    "DTL-LIB-0001-0001",
                    "DTL-LIB-0001-0002",
                    "CON-LIB-0001-0003",
                ],
                "justification": "Distinct intake details without any citation.",
            }
        ],
        "interface_notes": "",
        "confidence": 0.5,
    }
    errors = _validate_split_planner_output(no_citation, "LIB-0001")
    assert any("justification must contain at least one citation" in e for e in errors)

    malformed_citation = {
        "split_groups": [
            {
                "group_id": 0,
                "proposed_name": "Intake",
                "charter_summary": "Own intake.",
                "element_ids": [
                    "DTL-LIB-0001-0001",
                    "DTL-LIB-0001-0002",
                    "CON-LIB-0001-0003",
                ],
                "justification": "See [LIB-0001::spec.md] for details.",
            }
        ],
        "interface_notes": "",
        "confidence": 0.5,
    }
    errors = _validate_split_planner_output(malformed_citation, "LIB-0001")
    assert any("justification must contain at least one citation" in e for e in errors)

    with_charter_citation = {
        "split_groups": [
            {
                "group_id": 0,
                "proposed_name": "Intake",
                "charter_summary": "Own intake.",
                "element_ids": [
                    "DTL-LIB-0001-0001",
                    "DTL-LIB-0001-0002",
                    "CON-LIB-0001-0003",
                ],
                "justification": "Charter scope supports split [LIB-0001::charter.md].",
            }
        ],
        "interface_notes": "",
        "confidence": 0.5,
    }
    assert _validate_split_planner_output(with_charter_citation, "LIB-0001") == []

    with_constraint_citation = {
        "split_groups": [
            {
                "group_id": 0,
                "proposed_name": "Intake",
                "charter_summary": "Own intake.",
                "element_ids": [
                    "DTL-LIB-0001-0001",
                    "DTL-LIB-0001-0002",
                    "CON-LIB-0001-0003",
                ],
                "justification": "Constraint boundary [LIB-0001::spec.md::CON-LIB-0001-0003].",
            }
        ],
        "interface_notes": "",
        "confidence": 0.5,
    }
    assert _validate_split_planner_output(with_constraint_citation, "LIB-0001") == []

    with_detail_citation = {
        "split_groups": [
            {
                "group_id": 0,
                "proposed_name": "Intake",
                "charter_summary": "Own intake.",
                "element_ids": [
                    "DTL-LIB-0001-0001",
                    "DTL-LIB-0001-0002",
                    "CON-LIB-0001-0003",
                ],
                "justification": "Detail isolation [LIB-0001::spec.md::DTL-LIB-0001-0001].",
            }
        ],
        "interface_notes": "",
        "confidence": 0.5,
    }
    assert _validate_split_planner_output(with_detail_citation, "LIB-0001") == []


def test_agent_invocation_with_mocks(fs, monkeypatch) -> None:
    manager = _setup_workspace(fs, monkeypatch)

    lib_a_dir = manager.structure.libraries_dir / "LIB-0001"
    lib_b_dir = manager.structure.libraries_dir / "LIB-0002"
    lib_a_dir.mkdir(parents=True)
    lib_b_dir.mkdir(parents=True)
    (lib_a_dir / "charter.md").write_text("Charter A.", encoding="utf-8")
    (lib_b_dir / "charter.md").write_text("Charter B.", encoding="utf-8")
    (lib_a_dir / "spec.md").write_text(
        "## Details\n- Must intake.\n\n## Constraints\n- Preserve IDs.",
        encoding="utf-8",
    )

    overlap_candidate = {
        "lib_a": "LIB-0001",
        "lib_b": "LIB-0002",
        "matched_elements": [
            {
                "element_a_id": "DTL-LIB-0001-0001",
                "element_a_text": "Handles intake.",
                "element_b_id": "DTL-LIB-0002-0001",
                "element_b_text": "Handles intake.",
                "similarity": 0.8,
            }
        ],
    }
    split_candidate = {
        "lib_id": "LIB-0001",
        "cluster_assignments": {
            "DTL-LIB-0001-0001": 0,
            "DTL-LIB-0001-0002": 0,
            "CON-LIB-0001-0003": 0,
        },
        "silhouette_score": 0.55,
        "num_clusters": 2,
    }

    boundary_output = {
        "action": "merge",
        "rationale": "Overlap is strong [LIB-0001::spec.md::DTL-LIB-0001-0001].",
        "elements_to_move": [],
        "target_lib": "LIB-0001",
        "confidence": 0.74,
    }
    split_output = {
        "split_groups": [
            {
                "group_id": 0,
                "proposed_name": "Intake",
                "charter_summary": "Own intake.",
                "element_ids": [
                    "DTL-LIB-0001-0001",
                    "DTL-LIB-0001-0002",
                    "CON-LIB-0001-0003",
                ],
                "justification": "Distinct intake details [LIB-0001::spec.md::DTL-LIB-0001-0001].",
            }
        ],
        "interface_notes": "",
        "confidence": 0.66,
    }

    with patch(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        side_effect=[json.dumps(boundary_output), json.dumps(split_output)],
    ) as mock_run_agent:
        boundary_result = _judge_boundary_overlap(
            overlap_candidate, manager, architecture_context="Context."
        )
        split_result = _plan_library_split(split_candidate, manager)

    assert boundary_result["action"] == "merge"
    assert split_result["split_groups"][0]["group_id"] == 0

    boundary_prompt = mock_run_agent.call_args_list[0].kwargs["prompt"]
    split_prompt = mock_run_agent.call_args_list[1].kwargs["prompt"]
    assert boundary_prompt.startswith("## OUTPUT CONTRACT (REQUIRED)")
    assert "Library A ID: LIB-0001" in boundary_prompt
    assert "Cluster assignments:" in split_prompt
