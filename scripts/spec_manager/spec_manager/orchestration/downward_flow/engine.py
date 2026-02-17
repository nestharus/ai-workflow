# TODO(single-layer): DELETE — Downward flow engine traces failures backwards through
#   pins to atoms, then creates demotion tickets. Single-layer has no pin tracing and
#   no cross-layer demotion. Failure routing becomes: failing test/verifier → map to
#   owning shape → create work item with {phase, shape_id, required_change_type,
#   evidence} (Section 8.2, 11.1). Much simpler — no backward trace needed.
# IMPL(single-layer): `DemotionRouter.route_*` migrates to shape-index-aware
# routing and returns work-item/blocked-finding batches; this engine should not
# enrich router output with pin traces once that contract lands.
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

from spec_manager.orchestration.demotion import DemotionTicket
from spec_manager.orchestration.demotion.router import DemotionRouter, RoutingBatch
from spec_manager.orchestration.demotion.triage import DemotionContext, DemotionRouting

logger = logging.getLogger(__name__)

# Match pdd:pin marker comments in source
_PIN_MARKER_RE = re.compile(r"#\s*pdd:pin=(PIN-\S+)")
_TRACE_DEPTH_LIMIT = 12
_SOURCE_TO_KIND: dict[str, str] = {
    "TEST_FAILURE": "TEST",
    "ALGORITHMIC_GATE": "GATE",
    "ARCH_GATE": "GATE",
    "GATE_FAILURE": "GATE",
    "REVIEW": "REVIEW",
}
_KIND_TO_SOURCE: dict[str, str] = {
    "TEST": "TEST_FAILURE",
    "GATE": "ALGORITHMIC_GATE",
    "REVIEW": "REVIEW",
}


@dataclass(frozen=True)
class PinProjection:
    """Stable projection for registry pin identifiers."""

    pin_id: str


