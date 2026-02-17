# TODO(single-layer): RESTRUCTURE — Router converts failures to work items (not
#   DemotionTickets targeting layers). Remove _normalize_layer, _GATE_FINDING_PIN_KEYS.
#   Add shape_id resolution: map failing file -> owning shape (Section 8.2 step 1).
#   The evidence extraction logic (gate findings, test failures) survives.
#   No cross-phase routing: router routes within current phase or blocks.
#   3 phases (libraries, architecture, quality), forward-only, no cycling back.
# IMPL(single-layer): Ownership mapping should call
# `routing.shapes.resolve_shape_for_file` (most-specific package prefix) rather than
# maintaining a router-local prefix matcher.
# IMPL(single-layer): If ownership resolves to a PROPOSAL shape or metadata requests
# verifier refresh, emit verifier/spec work items for the current phase instead of
# treating the finding as converged.
# IMPL(single-layer): Keep this file aligned with `orchestration.demotion`
# ticket-contract migration (EscalationTicket fields + QUEUED/BLOCKED outcomes);
# router must not carry duplicate layer-era defaults once the shared schema changes.
# IMPL(single-layer): Consume triage as action authority (`queue_work_item`,
# `fix_in_phase`, `block`) and stop deriving synthetic target phases/layers in router code.
# IMPL(single-layer): Canonicalize gate IDs before triage so Section 10.2 gate
# collapse (`TESTS_PASS` -> `ALL_TESTS_PASS`) and retired-gate blocking are visible in
# `blocked_findings` diagnostics.
# ALGORITHM(single-layer):
#   References: response3 Sections 8.2 and 11.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] (3 forward-only phases).
#     - RoutingBatch: {created_work_items: list[WorkItem], blocked_findings: list[dict[str, Any]], diagnostics: list[str]}.
#     - GateFindingProjection keeps file/evidence extraction but replaces pin fields with shape owner fields.
#   Interface contracts:
#     - class DemotionRouter:
#       - def route_gate_failures(..., shape_index: ShapePackIndex) -> RoutingBatch
#       - def route_test_failures(..., shape_index: ShapePackIndex) -> RoutingBatch
#       - def route_review_findings(..., shape_index: ShapePackIndex) -> RoutingBatch
#   Control flow:
#     1. Parse failure payloads and normalize deterministic fields.
#     2. Resolve owning shape from failing file path using routing.shapes ownership.
#     3. Build EscalationContext and call triage() for phase-local routing decision.
#     4. If within current phase authority: materialize WorkItem with shape_id, required_change_type, evidence refs.
#     5. If outside current phase authority: block (no demotion to earlier phase).
#        Architecture can remediate algorithm issues in-place; Quality blocks on behavior change.
#     6. Aggregate blocked cases when owner shape cannot be resolved.
#   Error handling:
#     - Invalid failure payload type logs warning and creates blocked diagnostic entry.
#     - No cross-phase re-routing; out-of-authority findings block with diagnostics.
#   Integration points:
#     - Called by promotion loop VERIFY/PROMOTE failures and review finding conversion.
#     - Calls demotion.triage and coordination.work_items store.
#   Test requirements:
#     - File-to-shape routing works for nested package ownership.
#     - Gate/test/review payloads all convert to work items within current phase.
#     - Out-of-authority findings produce block, not cross-phase routing.
#     - Missing ownership produces block entry, not silent drop.

