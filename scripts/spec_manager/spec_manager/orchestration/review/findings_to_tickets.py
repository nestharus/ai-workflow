# TODO(single-layer): RESTRUCTURE — Findings-to-tickets pipeline loses layer routing.
#   Currently: finding category -> layer literal (L1/L2/L3). In single-layer:
#   finding category -> phase literal (Libraries/Architecture/Quality).
#   Mapping: LOGIC/SPEC/UNDER_SPEC -> Libraries, ARCH -> Architecture, STYLE/QUALITY -> Quality.
#   "Route via pins" becomes "route via shape_id" — finding references a file,
#   file->shape ownership determines shape_id for the work item (Section 6.3 rule #1).
#   Findings are routed within the current phase or block if outside that phase's authority.
#   DownwardFlowEngine reference -> remove (DELETE'd). DemotionRouter reference -> keep
#   but with phase-based targeting.
#   LLM authority constraint (Section 13.2/13.3): reviewer/LLM findings are advisory
#   only — they must NOT become hard gate results unless converted to deterministic
#   verifier tasks, explicit human decisions, or blocked ambiguity signals.
# ALGORITHM(single-layer):
#   References: response3 Sections 8.2, 11, 13.2, 13.3.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] (3 forward-only phases; no cycling back).
#     - Each phase edits code via its own PromotionLoop with IMPLEMENT step (no "refinement-only" phases).
#     - ReviewFinding keeps parsed reviewer payload; add resolved_shape_ids: list[ShapeId].
#     - ConversionResult returns produced_work_items and blocked_findings.
#   Interface contracts:
#     - def convert_findings(findings: list[dict[str, Any]], *, run_id: str, slice_id: str, shape_index: ShapePackIndex, active_phase: PhaseId) -> ConversionResult
#   Control flow:
#     1. Normalize categories/severity and reject malformed findings.
#     2. Resolve file->shape ownership for each finding; include multiple shapes when multiple files.
#     3. Convert each finding into WorkItem via demotion router/triage path.
#     4. Route by active-phase authority (not rigid category→phase mapping):
#        - If finding is within current phase authority: fix_in_phase or queue_work_item.
#        - If finding is outside current phase authority: block with diagnostics.
#        - Architecture can handle LOGIC/behavior findings in-place (algorithm remediation).
#        - Quality blocks on behavior-changing findings.
#     5. Mark LLM-origin findings advisory unless converted to deterministic verifier/test tasks or explicit block signals.
#   Error handling:
#     - Missing category/files yields blocked finding entry with validation errors.
#     - Unknown file owner creates blocked ambiguity requiring user input.
#   Integration points:
#     - Called by reviewer pipelines and promotion loop COORDINATE step within each phase.
#     - Calls demotion router + work item store.
# IMPL(single-layer): Keep finding-conversion payloads aligned with
# `orchestration.demotion` ticket-schema migration (`shape_id`,
# `required_change_type`, QUEUED/BLOCKED outcomes) so this module does not re-introduce
# layer-targeting fields after escalation cutover.
#   Test requirements:
#     - Authority-based routing: Architecture handles behavior findings in-place; Quality blocks on behavior.
#     - Multi-file finding produces one work item per owner shape or grouped by shape policy.
#     - Advisory-only finding cannot produce hard gate pass/fail side effects.
#     - Findings targeting a phase outside the active phase produce a block, not a re-triage.

