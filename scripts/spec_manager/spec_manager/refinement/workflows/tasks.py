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
    DecisionsIndex,
    SpecIndex,
    _SPEC_ELEMENT_ID_RE,
)
from spec_manager.schemas.tasks import (
    PatchGraphSchema,
    TaskIndexSchema,
    TaskSchema,
    TaskStatusSchema,
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
    "build_task_planning_context",
]