"""Demotion router: converts failure evidence into DemotionTickets.

Consumes gate violations, test failures, and review findings, and
produces routed DemotionTickets targeting the correct layer.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.orchestration.coordination.work_items import (
    RequiredChangeType,
    WorkItem,
    WorkItemLocation,
)
from spec_manager.orchestration.demotion.triage import (
    DemotionContext,
    DemotionRouting,
    infer_gate_source_layer,
    triage,
)
from spec_manager.routing.shapes import ShapeId, ShapePackIndex, resolve_shape_for_file

logger = logging.getLogger(__name__)

_SOURCE_PHASE_KEYS = ("source_phase", "failure_phase", "phase", "active_phase", "source_layer", "failure_layer", "layer", "origin_layer")
_GATE_FINDING_FILE_KEYS = ("file_path", "arch_file")
_GATE_FINDING_EVIDENCE_KEYS = ("raw_excerpt_path", "evidence_path", "excerpt_path")
_GATE_FINDING_REQUIRED_CHANGE_KEYS = ("required_change_type", "change_type")

_ALLOWED_PHASES = ("libraries", "architecture", "quality")
_PHASE_TO_LAYER = {
    "libraries": "L1",
    "architecture": "L2",
    "quality": "L3",
}
_LAYER_TO_PHASE = {v: k for k, v in _PHASE_TO_LAYER.items()}
_ALLOWED_CHANGE_TYPES = {
    "behavior_change",
    "wiring_only",
    "refactor_only",
    "spec_change",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _normalize_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if text:
        return text
    return None


def _unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _normalize_text_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if isinstance(values, (tuple, set)):
        values = list(values)
    if not isinstance(values, list):
        values = [values]

    normalized: list[str] = []
    for value in values:
        text = _normalize_text(value)
        if text:
            normalized.append(text)
    return normalized


def _first_nonempty(mapping: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _normalize_text(mapping.get(key))
        if value:
            return value
    return None


def _normalize_required_change_type(value: Any) -> RequiredChangeType | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    normalized = normalized.replace("-", "_").strip().lower()
    if normalized not in _ALLOWED_CHANGE_TYPES:
        return None
    return cast("RequiredChangeType", normalized)


def _normalize_phase(value: Any, *, fallback: PhaseId) -> PhaseId:
    normalized = _normalize_text(value)
    if normalized is None:
        return fallback

    lowered = normalized.lower()
    if lowered in _ALLOWED_PHASES:
        return cast("PhaseId", lowered)

    upper = normalized.upper()
    if upper in _LAYER_TO_PHASE:
        return cast("PhaseId", _LAYER_TO_PHASE[upper])

    return fallback


def _infer_source_phase(
    payload: dict[str, Any],
    *,
    fallback: PhaseId,
    gate_id: str | None = None,
) -> tuple[PhaseId, str | None]:
    discovered: list[PhaseId] = []
    issues: list[str] = []
    for key in _SOURCE_PHASE_KEYS:
        raw_value = payload.get(key)
        if raw_value is None:
            continue
        normalized_phase = _normalize_phase(raw_value, fallback="")
        if normalized_phase:
            discovered.append(normalized_phase)
            continue
        normalized_layer = _normalize_text(raw_value)
        if normalized_layer:
            issues.append(f"unrecognized_phase[{key}]={normalized_layer}")

    if not discovered and gate_id:
        gate_layer = infer_gate_source_layer(gate_id)
        if gate_layer:
            discovered.append(_LAYER_TO_PHASE[gate_layer])

    unique_discovered = list(dict.fromkeys(discovered))
    if not unique_discovered:
        issue = None
        if issues:
            issue = "; ".join(issues)
            logger.warning("Source phase unresolved for payload: %s", issue)
        return fallback, issue

    issue = None
    if len(unique_discovered) > 1:
        issue = f"conflicting source phases: {', '.join(unique_discovered)}"
        logger.warning("Source phase conflict for payload: %s", issue)
    return unique_discovered[0], issue


def _resolve_shape_for_file_with_diagnostics(
    file_path: str,
    shape_index: ShapePackIndex,
) -> tuple[ShapeId | None, list[str]]:
    normalized = _normalize_text(file_path)
    if not normalized:
        return None, ["missing file path"]

    try:
        shape_id = resolve_shape_for_file(normalized, shape_index)
    except Exception as exc:  # pragma: no cover - defensive for legacy resolver exceptions
        return None, [f"shape resolution failed: {type(exc).__name__}:{exc}"]

    if not shape_id:
        return None, ["shape owner not found"]
    return shape_id, []


def _group_files_by_shape(
    file_paths: list[str],
    shape_index: ShapePackIndex,
) -> tuple[dict[ShapeId, list[str]], list[tuple[str, list[str]]]]:
    grouped: dict[ShapeId, list[str]] = {}
    unresolved: list[tuple[str, list[str]]] = []

    for file_path in file_paths:
        shape_id, diagnostics = _resolve_shape_for_file_with_diagnostics(
            file_path,
            shape_index,
        )
        if shape_id is None:
            unresolved.append((file_path, diagnostics))
            continue
        grouped.setdefault(shape_id, []).append(file_path)

    for files in grouped.values():
        # Preserve deterministic ordering for downstream consumers.
        ordered_files = list(dict.fromkeys(files))
        files[:] = ordered_files

    return grouped, unresolved


@dataclass
class SourcePhaseResolution:
    phase: PhaseId
    issue: str | None = None


@dataclass
class GateFindingProjection:
    # IMPL(single-layer): Replace pin-centric routing fields with shape routing
    # fields (`shape_id`, optional `required_change_type` hint). Pin IDs can
    # survive only as non-authoritative intra-shape targeting hints.
    finding_index: int
    file_path: str | None = None
    pin_func_id: str | None = None
    required_change_type: str | None = None
    evidence_path: str | None = None

    def evidence_ref(self, gate_id: str) -> str:
        gate_ref = _normalize_text(gate_id) or "UNKNOWN_GATE"
        return f"gate_finding:{gate_ref}:{self.finding_index}"


def _project_gate_findings(
    gate_id: str,
    findings: Any,
) -> list[GateFindingProjection]:
    if not isinstance(findings, list):
        logger.warning(
            "Gate '%s' findings payload is %s, expected list; defaulting to file-level finding",
            gate_id,
            type(findings).__name__,
        )
        if isinstance(findings, dict):
            file_path = _first_nonempty(findings, _GATE_FINDING_FILE_KEYS)
            required_change_type = _first_nonempty(
                findings,
                _GATE_FINDING_REQUIRED_CHANGE_KEYS,
            )
            evidence_path = _first_nonempty(findings, _GATE_FINDING_EVIDENCE_KEYS)
        else:
            file_path = None
            required_change_type = None
            evidence_path = None
        return [
            GateFindingProjection(
                finding_index=0,
                file_path=file_path,
                required_change_type=required_change_type,
                evidence_path=evidence_path,
            )
        ]

    projected: list[GateFindingProjection] = []
    for idx, finding in enumerate(findings):
        if not isinstance(finding, dict):
            logger.warning(
                "Gate '%s' finding at index %s is %s, expected dict; keeping index-only provenance",
                gate_id,
                idx,
                type(finding).__name__,
            )
            projected.append(GateFindingProjection(finding_index=idx))
            continue

        projected.append(
            GateFindingProjection(
                finding_index=idx,
                file_path=_first_nonempty(finding, _GATE_FINDING_FILE_KEYS),
                pin_func_id=_first_nonempty(
                    finding,
                    ("pin_func_id", "matching_pin_func_id"),
                ),
                required_change_type=_first_nonempty(
                    finding,
                    _GATE_FINDING_REQUIRED_CHANGE_KEYS,
                ),
                evidence_path=_first_nonempty(finding, _GATE_FINDING_EVIDENCE_KEYS),
            )
        )
    return projected


def _resolve_required_change_type(
    explicit_change_type: str | None,
    routing: DemotionRouting,
) -> RequiredChangeType:
    explicit = _normalize_required_change_type(explicit_change_type)
    if explicit:
        return explicit

    if routing.action == "fix_in_layer":
        return "refactor_only"

    if routing.target_layer == "L2":
        return "wiring_only"
    if routing.target_layer == "L3":
        return "refactor_only"
    return "behavior_change"


def _authority_allows(
    active_phase: PhaseId,
    required_change_type: RequiredChangeType,
    routing: DemotionRouting,
) -> tuple[bool, str]:
    if routing.action == "block":
        return False, "triage_blocked"

    if active_phase == "libraries":
        return True, "queue_work_item"

    if active_phase == "architecture":
        if required_change_type == "refactor_only":
            return False, "architecture_refactor_out_of_authority"
        return True, "queue_work_item"

    if active_phase == "quality":
        if required_change_type == "refactor_only":
            return True, "queue_work_item"
        return False, "quality_restricts_blocking"

    return False, "unknown_active_phase"


@dataclass
class RoutingBatch:
    """Result of routing a batch of failures."""

    # IMPL(single-layer): Replace ticket/routing outputs with
    # `created_work_items`, `blocked_findings`, and `diagnostics` so the router
    # emits phase-local work (Section 8.2) instead of demotion tickets.
    created_work_items: list[WorkItem] = field(default_factory=list)
    blocked_findings: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


class DemotionRouter:
    """Routes failure evidence into work items and blocked findings."""

    def __init__(
        self,
        run_id: str = "",
        active_layer: str = "libraries",
    ) -> None:
        self._run_id = run_id
        self._active_phase = _normalize_phase(active_layer, fallback="libraries")
        self._active_layer = _PHASE_TO_LAYER[self._active_phase]

    def _build_blocked_finding(
        self,
        *,
        source: str,
        source_id: str | None,
        slice_id: str,
        finding_index: int | None,
        phase: PhaseId,
        failing_files: list[str],
        failing_pins: list[str],
        evidence_refs: list[str],
        reason: str,
        diagnostics: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "source": source,
            "source_id": source_id,
            "slice_id": slice_id,
            "finding_index": finding_index,
            "phase": phase,
            "failing_files": failing_files,
            "failing_pins": failing_pins,
            "evidence_refs": evidence_refs,
            "reason": reason,
            "diagnostics": diagnostics or [],
        }

    def _append_blocked(
        self,
        batch: RoutingBatch,
        *,
        source: str,
        source_id: str | None,
        slice_id: str,
        finding_index: int,
        phase: PhaseId,
        failing_files: list[str],
        failing_pins: list[str],
        evidence_refs: list[str],
        reason: str,
        diagnostics: list[str] | None = None,
    ) -> None:
        blocked = self._build_blocked_finding(
            source=source,
            source_id=source_id,
            slice_id=slice_id,
            finding_index=finding_index,
            phase=phase,
            failing_files=failing_files,
            failing_pins=failing_pins,
            evidence_refs=evidence_refs,
            reason=reason,
            diagnostics=diagnostics,
        )
        batch.blocked_findings.append(blocked)
        batch.diagnostics.append(f"{source}:{reason}")

    def _build_work_item(
        self,
        *,
        source: str,
        source_id: str | None,
        slice_id: str,
        finding_index: int,
        phase: PhaseId,
        title: str,
        description: str,
        shape_id: ShapeId,
        required_change_type: RequiredChangeType,
        routing: DemotionRouting,
        files: list[str],
        evidence_refs: list[str],
        failing_pins: list[str],
        required_shape_metadata: dict[str, Any],
    ) -> WorkItem:
        now = _utc_now()
        file_locations = [WorkItemLocation(file_path=file_path) for file_path in files]
        return WorkItem(
            work_item_id=f"demotion:{uuid.uuid4().hex[:12]}",
            run_id=self._run_id,
            slice_id=slice_id,
            title=title[:140],
            description=description,
            shape_id=shape_id,
            created_in_phase=phase,
            required_change_type=required_change_type,
            status="NEW",
            kind="SPEC_WORK",
            priority="normal",
            file_locations=file_locations,
            evidence_refs=evidence_refs,
            contract_ids=[],
            verifier_ids=[],
            created_at=now,
            updated_at=now,
            metadata={
                "created_phase": phase,
                "source": source,
                "source_id": source_id,
                "finding_index": finding_index,
                "triage_reason": routing.reason,
                "triage_action": routing.action,
                "triage_confidence": routing.confidence,
                "triage_diagnostics": routing.diagnostics,
                "required_change_type": required_change_type,
                "failing_pins": failing_pins,
                **required_shape_metadata,
            },
        )

    def _route_to_items(
        self,
        batch: RoutingBatch,
        *,
        source: str,
        source_id: str | None,
        source_phase: PhaseId,
        slice_id: str,
        finding_index: int,
        finding_description: str,
        category: str,
        dimension: str,
        tags: list[str],
        explicit_change_type: str | None,
        file_paths: list[str],
        evidence_paths: list[str],
        shape_index: ShapePackIndex,
        failing_pins: list[str],
    ) -> None:
        if not file_paths:
            reason = "no failing files available for shape routing"
            self._append_blocked(
                batch,
                source=source,
                source_id=source_id,
                slice_id=slice_id,
                finding_index=finding_index,
                phase=self._active_phase,
                failing_files=[],
                failing_pins=failing_pins,
                evidence_refs=evidence_paths,
                reason=reason,
                diagnostics=["missing_file_path"],
            )
            return

        grouped, unresolved = _group_files_by_shape(file_paths, shape_index)
        for file_path, diag in unresolved:
            self._append_blocked(
                batch,
                source=source,
                source_id=source_id,
                slice_id=slice_id,
                finding_index=finding_index,
                phase=self._active_phase,
                failing_files=[file_path],
                failing_pins=failing_pins,
                evidence_refs=evidence_paths,
                reason="ownership could not be resolved for failing file",
                diagnostics=diag,
            )

        if not grouped:
            return

        for shape_id, shape_files in grouped.items():
            shape = shape_index.shapes.get(shape_id)
            shape_status = ""
            requires_verifier_refresh = False
            if shape is not None:
                shape_status = str(shape.status)
                requires_verifier_refresh = bool(shape.requires_verifier_refresh)

            context = DemotionContext(
                active_layer=self._active_layer,
                source_layer=_PHASE_TO_LAYER[source_phase],
                source=source,
                gate=source_id,
                category=category,
                dimension=dimension,
                tags=tags,
                required_change_type=explicit_change_type or "",
                failing_files=shape_files,
                failing_pins=failing_pins,
                evidence_paths=evidence_paths,
            )
            routing = triage(context)
            required_change_type = _resolve_required_change_type(
                explicit_change_type,
                routing,
            )

            if shape_status == "PROPOSAL" or requires_verifier_refresh:
                required_change_type = "spec_change"

            allowed, outcome = _authority_allows(
                self._active_phase,
                required_change_type,
                routing,
            )
            if not allowed:
                self._append_blocked(
                    batch,
                    source=source,
                    source_id=source_id,
                    slice_id=slice_id,
                    finding_index=finding_index,
                    phase=self._active_phase,
                    failing_files=shape_files,
                    failing_pins=failing_pins,
                    evidence_refs=evidence_paths,
                    reason=outcome,
                    diagnostics=([f"triage={routing.reason}"] + routing.diagnostics),
                )
                continue

            item_title = (
                f"[{source}] {source_id or 'finding'} for shape {shape_id}"
            )
            item_description = (
                f"{finding_description} routing_outcome={outcome} "
                f"triage_reason={routing.reason} triage_confidence={routing.confidence}"
            )
            work_item = self._build_work_item(
                source=source,
                source_id=source_id,
                slice_id=slice_id,
                finding_index=finding_index,
                phase=self._active_phase,
                title=item_title,
                description=item_description,
                shape_id=shape_id,
                required_change_type=required_change_type,
                routing=routing,
                files=shape_files,
                evidence_refs=evidence_paths,
                failing_pins=failing_pins,
                required_shape_metadata={
                    "shape_status": shape_status,
                    "shape_requires_verifier_refresh": requires_verifier_refresh,
                    "source_phase": source_phase,
                },
            )
            batch.created_work_items.append(work_item)

    def route_gate_failures(
        self,
        *,
        slice_id: str,
        gate_results: list[dict[str, Any]],
        shape_index: ShapePackIndex,
    ) -> RoutingBatch:
        """Route gate failures into phase-local work items."""
        # IMPL(single-layer): Extend signature with `shape_index` and resolve a
        # deterministic owner shape for each failing file before triage.
        # Unresolved or ambiguous ownership must emit blocked diagnostics (no
        # speculative routing), matching Section 8.2.
        batch = RoutingBatch()

        if not isinstance(gate_results, list):
            reason = "gate_results must be a list"
            logger.warning("route_gate_failures payload invalid: %s", reason)
            batch.diagnostics.append(f"GATE_BATCH_INVALID:{reason}")
            return batch

        for index, gate_result in enumerate(gate_results):
            if not isinstance(gate_result, dict):
                reason = f"gate result at index {index} is {type(gate_result).__name__}"
                logger.warning("Invalid gate result payload: %s", reason)
                self._append_blocked(
                    batch,
                    source="GATE",
                    source_id=None,
                    slice_id=slice_id,
                    finding_index=index,
                    phase=self._active_phase,
                    failing_files=[],
                    failing_pins=[],
                    evidence_refs=[],
                    reason=reason,
                    diagnostics=["invalid_gate_result_type"],
                )
                continue

            gate_id = _normalize_text(gate_result.get("gate_id"))
            passed = bool(gate_result.get("passed", False))
            if passed:
                continue

            source_phase, source_issue = _infer_source_phase(
                gate_result,
                fallback=self._active_phase,
                gate_id=gate_id,
            )
            if source_issue:
                batch.diagnostics.append(f"GATE_SOURCE_PHASE:{source_issue}")

            source_issue_type = _normalize_text(gate_result.get("source", "ALGORITHMIC_GATE"))
            source = source_issue_type or "ALGORITHMIC_GATE"

            findings = _project_gate_findings(
                gate_id or "UNKNOWN_GATE",
                gate_result.get("findings", []),
            )

            fallback_file = _first_nonempty(gate_result, _GATE_FINDING_FILE_KEYS)
            fallback_evidence = _normalize_text_list(
                gate_result.get("evidence") or gate_result.get("evidence_path")
            )
            if not findings:
                findings = [
                    GateFindingProjection(
                        finding_index=0,
                        file_path=fallback_file,
                        required_change_type=_first_nonempty(gate_result, _GATE_FINDING_REQUIRED_CHANGE_KEYS),
                        evidence_path=_first_nonempty(gate_result, _GATE_FINDING_EVIDENCE_KEYS),
                    )
                ]

            for finding in findings:
                finding_files = _normalize_text_list(finding.file_path)
                evidence_refs = _unique_ordered(
                    [
                        *fallback_evidence,
                        finding.evidence_path or "",
                        finding.evidence_ref(gate_id or "UNKNOWN_GATE"),
                    ]
                )
                explicit_change_type = finding.required_change_type
                if not explicit_change_type:
                    explicit_change_type = _first_nonempty(gate_result, _GATE_FINDING_REQUIRED_CHANGE_KEYS)

                self._route_to_items(
                    batch,
                    source=source,
                    source_id=gate_id,
                    source_phase=source_phase,
                    slice_id=slice_id,
                    finding_index=finding.finding_index,
                    finding_description=f"gate failure in {gate_id}",
                    category=_normalize_text(gate_result.get("category", "")) or "",
                    dimension=_normalize_text(gate_result.get("dimension", "")) or "",
                    tags=_normalize_text_list(gate_result.get("tags", [])),
                    explicit_change_type=explicit_change_type,
                    file_paths=finding_files,
                    evidence_paths=evidence_refs,
                    shape_index=shape_index,
                    failing_pins=_normalize_text_list(finding.pin_func_id or ""),
                )

            if source_issue:
                logger.warning(
                    "Gate %s source phase resolution issue for result[%s]: %s",
                    gate_id,
                    index,
                    source_issue,
                )

        return batch

    def route_test_failures(
        self,
        *,
        slice_id: str,
        test_failures: list[dict[str, Any]],
        shape_index: ShapePackIndex,
    ) -> RoutingBatch:
        """Route test failures into phase-local work items."""
        batch = RoutingBatch()

        if not isinstance(test_failures, list):
            reason = "test_failures must be a list"
            logger.warning("route_test_failures payload invalid: %s", reason)
            batch.diagnostics.append(f"TEST_BATCH_INVALID:{reason}")
            return batch

        for index, failure in enumerate(test_failures):
            if not isinstance(failure, dict):
                reason = f"test failure at index {index} is {type(failure).__name__}"
                logger.warning("Invalid test failure payload: %s", reason)
                self._append_blocked(
                    batch,
                    source="TEST_FAILURE",
                    source_id=None,
                    slice_id=slice_id,
                    finding_index=index,
                    phase=self._active_phase,
                    failing_files=[],
                    failing_pins=[],
                    evidence_refs=[],
                    reason=reason,
                    diagnostics=["invalid_test_failure_type"],
                )
                continue

            source_phase, source_issue = _infer_source_phase(
                failure,
                fallback=self._active_phase,
                gate_id=None,
            )
            if source_issue:
                batch.diagnostics.append(f"TEST_SOURCE_PHASE:{source_issue}")

            failing_files = _normalize_text_list(failure.get("file") or failure.get("files", failure.get("file_path")))
            evidence_refs = _normalize_text_list(
                failure.get("raw_excerpt_path") or failure.get("evidence_path") or failure.get("evidence_paths")
            )
            if not evidence_refs:
                evidence_refs = _normalize_text_list(
                    failure.get("evidence")
                )

            if not failing_files:
                self._append_blocked(
                    batch,
                    source="TEST_FAILURE",
                    source_id=_normalize_text(failure.get("test_id")),
                    slice_id=slice_id,
                    finding_index=index,
                    phase=self._active_phase,
                    failing_files=[],
                    failing_pins=[],
                    evidence_refs=evidence_refs,
                    reason="test failure has no parseable file path",
                    diagnostics=["missing_file_paths"],
                )
                continue

            self._route_to_items(
                batch,
                source="TEST_FAILURE",
                source_id=_normalize_text(failure.get("test_id")) or f"test_{index}",
                source_phase=source_phase,
                slice_id=slice_id,
                finding_index=index,
                finding_description=f"test failure in {', '.join(failing_files)}",
                category="",
                dimension="",
                tags=[],
                explicit_change_type=_normalize_text(failure.get("required_change_type")),
                file_paths=failing_files,
                evidence_paths=evidence_refs,
                shape_index=shape_index,
                failing_pins=[],
            )

        return batch

    def route_review_findings(
        self,
        *,
        slice_id: str,
        findings: list[dict[str, Any]],
        shape_index: ShapePackIndex,
    ) -> RoutingBatch:
        """Route review findings into phase-local work items."""
        # IMPL(single-layer): For review findings, preserve
        # `required_change_type` as triage authority input and classify only for
        # current-phase handling (work item or block), with no backtracking.
        batch = RoutingBatch()

        if not isinstance(findings, list):
            reason = "findings must be a list"
            logger.warning("route_review_findings payload invalid: %s", reason)
            batch.diagnostics.append(f"REVIEW_BATCH_INVALID:{reason}")
            return batch

        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                reason = f"review finding at index {index} is {type(finding).__name__}"
                logger.warning("Invalid review finding payload: %s", reason)
                self._append_blocked(
                    batch,
                    source="REVIEW",
                    source_id=None,
                    slice_id=slice_id,
                    finding_index=index,
                    phase=self._active_phase,
                    failing_files=[],
                    failing_pins=[],
                    evidence_refs=[],
                    reason=reason,
                    diagnostics=["invalid_review_finding_type"],
                )
                continue

            source_phase, source_issue = _infer_source_phase(
                finding,
                fallback=self._active_phase,
                gate_id=None,
            )
            if source_issue:
                batch.diagnostics.append(f"REVIEW_SOURCE_PHASE:{source_issue}")

            finding_files = _normalize_text_list(finding.get("files", []))
            evidence_refs = _normalize_text_list(
                finding.get("evidence_paths")
                or finding.get("evidence")
                or finding.get("evidence_path", "")
            )
            category = _normalize_text(finding.get("category")) or ""
            dimension = _normalize_text(finding.get("dimension")) or ""
            tags = _normalize_text_list(finding.get("tags", []))
            required_change_type = _normalize_text(finding.get("required_change_type"))
            finding_desc = _normalize_text(finding.get("description")) or _normalize_text(finding.get("title")) or "review finding"

            if not finding_files:
                self._append_blocked(
                    batch,
                    source="REVIEW",
                    source_id=category or f"finding_{index}",
                    slice_id=slice_id,
                    finding_index=index,
                    phase=self._active_phase,
                    failing_files=[],
                    failing_pins=_normalize_text_list(finding.get("pins", [])),
                    evidence_refs=evidence_refs,
                    reason="review finding has no parseable file paths",
                    diagnostics=["missing_file_paths"],
                )
                continue

            self._route_to_items(
                batch,
                source="REVIEW",
                source_id=category or f"finding_{index}",
                source_phase=source_phase,
                slice_id=slice_id,
                finding_index=index,
                finding_description=finding_desc,
                category=category,
                dimension=dimension,
                tags=tags,
                explicit_change_type=required_change_type,
                file_paths=finding_files,
                evidence_paths=evidence_refs,
                shape_index=shape_index,
                failing_pins=_normalize_text_list(finding.get("pins", [])),
            )

        return batch
