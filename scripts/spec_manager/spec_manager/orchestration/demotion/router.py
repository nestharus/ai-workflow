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
    triage,
)

logger = logging.getLogger(__name__)


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
        self._active_layer = active_layer

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
        ticket = DemotionTicket(
            run_id=self._run_id,
            source=ctx.source or "GATE_FAILURE",
            category=ctx.category or "",
            gate=ctx.gate,
            target_layer=routing.target_layer,
            severity=ticket_severity,
            failing_pins=list(ctx.failing_pins),
            failing_files=list(ctx.failing_files),
            diagnosis=routing.reason,
            evidence_refs=list(ctx.evidence_paths),
        )

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

            gate_id = gr.get("gate_id", "")
            findings = gr.get("findings", [])

            # Extract failing files and pins from findings
            failing_files = set()
            failing_pins = set()
            for finding in findings:
                if f := finding.get("file_path", finding.get("arch_file", "")):
                    failing_files.add(f)
                if p := finding.get("pin_func_id", finding.get("matching_pin_func_id", "")):
                    failing_pins.add(p)

            ctx = DemotionContext(
                active_layer=self._active_layer,
                source_layer=self._active_layer,
                source="GATE_FAILURE",
                gate=gate_id,
                failing_files=list(failing_files),
                failing_pins=list(failing_pins),
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
            ctx = DemotionContext(
                active_layer=self._active_layer,
                source_layer=self._active_layer,
                source="TEST_FAILURE",
                failing_files=[failure.get("file", "")],
                evidence_paths=[failure.get("raw_excerpt_path", "")],
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

            ctx = DemotionContext(
                active_layer=self._active_layer,
                source_layer=self._active_layer,
                source="REVIEW",
                category=category,
                dimension=finding.get("dimension", ""),
                tags=list(finding.get("tags", []) or []),
                required_change_type=finding.get("required_change_type", ""),
                failing_files=finding.get("files", []),
                failing_pins=finding.get("pins", []),
                evidence_paths=finding.get("evidence_paths", []),
            )

            ticket, routing = self.route(ctx)
            ticket.slice_id = slice_id
            ticket.diagnosis = finding.get("description", routing.reason)
            batch.tickets.append(ticket)
            batch.routings.append(routing)

        return batch
