from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.refinement.formats import _extract_json_payload

LABEL_BY_LIB = {
    "LIB-0001": "Core Workflow",
    "LIB-0002": "Integration Ops",
    "LIB-0003": "Edge Handling",
}


def _stable_bucket(key: str) -> float:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:8]  # noqa: S324
    return int(digest, 16) / 0xFFFFFFFF


def _should_violate(key: str, rate: float) -> bool:
    return _stable_bucket(key) < rate


def _extract_first(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    if not match:
        return None
    if match.lastindex:
        return match.group(1)
    return match.group(0)


def _extract_file_id(prompt: str) -> str | None:
    labeled = _extract_first(r"Current File ID:\s*(F\d{4})", prompt)
    if labeled:
        return labeled
    labeled = _extract_first(r"File ID:\s*(F\d{4})", prompt)
    if labeled:
        return labeled
    return _extract_first(r"\bF\d{4}\b", prompt)


def _extract_lib_id(prompt: str) -> str | None:
    labeled = _extract_first(r"Library ID:\s*(LIB-\d{4})", prompt)
    if labeled:
        return labeled
    labeled = _extract_first(r"Library (LIB-\d{4}) Charter", prompt)
    if labeled:
        return labeled
    labeled = _extract_first(r"Library (LIB-\d{4}) Spec", prompt)
    if labeled:
        return labeled
    return _extract_first(r"\bLIB-\d{4}\b", prompt)


def _pick_first(items: list[str]) -> str:
    return items[0] if items else "UNKNOWN"


def _make_summary(file_id: str, sections: list[str], *, violation: str | None = None) -> str:
    primary = _pick_first(sections)
    secondary = sections[1] if len(sections) > 1 else primary
    tertiary = sections[2] if len(sections) > 2 else primary

    evidence_primary = f"[{file_id}::{primary}]"
    evidence_secondary = f"[{file_id}::{secondary}]"
    evidence_tertiary = f"[{file_id}::{tertiary}]"

    if violation == "invalid_file":
        evidence_primary = "[F0999::INTRO]"
    elif violation == "invented_section":
        evidence_secondary = f"[{file_id}::INVENTED]"
    elif violation == "compound_pointer":
        evidence_tertiary = f"[{file_id}::{primary}, {file_id}::{secondary}]"

    lines = [
        f"# File Summary: {file_id}",
        f"File ID: {file_id}",
        "",
        "## Algorithms",
        f"- Validate Intake | Ensure payload sanity | Evidence: {evidence_primary}",
        "",
        "## Components",
        f"- Intake API | Accept requests | Evidence: {evidence_secondary}",
        "",
        "## Workflows",
        f"- Intake Flow | Validate then route | Evidence: {evidence_tertiary}",
        "",
        "## Candidate Responsibilities",
        f"- Maintain ingestion contracts | Evidence: {evidence_primary}",
        "",
        "## Dependencies",
        "- None",
        "",
        "## Evidence Map",
    ]
    for section in sections:
        lines.append(f"- {section}: [{file_id}::{section}]")

    if violation == "missing_evidence":
        lines.append("- MissingEvidence: none")

    if violation == "trailing_fence":
        lines.append("```")

    if violation == "stray_preamble":
        lines.insert(0, "Here is the summary output:")

    return "\n".join(lines).rstrip() + "\n"


def mock_summarization_agent(
    file_id: str,
    content: str,
    sections: list[str],
    *,
    violation_rate: float,
) -> str:
    _ = content
    violation_modes = [
        "invalid_file",
        "invented_section",
        "compound_pointer",
        "missing_evidence",
        "trailing_fence",
        "stray_preamble",
    ]
    key = f"summary:{file_id}"
    if _should_violate(key, violation_rate):
        mode = violation_modes[
            int(_stable_bucket(key) * len(violation_modes)) % len(violation_modes)
        ]
        return _make_summary(file_id, sections, violation=mode)
    return _make_summary(file_id, sections)


def mock_library_labeling_agent(
    file_id: str,
    section: str,
    label: str,
    *,
    violation_rate: float,
) -> str:
    key = f"label:{file_id}"
    if _should_violate(key, violation_rate):
        # Missing candidate_labels field to trigger repair.
        payload = {
            "file_id": file_id,
            "uncertain_labels": [{"label": label, "rationale": "Insufficient evidence."}],
        }
        return json.dumps(payload)

    payload = {
        "file_id": file_id,
        "candidate_labels": [
            {
                "label": label,
                "sections": [f"[{file_id}::{section}]"],
                "confidence": 0.78,
                "rationale": "Summary aligns with library capability.",
            }
        ],
        "uncertain_labels": [],
    }
    return json.dumps(payload)


def mock_library_refiner_agent(library_ids: list[str], *, violation_rate: float) -> str:
    key = "refiner:" + ":".join(sorted(library_ids))
    payload = []
    for lib_id in library_ids:
        payload.append(
            {
                "lib_id": lib_id,
                "final_label": LABEL_BY_LIB.get(lib_id, lib_id),
                "merged_from": [LABEL_BY_LIB.get(lib_id, lib_id)],
                "split_notes": "",
                "stable_internal_id": lib_id,
            }
        )

    if _should_violate(key, violation_rate) and payload:
        payload[0]["lib_id"] = "lib_bad"

    return json.dumps(payload)


def mock_charter_generator_agent(
    lib_id: str,
    evidence: list[tuple[str, str]],
    *,
    violation_rate: float,
) -> str:
    key = f"charter:{lib_id}"
    evidence_lines = [f"- [{file_id}::{section}]" for file_id, section in evidence]

    if _should_violate(key, violation_rate) and evidence_lines:
        evidence_lines[0] = "- [F0999::MISSING]"

    lines = [
        "## Library Index",
        f"- {lib_id}: {LABEL_BY_LIB.get(lib_id, 'Library')}",
        "",
        "## Library Charters",
        f"### {lib_id}",
        "#### Intent",
        f"Own {LABEL_BY_LIB.get(lib_id, 'core')} responsibilities.",
        "",
        "#### Boundaries",
        "Covers intake, validation, and routing workflows.",
        "",
        "#### Responsibilities",
        "- Maintain core workflow surfaces",
        "- Coordinate downstream handoffs",
        "",
        "#### Evidence",
        *evidence_lines,
        "",
        "#### Overlap Resolutions",
        "- None",
    ]

    if _should_violate(key + ":preamble", violation_rate):
        lines.insert(0, "Here is the charter:")

    if _should_violate(key + ":fence", violation_rate):
        lines.append("```")

    return "\n".join(lines).rstrip() + "\n"


def mock_overlap_resolver_agent(lib_a: str, lib_b: str, *, violation_rate: float) -> str:
    key = f"overlap:{lib_a}:{lib_b}"
    if _should_violate(key, violation_rate):
        return json.dumps({"decision": "invalid", "rationale": "bad"})
    return json.dumps(
        {
            "decision": "assign_to_lib_A",
            "rationale": "Overlap belongs to library A.",
            "affected_files": [],
        }
    )


def mock_evidence_mapper_agent(
    lib_id: str,
    file_id: str,
    sections: list[str],
    *,
    violation_rate: float,
) -> str:
    key = f"evidence:{lib_id}:{file_id}"
    if _should_violate(key, violation_rate):
        return json.dumps(
            {
                "file_id": "F0999",
                "relevant_sections": ["INVENTED"],
                "confidence": 1.2,
                "rationale": "Invalid evidence",
            }
        )

    selected = sections[:2] if len(sections) >= 2 else sections
    return json.dumps(
        {
            "file_id": file_id,
            "relevant_sections": selected,
            "confidence": 0.82,
            "rationale": "Directly supports charter intent.",
        }
    )


def mock_spec_integrator_agent(
    lib_id: str,
    file_id: str,
    sections: list[str],
    *,
    violation_rate: float,
    violation_mode: str = "invalid_citation",
) -> str:
    key = f"spec:{lib_id}:{file_id}"
    valid_sections = sections or ["INTRO"]
    if _should_violate(key, violation_rate):
        if violation_mode == "compound_pointer":
            primary = valid_sections[0]
            secondary = valid_sections[1] if len(valid_sections) > 1 else primary
            return json.dumps(
                {
                    "file_id": file_id,
                    "lib_id": lib_id,
                    "patches": [
                        {
                            "op": "add",
                            "section": "Requirements",
                            "bullet_index": None,
                            "content": "Compound pointer case.",
                            "citations": [f"[{file_id}::{primary}, {file_id}::{secondary}]"],
                        }
                    ],
                }
            )
        if violation_mode == "invalid_op":
            return json.dumps(
                {
                    "file_id": file_id,
                    "lib_id": lib_id,
                    "patches": [
                        {
                            "op": "delete",
                            "section": "Requirements",
                            "bullet_index": 0,
                            "content": "",
                            "citations": [f"[{file_id}::{valid_sections[0]}]"],
                        }
                    ],
                }
            )
        return json.dumps(
            {
                "file_id": file_id,
                "lib_id": lib_id,
                "patches": [
                    {
                        "op": "add",
                        "section": "Requirements",
                        "bullet_index": None,
                        "content": "Missing citation case.",
                        "citations": [f"[F0999::{valid_sections[0]}]"],
                    }
                ],
            }
        )

    return json.dumps(
        {
            "file_id": file_id,
            "lib_id": lib_id,
            "patches": [
                {
                    "op": "add",
                    "section": "Requirements",
                    "bullet_index": None,
                    "content": f"Supports {LABEL_BY_LIB.get(lib_id, lib_id)} processing.",
                    "citations": [f"[{file_id}::{section}]" for section in valid_sections],
                }
            ],
        }
    )


def mock_gap_auditor_agent(
    file_id: str,
    *,
    violation_rate: float,
) -> str:
    key = f"gap:{file_id}"
    if _should_violate(key, violation_rate):
        return "not-json"
    return json.dumps({"gaps": [], "total_gaps": 0, "file_id": file_id})


def mock_architecture_brief_extractor_agent(
    lib_id: str,
    *,
    violation_rate: float,
) -> str:
    key = f"brief:{lib_id}"
    payload = {
        "lib_id": lib_id,
        "intent": f"Support {LABEL_BY_LIB.get(lib_id, lib_id)}",
        "boundaries": "Defines core constraints and dependencies.",
        "dependencies": ["External API"],
        "constraints": [
            {
                "type": "Latency",
                "description": "Keep response time under 200ms.",
                "citation": f"[{lib_id}::spec.md::CONSTRAINTS]",
            }
        ],
        "interfaces": [
            {
                "type": "HTTP",
                "description": "Expose intake endpoints.",
                "citation": f"[{lib_id}::spec.md::API]",
            }
        ],
    }
    if _should_violate(key, violation_rate):
        payload["constraints"][0]["citation"] = "[LIB-0999::spec.md::MISSING]"
    return json.dumps(payload)


def mock_architecture_proposer_agent(
    library_ids: list[str],
    *,
    violation_rate: float,
) -> str:
    candidates = []
    for idx in range(1, 4):
        lib_id = library_ids[0] if library_ids else "LIB-0001"
        candidates.append(
            {
                "arch_id": f"arch_00{idx}",
                "pattern": "Layered Services",
                "description": f"Candidate {idx} focusing on separation of concerns.",
                "components": [
                    {
                        "name": "API Layer",
                        "responsibilities": ["Intake", "Validation"],
                    },
                    {
                        "name": "Core Layer",
                        "responsibilities": ["Routing", "Coordination"],
                    },
                ],
                "communication": "Synchronous HTTP",
                "deployment": "Single service",
                "citations": [f"[{lib_id}::charter.md]"],
                "tradeoffs": {
                    "advantages": ["Clear boundaries"],
                    "disadvantages": ["Potential latency"],
                },
            }
        )

    if _should_violate("arch_proposer", violation_rate) and candidates:
        candidates[0]["citations"] = ["[F0001::INTRO]"]

    return json.dumps(candidates)


def mock_architecture_selector_agent(
    candidates: list[str],
    *,
    violation_rate: float,
) -> str:
    selected = candidates[0] if candidates else "arch_001"
    payload = {
        "selected_arch_id": selected,
        "rationale": "Best balance of modularity. [LIB-0001::charter.md]",
        "rejected_architectures": [],
        "implementation_risks": ["Boundary drift"],
        "evolution_notes": "Review after scale testing.",
    }
    if _should_violate("arch_selector", violation_rate):
        payload["rationale"] = "Missing citations"
    return json.dumps(payload)


def mock_architecture_mapper_agent(
    lib_id: str,
    component: str,
    *,
    violation_rate: float,
    violation_mode: str = "invalid_citation",
) -> str:
    payload = {
        "lib_id": lib_id,
        "component": component,
        "rationale": f"{lib_id} aligns with {component}.",
        "citations": [f"[{lib_id}::charter.md]"],
        "cross_component_dependencies": [
            {
                "target_component": "Data Layer",
                "reason": "Needs storage access.",
                "citation": f"[{lib_id}::spec.md::CONSTRAINTS]",
            }
        ],
    }
    if _should_violate(f"arch_map:{lib_id}", violation_rate):
        if violation_mode == "missing_citations":
            payload.pop("citations")
        else:
            payload["citations"] = ["[F0001::INTRO]"]
    return json.dumps(payload)


def _extract_interface_bundle(prompt: str) -> dict[str, Any]:
    if not prompt:
        return {}
    try:
        payload = _extract_json_payload(prompt)
    except Exception:
        payload = ""
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _build_interface_contract_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    edge = bundle.get("edge", {}) if isinstance(bundle, dict) else {}
    consumer = bundle.get("consumer", {}) if isinstance(bundle, dict) else {}
    provider = bundle.get("provider", {}) if isinstance(bundle, dict) else {}
    architecture = bundle.get("architecture", {}) if isinstance(bundle, dict) else {}

    edge_id = edge.get("edge_id", "EDGE-LIB-0001-LIB-0002")
    consumer_lib = edge.get("consumer_lib") or consumer.get("lib_id") or "LIB-0001"
    provider_lib = edge.get("provider_lib") or provider.get("lib_id") or "LIB-0002"

    consumer_elements = [
        elem.get("element_id") for elem in consumer.get("elements", []) if isinstance(elem, dict)
    ]
    provider_elements = [
        elem.get("element_id") for elem in provider.get("elements", []) if isinstance(elem, dict)
    ]

    consumer_requirement = consumer_elements[0] if consumer_elements else "REQ-LIB-0001-0001"
    provider_requirement = provider_elements[0] if provider_elements else "REQ-LIB-0002-0001"

    consumer_component = architecture.get("consumer_component") or {}
    provider_component = architecture.get("provider_component") or {}
    provider_component_name = (
        provider_component.get("name") if isinstance(provider_component, dict) else None
    )
    provider_component_desc = (
        provider_component.get("description") if isinstance(provider_component, dict) else None
    )
    consumer_component_name = (
        consumer_component.get("name") if isinstance(consumer_component, dict) else None
    )

    details = "Provides the primary interface."
    if provider_component_name:
        details = f"{details} Runs in {provider_component_name}."
        if provider_component_desc:
            details = f"{details} {provider_component_desc}"

    expectations = ["Availability 99.9%"]
    if consumer_component_name:
        expectations.append(f"Aligned with {consumer_component_name} responsibilities.")

    decisions: list[str] = []
    for source in (consumer, provider):
        for decision in source.get("decisions", []) if isinstance(source, dict) else []:
            decision_id = decision.get("decision_id") if isinstance(decision, dict) else None
            if isinstance(decision_id, str):
                decisions.append(decision_id)

    seen_decisions: set[str] = set()
    open_questions: list[str] = []
    for item in decisions:
        if item in seen_decisions:
            continue
        seen_decisions.add(item)
        open_questions.append(item)

    return {
        "edge_id": edge_id,
        "consumer_lib": consumer_lib,
        "provider_lib": provider_lib,
        "contract_version": "v1",
        "provided": [
            {
                "name": "Primary Interface",
                "type": "http",
                "requirements": [provider_requirement],
                "details": details,
                "acceptance": ["Returns expected payload"],
                "citations": [f"[{provider_lib}::spec.md::{provider_requirement}]"],
            }
        ],
        "consumed_by": [
            {
                "consumer_requirement": consumer_requirement,
                "expectations": expectations,
                "citations": [f"[{consumer_lib}::spec.md::{consumer_requirement}]"],
            }
        ],
        "data_contract": {
            "schemas": ["schemas/interface.json"],
            "compatibility": "Backward compatible",
        },
        "operational": {
            "performance": "p95 < 200ms",
            "failure_modes": "Graceful degradation",
            "security": "OAuth2",
        },
        "open_questions": open_questions,
    }


def _format_interface_contract_markdown(contract: dict[str, Any]) -> str:
    edge_id = contract.get("edge_id", "")
    consumer_lib = contract.get("consumer_lib", "")
    provider_lib = contract.get("provider_lib", "")
    lines = [
        "# Interface Contract",
        "",
        "## Purpose",
        f"- Edge ID: {edge_id}",
        f"- Consumer: {consumer_lib}",
        f"- Provider: {provider_lib}",
        "",
        "## Provided",
        "- Primary Interface",
        "",
        "## Consumed",
        "- Consumer Expectations",
        "",
        "## Data Contract",
        "- Schemas: interface.json",
        "",
        "## Operational",
        "- Performance: p95 < 200ms",
        "",
        "## Open Questions",
        "- None",
        "",
        "## Evidence",
        "- See citations in JSON",
    ]
    return "\n".join(lines).rstrip() + "\n"


def mock_interface_edge_extractor_agent(
    prompt: str,
    *,
    violation_rate: float,
    violation_mode: str | None = None,
    edges_by_lib: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    lib_id = _extract_lib_id(prompt) or "LIB-0001"

    edges = []
    if edges_by_lib and lib_id in edges_by_lib:
        edges = edges_by_lib[lib_id]
    elif lib_id == "LIB-0001":
        edges = [
            {
                "provider_lib": "LIB-0002",
                "consumer_elements": ["REQ-LIB-0001-0001"],
                "kind": "api",
                "summary": "Consumes provider API for lookups.",
                "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0001]"],
            },
            {
                "provider_lib": "LIB-0003",
                "consumer_elements": ["REQ-LIB-0001-0002"],
                "kind": "events",
                "summary": "Subscribes to provider events.",
                "evidence": ["[LIB-0001::spec.md::REQ-LIB-0001-0002]"],
            },
        ]

    violation_modes = [
        "invalid_provider_lib",
        "missing_consumer_elements",
        "invalid_kind",
    ]
    key = f"interface_edge:{lib_id}"
    mode = violation_mode
    if mode is None and _should_violate(key, violation_rate):
        mode = violation_modes[
            int(_stable_bucket(key) * len(violation_modes)) % len(violation_modes)
        ]

    if mode and edges:
        if mode == "invalid_provider_lib":
            edges[0]["provider_lib"] = "LIB-9999"
        elif mode == "missing_consumer_elements":
            edges[0]["consumer_elements"] = ["REQ-LIB-0001-9999"]
        elif mode == "invalid_kind":
            edges[0]["kind"] = "unknown"

    return json.dumps({"edges": edges})


def mock_interface_contract_writer_agent(
    prompt: str,
    *,
    violation_rate: float,
    violation_mode: str | None = None,
) -> str:
    bundle = _extract_interface_bundle(prompt)
    contract = _build_interface_contract_payload(bundle)

    key = f"interface_contract:{contract.get('edge_id', 'EDGE')}"
    mode = violation_mode
    if mode is None and _should_violate(key, violation_rate):
        modes = ["invalid_citation", "missing_sections", "invalid_element_ids"]
        mode = modes[int(_stable_bucket(key) * len(modes)) % len(modes)]

    if mode == "invalid_citation":
        contract["provided"][0]["citations"] = ["[F0999::INTRO]"]
    elif mode == "missing_sections":
        contract.pop("consumed_by", None)
    elif mode == "invalid_element_ids":
        contract["provided"][0]["requirements"] = ["REQ-INVALID"]

    markdown = _format_interface_contract_markdown(contract)
    payload = json.dumps(contract, indent=2)
    return "\n".join([markdown, "```json", payload, "```"])


def mock_interface_contract_judge_agent(
    prompt: str,
    *,
    violation_rate: float,
) -> str:
    key = "interface_contract_judge"
    if _should_violate(key, violation_rate):
        return json.dumps({"valid": False, "errors": ["Schema mismatch"]})
    return json.dumps({"valid": True, "errors": []})


def mock_interface_contract_repairer_agent(
    prompt: str,
    *,
    violation_rate: float,
) -> str:
    key = "interface_contract_repair"
    if _should_violate(key, violation_rate):
        return "not-json"
    bundle = _extract_interface_bundle(prompt)
    contract = _build_interface_contract_payload(bundle)
    markdown = _format_interface_contract_markdown(contract)
    payload = json.dumps(contract, indent=2)
    return "\n".join([markdown, "```json", payload, "```"])


def mock_repair_agent(
    artifact_type: str,
    file_id: str | None,
    lib_id: str | None,
    sections: list[str],
) -> str:
    target_file = file_id or "F0001"
    target_section = _pick_first(sections)
    target_lib = lib_id or "LIB-0001"

    if artifact_type == "summary":
        return _make_summary(target_file, sections)

    if artifact_type == "library_labels":
        payload = {
            "file_id": target_file,
            "candidate_labels": [
                {
                    "label": LABEL_BY_LIB.get(target_lib, target_lib),
                    "sections": [f"[{target_file}::{target_section}]"],
                    "confidence": 0.8,
                    "rationale": "Repair: corrected fields.",
                }
            ],
            "uncertain_labels": [],
        }
        return json.dumps(payload)

    if artifact_type == "charter":
        return mock_charter_generator_agent(
            target_lib,
            [(target_file, target_section)],
            violation_rate=0.0,
        )

    if artifact_type == "evidence_json":
        payload = {
            "file_id": target_file,
            "sections": [target_section],
            "confidence": 0.8,
            "rationale": "Repair: valid evidence.",
        }
        return json.dumps(payload)

    if artifact_type == "spec_patches":
        repair_sections = sections if sections else [target_section]
        payload = {
            "file_id": target_file,
            "lib_id": target_lib,
            "operations": [
                {
                    "op": "add",
                    "section": "Requirements",
                    "bullet_index": None,
                    "content": "Repair: restore missing content.",
                    "citations": [f"[{target_file}::{s}]" for s in repair_sections],
                }
            ],
        }
        return json.dumps(payload)

    if artifact_type == "architecture_selection":
        payload = {
            "selected_arch_id": "arch_001",
            "rationale": f"Repair: aligned with constraints. [{target_lib}::charter.md]",
            "rejected_architectures": [],
            "implementation_risks": [],
            "evolution_notes": "Repair applied.",
        }
        return json.dumps(payload)

    if artifact_type == "architecture_mapping":
        mapping_lines = [
            "# Architecture Mapping",
            "",
            "## Architecture",
            "arch_001",
            "",
            "## Component Mappings",
            "",
            "### Component: API Layer",
            "",
            "**Responsibilities**: Intake",
            "",
            "**Libraries**:",
            f"- {target_lib}: Core responsibilities [{target_lib}::charter.md]",
            "",
            "## Cross-Component Dependencies",
            f"- API Layer -> Data Layer: storage [{target_lib}::spec.md::CONSTRAINTS]",
            "",
            "## Unmapped Libraries",
            "- None",
        ]
        return "\n".join(mapping_lines).rstrip() + "\n"

    return ""


@dataclass
class MockAgentController:
    manifest: dict[str, dict[str, Any]]
    violation_rate: float = 0.15
    violation_overrides: dict[str, float] = field(default_factory=dict)
    spec_patch_violation: str = "invalid_citation"
    mapping_violation_mode: str = "invalid_citation"
    gap_mode: str = "empty"
    repair_success_rate: float = 0.9
    interface_edge_violation_mode: str | None = None
    interface_contract_violation_mode: str | None = None
    interface_edges_by_lib: dict[str, list[dict[str, Any]]] | None = None
    interface_contract_overrides: dict[str, str] = field(default_factory=dict)
    call_log: list[dict[str, Any]] = field(default_factory=list)
    repair_calls: list[dict[str, Any]] = field(default_factory=list)

    def _file_ids(self) -> list[str]:
        file_ids = [key for key in self.manifest if re.fullmatch(r"F\d{4}", key)]
        return sorted(file_ids)

    def _sections(self, file_id: str) -> list[str]:
        entry = self.manifest.get(file_id, {})
        sections = entry.get("sections", []) if isinstance(entry, dict) else []
        return [section for section in sections if isinstance(section, str)]

    def _libraries(self) -> list[str]:
        if "library_ids" in self.manifest:
            library_ids = self.manifest.get("library_ids")
            if isinstance(library_ids, list) and library_ids:
                return sorted([lib_id for lib_id in library_ids if isinstance(lib_id, str)])
        if "libraries" in self.manifest:
            libraries = self.manifest.get("libraries")
            if isinstance(libraries, dict) and libraries:
                return sorted([lib_id for lib_id in libraries if isinstance(lib_id, str)])

        libs: set[str] = set()
        for entry in self.manifest.values():
            for lib_id in entry.get("expected_libraries", []):
                libs.add(lib_id)
        return sorted(libs) if libs else ["LIB-0001"]

    def _file_to_lib(self, file_id: str) -> str:
        entry = self.manifest.get(file_id, {})
        libs = entry.get("expected_libraries", []) if isinstance(entry, dict) else []
        return libs[0] if libs else "LIB-0001"

    def dispatch(
        self,
        *,
        agent_name: str,
        prompt: str,
        workspace: Path,
        max_retries: int = 2,
        structured_schema: Any | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> str:
        _ = workspace
        _ = max_retries
        _ = structured_schema
        _ = extra_env

        self.call_log.append({"agent_name": agent_name, "prompt": prompt})
        effective_rate = self.violation_overrides.get(agent_name, self.violation_rate)

        if agent_name == "glm-file-what-summarizer":
            file_id = _extract_file_id(prompt) or _pick_first(self._file_ids())
            sections = self._sections(file_id)
            return mock_summarization_agent(
                file_id,
                prompt,
                sections,
                violation_rate=effective_rate,
            )

        if agent_name == "glm-file-library-labeler":
            file_id = _extract_file_id(prompt) or _pick_first(self._file_ids())
            section = _pick_first(self._sections(file_id))
            label = LABEL_BY_LIB.get(self._file_to_lib(file_id), "Core Workflow")
            return mock_library_labeling_agent(
                file_id,
                section,
                label,
                violation_rate=effective_rate,
            )

        if agent_name == "opus-library-label-refiner":
            return mock_library_refiner_agent(
                self._libraries(),
                violation_rate=0.0,
            )

        if agent_name == "opus-library-synthesizer":
            lib_id = _extract_lib_id(prompt) or _pick_first(self._libraries())
            file_ids = [fid for fid in self._file_ids() if self._file_to_lib(fid) == lib_id]
            evidence = [(fid, _pick_first(self._sections(fid))) for fid in file_ids]
            return mock_charter_generator_agent(lib_id, evidence, violation_rate=effective_rate)

        if agent_name == "glm-library-overlap-resolver":
            lib_ids = self._libraries()
            lib_a = lib_ids[0]
            lib_b = lib_ids[1] if len(lib_ids) > 1 else lib_a
            return mock_overlap_resolver_agent(lib_a, lib_b, violation_rate=effective_rate)

        if agent_name == "glm-library-relevance-classifier":
            # Minimal classifier response
            return json.dumps({"relevant": "yes", "rationale": "Likely related", "confidence": 0.7})

        if agent_name == "glm-library-evidence-mapper":
            file_id = _extract_file_id(prompt) or _pick_first(self._file_ids())
            lib_id = _extract_lib_id(prompt) or self._file_to_lib(file_id)
            sections = self._sections(file_id)
            return mock_evidence_mapper_agent(
                lib_id, file_id, sections, violation_rate=effective_rate
            )

        if agent_name == "glm-library-spec-integrator":
            file_id = _extract_file_id(prompt) or _pick_first(self._file_ids())
            lib_id = _extract_lib_id(prompt) or self._file_to_lib(file_id)
            sections = self._sections(file_id)[:2]
            return mock_spec_integrator_agent(
                lib_id,
                file_id,
                sections,
                violation_rate=effective_rate,
                violation_mode=self.spec_patch_violation,
            )

        if agent_name == "chatgpt-library-spec-gap-judge":
            file_id = _extract_file_id(prompt) or "F0001"
            if self.gap_mode == "persistent":
                return json.dumps(
                    {
                        "gaps": [
                            {
                                "source": f"[{file_id}::INTRO]",
                                "missing_content": "Missing requirement details.",
                                "where_in_spec": "Requirements",
                                "severity": "must",
                            }
                        ],
                        "total_gaps": 1,
                        "file_id": file_id,
                    }
                )
            return mock_gap_auditor_agent(file_id, violation_rate=effective_rate)

        if agent_name == "opus-sublibrary-planner":
            return json.dumps({"sub_libraries": []})

        if agent_name == "glm-architecture-brief-extractor":
            lib_id = _extract_lib_id(prompt) or _pick_first(self._libraries())
            return mock_architecture_brief_extractor_agent(lib_id, violation_rate=effective_rate)

        if agent_name == "opus-architecture-proposer":
            return mock_architecture_proposer_agent(
                self._libraries(), violation_rate=effective_rate
            )

        if agent_name == "chatgpt-architecture-tradeoff-judge":
            candidates = re.findall(r"arch_\d{3}", prompt)
            return mock_architecture_selector_agent(candidates, violation_rate=effective_rate)

        if agent_name == "glm-architecture-library-mapper":
            lib_id = _extract_lib_id(prompt) or _pick_first(self._libraries())
            component = "API Layer"
            return mock_architecture_mapper_agent(
                lib_id,
                component,
                violation_rate=effective_rate,
                violation_mode=self.mapping_violation_mode,
            )

        if agent_name == "glm-interface-edge-extractor":
            return mock_interface_edge_extractor_agent(
                prompt,
                violation_rate=effective_rate,
                violation_mode=self.interface_edge_violation_mode,
                edges_by_lib=self.interface_edges_by_lib,
            )

        if agent_name == "opus-interface-contract-writer":
            bundle = _extract_interface_bundle(prompt)
            edge_id = ""
            if isinstance(bundle, dict):
                edge = bundle.get("edge", {})
                if isinstance(edge, dict):
                    edge_id = (
                        edge.get("edge_id", "") if isinstance(edge.get("edge_id"), str) else ""
                    )
            violation_mode = self.interface_contract_violation_mode
            if edge_id and edge_id in self.interface_contract_overrides:
                violation_mode = self.interface_contract_overrides[edge_id]
            return mock_interface_contract_writer_agent(
                prompt,
                violation_rate=effective_rate,
                violation_mode=violation_mode,
            )

        if agent_name == "chatgpt-interface-contract-judge":
            return mock_interface_contract_judge_agent(
                prompt,
                violation_rate=effective_rate,
            )

        if agent_name == "chatgpt-interface-contract-repairer":
            self.repair_calls.append(
                {"artifact_type": "interface_contract", "file_id": None, "lib_id": None}
            )
            return mock_interface_contract_repairer_agent(
                prompt,
                violation_rate=effective_rate,
            )

        if agent_name.startswith("repair-"):
            artifact_type = agent_name.replace("repair-", "").replace("-", "_")
            file_id = _extract_file_id(prompt)
            lib_id = _extract_lib_id(prompt)
            if file_id not in self._file_ids():
                file_id = _pick_first(self._file_ids())
            if lib_id not in self._libraries():
                lib_id = _pick_first(self._libraries())
            sections = (
                self._sections(file_id)
                if file_id
                else self._sections(_pick_first(self._file_ids()))
            )
            if not sections:
                sections = self._sections(_pick_first(self._file_ids()))
            self.repair_calls.append(
                {"artifact_type": artifact_type, "file_id": file_id, "lib_id": lib_id}
            )
            return mock_repair_agent(artifact_type, file_id, lib_id, sections)

        raise AssertionError(f"Unexpected agent name: {agent_name}")
