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
from spec_manager.orchestration.demotion.router import DemotionRouter, RoutingBatch
from spec_manager.orchestration.downward_flow.engine import (
    DownwardFlowEngine,
    FailureEvidence,
)

logger = logging.getLogger(__name__)


@dataclass
class ReviewFinding:
    """A single finding from a reviewer agent."""

    category: str = ""  # STYLE, QUALITY, LOGIC, ARCH, SPEC, UNDER_SPEC
    description: str = ""
    files: list[str] = field(default_factory=list)
    pins: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    severity: str = "MAJOR"  # BLOCKER, MAJOR, MINOR

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewFinding:
        """Create from a dict (reviewer agent output)."""
        return cls(
            category=data.get("category", ""),
            description=data.get("description", ""),
            files=data.get("files", []),
            pins=data.get("pins", []),
            evidence_paths=data.get("evidence_paths", []),
            severity=data.get("severity", "MAJOR"),
        )


@dataclass
class ConversionResult:
    """Result of converting review findings to demotion tickets."""

    tickets: list[DemotionTicket] = field(default_factory=list)
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0


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

    for raw in findings:
        finding = ReviewFinding.from_dict(raw)

        if not finding.category:
            result.skipped += 1
            continue

        # UNDER_SPEC findings produce under-spec events
        if finding.category.upper() == "UNDER_SPEC":
            result.under_spec_events.append({
                "kind": "REVIEW_UNDER_SPEC",
                "question": finding.description,
                "needed_for": ", ".join(finding.files) if finding.files else "unknown",
                "source": "REVIEW",
            })
            continue

        # Route through DownwardFlowEngine for pin tracing
        evidence = FailureEvidence(
            source="REVIEW",
            failing_files=finding.files,
            review_findings=[raw],
            evidence_paths=finding.evidence_paths,
        )

        batch = engine.trace_and_route(evidence)
        for ticket in batch.tickets:
            ticket.slice_id = slice_id
            ticket.diagnosis = finding.description
            result.tickets.append(ticket)

    return result
