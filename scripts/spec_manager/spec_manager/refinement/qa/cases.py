"""Manual, on-demand QA cases for spec-refinement agent steps."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from spec_manager.core.gaps import Severity
from spec_manager.refinement.core.gap import Gap, GapEvidence, GapType
from spec_manager.refinement.qa.validators import (
    validate_architecture_library_mapping_output,
    validate_architecture_proposal_output,
    validate_architecture_selection_output,
    validate_evidence_mapper_output,
    validate_phase0_determinism,
    validate_spec_integrator_output,
)
from spec_manager.refinement.validation_utils import build_file_id_lookup
from spec_manager.refinement.workflows.architecture import (
    _build_architecture_proposal_prompt,
    _build_architecture_selection_prompt,
    _build_library_mapping_prompt,
)
from spec_manager.refinement.workflows.evidence_expansion import _build_evidence_prompt
from spec_manager.refinement.workflows.spec_building import _build_file_ref, _build_patch_prompt
from spec_manager.refinement.workspace import WorkspaceManager, WorkspaceState


@dataclass(frozen=True)
class PreparedQaCase:
    """A QA case that has been prepared with workspace state."""

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
    """A manual, on-demand QA case for spec-refinement agent steps."""

    case_id: str
    agent_name: str
    description: str

    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:  # pragma: no cover
        """Prepare the QA case with workspace state."""
        raise NotImplementedError


_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "system_medium_v1"
_PATCH_STREAM_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "patch_stream_v1"


def _identity(text: str) -> str:
    return text


def _qa_issue(issue_type: str, message: str, **extra: object) -> dict[str, object]:
    issue: dict[str, object] = {"type": issue_type, "message": message}
    issue.update(extra)
    return issue


def _phase0_run_id(base_run_id: str, suffix: str) -> str:
    token = uuid.uuid4().hex[:8]
    return f"{base_run_id}_{suffix}_{token}"


def _read_json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _read_manifest(path: Path) -> tuple[str, dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    return raw, json.loads(raw)


def _pick_snapshot_file(snapshot_dir: Path) -> Path:
    for path in sorted(snapshot_dir.rglob("*")):
        if path.is_file():
            return path
    raise RuntimeError(f"No snapshot files found in {snapshot_dir}.")


def _append_byte(path: Path) -> None:
    with path.open("ab") as handle:
        handle.write(b"\n")


def _phase0_determinism_validator(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        return [_qa_issue("parse_error", f"Failed to parse phase0 payload: {exc}")]

    first_state_data = payload.get("first_state")
    second_state_data = payload.get("second_state")
    if not isinstance(first_state_data, dict) or not isinstance(second_state_data, dict):
        return [_qa_issue("invalid_state", "Phase0 payload missing state dictionaries.")]

    try:
        first_state = WorkspaceState.from_dict(first_state_data)
        second_state = WorkspaceState.from_dict(second_state_data)
    except Exception as exc:
        return [_qa_issue("invalid_state", f"Failed to hydrate workspace state: {exc}")]

    merged_allowlists = dict(allowlists or {})
    for key in ("manifest_raw", "init_issues", "resume", "immutability"):
        if key in payload:
            merged_allowlists[key] = payload[key]

    return validate_phase0_determinism(
        first_manifest=payload.get("first_manifest", {}),
        second_manifest=payload.get("second_manifest", {}),
        first_state=first_state,
        second_state=second_state,
        allowlists=merged_allowlists,
    )


def _phase0_mode_detection_validator(
    output: str, manager: WorkspaceManager, allowlists: dict[str, Any]
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        return [_qa_issue("parse_error", f"Failed to parse phase0 payload: {exc}")]

    issues: list[dict[str, Any]] = []

    snapshot = payload.get("snapshot", {})
    patch = payload.get("patch_stream", {})
    resume = payload.get("resume", {})

    expected_snapshot = allowlists.get("snapshot_mode", "snapshot")
    expected_patch = allowlists.get("patch_mode", "patch_stream")

    snapshot_mode = snapshot.get("mode") or (snapshot.get("state") or {}).get("mode")
    if snapshot_mode != expected_snapshot:
        issues.append(
            _qa_issue(
                "snapshot_mode_mismatch",
                "Snapshot fixture mode detection mismatch.",
                expected=expected_snapshot,
                got=snapshot_mode,
            )
        )

    patch_mode = patch.get("mode") or (patch.get("state") or {}).get("mode")
    if patch_mode != expected_patch:
        issues.append(
            _qa_issue(
                "patch_mode_mismatch",
                "Patch-stream fixture mode detection mismatch.",
                expected=expected_patch,
                got=patch_mode,
            )
        )

    snapshot_state = snapshot.get("state")
    if isinstance(snapshot_state, dict) and snapshot_state.get("mode") != snapshot_mode:
        issues.append(
            _qa_issue(
                "snapshot_mode_not_persisted",
                "Snapshot mode not persisted in state.json.",
                mode=snapshot_mode,
                state_mode=snapshot_state.get("mode"),
            )
        )

    patch_state = patch.get("state")
    if isinstance(patch_state, dict) and patch_state.get("mode") != patch_mode:
        issues.append(
            _qa_issue(
                "patch_mode_not_persisted",
                "Patch-stream mode not persisted in state.json.",
                mode=patch_mode,
                state_mode=patch_state.get("mode"),
            )
        )

    resume_issues = resume.get("issues")
    warning_text = ""
    if isinstance(resume_issues, list):
        warning_text = " ".join(str(item) for item in resume_issues)
    if "Warning: Detected mode" not in warning_text:
        issues.append(
            _qa_issue(
                "resume_warning_missing",
                "Mode mismatch warning not emitted on resume.",
            )
        )

    existing_mode = resume.get("existing_mode")
    mode_after = resume.get("mode_after")
    if existing_mode and mode_after and existing_mode != mode_after:
        issues.append(
            _qa_issue(
                "resume_mode_changed",
                "Mode changed on resume despite mismatch.",
                existing=existing_mode,
                after=mode_after,
            )
        )

    return issues


def _run_phase0_determinism_test(*, base_run_id: str, fixture_dir: Path) -> dict[str, Any]:
    first_run_id = _phase0_run_id(base_run_id, "phase0_det_a")
    second_run_id = _phase0_run_id(base_run_id, "phase0_det_b")

    first_manager = WorkspaceManager(run_id=first_run_id, input_folder=fixture_dir)
    first_init_issues = first_manager.initialize(force=True)
    second_manager = WorkspaceManager(run_id=second_run_id, input_folder=fixture_dir)
    second_init_issues = second_manager.initialize(force=True)

    first_manifest_raw, first_manifest = _read_manifest(first_manager.structure.files_json)
    second_manifest_raw, second_manifest = _read_manifest(second_manager.structure.files_json)
    first_state = _read_json(first_manager.structure.root / "state.json")
    second_state = _read_json(second_manager.structure.root / "state.json")

    resume_run_id = _phase0_run_id(base_run_id, "phase0_resume")
    resume_manager = WorkspaceManager(run_id=resume_run_id, input_folder=fixture_dir)
    resume_init_issues = resume_manager.initialize(force=True)
    resume_target = _pick_snapshot_file(resume_manager.structure.spec_snapshot_dir)
    _append_byte(resume_target)
    # Refresh baseline to bypass immutability so manifest conflict triggers on resume.
    resume_baseline, resume_baseline_issues = resume_manager._build_spec_snapshot_baseline()
    resume_manager.state.spec_snapshot_baseline = resume_baseline
    resume_manager._save_state()
    resume_issues = resume_manager.initialize(force=False)

    immut_run_id = _phase0_run_id(base_run_id, "phase0_immut")
    immut_manager = WorkspaceManager(run_id=immut_run_id, input_folder=fixture_dir)
    immut_init_issues = immut_manager.initialize(force=True)
    immut_target = _pick_snapshot_file(immut_manager.structure.spec_snapshot_dir)
    _append_byte(immut_target)
    immut_issues = immut_manager.initialize(force=False)

    return {
        "first_manifest": first_manifest,
        "second_manifest": second_manifest,
        "first_state": first_state,
        "second_state": second_state,
        "manifest_raw": {"first": first_manifest_raw, "second": second_manifest_raw},
        "init_issues": {"first": first_init_issues, "second": second_init_issues},
        "resume": {
            "init_issues": resume_init_issues,
            "baseline_issues": resume_baseline_issues,
            "issues": resume_issues,
        },
        "immutability": {
            "init_issues": immut_init_issues,
            "issues": immut_issues,
        },
    }


def _run_phase0_mode_detection_test(
    *, base_run_id: str, snapshot_fixture: Path, patch_fixture: Path
) -> dict[str, Any]:
    snapshot_run_id = _phase0_run_id(base_run_id, "phase0_mode_snapshot")
    snapshot_manager = WorkspaceManager(run_id=snapshot_run_id, input_folder=snapshot_fixture)
    snapshot_init_issues = snapshot_manager.initialize(force=True)
    snapshot_state = _read_json(snapshot_manager.structure.root / "state.json")

    patch_run_id = _phase0_run_id(base_run_id, "phase0_mode_patch")
    patch_manager = WorkspaceManager(run_id=patch_run_id, input_folder=patch_fixture)
    patch_init_issues = patch_manager.initialize(force=True)
    patch_state = _read_json(patch_manager.structure.root / "state.json")

    detected_mode = patch_manager.state.mode
    existing_mode = "snapshot" if detected_mode == "patch_stream" else "patch_stream"
    # Force a mismatch to confirm resume warnings and mode stability.
    patch_manager.state.mode = existing_mode
    patch_manager._save_state()
    resume_issues = patch_manager.initialize(force=False)
    resume_state = _read_json(patch_manager.structure.root / "state.json")

    return {
        "snapshot": {
            "init_issues": snapshot_init_issues,
            "mode": snapshot_state.get("mode"),
            "state": snapshot_state,
        },
        "patch_stream": {
            "init_issues": patch_init_issues,
            "mode": patch_state.get("mode"),
            "state": patch_state,
        },
        "resume": {
            "existing_mode": existing_mode,
            "detected_mode": detected_mode,
            "issues": resume_issues,
            "mode_after": resume_state.get("mode"),
        },
    }


def _write_library(manager: WorkspaceManager, lib_id: str, charter: str, spec: str) -> None:
    lib_dir = manager.structure.libraries_dir / lib_id
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "charter.md").write_text(charter.strip() + "\n", encoding="utf-8")
    (lib_dir / "spec.md").write_text(spec.strip() + "\n", encoding="utf-8")


def _library_charter(
    *, title: str, intent: str, boundaries: list[str], responsibilities: list[str]
) -> str:
    lines = [
        f"# Library Charter: {title}",
        "",
        "## Overview",
        intent.strip(),
        "",
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
        "## Analysis",
        "- None",
        "",
        "## Constraints",
    ]
    for item in constraints:
        lines.append(f"- {item}")
    lines.extend(["", "## Overview"])
    lines.append(intent.strip())
    lines.append("")
    for item in boundaries:
        lines.append(f"- {item}")
    lines.extend(["", "## Details"])
    for item in requirements:
        lines.append(f"- {item}")
    for item in dependencies:
        lines.append(f"- {item}")
    lines.append("")
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


class Phase0DeterminismCase(QaCase):
    """Phase 0 determinism validation test case."""

    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        """Prepare the Phase 0 determinism test case."""
        payload = _run_phase0_determinism_test(
            base_run_id=manager.run_id,
            fixture_dir=_FIXTURE_DIR,
        )
        prompt = json.dumps(payload, indent=2, sort_keys=True)

        acceptance = [
            "Initializing the same input twice produces byte-identical manifest/files.json.",
            "File IDs are sequential (F0001, F0002, ...) and stable across runs.",
            "SHA256 hashes are deterministic for identical file content.",
            "Mode detection correctly identifies 'snapshot' mode for standard fixtures.",
            "Resume safety check detects manifest conflicts and requires --force.",
            "Spec snapshot immutability validation detects modifications.",
        ]

        return PreparedQaCase(
            case_id=self.case_id,
            agent_name=self.agent_name,
            description=self.description,
            prompt=prompt,
            acceptance_criteria=acceptance,
            allowlists={"expected_mode": "snapshot"},
            postprocess=_identity,
            validator=_phase0_determinism_validator,
        )


class Phase0ModeDetectionCase(QaCase):
    """Phase 0 mode detection validation test case."""

    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        """Prepare the Phase 0 mode detection test case."""
        payload = _run_phase0_mode_detection_test(
            base_run_id=manager.run_id,
            snapshot_fixture=_FIXTURE_DIR,
            patch_fixture=_PATCH_STREAM_FIXTURE_DIR,
        )
        prompt = json.dumps(payload, indent=2, sort_keys=True)

        acceptance = [
            "Mode detection identifies 'snapshot' for standard markdown files.",
            "Mode detection identifies 'patch_stream' for .patch/.diff files "
            "or patches/ directories.",
            "Mode is persisted in state.json.",
            "Mode remains stable across resume operations.",
        ]

        return PreparedQaCase(
            case_id=self.case_id,
            agent_name=self.agent_name,
            description=self.description,
            prompt=prompt,
            acceptance_criteria=acceptance,
            allowlists={"snapshot_mode": "snapshot", "patch_mode": "patch_stream"},
            postprocess=_identity,
            validator=_phase0_mode_detection_validator,
        )


class EvidenceMapperAllowlistCase(QaCase):
    """Evidence mapper allowlist validation test case."""

    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        """Prepare the evidence mapper allowlist test case."""
        # Map Storage charter -> Gateway file sections.
        lib_id = "LIB-0002"
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

        file_id = "F0001"
        valid_sections = manager.get_section_labels(file_id)

        # Summary includes headings like "Components"/"Workflows"
        # which must NOT be used as section IDs.
        summary = (
            "# File Summary: F0001\n"
            "File ID: F0001\n"
            "\n"
            "## Algorithms\n"
            "- Request routing | Map path+method to internal handler | "
            "Evidence: [F0001::BOUNDARIES] [F0001::REQUIREMENTS]\n"
            "- Correlation propagation | Attach and forward correlation_id | "
            "Evidence: [F0001::REQUIREMENTS]\n"
            "\n"
            "## Components\n"
            "- Gateway | Validate + route inbound requests | "
            "Evidence: [F0001::INTRO] [F0001::BOUNDARIES]\n"
            "\n"
            "## Workflows\n"
            "- Inbound request | validate -> route -> persist metadata -> publish audit event | "
            "Evidence: [F0001::REQUIREMENTS] [F0001::INTEGRATION]\n"
            "\n"
            "## Candidate Responsibilities\n"
            "- Own input validation and request routing for external traffic | "
            "Evidence: [F0001::BOUNDARIES]\n"
            "- Persist request/response metadata via Storage | Evidence: [F0001::INTEGRATION]\n"
            "\n"
            "## Dependencies\n"
            "- Storage\n"
            "- Event Bus\n"
            "\n"
            "## Evidence Map\n"
            "- INTRO: [F0001::INTRO]\n"
            "- BOUNDARIES: [F0001::BOUNDARIES]\n"
            "- REQUIREMENTS: [F0001::REQUIREMENTS]\n"
            "- CONSTRAINTS: [F0001::CONSTRAINTS]\n"
            "- INTEGRATION: [F0001::INTEGRATION]\n"
        )

        prompt = _build_evidence_prompt(
            lib_id=lib_id,
            charter_content=charter,
            file_id=file_id,
            summary_content=summary,
            manager=manager,
        )

        acceptance = [
            "Output is valid JSON with keys: file_id, relevant_sections, confidence, rationale.",
            "file_id equals F0001.",
            "relevant_sections is a list and every entry is an exact match from the allow-list.",
            "relevant_sections MUST NOT contain summary headings like 'Components' or 'Workflows'.",
            "Because the Gateway integrates with Storage, relevant_sections should include "
            "INTEGRATION.",
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
    """Spec integrator unsupported assertion handling test case."""

    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        """Prepare the spec integrator unsupported assertion test case."""
        # Storage library integration against the Storage source file.
        lib_id = "LIB-0002"
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

        current_spec = """# Library Spec: LIB-0002

