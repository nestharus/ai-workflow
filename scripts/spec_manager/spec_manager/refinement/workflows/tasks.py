"""Task planning workflow context builders for spec refinement."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.refinement.agent_utils import run_agent
from spec_manager.refinement.core.gap import Gap, parse_gaps_markdown
from spec_manager.refinement.core.gap_queue import GapQueue
from spec_manager.refinement.progress import ProgressTracker
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
    TaskIndexEntrySchema,
    TaskIndexSchema,
    TaskSchema,
    TaskStatusSchema,
    _find_patch_graph_cycles,
    validate_acceptance_criteria,
    validate_decision_gap_coverage,
    validate_edge_coverage,
    validate_element_coverage,
    validate_patch_graph_acyclic,
    write_patch_graph_json,
    write_task_index_json,
    write_task_index_markdown,
    write_task_json,
    write_task_markdown,
    write_task_status_json,
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
_ELEMENT_ID_RE = re.compile(r"(?:REQ-LIB-\d{4}-\d{4}|FLOW-LIB-\d{4}-\d{2}|INV-LIB-\d{4}-\d{4})")
_EDGE_ID_RE = re.compile(r"EDGE-LIB-\d{4}-LIB-\d{4}")
_DECISION_ID_RE = re.compile(r"DEC-LIB-\d{4}-\d{4}")
_GAP_ID_RE = re.compile(r"GAP-[A-Z_]+")
_TASK_ID_FRAGMENT_RE = re.compile(r"TASK-\d{4}")


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


def _parse_coverage_error(error_message: str, error_type: str) -> dict[str, Any]:
    context: dict[str, str] = {}
    patterns: dict[str, tuple[str, re.Pattern[str]]] = {
        "missing_element_coverage": ("element_id", _ELEMENT_ID_RE),
        "missing_edge_coverage": ("edge_id", _EDGE_ID_RE),
        "missing_decision_coverage": ("decision_id", _DECISION_ID_RE),
        "missing_gap_coverage": ("gap_id", _GAP_ID_RE),
        "weak_acceptance_criteria": ("task_id", _TASK_ID_FRAGMENT_RE),
        "missing_acceptance_criteria": ("task_id", _TASK_ID_FRAGMENT_RE),
    }
    pattern_entry = patterns.get(error_type)
    if pattern_entry is not None:
        context_key, pattern = pattern_entry
        match = pattern.search(error_message)
        if match:
            context[context_key] = match.group(0)
    return {"error_type": error_type, "message": error_message, "context": context}


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


def validate_task_element_coverage(
    tasks: list[dict[str, Any]],
    planning_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate that tasks cover all required spec elements."""
    coverage_type = "element"
    logger.debug("Validating %s coverage for %d tasks", coverage_type, len(tasks))
    required_elements: set[str] = set()
    coverage_targets = planning_context.get("coverage_targets") or {}
    for element_ids in coverage_targets.values():
        if element_ids is None:
            continue
        for element_id in element_ids:
            required_elements.add(str(element_id))

    excluded = planning_context.get("coverage_targets_excluded") or []
    required_elements -= {str(eid) for eid in excluded}

    task_schemas = [TaskSchema.model_validate(task) for task in tasks]
    _, messages = validate_element_coverage(task_schemas, required_elements)
    errors = [_parse_coverage_error(message, "missing_element_coverage") for message in messages]

    logger.info("%s validation: %d errors", coverage_type, len(errors))
    for error in errors:
        element_id = error["context"].get("element_id")
        if element_id:
            logger.debug("Missing %s: %s", "element", element_id)
    return errors


