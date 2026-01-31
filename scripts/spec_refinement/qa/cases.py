"""Manual, on-demand QA cases for spec-refinement agent steps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from scripts.spec_refinement.core.gap import Gap, GapEvidence, GapType
from scripts.spec_refinement.qa.validators import (
    validate_architecture_library_mapping_output,
    validate_architecture_proposal_output,
    validate_architecture_selection_output,
    validate_evidence_mapper_output,
    validate_spec_integrator_output,
)
from scripts.spec_refinement.workspace import WorkspaceManager
from scripts.spec_manager.spec_manager.core.gaps import Severity

from scripts.spec_refinement.workflows.architecture import (
    _build_library_mapping_prompt,
    _build_architecture_proposal_prompt,
    _build_architecture_selection_prompt,
)
from scripts.spec_refinement.workflows.evidence_expansion import _build_evidence_prompt
from scripts.spec_refinement.workflows.spec_building import _build_patch_prompt


@dataclass(frozen=True)
class PreparedQaCase:
    case_id: str
    agent_name: str
    description: str
    prompt: str
    acceptance_criteria: list[str]
    allowlists: dict[str, Any]
    postprocess: Callable[[str], str]
    # Validate the *postprocessed* output that the workflow would consume.
    validator: Callable[[str, WorkspaceManager, dict[str, Any]], list[dict[str, Any]]]


@dataclass(frozen=True)
class QaCase:
    case_id: str
    agent_name: str
    description: str

    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:  # pragma: no cover
        raise NotImplementedError


_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "system_medium_v1"


def _identity(text: str) -> str:
    return text


def _write_library(manager: WorkspaceManager, lib_id: str, charter: str, spec: str) -> None:
    lib_dir = manager.structure.libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "charter.md").write_text(charter.strip() + "\n", encoding="utf-8")
    (lib_dir / "spec.md").write_text(spec.strip() + "\n", encoding="utf-8")


def _library_charter(*, title: str, intent: str, boundaries: list[str], responsibilities: list[str]) -> str:
    lines = [
        f"# Library Charter: {title}",
        "",
        "## Intent",
        intent.strip(),
        "",
        "## Boundaries",
    ]
    for item in boundaries:
        lines.append(f"- {item}")
    lines.extend(["", "## Responsibilities"])
    for item in responsibilities:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _library_spec(
    *,
    lib_id: str,
    intent: str,
    boundaries: list[str],
    requirements: list[str],
    constraints: list[str],
    dependencies: list[str],
) -> str:
    lines = [
        f"# Library Spec: {lib_id}",
        "",
        "## Intent",
        intent.strip(),
        "",
        "## Boundaries",
    ]
    for item in boundaries:
        lines.append(f"- {item}")
    lines.extend(["", "## Requirements"])
    for item in requirements:
        lines.append(f"- {item}")
    lines.extend(["", "## Constraints"])
    for item in constraints:
        lines.append(f"- {item}")
    lines.extend(["", "## Dependencies"])
    for item in dependencies:
        lines.append(f"- {item}")
    lines.extend(["", "## Decisions Needed", "- None", ""])
    return "\n".join(lines)


def _extract_constraints_for_arch_prompt(lib_specs: dict[str, str]) -> list[str]:
    """Extract short constraint snippets from specs for architecture proposal prompts.

    We keep this lightweight and deterministic for QA purposes.
    """
    constraints: list[str] = []
    for lib_id, spec in lib_specs.items():
        # Simple: grab the first 3 bullet lines from the Constraints section.
        in_constraints = False
        bullets: list[str] = []
        for line in spec.splitlines():
            if line.strip().lower() == "## constraints":
                in_constraints = True
                continue
            if in_constraints and line.strip().startswith("## "):
                break
            if in_constraints and line.strip().startswith(("-", "*")):
                bullets.append(line.strip().lstrip("-* ").strip())
                if len(bullets) >= 3:
                    break
        for bullet in bullets:
            constraints.append(f"{lib_id}::Constraints: {bullet}")
    return constraints


class EvidenceMapperAllowlistCase(QaCase):
    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        # Map Storage charter -> Gateway file sections.
        lib_id = "lib_002"
        charter = _library_charter(
            title=lib_id,
            intent="Provide durable persistence and retrieval APIs for other components.",
            boundaries=[
                "Owns record storage and retrieval APIs.",
                "Does NOT own request routing or input validation (Gateway owns those).",
            ],
            responsibilities=[
                "Persist records durably",
                "Retrieve records by ID",
                "Support deletion/tombstoning semantics",
            ],
        )
        # Spec only needed for architecture cases; keep minimal.
        spec = _library_spec(
            lib_id=lib_id,
            intent="Durable persistence APIs.",
            boundaries=["Owns record storage + retrieval"],
            requirements=["Store records", "Lookup by ID"],
            constraints=["Encrypt at rest"],
            dependencies=["Used by Gateway"],
        )
        _write_library(manager, lib_id, charter, spec)

        file_id = "file_001"
        valid_sections = manager.get_section_labels(file_id)

        # Summary includes headings like "Components"/"Workflows" which must NOT be used as section IDs.
        summary = """# File Summary: file_001
