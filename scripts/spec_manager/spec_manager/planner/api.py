"""Core types and Planner API for the planning module.

Defines the public data types (PlanningContext, PlanningRequest,
PlanningResult) and the Planner class that serves as the single
auto-mode decision authority.
"""

from __future__ import annotations

import copy
import json
import logging
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
    "UNDER_SPEC",  # resolve or block; produce constraints or questions
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

        Returns a dict with ``blocked`` (bool) and ``constraints`` keys.
        """
        req = PlanningRequest(
            capability="UNDER_SPEC",
            context=context,
            inputs={"events": events},
        )
        result = self.plan(req)
        return result.outputs

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