@dataclass
class BackwardTraceResult:
    """Trace result from backward traversal of a single pin."""

    traced_atoms: list[str] = field(default_factory=list)
    trace_path: list[str] = field(default_factory=list)
    degradations: list[str] = field(default_factory=list)


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
    degradations: list[str] = field(default_factory=list)


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

        Dispatches to the appropriate handler based on source-authoritative evidence.
        """
        source = str(evidence.source or "").strip().upper()
        declared_kind = _SOURCE_TO_KIND.get(source)
        populated_kinds = self._populated_kinds(evidence)

        if source and declared_kind is None:
            return self._build_evidence_issue_batch(
                evidence,
                reason=f"Unsupported FailureEvidence.source '{source}'",
                issue_code="UNSUPPORTED_SOURCE",
                declared_kind=None,
            )

        if declared_kind:
            if declared_kind not in populated_kinds:
                return self._build_evidence_issue_batch(
                    evidence,
                    reason=(
                        f"FailureEvidence.source '{source}' declares {declared_kind} evidence, "
                        f"but payload kinds are {sorted(populated_kinds) or ['NONE']}"
                    ),
                    issue_code="SOURCE_PAYLOAD_MISMATCH",
                    declared_kind=declared_kind,
                )
            extra_kinds = sorted(kind for kind in populated_kinds if kind != declared_kind)
            if extra_kinds:
                return self._build_evidence_issue_batch(
                    evidence,
                    reason=(
                        f"FailureEvidence.source '{source}' conflicts with "
                        f"additional payload kinds: {extra_kinds}"
                    ),
                    issue_code="AMBIGUOUS_EVIDENCE_PAYLOAD",
                    declared_kind=declared_kind,
                )
            return self._dispatch_kind(declared_kind, evidence)

        if len(populated_kinds) == 1:
            return self._dispatch_kind(next(iter(populated_kinds)), evidence)

        if len(populated_kinds) > 1:
            return self._build_evidence_issue_batch(
                evidence,
                reason=(
                    "FailureEvidence contains multiple populated payload kinds "
                    f"without authoritative source: {sorted(populated_kinds)}"
                ),
                issue_code="AMBIGUOUS_EVIDENCE_PAYLOAD",
                declared_kind=None,
            )

        return RoutingBatch()

    def _handle_test_failures(self, evidence: FailureEvidence) -> RoutingBatch:
        """Trace test failures through pins to atoms."""
        batch = RoutingBatch()
        if not evidence.failing_files:
            return self._build_evidence_issue_batch(
                evidence,
                reason=(
                    "TEST failure evidence did not include failing_files; "
                    "cannot map failure to pins without file anchors"
                ),
                issue_code="MISSING_FAILING_FILES",
                declared_kind="TEST",
            )

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
            self._augment_ticket_with_evidence(
                ticket,
                evidence,
                trace=trace,
                file_path=file_path,
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
            aggregate_trace = TraceResult()

            # Trace failing files to atoms
            for file_path in ticket.failing_files:
                trace = self._trace_file(file_path)
                ticket.failing_atoms = self._merge_unique(ticket.failing_atoms, trace.traced_atoms)
                ticket.failing_pins = self._merge_unique(ticket.failing_pins, trace.located_pins)
                aggregate_trace.trace_path.extend(trace.trace_path)
                aggregate_trace.degradations.extend(trace.degradations)
            aggregate_trace.trace_path = self._dedupe_preserve_order(aggregate_trace.trace_path)
            aggregate_trace.degradations = self._dedupe_preserve_order(aggregate_trace.degradations)
            self._augment_ticket_with_evidence(ticket, evidence, trace=aggregate_trace)

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
            aggregate_trace = TraceResult()

            for file_path in ticket.failing_files:
                trace = self._trace_file(file_path)
                ticket.failing_atoms = self._merge_unique(ticket.failing_atoms, trace.traced_atoms)
                ticket.failing_pins = self._merge_unique(ticket.failing_pins, trace.located_pins)
                aggregate_trace.trace_path.extend(trace.trace_path)
                aggregate_trace.degradations.extend(trace.degradations)
            aggregate_trace.trace_path = self._dedupe_preserve_order(aggregate_trace.trace_path)
            aggregate_trace.degradations = self._dedupe_preserve_order(aggregate_trace.degradations)
            self._augment_ticket_with_evidence(ticket, evidence, trace=aggregate_trace)

        return batch

    def _trace_file(self, file_path: str) -> TraceResult:
        """Trace a file through the pin registry to find covering pins and atoms."""
        result = TraceResult()
        result.trace_path.append(f"FILE:{file_path}")

        # Strategy 1: Query pin registry for pins covering this file
        if self._pin_registry:
            try:
                covering = self._pin_registry.query_pin_functions_for_file(file_path)
                projected, projection_issues = self._project_pin_refs(
                    covering,
                    query_name="query_pin_functions_for_file",
                    query_subject=file_path,
                )
                result.degradations.extend(projection_issues)
                for pf in projected:
                    pin_id = pf.pin_id
                    if pin_id:
                        result.located_pins.append(pin_id)
                        result.trace_path.append(f"FILE_PIN:{file_path}->{pin_id}")

                # Trace backward through edges to find atom pins
                for pin_id in list(result.located_pins):
                    backward = self._trace_backward(pin_id)
                    result.traced_atoms.extend(backward.traced_atoms)
                    result.trace_path.extend(backward.trace_path)
                    result.degradations.extend(backward.degradations)
            except Exception as exc:
                issue = f"PIN_QUERY_FAILED:{file_path}:{type(exc).__name__}:{exc}"
                logger.warning("Pin registry query failed for %s: %s", file_path, exc)
                result.degradations.append(issue)
                result.trace_path.append(f"TRACE_DEGRADED:{issue}")

        # Strategy 2: Scan file for pdd:pin markers
        if not result.located_pins:
            marker_pins = self._scan_markers(file_path)
            result.located_pins.extend(marker_pins)
            for pin_id in marker_pins:
                result.trace_path.append(f"MARKER_PIN:{file_path}->{pin_id}")
                backward = self._trace_backward(pin_id)
                result.traced_atoms.extend(backward.traced_atoms)
                result.trace_path.extend(backward.trace_path)
                result.degradations.extend(backward.degradations)

        # Deduplicate
        result.located_pins = self._dedupe_preserve_order(result.located_pins)
        result.traced_atoms = self._dedupe_preserve_order(result.traced_atoms)
        result.trace_path = self._dedupe_preserve_order(result.trace_path)
        result.degradations = self._dedupe_preserve_order(result.degradations)

        return result

    def _trace_backward(self, pin_id: str) -> BackwardTraceResult:
        """Trace a pin backward through edges to find atom-level pins."""
        if not self._pin_registry:
            return BackwardTraceResult()

        result = BackwardTraceResult()
        visited: set[str] = set()

        def walk(current_pin: str, *, depth: int) -> None:
            if depth > _TRACE_DEPTH_LIMIT:
                issue = f"TRACE_DEPTH_LIMIT:{current_pin}:{_TRACE_DEPTH_LIMIT}"
                result.degradations.append(issue)
                result.trace_path.append(f"TRACE_DEGRADED:{issue}")
                return
            if current_pin in visited:
                result.trace_path.append(f"TRACE_CYCLE:{current_pin}")
                return
            visited.add(current_pin)

            try:
                importers = self._pin_registry.query_importers(current_pin)
            except Exception as exc:
                issue = f"TRACE_QUERY_FAILED:{current_pin}:{type(exc).__name__}:{exc}"
                logger.warning("Trace backward failed for %s: %s", current_pin, exc)
                result.degradations.append(issue)
                result.trace_path.append(f"TRACE_DEGRADED:{issue}")
                return

            projected, projection_issues = self._project_pin_refs(
                importers,
                query_name="query_importers",
                query_subject=current_pin,
            )
            result.degradations.extend(projection_issues)
            if projection_issues:
                for issue in projection_issues:
                    result.trace_path.append(f"TRACE_DEGRADED:{issue}")

            if not projected:
                result.trace_path.append(f"TRACE_EMPTY:{current_pin}")
                return

            for importer in projected:
                importer_pin = importer.pin_id
                result.trace_path.append(f"TRACE_EDGE:{current_pin}<-{importer_pin}")
                if importer_pin.startswith("PIN-ATOM-"):
                    result.traced_atoms.append(importer_pin)
                else:
                    walk(importer_pin, depth=depth + 1)

        walk(pin_id, depth=0)
        result.traced_atoms = self._dedupe_preserve_order(result.traced_atoms)
        result.trace_path = self._dedupe_preserve_order(result.trace_path)
        result.degradations = self._dedupe_preserve_order(result.degradations)
        return result

    def _scan_markers(self, file_path: str) -> list[str]:
        """Scan a file for pdd:pin= marker comments."""
        try:
            from pathlib import Path

            content = Path(file_path).read_text(encoding="utf-8")
            return _PIN_MARKER_RE.findall(content)
        except (OSError, UnicodeDecodeError):
            return []

    def _dispatch_kind(self, kind: str, evidence: FailureEvidence) -> RoutingBatch:
        if kind == "TEST":
            return self._handle_test_failures(evidence)
        if kind == "GATE":
            return self._handle_gate_failures(evidence)
        if kind == "REVIEW":
            return self._handle_review_findings(evidence)
        return self._build_evidence_issue_batch(
            evidence,
            reason=f"Unsupported dispatch kind '{kind}'",
            issue_code="UNSUPPORTED_DISPATCH_KIND",
            declared_kind=kind,
        )

    @staticmethod
    def _populated_kinds(evidence: FailureEvidence) -> set[str]:
        kinds: set[str] = set()
        if evidence.gate_results:
            kinds.add("GATE")
        if evidence.review_findings:
            kinds.add("REVIEW")
        if evidence.failing_files or evidence.failing_lines or evidence.stack_trace:
            kinds.add("TEST")
        return kinds

    @staticmethod
    def _dedupe_preserve_order(values: list[str]) -> list[str]:
        return [item for item in dict.fromkeys(str(value).strip() for value in values) if item]

    def _merge_unique(self, *groups: list[str]) -> list[str]:
        merged: list[str] = []
        for group in groups:
            merged.extend(group)
        return self._dedupe_preserve_order(merged)

    @staticmethod
    def _project_pin_refs(
        refs: Any,
        *,
        query_name: str,
        query_subject: str,
    ) -> tuple[list[PinProjection], list[str]]:
        if not isinstance(refs, list):
            issue = f"INVALID_QUERY_PAYLOAD:{query_name}:{query_subject}:{type(refs).__name__}"
            return [], [issue]

        projected: list[PinProjection] = []
        issues: list[str] = []
        for idx, ref in enumerate(refs):
            pin_id = ""
            if isinstance(ref, dict):
                pin_id = str(ref.get("pin_id", "")).strip()
            else:
                pin_id = str(getattr(ref, "pin_id", "")).strip()

            if pin_id:
                projected.append(PinProjection(pin_id=pin_id))
                continue

            issues.append(f"MISSING_PIN_ID:{query_name}:{query_subject}:{idx}:{type(ref).__name__}")
        return projected, issues

    @staticmethod
    def _normalize_ticket_source(source: str, declared_kind: str | None) -> str:
        normalized = str(source or "").strip().upper()
        if normalized in {"ALGORITHMIC_GATE", "ARCH_GATE", "TEST_FAILURE", "LINEAGE", "REVIEW"}:
            return normalized
        if declared_kind:
            return _KIND_TO_SOURCE.get(declared_kind, "ALGORITHMIC_GATE")
        return "ALGORITHMIC_GATE"

    def _build_evidence_issue_batch(
        self,
        evidence: FailureEvidence,
        *,
        reason: str,
        issue_code: str,
        declared_kind: str | None,
    ) -> RoutingBatch:
        source = self._normalize_ticket_source(evidence.source, declared_kind)
        ticket = DemotionTicket(
            run_id=self._run_id,
            source=source,
            target_layer=self._active_layer,
            severity="BLOCKER",
            origin_layer=self._active_layer,
            hop_trace=[self._active_layer, self._active_layer],
            failing_files=list(evidence.failing_files),
            diagnosis=reason,
            evidence_refs=list(evidence.evidence_paths),
            questions=[issue_code],
        )
        self._augment_ticket_with_evidence(ticket, evidence, trace=None)
        routing = DemotionRouting(
            target_layer=self._active_layer,
            action="block",
            reason=reason,
            confidence=1.0,
            diagnostics=[issue_code],
        )
        return RoutingBatch(tickets=[ticket], routings=[routing])

    def _augment_ticket_with_evidence(
        self,
        ticket: DemotionTicket,
        evidence: FailureEvidence,
        *,
        trace: TraceResult | None,
        file_path: str | None = None,
    ) -> None:
        ticket.evidence_refs = self._merge_unique(ticket.evidence_refs, evidence.evidence_paths)

        if evidence.stack_trace:
            ticket.questions.append(f"STACK_TRACE:{evidence.stack_trace}")

        if evidence.failing_lines:
            ticket.questions.append(f"FAILING_LINES_COUNT:{len(evidence.failing_lines)}")
            for entry in evidence.failing_lines:
                if not isinstance(entry, dict):
                    ticket.questions.append(f"FAILING_LINE_UNPROJECTED:{type(entry).__name__}")
                    continue
                anchor = dict(entry)
                if file_path and not anchor.get("file"):
                    anchor["file"] = file_path
                ticket.symbol_span_anchors.append(anchor)

        if trace is None:
            ticket.questions = self._dedupe_preserve_order(ticket.questions)
            return

        ticket.failing_pins = self._merge_unique(ticket.failing_pins, trace.located_pins)
        ticket.failing_atoms = self._merge_unique(ticket.failing_atoms, trace.traced_atoms)
        for hop in trace.trace_path:
            ticket.questions.append(f"TRACE_PATH:{hop}")
        for degradation in trace.degradations:
            ticket.questions.append(f"TRACE_DEGRADED:{degradation}")
        ticket.questions = self._dedupe_preserve_order(ticket.questions)