File ID: file_001

## Algorithms
- Request routing | Map path+method to internal handler | Evidence: [file_001::BOUNDARIES] [file_001::REQUIREMENTS]
- Correlation propagation | Attach and forward correlation_id | Evidence: [file_001::REQUIREMENTS]

## Components
- Gateway | Validate + route inbound requests | Evidence: [file_001::INTRO] [file_001::BOUNDARIES]

## Workflows
- Inbound request | validate -> route -> persist metadata -> publish audit event | Evidence: [file_001::REQUIREMENTS] [file_001::INTEGRATION]

## Candidate Responsibilities
- Own input validation and request routing for external traffic | Evidence: [file_001::BOUNDARIES]
- Persist request/response metadata via Storage | Evidence: [file_001::INTEGRATION]

## Dependencies
- Storage
- Event Bus

## Evidence Map
- INTRO: [file_001::INTRO]
- BOUNDARIES: [file_001::BOUNDARIES]
- REQUIREMENTS: [file_001::REQUIREMENTS]
- CONSTRAINTS: [file_001::CONSTRAINTS]
- INTEGRATION: [file_001::INTEGRATION]
"""

        prompt = _build_evidence_prompt(
            lib_id=lib_id,
            charter_content=charter,
            file_id=file_id,
            summary_content=summary,
            valid_sections=valid_sections,
        )

        acceptance = [
            "Output is valid JSON with keys: file_id, relevant_sections, confidence, rationale.",
            "file_id equals file_001.",
            "relevant_sections is a list and every entry is an exact match from the allow-list.",
            "relevant_sections MUST NOT contain summary headings like 'Components' or 'Workflows'.",
            "Because the Gateway integrates with Storage, relevant_sections should include INTEGRATION.",
        ]

        return PreparedQaCase(
            case_id=self.case_id,
            agent_name=self.agent_name,
            description=self.description,
            prompt=prompt,
            acceptance_criteria=acceptance,
            allowlists={"file_id": file_id, "valid_sections": valid_sections},
            postprocess=_identity,
            validator=validate_evidence_mapper_output,
        )


class SpecIntegratorUnsupportedAssertionCase(QaCase):
    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        # Storage library integration against the Storage source file.
        lib_id = "lib_002"
        charter = _library_charter(
            title=lib_id,
            intent="Provide durable persistence and retrieval APIs for other components.",
            boundaries=[
                "Owns record storage and retrieval APIs.",
                "Does NOT own request routing or input validation (Gateway owns those).",
                # Intentional: this is NOT in the source file and must be reclassified.
                "Does NOT own throughput management.",
            ],
            responsibilities=[
                "Persist records durably",
                "Retrieve records by ID",
                "Support deletion/tombstoning semantics",
            ],
        )

        current_spec = """# Library Spec: lib_002

## Intent
Provide durable persistence APIs. [file_002::INTRO]

## Boundaries
- Owns record storage and retrieval operations. [file_002::BOUNDARIES]
- Does NOT own request validation or request routing. [file_002::BOUNDARIES]
- Does NOT own throughput management. [file_002::BOUNDARIES]

## Requirements
- Store records reliably with an idempotency key. [file_002::REQUIREMENTS]
- Support lookup by ID. [file_002::REQUIREMENTS]

## Constraints
- Data must be encrypted at rest. [file_002::CONSTRAINTS]

## Dependencies
- Called by Gateway for persistence. [file_002::INTEGRATION]

