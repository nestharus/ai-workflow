from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LABEL_BY_LIB = {
    "lib_001": "Core Workflow",
    "lib_002": "Integration Ops",
    "lib_003": "Edge Handling",
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
    labeled = _extract_first(r"Library ID:\s*(lib_\d{3})", prompt)
    if labeled:
        return labeled
    labeled = _extract_first(r"Library (lib_\d{3}) Charter", prompt)
    if labeled:
        return labeled
    labeled = _extract_first(r"Library (lib_\d{3}) Spec", prompt)
    if labeled:
        return labeled
    return _extract_first(r"\blib_\d{3}\b", prompt)


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
        payload["constraints"][0]["citation"] = "[lib_999::spec.md::MISSING]"
    return json.dumps(payload)


def mock_architecture_proposer_agent(
    library_ids: list[str],
    *,
    violation_rate: float,
) -> str:
    candidates = []
    for idx in range(1, 4):
        lib_id = library_ids[0] if library_ids else "lib_001"
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
        "rationale": "Best balance of modularity. [lib_001::charter.md]",
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


def mock_repair_agent(
    artifact_type: str,
    file_id: str | None,
    lib_id: str | None,
    sections: list[str],
) -> str:
    target_file = file_id or "F0001"
    target_section = _pick_first(sections)
    target_lib = lib_id or "lib_001"

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
    call_log: list[dict[str, Any]] = field(default_factory=list)
    repair_calls: list[dict[str, Any]] = field(default_factory=list)

    def _file_ids(self) -> list[str]:
        return sorted(self.manifest.keys())

    def _sections(self, file_id: str) -> list[str]:
        entry = self.manifest.get(file_id, {})
        sections = entry.get("sections", []) if isinstance(entry, dict) else []
        return [section for section in sections if isinstance(section, str)]

    def _libraries(self) -> list[str]:
        libs: set[str] = set()
        for entry in self.manifest.values():
            for lib_id in entry.get("expected_libraries", []):
                libs.add(lib_id)
        return sorted(libs) if libs else ["lib_001"]

    def _file_to_lib(self, file_id: str) -> str:
        entry = self.manifest.get(file_id, {})
        libs = entry.get("expected_libraries", []) if isinstance(entry, dict) else []
        return libs[0] if libs else "lib_001"

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

        self.call_log.append({"agent_name": agent_name})
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
