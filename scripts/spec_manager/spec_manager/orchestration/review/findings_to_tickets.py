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
# IMPL(single-layer): Router integration should pass `shape_index` and consume
# explicit blocked-finding outputs (ownership ambiguity / out-of-authority)
# rather than assuming DemotionTicket-only conversion succeeds.
# IMPL(single-layer): Keep this module as the normalization boundary for reviewer
# payloads, then hand off a stable finding schema to `demotion.router.route_review_findings`
# (`finding_index`, `category`, `description`, `files`, `pins`, `evidence_paths`,
# `required_change_type`, source-phase hints) so routing semantics stay centralized.
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

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.orchestration.coordination.work_items import WorkItem
from spec_manager.orchestration.demotion.router import DemotionRouter
from spec_manager.routing.shapes import ShapeId, ShapePackIndex, resolve_shape_for_file

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


def _normalize_shape_id(value: Any) -> ShapeId | None:
    text = str(value).strip()
    if not text:
        return None
    return ShapeId(text)


def _normalize_shape_id_list(value: Any) -> list[ShapeId]:
    normalized: list[ShapeId] = []
    if value is None:
        return normalized

    values: list[Any]
    if isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    for item in values:
        shape_id = _normalize_shape_id(item)
        if shape_id is None:
            continue
        if shape_id in normalized:
            continue
        normalized.append(shape_id)
    return normalized


def _resolve_shape_owners(
    files: list[str],
    shape_index: ShapePackIndex,
) -> tuple[list[ShapeId], list[str], list[str], list[str]]:
    resolved_shape_ids: list[ShapeId] = []
    unresolved_files: list[str] = []
    resolved_files: list[str] = []
    diagnostics: list[str] = []

    for file_path in files:
        normalized = file_path.strip()
        if not normalized:
            unresolved_files.append(file_path)
            diagnostics.append("file path is empty")
            continue

        try:
            shape_id = resolve_shape_for_file(normalized, shape_index)
        except Exception as exc:
            unresolved_files.append(normalized)
            diagnostics.append(f"shape resolution failed: {type(exc).__name__}: {exc}")
            continue

        if shape_id is None:
            unresolved_files.append(normalized)
            diagnostics.append(f"shape owner not found for file: {normalized}")
            continue

        if shape_id not in resolved_shape_ids:
            resolved_shape_ids.append(shape_id)
        if normalized not in resolved_files:
            resolved_files.append(normalized)

    return resolved_shape_ids, unresolved_files, diagnostics, resolved_files


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
    resolved_shape_ids: list[ShapeId] = field(default_factory=list)
    normalization_notes: list[str] = field(default_factory=list)
    # IMPL(single-layer): Add `resolved_shape_ids: list[ShapeId]` once ownership is
    # resolved during conversion, so multi-file findings can fan out deterministically
    # without recomputing file ownership in downstream steps.

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
            resolved_shape_ids=_normalize_shape_id_list(data.get("resolved_shape_ids")),
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
                resolved_shape_ids=[],
                normalization_notes=notes,
            ),
            None,
        )

    def to_router_finding(self, *, finding_index: int) -> dict[str, Any]:
        # IMPL(single-layer): Keep this projection as the single normalized payload
        # contract for router review-finding ingestion; retire layer-era fields here
        # when all callers use phase vocabulary.
        payload: dict[str, Any] = {
            "finding_index": finding_index,
            "category": self.category,
            "description": self.description,
            "files": list(self.files),
            "pins": list(self.pins),
            "evidence_paths": list(self.evidence_paths),
        }
        if self.severity:
            payload["severity"] = self.severity
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
        if self.resolved_shape_ids:
            payload["resolved_shape_ids"] = [str(shape_id) for shape_id in self.resolved_shape_ids]
        return payload