"""Convert reviewer agent findings into DemotionTickets.

Translates structured findings from reviewer agents (chatgpt-*-reviewer.md)
into DemotionTickets via the DownwardFlowEngine + DemotionRouter pipeline.

Each finding must include a ``category`` field:
- STYLE / QUALITY → L3
- LOGIC → route via pins → L1
- ARCH → L2
- SPEC / UNDER_SPEC → L1 + under-spec events
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from spec_manager.orchestration.demotion import DemotionTicket
from spec_manager.orchestration.downward_flow.engine import (
    DownwardFlowEngine,
    FailureEvidence,
)

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = frozenset({"STYLE", "QUALITY", "LOGIC", "ARCH", "SPEC", "UNDER_SPEC"})
_VALID_SEVERITIES = frozenset({"BLOCKER", "MAJOR", "MINOR"})


def _normalize_text_list(*, value: Any, field_name: str) -> tuple[list[str], str | None]:
    if value is None:
        return [], None
    if not isinstance(value, list):
        return [], f"{field_name} must be a list of strings"

    normalized: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            return [], f"{field_name}[{idx}] must be a string"
        text = item.strip()
        if text:
            normalized.append(text)
    return normalized, None


def _coerce_text_field(
    *,
    value: Any,
    field_name: str,
    required: bool = False,
) -> tuple[str, str | None]:
    if value is None:
        if required:
            return "", f"{field_name} is required"
        return "", None
    if not isinstance(value, str):
        return "", f"{field_name} must be a string"
    text = value.strip()
    if required and not text:
        return "", f"{field_name} is required"
    return text, None


@dataclass
class ReviewFinding:
    """A single finding from a reviewer agent."""

    category: str = ""  # STYLE, QUALITY, LOGIC, ARCH, SPEC, UNDER_SPEC
    description: str = ""
    files: list[str] = field(default_factory=list)
    pins: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    severity: str = "MAJOR"  # BLOCKER, MAJOR, MINOR
    dimension: str = ""
    tags: list[str] = field(default_factory=list)
    required_change_type: str = ""
    source_layer: str = ""
    failure_layer: str = ""
    layer: str = ""
    origin_layer: str = ""
    normalization_notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewFinding:
        """Create from a trusted dict payload."""
        return cls(
            category=str(data.get("category", "")).strip().upper(),
            description=str(data.get("description", "")).strip(),
            files=[str(path).strip() for path in data.get("files", []) if str(path).strip()],
            pins=[str(pin).strip() for pin in data.get("pins", []) if str(pin).strip()],
            evidence_paths=[
                str(path).strip() for path in data.get("evidence_paths", []) if str(path).strip()
            ],
            severity=str(data.get("severity", "MAJOR")).strip().upper() or "MAJOR",
            dimension=str(data.get("dimension", "")).strip(),
            tags=[str(tag).strip() for tag in data.get("tags", []) if str(tag).strip()],
            required_change_type=str(data.get("required_change_type", "")).strip(),
            source_layer=str(data.get("source_layer", "")).strip(),
            failure_layer=str(data.get("failure_layer", "")).strip(),
            layer=str(data.get("layer", "")).strip(),
            origin_layer=str(data.get("origin_layer", "")).strip(),
        )

    @classmethod
    def from_external_dict(
        cls,
        *,
        index: int,
        data: Any,
    ) -> tuple[ReviewFinding | None, dict[str, Any] | None]:
        """Validate and project reviewer output into a stable internal shape."""
        if not isinstance(data, dict):
            return None, {
                "index": index,
                "reason": "invalid_payload_type",
                "errors": [f"finding must be an object, got {type(data).__name__}"],
                "finding": data,
            }

        errors: list[str] = []
        notes: list[str] = []

        category, category_error = _coerce_text_field(
            value=data.get("category"),
            field_name="category",
            required=True,
        )
        if category_error:
            errors.append(category_error)
        category = category.upper()
        if category and category not in _VALID_CATEGORIES:
            errors.append(f"category must be one of {sorted(_VALID_CATEGORIES)}; got '{category}'")

        description, description_error = _coerce_text_field(
            value=data.get("description"),
            field_name="description",
            required=False,
        )
        if description_error:
            errors.append(description_error)
        if category in {"SPEC", "UNDER_SPEC"} and not description:
            errors.append("description is required for SPEC/UNDER_SPEC findings")

        severity, severity_error = _coerce_text_field(
            value=data.get("severity"),
            field_name="severity",
            required=False,
        )
        if severity_error:
            errors.append(severity_error)
        severity = severity.upper()
        if not severity:
            severity = "MAJOR"
            notes.append("severity_missing_defaulted_to_major")
        if severity not in _VALID_SEVERITIES:
            errors.append(f"severity must be one of {sorted(_VALID_SEVERITIES)}; got '{severity}'")

        files, files_error = _normalize_text_list(value=data.get("files"), field_name="files")
        if files_error:
            errors.append(files_error)

        pins, pins_error = _normalize_text_list(value=data.get("pins"), field_name="pins")
        if pins_error:
            errors.append(pins_error)

        evidence_paths, evidence_paths_error = _normalize_text_list(
            value=data.get("evidence_paths"),
            field_name="evidence_paths",
        )
        if evidence_paths_error:
            errors.append(evidence_paths_error)

        tags, tags_error = _normalize_text_list(value=data.get("tags"), field_name="tags")
        if tags_error:
            errors.append(tags_error)

        dimension, dimension_error = _coerce_text_field(
            value=data.get("dimension"),
            field_name="dimension",
            required=False,
        )
        if dimension_error:
            errors.append(dimension_error)

        required_change_type, required_change_type_error = _coerce_text_field(
            value=data.get("required_change_type"),
            field_name="required_change_type",
            required=False,
        )
        if required_change_type_error:
            errors.append(required_change_type_error)

        source_layer, source_layer_error = _coerce_text_field(
            value=data.get("source_layer"),
            field_name="source_layer",
            required=False,
        )
        if source_layer_error:
            errors.append(source_layer_error)

        failure_layer, failure_layer_error = _coerce_text_field(
            value=data.get("failure_layer"),
            field_name="failure_layer",
            required=False,
        )
        if failure_layer_error:
            errors.append(failure_layer_error)

        layer, layer_error = _coerce_text_field(
            value=data.get("layer"),
            field_name="layer",
            required=False,
        )
        if layer_error:
            errors.append(layer_error)

        origin_layer, origin_layer_error = _coerce_text_field(
            value=data.get("origin_layer"),
            field_name="origin_layer",
            required=False,
        )
        if origin_layer_error:
            errors.append(origin_layer_error)

        if errors:
            return None, {
                "index": index,
                "reason": "invalid_finding",
                "errors": errors,
                "finding": dict(data),
            }

        return (
            cls(
                category=category,
                description=description,
                files=files,
                pins=pins,
                evidence_paths=evidence_paths,
                severity=severity,
                dimension=dimension,
                tags=tags,
                required_change_type=required_change_type,
                source_layer=source_layer,
                failure_layer=failure_layer,
                layer=layer,
                origin_layer=origin_layer,
                normalization_notes=notes,
            ),
            None,
        )

    def to_router_finding(self, *, finding_index: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "finding_index": finding_index,
            "category": self.category,
            "description": self.description,
            "files": list(self.files),
            "pins": list(self.pins),
            "evidence_paths": list(self.evidence_paths),
            "severity": self.severity,
        }
        if self.dimension:
            payload["dimension"] = self.dimension
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.required_change_type:
            payload["required_change_type"] = self.required_change_type
        if self.source_layer:
            payload["source_layer"] = self.source_layer
        if self.failure_layer:
            payload["failure_layer"] = self.failure_layer
        if self.layer:
            payload["layer"] = self.layer
        if self.origin_layer:
            payload["origin_layer"] = self.origin_layer
        return payload


@dataclass
class ConversionResult:
    """Result of converting review findings to demotion tickets."""

    tickets: list[DemotionTicket] = field(default_factory=list)
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    skipped_details: list[dict[str, Any]] = field(default_factory=list)


def convert_findings(
    *,
    findings: list[dict[str, Any]],
    run_id: str = "",
    slice_id: str = "",
    active_layer: str = "L1",
    pin_registry: Any = None,
) -> ConversionResult:
    """Convert reviewer findings into DemotionTickets.

    For SPEC/UNDER_SPEC findings, also emits under_spec_events that
    can be fed into the UnderSpecManager for constraint resolution.

    Args:
        findings: Raw finding dicts from reviewer agents.
        run_id: Current run identifier.
        slice_id: Slice identifier.
        active_layer: Currently active promotion layer.
        pin_registry: PinFunctionRegistry for pin tracing.

    Returns:
        ConversionResult with tickets and any under-spec events.
    """
    result = ConversionResult()

    engine = DownwardFlowEngine(
        run_id=run_id,
        active_layer=active_layer,
        pin_registry=pin_registry,
    )

    for idx, raw in enumerate(findings):
        finding, invalid = ReviewFinding.from_external_dict(index=idx, data=raw)
        if invalid:
            result.skipped += 1
            result.skipped_details.append(invalid)
            logger.warning(
                "Skipping invalid review finding at index %s: %s",
                idx,
                "; ".join(invalid.get("errors", [])),
            )
            continue
        assert finding is not None

        # SPEC/UNDER_SPEC findings produce under-spec events.
        if finding.category in {"SPEC", "UNDER_SPEC"}:
            needed_for = ", ".join(finding.files)
            source_file = finding.files[0] if finding.files else ""
            result.under_spec_events.append(
                {
                    "kind": "REVIEW_UNDER_SPEC",
                    "question": finding.description,
                    "needed_for": needed_for,
                    "source": "REVIEW",
                    "source_file": source_file,
                    "severity": finding.severity,
                    "evidence_paths": list(finding.evidence_paths),
                    "context": {
                        "finding_index": idx,
                        "category": finding.category,
                        "files": list(finding.files),
                        "pins": list(finding.pins),
                        "evidence_paths": list(finding.evidence_paths),
                        "severity": finding.severity,
                        "normalization_notes": list(finding.normalization_notes),
                    },
                }
            )
            continue

        # Route through DownwardFlowEngine for pin tracing
        projected_finding = finding.to_router_finding(finding_index=idx)
        evidence = FailureEvidence(
            source="REVIEW",
            review_findings=[projected_finding],
            evidence_paths=finding.evidence_paths,
        )

        batch = engine.trace_and_route(evidence)
        for ticket in batch.tickets:
            ticket.slice_id = slice_id
            ticket.diagnosis = finding.description
            ticket.severity = finding.severity
            for note in finding.normalization_notes:
                ticket.questions.append(f"FINDING_NORMALIZATION:{note}")
            result.tickets.append(ticket)

    return result
