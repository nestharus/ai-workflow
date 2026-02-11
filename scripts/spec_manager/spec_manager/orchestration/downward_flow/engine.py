"""DownwardFlowEngine: traces failures to pin origins and creates tickets.

Given failure evidence (test results, gate violations, review findings),
identifies failing pins via PinRegistry queries, traces backward to atoms,
classifies the failure via DemotionRouter, and produces DemotionTickets.

Invoked from:
- INTEGRATE step on test failures
- L3 review findings
- Architectural gate failures
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from spec_manager.orchestration.demotion.router import DemotionRouter, RoutingBatch
from spec_manager.orchestration.demotion.triage import DemotionContext

logger = logging.getLogger(__name__)

# Match pdd:pin marker comments in source
_PIN_MARKER_RE = re.compile(r"#\s*pdd:pin=(PIN-\S+)")


@dataclass
class FailureEvidence:
    """Raw failure evidence from tests, gates, or reviews."""

    source: str = ""  # TEST_FAILURE, GATE_FAILURE, REVIEW
    failing_files: list[str] = field(default_factory=list)
    failing_lines: list[dict[str, Any]] = field(default_factory=list)
    stack_trace: str = ""
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    review_findings: list[dict[str, Any]] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)


@dataclass
class TraceResult:
    """Result of tracing a failure through the pin graph."""

    located_pins: list[str] = field(default_factory=list)
    traced_atoms: list[str] = field(default_factory=list)
    trace_path: list[str] = field(default_factory=list)


class DownwardFlowEngine:
    """Traces failures through the pin graph to atom origins.

    Algorithm:
    1. Identify failing locations (files, line ranges)
    2. Map locations → pins via PinRegistry.pins_covering() or marker scan
    3. Trace backward via PinRegistry.trace_backward() to L1 atoms
    4. Classify and route via DemotionRouter
    5. Create DemotionTickets with evidence paths

    Args:
        run_id: Current run identifier.
        active_layer: Currently active promotion layer.
        pin_registry: PinFunctionRegistry instance for pin queries.
    """

    def __init__(
        self,
        *,
        run_id: str = "",
        active_layer: str = "L1",
        pin_registry: Any = None,
    ) -> None:
        self._run_id = run_id
        self._active_layer = active_layer
        self._pin_registry = pin_registry
        self._router = DemotionRouter(
            run_id=run_id,
            active_layer=active_layer,
        )

    def trace_and_route(self, evidence: FailureEvidence) -> RoutingBatch:
        """Trace failure evidence through pins and produce tickets.

        Dispatches to the appropriate handler based on evidence source.
        """
        if evidence.gate_results:
            return self._handle_gate_failures(evidence)
        if evidence.review_findings:
            return self._handle_review_findings(evidence)
        return self._handle_test_failures(evidence)

    def _handle_test_failures(self, evidence: FailureEvidence) -> RoutingBatch:
        """Trace test failures through pins to atoms."""
        batch = RoutingBatch()

        for file_path in evidence.failing_files:
            trace = self._trace_file(file_path)

            ctx = DemotionContext(
                active_layer=self._active_layer,
                source_layer=self._active_layer,
                source="TEST_FAILURE",
                failing_files=[file_path],
                failing_pins=trace.located_pins,
                evidence_paths=evidence.evidence_paths,
            )

            ticket, routing = self._router.route(ctx)
            ticket.run_id = self._run_id
            ticket.origin_layer = self._active_layer
            ticket.hop_trace = [self._active_layer, routing.target_layer]
            ticket.failing_atoms = trace.traced_atoms
            ticket.diagnosis = (
                f"Test failure in {file_path}: "
                f"pins={trace.located_pins}, atoms={trace.traced_atoms}"
            )

            batch.tickets.append(ticket)
            batch.routings.append(routing)

        return batch

    def _handle_gate_failures(self, evidence: FailureEvidence) -> RoutingBatch:
        """Route gate failures, enriching with pin tracing."""
        batch = self._router.route_gate_failures(
            slice_id="",
            gate_results=evidence.gate_results,
        )

        # Enrich tickets with pin trace info
        for ticket in batch.tickets:
            ticket.origin_layer = self._active_layer
            ticket.hop_trace = [self._active_layer, ticket.target_layer]

            # Trace failing files to atoms
            for file_path in ticket.failing_files:
                trace = self._trace_file(file_path)
                ticket.failing_atoms.extend(trace.traced_atoms)
                ticket.failing_pins = list(set(ticket.failing_pins) | set(trace.located_pins))

        return batch

    def _handle_review_findings(self, evidence: FailureEvidence) -> RoutingBatch:
        """Route review findings through pin tracing."""
        batch = self._router.route_review_findings(
            slice_id="",
            findings=evidence.review_findings,
        )

        for ticket in batch.tickets:
            ticket.origin_layer = self._active_layer
            ticket.hop_trace = [self._active_layer, ticket.target_layer]

            for file_path in ticket.failing_files:
                trace = self._trace_file(file_path)
                ticket.failing_atoms.extend(trace.traced_atoms)
                ticket.failing_pins = list(set(ticket.failing_pins) | set(trace.located_pins))

        return batch

    def _trace_file(self, file_path: str) -> TraceResult:
        """Trace a file through the pin registry to find covering pins and atoms."""
        result = TraceResult()

        # Strategy 1: Query pin registry for pins covering this file
        if self._pin_registry:
            try:
                covering = self._pin_registry.query_pin_functions_for_file(file_path)
                for pf in covering:
                    pin_id = getattr(pf, "pin_id", None) or getattr(pf, "id", "")
                    if pin_id:
                        result.located_pins.append(pin_id)

                # Trace backward through edges to find atom pins
                for pin_id in list(result.located_pins):
                    atoms = self._trace_backward(pin_id)
                    result.traced_atoms.extend(atoms)
            except Exception as exc:
                logger.debug("Pin registry query failed for %s: %s", file_path, exc)

        # Strategy 2: Scan file for pdd:pin markers
        if not result.located_pins:
            marker_pins = self._scan_markers(file_path)
            result.located_pins.extend(marker_pins)
            for pin_id in marker_pins:
                atoms = self._trace_backward(pin_id)
                result.traced_atoms.extend(atoms)

        # Deduplicate
        result.located_pins = list(dict.fromkeys(result.located_pins))
        result.traced_atoms = list(dict.fromkeys(result.traced_atoms))

        return result

    def _trace_backward(self, pin_id: str) -> list[str]:
        """Trace a pin backward through edges to find atom-level pins."""
        if not self._pin_registry:
            return []

        atoms: list[str] = []
        try:
            # Look for edges where this pin is a destination (imported by)
            importers = self._pin_registry.query_importers(pin_id)
            for imp in importers:
                imp_id = getattr(imp, "pin_id", None) or getattr(imp, "id", "")
                if imp_id and imp_id.startswith("PIN-ATOM-"):
                    atoms.append(imp_id)
                elif imp_id:
                    # Recurse one level (avoid deep recursion)
                    atoms.append(imp_id)
        except Exception as exc:
            logger.debug("Trace backward failed for %s: %s", pin_id, exc)

        return atoms

    def _scan_markers(self, file_path: str) -> list[str]:
        """Scan a file for pdd:pin= marker comments."""
        try:
            from pathlib import Path

            content = Path(file_path).read_text(encoding="utf-8")
            return _PIN_MARKER_RE.findall(content)
        except (OSError, UnicodeDecodeError):
            return []
