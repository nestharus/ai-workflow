from __future__ import annotations

import pytest
from spec_manager.refinement.workflows.tasks import (
    assign_task_ids,
    build_patch_graph,
    resolve_task_dependencies,
)
from spec_manager.schemas.tasks import validate_patch_graph_acyclic
from spec_manager.utils.graph import get_topological_order

pytestmark = [pytest.mark.tasks, pytest.mark.unit]


def _patch_graph_to_dependency_graph(patch_graph) -> dict[str, object]:
    nodes = {
        node: {"id": node, "name": node, "keywords": [], "sources": []}
        for node in patch_graph.nodes
    }
    adjacency = {node: {"incoming": [], "outgoing": []} for node in patch_graph.nodes}
    for source, target in patch_graph.edges:
        adjacency[source]["outgoing"].append(
            {"target": target, "type": "depends_on", "relation_id": "task"}
        )
        adjacency[target]["incoming"].append(
            {"source": source, "type": "depends_on", "relation_id": "task"}
        )
    return {"nodes": nodes, "edges": [], "adjacency": adjacency}


def test_assign_task_ids_stable_sort() -> None:
    tasks = [
        {"title": "Zeta", "component": "Core", "libraries": ["LIB-0002"]},
        {"title": "Alpha", "component": "API", "libraries": ["LIB-0001"]},
        {"title": "Beta", "component": "API", "libraries": ["LIB-0002", "LIB-0001"]},
    ]

    first = assign_task_ids(tasks)
    second = assign_task_ids(list(reversed(tasks)))

    assert [task["task_id"] for task in first] == [task["task_id"] for task in second]
    assert [task["title"] for task in first] == ["Alpha", "Beta", "Zeta"]
    assert [task["task_id"] for task in first] == ["TASK-0001", "TASK-0002", "TASK-0003"]


def test_resolve_dependencies_by_title() -> None:
    tasks = [
        {"task_id": "TASK-0001", "title": "Setup", "depends_on": []},
        {"task_id": "TASK-0002", "title": "Implement", "depends_on": ["Setup"]},
    ]

    resolved = resolve_task_dependencies(tasks)

    assert resolved[1]["depends_on"] == ["TASK-0001"]


def test_resolve_dependencies_by_temp_id() -> None:
    tasks = [
        {"task_id": "TASK-0001", "title": "TEMP-001", "depends_on": []},
        {"task_id": "TASK-0002", "title": "Implement", "depends_on": ["TEMP-001"]},
    ]

    resolved = resolve_task_dependencies(tasks)

    assert resolved[1]["depends_on"] == ["TASK-0001"]


def test_build_patch_graph_valid_dag() -> None:
    tasks = [
        {"task_id": "TASK-0001", "depends_on": []},
        {"task_id": "TASK-0002", "depends_on": ["TASK-0001"]},
        {"task_id": "TASK-0003", "depends_on": ["TASK-0002"]},
    ]

    patch_graph = build_patch_graph(tasks, run_id="run_graph")

    assert set(patch_graph.nodes) == {"TASK-0001", "TASK-0002", "TASK-0003"}
    assert ("TASK-0001", "TASK-0002") in patch_graph.edges
    assert ("TASK-0002", "TASK-0003") in patch_graph.edges
    is_valid, errors = validate_patch_graph_acyclic(patch_graph)
    assert is_valid
    assert errors == []


def test_validate_task_graph_detects_cycles() -> None:
    tasks = [
        {"task_id": "TASK-0001", "depends_on": ["TASK-0002"]},
        {"task_id": "TASK-0002", "depends_on": ["TASK-0001"]},
    ]

    with pytest.raises(ValueError, match="Circular dependency detected"):
        build_patch_graph(tasks, run_id="run_cycle")


def test_validate_task_graph_detects_missing_dependencies() -> None:
    tasks = [
        {"task_id": "TASK-0001", "depends_on": ["TASK-9999"]},
    ]

    with pytest.raises(ValueError, match="TASK-9999"):
        build_patch_graph(tasks, run_id="run_missing")


def test_topological_sort_ordering() -> None:
    tasks = [
        {"task_id": "TASK-0001", "depends_on": []},
        {"task_id": "TASK-0002", "depends_on": ["TASK-0001"]},
        {"task_id": "TASK-0003", "depends_on": ["TASK-0001"]},
        {"task_id": "TASK-0004", "depends_on": ["TASK-0002", "TASK-0003"]},
    ]

    patch_graph = build_patch_graph(tasks, run_id="run_topo")
    graph = _patch_graph_to_dependency_graph(patch_graph)
    order = get_topological_order(graph)
    position = {task_id: idx for idx, task_id in enumerate(order)}

    for source, target in patch_graph.edges:
        assert position[source] < position[target]