## Analysis
- None

## Constraints
- Data must be encrypted at rest. [F0002::CONSTRAINTS]

## Overview
Provide durable persistence APIs. [F0002::INTRO]

- Owns record storage and retrieval operations. [F0002::BOUNDARIES]
- Does NOT own request validation or request routing. [F0002::BOUNDARIES]
- Does NOT own throughput management. [F0002::BOUNDARIES]

## Details
- Store records reliably with an idempotency key. [F0002::REQUIREMENTS]
- Support lookup by ID. [F0002::REQUIREMENTS]
- Called by Gateway for persistence. [F0002::INTEGRATION]
"""

        file_id = "F0002"
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
                "throughput management. Reclassify into Analysis rather than asserting it."
            ),
            evidence=[
                GapEvidence(
                    invariant_family="content",
                    description="Unsupported boundary assertion: throughput management.",
                    details={"where_in_spec": "Overview"},
                    confidence=1.0,
                    location=f"{file_id}::BOUNDARIES",
                    detector="qa-harness",
                )
            ],
        )

        file_ref = _build_file_ref(file_id, manager)
        file_id_lookup = build_file_id_lookup(
            manager.state.file_manifest, manager.structure.spec_snapshot_dir
        )
        file_refs = [file_id_lookup.get(f) for f in manager.state.file_manifest]

        prompt = _build_patch_prompt(
            lib_id=lib_id,
            charter_content=charter,
            spec_content=current_spec,
            file_id=file_id,
            file_ref=file_ref,
            file_content=file_content,
            evidence_sections=evidence_sections,
            valid_section_ids=valid_sections,
            valid_file_refs=[str(f) for f in file_refs if f is not None],
            file_id_lookup=file_id_lookup,
            gaps=[gap],
        )

        acceptance = [
            "Output is valid JSON matching SpecPatchOutput (file_id, lib_id, patches).",
            "All patch operations are add/edit/move (no delete).",
            "Citations use only [F####::SECTION] and section labels are from the allow-list.",
            "The unsupported claim about throughput management is moved from Overview into "
            "Analysis (not asserted in Overview after applying patches).",
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
    """Architecture proposal validation test case."""

    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        """Prepare the architecture proposal test case."""
        # Create 4 libraries representing the fixture system.
        libs: dict[str, dict[str, Any]] = {
            "LIB-0001": {
                "name": "Gateway",
                "intent": "Handle inbound HTTP requests; validate and route; emit audit events.",
                "boundaries": [
                    "Owns request routing + validation for external requests.",
                    "Does NOT own persistence (delegates to Storage).",
                ],
                "requirements": ["Route requests", "Validate inputs", "Propagate correlation_id"],
                "constraints": ["<=5ms p95 overhead", "Do not log secrets"],
                "dependencies": ["Calls LIB-0002", "Publishes to LIB-0003"],
            },
            "LIB-0002": {
                "name": "Storage",
                "intent": "Durable persistence + retrieval APIs.",
                "boundaries": [
                    "Owns record storage + retrieval APIs.",
                    "Does NOT own request routing or validation.",
                ],
                "requirements": ["Store records", "Lookup by ID", "Delete by ID (tombstone)"],
                "constraints": ["Encrypt at rest", "Durability 99.99% monthly"],
                "dependencies": ["Consumed by LIB-0001 and LIB-0004"],
            },
            "LIB-0003": {
                "name": "Event Bus",
                "intent": "Publish/subscribe messaging for audit and domain events.",
                "boundaries": [
                    "Owns event publishing + delivery semantics.",
                    "Does NOT own business logic; transports events only.",
                ],
                "requirements": ["At-least-once delivery", "Consumer groups with offsets"],
                "constraints": ["Order per key", ">=10k events/sec burst"],
                "dependencies": ["Consumes/produces by LIB-0001 and LIB-0004"],
            },
            "LIB-0004": {
                "name": "Domain Services",
                "intent": "Core workflows orchestrating Gateway, Storage, Event Bus.",
                "boundaries": [
                    "Owns domain business logic and orchestration.",
                    "Does NOT own routing/validation (Gateway) or delivery semantics (Event Bus).",
                ],
                "requirements": [
                    "Persist state",
                    "Publish domain events",
                    "Deterministic workflows",
                ],
                "constraints": ["Idempotent execution", "Testable (no hidden I/O)"],
                "dependencies": ["Uses LIB-0002 and LIB-0003"],
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

        # In the real workflow, architecture briefs are extracted via a separate agent step.
        # For this single-agent QA case, we provide deterministic briefs with valid citations.
        briefs: dict[str, dict[str, Any]] = {}
        for lib_id, info in libs.items():
            briefs[lib_id] = {
                "lib_id": lib_id,
                "intent": info["intent"],
                "boundaries": " ".join(info["boundaries"]).strip(),
                "dependencies": info["dependencies"],
                "constraints": [
                    {
                        "type": "Constraint",
                        "description": item,
                        "citation": f"[{lib_id}::spec.md::CONSTRAINTS]",
                    }
                    for item in info["constraints"]
                ],
                "interfaces": [
                    {
                        "type": "Interface",
                        "description": ("See Details section for interaction surface."),
                        "citation": f"[{lib_id}::spec.md::REQUIREMENTS]",
                    }
                ],
            }

        prompt = _build_architecture_proposal_prompt(lib_charters, lib_specs, briefs)

        acceptance = [
            "Output is a JSON array with 3-5 candidates.",
            "Each candidate has arch_id, pattern, description, components, communication, "
            "deployment, citations, tradeoffs.",
            "Citations use ONLY [LIB-####::charter.md] or [LIB-####::spec.md::SECTION] "
            "pointers (no [F####::...]).",
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
    """Architecture selection validation test case."""

    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        """Prepare the architecture selection test case."""
        # Reuse the same libraries as ArchitectureProposalCase for realistic context.
        proposal_case = ArchitectureProposalCase(
            case_id="phase6_arch_proposal",
            agent_name="opus-architecture-proposer",
            description="Internal reuse for selection case setup.",
        )
        proposal_case.prepare(manager)

        # Provide two candidate architectures to judge: one good, one clearly worse.
        candidates: dict[str, str] = {
            "arch_001": (
                "# Architecture Candidate: arch_001\n\n"
                "## Pattern\n"
                "Layered monolith\n\n"
                "## Description\n"
                "Single deployable with clear layers.\n\n"
                "## Components\n"
                "- Gateway: routing/validation\n"
                "- Domain: workflows\n"
                "- Storage: persistence\n"
                "- Eventing: publish events\n\n"
                "## Communication\n"
                "In-process calls for core flows; async publish for events.\n\n"
                "## Deployment\n"
                "Single deployable.\n\n"
                "## Tradeoffs\n"
                "### Advantages\n"
                "- Lower operational complexity\n\n"
                "### Disadvantages\n"
                "- Harder independent scaling\n\n"
                "## Citations\n"
                "- [LIB-0001::charter.md]\n"
                "- [LIB-0002::spec.md::CONSTRAINTS]\n"
            ),
            "arch_002": (
                "# Architecture Candidate: arch_002\n\n"
                "## Pattern\n"
                "Microservices\n\n"
                "## Description\n"
                "Split each library into a separate service.\n\n"
                "## Components\n"
                "- GatewaySvc\n"
                "- DomainSvc\n"
                "- StorageSvc\n"
                "- EventBusSvc\n\n"
                "## Communication\n"
                "Synchronous network calls for all interactions.\n\n"
                "## Deployment\n"
                "Four services.\n\n"
                "## Tradeoffs\n"
                "### Advantages\n"
                "- Independent deploys\n\n"
                "### Disadvantages\n"
                "- Higher latency and ops burden\n\n"
                "## Citations\n"
                "- [LIB-0001::charter.md]\n"
                "- [LIB-0003::spec.md::CONSTRAINTS]\n"
            ),
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
            "selected_arch_id is one of the provided candidates (arch_001 or arch_002) or null "
            "with explanation.",
            "rationale includes library-pointer citations only ([LIB-####::...]); no [F####::...].",
            "Rejected architectures include concrete reasons.",
        ]

        return PreparedQaCase(
            case_id=self.case_id,
            agent_name=self.agent_name,
            description=self.description,
            prompt=prompt,
            acceptance_criteria=acceptance,
            allowlists={
                "candidate_ids": sorted(candidates.keys()),
                "library_ids": sorted(lib_specs.keys()),
            },
            postprocess=_identity,
            validator=validate_architecture_selection_output,
        )


class ArchitectureLibraryMappingCase(QaCase):
    """Architecture library mapping validation test case."""

    def prepare(self, manager: WorkspaceManager) -> PreparedQaCase:
        """Prepare the architecture library mapping test case."""
        # Ensure libraries exist with spec sections for citations.
        proposal_case = ArchitectureProposalCase(
            case_id="phase6_arch_proposal",
            agent_name="opus-architecture-proposer",
            description="Internal reuse for mapping case setup.",
        )
        proposal_case.prepare(manager)

        selected_architecture = (
            "# Selected Architecture: arch_001\n\n"
            "## Rationale\n"
            "Layered monolith keeps ops cost low while meeting Gateway latency and Event Bus "
            "throughput. [LIB-0001::spec.md::CONSTRAINTS] [LIB-0003::spec.md::CONSTRAINTS]\n\n"
            "## Selected Candidate\n"
            "# Architecture Candidate: arch_001\n\n"
            "## Pattern\n"
            "Layered monolith\n\n"
            "## Description\n"
            "Single deployable with clear layers.\n\n"
            "## Components\n"
            "- Gateway: routing/validation\n"
            "- Domain: workflows\n"
            "- Storage: persistence\n"
            "- Eventing: publish events\n\n"
            "## Communication\n"
            "In-process calls for core flows; async publish for events.\n\n"
            "## Deployment\n"
            "Single deployable.\n"
        )
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

        target_lib_id = "LIB-0002"
        charter = lib_charters.get(target_lib_id, "")
        spec = lib_specs.get(target_lib_id, "")
        prompt = _build_library_mapping_prompt(target_lib_id, selected_architecture, charter, spec)

        acceptance = [
            "Output is valid JSON for a single-library mapping fragment.",
            "lib_id matches the requested library (LIB-0002).",
            "component matches one of the components listed in the selected architecture.",
            "citations contains at least one library-pointer citation ([LIB-####::...]).",
            "No source-file citations like [F####::...] appear in citations or dependencies.",
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
    "phase0_determinism": Phase0DeterminismCase(
        case_id="phase0_determinism",
        agent_name="none",
        description="Phase 0 initialization must be deterministic and enforce immutability.",
    ),
    "phase0_mode_detection": Phase0ModeDetectionCase(
        case_id="phase0_mode_detection",
        agent_name="none",
        description="Phase 0 mode detection must classify snapshot vs patch stream correctly.",
    ),
    "phase3_evidence_mapper_allowlist": EvidenceMapperAllowlistCase(
        case_id="phase3_evidence_mapper_allowlist",
        agent_name="glm-library-evidence-mapper",
        description=(
            "Evidence mapper must choose relevant_sections only from the provided "
            "allow-list and must not output summary headings like 'Components'/'Workflows'."
        ),
    ),
    "phase4_spec_integrator_unsupported_assertion": SpecIntegratorUnsupportedAssertionCase(
        case_id="phase4_spec_integrator_unsupported_assertion",
        agent_name="glm-library-spec-integrator",
        description=(
            "Spec integrator must produce valid patch ops (no delete), "
            "keep citations within the [F####::SECTION] allowlists, "
            "and reclassify unsupported assertions into Analysis."
        ),
    ),
    "phase6_arch_proposal": ArchitectureProposalCase(
        case_id="phase6_arch_proposal",
        agent_name="opus-architecture-proposer",
        description=(
            "Architecture proposer must produce 3-5 candidates with library-pointer citations."
        ),
    ),
    "phase6_arch_selection": ArchitectureSelectionCase(
        case_id="phase6_arch_selection",
        agent_name="chatgpt-architecture-tradeoff-judge",
        description=(
            "Architecture selection must cite only library pointers and select a valid candidate."
        ),
    ),
    "phase6_arch_library_mapping": ArchitectureLibraryMappingCase(
        case_id="phase6_arch_library_mapping",
        agent_name="glm-architecture-library-mapper",
        description=(
            "Architecture mapping must map a single library with library-pointer citations."
        ),
    ),
}


def qa_fixture_dir() -> Path:
    """Return the fixture directory used by built-in QA cases."""
    return _FIXTURE_DIR
