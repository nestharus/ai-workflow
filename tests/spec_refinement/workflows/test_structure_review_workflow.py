from __future__ import annotations

import json
from pathlib import Path

import pytest
from spec_manager.refinement.formats import LibraryEventType
from spec_manager.refinement.workflows.library_structure_review import (
    apply_move_actions,
    apply_split_actions,
    consolidate_proposals,
    detect_structure_issues,
    review_library_structure,
)
from spec_manager.refinement.workflows.library_synthesis import _read_library_events
from spec_manager.refinement.workflows.spec_stabilization import build_spec_index
from spec_manager.refinement.workspace import Phase
from spec_manager.schemas.review_actions import (
    ReviewAction,
    ReviewActionsReport,
    read_review_actions_json,
    write_review_actions_json,
)


def _complete_spec_stabilization(manager) -> None:
    manager.start_phase(Phase.SPEC_STABILIZATION)
    manager.complete_phase(Phase.SPEC_STABILIZATION, outputs={"specs": 1})


def _make_element(
    lib_id: str,
    index: int,
    *,
    kind: str = "requirement",
    text: str = "alpha",
) -> dict[str, str]:
    lib_suffix = lib_id.split("-", 1)[1]
    if kind == "requirement":
        element_id = f"REQ-LIB-{lib_suffix}-{index:04d}"
    elif kind == "invariant":
        element_id = f"INV-LIB-{lib_suffix}-{index:04d}"
    elif kind == "flow":
        element_id = f"FLOW-LIB-{lib_suffix}-{index:02d}"
    else:
        element_id = f"REQ-LIB-{lib_suffix}-{index:04d}"
    return {"element_id": element_id, "kind": kind, "text": text}


def _create_library_with_elements(
    manager,
    lib_id: str,
    elements: list[dict[str, str]],
    *,
    intent: str | None = None,
    evidence_sources: list[dict[str, object]] | None = None,
) -> Path:
    manager.state.register_library_id(lib_id)
    lib_dir = manager.structure.libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)

    file_id = next(iter(manager.state.file_manifest))
    relpath = manager.state.file_manifest[file_id]["relpath"]
    section_id = manager.state.section_manifest[file_id][0]
    spec_pointer = f"[spec_snapshot/{relpath}::{section_id}]"

    sections: dict[str, list[str]] = {
        "Requirements": [],
        "Flows": [],
        "Constraints": [],
        "Dependencies": [],
    }

    for element in elements:
        element_id = element["element_id"]
        text = element["text"]
        lib_pointer = f"[{lib_id}::spec.md::{element_id}]"
        line = f"- {element_id}: {text} {lib_pointer} {spec_pointer}"
        if element["kind"] == "requirement":
            sections["Requirements"].append(line)
        elif element["kind"] == "flow":
            sections["Flows"].append(line)
        elif element["kind"] == "invariant":
            sections["Constraints"].append(line)
        else:
            sections["Dependencies"].append(line)

    lines = [f"# Library Spec: {lib_id}", ""]
    for title in ["Requirements", "Flows", "Constraints", "Dependencies"]:
        lines.append(f"## {title}")
        if sections[title]:
            lines.extend(sections[title])
        else:
            lines.append("<!-- No elements assigned -->")
        lines.append("")

    spec_content = "\n".join(lines).rstrip() + "\n"
    (lib_dir / "spec.md").write_text(spec_content, encoding="utf-8")

    charter_intent = intent or f"Intent for {lib_id}"
    charter_content = "\n".join(
        [
            f"# Library Charter: {lib_id}",
            "",
            "## Intent",
            charter_intent,
            "",
            "## Boundaries",
            "Boundaries.",
            "",
            "## Responsibilities",
            "- None",
            "",
            "## Evidence",
            f"- {spec_pointer}",
            "",
            "## Overlap Resolutions",
            "- None",
            "",
        ]
    )
    (lib_dir / "charter.md").write_text(charter_content, encoding="utf-8")

    if evidence_sources is None:
        evidence_sources = [{"file_id": file_id, "sections": [section_id]}]
    evidence_payload = {"sources": evidence_sources}
    (lib_dir / "evidence.json").write_text(json.dumps(evidence_payload, indent=2), encoding="utf-8")

    spec_index = build_spec_index(spec_content, lib_id)
    (lib_dir / "spec_index.json").write_text(json.dumps(spec_index, indent=2), encoding="utf-8")

    return lib_dir