## Decisions Needed
- None
"""

        file_id = "file_002"
        file_path = manager.get_file_path(file_id)
        if file_path is None:
            raise RuntimeError(f"Missing fixture source file for {file_id}.")
        file_content = file_path.read_text(encoding="utf-8")

        evidence_sections = manager.get_section_labels(file_id)
        valid_sections = manager.get_section_labels(file_id)
        valid_file_ids = list(manager.state.file_manifest.keys())

        # Force the integrator to treat the unsupported claim as non-asserted.
        gap = Gap(
            id="qa_gap_001",
            gap_type=GapType.content_mismatch,
            severity=Severity.ERROR,
            source=[f"[{file_id}::BOUNDARIES]"],
            derived_artifact_target=f"libraries/{lib_id}/spec.md",
            description=(
                "Spec asserts 'Does NOT own throughput management' but the source does not mention "
                "throughput management. Reclassify as a Decision Needed rather than asserting it."
            ),
            evidence=[
                GapEvidence(
                    invariant_family="content",
                    description="Unsupported boundary assertion: throughput management.",
                    details={"where_in_spec": "Boundaries"},
                    confidence=1.0,
                    location=f"{file_id}::BOUNDARIES",
                    detector="qa-harness",
                )
            ],
        )

        prompt = _build_patch_prompt(
            lib_id=lib_id,
            charter_content=charter,
            spec_content=current_spec,
            file_id=file_id,
            file_content=file_content,
            evidence_sections=evidence_sections,
            valid_sections=valid_sections,
            valid_file_ids=valid_file_ids,
            gaps=[gap],
        )

        acceptance = [
            "Output is valid JSON matching SpecPatchOutput (file_id, lib_id, patches).",
            "All patch operations are add/edit/move (no delete).",
            "Citations use only [file_###::SECTION] and section labels are from the allow-list.",
            "The unsupported claim about throughput management is moved from Boundaries into Decisions Needed (not asserted in Boundaries after applying patches).",
        ]

        return PreparedQaCase(
            case_id=self.case_id,
            agent_name=self.agent_name,
            description=self.description,
            prompt=prompt,
            acceptance_criteria=acceptance,
            allowlists={
                "lib_id": lib_id,
                "file_id": file_id,
                "valid_sections": valid_sections,
                "valid_file_ids": valid_file_ids,
                "current_spec": current_spec,
            },
            postprocess=_identity,
            validator=validate_spec_integrator_output,
        )


class ArchitectureProposalCase(QaCase):
    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        # Create 4 libraries representing the fixture system.
        libs: dict[str, dict[str, Any]] = {
            "lib_001": {
                "name": "Gateway",
                "intent": "Handle inbound HTTP requests; validate and route; emit audit events.",
                "boundaries": [
                    "Owns request routing + validation for external requests.",
                    "Does NOT own persistence (delegates to Storage).",
                ],
                "requirements": ["Route requests", "Validate inputs", "Propagate correlation_id"],
                "constraints": ["<=5ms p95 overhead", "Do not log secrets"],
                "dependencies": ["Calls lib_002", "Publishes to lib_003"],
            },
            "lib_002": {
                "name": "Storage",
                "intent": "Durable persistence + retrieval APIs.",
                "boundaries": [
                    "Owns record storage + retrieval APIs.",
                    "Does NOT own request routing or validation.",
                ],
                "requirements": ["Store records", "Lookup by ID", "Delete by ID (tombstone)"],
                "constraints": ["Encrypt at rest", "Durability 99.99% monthly"],
                "dependencies": ["Consumed by lib_001 and lib_004"],
            },
            "lib_003": {
                "name": "Event Bus",
                "intent": "Publish/subscribe messaging for audit and domain events.",
                "boundaries": [
                    "Owns event publishing + delivery semantics.",
                    "Does NOT own business logic; transports events only.",
                ],
                "requirements": ["At-least-once delivery", "Consumer groups with offsets"],
                "constraints": ["Order per key", ">=10k events/sec burst"],
                "dependencies": ["Consumes/produces by lib_001 and lib_004"],
            },
            "lib_004": {
                "name": "Domain Services",
                "intent": "Core workflows orchestrating Gateway, Storage, Event Bus.",
                "boundaries": [
                    "Owns domain business logic and orchestration.",
                    "Does NOT own routing/validation (Gateway) or delivery semantics (Event Bus).",
                ],
                "requirements": ["Persist state", "Publish domain events", "Deterministic workflows"],
                "constraints": ["Idempotent execution", "Testable (no hidden I/O)"],
                "dependencies": ["Uses lib_002 and lib_003"],
            },
        }

        lib_charters: dict[str, str] = {}
        lib_specs: dict[str, str] = {}
        for lib_id, info in libs.items():
            charter = _library_charter(
                title=info["name"],
                intent=info["intent"],
                boundaries=info["boundaries"],
                responsibilities=info["requirements"],
            )
            spec = _library_spec(
                lib_id=lib_id,
                intent=info["intent"],
                boundaries=info["boundaries"],
                requirements=info["requirements"],
                constraints=info["constraints"],
                dependencies=info["dependencies"],
            )
            _write_library(manager, lib_id, charter, spec)
            lib_charters[lib_id] = charter
            lib_specs[lib_id] = spec

        constraints = _extract_constraints_for_arch_prompt(lib_specs)
        prompt = _build_architecture_proposal_prompt(lib_charters, lib_specs, constraints)

        acceptance = [
            "Output is a JSON array with 3-5 candidates.",
            "Each candidate has arch_id, pattern, description, components, communication, deployment, citations, tradeoffs.",
            "Citations use ONLY [lib_###::charter.md] or [lib_###::spec.md::SECTION] pointers (no [file_###::...]).",
            "Tradeoffs are concrete and measurable (not vague).",
        ]

        allowlists = {"library_ids": sorted(lib_specs.keys())}

        return PreparedQaCase(
            case_id=self.case_id,
            agent_name=self.agent_name,
            description=self.description,
            prompt=prompt,
            acceptance_criteria=acceptance,
            allowlists=allowlists,
            postprocess=_identity,
            validator=validate_architecture_proposal_output,
        )


class ArchitectureSelectionCase(QaCase):
    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        # Reuse the same libraries as ArchitectureProposalCase for realistic context.
        proposal_case = ArchitectureProposalCase(
            case_id="phase6_arch_proposal",
            agent_name="opus-architecture-proposer",
            description="Internal reuse for selection case setup.",
        )
        prepared = proposal_case.prepare(manager)

        # Provide two candidate architectures to judge: one good, one clearly worse.
        candidates: dict[str, str] = {
            "arch_001": "# Architecture Candidate: arch_001\n\n## Pattern\nLayered monolith\n\n## Description\nSingle deployable with clear layers.\n\n## Components\n- Gateway: routing/validation\n- Domain: workflows\n- Storage: persistence\n- Eventing: publish events\n\n## Communication\nIn-process calls for core flows; async publish for events.\n\n## Deployment\nSingle deployable.\n\n## Tradeoffs\n### Advantages\n- Lower operational complexity\n\n### Disadvantages\n- Harder independent scaling\n\n## Citations\n- [lib_001::charter.md]\n- [lib_002::spec.md::CONSTRAINTS]\n",
            "arch_002": "# Architecture Candidate: arch_002\n\n## Pattern\nMicroservices\n\n## Description\nSplit each library into a separate service.\n\n## Components\n- GatewaySvc\n- DomainSvc\n- StorageSvc\n- EventBusSvc\n\n## Communication\nSynchronous network calls for all interactions.\n\n## Deployment\nFour services.\n\n## Tradeoffs\n### Advantages\n- Independent deploys\n\n### Disadvantages\n- Higher latency and ops burden\n\n## Citations\n- [lib_001::charter.md]\n- [lib_003::spec.md::CONSTRAINTS]\n",
        }

        # Specs created by prepared setup exist in the workspace.
        lib_specs: dict[str, str] = {}
        for lib_dir in sorted(manager.structure.libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            spec_path = lib_dir / "spec.md"
            if spec_path.exists():
                lib_specs[lib_dir.name] = spec_path.read_text(encoding="utf-8")

        prompt = _build_architecture_selection_prompt(candidates, lib_specs)

        acceptance = [
            "Output is valid JSON with selected_arch_id and rationale.",
            "selected_arch_id is one of the provided candidates (arch_001 or arch_002) or null with explanation.",
            "rationale includes library-pointer citations only ([lib_###::...]); no [file_###::...].",
            "Rejected architectures include concrete reasons.",
        ]

        return PreparedQaCase(
            case_id=self.case_id,
            agent_name=self.agent_name,
            description=self.description,
            prompt=prompt,
            acceptance_criteria=acceptance,
            allowlists={"candidate_ids": sorted(candidates.keys()), "library_ids": sorted(lib_specs.keys())},
            postprocess=_identity,
            validator=validate_architecture_selection_output,
        )


class ArchitectureLibraryMappingCase(QaCase):
    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        # Ensure libraries exist with spec sections for citations.
        proposal_case = ArchitectureProposalCase(
            case_id="phase6_arch_proposal",
            agent_name="opus-architecture-proposer",
            description="Internal reuse for mapping case setup.",
        )
        proposal_case.prepare(manager)

        selected_architecture = """# Selected Architecture: arch_001