def validate_task_edge_coverage(
    tasks: list[dict[str, Any]],
    planning_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate that tasks cover all required edges."""
    coverage_type = "edge"
    logger.debug("Validating %s coverage for %d tasks", coverage_type, len(tasks))
    required_edges: set[str] = set()
    edges = planning_context.get("edges") or []
    for edge in edges:
        edge_id = edge.get("edge_id")
        if edge_id:
            required_edges.add(str(edge_id))

    task_schemas = [TaskSchema.model_validate(task) for task in tasks]
    _, messages = validate_edge_coverage(task_schemas, required_edges)
    errors = [_parse_coverage_error(message, "missing_edge_coverage") for message in messages]

    logger.info("%s validation: %d errors", coverage_type, len(errors))
    for error in errors:
        edge_id = error["context"].get("edge_id")
        if edge_id:
            logger.debug("Missing %s: %s", "edge", edge_id)
    return errors


def validate_task_decision_gap_coverage(
    tasks: list[dict[str, Any]],
    planning_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate that tasks cover open decisions and gaps."""
    coverage_type = "decision/gap"
    logger.debug("Validating %s coverage for %d tasks", coverage_type, len(tasks))
    required_decisions: set[str] = set()
    required_gaps: set[str] = set()

    open_decisions = planning_context.get("open_decisions") or []
    for decision in open_decisions:
        if decision.get("requires_external_input"):
            continue
        decision_id = decision.get("decision_id")
        if decision_id:
            required_decisions.add(str(decision_id))

    open_gaps = planning_context.get("open_gaps") or []
    for gap in open_gaps:
        if gap.get("requires_external_input"):
            continue
        gap_id = gap.get("gap_id")
        if gap_id:
            required_gaps.add(str(gap_id))

    task_schemas = [TaskSchema.model_validate(task) for task in tasks]
    _, messages = validate_decision_gap_coverage(task_schemas, required_decisions, required_gaps)

    errors: list[dict[str, Any]] = []
    for message in messages:
        if _DECISION_ID_RE.search(message):
            error_type = "missing_decision_coverage"
        elif _GAP_ID_RE.search(message):
            error_type = "missing_gap_coverage"
        else:
            error_type = "missing_decision_coverage"
        errors.append(_parse_coverage_error(message, error_type))

    logger.info("%s validation: %d errors", coverage_type, len(errors))
    for error in errors:
        if error["error_type"] == "missing_decision_coverage":
            decision_id = error["context"].get("decision_id")
            if decision_id:
                logger.debug("Missing %s: %s", "decision", decision_id)
        elif error["error_type"] == "missing_gap_coverage":
            gap_id = error["context"].get("gap_id")
            if gap_id:
                logger.debug("Missing %s: %s", "gap", gap_id)
    return errors


def validate_task_acceptance_criteria(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate that tasks include verifiable acceptance criteria."""
    coverage_type = "acceptance criteria"
    logger.debug("Validating %s coverage for %d tasks", coverage_type, len(tasks))
    task_schemas = [TaskSchema.model_validate(task) for task in tasks]
    _, messages = validate_acceptance_criteria(task_schemas)

    errors: list[dict[str, Any]] = []
    for message in messages:
        if "missing acceptance criteria" in message.lower():
            error_type = "missing_acceptance_criteria"
        else:
            error_type = "weak_acceptance_criteria"
        errors.append(_parse_coverage_error(message, error_type))

    logger.info("%s validation: %d errors", coverage_type, len(errors))
    for error in errors:
        task_id = error["context"].get("task_id")
        if not task_id:
            continue
        if error["error_type"] == "missing_acceptance_criteria":
            item_type = "acceptance criteria"
        else:
            item_type = "acceptance criteria signal"
        logger.debug("Missing %s: %s", item_type, task_id)
    return errors


def validate_task_plan_completeness(
    tasks: list[dict[str, Any]],
    planning_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate task plans against coverage and acceptance criteria."""
    errors: list[dict[str, Any]] = []
    errors.extend(validate_task_element_coverage(tasks, planning_context))
    errors.extend(validate_task_edge_coverage(tasks, planning_context))
    errors.extend(validate_task_decision_gap_coverage(tasks, planning_context))
    errors.extend(validate_task_acceptance_criteria(tasks))
    logger.info("Task plan validation: %d errors found", len(errors))
    return errors


def _parse_task_plan_output(output: str) -> dict[str, Any] | None:
    """Parse task plan output, handling raw JSON and fenced JSON blocks."""
    if not output or not output.strip():
        return None

    cleaned = output.strip()
    candidates = [cleaned]
    for match in re.findall(r"```(?:json)?\s*(.+?)```", cleaned, flags=re.DOTALL):
        candidate = match.strip()
        if candidate:
            candidates.append(candidate)

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    match = re.search(r"(\{.*\}|\[.*\])", cleaned, flags=re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            return payload
    return None


def _build_task_plan_prompt(planning_context: dict[str, Any]) -> str:
    """Build the task planning prompt for the planner agent."""
    context_payload = json.dumps(planning_context, indent=2)
    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return ONLY valid JSON. No preamble, no code fences.",
        "",
        "REQUIRED SCHEMA:",
        '{"tasks": [{"title": "...", "description": "...", "priority": "p0|p1|p2", '
        '"component": "...", "libraries": ["LIB-####"], '
        '"covers": {"elements": ["REQ-LIB-####-####"], "edges": ["EDGE-LIB-####-LIB-####"], '
        '"decisions": ["DEC-LIB-####-####"], "gaps": ["GAP-..."]}, '
        '"acceptance_criteria": ["..."], "suggested_files": ["..."], '
        '"risk_notes": "...", "validation_notes": "...", "citations": ["[LIB-####::spec.md::REQ-LIB-####-####]"], '  # noqa: E501
        '"depends_on": ["Task title"]}]}',
        "",
        "REQUIRED RULES:",
        "- Do NOT include task_id (it will be assigned later).",
        "- Task titles must be unique.",
        "- Acceptance criteria must be verifiable (tests, logs, outputs, files, returns).",
        "- Coverage must include all required elements, edges, open gaps, and open decisions.",
        "- Use component names and library IDs from the planning context.",
        "- depends_on should reference other task titles when possible.",
        "",
        "## PLANNING CONTEXT",
        context_payload,
        "",
        "## INSTRUCTIONS",
        "Generate a complete, minimal task plan that covers all targets.",
        "Ensure tasks are actionable, scoped, and have clear acceptance criteria.",
    ]
    return "\n".join(lines)


def _build_task_plan_judge_prompt(
    tasks: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    planning_context: dict[str, Any],
) -> str:
    """Build the validation/repair prompt for the task plan judge."""
    error_payload = json.dumps(errors, indent=2)
    tasks_payload = json.dumps({"tasks": tasks}, indent=2)
    coverage_requirements = {
        "coverage_targets": planning_context.get("coverage_targets") or {},
        "edges": [
            edge.get("edge_id")
            for edge in (planning_context.get("edges") or [])
            if edge.get("edge_id")
        ],
        "open_gaps": planning_context.get("open_gaps") or [],
        "open_decisions": planning_context.get("open_decisions") or [],
    }
    coverage_payload = json.dumps(coverage_requirements, indent=2)
    existing_ids = sorted(
        {
            str(task.get("task_id", "")).strip()
            for task in tasks
            if isinstance(task, dict) and task.get("task_id")
        }
    )
    id_list = ", ".join(existing_ids) if existing_ids else "None"

    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return ONLY valid JSON. No preamble, no code fences.",
        "",
        "Choose ONE output format:",
        "",
        "Option A (full repaired plan):",
        '{"tasks": [{"task_id": "TASK-0001", "title": "...", "description": "...", '
        '"priority": "p0|p1|p2", "component": "...", "libraries": ["LIB-####"], '
        '"covers": {"elements": ["REQ-LIB-####-####"], "edges": ["EDGE-LIB-####-LIB-####"], '
        '"decisions": ["DEC-LIB-####-####"], "gaps": ["GAP-..."]}, '
        '"acceptance_criteria": ["..."], "suggested_files": ["..."], '
        '"risk_notes": "...", "validation_notes": "...", "citations": ["[LIB-####::spec.md::REQ-LIB-####-####]"], '  # noqa: E501
        '"depends_on": ["TASK-####"]}]}',
        "",
        "Option B (delta plan):",
        '{"delta": {"add": [{"task_id": "TASK-####", "...": "..."}], '
        '"update": [{"task_id": "TASK-####", "fields": {"covers": {"elements": [], "edges": [], '
        '"decisions": [], "gaps": []}, "acceptance_criteria": ["..."]}}]}}',
        "",
        "RULES:",
        "- Keep existing task_id values unchanged; use new unique TASK-#### for added tasks.",
        "- For updates, include full replacement values for any fields you change.",
        "- If updating covers, include all covers fields (elements, edges, decisions, gaps).",
        "",
        "## EXISTING TASK IDS",
        id_list,
        "",
        "## VALIDATION ERRORS",
        error_payload,
        "",
        "## COVERAGE REQUIREMENTS",
        coverage_payload,
        "",
        "## CURRENT TASK PLAN",
        tasks_payload,
        "",
        "## INSTRUCTIONS",
        "Fix the validation errors while preserving task quality and coverage.",
    ]
    return "\n".join(lines)


def _draft_task_plan(
    planning_context: dict[str, Any],
    manager: WorkspaceManager,
) -> list[dict[str, Any]]:
    """Draft an initial task plan via the planner agent."""
    prompt = _build_task_plan_prompt(planning_context)
    logger.info("Drafting task plan with opus-task-planner.")
    started_at = _NOW().isoformat()
    logger.debug("Task planner started at %s.", started_at)
    start_time = time.perf_counter()
    try:
        output = run_agent(
            agent_name="opus-task-planner",
            prompt=prompt,
            workspace=manager.workspace_path,
        )
    except RuntimeError as exc:
        logger.exception("Task planner agent failed: %s")
        raise RuntimeError(f"Task planner agent failed: {exc}") from exc
    latency = time.perf_counter() - start_time
    logger.info("Task planner completed in %.2fs.", latency)

    payload = _parse_task_plan_output(output)
    if not isinstance(payload, dict):
        raise TypeError("Task planner output is not valid JSON.")

    tasks_payload = payload.get("tasks")
    if not isinstance(tasks_payload, list):
        raise TypeError("Task planner output missing 'tasks' list.")
    if not all(isinstance(task, dict) for task in tasks_payload):
        raise RuntimeError("Task planner output contains non-object tasks.")

    logger.debug("Task planner produced %d tasks.", len(tasks_payload))
    return list(tasks_payload)


def _validate_and_repair_task_plan(
    tasks: list[dict[str, Any]],
    planning_context: dict[str, Any],
    manager: WorkspaceManager,
    max_attempts: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Validate and repair task plans via the judge agent."""
    repairs_attempted = 0
    repairs_succeeded = 0
    judge_attempts: list[dict[str, Any]] = []

    def _apply_delta(
        current_tasks: list[dict[str, Any]],
        delta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        updated = [dict(task) for task in current_tasks]
        task_index = {
            str(task.get("task_id", "")).strip(): idx
            for idx, task in enumerate(updated)
            if isinstance(task, dict)
        }
        title_index = {
            str(task.get("title", "")).strip().casefold(): idx
            for idx, task in enumerate(updated)
            if isinstance(task, dict) and task.get("title")
        }

        additions = delta.get("add") or []
        updates = delta.get("update") or []

        if not isinstance(additions, list) or not isinstance(updates, list):
            raise TypeError("Delta payload must include list values for add/update.")

        for patch in updates:
            if not isinstance(patch, dict):
                continue
            task_id = str(patch.get("task_id", "")).strip()
            title = str(patch.get("title", "")).strip()
            target_idx = task_index.get(task_id)
            if target_idx is None and title:
                target_idx = title_index.get(title.casefold())
            if target_idx is None:
                logger.warning(
                    "Delta update references unknown task_id/title: %s/%s", task_id, title
                )
                continue
            fields = patch.get("fields")
            if not isinstance(fields, dict):
                logger.warning("Delta update for %s missing fields object.", task_id or title)
                continue
            target = dict(updated[target_idx])
            for key, value in fields.items():
                target[key] = value
            updated[target_idx] = target

        for task in additions:
            if not isinstance(task, dict):
                continue
            updated.append(task)

        return updated

    last_errors: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        try:
            last_errors = validate_task_plan_completeness(tasks, planning_context)
        except Exception as exc:
            logger.warning("Task plan validation failed due to schema error: %s", exc)
            last_errors = [
                {
                    "error_type": "task_schema_error",
                    "message": str(exc),
                    "context": {},
                }
            ]

        if not last_errors:
            return (
                tasks,
                {
                    "repairs_attempted": repairs_attempted,
                    "repairs_succeeded": repairs_succeeded,
                    "judge_attempts": judge_attempts,
                },
                [],
            )

        logger.warning(
            "Task plan validation failed (attempt %d/%d): %d errors",
            attempt,
            max_attempts,
            len(last_errors),
        )

        repairs_attempted += 1
        prompt = _build_task_plan_judge_prompt(tasks, last_errors, planning_context)
        started_at = _NOW().isoformat()
        logger.debug("Task plan judge attempt %d started at %s.", attempt, started_at)
        start_time = time.perf_counter()
        try:
            output = run_agent(
                agent_name="chatgpt-task-plan-judge",
                prompt=prompt,
                workspace=manager.workspace_path,
            )
        except RuntimeError as exc:
            latency = time.perf_counter() - start_time
            logger.warning("Task plan judge failed on attempt %d: %s", attempt, exc)
            judge_attempts.append(
                {
                    "attempt": attempt,
                    "error_count": len(last_errors),
                    "started_at": started_at,
                    "latency_seconds": latency,
                    "status": "failed",
                    "message": str(exc),
                }
            )
            continue

        latency = time.perf_counter() - start_time
        payload = _parse_task_plan_output(output)
        if not isinstance(payload, dict):
            logger.warning("Task plan judge returned invalid JSON on attempt %d.", attempt)
            judge_attempts.append(
                {
                    "attempt": attempt,
                    "error_count": len(last_errors),
                    "started_at": started_at,
                    "latency_seconds": latency,
                    "status": "invalid_json",
                }
            )
            continue

        updated = False
        if "tasks" in payload:
            candidate = payload.get("tasks")
            if isinstance(candidate, list) and all(isinstance(task, dict) for task in candidate):
                tasks = list(candidate)
                updated = True
            else:
                logger.warning(
                    "Task plan judge returned invalid tasks list on attempt %d.", attempt
                )
        elif "delta" in payload:
            delta = payload.get("delta")
            if isinstance(delta, dict):
                try:
                    tasks = _apply_delta(tasks, delta)
                    updated = True
                except Exception as exc:
                    logger.warning("Failed to apply task plan delta: %s", exc)
            else:
                logger.warning(
                    "Task plan judge returned invalid delta payload on attempt %d.", attempt
                )
        else:
            logger.warning("Task plan judge output missing tasks or delta on attempt %d.", attempt)

        if updated:
            repairs_succeeded += 1
            status = "applied"
        else:
            status = "ignored"

        judge_attempts.append(
            {
                "attempt": attempt,
                "error_count": len(last_errors),
                "started_at": started_at,
                "latency_seconds": latency,
                "status": status,
            }
        )

    try:
        last_errors = validate_task_plan_completeness(tasks, planning_context)
    except Exception as exc:
        last_errors = [
            {
                "error_type": "task_schema_error",
                "message": str(exc),
                "context": {},
            }
        ]

    return (
        tasks,
        {
            "repairs_attempted": repairs_attempted,
            "repairs_succeeded": repairs_succeeded,
            "judge_attempts": judge_attempts,
        },
        last_errors,
    )


def _write_task_artifacts(
    tasks: list[dict[str, Any]],
    patch_graph: PatchGraphSchema,
    manager: WorkspaceManager,
    run_id: str,
) -> dict[str, Any]:
    """Write task plan artifacts (index, per-task files, patch graph)."""
    tasks_dir = manager.structure.tasks_dir
    tasks_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _NOW().isoformat()

    task_schemas: list[TaskSchema] = []
    for task in tasks:
        task_schemas.append(TaskSchema.model_validate(task))

    index_entries: list[TaskIndexEntrySchema] = []
    for task in sorted(task_schemas, key=lambda item: item.task_id):
        index_entries.append(
            TaskIndexEntrySchema(
                task_id=task.task_id,
                title=task.title,
                status="planned",
                priority=task.priority,
                component=task.component,
                libraries=task.libraries,
                covers=task.covers,
                depends_on=task.depends_on,
            )
        )

    task_index = TaskIndexSchema(
        run_id=run_id,
        generated_at=generated_at,
        tasks=index_entries,
    )

    task_index_path = tasks_dir / "task_index.json"
    task_index_md_path = tasks_dir / "task_index.md"
    patch_graph_path = tasks_dir / "patch_graph.json"

    write_task_index_json(task_index, task_index_path)
    write_task_index_markdown(task_index, task_index_md_path)
    write_patch_graph_json(patch_graph, patch_graph_path)

    tracker = None
    if task_schemas:
        tracker = ProgressTracker(
            total=len(task_schemas),
            description="Writing task artifacts",
            manager=manager,
        )

    for task in task_schemas:
        task_dir = tasks_dir / task.task_id
        write_task_json(task, task_dir / "task.json")
        write_task_markdown(task, task_dir / "task.md")
        status = TaskStatusSchema(
            task_id=task.task_id,
            status="planned",
            created_at=generated_at,
            updated_at=generated_at,
        )
        write_task_status_json(status, task_dir / "status.json")
        if tracker is not None:
            tracker.update(status=task.task_id)

    if tracker is not None:
        tracker.finish()

    return {
        "tasks_dir": str(tasks_dir),
        "task_index_path": str(task_index_path),
        "task_index_md_path": str(task_index_md_path),
        "patch_graph_path": str(patch_graph_path),
        "tasks_written": len(task_schemas),
    }


def plan_tasks(run_id: str) -> dict[str, Any]:
    """Plan tasks for the current run using LLM planning and validation."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    logger.info("Starting task planning for run %s.", run_id)
    evidence: list[dict[str, Any]] = []

    try:
        planning_context = build_task_planning_context(manager)
        logger.info(
            "Planning context built: %d components, %d edges, %d gaps, %d decisions.",
            len(planning_context.get("components") or {}),
            len(planning_context.get("edges") or []),
            len(planning_context.get("open_gaps") or []),
            len(planning_context.get("open_decisions") or []),
        )

        planner_started_at = _NOW().isoformat()
        planner_start = time.perf_counter()
        tasks = _draft_task_plan(planning_context, manager)
        planner_latency = time.perf_counter() - planner_start
        planner_completed_at = _NOW().isoformat()
        evidence.append(
            {
                "event": "task_planner_invocation",
                "agent_name": "opus-task-planner",
                "model": "opus-task-planner",
                "started_at": planner_started_at,
                "completed_at": planner_completed_at,
                "latency_seconds": planner_latency,
                "task_count": len(tasks),
            }
        )

        tasks, patch_graph = assign_task_ids_and_build_graph(tasks, run_id)

        tasks, repair_stats, validation_errors = _validate_and_repair_task_plan(
            tasks, planning_context, manager
        )

        judge_attempts = repair_stats.get("judge_attempts") or []
        for attempt in judge_attempts:
            evidence.append(
                {
                    "event": "task_plan_judge",
                    "agent_name": "chatgpt-task-plan-judge",
                    "model": "chatgpt-task-plan-judge",
                    **attempt,
                }
            )

        if validation_errors:
            error_details = json.dumps(validation_errors, indent=2)
            raise ValueError(f"Task plan validation failed after repairs: {error_details}")

        if repair_stats.get("repairs_succeeded", 0) > 0:
            logger.info("Reassigning task IDs and rebuilding patch graph after repairs.")
            tasks, patch_graph = assign_task_ids_and_build_graph(tasks, run_id)

        outputs = _write_task_artifacts(tasks, patch_graph, manager, run_id)

        error_type_counts: dict[str, int] = {}
        for error in validation_errors:
            error_type = error.get("error_type", "unknown")
            error_type_counts[error_type] = error_type_counts.get(error_type, 0) + 1

        coverage_stats = {
            "coverage_targets": sum(
                len(value or [])
                for value in (planning_context.get("coverage_targets") or {}).values()
            ),
            "edges_required": len(planning_context.get("edges") or []),
            "open_gaps_required": len(planning_context.get("open_gaps") or []),
            "open_decisions_required": len(planning_context.get("open_decisions") or []),
            "error_types": error_type_counts,
        }

        validation_stats = {
            **{k: v for k, v in repair_stats.items() if k != "judge_attempts"},
            "coverage": coverage_stats,
        }

        evidence.append(
            {
                "event": "task_plan_repair_summary",
                "repairs_attempted": repair_stats.get("repairs_attempted", 0),
                "repairs_succeeded": repair_stats.get("repairs_succeeded", 0),
            }
        )

        return {
            "success": True,
            "tasks_count": len(tasks),
            "validation_errors": [],
            "task_index_path": outputs.get("task_index_path"),
            "patch_graph_path": outputs.get("patch_graph_path"),
            "validation_stats": validation_stats,
            "evidence": evidence,
        }
    except Exception as exc:
        logger.exception("Task planning failed for run %s.", run_id)
        raise RuntimeError(f"Task planning failed for run {run_id}: {exc}") from exc


__all__ = [
    "assign_task_ids",
    "assign_task_ids_and_build_graph",
    "build_patch_graph",
    "build_task_planning_context",
    "plan_tasks",
    "resolve_task_dependencies",
    "validate_dependency_references",
    "validate_task_acceptance_criteria",
    "validate_task_decision_gap_coverage",
    "validate_task_edge_coverage",
    "validate_task_element_coverage",
    "validate_task_graph",
    "validate_task_plan_completeness",
]
