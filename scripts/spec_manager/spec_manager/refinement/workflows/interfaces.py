"""Interface edge extraction workflow for Phase 8 spec refinement."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime as time
from pathlib import Path
from typing import Any

from spec_manager.refinement.agent_utils import run_agent
from spec_manager.refinement.progress import ProgressTracker
from spec_manager.refinement.workspace import Phase, PhaseStatus, WorkspaceManager
from spec_manager.schemas.edge_list import (
    EdgeSchema,
    EdgeListSchema,
    allocate_edge_id,
    validate_edge_references,
)
from spec_manager.schemas.spec_indexes import DecisionsIndex, SpecIndex

LIB_ID_RE = re.compile(r"LIB-\d{4}")

logger = logging.getLogger(__name__)

_KIND_VALUES = {"api", "data", "events", "storage", "config", "other"}
_ISSUE_SINK: list[dict[str, Any]] | None = None


def _set_issue_sink(issues: list[dict[str, Any]] | None) -> None:
    global _ISSUE_SINK
    _ISSUE_SINK = issues


def _record_issue(
    lib_id: str,
    error_type: str,
    message: str,
    *,
    edge_id: str | None = None,
) -> None:
    issue = {"lib_id": lib_id, "error_type": error_type, "message": message}
    if edge_id is not None:
        issue["edge_id"] = edge_id
    if _ISSUE_SINK is not None:
        _ISSUE_SINK.append(issue)
    logger.warning("%s (%s): %s", lib_id, error_type, message)


def _truncate_text(value: str, limit: int) -> str:
    trimmed = value.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[:limit].rstrip()


def _read_spec_index(lib_dir: Path) -> SpecIndex | None:
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
    except Exception as exc:  # noqa: BLE001 - capture schema validation failures
        _record_issue(lib_id, "spec_index_validation_error", str(exc))
        return None


def _read_decisions_index(lib_dir: Path) -> DecisionsIndex | None:
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
    except Exception as exc:  # noqa: BLE001 - capture schema validation failures
        _record_issue(lib_id, "decisions_index_validation_error", str(exc))
        return None


def _scan_spec_indexes_for_lib_mentions(
    manager: WorkspaceManager,
) -> dict[tuple[str, str], dict[str, Any]]:
    candidate_edges: dict[tuple[str, str], dict[str, Any]] = {}
    libraries_dir = manager.structure.libraries_dir

    if not libraries_dir.exists():
        _record_issue("unknown", "missing_libraries_dir", "Libraries directory missing")
        return candidate_edges

    for lib_dir in sorted(libraries_dir.iterdir()):
        if not lib_dir.is_dir():
            continue
        lib_id = lib_dir.name
        if not LIB_ID_RE.fullmatch(lib_id):
            _record_issue(lib_id, "invalid_library_id", "Library directory name invalid")
            continue

        spec_index = _read_spec_index(lib_dir)
        if spec_index is None:
            continue

        for element in spec_index.elements:
            mentions = LIB_ID_RE.findall(element.text or "")
            for provider_lib in mentions:
                edge_key = (lib_id, provider_lib)
                evidence_pointer = f"[{lib_id}::spec.md::{element.element_id}]"

                if edge_key not in candidate_edges:
                    candidate_edges[edge_key] = {
                        "consumer_lib": lib_id,
                        "provider_lib": provider_lib,
                        "consumer_elements": [element.element_id],
                        "provider_elements": [],
                        "kind": "other",
                        "summary": "",
                        "evidence": [evidence_pointer],
                    }
                else:
                    edge = candidate_edges[edge_key]
                    if element.element_id not in edge["consumer_elements"]:
                        edge["consumer_elements"].append(element.element_id)
                    if evidence_pointer not in edge["evidence"]:
                        edge["evidence"].append(evidence_pointer)

    return candidate_edges


def _build_edge_extraction_prompt(
    lib_id: str,
    charter: str,
    spec_index: SpecIndex,
    allocated_library_ids: set[str],
) -> str:
    charter_excerpt = _truncate_text(charter, 2000) if charter else ""
    allowlist = ", ".join(sorted(allocated_library_ids))

    element_lines: list[str] = []
    for element in spec_index.elements:
        summary = _truncate_text(element.text, 280)
        element_lines.append(f"- {element.element_id}: {summary}")
    if not element_lines:
        element_lines.append("- None")

    lines = [
        "## OUTPUT CONTRACT (REQUIRED)",
        "",
        "Return ONLY valid JSON. No preamble, no code fences.",
        "",
        "REQUIRED SCHEMA:",
        '{"edges": [{"provider_lib": "LIB-####", "consumer_elements": ["REQ-..."], '
        '"kind": "api|data|events|storage|config|other", "summary": "...", '
        '"evidence": ["[LIB-####::spec.md::...]"]}]}',
        "",
        "REQUIRED RULES:",
        "- provider_lib MUST be from the allowlist",
        "- consumer_elements MUST exist in the spec_index for this library",
        "- kind MUST be one of: api, data, events, storage, config, other",
        "- evidence MUST include citations to spec elements",
        "",
        "FORBIDDEN:",
        "- Inventing library IDs not in the allowlist",
        "- Referencing non-existent element IDs",
        "- Edges without evidence",
        "",
        "## INPUT DATA",
        "",
        "## Library ID",
        lib_id,
        "",
        "## Charter",
        charter_excerpt or "(empty)",
        "",
        "## Spec Index Elements",
        *element_lines,
        "",
        "## Allowlist of Library IDs",
        allowlist or "(none)",
        "",
        "## OUTPUT FORMAT",
        "",
        "Example JSON payload:",
        '{"edges": [{"provider_lib": "LIB-0002", '
        '"consumer_elements": ["REQ-LIB-0001-0001"], "kind": "api", '
        '"summary": "Consumes provider API for lifecycle updates.", '
        '"evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"]}]}',
    ]
    return "\n".join(lines)


def _extract_edges_via_llm(
    manager: WorkspaceManager,
    allocated_library_ids: set[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    llm_edges: dict[tuple[str, str], dict[str, Any]] = {}
    libraries = {
        lib_dir.name: lib_dir
        for lib_dir in manager.structure.libraries_dir.iterdir()
        if lib_dir.is_dir()
    }

    if not libraries:
        return llm_edges

    tracker = ProgressTracker(total=len(libraries), description="Extracting interface edges", manager=manager)

    def _extract_for_library(lib_id: str, lib_dir: Path) -> list[dict[str, Any]]:
        if not LIB_ID_RE.fullmatch(lib_id):
            _record_issue(lib_id, "invalid_library_id", "Library directory name invalid")
            return []

        charter_path = lib_dir / "charter.md"
        if charter_path.exists():
            try:
                charter = charter_path.read_text(encoding="utf-8")
            except OSError as exc:
                _record_issue(lib_id, "charter_read_error", str(exc))
                charter = ""
        else:
            _record_issue(lib_id, "missing_charter", "charter.md not found")
            charter = ""

        spec_index = _read_spec_index(lib_dir)
        if spec_index is None:
            return []

        prompt = _build_edge_extraction_prompt(lib_id, charter, spec_index, allocated_library_ids)
        try:
            output = run_agent(
                agent_name="glm-interface-edge-extractor",
                prompt=prompt,
                workspace=manager.workspace_path,
            )
        except RuntimeError as exc:
            _record_issue(lib_id, "agent_error", str(exc))
            return []

        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            _record_issue(lib_id, "agent_json_error", str(exc))
            return []

        if isinstance(payload, dict):
            edges_payload = payload.get("edges")
        else:
            edges_payload = payload

        if not isinstance(edges_payload, list):
            _record_issue(lib_id, "agent_schema_error", "Agent output missing edges list")
            return []

        consumer_element_ids = {element.element_id for element in spec_index.elements}
        validated_edges: list[dict[str, Any]] = []

        for raw_edge in edges_payload:
            if not isinstance(raw_edge, dict):
                _record_issue(lib_id, "edge_type_error", "Edge entry is not an object")
                continue

            provider_lib = raw_edge.get("provider_lib")
            if not isinstance(provider_lib, str) or provider_lib not in allocated_library_ids:
                _record_issue(lib_id, "edge_provider_error", "provider_lib not in allowlist")
                continue

            consumer_elements = raw_edge.get("consumer_elements")
            if not isinstance(consumer_elements, list) or not all(
                isinstance(item, str) for item in consumer_elements
            ):
                _record_issue(lib_id, "edge_consumer_elements_error", "consumer_elements invalid")
                continue

            missing_elements = [
                element_id
                for element_id in consumer_elements
                if element_id not in consumer_element_ids
            ]
            if missing_elements:
                _record_issue(
                    lib_id,
                    "edge_consumer_elements_missing",
                    f"Missing consumer elements: {', '.join(missing_elements)}",
                )
                continue

            kind = raw_edge.get("kind", "other")
            if not isinstance(kind, str) or kind not in _KIND_VALUES:
                _record_issue(lib_id, "edge_kind_error", "kind is invalid")
                continue

            summary = raw_edge.get("summary", "")
            if not isinstance(summary, str):
                summary = str(summary)

            evidence = raw_edge.get("evidence", [])
            if not isinstance(evidence, list) or not all(
                isinstance(item, str) for item in evidence
            ):
                _record_issue(lib_id, "edge_evidence_error", "evidence must be a list of strings")
                continue
            if not evidence:
                _record_issue(lib_id, "edge_evidence_missing", "edge missing evidence")
                continue

            provider_elements = raw_edge.get("provider_elements", [])
            if not isinstance(provider_elements, list) or not all(
                isinstance(item, str) for item in provider_elements
            ):
                provider_elements = []

            validated_edges.append(
                {
                    "consumer_lib": lib_id,
                    "provider_lib": provider_lib,
                    "consumer_elements": list(dict.fromkeys(consumer_elements)),
                    "provider_elements": list(dict.fromkeys(provider_elements)),
                    "kind": kind,
                    "summary": summary,
                    "evidence": list(dict.fromkeys(evidence)),
                }
            )

        return validated_edges

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(_extract_for_library, lib_id, lib_dir): lib_id
            for lib_id, lib_dir in libraries.items()
        }
        for future in as_completed(futures):
            lib_id = futures[future]
            try:
                edges = future.result()
                for edge in edges:
                    edge_key = (edge["consumer_lib"], edge["provider_lib"])
                    if edge_key in llm_edges:
                        existing = llm_edges[edge_key]
                        existing["consumer_elements"] = list(
                            dict.fromkeys(existing["consumer_elements"] + edge["consumer_elements"])
                        )
                        existing["provider_elements"] = list(
                            dict.fromkeys(existing["provider_elements"] + edge["provider_elements"])
                        )
                        existing["evidence"] = list(
                            dict.fromkeys(existing["evidence"] + edge["evidence"])
                        )
                        if edge.get("summary"):
                            existing["summary"] = edge["summary"]
                        if edge.get("kind") and edge.get("kind") != "other":
                            existing["kind"] = edge["kind"]
                    else:
                        llm_edges[edge_key] = edge
                tracker.update(status=lib_id)
            except Exception as exc:  # noqa: BLE001 - continue processing others
                _record_issue(lib_id, "edge_extraction_failed", str(exc))
                tracker.update(status=f"{lib_id} (failed)")

    tracker.finish()
    return llm_edges


def _merge_and_deduplicate_edges(
    deterministic_edges: dict[tuple[str, str], dict[str, Any]],
    llm_edges: dict[tuple[str, str], dict[str, Any]],
) -> list[EdgeSchema]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    for edge_key, edge in deterministic_edges.items():
        merged[edge_key] = {
            **edge,
            "consumer_elements": list(dict.fromkeys(edge.get("consumer_elements", []))),
            "provider_elements": list(dict.fromkeys(edge.get("provider_elements", []))),
            "evidence": list(dict.fromkeys(edge.get("evidence", []))),
        }

    for edge_key, edge in llm_edges.items():
        if edge_key in merged:
            existing = merged[edge_key]
            existing["consumer_elements"] = list(
                dict.fromkeys(existing["consumer_elements"] + edge.get("consumer_elements", []))
            )
            existing["provider_elements"] = list(
                dict.fromkeys(existing["provider_elements"] + edge.get("provider_elements", []))
            )
            existing["evidence"] = list(
                dict.fromkeys(existing["evidence"] + edge.get("evidence", []))
            )
            if edge.get("kind") and edge.get("kind") != "other":
                existing["kind"] = edge["kind"]
            if edge.get("summary") and not existing.get("summary"):
                existing["summary"] = edge["summary"]
        else:
            merged[edge_key] = {
                **edge,
                "consumer_elements": list(dict.fromkeys(edge.get("consumer_elements", []))),
                "provider_elements": list(dict.fromkeys(edge.get("provider_elements", []))),
                "evidence": list(dict.fromkeys(edge.get("evidence", []))),
            }

    edges: list[EdgeSchema] = []
    for edge_key, edge in merged.items():
        consumer_lib, provider_lib = edge_key
        edge_id = allocate_edge_id(consumer_lib, provider_lib)
        payload = {
            "edge_id": edge_id,
            "consumer_lib": consumer_lib,
            "provider_lib": provider_lib,
            "kind": edge.get("kind", "other"),
            "consumer_elements": edge.get("consumer_elements", []),
            "provider_elements": edge.get("provider_elements", []),
            "summary": edge.get("summary", ""),
            "evidence": edge.get("evidence", []),
        }
        try:
            edges.append(EdgeSchema.model_validate(payload))
        except Exception as exc:  # noqa: BLE001 - skip invalid edges
            _record_issue(consumer_lib, "edge_schema_error", str(exc), edge_id=edge_id)

    return edges


def _build_element_lookup(manager: WorkspaceManager) -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = {}
    libraries_dir = manager.structure.libraries_dir

    if not libraries_dir.exists():
        _record_issue("unknown", "missing_libraries_dir", "Libraries directory missing")
        return lookup

    for lib_dir in sorted(libraries_dir.iterdir()):
        if not lib_dir.is_dir():
            continue
        lib_id = lib_dir.name
        if not LIB_ID_RE.fullmatch(lib_id):
            continue

        element_ids: set[str] = set()

        spec_index = _read_spec_index(lib_dir)
        if spec_index is not None:
            element_ids.update(element.element_id for element in spec_index.elements)

        decisions_index = _read_decisions_index(lib_dir)
        if decisions_index is not None:
            element_ids.update(
                decision.decision_id for decision in decisions_index.decisions
            )

        if element_ids:
            lookup[lib_id] = element_ids

    return lookup


def _extract_architecture_components(manager: WorkspaceManager) -> dict[str, str]:
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


def build_edge_context_bundles(
    edges: list[EdgeSchema],
    manager: WorkspaceManager,
) -> dict[str, dict[str, Any]]:
    bundles: dict[str, dict[str, Any]] = {}
    architecture_components = _extract_architecture_components(manager)

    selected_path = manager.structure.architecture_dir / "selected.md"
    component_descriptions: dict[str, str] = {}
    if selected_path.exists():
        try:
            selected_content = selected_path.read_text(encoding="utf-8")
        except OSError as exc:
            _record_issue("unknown", "selected_read_error", str(exc))
            selected_content = ""
        if selected_content:
            in_components = False
            for line in selected_content.splitlines():
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

    def _extract_elements(spec_index: SpecIndex | None, element_ids: list[str]) -> list[dict[str, Any]]:
        if spec_index is None or not element_ids:
            return []
        element_lookup = {element.element_id: element for element in spec_index.elements}
        extracted: list[dict[str, Any]] = []
        for element_id in element_ids:
            element = element_lookup.get(element_id)
            if not element:
                continue
            extracted.append(
                {
                    "element_id": element.element_id,
                    "kind": element.kind,
                    "section": element.section,
                    "text": element.text,
                    "citations": list(element.citations),
                }
            )
        return extracted

    def _extract_decisions(
        decisions_index: DecisionsIndex | None, element_ids: list[str],
    ) -> list[dict[str, Any]]:
        if decisions_index is None or not element_ids:
            return []
        decision_lookup = {d.decision_id: d for d in decisions_index.decisions}
        extracted: list[dict[str, Any]] = []
        for element_id in element_ids:
            decision = decision_lookup.get(element_id)
            if not decision:
                continue
            extracted.append(
                {
                    "decision_id": decision.decision_id,
                    "status": decision.status,
                    "question": decision.question,
                    "context": decision.context,
                    "options": list(decision.options),
                    "default": decision.default,
                    "citations": list(decision.citations),
                }
            )
        return extracted

    for edge in edges:
        consumer_dir = manager.structure.libraries_dir / edge.consumer_lib
        provider_dir = manager.structure.libraries_dir / edge.provider_lib

        consumer_charter_path = consumer_dir / "charter.md"
        if consumer_charter_path.exists():
            try:
                consumer_charter = consumer_charter_path.read_text(encoding="utf-8")
            except OSError as exc:
                _record_issue(edge.consumer_lib, "charter_read_error", str(exc))
                consumer_charter = ""
        else:
            _record_issue(edge.consumer_lib, "missing_charter", "charter.md not found")
            consumer_charter = ""

        provider_charter_path = provider_dir / "charter.md"
        if provider_charter_path.exists():
            try:
                provider_charter = provider_charter_path.read_text(encoding="utf-8")
            except OSError as exc:
                _record_issue(edge.provider_lib, "charter_read_error", str(exc))
                provider_charter = ""
        else:
            _record_issue(edge.provider_lib, "missing_charter", "charter.md not found")
            provider_charter = ""

        consumer_spec_index = _read_spec_index(consumer_dir)
        provider_spec_index = _read_spec_index(provider_dir)
        consumer_decisions_index = _read_decisions_index(consumer_dir)
        provider_decisions_index = _read_decisions_index(provider_dir)

        consumer_elements = _extract_elements(consumer_spec_index, edge.consumer_elements)
        provider_elements = _extract_elements(provider_spec_index, edge.provider_elements)
        consumer_decisions = _extract_decisions(consumer_decisions_index, edge.consumer_elements)
        provider_decisions = _extract_decisions(provider_decisions_index, edge.provider_elements)

        consumer_component = architecture_components.get(edge.consumer_lib)
        provider_component = architecture_components.get(edge.provider_lib)

        bundle = {
            "edge": edge.model_dump(),
            "consumer": {
                "lib_id": edge.consumer_lib,
                "charter": consumer_charter,
                "elements": consumer_elements,
                "decisions": consumer_decisions,
            },
            "provider": {
                "lib_id": edge.provider_lib,
                "charter": provider_charter,
                "elements": provider_elements,
                "decisions": provider_decisions,
            },
            "architecture": {
                "consumer_component": {
                    "name": consumer_component,
                    "description": component_descriptions.get(consumer_component or "", ""),
                }
                if consumer_component
                else None,
                "provider_component": {
                    "name": provider_component,
                    "description": component_descriptions.get(provider_component or "", ""),
                }
                if provider_component
                else None,
            },
        }

        bundles[edge.edge_id] = bundle

    return bundles


def extract_interface_edges(run_id: str) -> dict[str, Any]:
    """Extract interface edges for Phase 8."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized.")

    stabilization_status = manager.state.phases[Phase.SPEC_STABILIZATION.value].status
    if stabilization_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Spec stabilization must be completed before interface extraction.")

    mapping_status = manager.state.phases[Phase.ARCHITECTURE_MAPPING.value].status
    if mapping_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Architecture mapping must be completed before interface extraction.")

    manager.start_phase(Phase.INTERFACES)
    issues: list[dict[str, Any]] = []
    phase_result = manager.state.phases[Phase.INTERFACES.value]
    phase_result.issues = issues
    _set_issue_sink(issues)

    try:
        allocated_library_ids = manager.allocated_library_ids

        deterministic_edges = _scan_spec_indexes_for_lib_mentions(manager)
        logger.info(
            "Deterministic edge scan found %d candidate edges.",
            len(deterministic_edges),
        )

        llm_edges = _extract_edges_via_llm(manager, allocated_library_ids)
        logger.info("LLM edge extraction found %d candidate edges.", len(llm_edges))

        edges = _merge_and_deduplicate_edges(deterministic_edges, llm_edges)
        logger.info("Merged edge list contains %d edges.", len(edges))

        element_lookup = _build_element_lookup(manager)
        validation_errors: list[dict[str, Any]] = []
        for edge in edges:
            is_valid, errors = validate_edge_references(edge, allocated_library_ids, element_lookup)
            if not is_valid:
                for message in errors:
                    error_entry = {
                        "lib_id": edge.consumer_lib,
                        "error_type": "edge_validation",
                        "message": message,
                        "edge_id": edge.edge_id,
                    }
                    validation_errors.append(error_entry)
                    issues.append(error_entry)

        context_bundles = build_edge_context_bundles(edges, manager)

        outputs_dir = manager.workspace_path / "agent_outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        edge_list = EdgeListSchema(
            run_id=run_id,
            generated_at=time.now().isoformat(),
            edges=edges,
        )
        edge_candidates_path = outputs_dir / "edge_candidates.json"
        edge_candidates_path.write_text(
            json.dumps(edge_list.model_dump(), indent=2),
            encoding="utf-8",
        )

        edge_contexts_path = outputs_dir / "edge_contexts.json"
        edge_contexts_path.write_text(
            json.dumps(context_bundles, indent=2),
            encoding="utf-8",
        )

        outputs = {
            "edges_count": len(edges),
            "edges": [edge.model_dump() for edge in edges],
            "validation_errors": validation_errors,
            "context_bundles_count": len(context_bundles),
        }
        manager.complete_phase(Phase.INTERFACES, outputs=outputs)
        return outputs
    except Exception as exc:
        manager.fail_phase(Phase.INTERFACES, error=str(exc))
        raise
    finally:
        _set_issue_sink(None)
