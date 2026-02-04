from __future__ import annotations

import json
from pathlib import Path

import pytest
from spec_manager.refinement.formats import _extract_json_payload
from spec_manager.refinement.workflows.tasks import (
    build_task_planning_context,
    plan_tasks,
    validate_task_plan_completeness,
)
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager
from spec_manager.schemas.tasks import (
    read_patch_graph_json,
    read_task_index_json,
    read_task_json,
    read_task_status_json,
    validate_patch_graph_acyclic,
)

from tests.spec_refinement.fixtures.test_corpus import (
    create_interface_test_libraries,
    create_task_planning_prerequisites,
)

pytestmark = [pytest.mark.tasks, pytest.mark.workflow_smoke]


def _complete_prerequisites(manager) -> None:
    manager.start_phase(Phase.INTERFACES)
    manager.complete_phase(
        Phase.INTERFACES,
        outputs={"edge_list_path": "edge_list.json", "interface_index_path": "interface_index.json"},
    )
    manager.start_phase(Phase.ARCHITECTURE_MAPPING)
    manager.complete_phase(Phase.ARCHITECTURE_MAPPING, outputs={"mapped": 1})


def _create_architecture_and_interfaces(fs, manager, manifest: dict[str, object]) -> None:
    create_task_planning_prerequisites(fs, manager.run_id, manifest)


def _assert_task_files_valid(run_dir: Path, task_id: str) -> None:
    task_dir = run_dir / "tasks" / task_id
    task_json = task_dir / "task.json"
    task_md = task_dir / "task.md"
    status_json = task_dir / "status.json"

    assert task_json.exists()
    assert task_md.exists()
    assert status_json.exists()

    task = read_task_json(task_json)
    assert task.task_id == task_id
    status = read_task_status_json(status_json)
    assert status.task_id == task_id

    content = task_md.read_text(encoding="utf-8")
    for section in ["## Title", "## Description", "## Coverage", "## Acceptance Criteria"]:
        assert section in content


def _expected_task_count(manifest: dict[str, object]) -> int:
    library_ids = manifest.get("library_ids") or []
    edges = manifest.get("expected_edges") or []
    decision_ids = manifest.get("decision_ids") or {}
    decision_count = sum(len(ids or []) for ids in decision_ids.values())
    return len(library_ids) + len(edges) + decision_count


