"""Task planning workflow context builders for spec refinement."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.refinement.core.gap import Gap, parse_gaps_markdown
from spec_manager.refinement.core.gap_queue import GapQueue
from spec_manager.refinement.workspace.manager import WorkspaceManager
from spec_manager.schemas.edge_list import (
    LIB_ID_RE,
    EdgeListSchema,
    InterfaceIndexSchema,
    read_edge_list_json,
    read_interface_index_json,
)
from spec_manager.schemas.spec_indexes import (
    _SPEC_ELEMENT_ID_RE,
    DecisionsIndex,
    SpecIndex,
)
from spec_manager.schemas.tasks import (
    TASK_ID_RE,
    PatchGraphSchema,
    TaskIndexSchema,
    TaskSchema,
    TaskStatusSchema,
    _find_patch_graph_cycles,
    validate_patch_graph_acyclic,
)

logger = logging.getLogger(__name__)

_ISSUE_SINK: list[dict[str, Any]] | None = None
_SCHEMA_TYPES = (
    TaskSchema,
    TaskIndexSchema,
    PatchGraphSchema,
    TaskStatusSchema,
    EdgeListSchema,
    InterfaceIndexSchema,
    Gap,
)
_NOW = datetime.now


def _set_issue_sink(issues: list[dict[str, Any]] | None) -> None:
    global _ISSUE_SINK
    _ISSUE_SINK = issues


def _record_issue(lib_id: str, error_type: str, message: str) -> None:
    issue = {"lib_id": lib_id, "error_type": error_type, "message": message}
    if _ISSUE_SINK is not None:
        _ISSUE_SINK.append(issue)
    logger.warning("%s (%s): %s", lib_id, error_type, message)


def _load_architecture_mapping(manager: WorkspaceManager) -> dict[str, str]:
    mapping_path = manager.structure.architecture_dir / "mapping.md"
    if not mapping_path.exists():
        _record_issue("unknown", "missing_mapping", "architecture/mapping.md not found")
        return {}

    try:
        content = mapping_path.read_text(encoding="utf-8")
    except OSError as exc:
        _record_issue("unknown", "mapping_read_error", str(exc))
        return {}

    components: dict[str, str] = {}
    current_component: str | None = None

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("### Component:"):
            current_component = stripped.split(":", 1)[1].strip()
            continue
        if stripped.startswith("## "):
            current_component = None
            continue
        if current_component:
            match = LIB_ID_RE.search(stripped)
            if match:
                components[match.group(0)] = current_component

    return components


def _load_architecture_components(manager: WorkspaceManager) -> dict[str, str]:
    selected_path = manager.structure.architecture_dir / "selected.md"
    if not selected_path.exists():
        _record_issue("unknown", "missing_selected", "architecture/selected.md not found")
        return {}

    try:
        content = selected_path.read_text(encoding="utf-8")
    except OSError as exc:
        _record_issue("unknown", "selected_read_error", str(exc))
        return {}

    component_descriptions: dict[str, str] = {}
    in_components = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Components"):
            in_components = True
            continue
        if in_components and stripped.startswith("## "):
            in_components = False
        if not in_components:
            continue
        if stripped.startswith("- "):
            item = stripped[2:].strip()
            if not item:
                continue
            if ":" in item:
                name, desc = item.split(":", 1)
                component_descriptions[name.strip()] = desc.strip()
            else:
                component_descriptions[item.strip()] = ""

    return component_descriptions


def _load_edge_list(manager: WorkspaceManager) -> EdgeListSchema | None:
    edge_list_path = manager.structure.indexes_dir / "edge_list.json"
    if not edge_list_path.exists():
        _record_issue("unknown", "missing_edge_list", "workspace/indexes/edge_list.json not found")
        return None
    try:
        return read_edge_list_json(edge_list_path)
    except OSError as exc:
        _record_issue("unknown", "edge_list_read_error", str(exc))
        return None
    except json.JSONDecodeError as exc:
        _record_issue("unknown", "edge_list_json_error", str(exc))
        return None
    except Exception as exc:
        _record_issue("unknown", "edge_list_validation_error", str(exc))
        return None


def _load_interface_index(manager: WorkspaceManager) -> InterfaceIndexSchema | None:
    interface_index_path = manager.structure.indexes_dir / "interface_index.json"
    if not interface_index_path.exists():
        _record_issue(
            "unknown",
            "missing_interface_index",
            "workspace/indexes/interface_index.json not found",
        )
        return None
    try:
        return read_interface_index_json(interface_index_path)
    except OSError as exc:
        _record_issue("unknown", "interface_index_read_error", str(exc))
        return None
    except json.JSONDecodeError as exc:
        _record_issue("unknown", "interface_index_json_error", str(exc))
        return None
    except Exception as exc:
        _record_issue("unknown", "interface_index_validation_error", str(exc))
        return None


def _load_spec_index(lib_dir: Path) -> SpecIndex | None:
    spec_index_path = lib_dir / "spec_index.json"
    lib_id = lib_dir.name
    if not spec_index_path.exists():
        _record_issue(lib_id, "missing_spec_index", "spec_index.json not found")
        return None
    try:
        content = spec_index_path.read_text(encoding="utf-8")
    except OSError as exc:
        _record_issue(lib_id, "spec_index_read_error", str(exc))
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        _record_issue(lib_id, "spec_index_json_error", str(exc))
        return None

    try:
        return SpecIndex.model_validate(payload)
    except Exception as exc:
        _record_issue(lib_id, "spec_index_validation_error", str(exc))
        return None


def _load_decisions_index(lib_dir: Path) -> DecisionsIndex | None:
    decisions_index_path = lib_dir / "decisions_index.json"
    lib_id = lib_dir.name
    if not decisions_index_path.exists():
        return None
    try:
        content = decisions_index_path.read_text(encoding="utf-8")
    except OSError as exc:
        _record_issue(lib_id, "decisions_index_read_error", str(exc))
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        _record_issue(lib_id, "decisions_index_json_error", str(exc))
        return None

    try:
        return DecisionsIndex.model_validate(payload)
    except Exception as exc:
        _record_issue(lib_id, "decisions_index_validation_error", str(exc))
        return None


def _load_library_gaps(lib_dir: Path) -> list[Gap]:
    gaps_path = lib_dir / "gaps.md"
    if not gaps_path.exists():
        return []
    try:
        content = gaps_path.read_text(encoding="utf-8")
    except OSError as exc:
        _record_issue(lib_dir.name, "gaps_read_error", str(exc))
        return []
    try:
        return parse_gaps_markdown(content)
    except Exception as exc:
        _record_issue(lib_dir.name, "gaps_parse_error", str(exc))
        return []


def _load_gap_queue(lib_dir: Path) -> GapQueue | None:
    queue_path = lib_dir / "gap_queue.json"
    if not queue_path.exists():
        return None
    try:
        content = queue_path.read_text(encoding="utf-8")
    except OSError as exc:
        _record_issue(lib_dir.name, "gap_queue_read_error", str(exc))
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        _record_issue(lib_dir.name, "gap_queue_json_error", str(exc))
        return None
    try:
        return GapQueue.from_dict(payload)
    except Exception as exc:
        _record_issue(lib_dir.name, "gap_queue_validation_error", str(exc))
        return None


def _extract_coverage_targets(manager: WorkspaceManager) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {}
    libraries_dir = manager.structure.libraries_dir

    if not libraries_dir.exists():
        _record_issue("unknown", "missing_libraries_dir", "Libraries directory missing")
        return targets

    for lib_dir in sorted(libraries_dir.iterdir()):
        if not lib_dir.is_dir():
            continue
        lib_id = lib_dir.name
        if not LIB_ID_RE.fullmatch(lib_id):
            continue

        element_ids: set[str] = set()

        spec_index = _load_spec_index(lib_dir)
        if spec_index is not None:
            for element in spec_index.elements:
                if _SPEC_ELEMENT_ID_RE.fullmatch(element.element_id):
                    element_ids.add(element.element_id)

        if element_ids:
            targets[lib_id] = element_ids

    return targets


def _get_allocated_library_ids(manager: WorkspaceManager) -> set[str]:
    libraries_dir = manager.structure.libraries_dir
    if not libraries_dir.exists():
        _record_issue("unknown", "missing_libraries_dir", "Libraries directory missing")
        return set()

    allocated: set[str] = set()
    for lib_dir in sorted(libraries_dir.iterdir()):
        if not lib_dir.is_dir():
            continue
        lib_id = lib_dir.name
        if LIB_ID_RE.fullmatch(lib_id):
            allocated.add(lib_id)
    return allocated


def _load_library_charter(lib_dir: Path) -> str:
    charter_path = lib_dir / "charter.md"
    if not charter_path.exists():
        _record_issue(lib_dir.name, "missing_charter", "charter.md not found")
        return ""
    try:
        return charter_path.read_text(encoding="utf-8")
    except OSError as exc:
        _record_issue(lib_dir.name, "charter_read_error", str(exc))
        return ""


def assign_task_ids(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign deterministic TASK-#### identifiers to tasks."""
    if not tasks:
        return []

    def _sort_key(task: dict[str, Any]) -> tuple[str, list[str], str]:
        component = task.get("component") or ""
        libraries = task.get("libraries") or []
        title = task.get("title") or ""
        return (component, sorted(libraries), title)

    sorted_tasks = sorted(tasks, key=_sort_key)
    assigned: list[dict[str, Any]] = []
    for index, task in enumerate(sorted_tasks, start=1):
        payload = dict(task)
        payload["task_id"] = f"TASK-{index:04d}"
        assigned.append(payload)
    return assigned