## Rationale
Layered monolith keeps ops cost low while meeting Gateway latency and Event Bus throughput. [lib_001::spec.md::CONSTRAINTS] [lib_003::spec.md::CONSTRAINTS]

## Selected Candidate
# Architecture Candidate: arch_001

## Pattern
Layered monolith

## Description
Single deployable with clear layers.

## Components
- Gateway: routing/validation
- Domain: workflows
- Storage: persistence
- Eventing: publish events

## Communication
In-process calls for core flows; async publish for events.

## Deployment
Single deployable.
"""
        allowed_components = ["Gateway", "Domain", "Storage", "Eventing"]

        lib_specs: dict[str, str] = {}
        lib_charters: dict[str, str] = {}
        for lib_dir in sorted(manager.structure.libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            charter_path = lib_dir / "charter.md"
            spec_path = lib_dir / "spec.md"
            if charter_path.exists():
                lib_charters[lib_dir.name] = charter_path.read_text(encoding="utf-8")
            if spec_path.exists():
                lib_specs[lib_dir.name] = spec_path.read_text(encoding="utf-8")

        target_lib_id = "lib_002"
        charter = lib_charters.get(target_lib_id, "")
        spec = lib_specs.get(target_lib_id, "")
        prompt = _build_library_mapping_prompt(target_lib_id, selected_architecture, charter, spec)

        acceptance = [
            "Output is valid JSON for a single-library mapping fragment.",
            "lib_id matches the requested library (lib_002).",
            "component matches one of the components listed in the selected architecture.",
            "citations contains at least one library-pointer citation ([lib_###::...]).",
            "No source-file citations like [file_###::...] appear in citations or dependencies.",
        ]

        return PreparedQaCase(
            case_id=self.case_id,
            agent_name="glm-architecture-library-mapper",
            description=self.description,
            prompt=prompt,
            acceptance_criteria=acceptance,
            allowlists={"lib_id": target_lib_id, "components": allowed_components},
            postprocess=_identity,
            validator=validate_architecture_library_mapping_output,
        )


QA_CASES: dict[str, QaCase] = {
    "phase3_evidence_mapper_allowlist": EvidenceMapperAllowlistCase(
        case_id="phase3_evidence_mapper_allowlist",
        agent_name="glm-library-evidence-mapper",
        description=(
            "Evidence mapper must choose relevant_sections only from the provided allow-list and "
            "must not output summary headings like 'Components'/'Workflows'."
        ),
    ),
    "phase4_spec_integrator_unsupported_assertion": SpecIntegratorUnsupportedAssertionCase(
        case_id="phase4_spec_integrator_unsupported_assertion",
        agent_name="glm-library-spec-integrator",
        description=(
            "Spec integrator must produce valid patch ops (no delete), keep citations within the "
            "[file_###::SECTION] allowlists, and reclassify unsupported assertions into Decisions Needed."
        ),
    ),
    "phase6_arch_proposal": ArchitectureProposalCase(
        case_id="phase6_arch_proposal",
        agent_name="opus-architecture-proposer",
        description="Architecture proposer must produce 3-5 candidates with library-pointer citations.",
    ),
    "phase6_arch_selection": ArchitectureSelectionCase(
        case_id="phase6_arch_selection",
        agent_name="chatgpt-architecture-tradeoff-judge",
        description="Architecture selection must cite only library pointers and select a valid candidate.",
    ),
    "phase6_arch_library_mapping": ArchitectureLibraryMappingCase(
        case_id="phase6_arch_library_mapping",
        agent_name="glm-architecture-library-mapper",
        description="Architecture mapping must map a single library with library-pointer citations.",
    ),
}


def qa_fixture_dir() -> Path:
    """Return the fixture directory used by built-in QA cases."""
    return _FIXTURE_DIR