@dataclass
class ConversionResult:
    """Result of converting review findings to demotion tickets."""

    # IMPL(single-layer): Replace `tickets`/`skipped` outputs with router-native
    # `produced_work_items` + `blocked_findings` once escalation switches from
    # DemotionTicket artifacts to phase-local work-item persistence.
    produced_work_items: list[WorkItem] = field(default_factory=list)
    blocked_findings: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def convert_findings(
    *,
    findings: list[dict[str, Any]],
    shape_index: ShapePackIndex,
    run_id: str = "",
    slice_id: str = "",
    active_phase: PhaseId = "libraries",
) -> ConversionResult:
    """Convert reviewer findings into phase-local work items.

    Args:
        findings: Raw finding dicts from reviewer agents.
        run_id: Current run identifier.
        slice_id: Slice identifier.
        shape_index: Shape pack index used for ownership resolution.
        active_phase: Currently active phase.

    Returns:
        ConversionResult with produced_work_items and blocked_findings.
    """
    # IMPL(single-layer): Signature migrates to
    # `convert_findings(..., shape_index: ShapePackIndex, active_phase: PhaseId)` and
    # drops `active_layer`/`pin_registry` once DownwardFlowEngine is removed.
    result = ConversionResult()

    # IMPL(single-layer): Replace engine construction with direct demotion-router
    # review routing so conversion is phase-authority aware and returns blocked
    # ambiguity/out-of-authority diagnostics explicitly.
    router = DemotionRouter(
        run_id=run_id,
        active_layer=active_phase,
    )

    if not isinstance(findings, list):
        reason = "findings must be a list"
        logger.warning("convert_findings payload invalid: %s", reason)
        result.blocked_findings.append(
            {
                "index": 0,
                "reason": reason,
                "errors": [reason],
                "finding": findings,
            }
        )
        result.diagnostics.append(f"FINDINGS_BATCH_INVALID:{reason}")
        return result

    for idx, raw in enumerate(findings):
        finding, invalid = ReviewFinding.from_external_dict(index=idx, data=raw)
        if invalid:
            blocked = dict(invalid)
            blocked["finding_index"] = idx
            blocked.setdefault("phase", active_phase)
            result.blocked_findings.append(blocked)
            logger.warning(
                "Skipping invalid review finding at index %s: %s",
                idx,
                "; ".join(invalid.get("errors", [])),
            )
            continue
        assert finding is not None

        if not finding.files:
            result.blocked_findings.append(
                {
                    "source": "REVIEW",
                    "source_id": f"finding_{idx}",
                    "slice_id": slice_id,
                    "finding_index": idx,
                    "phase": active_phase,
                    "failing_files": [],
                    "failing_pins": list(finding.pins),
                    "evidence_refs": list(finding.evidence_paths),
                    "reason": "review finding has no parseable file paths",
                    "diagnostics": ["missing_file_paths"],
                }
            )
            logger.warning(
                "Skipping review finding at index %s: no parseable file paths",
                idx,
            )
            continue

        resolved_shape_ids, unresolved_files, owner_diagnostics, resolved_files = _resolve_shape_owners(
            finding.files,
            shape_index,
        )
        finding.files = resolved_files
        finding.resolved_shape_ids = resolved_shape_ids
        if unresolved_files:
            result.blocked_findings.append(
                {
                    "source": "REVIEW",
                    "source_id": finding.category or f"finding_{idx}",
                    "slice_id": slice_id,
                    "finding_index": idx,
                    "phase": active_phase,
                    "failing_files": unresolved_files,
                    "failing_pins": list(finding.pins),
                    "evidence_refs": list(finding.evidence_paths),
                    "reason": "ownership could not be resolved for one or more finding files",
                    "diagnostics": owner_diagnostics,
                }
            )

        if not resolved_shape_ids:
            logger.warning(
                "Skipping review finding at index %s: no resolvable file owners",
                idx,
            )
            continue

        normalized_finding = finding.to_router_finding(finding_index=idx)
        normalized_finding["files"] = [str(path) for path in finding.files]
        batch = router.route_review_findings(
            slice_id=slice_id,
            findings=[normalized_finding],
            shape_index=shape_index,
        )

        for finding_item in batch.created_work_items:
            if finding_item.shape_id and finding_item.shape_id not in finding.resolved_shape_ids:
                finding.resolved_shape_ids.append(finding_item.shape_id)
            metadata = dict(finding_item.metadata)
            metadata["finding_index"] = idx
            finding_item.metadata = metadata
            result.produced_work_items.append(finding_item)

        for blocked in batch.blocked_findings:
            blocked_finding = dict(blocked)
            blocked_finding["source_id"] = finding.category or blocked_finding.get(
                "source_id"
            )
            blocked_finding["finding_index"] = idx
            blocked_finding["phase"] = active_phase
            blocked_finding.setdefault("slice_id", slice_id)
            result.blocked_findings.append(blocked_finding)

        result.diagnostics.extend(batch.diagnostics)

    return result