def resolve_task_dependencies(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve dependency references from titles to TASK-#### identifiers."""
    title_entries: dict[str, list[tuple[str, str]]] = {}
    for task in tasks:
        title = str(task.get("title", "")).strip()
        task_id = str(task.get("task_id", "")).strip()
        key = title.casefold()
        title_entries.setdefault(key, []).append((title, task_id))

    for entries in title_entries.values():
        if len(entries) > 1:
            title = entries[0][0]
            task_ids = [task_id for _, task_id in entries]
            raise ValueError(f"Duplicate task title '{title}' found in tasks {task_ids}")

    title_to_id = {key: entries[0][1] for key, entries in title_entries.items()}
    resolved: list[dict[str, Any]] = []
    for task in tasks:
        payload = dict(task)
        depends_on = list(payload.get("depends_on") or [])
        resolved_deps: list[str] = []
        for ref in depends_on:
            ref_str = str(ref)
            if TASK_ID_RE.fullmatch(ref_str):
                resolved_deps.append(ref_str)
                continue
            resolved_id = title_to_id.get(ref_str.strip().casefold())
            if resolved_id is None:
                raise ValueError(
                    f"Unknown dependency reference '{ref}' in task '{payload.get('task_id')}'"
                )
            resolved_deps.append(resolved_id)
        payload["depends_on"] = resolved_deps
        resolved.append(payload)
    return resolved


def validate_dependency_references(tasks: list[dict[str, Any]]) -> None:
    """Ensure all dependency references point to known task IDs."""
    valid_ids = {str(task.get("task_id", "")).strip() for task in tasks}
    errors: list[str] = []
    for task in tasks:
        task_id = str(task.get("task_id", "")).strip()
        for dep_id in task.get("depends_on") or []:
            dep_str = str(dep_id)
            if dep_str not in valid_ids:
                errors.append(f"Task '{task_id}' depends on non-existent task '{dep_str}'")
    if errors:
        raise ValueError("; ".join(errors))


def build_patch_graph(tasks: list[dict[str, Any]], run_id: str) -> PatchGraphSchema:
    """Build a validated patch graph from resolved tasks."""
    nodes = [str(task.get("task_id", "")).strip() for task in tasks]
    edges: list[tuple[str, str]] = []
    for task in tasks:
        task_id = str(task.get("task_id", "")).strip()
        for dep_id in task.get("depends_on") or []:
            edges.append((task_id, str(dep_id)))
    generated_at = datetime.now().isoformat()
    raw_graph = PatchGraphSchema.model_construct(
        run_id=run_id,
        generated_at=generated_at,
        nodes=nodes,
        edges=edges,
    )
    validate_task_graph(raw_graph)
    return PatchGraphSchema.model_validate(raw_graph.model_dump())


def validate_task_graph(graph: PatchGraphSchema) -> None:
    """Validate that the patch graph is acyclic with clear cycle details."""
    is_valid, errors = validate_patch_graph_acyclic(graph)
    if is_valid:
        return

    adjacency: dict[str, list[str]] = {node: [] for node in graph.nodes}
    for source, target in graph.edges:
        adjacency.setdefault(source, []).append(target)

    cycles = _find_patch_graph_cycles(adjacency)
    cycle_chain = "; ".join(" -> ".join(cycle) for cycle in cycles) if cycles else "; ".join(errors)
    raise ValueError(f"Circular dependency detected: {cycle_chain}. Tasks must form a DAG.")


def assign_task_ids_and_build_graph(
    tasks: list[dict[str, Any]],
    run_id: str,
) -> tuple[list[dict[str, Any]], PatchGraphSchema]:
    """Assign task IDs, resolve dependencies, and build a patch graph."""
    logger.info("Assigning task IDs for %d tasks.", len(tasks))
    tasks_with_ids = assign_task_ids(tasks)
    logger.info("Resolving task dependencies for %d tasks.", len(tasks_with_ids))
    resolved_tasks = resolve_task_dependencies(tasks_with_ids)
    logger.info("Validating dependency references.")
    validate_dependency_references(resolved_tasks)
    logger.info("Building patch graph.")
    try:
        patch_graph = build_patch_graph(resolved_tasks, run_id)
    except ValueError as exc:
        if str(exc).startswith("Circular dependency detected:"):
            raise
        raise ValueError(f"Patch graph validation failed: {exc}") from exc
    return resolved_tasks, patch_graph


def build_task_planning_context(manager: WorkspaceManager) -> dict[str, Any]:
    """Build deterministic context for task planning."""
    issues: list[dict[str, Any]] = []
    _set_issue_sink(issues)
    try:
        lib_to_component = _load_architecture_mapping(manager)
        component_descriptions = _load_architecture_components(manager)
        edge_list = _load_edge_list(manager)
        _load_interface_index(manager)
        coverage_targets = _extract_coverage_targets(manager)

        components_by_name: dict[str, list[str]] = {}
        for lib_id, component in lib_to_component.items():
            components_by_name.setdefault(component, []).append(lib_id)

        components: dict[str, dict[str, Any]] = {}
        for component_name in sorted(components_by_name):
            lib_ids = sorted(components_by_name[component_name])
            components[component_name] = {
                "description": component_descriptions.get(component_name, ""),
                "libraries": lib_ids,
            }

        edges: list[dict[str, Any]] = []
        if edge_list is not None:
            for edge in sorted(edge_list.edges, key=lambda item: item.edge_id):
                edges.append(
                    {
                        "edge_id": edge.edge_id,
                        "consumer_lib": edge.consumer_lib,
                        "provider_lib": edge.provider_lib,
                        "kind": edge.kind,
                        "summary": edge.summary,
                        "consumer_elements": list(edge.consumer_elements),
                        "provider_elements": list(edge.provider_elements),
                    }
                )

        coverage_payload = {
            lib_id: sorted(element_ids) for lib_id, element_ids in sorted(coverage_targets.items())
        }

        open_gaps: list[dict[str, Any]] = []
        open_decisions: list[dict[str, Any]] = []

        libraries_dir = manager.structure.libraries_dir
        if libraries_dir.exists():
            for lib_dir in sorted(libraries_dir.iterdir()):
                if not lib_dir.is_dir():
                    continue
                lib_id = lib_dir.name
                if not LIB_ID_RE.fullmatch(lib_id):
                    continue

                gap_queue = _load_gap_queue(lib_dir)
                if gap_queue is not None:
                    gaps = gap_queue.get_open_gaps()
                else:
                    gaps = [gap for gap in _load_library_gaps(lib_dir) if gap.status == "open"]

                for gap in gaps:
                    open_gaps.append(
                        {
                            "gap_id": gap.id,
                            "lib_id": lib_id,
                            "gap_type": gap.gap_type.value,
                            "severity": gap.severity.value,
                            "description": gap.description,
                        }
                    )

                decisions_index = _load_decisions_index(lib_dir)
                if decisions_index is not None:
                    for decision in decisions_index.decisions:
                        if decision.status != "open":
                            continue
                        open_decisions.append(
                            {
                                "decision_id": decision.decision_id,
                                "lib_id": lib_id,
                                "question": decision.question,
                                "status": decision.status,
                            }
                        )

        open_gaps.sort(key=lambda item: (item["lib_id"], item["gap_id"]))
        open_decisions.sort(key=lambda item: (item["lib_id"], item["decision_id"]))

        return {
            "run_id": manager.run_id,
            "components": components,
            "edges": edges,
            "coverage_targets": coverage_payload,
            "open_gaps": open_gaps,
            "open_decisions": open_decisions,
            "issues": issues,
        }
    finally:
        _set_issue_sink(None)


__all__ = [
    "assign_task_ids",
    "assign_task_ids_and_build_graph",
    "build_patch_graph",
    "build_task_planning_context",
    "resolve_task_dependencies",
    "validate_dependency_references",
    "validate_task_graph",
]
