"""Core types and Planner API for the planning module.

Defines the public data types (PlanningContext, PlanningRequest,
PlanningResult) and the Planner class that serves as the single
auto-mode decision authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from spec_manager.planner.router import CapabilityRouter, LayerRouter

logger = logging.getLogger(__name__)
PLANNER_VERSION = "1"

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Layer = Literal["l1", "l2", "l3", "any"]
Capability = Literal[
    "RESOLVE_SIGNAL",  # interactive refinement + under-spec questions
    "GAP",  # gap understanding / clustering / prioritization
    "PLAN",  # plan synthesis (intentions / wiring / refactor)
    "UNDER_SPEC",  # resolve or block; produce constraints + routing + monitors
    "INTEGRATION_ANALYSIS",
    "TRIAGE_SIGNAL",  # reactive triage of coordination signals
]


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass
class PlanningContext:
    """Per-request context passed through all planner operations."""

    run_id: str = ""
    slice_id: str = ""
    iteration: int = 0
    layer: Layer = "any"
    mode: Literal["auto", "interactive"] = "auto"
    workspace_root: str = ""
    slice_root: str = ""
    bundle_ref: Any = None  # EvidenceBundle or lightweight view
    signal_ref: Any = None  # InputSignal or Ambiguity
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanningRequest:
    """A typed request dispatched to the planner."""

    capability: Capability
    context: PlanningContext
    inputs: dict[str, Any] = field(default_factory=dict)
    constraints_hint: dict[str, Any] | None = None


@dataclass
class PlanningResult:
    """Outcome of a planner invocation."""

    status: Literal["OK", "BLOCKED", "NEEDS_INPUT", "NOOP", "ERROR", "WAITING"]
    outputs: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class Planner:
    """Single auto-mode decision authority across the spec manager lifecycle.

    Routes each ``PlanningRequest`` to the appropriate layer planner
    (L1/L2/L3) via a ``LayerRouter``, then dispatches by capability
    through a ``CapabilityRouter``.  Every invocation is tagged with a
    trace id for observability.

    If *register_defaults* is True (the default), real L1/L2/L3 planners
    are registered automatically.  Pass False and call
    ``register_layer_planner`` manually for testing.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        mode: str = "auto",
        *,
        register_defaults: bool = True,
        research_tool: Any = None,
        integration_tool: Any = None,
        evidence_tool: Any = None,
        constraints_tool: Any = None,
        override_provider: Callable[[PlanningRequest], PlanningResult | None] | None = None,
        model_id: str = "",
        work_item_store: Any = None,
        wait_graph: Any = None,
        on_constraint_saved: Callable | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root)
        self._mode = mode
        self._model_id = model_id
        self._constraints_tool = constraints_tool
        self._layer_router = LayerRouter()
        self._capability_router = CapabilityRouter()
        self._override_provider = override_provider
        self._work_item_store = work_item_store
        self._wait_graph = wait_graph

        # Build a shared ConstraintStoreAdapter for L1/L2 planners
        from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter

        self._constraints_adapter = ConstraintStoreAdapter(
            self._workspace_root,
            on_constraint_saved=on_constraint_saved,
        )

        if register_defaults:
            self._register_default_planners(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
                constraints_tool=constraints_tool,
            )

    def _register_default_planners(
        self,
        research_tool: Any = None,
        integration_tool: Any = None,
        evidence_tool: Any = None,
        constraints_tool: Any = None,
    ) -> None:
        """Register real L1/L2/L3 planners with injected tools."""
        from spec_manager.planner.layers.l1 import L1Planner
        from spec_manager.planner.layers.l2 import L2Planner
        from spec_manager.planner.layers.l3 import L3Planner

        self._layer_router.register(
            "l1",
            L1Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
                constraints_tool=constraints_tool,
                constraints_store_adapter=self._constraints_adapter,
            ),
        )
        self._layer_router.register(
            "l2",
            L2Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
                constraints_tool=constraints_tool,
                constraints_store_adapter=self._constraints_adapter,
                work_item_store=self._work_item_store,
                wait_graph=self._wait_graph,
            ),
        )
        self._layer_router.register(
            "l3",
            L3Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
                constraints_tool=constraints_tool,
            ),
        )

    def register_layer_planner(self, layer: str, planner: Any) -> None:
        """Register a custom planner for a layer (useful for testing)."""
        self._layer_router.register(layer, planner)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def plan(self, req: PlanningRequest) -> PlanningResult:
        """Route *req* to the correct layer planner and capability handler.

        Returns a ``PlanningResult`` with a unique ``trace_id`` for
        every invocation regardless of outcome.  Every call persists a
        trace (including errors) and appends to ``index.jsonl``.
        """
        from spec_manager.planner.trace import (
            DecisionRecord,
            ModelCallRecord,
            PlannerTrace,
            ToolCallRecord,
            canonical_json,
            compute_decision_key,
            compute_input_hash,
            content_hash,
        )

        trace_id = _new_trace_id()
        layer = req.context.layer
        ctx = req.context

        decision_key = compute_decision_key(
            layer=str(layer),
            capability=req.capability,
            slice_id=ctx.slice_id,
            iteration=ctx.iteration,
            inputs=req.inputs,
        )
        input_hash = compute_input_hash(req.capability, req.inputs)

        trace = PlannerTrace.start(
            trace_id,
            _request_snapshot(
                req,
                input_hash=input_hash,
                decision_key=decision_key,
                model_id=self._model_id,
                planner_version=PLANNER_VERSION,
            ),
            decision_key=decision_key,
            run_id=ctx.run_id,
            model_id=self._model_id,
            planner_version=PLANNER_VERSION,
            layer=str(layer),
            capability=req.capability,
            slice_id=ctx.slice_id,
        )

        logger.debug(
            "planner.plan  trace=%s  key=%s  capability=%s  layer=%s  slice=%s",
            trace_id,
            decision_key,
            req.capability,
            layer,
            ctx.slice_id,
        )

        # Override hook (for counterfactual testing / ground truth injection)
        if self._override_provider is not None:
            override_result = self._override_provider(req)
            if override_result is not None:
                override_result.trace_id = trace_id
                trace.status = override_result.status
                trace.overridden = True
                trace.set_decision(
                    DecisionRecord(
                        decision_text=f"OVERRIDDEN: {override_result.status}",
                    )
                )
                trace.add_artifact("override_outputs", override_result.outputs)
                self._persist_trace(trace)
                return override_result

        try:
            planner = self._layer_router.select(layer)
            route_start = time.perf_counter()
            result = self._capability_router.route(planner, req)
            duration_ms = (time.perf_counter() - route_start) * 1000.0
            result.trace_id = trace_id
            trace.status = result.status
            trace.set_decision(
                DecisionRecord(
                    decision_text=result.status,
                )
            )
            trace.add_artifact("outputs", result.outputs)
            usage_tokens = _extract_tokens(result.outputs)
            trace.record_model_call(
                ModelCallRecord(
                    agent_name=f"{str(layer).lower()}:{req.capability}",
                    model=self._model_id,
                    duration_ms=duration_ms,
                    tokens_in=usage_tokens[0],
                    tokens_out=usage_tokens[1],
                    model_params={
                        "mode": self._mode,
                        "capability": req.capability,
                        "layer": str(layer),
                        "planner_version": PLANNER_VERSION,
                    },
                    prompt_text=canonical_json(req.inputs),
                    response_text=canonical_json(result.outputs),
                )
            )
            trace.record_tool_call(
                ToolCallRecord(
                    tool_name=f"planner.route.{str(req.capability).lower()}",
                    inputs_hash=content_hash(canonical_json(req.inputs)),
                    output_summary=result.status,
                    duration_ms=duration_ms,
                    tokens_in=usage_tokens[0],
                    tokens_out=usage_tokens[1],
                    tool_params={"layer": str(layer)},
                )
            )
            self._persist_trace(trace)
            return result
        except Exception as exc:
            logger.exception("planner.plan failed  trace=%s", trace_id)
            result = PlanningResult(
                status="ERROR",
                trace_id=trace_id,
                error=str(exc),
            )
            trace.status = "ERROR"
            trace.set_decision(
                DecisionRecord(
                    decision_text=f"ERROR: {exc}",
                )
            )
            self._persist_trace(trace)
            return result

    def _persist_trace(self, trace: Any) -> None:
        """Persist trace artifacts; failure is a hard planner error."""
        trace.persist(self._workspace_root)
        try:
            self._persist_planner_state(trace)
        except Exception:
            logger.debug("Failed to persist planner_state for %s", trace.trace_id, exc_info=True)

    def _persist_planner_state(self, trace: Any) -> None:
        """Persist a per-layer planner decision digest for attribution/debugging."""
        run_id = str(getattr(trace, "run_id", "") or "")
        layer = str(getattr(trace, "layer", "") or "")
        slice_id = str(getattr(trace, "slice_id", "") or "")
        if not run_id or not layer or not slice_id:
            return
        if layer not in {"l1", "l2", "l3"}:
            return

        state_dir = self._workspace_root / "analysis" / "planner_state" / run_id / layer
        state_dir.mkdir(parents=True, exist_ok=True)

        outputs = {}
        artifacts = getattr(trace, "artifacts", {}) or {}
        override_outputs = artifacts.get("override_outputs")
        if isinstance(override_outputs, dict):
            outputs = override_outputs
        else:
            regular_outputs = artifacts.get("outputs")
            if isinstance(regular_outputs, dict):
                outputs = regular_outputs

        decision_text = ""
        decision = getattr(trace, "decision", None)
        if decision is not None:
            decision_text = str(getattr(decision, "decision_text", "") or "")

        payload = {
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "run_id": run_id,
            "layer": layer,
            "slice_id": slice_id,
            "trace_id": str(getattr(trace, "trace_id", "") or ""),
            "decision_key": str(getattr(trace, "decision_key", "") or ""),
            "capability": str(getattr(trace, "capability", "") or ""),
            "status": str(getattr(trace, "status", "") or ""),
            "decision_text": decision_text,
            "overridden": bool(getattr(trace, "overridden", False)),
            "outputs": outputs,
        }
        safe_slice_id = slice_id.replace("/", "__").replace("\\", "__")
        out_path = state_dir / f"{safe_slice_id}.json"
        out_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Convenience adapters for existing call sites
    # ------------------------------------------------------------------

    def resolve_signal(self, signal: Any, context: PlanningContext) -> Any:
        """Resolve an ambiguity signal.

        Returns the layer planner's response (typically a dict or None).
        """
        context.signal_ref = signal
        req = PlanningRequest(
            capability="RESOLVE_SIGNAL",
            context=context,
            inputs={"signal": signal},
        )
        result = self.plan(req)
        return result.outputs.get("response")

    def plan_from_gaps(
        self, context: PlanningContext, gaps: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Generate plan intentions from a gap list.

        Returns a list of intention dicts (may be empty on NOOP).
        """
        req = PlanningRequest(
            capability="PLAN",
            context=context,
            inputs={"gaps": gaps},
        )
        result = self.plan(req)
        return result.outputs.get("intentions", [])

    def resolve_under_spec(
        self, context: PlanningContext, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Resolve or block under-spec events.

        Returns an explicit contract with:
        ``blocked``, ``constraints``, ``questions``, ``resolved``,
        ``routing`` (work items), ``monitors``, and ``expansions``.
        """
        req = PlanningRequest(
            capability="UNDER_SPEC",
            context=context,
            inputs={"events": events},
        )
        result = self.plan(req)
        outputs = result.outputs if isinstance(result.outputs, dict) else {}
        return self._normalize_under_spec_outputs(
            context=context,
            events=events,
            outputs=outputs,
            status=result.status,
        )

    def _normalize_under_spec_outputs(
        self,
        *,
        context: PlanningContext,
        events: list[dict[str, Any]],
        outputs: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        blocked = bool(outputs.get("blocked", False) or status == "BLOCKED")
        constraints_raw = outputs.get("constraints", {})
        constraints = constraints_raw if isinstance(constraints_raw, dict) else {}
        questions_raw = outputs.get("questions", [])
        questions = (
            [str(q).strip() for q in questions_raw if str(q).strip()]
            if isinstance(questions_raw, list)
            else []
        )
        resolved_raw = outputs.get("resolved", [])
        resolved = (
            [row for row in resolved_raw if isinstance(row, dict)]
            if isinstance(resolved_raw, list)
            else []
        )
        routing_raw = outputs.get("routing", [])
        routing = (
            [row for row in routing_raw if isinstance(row, dict)]
            if isinstance(routing_raw, list)
            else []
        )
        monitors_raw = outputs.get("monitors", [])
        monitors = (
            [row for row in monitors_raw if isinstance(row, dict)]
            if isinstance(monitors_raw, list)
            else []
        )

        expansions: list[dict[str, Any]] = []
        expansions_raw = outputs.get("expansions", [])
        if isinstance(expansions_raw, list):
            expansions.extend(row for row in expansions_raw if isinstance(row, dict))
        single_expansion = outputs.get("expansion")
        if isinstance(single_expansion, dict):
            expansions.append(single_expansion)

        # When UNDER_SPEC remains blocked with no routable payload, synthesize
        # spec expansion work-items via TRIAGE_SIGNAL so callers can route
        # provider work and register monitors explicitly.
        if blocked and not routing and events:
            triage_payload = self._expand_under_spec_via_triage(context=context, events=events)
            routing.extend(triage_payload["routing"])
            monitors.extend(triage_payload["monitors"])
            expansions.extend(triage_payload["expansions"])

        contradictions_raw = outputs.get("contradictions", [])
        contradictions = (
            [str(item) for item in contradictions_raw if str(item).strip()]
            if isinstance(contradictions_raw, list)
            else []
        )

        confidence_raw = outputs.get("confidence", outputs.get("score", 0.0))
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0

        return {
            "blocked": blocked,
            "constraints": constraints,
            "questions": questions,
            "resolved": resolved,
            "routing": routing,
            "monitors": monitors,
            "expansions": expansions,
            "confidence": max(0.0, min(1.0, confidence)),
            "contradictions": contradictions,
        }

    def _expand_under_spec_via_triage(
        self,
        *,
        context: PlanningContext,
        events: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        routing: list[dict[str, Any]] = []
        monitors: list[dict[str, Any]] = []
        expansions: list[dict[str, Any]] = []

        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue

            signal = self._synthesize_under_spec_signal(
                context=context,
                event=event,
                event_index=index,
            )
            triage_ctx = PlanningContext(
                run_id=context.run_id,
                slice_id=context.slice_id,
                iteration=context.iteration,
                layer="l1",
                mode=context.mode,
                workspace_root=context.workspace_root,
                slice_root=context.slice_root,
                bundle_ref=context.bundle_ref,
                signal_ref=signal,
                metadata={"source": "UNDER_SPEC_EXPANSION"},
            )

            triage_result = self.triage_signal(triage_ctx, signal)
            triage_outputs = (
                triage_result.outputs
                if hasattr(triage_result, "outputs") and isinstance(triage_result.outputs, dict)
                else {}
            )
            triage_routing = triage_outputs.get("routing", [])
            triage_monitors = triage_outputs.get("monitors", [])
            confidence_raw = triage_outputs.get("confidence", 0.0)
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.0
            proposal_models_raw = triage_outputs.get("proposal_models", [])
            proposal_models = (
                [str(model) for model in proposal_models_raw if str(model).strip()]
                if isinstance(proposal_models_raw, list)
                else []
            )

            triage_routing_dicts = (
                [row for row in triage_routing if isinstance(row, dict)]
                if isinstance(triage_routing, list)
                else []
            )
            triage_monitor_dicts = (
                [row for row in triage_monitors if isinstance(row, dict)]
                if isinstance(triage_monitors, list)
                else []
            )

            consistency_passed = self._consistency_check(
                signal=signal,
                routing_payloads=triage_routing_dicts,
            )
            contradictions_raw = triage_outputs.get("contradictions", [])
            contradictions = (
                [str(item) for item in contradictions_raw if str(item).strip()]
                if isinstance(contradictions_raw, list)
                else []
            )

            for payload in triage_routing_dicts:
                metadata = payload.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata = dict(metadata)
                metadata["event_id"] = str(event.get("event_id", "")).strip()
                metadata["signal_id"] = signal["signal_id"]
                metadata["spec_refs"] = list(signal["spec_refs"])
                metadata["provenance"] = (
                    f"Expansion created to resolve signal_id {signal['signal_id']}."
                )
                metadata["confidence"] = confidence
                metadata["proposal_models"] = proposal_models
                metadata["consistency_passed"] = consistency_passed
                payload["metadata"] = metadata
                routing.append(payload)

            for payload in triage_monitor_dicts:
                payload = dict(payload)
                payload.setdefault("signal_id", signal["signal_id"])
                monitors.append(payload)

            expansions.append(
                {
                    "event_id": str(event.get("event_id", "")).strip(),
                    "signal_id": signal["signal_id"],
                    "action": str(triage_outputs.get("action", "NOOP")).strip().upper() or "NOOP",
                    "confidence": max(0.0, min(1.0, confidence)),
                    "proposal_models": proposal_models,
                    "consistency_passed": consistency_passed,
                    "contradictions": contradictions,
                    "spec_refs": list(signal["spec_refs"]),
                    "routing": triage_routing_dicts,
                    "monitors": triage_monitor_dicts,
                    "why": str(triage_outputs.get("why", "")).strip(),
                    "missing_detail": str(triage_outputs.get("missing_detail", "")).strip(),
                }
            )

        return {
            "routing": routing,
            "monitors": monitors,
            "expansions": expansions,
        }

    @staticmethod
    def _synthesize_under_spec_signal(
        *,
        context: PlanningContext,
        event: dict[str, Any],
        event_index: int,
    ) -> dict[str, Any]:
        question = str(event.get("question", "")).strip() or "Under-specification detected"
        raw_event_id = str(event.get("event_id", "")).strip()
        event_id = raw_event_id or hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]
        source_line_raw = event.get("source_line", 0)
        try:
            source_line = int(source_line_raw or 0)
        except (TypeError, ValueError):
            source_line = 0

        ctx_payload = event.get("context", {})
        artifact_key = ""
        if isinstance(ctx_payload, dict):
            artifact_key = str(
                ctx_payload.get("needed_for")
                or ctx_payload.get("artifact_key")
                or ctx_payload.get("context")
                or ""
            ).strip()
        if not artifact_key:
            artifact_key = str(event.get("needed_for", "")).strip()
        if not artifact_key:
            artifact_key = str(event.get("source_file", event.get("file", ""))).strip()
        signal_id = f"{context.slice_id}:{context.iteration}:{event_id}:{event_index}"
        spec_refs = Planner._extract_spec_refs_from_event(
            event=event,
            question=question,
            source_line=source_line,
        )

        return {
            "signal_version": 1,
            "signal_id": signal_id,
            "run_id": context.run_id,
            "layer": context.layer,
            "slice_id": context.slice_id,
            "iteration": context.iteration,
            "status": "HALT",
            "classification": "AMBIGUOUS_SPEC",
            "need": {
                "summary": question,
                "artifact_key": artifact_key,
            },
            "spec_refs": spec_refs,
            "search_hints": {
                "keywords": [token for token in re.split(r"[^a-zA-Z0-9]+", artifact_key) if token],
                "possible_owner_slices": [],
            },
            "payload": {"under_spec_event": event},
        }

    @staticmethod
    def _extract_spec_refs_from_event(
        *,
        event: dict[str, Any],
        question: str,
        source_line: int,
    ) -> list[dict[str, Any]]:
        context_payload = event.get("context", {})
        if isinstance(context_payload, dict):
            refs = context_payload.get("spec_refs", [])
            if isinstance(refs, list):
                normalized: list[dict[str, Any]] = []
                for raw in refs:
                    if not isinstance(raw, dict):
                        continue
                    text = str(raw.get("spec_text", "")).strip()
                    source_file = str(raw.get("source_file", "")).strip()
                    source_symbol = str(raw.get("source_symbol", "")).strip()
                    line_hint_raw = raw.get("source_line_hint", source_line)
                    try:
                        line_hint = int(line_hint_raw or 0)
                    except (TypeError, ValueError):
                        line_hint = 0
                    if not (text or source_file):
                        continue
                    normalized.append(
                        {
                            "spec_text": text or question,
                            "source_file": source_file,
                            "source_symbol": source_symbol,
                            "source_line_hint": line_hint,
                        }
                    )
                if normalized:
                    return normalized

        return [
            {
                "spec_text": question,
                "source_file": str(event.get("source_file", event.get("file", ""))).strip(),
                "source_symbol": "",
                "source_line_hint": source_line,
            }
        ]

    @staticmethod
    def _consistency_check(
        *,
        signal: dict[str, Any],
        routing_payloads: list[dict[str, Any]],
    ) -> bool:
        spec_text = " ".join(
            str(ref.get("spec_text", "")).strip().lower()
            for ref in signal.get("spec_refs", [])
            if isinstance(ref, dict)
        ).strip()
        routed_text = " ".join(
            str(payload.get("spec_text", "")).strip().lower() for payload in routing_payloads
        ).strip()
        if not spec_text or not routed_text:
            return False
        spec_tokens = {t for t in re.split(r"[^a-z0-9]+", spec_text) if t}
        routed_tokens = {t for t in re.split(r"[^a-z0-9]+", routed_text) if t}
        if not spec_tokens or not routed_tokens:
            return False
        return len(spec_tokens & routed_tokens) > 0

    def triage_signal(
        self,
        context: PlanningContext,
        signal: dict[str, Any],
    ) -> PlanningResult:
        """Triage a coordination signal from a halted agent.

        The planner searches work items, classifies the need, and returns
        routing decisions + monitor specs.
        """
        req = PlanningRequest(
            capability="TRIAGE_SIGNAL",
            context=context,
            inputs={"signal": signal},
        )
        return self.plan(req)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_trace_id() -> str:
    """Return a short unique trace identifier."""
    return uuid.uuid4().hex[:12]


def _request_snapshot(
    req: PlanningRequest,
    *,
    input_hash: str = "",
    decision_key: str = "",
    model_id: str = "",
    planner_version: str = "",
) -> dict[str, Any]:
    """Build a JSON-safe snapshot of the request for trace storage."""
    ctx = req.context
    return {
        "capability": req.capability,
        "layer": ctx.layer,
        "run_id": ctx.run_id,
        "slice_id": ctx.slice_id,
        "iteration": ctx.iteration,
        "mode": ctx.mode,
        "workspace_root": ctx.workspace_root,
        "slice_root": ctx.slice_root,
        "metadata": _safe_deepcopy(ctx.metadata),
        "inputs": _safe_deepcopy(req.inputs),
        "inputs_keys": sorted(req.inputs.keys()),
        "input_hash": input_hash,
        "decision_key": decision_key,
        "model_id": model_id,
        "planner_version": planner_version,
        "constraints_hint": _safe_deepcopy(req.constraints_hint),
        "has_constraints_hint": req.constraints_hint is not None,
    }


def _safe_deepcopy(value: Any) -> Any:
    """Best-effort deep copy for trace snapshots."""
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _extract_tokens(outputs: dict[str, Any]) -> tuple[int, int]:
    """Best-effort extraction of token usage metadata from planner outputs."""
    if not isinstance(outputs, dict):
        return 0, 0
    usage = outputs.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    raw_in = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    raw_out = usage.get("output_tokens", usage.get("completion_tokens", 0))
    try:
        tokens_in = int(raw_in or 0)
    except (TypeError, ValueError):
        tokens_in = 0
    try:
        tokens_out = int(raw_out or 0)
    except (TypeError, ValueError):
        tokens_out = 0
    return max(tokens_in, 0), max(tokens_out, 0)
