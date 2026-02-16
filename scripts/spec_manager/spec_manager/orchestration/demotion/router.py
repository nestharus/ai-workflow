"""Demotion router: converts failure evidence into DemotionTickets.

Consumes gate violations, test failures, and review findings, and
produces routed DemotionTickets targeting the correct layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from spec_manager.orchestration.demotion import DemotionTicket
from spec_manager.orchestration.demotion.triage import (
    DemotionContext,
    DemotionRouting,
    infer_gate_source_layer,
    triage,
)

logger = logging.getLogger(__name__)
_SOURCE_LAYER_KEYS = ("source_layer", "failure_layer", "layer", "origin_layer")
_GATE_FINDING_FILE_KEYS = ("file_path", "arch_file")
_GATE_FINDING_PIN_KEYS = ("pin_func_id", "matching_pin_func_id")
_GATE_FINDING_EVIDENCE_KEYS = ("raw_excerpt_path", "evidence_path", "excerpt_path")


def _normalize_layer(layer: Any) -> str | None:
    normalized = str(layer or "").strip().upper()
    if normalized in {"L1", "L2", "L3"}:
        return normalized
    return None


def _normalize_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if normalized:
        return normalized
    return None


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


@dataclass
class SourceLayerResolution:
    layer: str | None
    issue: str | None = None


@dataclass
class GateFindingProjection:
    finding_index: int
    file_path: str | None = None
    pin_func_id: str | None = None
    evidence_path: str | None = None

    def evidence_ref(self, gate_id: str) -> str:
        gate_ref = _normalize_text(gate_id) or "UNKNOWN_GATE"
        return f"gate_finding:{gate_ref}:{self.finding_index}"


def _project_gate_findings(gate_id: str, findings: Any) -> list[GateFindingProjection]:
    if not isinstance(findings, list):
        logger.warning(
            "Gate '%s' findings payload is %s, expected list; ignoring payload",
            gate_id,
            type(findings).__name__,
        )
        return []

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
                pin_func_id=_first_nonempty(finding, _GATE_FINDING_PIN_KEYS),
                evidence_path=_first_nonempty(finding, _GATE_FINDING_EVIDENCE_KEYS),
            )
        )
    return projected


def _active_layer_or_default(*layers: str | None) -> str:
    for layer in layers:
        normalized = _normalize_layer(layer)
        if normalized:
            return normalized
    return "L1"


def _build_blocked_ticket(
    *,
    run_id: str,
    source: str,
    category: str,
    gate: str | None,
    active_layer: str,
    diagnosis: str,
    failing_files: list[str] | None = None,
    failing_pins: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    diagnostics: list[str] | None = None,
) -> tuple[DemotionTicket, DemotionRouting]:
    layer = _active_layer_or_default(active_layer)
    normalized_source = _normalize_text(source) or "ALGORITHMIC_GATE"
    ticket = DemotionTicket(
        run_id=run_id,
        source=normalized_source,
        category=category or "",
        gate=gate,
        target_layer=layer,
        severity="BLOCKER",
        origin_layer=layer,
        hop_trace=[layer, layer],
        failing_pins=list(failing_pins or []),
        failing_files=list(failing_files or []),
        diagnosis=diagnosis,
        evidence_refs=list(evidence_refs or []),
    )
    ticket.questions.extend(list(diagnostics or []))
    routing = DemotionRouting(
        target_layer=layer,
        action="block",
        reason=diagnosis,
        confidence=1.0,
        diagnostics=list(diagnostics or []),
    )
    return ticket, routing


def _infer_source_layer(
    evidence: dict[str, Any],
    *,
    fallback: str,
    gate_id: str | None = None,
) -> SourceLayerResolution:
    evidence_layers: list[tuple[str, str]] = []
    for key in _SOURCE_LAYER_KEYS:
        normalized = _normalize_layer(evidence.get(key))
        if normalized:
            evidence_layers.append((key, normalized))

    inferred_gate_layer = infer_gate_source_layer(gate_id)
    evidence_layer = evidence_layers[0][1] if evidence_layers else None
    distinct_evidence_layers = {layer for _, layer in evidence_layers}
    issue: str | None = None

    if len(distinct_evidence_layers) > 1:
        issue = "Conflicting source-layer fields in evidence: " + ", ".join(
            f"{key}={layer}" for key, layer in evidence_layers
        )
    if inferred_gate_layer and evidence_layer and inferred_gate_layer != evidence_layer:
        mismatch = (
            f"Gate '{gate_id}' infers source layer {inferred_gate_layer}, "
            f"but evidence fields indicate {evidence_layer}"
        )
        issue = f"{issue}; {mismatch}" if issue else mismatch

    if inferred_gate_layer:
        return SourceLayerResolution(layer=inferred_gate_layer, issue=issue)
    if evidence_layer:
        return SourceLayerResolution(layer=evidence_layer, issue=issue)

    normalized_fallback = _normalize_layer(fallback)
    if normalized_fallback:
        return SourceLayerResolution(layer=normalized_fallback, issue=issue)
    unresolved = issue or "Could not infer source layer from gate, evidence, or fallback"
    return SourceLayerResolution(layer=None, issue=unresolved)


def _gate_source_for_layer(layer: str) -> str:
    normalized = _normalize_layer(layer) or "L1"
    return "ALGORITHMIC_GATE" if normalized == "L1" else "ARCH_GATE"


@dataclass
class RoutingBatch:
    """Result of routing a batch of failures."""

    tickets: list[DemotionTicket] = field(default_factory=list)
    routings: list[DemotionRouting] = field(default_factory=list)


class DemotionRouter:
    """Routes failure evidence into DemotionTickets.

    Wraps the triage classifier and extends DemotionTicket with
    origin_layer and hop_trace for multi-layer traceability.

    Args:
        run_id: Current run identifier.
        active_layer: Currently active promotion layer.
    """

    def __init__(
        self,
        run_id: str = "",
        active_layer: str = "L1",
    ) -> None:
        self._run_id = run_id
        normalized_active = _normalize_layer(active_layer)
        if not normalized_active:
            logger.warning(
                "DemotionRouter active_layer '%s' is invalid; defaulting to L1",
                active_layer,
            )
            normalized_active = "L1"
        self._active_layer = normalized_active

    def route(self, ctx: DemotionContext) -> tuple[DemotionTicket, DemotionRouting]:
        """Triage a single failure and produce a DemotionTicket.

        Args:
            ctx: Failure context with evidence.

        Returns:
            (DemotionTicket, DemotionRouting) pair.
        """
        routing = triage(ctx)

        ticket_severity = (
            "BLOCKER" if (routing.action == "block" or routing.confidence >= 0.8) else "MAJOR"
        )
        origin_layer = _active_layer_or_default(
            ctx.source_layer, ctx.active_layer, self._active_layer
        )
        ticket = DemotionTicket(
            run_id=self._run_id,
            source=ctx.source or "ALGORITHMIC_GATE",
            category=ctx.category or "",
            gate=ctx.gate,
            target_layer=routing.target_layer,
            severity=ticket_severity,
            origin_layer=origin_layer,
            hop_trace=[origin_layer, routing.target_layer],
            failing_pins=list(ctx.failing_pins),
            failing_files=list(ctx.failing_files),
            diagnosis=routing.reason,
            evidence_refs=list(ctx.evidence_paths),
        )
        if routing.diagnostics:
            ticket.questions.extend(routing.diagnostics)

        return ticket, routing

    def route_gate_failures(
        self,
        *,
        slice_id: str,
        gate_results: list[dict[str, Any]],
    ) -> RoutingBatch:
        """Route gate failures into DemotionTickets.

        Args:
            slice_id: Slice identifier.
            gate_results: List of gate result dicts from LayerPromotionGate.

        Returns:
            RoutingBatch with all produced tickets.
        """
        batch = RoutingBatch()

        for gr in gate_results:
            if gr.get("passed", True):
                continue

            gate_id = _normalize_text(gr.get("gate_id")) or ""
            findings = _project_gate_findings(gate_id, gr.get("findings", []))
            source_resolution = _infer_source_layer(
                gr,
                fallback=self._active_layer,
                gate_id=gate_id,
            )
            source_layer = source_resolution.layer
            if source_resolution.issue:
                logger.warning(
                    "Gate '%s' source-layer ambiguity: %s", gate_id, source_resolution.issue
                )

            failing_files = [finding.file_path for finding in findings if finding.file_path]
            failing_pins = [finding.pin_func_id for finding in findings if finding.pin_func_id]
            evidence_paths: list[str] = []
            for finding in findings:
                if finding.evidence_path:
                    evidence_paths.append(finding.evidence_path)
                evidence_paths.append(finding.evidence_ref(gate_id))

            if not failing_files and not failing_pins and not evidence_paths:
                diagnosis = (
                    f"Gate failure '{gate_id}' is missing file/pin/evidence references; "
                    "manual triage required to preserve traceability"
                )
                ticket, routing = _build_blocked_ticket(
                    run_id=self._run_id,
                    source="ALGORITHMIC_GATE",
                    category="",
                    gate=gate_id or None,
                    active_layer=self._active_layer,
                    diagnosis=diagnosis,
                    diagnostics=["MISSING_TRACE_REFERENCES"],
                )
                ticket.slice_id = slice_id
                batch.tickets.append(ticket)
                batch.routings.append(routing)
                continue

            if not source_layer:
                diagnosis = (
                    f"Cannot route gate failure '{gate_id}': source layer unresolved "
                    f"({source_resolution.issue or 'missing source metadata'})"
                )
                ticket, routing = _build_blocked_ticket(
                    run_id=self._run_id,
                    source="ALGORITHMIC_GATE",
                    category="",
                    gate=gate_id or None,
                    active_layer=self._active_layer,
                    diagnosis=diagnosis,
                    failing_files=failing_files,
                    failing_pins=failing_pins,
                    evidence_refs=evidence_paths,
                    diagnostics=["SOURCE_LAYER_UNRESOLVED"],
                )
                ticket.slice_id = slice_id
                batch.tickets.append(ticket)
                batch.routings.append(routing)
                continue

            ctx = DemotionContext(
                active_layer=self._active_layer,
                source_layer=source_layer,
                source=_gate_source_for_layer(source_layer),
                gate=gate_id,
                failing_files=failing_files,
                failing_pins=failing_pins,
                evidence_paths=evidence_paths,
            )

            ticket, routing = self.route(ctx)
            ticket.slice_id = slice_id
            batch.tickets.append(ticket)
            batch.routings.append(routing)

        return batch

    def route_test_failures(
        self,
        *,
        slice_id: str,
        test_failures: list[dict[str, Any]],
    ) -> RoutingBatch:
        """Route test failures into DemotionTickets.

        Args:
            slice_id: Slice identifier.
            test_failures: List of test failure dicts.

        Returns:
            RoutingBatch with all produced tickets.
        """
        batch = RoutingBatch()

        for failure in test_failures:
            source_resolution = _infer_source_layer(
                failure,
                fallback=self._active_layer,
            )
            source_layer = source_resolution.layer
            failing_files = _normalize_text_list(failure.get("file"))
            evidence_paths = _normalize_text_list(failure.get("raw_excerpt_path"))
            if not failing_files and not evidence_paths:
                diagnosis = (
                    "Test failure is missing both file path and evidence path; "
                    "manual triage required to preserve traceability"
                )
                ticket, routing = _build_blocked_ticket(
                    run_id=self._run_id,
                    source="TEST_FAILURE",
                    category="",
                    gate=None,
                    active_layer=self._active_layer,
                    diagnosis=diagnosis,
                    diagnostics=["MISSING_TRACE_REFERENCES"],
                )
                ticket.slice_id = slice_id
                batch.tickets.append(ticket)
                batch.routings.append(routing)
                continue
            if not source_layer:
                issue_desc = source_resolution.issue or "missing source metadata"
                diagnosis = (
                    "Test failure source layer could not be inferred; "
                    f"manual triage required ({issue_desc})"
                )
                ticket, routing = _build_blocked_ticket(
                    run_id=self._run_id,
                    source="TEST_FAILURE",
                    category="",
                    gate=None,
                    active_layer=self._active_layer,
                    diagnosis=diagnosis,
                    failing_files=failing_files,
                    evidence_refs=evidence_paths,
                    diagnostics=["SOURCE_LAYER_UNRESOLVED"],
                )
                ticket.slice_id = slice_id
                batch.tickets.append(ticket)
                batch.routings.append(routing)
                continue
            ctx = DemotionContext(
                active_layer=self._active_layer,
                source_layer=source_layer,
                source="TEST_FAILURE",
                failing_files=failing_files,
                evidence_paths=evidence_paths,
            )

            ticket, routing = self.route(ctx)
            ticket.slice_id = slice_id
            ticket.diagnosis = failure.get("message", routing.reason)
            batch.tickets.append(ticket)
            batch.routings.append(routing)

        return batch

    def route_review_findings(
        self,
        *,
        slice_id: str,
        findings: list[dict[str, Any]],
    ) -> RoutingBatch:
        """Route review findings into DemotionTickets.

        Review findings are routed via canonical finding fields
        (category/dimension/tags/required_change_type).

        Args:
            slice_id: Slice identifier.
            findings: Review finding dicts with category field.

        Returns:
            RoutingBatch with all produced tickets.
        """
        batch = RoutingBatch()

        for finding in findings:
            category = finding.get("category", "")
            source_resolution = _infer_source_layer(
                finding,
                fallback=self._active_layer,
            )
            source_layer = source_resolution.layer
            failing_files = _normalize_text_list(finding.get("files", []))
            failing_pins = _normalize_text_list(finding.get("pins", []))
            evidence_paths = _normalize_text_list(finding.get("evidence_paths", []))
            if not source_layer:
                issue_desc = source_resolution.issue or "missing source metadata"
                diagnosis = (
                    "Review finding source layer could not be inferred; "
                    f"manual triage required ({issue_desc})"
                )
                ticket, routing = _build_blocked_ticket(
                    run_id=self._run_id,
                    source="REVIEW",
                    category=category,
                    gate=None,
                    active_layer=self._active_layer,
                    diagnosis=diagnosis,
                    failing_files=failing_files,
                    failing_pins=failing_pins,
                    evidence_refs=evidence_paths,
                    diagnostics=["SOURCE_LAYER_UNRESOLVED"],
                )
                ticket.slice_id = slice_id
                batch.tickets.append(ticket)
                batch.routings.append(routing)
                continue

            ctx = DemotionContext(
                active_layer=self._active_layer,
                source_layer=source_layer,
                source="REVIEW",
                category=category,
                dimension=finding.get("dimension", ""),
                tags=list(finding.get("tags", []) or []),
                required_change_type=finding.get("required_change_type", ""),
                failing_files=failing_files,
                failing_pins=failing_pins,
                evidence_paths=evidence_paths,
            )

            ticket, routing = self.route(ctx)
            ticket.slice_id = slice_id
            ticket.diagnosis = finding.get("description", routing.reason)
            batch.tickets.append(ticket)
            batch.routings.append(routing)

        return batch