def _mock_boundary_judge(action: str, rationale: str, *, elements=None, target_lib=None) -> str:
    payload = {
        "action": action,
        "rationale": rationale,
        "elements_to_move": elements or [],
        "target_lib": target_lib or "LIB-0001",
        "confidence": 0.72,
    }
    return json.dumps(payload)


def _mock_split_planner(split_groups: list[dict[str, object]]) -> str:
    payload = {
        "split_groups": split_groups,
        "interface_notes": "Notes",
        "confidence": 0.62,
    }
    return json.dumps(payload)


def _write_review_actions_report(
    manager,
    actions: list[ReviewAction],
    *,
    thresholds: dict[str, float] | None = None,
) -> Path:
    report = ReviewActionsReport(
        run_id=manager.run_id,
        generated_at="2024-01-01T00:00:00",
        thresholds=thresholds or {"overlap_similarity": 0.35, "min_shared_elements": 5},
        actions=actions,
    )
    report_path = manager.structure.reports_dir / "review_actions.json"
    write_review_actions_json(report, report_path)
    return report_path


# Detection workflow tests


def test_detect_structure_issues_finds_overlaps(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements_a = [_make_element("LIB-0001", idx, text="shared alpha") for idx in range(1, 7)]
    elements_b = [_make_element("LIB-0002", idx, text="shared alpha") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements_a)
    _create_library_with_elements(manager, "LIB-0002", elements_b)

    results = detect_structure_issues(manager)

    assert results["overlap_candidates"]


def test_detect_structure_issues_finds_splits(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text="alpha group") for idx in range(1, 6)]
    elements += [_make_element("LIB-0001", idx + 5, text="beta group") for idx in range(1, 6)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    results = detect_structure_issues(manager)

    assert results["split_candidates"]


def test_detect_structure_issues_no_candidates(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements_a = [_make_element("LIB-0001", 1, text="alpha")]
    elements_b = [_make_element("LIB-0002", 1, text="beta")]
    _create_library_with_elements(manager, "LIB-0001", elements_a)
    _create_library_with_elements(manager, "LIB-0002", elements_b)

    results = detect_structure_issues(manager)

    assert results["overlap_candidates"] == []
    assert results["split_candidates"] == []


def test_detect_structure_issues_loads_architecture_context(
    spec_refinement_workspace, monkeypatch
) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements_a = [_make_element("LIB-0001", idx, text="shared alpha") for idx in range(1, 7)]
    elements_b = [_make_element("LIB-0002", idx, text="shared alpha") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements_a)
    _create_library_with_elements(manager, "LIB-0002", elements_b)

    arch_dir = manager.structure.architecture_dir
    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir / "selected.md").write_text("Selected context", encoding="utf-8")
    (arch_dir / "mapping.md").write_text("Mapping context", encoding="utf-8")

    captured: dict[str, str] = {}

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        captured["prompt"] = prompt
        return _mock_boundary_judge(
            "merge",
            "Overlap [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    detect_structure_issues(manager, consolidate=True)

    assert "Architecture Mapping Context" in captured["prompt"]
    assert "Selected context" in captured["prompt"]
    assert "Mapping context" in captured["prompt"]


# Agent integration tests


def test_boundary_judge_merge_decision(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements_a = [_make_element("LIB-0001", 1, text="shared alpha")]
    elements_b = [_make_element("LIB-0002", 1, text="shared alpha")]
    _create_library_with_elements(manager, "LIB-0001", elements_a)
    _create_library_with_elements(manager, "LIB-0002", elements_b)

    overlap_candidates = [
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0002",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [
                {
                    "element_a_id": "REQ-LIB-0001-0001",
                    "element_a_text": "shared alpha",
                    "element_b_id": "REQ-LIB-0002-0001",
                    "element_b_text": "shared alpha",
                    "similarity": 0.9,
                }
            ],
        }
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_boundary_judge(
            "merge",
            "Overlap [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    report = consolidate_proposals(manager, overlap_candidates, [], {"overlap_similarity": 0.35})

    assert report.actions[0].type == "merge"


def test_boundary_judge_keep_separate_decision(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements_a = [_make_element("LIB-0001", 1, text="shared alpha")]
    elements_b = [_make_element("LIB-0002", 1, text="shared alpha")]
    _create_library_with_elements(manager, "LIB-0001", elements_a)
    _create_library_with_elements(manager, "LIB-0002", elements_b)

    overlap_candidates = [
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0002",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        }
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_boundary_judge(
            "keep_separate",
            "No overlap [LIB-0001::charter.md].",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    report = consolidate_proposals(manager, overlap_candidates, [], {"overlap_similarity": 0.35})

    assert report.actions == []


def test_boundary_judge_move_elements_decision(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements_a = [_make_element("LIB-0001", 1, text="shared alpha")]
    elements_b = [_make_element("LIB-0002", 1, text="shared alpha")]
    _create_library_with_elements(manager, "LIB-0001", elements_a)
    _create_library_with_elements(manager, "LIB-0002", elements_b)

    overlap_candidates = [
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0002",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        }
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_boundary_judge(
            "move_elements",
            "Move element [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            elements=["REQ-LIB-0001-0001"],
            target_lib="LIB-0002",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    report = consolidate_proposals(manager, overlap_candidates, [], {"overlap_similarity": 0.35})

    assert report.actions[0].type == "move_elements"
    assert report.actions[0].elements == ["REQ-LIB-0001-0001"]


def test_split_planner_creates_split_action(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text="alpha") for idx in range(1, 6)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    split_candidates = [
        {
            "lib_id": "LIB-0001",
            "num_clusters": 2,
            "silhouette_score": 0.42,
            "cluster_assignments": {
                "REQ-LIB-0001-0001": 0,
                "REQ-LIB-0001-0002": 0,
                "REQ-LIB-0001-0003": 0,
            },
        }
    ]

    split_groups = [
        {
            "group_id": 0,
            "proposed_name": "Intake",
            "charter_summary": "Own intake",
            "element_ids": [
                "REQ-LIB-0001-0001",
                "REQ-LIB-0001-0002",
                "REQ-LIB-0001-0003",
            ],
            "justification": "Reason [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        }
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_split_planner(split_groups)

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    report = consolidate_proposals(manager, [], split_candidates, {"overlap_similarity": 0.35})

    assert report.actions[0].type == "split"


def test_split_planner_empty_output_no_action(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text="alpha") for idx in range(1, 6)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    split_candidates = [
        {
            "lib_id": "LIB-0001",
            "num_clusters": 2,
            "silhouette_score": 0.42,
            "cluster_assignments": {
                "REQ-LIB-0001-0001": 0,
                "REQ-LIB-0001-0002": 0,
                "REQ-LIB-0001-0003": 0,
            },
        }
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_split_planner([])

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    report = consolidate_proposals(manager, [], split_candidates, {"overlap_similarity": 0.35})

    assert report.actions == []


# Proposal consolidation tests


def test_consolidate_proposals_assigns_stable_ids(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    _create_library_with_elements(manager, "LIB-0001", [_make_element("LIB-0001", 1)])
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])
    _create_library_with_elements(manager, "LIB-0003", [_make_element("LIB-0003", 1)])

    overlap_candidates = [
        {
            "lib_a": "LIB-0002",
            "lib_b": "LIB-0003",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        },
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0002",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        },
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_boundary_judge(
            "merge",
            "Overlap [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    report = consolidate_proposals(manager, overlap_candidates, [], {"overlap_similarity": 0.35})

    assert [action.action_id for action in report.actions] == ["ACT-0001", "ACT-0002"]


def test_consolidate_proposals_validates_pointers(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    _create_library_with_elements(manager, "LIB-0001", [_make_element("LIB-0001", 1)])
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])

    overlap_candidates = [
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0002",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        }
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_boundary_judge(
            "merge",
            "Overlap [LIB-9999::spec.md::REQ-LIB-9999-0001].",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    report = consolidate_proposals(manager, overlap_candidates, [], {"overlap_similarity": 0.35})

    assert report.actions[0].status == "rejected"
    assert "Pointer validation failed" in (report.actions[0].notes or "")


def test_consolidate_proposals_merges_boundary_and_split(
    spec_refinement_workspace, monkeypatch
) -> None:
    manager, _manifest = spec_refinement_workspace()
    _create_library_with_elements(manager, "LIB-0001", [_make_element("LIB-0001", 1)])
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])

    overlap_candidates = [
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0002",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        }
    ]
    split_candidates = [
        {
            "lib_id": "LIB-0001",
            "num_clusters": 2,
            "silhouette_score": 0.42,
            "cluster_assignments": {
                "REQ-LIB-0001-0001": 0,
                "REQ-LIB-0001-0002": 0,
                "REQ-LIB-0001-0003": 0,
            },
        }
    ]

    split_groups = [
        {
            "group_id": 0,
            "proposed_name": "Intake",
            "charter_summary": "Own intake",
            "element_ids": [
                "REQ-LIB-0001-0001",
                "REQ-LIB-0001-0002",
                "REQ-LIB-0001-0003",
            ],
            "justification": "Reason [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        }
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        if agent_name == "chatgpt-library-boundary-judge":
            return _mock_boundary_judge(
                "merge",
                "Overlap [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            )
        if agent_name == "opus-library-split-planner":
            return _mock_split_planner(split_groups)
        raise AssertionError(f"Unexpected agent {agent_name}")

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    report = consolidate_proposals(
        manager, overlap_candidates, split_candidates, {"overlap_similarity": 0.35}
    )

    assert {action.type for action in report.actions} == {"merge", "split"}


def test_consolidate_proposals_sorts_actions_deterministically(
    spec_refinement_workspace, monkeypatch
) -> None:
    manager, _manifest = spec_refinement_workspace()
    _create_library_with_elements(manager, "LIB-0001", [_make_element("LIB-0001", 1)])
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])
    _create_library_with_elements(manager, "LIB-0003", [_make_element("LIB-0003", 1)])

    overlap_candidates = [
        {
            "lib_a": "LIB-0002",
            "lib_b": "LIB-0003",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        },
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0002",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        },
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_boundary_judge(
            "merge",
            "Overlap [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    first = consolidate_proposals(manager, overlap_candidates, [], {"overlap_similarity": 0.35})
    second = consolidate_proposals(
        manager,
        list(reversed(overlap_candidates)),
        [],
        {"overlap_similarity": 0.35},
    )

    first_ids = [action.action_id for action in first.actions]
    second_ids = [action.action_id for action in second.actions]
    assert first_ids == second_ids


# Report generation tests


def test_review_library_structure_writes_json(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    _complete_spec_stabilization(manager)

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        lambda **_: _mock_boundary_judge(
            "keep_separate",
            "No overlap [LIB-0001::charter.md].",
        ),
    )

    review_library_structure(manager.run_id)

    assert (manager.structure.reports_dir / "review_actions.json").exists()


def test_review_library_structure_writes_markdown(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    _complete_spec_stabilization(manager)

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        lambda **_: _mock_boundary_judge(
            "keep_separate",
            "No overlap [LIB-0001::charter.md].",
        ),
    )

    review_library_structure(manager.run_id)

    assert (manager.structure.reports_dir / "review_actions.md").exists()


def test_review_actions_json_contains_metadata(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    _complete_spec_stabilization(manager)

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        lambda **_: _mock_boundary_judge(
            "keep_separate",
            "No overlap [LIB-0001::charter.md].",
        ),
    )

    review_library_structure(manager.run_id)

    report = read_review_actions_json(manager.structure.reports_dir / "review_actions.json")
    assert report.run_id == manager.run_id
    assert "overlap_similarity" in report.thresholds


def test_review_actions_json_contains_actions(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements_a = [_make_element("LIB-0001", idx, text="shared alpha") for idx in range(1, 7)]
    elements_b = [_make_element("LIB-0002", idx, text="shared alpha") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements_a)
    _create_library_with_elements(manager, "LIB-0002", elements_b)
    _complete_spec_stabilization(manager)

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_boundary_judge(
            "merge",
            "Overlap [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    review_library_structure(manager.run_id)

    report = read_review_actions_json(manager.structure.reports_dir / "review_actions.json")
    assert report.actions


# Split application tests


def test_apply_single_split_creates_new_libraries(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "split",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": [],
            "elements": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002", "REQ-LIB-0001-0003"],
            "summary": "Intake - Handles intake",
            "rationale": "Split [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )
    report_path = _write_review_actions_report(manager, [action])

    summary = apply_split_actions(manager, report_path)

    assert summary["new_library_ids"]
    for lib_id in summary["new_library_ids"]:
        assert (manager.structure.libraries_dir / lib_id).exists()


def test_apply_single_split_partitions_elements(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "split",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": [],
            "elements": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002", "REQ-LIB-0001-0003"],
            "summary": "Intake - Handles intake",
            "rationale": "Split [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )
    report_path = _write_review_actions_report(manager, [action])

    summary = apply_split_actions(manager, report_path)

    new_lib_id = summary["new_library_ids"][0]
    new_spec = (manager.structure.libraries_dir / new_lib_id / "spec.md").read_text(
        encoding="utf-8"
    )
    assert f"REQ-{new_lib_id}" in new_spec

    source_spec = (manager.structure.libraries_dir / "LIB-0001" / "spec.md").read_text(
        encoding="utf-8"
    )
    assert "moved to" in source_spec


def test_apply_single_split_records_events(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "split",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": [],
            "elements": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002", "REQ-LIB-0001-0003"],
            "summary": "Intake - Handles intake",
            "rationale": "Split [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )
    report_path = _write_review_actions_report(manager, [action])

    summary = apply_split_actions(manager, report_path)

    source_events = _read_library_events(manager.structure.libraries_dir / "LIB-0001")
    assert any(event.event_type == LibraryEventType.LIBRARY_SPLIT for event in source_events)

    new_lib_id = summary["new_library_ids"][0]
    new_events = _read_library_events(manager.structure.libraries_dir / new_lib_id)
    assert any(event.event_type == LibraryEventType.LIBRARY_CREATED for event in new_events)


def test_apply_single_split_updates_specs(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "split",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": [],
            "elements": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002", "REQ-LIB-0001-0003"],
            "summary": "Intake - Handles intake",
            "rationale": "Split [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )
    report_path = _write_review_actions_report(manager, [action])

    summary = apply_split_actions(manager, report_path)
    new_lib_id = summary["new_library_ids"][0]

    new_spec = (manager.structure.libraries_dir / new_lib_id / "spec.md").read_text(
        encoding="utf-8"
    )
    assert "REQ-" in new_spec


def test_apply_single_split_updates_charters(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "split",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": [],
            "elements": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002", "REQ-LIB-0001-0003"],
            "summary": "Intake - Handles intake",
            "rationale": "Split [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )
    report_path = _write_review_actions_report(manager, [action])

    summary = apply_split_actions(manager, report_path)
    new_lib_id = summary["new_library_ids"][0]

    charter = (manager.structure.libraries_dir / new_lib_id / "charter.md").read_text(
        encoding="utf-8"
    )
    assert "Intake" in charter
    assert "Handles intake" in charter


def test_apply_single_split_validates_artifacts(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "split",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": [],
            "elements": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002", "REQ-LIB-0001-0003"],
            "summary": "Intake - Handles intake",
            "rationale": "Split [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )
    report_path = _write_review_actions_report(manager, [action])

    summary = apply_split_actions(manager, report_path)

    assert summary["validation_issues"] == []
    assert summary["errors"] == []


def test_apply_split_actions_with_flag(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text="alpha group") for idx in range(1, 6)] + [
        _make_element("LIB-0001", idx + 5, text="beta group") for idx in range(1, 6)
    ]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _complete_spec_stabilization(manager)

    split_groups = [
        {
            "group_id": 0,
            "proposed_name": "Intake",
            "charter_summary": "Own intake",
            "element_ids": [
                "REQ-LIB-0001-0001",
                "REQ-LIB-0001-0002",
                "REQ-LIB-0001-0003",
            ],
            "justification": "Reason [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        },
        {
            "group_id": 1,
            "proposed_name": "Processing",
            "charter_summary": "Own processing",
            "element_ids": [
                "REQ-LIB-0001-0004",
                "REQ-LIB-0001-0005",
                "REQ-LIB-0001-0006",
            ],
            "justification": "Reason [LIB-0001::spec.md::REQ-LIB-0001-0004].",
        },
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_split_planner(split_groups)

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    result = review_library_structure(manager.run_id, apply_splits=True)

    assert result["split_application"]
    assert result["split_application"]["applied_count"] > 0


# Move application tests


def test_apply_single_move_inserts_tombstones(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 4)]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "move_elements",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0002"],
            "elements": ["REQ-LIB-0001-0001"],
            "summary": "Move intake",
            "rationale": "Move [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )

    apply_move_actions(manager, [action])

    source_spec = (manager.structure.libraries_dir / "LIB-0001" / "spec.md").read_text(
        encoding="utf-8"
    )
    assert "REQ-LIB-0001-0001 moved to LIB-0002" in source_spec


def test_apply_single_move_copies_elements(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 4)]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "move_elements",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0002"],
            "elements": ["REQ-LIB-0001-0001"],
            "summary": "Move intake",
            "rationale": "Move [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )

    apply_move_actions(manager, [action])

    target_spec = (manager.structure.libraries_dir / "LIB-0002" / "spec.md").read_text(
        encoding="utf-8"
    )
    assert "Moved from LIB-0001" in target_spec
    assert "REQ-LIB-0002" in target_spec


def test_apply_single_move_updates_evidence(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 4)]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _create_library_with_elements(
        manager, "LIB-0002", [_make_element("LIB-0002", 1)], evidence_sources=[]
    )

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "move_elements",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0002"],
            "elements": ["REQ-LIB-0001-0001"],
            "summary": "Move intake",
            "rationale": "Move [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )

    apply_move_actions(manager, [action])

    target_evidence = json.loads(
        (manager.structure.libraries_dir / "LIB-0002" / "evidence.json").read_text(encoding="utf-8")
    )
    assert target_evidence["sources"]


def test_apply_single_move_records_events(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 4)]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "move_elements",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0002"],
            "elements": ["REQ-LIB-0001-0001"],
            "summary": "Move intake",
            "rationale": "Move [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )

    apply_move_actions(manager, [action])

    source_events = _read_library_events(manager.structure.libraries_dir / "LIB-0001")
    target_events = _read_library_events(manager.structure.libraries_dir / "LIB-0002")
    assert any(event.event_type == LibraryEventType.BOUNDARY_CHANGED for event in source_events)
    assert any(event.event_type == LibraryEventType.BOUNDARY_CHANGED for event in target_events)


def test_apply_single_move_preserves_traceability(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 4)]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "move_elements",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0002"],
            "elements": ["REQ-LIB-0001-0001"],
            "summary": "Move intake",
            "rationale": "Move [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )

    apply_move_actions(manager, [action])

    source_spec = (manager.structure.libraries_dir / "LIB-0001" / "spec.md").read_text(
        encoding="utf-8"
    )
    assert "REQ-LIB-0001-0001 moved to LIB-0002" in source_spec


def test_apply_single_move_validates_artifacts(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 4)]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "move_elements",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0002"],
            "elements": ["REQ-LIB-0001-0001"],
            "summary": "Move intake",
            "rationale": "Move [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )

    summary = apply_move_actions(manager, [action])

    assert summary["failed"] == 0


def test_apply_move_actions_with_flag(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 4)]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])
    _complete_spec_stabilization(manager)

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "move_elements",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0002"],
            "elements": ["REQ-LIB-0001-0001"],
            "summary": "Move intake",
            "rationale": "Move [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )
    report_path = _write_review_actions_report(manager, [action])

    def _fake_detect(manager, thresholds=None, consolidate=False):
        return {
            "thresholds": {"overlap_similarity": 0.35, "min_shared_elements": 5},
            "overlap_candidates": [],
            "split_candidates": [],
            "report_paths": {"json": str(report_path)},
        }

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.detect_structure_issues",
        _fake_detect,
    )

    result = review_library_structure(manager.run_id, apply_moves=True)

    assert result["move_application"]
    assert result["move_application"]["applied"] == 1


# Error handling tests


def test_apply_split_rollback_on_validation_failure(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements)

    source_spec = (manager.structure.libraries_dir / "LIB-0001" / "spec.md").read_text(
        encoding="utf-8"
    )

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "split",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": [],
            "elements": ["REQ-LIB-0001-0001", "REQ-LIB-0001-0002", "REQ-LIB-0001-0003"],
            "summary": "Intake - Handles intake",
            "rationale": "Split [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )
    report_path = _write_review_actions_report(manager, [action])

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review._validate_split_artifacts",
        lambda *_args, **_kwargs: [{"type": "invalid", "message": "bad"}],
    )
    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review._repair_split_artifacts",
        lambda *_args, **_kwargs: False,
    )

    summary = apply_split_actions(manager, report_path)

    assert summary["rejected_actions"]
    assert summary["new_library_ids"] == []
    assert (manager.structure.libraries_dir / "LIB-0001" / "spec.md").read_text(
        encoding="utf-8"
    ) == source_spec


def test_apply_move_rollback_on_validation_failure(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text=f"alpha {idx}") for idx in range(1, 4)]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])

    source_spec = (manager.structure.libraries_dir / "LIB-0001" / "spec.md").read_text(
        encoding="utf-8"
    )
    target_spec = (manager.structure.libraries_dir / "LIB-0002" / "spec.md").read_text(
        encoding="utf-8"
    )

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "move_elements",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0002"],
            "elements": ["REQ-LIB-0001-0001"],
            "summary": "Move intake",
            "rationale": "Move [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review._validate_moved_elements",
        lambda *_args, **_kwargs: [{"type": "missing", "message": "bad"}],
    )

    summary = apply_move_actions(manager, [action])

    assert summary["failed"] == 1
    assert (manager.structure.libraries_dir / "LIB-0001" / "spec.md").read_text(
        encoding="utf-8"
    ) == source_spec
    assert (manager.structure.libraries_dir / "LIB-0002" / "spec.md").read_text(
        encoding="utf-8"
    ) == target_spec


def test_agent_failure_continues_workflow(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    _create_library_with_elements(manager, "LIB-0001", [_make_element("LIB-0001", 1)])
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])
    _create_library_with_elements(manager, "LIB-0003", [_make_element("LIB-0003", 1)])

    overlap_candidates = [
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0002",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        },
        {
            "lib_a": "LIB-0001",
            "lib_b": "LIB-0003",
            "similarity": 0.6,
            "shared_element_count": 1,
            "matched_elements": [],
        },
    ]

    calls = {"count": 0}

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("agent failure")
        return _mock_boundary_judge(
            "merge",
            "Overlap [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    report = consolidate_proposals(manager, overlap_candidates, [], {"overlap_similarity": 0.35})

    assert len(report.actions) == 1


def test_invalid_action_skipped_during_application(spec_refinement_workspace) -> None:
    manager, _manifest = spec_refinement_workspace()
    _create_library_with_elements(manager, "LIB-0001", [_make_element("LIB-0001", 1)])
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1)])

    action = ReviewAction.model_validate(
        {
            "action_id": "ACT-0001",
            "type": "move_elements",
            "status": "proposed",
            "source_libs": ["LIB-0001"],
            "target_libs": ["LIB-0002"],
            "elements": ["REQ-LIB-0001-9999"],
            "summary": "Move intake",
            "rationale": "Move [LIB-0001::spec.md::REQ-LIB-0001-0001].",
            "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
        }
    )

    summary = apply_move_actions(manager, [action])

    assert summary["applied"] == 0
    assert summary["failed"] == 1


# End-to-end tests


def test_full_workflow_overlap_to_merge(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements_a = [_make_element("LIB-0001", idx, text="shared alpha") for idx in range(1, 7)]
    elements_b = [_make_element("LIB-0002", idx, text="shared alpha") for idx in range(1, 7)]
    _create_library_with_elements(manager, "LIB-0001", elements_a)
    _create_library_with_elements(manager, "LIB-0002", elements_b)
    _complete_spec_stabilization(manager)

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_boundary_judge(
            "merge",
            "Overlap [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        )

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    review_library_structure(manager.run_id)

    report = read_review_actions_json(manager.structure.reports_dir / "review_actions.json")
    assert report.actions[0].type == "merge"


def test_full_workflow_split_to_new_libraries(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    elements = [_make_element("LIB-0001", idx, text="alpha group") for idx in range(1, 6)] + [
        _make_element("LIB-0001", idx + 5, text="beta group") for idx in range(1, 6)
    ]
    _create_library_with_elements(manager, "LIB-0001", elements)
    _complete_spec_stabilization(manager)

    split_groups = [
        {
            "group_id": 0,
            "proposed_name": "Intake",
            "charter_summary": "Own intake",
            "element_ids": [
                "REQ-LIB-0001-0001",
                "REQ-LIB-0001-0002",
                "REQ-LIB-0001-0003",
            ],
            "justification": "Reason [LIB-0001::spec.md::REQ-LIB-0001-0001].",
        },
        {
            "group_id": 1,
            "proposed_name": "Processing",
            "charter_summary": "Own processing",
            "element_ids": [
                "REQ-LIB-0001-0004",
                "REQ-LIB-0001-0005",
                "REQ-LIB-0001-0006",
            ],
            "justification": "Reason [LIB-0001::spec.md::REQ-LIB-0001-0004].",
        },
    ]

    def _run_agent(*, agent_name: str, prompt: str, workspace: Path, max_retries: int = 2) -> str:
        return _mock_split_planner(split_groups)

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        _run_agent,
    )

    result = review_library_structure(manager.run_id, apply_splits=True)

    assert result["split_application"]
    assert result["split_application"]["applied_count"] > 0


def test_full_workflow_no_actions_needed(spec_refinement_workspace, monkeypatch) -> None:
    manager, _manifest = spec_refinement_workspace()
    _create_library_with_elements(manager, "LIB-0001", [_make_element("LIB-0001", 1)])
    _create_library_with_elements(manager, "LIB-0002", [_make_element("LIB-0002", 1, text="beta")])
    _complete_spec_stabilization(manager)

    monkeypatch.setattr(
        "spec_manager.refinement.workflows.library_structure_review.run_agent",
        lambda **_: _mock_boundary_judge(
            "keep_separate",
            "No overlap [LIB-0001::charter.md].",
        ),
    )

    review_library_structure(manager.run_id)

    report = read_review_actions_json(manager.structure.reports_dir / "review_actions.json")
    assert report.actions == []