def test_plan_tasks_creates_task_index(interface_workspace, mock_task_agents, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_index")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    mock_task_agents(manifest)

    result = plan_tasks(manager.run_id)

    task_index_path = manager.structure.tasks_dir / "task_index.json"
    assert task_index_path.exists()

    task_index = read_task_index_json(task_index_path)
    expected_count = _expected_task_count(manifest)
    assert len(task_index.tasks) == expected_count
    assert result["tasks_count"] == expected_count


def test_plan_tasks_creates_patch_graph(interface_workspace, mock_task_agents, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_graph")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    mock_task_agents(manifest)

    plan_tasks(manager.run_id)

    patch_graph_path = manager.structure.tasks_dir / "patch_graph.json"
    assert patch_graph_path.exists()

    patch_graph = read_patch_graph_json(patch_graph_path)
    is_valid, errors = validate_patch_graph_acyclic(patch_graph)
    assert is_valid
    assert errors == []

    task_index = read_task_index_json(manager.structure.tasks_dir / "task_index.json")
    expected_edges = {
        (task.task_id, dependency)
        for task in task_index.tasks
        for dependency in task.depends_on
    }
    assert set(patch_graph.edges) == expected_edges


def test_plan_tasks_creates_task_artifacts(interface_workspace, mock_task_agents, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_artifacts")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    mock_task_agents(manifest)

    plan_tasks(manager.run_id)

    task_index = read_task_index_json(manager.structure.tasks_dir / "task_index.json")
    for task in task_index.tasks:
        _assert_task_files_valid(manager.run_root, task.task_id)


def test_plan_tasks_validates_coverage(interface_workspace, mock_task_agents, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_validate")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    controller = mock_task_agents(manifest, violation_mode="missing_edge_coverage")

    result = plan_tasks(manager.run_id)

    assert result["validation_stats"]["repairs_attempted"] > 0
    assert any(
        call["agent_name"] == "chatgpt-task-plan-judge" for call in controller.call_log
    )


def test_plan_tasks_repair_loop_succeeds(interface_workspace, mock_task_agents, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_repair_success")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    controller = mock_task_agents(manifest, violation_mode="missing_element_coverage")

    result = plan_tasks(manager.run_id)

    assert any(
        call["agent_name"] == "chatgpt-task-plan-repairer" for call in controller.call_log
    )
    assert result["validation_stats"]["repairs_attempted"] >= 1
    assert result["validation_stats"]["repairs_succeeded"] >= 1

    planning_context = build_task_planning_context(manager)
    tasks = [
        read_task_json(manager.structure.tasks_dir / task.task_id / "task.json").model_dump()
        for task in read_task_index_json(manager.structure.tasks_dir / "task_index.json").tasks
    ]
    errors = validate_task_plan_completeness(tasks, planning_context)
    assert errors == []


def test_plan_tasks_repair_loop_fails_after_max_retries(
    interface_workspace, mock_task_agents, fs
) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_repair_fail")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    controller = mock_task_agents(
        manifest,
        violation_mode="missing_element_coverage",
        overrides={"chatgpt-task-plan-repairer": 1.0},
    )

    with pytest.raises(RuntimeError, match="validation failed after repairs"):
        plan_tasks(manager.run_id)

    repair_calls = [
        call
        for call in controller.call_log
        if call["agent_name"] == "chatgpt-task-plan-repairer"
    ]
    assert len(repair_calls) == 3


def test_plan_tasks_handles_no_gaps_or_decisions(
    interface_workspace, mock_task_agents, fs
) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_no_decisions")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)

    for lib_id in manifest["library_ids"]:
        decisions_index = manager.structure.libraries_dir / lib_id / "decisions_index.json"
        if decisions_index.exists():
            decisions_index.unlink()

    mock_task_agents(manifest)

    result = plan_tasks(manager.run_id)

    expected_tasks = len(manifest["library_ids"]) + len(manifest["expected_edges"])
    assert result["tasks_count"] == expected_tasks

    task_index = read_task_index_json(manager.structure.tasks_dir / "task_index.json")
    for task in task_index.tasks:
        task_json = read_task_json(manager.structure.tasks_dir / task.task_id / "task.json")
        assert task_json.covers.decisions == []
        assert task_json.covers.gaps == []


def test_plan_tasks_phase_tracking(interface_workspace, mock_task_agents, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_phase")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    mock_task_agents(manifest)

    plan_tasks(manager.run_id)

    refreshed = WorkspaceManager(run_id=manager.run_id, input_folder=Path("."))
    phase_result = refreshed.state.phases[Phase.TASKS.value]
    assert phase_result.status == PhaseStatus.COMPLETED
    assert phase_result.started_at is not None
    assert phase_result.completed_at is not None
    assert phase_result.outputs["task_index_path"]
    assert phase_result.outputs["patch_graph_path"]
    assert phase_result.outputs["task_count"]
    assert phase_result.outputs["coverage_stats"]


def test_plan_tasks_prerequisite_validation(interface_workspace, fs) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_prereq")
    _create_architecture_and_interfaces(fs, manager, manifest)

    with pytest.raises(RuntimeError, match="Interfaces phase must be completed"):
        plan_tasks(manager.run_id)


def test_plan_tasks_uses_architecture_mapping(
    interface_workspace, mock_task_agents, fs
) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_arch")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    controller = mock_task_agents(manifest)

    plan_tasks(manager.run_id)

    prompts = [
        call["prompt"]
        for call in controller.call_log
        if call["agent_name"] == "opus-task-planner"
    ]
    assert prompts

    prompt = prompts[0]
    context_payload = prompt.split("## PLANNING CONTEXT", 1)[1]
    planning_context = json.loads(_extract_json_payload(context_payload))
    assert "API Layer" in planning_context.get("components", {})

    task_index = read_task_index_json(manager.structure.tasks_dir / "task_index.json")
    components = {task.component for task in task_index.tasks}
    assert "API Layer" in components


def test_plan_tasks_includes_decisions_in_tasks(
    interface_workspace, mock_task_agents, fs
) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_decisions")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    mock_task_agents(manifest)

    plan_tasks(manager.run_id)

    expected_decisions = {
        decision_id for ids in manifest["decision_ids"].values() for decision_id in ids
    }
    task_index = read_task_index_json(manager.structure.tasks_dir / "task_index.json")
    covered = set()
    for task in task_index.tasks:
        task_json = read_task_json(manager.structure.tasks_dir / task.task_id / "task.json")
        covered.update(task_json.covers.decisions)

    assert covered == expected_decisions


def test_plan_tasks_renders_markdown_index(
    interface_workspace, mock_task_agents, fs
) -> None:
    manager, manifest = interface_workspace(run_id="run_tasks_md")
    _create_architecture_and_interfaces(fs, manager, manifest)
    _complete_prerequisites(manager)
    mock_task_agents(manifest)

    plan_tasks(manager.run_id)

    index_md = manager.structure.tasks_dir / "task_index.md"
    assert index_md.exists()

    content = index_md.read_text(encoding="utf-8")
    assert "| Task ID | Title | Component | Status | Priority | Dependencies |" in content


def test_plan_tasks_deterministic_task_ids(interface_workspace, mock_task_agents, fs) -> None:
    manager_a, manifest_a = interface_workspace(run_id="run_tasks_det_a")
    _create_architecture_and_interfaces(fs, manager_a, manifest_a)
    _complete_prerequisites(manager_a)
    mock_task_agents(manifest_a)
    plan_tasks(manager_a.run_id)

    manager_b = WorkspaceManager(run_id="run_tasks_det_b", input_folder=manager_a.input_folder)
    issues = manager_b.initialize(force=True)
    assert issues == []
    manifest_b = create_interface_test_libraries(fs, run_id=manager_b.run_id)
    for lib_id in manifest_b["library_ids"]:
        manager_b.state.register_library_id(lib_id)
    manager_b.save_state()
    _create_architecture_and_interfaces(fs, manager_b, manifest_b)
    _complete_prerequisites(manager_b)
    mock_task_agents(manifest_b, task_overrides={"__order__": "reverse"})
    plan_tasks(manager_b.run_id)

    index_a = read_task_index_json(manager_a.structure.tasks_dir / "task_index.json")
    index_b = read_task_index_json(manager_b.structure.tasks_dir / "task_index.json")

    def _signature(task) -> tuple[str, str, tuple[str, ...]]:
        return (task.title, task.component, tuple(sorted(task.libraries)))

    mapping_a = {_signature(task): task.task_id for task in index_a.tasks}
    mapping_b = {_signature(task): task.task_id for task in index_b.tasks}

    assert mapping_a == mapping_b
