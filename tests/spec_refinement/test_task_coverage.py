from __future__ import annotations

import pytest
from spec_manager.refinement.workflows.tasks import (
    validate_task_acceptance_criteria,
    validate_task_decision_gap_coverage,
    validate_task_edge_coverage,
    validate_task_element_coverage,
)
from spec_manager.schemas.tasks import TaskCoversSchema, TaskSchema

pytestmark = [pytest.mark.tasks, pytest.mark.unit]


def _make_task(
    task_id: str,
    title: str,
    *,
    component: str = "API Layer",
    libraries: list[str] | None = None,
    elements: list[str] | None = None,
    edges: list[str] | None = None,
    decisions: list[str] | None = None,
    gaps: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "title": title,
        "description": f"Task {title}",
        "priority": "p1",
        "component": component,
        "libraries": libraries or ["LIB-0001"],
        "covers": {
            "elements": elements or [],
            "edges": edges or [],
            "decisions": decisions or [],
            "gaps": gaps or [],
        },
        "acceptance_criteria": acceptance_criteria or ["Tests validate output."],
        "suggested_files": [],
        "risk_notes": "",
        "validation_notes": "",
        "citations": [],
        "depends_on": depends_on or [],
    }


def test_validate_element_coverage_complete() -> None:
    planning_context = {
        "coverage_targets": {
            "LIB-0001": ["REQ-LIB-0001-0001", "FLOW-LIB-0001-01", "INV-LIB-0001-0001"],
        }
    }
    tasks = [
        _make_task(
            "TASK-0001",
            "Cover elements",
            elements=["REQ-LIB-0001-0001", "FLOW-LIB-0001-01", "INV-LIB-0001-0001"],
        )
    ]

    errors = validate_task_element_coverage(tasks, planning_context)

    assert errors == []


def test_validate_element_coverage_missing_elements() -> None:
    planning_context = {
        "coverage_targets": {
            "LIB-0001": [
                "REQ-LIB-0001-0001",
                "REQ-LIB-0001-0002",
                "FLOW-LIB-0001-01",
                "INV-LIB-0001-0001",
                "INV-LIB-0001-0002",
            ]
        }
    }
    tasks = [
        _make_task(
            "TASK-0001",
            "Partial coverage",
            elements=["REQ-LIB-0001-0001", "FLOW-LIB-0001-01", "INV-LIB-0001-0001"],
        )
    ]

    errors = validate_task_element_coverage(tasks, planning_context)
    missing = {error["context"]["element_id"] for error in errors}

    assert len(errors) == 2
    assert missing == {"REQ-LIB-0001-0002", "INV-LIB-0001-0002"}


def test_validate_edge_coverage_complete() -> None:
    planning_context = {
        "edges": [
            {"edge_id": "EDGE-LIB-0001-LIB-0002"},
            {"edge_id": "EDGE-LIB-0001-LIB-0003"},
        ]
    }
    tasks = [
        _make_task(
            "TASK-0001",
            "Cover edges",
            edges=["EDGE-LIB-0001-LIB-0002", "EDGE-LIB-0001-LIB-0003"],
        )
    ]

    errors = validate_task_edge_coverage(tasks, planning_context)

    assert errors == []


def test_validate_edge_coverage_missing_edges() -> None:
    planning_context = {
        "edges": [
            {"edge_id": "EDGE-LIB-0001-LIB-0002"},
            {"edge_id": "EDGE-LIB-0001-LIB-0003"},
            {"edge_id": "EDGE-LIB-0002-LIB-0003"},
        ]
    }
    tasks = [
        _make_task(
            "TASK-0001",
            "Partial edges",
            edges=["EDGE-LIB-0001-LIB-0002", "EDGE-LIB-0001-LIB-0003"],
        )
    ]

    errors = validate_task_edge_coverage(tasks, planning_context)

    assert len(errors) == 1
    assert errors[0]["context"]["edge_id"] == "EDGE-LIB-0002-LIB-0003"


def test_validate_decision_coverage_complete() -> None:
    planning_context = {
        "open_decisions": [
            {"decision_id": "DEC-LIB-0001-0001", "lib_id": "LIB-0001"},
            {"decision_id": "DEC-LIB-0001-0002", "lib_id": "LIB-0001"},
        ],
        "open_gaps": [],
    }
    tasks = [
        _make_task(
            "TASK-0001",
            "Decisions covered",
            decisions=["DEC-LIB-0001-0001", "DEC-LIB-0001-0002"],
        )
    ]

    errors = validate_task_decision_gap_coverage(tasks, planning_context)

    assert errors == []


def test_validate_decision_coverage_allows_external_input() -> None:
    planning_context = {
        "open_decisions": [
            {
                "decision_id": "DEC-LIB-0002-0001",
                "lib_id": "LIB-0002",
                "requires_external_input": True,
            }
        ],
        "open_gaps": [],
    }
    tasks = [
        _make_task(
            "TASK-0001",
            "No decisions",
            decisions=[],
        )
    ]

    errors = validate_task_decision_gap_coverage(tasks, planning_context)

    assert errors == []


def test_validate_gap_coverage_complete() -> None:
    planning_context = {
        "open_decisions": [],
        "open_gaps": [
            {"gap_id": "GAP-FOUNDATION", "lib_id": "LIB-0001"},
            {"gap_id": "GAP-PLANNING", "lib_id": "LIB-0001"},
        ],
    }
    tasks = [
        _make_task(
            "TASK-0001",
            "Gap coverage",
            gaps=["GAP-FOUNDATION", "GAP-PLANNING"],
        )
    ]

    errors = validate_task_decision_gap_coverage(tasks, planning_context)

    assert errors == []


def test_validate_acceptance_criteria_quality_valid() -> None:
    tasks = [
        _make_task(
            "TASK-0001",
            "Valid criteria",
            acceptance_criteria=[
                "Tests cover acceptance flow.",
                "Log output includes success marker.",
                "File created at reports/output.json.",
            ],
        )
    ]

    errors = validate_task_acceptance_criteria(tasks)

    assert errors == []


def test_validate_acceptance_criteria_quality_weak() -> None:
    tasks = [
        _make_task(
            "TASK-0001",
            "Weak criteria",
            acceptance_criteria=["Implement the feature.", "Update the code."],
        )
    ]

    errors = validate_task_acceptance_criteria(tasks)

    assert len(errors) == 1
    assert errors[0]["context"]["task_id"] == "TASK-0001"


def test_validate_acceptance_criteria_empty() -> None:
    task = TaskSchema.model_construct(
        task_id="TASK-0001",
        title="Missing criteria",
        description="No criteria provided.",
        priority="p1",
        component="API Layer",
        libraries=["LIB-0001"],
        covers=TaskCoversSchema.model_construct(
            elements=["REQ-LIB-0001-0001"],
            edges=[],
            decisions=[],
            gaps=[],
        ),
        acceptance_criteria=[],
        suggested_files=[],
        risk_notes="",
        validation_notes="",
        citations=[],
        depends_on=[],
    )

    errors = validate_task_acceptance_criteria([task])

    assert len(errors) == 1
    assert errors[0]["context"]["task_id"] == "TASK-0001"
