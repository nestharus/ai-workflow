"""Core types and planner API for the planning module.

Defines the public data types (PlanningContext, PlanningRequest,
PlanningResult) and the GeneralPlanner class that serves as the single
auto-mode decision authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from spec_manager.planner.jit.actions import ActionType
from spec_manager.planner.jit.state_machine import PlannerStateMachine, PlanPhase, PlanStatus
from spec_manager.planner.router import (
    CapabilityRouter,
    LayerRouter,
    ModelRouteDecision,
    ModelRouter,
    ReviewPack,
)
from spec_manager.planner.tools.constraints_tool import ConstraintsTool
from spec_manager.planner.trace import ReplayBundle

logger = logging.getLogger(__name__)
PLANNER_VERSION = "1"
_VALID_INGEST_TAXONOMY = frozenset({"INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION"})
_VALID_UNDER_SPEC_DIMENSIONS = frozenset(
    {"software", "legal", "economic", "organizational", "temporal", "operational"}
)
_VALID_UNDER_SPEC_DECISION_TYPES = frozenset(
    {"dependency", "infrastructure", "data_policy", "security", "performance", "architecture"}
)

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
    "INGEST_USER_ANSWER",  # planner-mediated answer ingestion
]


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass
class PlanningContext:
    """Per-request context passed through all planner operations."""

    run_id: str | None = None
    slice_id: str | None = None
    iteration: int | None = None
    layer: Layer = "any"
    mode: Literal["auto", "interactive"] = "auto"
    workspace_root: str = ""
    slice_root: str | None = None
    bundle_ref: Any = field(default_factory=dict)  # EvidenceBundle authority for PLAN inputs
    signal_ref: Any | None = None  # InputSignal or Ambiguity
    metadata: dict[str, Any] | None = None


@dataclass
class PlanningRequest:
    """A typed request dispatched to the planner."""

    capability: Capability
    context: PlanningContext
    inputs: dict[str, Any]
    constraints_hint: dict[str, Any] | None = None


@dataclass
class PlanningResult:
    """Outcome of a planner invocation."""

    status: Literal["OK", "BLOCKED", "NEEDS_INPUT", "NOOP", "ERROR", "WAITING"]
    outputs: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    error: str = ""


@dataclass
class PromotionLoopAdapters:
    """Adapter hooks used by PromotionLoop to coordinate planner execution gates."""

    before_step: Callable[[str, PlanningRequest, dict[str, Any]], None] | None = None
    after_step: Callable[[str, PlanningRequest, PlanningResult, dict[str, Any]], None] | None = None
    on_bundle_update: Callable[[PlanningRequest, dict[str, Any]], dict[str, Any] | None] | None = (
        None
    )


# ---------------------------------------------------------------------------
# General Planner
# ---------------------------------------------------------------------------


class GeneralPlanner:
    """Single auto-mode decision authority across the spec manager lifecycle.

    Routes each ``PlanningRequest`` to the appropriate layer planner
    (L1/L2/L3) via a ``LayerRouter`` and resolves model selection using
    ``ModelRouter``. Capability dispatch is expressed as ``NextAction``
    sequences and executed against planner adapters. Every invocation is
    tagged with a trace id for observability.

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
        constraints_tool: Any = None,
        override_provider: Callable[[PlanningRequest], PlanningResult | None] | None = None,
        model_id: str = "",
        work_item_store: Any = None,
        wait_graph: Any = None,
        on_constraint_saved: Callable | None = None,
        on_decision_recorded: Callable[[dict[str, Any]], None] | None = None,
        promotion_adapters: PromotionLoopAdapters | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root)
        self._mode = mode
        self._default_model_id = str(model_id).strip()
        self._model_id = self._default_model_id
        self._layer_router = LayerRouter()
        self._model_router = ModelRouter(default_model_id=self._default_model_id)
        self._capability_router = CapabilityRouter(integration_tool=integration_tool)
        self._override_provider = override_provider
        self._work_item_store = work_item_store
        self._wait_graph = wait_graph
        self._on_decision_recorded = on_decision_recorded
        self._promotion_adapters = (
            promotion_adapters if promotion_adapters is not None else PromotionLoopAdapters()
        )
        if constraints_tool is None:
            constraints_tool = ConstraintsTool(
                workspace_root=self._workspace_root,
                on_constraint_saved=on_constraint_saved,
            )
        self._constraints_tool = constraints_tool
        if hasattr(constraints_tool, "load_merged") and hasattr(constraints_tool, "save_facts"):
            self._constraints_store_tool = constraints_tool
        else:
            self._constraints_store_tool = ConstraintsTool(
                workspace_root=self._workspace_root,
                on_constraint_saved=on_constraint_saved,
            )

        if register_defaults:
            self._register_default_planners(
                research_tool=research_tool,
                integration_tool=integration_tool,
                constraints_tool=self._constraints_tool,
            )

    def _register_default_planners(
        self,
        research_tool: Any = None,
        integration_tool: Any = None,
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
                constraints_tool=constraints_tool,
                constraints_store_adapter=self._constraints_store_tool,
            ),
        )
        self._layer_router.register(
            "l2",
            L2Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                constraints_tool=constraints_tool,
                constraints_store_adapter=self._constraints_store_tool,
                work_item_store=self._work_item_store,
                wait_graph=self._wait_graph,
            ),
        )
        self._layer_router.register(
            "l3",
            L3Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
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
            PlannerTrace,
            compute_decision_key,
            compute_input_hash,
        )

        trace_id = _new_trace_id()
        layer = req.context.layer
        ctx = req.context
        run_id = str(ctx.run_id or "").strip()
        slice_id = str(ctx.slice_id or "").strip()
        iteration_raw = ctx.iteration
        try:
            iteration = int(iteration_raw) if iteration_raw is not None else 0
        except (TypeError, ValueError):
            iteration = 0
        proposal_models = self._extract_proposal_models(req)
        requires_external_facts = self._requires_external_facts(req)
        high_risk = self._is_high_risk_request(req)
        resolved_route = self._model_router.resolve(
            req,
            prefer_models=proposal_models,
            requires_external_facts=requires_external_facts,
            high_risk=high_risk,
        )
        selected_model = resolved_route.primary_model or self._default_model_id
        if selected_model:
            self._model_id = selected_model

        decision_key = compute_decision_key(
            layer=str(layer),
            capability=req.capability,
            slice_id=slice_id,
            iteration=iteration,
            inputs=req.inputs,
        )
        input_hash = compute_input_hash(req.capability, req.inputs)

        trace = PlannerTrace.start(
            trace_id,
            _request_snapshot(
                req,
                input_hash=input_hash,
                decision_key=decision_key,
                model_id=selected_model,
                planner_version=PLANNER_VERSION,
                model_route=resolved_route.to_dict(),
            ),
            decision_key=decision_key,
            run_id=run_id,
            model_id=selected_model,
            planner_version=PLANNER_VERSION,
            layer=str(layer),
            capability=req.capability,
            slice_id=slice_id,
        )
        state_machine = self._load_state_machine(req)
        executed_actions: list[dict[str, Any]] = []

        logger.debug(
            "planner.plan  trace=%s  key=%s  capability=%s  layer=%s  slice=%s",
            trace_id,
            decision_key,
            req.capability,
            layer,
            slice_id,
        )

        context_token = ConstraintsTool.push_planner_update_context(
            run_id=run_id,
            layer=str(layer),
            capability=req.capability,
        )
        self._capability_router.bind_trace(trace)
        try:
            # Override hook (for counterfactual testing / ground truth injection)
            if self._override_provider is not None:
                override_result = self._override_provider(req)
                if override_result is not None:
                    override_result.trace_id = trace_id
                    trace.status = override_result.status
                    trace.overridden = True
                    decision_record = self._build_decision_record(
                        req=req,
                        result=override_result,
                        model_route=resolved_route,
                        dispatch_gates={},
                        requires_external_facts=requires_external_facts,
                        high_risk=high_risk,
                        overridden=True,
                    )
                    trace.set_decision(decision_record)
                    trace.set_result(self._result_snapshot(override_result, decision_record))
                    trace.add_artifact("override_outputs", override_result.outputs)
                    self._record_canonical_artifacts(trace=trace, result=override_result)
                    replay_bundle = self._build_replay_bundle(
                        trace_id=trace_id,
                        decision_key=decision_key,
                        req=req,
                        selected_model=selected_model,
                        model_route=resolved_route,
                        state_machine=state_machine,
                        executed_actions=[],
                        result=override_result,
                        trace=trace,
                    )
                    trace.add_artifact("replay_bundle", replay_bundle.to_dict())
                    trace.set_replay_payload(
                        self._build_replay_payload(
                            trace=trace,
                            replay_bundle=replay_bundle,
                        )
                    )
                    self._persist_trace(trace)
                    self._emit_decision_recorded_event(
                        trace=trace,
                        context=ctx,
                        capability=req.capability,
                        decision_key=decision_key,
                        outputs=override_result.outputs,
                    )
                    return override_result

            dispatch_gates: dict[str, Any] = {}
            effective_route = resolved_route
            if req.capability == "INGEST_USER_ANSWER":
                result = self._handle_ingest_user_answer(req)
                state_machine.complete()
            else:
                planner = self._layer_router.select(layer)
                planner.bind_trace(trace)
                result, effective_route, dispatch_gates, executed_actions = (
                    self._route_request_with_gates(
                        planner=planner,
                        req=req,
                        initial_route=resolved_route,
                        state_machine=state_machine,
                    )
                )
            result.trace_id = trace_id
            trace.status = result.status
            selected_model = effective_route.primary_model or selected_model
            if selected_model:
                self._model_id = selected_model
                trace.model_id = selected_model
            self._annotate_result_dispatch_metadata(
                result,
                model_route=effective_route,
                dispatch_gates=dispatch_gates,
                planner_state=state_machine.to_dict(),
                next_actions=executed_actions,
            )
            self._persist_state_machine(req, state_machine)
            decision_record = self._build_decision_record(
                req=req,
                result=result,
                model_route=effective_route,
                dispatch_gates=dispatch_gates,
                requires_external_facts=requires_external_facts,
                high_risk=high_risk,
            )
            trace.set_decision(decision_record)
            trace.set_result(self._result_snapshot(result, decision_record))
            trace.add_artifact("outputs", result.outputs)
            trace.add_artifact("model_route", effective_route.to_dict())
            trace.add_artifact("planner_state", state_machine.to_dict())
            if executed_actions:
                trace.add_artifact("next_actions", executed_actions)
            if dispatch_gates:
                trace.add_artifact("dispatch_gates", dispatch_gates)
            self._record_canonical_artifacts(trace=trace, result=result)
            replay_bundle = self._build_replay_bundle(
                trace_id=trace_id,
                decision_key=decision_key,
                req=req,
                selected_model=selected_model,
                model_route=effective_route,
                state_machine=state_machine,
                executed_actions=executed_actions,
                result=result,
                trace=trace,
            )
            trace.add_artifact("replay_bundle", replay_bundle.to_dict())
            trace.set_replay_payload(
                self._build_replay_payload(
                    trace=trace,
                    replay_bundle=replay_bundle,
                )
            )
            self._persist_trace(trace)
            self._emit_decision_recorded_event(
                trace=trace,
                context=ctx,
                capability=req.capability,
                decision_key=decision_key,
                outputs=result.outputs,
            )
            return result
        except Exception as exc:
            logger.exception("planner.plan failed  trace=%s", trace_id)
            result = PlanningResult(
                status="ERROR",
                trace_id=trace_id,
                error=str(exc),
            )
            trace.status = "ERROR"
            decision_record = self._build_decision_record(
                req=req,
                result=result,
                model_route=resolved_route,
                dispatch_gates={},
                requires_external_facts=requires_external_facts,
                high_risk=high_risk,
                error_text=str(exc),
            )
            trace.set_decision(decision_record)
            trace.set_result(self._result_snapshot(result, decision_record))
            trace.add_artifact("outputs", result.outputs)
            replay_bundle = self._build_replay_bundle(
                trace_id=trace_id,
                decision_key=decision_key,
                req=req,
                selected_model=selected_model,
                model_route=resolved_route,
                state_machine=state_machine,
                executed_actions=executed_actions,
                result=result,
                trace=trace,
            )
            trace.add_artifact("replay_bundle", replay_bundle.to_dict())
            trace.set_replay_payload(
                self._build_replay_payload(
                    trace=trace,
                    replay_bundle=replay_bundle,
                )
            )
            self._persist_trace(trace)
            self._emit_decision_recorded_event(
                trace=trace,
                context=ctx,
                capability=req.capability,
                decision_key=decision_key,
                outputs={},
            )
            return result
        finally:
            if req.capability != "INGEST_USER_ANSWER":
                try:
                    self._layer_router.select(layer).bind_trace(None)
                except Exception:
                    logger.debug("Failed to clear layer trace binding", exc_info=True)
            self._capability_router.bind_trace(None)
            ConstraintsTool.pop_planner_update_context(context_token)

    def _route_request_with_gates(
        self,
        *,
        planner: Any,
        req: PlanningRequest,
        initial_route: ModelRouteDecision,
        state_machine: PlannerStateMachine,
    ) -> tuple[PlanningResult, ModelRouteDecision, dict[str, Any], list[dict[str, Any]]]:
        """Apply dispatch gates before routing to capability execution."""
        gates: dict[str, Any] = {
            "deterministic_local_checked": True,
            "integration_analysis_checked": False,
            "external_research_required": self._requires_external_facts(req),
            "critique_checked": False,
            "path": "capability_dispatch",
        }
        executed_actions: list[dict[str, Any]] = []
        deterministic_result = self._try_deterministic_local_resolution(req)
        if deterministic_result is not None:
            gates["path"] = "deterministic_local"
            state_machine.complete()
            executed_actions.append(
                {
                    "action": ActionType.COMPLETE.value,
                    "agent": "",
                    "tool": "deterministic_local",
                    "inputs": {},
                    "prompt": "",
                }
            )
            return deterministic_result, initial_route, gates, executed_actions

        routed_req = req
        if self._should_run_integration_gate(req):
            gates["integration_analysis_checked"] = True
            self._notify_gate_hook("before_step", "integration_gate", req, gates)
            integration_req = PlanningRequest(
                capability="INTEGRATION_ANALYSIS",
                context=req.context,
                inputs=dict(req.inputs) if isinstance(req.inputs, dict) else {},
                constraints_hint=req.constraints_hint,
            )
            integration_route = self._model_router.resolve(
                integration_req,
                requires_external_facts=False,
                high_risk=False,
            )
            integration_result, integration_actions = self._execute_next_actions(
                planner,
                integration_req,
                model_route=integration_route,
                state_machine=state_machine,
                terminal=False,
            )
            executed_actions.extend(integration_actions)
            gates["integration_analysis_status"] = integration_result.status
            if isinstance(integration_result.outputs, dict):
                merged_inputs = dict(req.inputs) if isinstance(req.inputs, dict) else {}
                merged_inputs.setdefault("integration_analysis", integration_result.outputs)
                if self._promotion_adapters.on_bundle_update is not None:
                    try:
                        bundle_updates = self._promotion_adapters.on_bundle_update(
                            req,
                            integration_result.outputs,
                        )
                    except Exception:
                        logger.warning("promotion on_bundle_update hook failed", exc_info=True)
                        bundle_updates = None
                    if isinstance(bundle_updates, dict):
                        merged_inputs.update(bundle_updates)
                routed_req = PlanningRequest(
                    capability=req.capability,
                    context=req.context,
                    inputs=merged_inputs,
                    constraints_hint=req.constraints_hint,
                )
            self._notify_gate_hook(
                "after_step", "integration_gate", integration_req, gates, integration_result
            )

        effective_route = self._model_router.resolve(
            routed_req,
            prefer_models=self._extract_proposal_models(routed_req),
            requires_external_facts=self._requires_external_facts(routed_req),
            high_risk=self._is_high_risk_request(routed_req),
        )
        result, primary_actions = self._execute_next_actions(
            planner,
            routed_req,
            model_route=effective_route,
            state_machine=state_machine,
        )
        executed_actions.extend(primary_actions)

        review_pack = self._build_review_pack(routed_req, effective_route)
        if review_pack is not None:
            gates["critique_checked"] = True
            self._notify_gate_hook("before_step", "review_pack", routed_req, gates)
            review_summary, review_actions = self._execute_review_pack(
                planner=planner,
                req=routed_req,
                review_pack=review_pack,
                state_machine=state_machine,
            )
            executed_actions.extend(review_actions)
            gates["critique_status"] = str(review_summary.get("status", "")).strip()
            gates["critique_model"] = str(review_summary.get("primary_model", "")).strip()
            if isinstance(result.outputs, dict):
                result.outputs["review_pack"] = review_summary
                primary_review = review_summary.get("primary_review")
                if isinstance(primary_review, dict):
                    result.outputs["critique"] = primary_review
            self._notify_gate_hook("after_step", "review_pack", routed_req, gates, result)

        return result, effective_route, gates, executed_actions

    def _execute_next_actions(
        self,
        planner: Any,
        req: PlanningRequest,
        *,
        model_route: ModelRouteDecision,
        state_machine: PlannerStateMachine,
        terminal: bool = True,
    ) -> tuple[PlanningResult, list[dict[str, Any]]]:
        self._model_router.bind_context(req, model_route)
        actions = self._capability_router.plan_actions(
            req,
            requires_external_facts=self._requires_external_facts(req),
        )
        interim: dict[str, Any] = {}
        executed_actions: list[dict[str, Any]] = []
        for action in actions:
            action_dict = action.to_dict()
            executed_actions.append(action_dict)
            self._advance_state_from_action(state_machine, action)

            if action.action == ActionType.RUN_TOOL:
                self._capability_router.run_tool(
                    planner=planner,
                    req=req,
                    tool_name=action.tool,
                    action_inputs=action.inputs if isinstance(action.inputs, dict) else None,
                    interim=interim,
                )
                continue

            if action.action == ActionType.CALL_AGENT:
                self._capability_router.run_agent(
                    planner=planner,
                    req=req,
                    agent_name=action.agent,
                    action_inputs=action.inputs if isinstance(action.inputs, dict) else None,
                    interim=interim,
                )
                continue

            if action.action == ActionType.USER_INPUT:
                if self._should_pause_for_user_input(req=req, interim=interim):
                    prompt = self._resolve_wait_prompt(interim, fallback=action.prompt)
                    state_machine.wait_for_input(prompt)
                    outputs = self._build_needs_input_outputs(
                        req=req,
                        interim=interim,
                        prompt=prompt,
                        planner_state=state_machine.to_dict(),
                    )
                    return PlanningResult(status="NEEDS_INPUT", outputs=outputs), executed_actions
                continue

            if action.action == ActionType.COMPLETE:
                if terminal and state_machine.status != PlanStatus.COMPLETED:
                    state_machine.complete()
                return self._capability_router.finalize(req, interim), executed_actions

            if action.action == ActionType.ERROR:
                state_machine.error(action.prompt)
                return PlanningResult(status="ERROR", error=action.prompt), executed_actions

        finalized = self._capability_router.finalize(req, interim)
        if finalized.status == "NEEDS_INPUT":
            state_machine.wait_for_input()
        elif (
            terminal
            and finalized.status != "ERROR"
            and state_machine.status != PlanStatus.COMPLETED
        ):
            state_machine.complete()
        return finalized, executed_actions

    def _execute_review_pack(
        self,
        *,
        planner: Any,
        req: PlanningRequest,
        review_pack: ReviewPack,
        state_machine: PlannerStateMachine,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        reviews: list[dict[str, Any]] = []
        executed_actions: list[dict[str, Any]] = []
        for index, reviewer in enumerate(review_pack.agents, start=1):
            capability = str(reviewer.get("capability", "INTEGRATION_ANALYSIS")).strip().upper()
            critique_req = PlanningRequest(
                capability=capability,  # type: ignore[arg-type]
                context=req.context,
                inputs=dict(req.inputs) if isinstance(req.inputs, dict) else {},
                constraints_hint=req.constraints_hint,
            )
            preferred_model = str(reviewer.get("model", "")).strip()
            critique_route = self._model_router.resolve(
                critique_req,
                prefer_models=[preferred_model] if preferred_model else None,
                requires_external_facts=False,
                high_risk=False,
            )
            critique_result, critique_actions = self._execute_next_actions(
                planner,
                critique_req,
                model_route=critique_route,
                state_machine=state_machine,
                terminal=False,
            )
            executed_actions.extend(critique_actions)
            reviews.append(
                {
                    "reviewer": str(reviewer.get("name", f"reviewer_{index}")).strip()
                    or f"reviewer_{index}",
                    "status": critique_result.status,
                    "model": critique_route.primary_model,
                    "work_type": critique_route.work_type,
                    "summary": self._build_critique_summary(
                        critique_result=critique_result,
                        critique_route=critique_route,
                    ),
                    "outputs": critique_result.outputs
                    if isinstance(critique_result.outputs, dict)
                    else {},
                }
            )

        accepted = self._review_pack_passes(
            acceptance_checks=review_pack.acceptance_checks,
            reviews=reviews,
        )
        if any(str(review.get("status", "")).upper() == "ERROR" for review in reviews):
            merged_status = "ERROR"
        elif accepted:
            merged_status = "OK"
        else:
            merged_status = "BLOCKED"
        primary_review = reviews[0]["summary"] if reviews else {}
        primary_model = str(reviews[0].get("model", "")).strip() if reviews else ""
        return (
            {
                "name": review_pack.name,
                "merge_strategy": review_pack.merge_strategy,
                "acceptance_checks": list(review_pack.acceptance_checks),
                "status": merged_status,
                "accepted": accepted,
                "reviews": reviews,
                "primary_review": primary_review,
                "primary_model": primary_model,
            },
            executed_actions,
        )

    def _build_review_pack(
        self,
        req: PlanningRequest,
        model_route: ModelRouteDecision,
    ) -> ReviewPack | None:
        if not self._should_run_critique_gate(req, model_route):
            return None
        layer = str(req.context.layer or "any").strip().lower()
        risk = "high" if self._is_high_risk_request(req) else "standard"
        agents: list[dict[str, Any]] = []
        if model_route.secondary_model:
            agents.append(
                {
                    "name": "secondary_critic",
                    "capability": "INTEGRATION_ANALYSIS",
                    "model": model_route.secondary_model,
                }
            )
        agents.append(
            {
                "name": "primary_reviewer",
                "capability": "INTEGRATION_ANALYSIS",
                "model": model_route.primary_model,
            }
        )
        if layer == "l3" or risk == "high":
            agents.append(
                {
                    "name": "adversarial_reviewer",
                    "capability": "INTEGRATION_ANALYSIS",
                    "model": model_route.secondary_model or model_route.primary_model,
                }
            )
        merge_strategy = "all_must_pass" if len(agents) > 1 else "single"
        return ReviewPack(
            name=f"{layer}_{str(req.capability).lower()}_{risk}_review",
            agents=agents,
            merge_strategy=merge_strategy,
            acceptance_checks=["status_not_error", "risk_profile_present"],
        )

    @staticmethod
    def _review_pack_passes(
        *,
        acceptance_checks: list[str],
        reviews: list[dict[str, Any]],
    ) -> bool:
        if not reviews:
            return False
        checks = {str(check).strip().lower() for check in acceptance_checks if str(check).strip()}
        for review in reviews:
            status = str(review.get("status", "")).strip().upper()
            outputs = review.get("outputs", {})
            if "status_not_error" in checks and status == "ERROR":
                return False
            if "risk_profile_present" in checks and (
                not isinstance(outputs, dict) or not isinstance(outputs.get("risk_profile"), dict)
            ):
                return False
        return True

    @staticmethod
    def _advance_state_from_action(
        state_machine: PlannerStateMachine,
        action: Any,
    ) -> None:
        inputs = action.inputs if isinstance(action.inputs, dict) else {}
        phase_raw = str(inputs.get("phase", "")).strip().lower()
        if phase_raw:
            for phase in PlanPhase:
                if phase.value == phase_raw and phase != state_machine.phase:
                    state_machine.advance(phase)
                    break
        if state_machine.status in {PlanStatus.PAUSED, PlanStatus.WAITING_INPUT}:
            state_machine.resume()

    @staticmethod
    def _should_pause_for_user_input(
        *,
        req: PlanningRequest,
        interim: dict[str, Any],
    ) -> bool:
        if str(req.context.mode).strip().lower() != "interactive":
            return False
        if str(req.capability).strip().upper() != "UNDER_SPEC":
            return False
        result = interim.get("under_spec_result")
        if not isinstance(result, dict):
            return False
        questions = result.get("questions", [])
        return bool(result.get("blocked", False) and isinstance(questions, list) and questions)

    @staticmethod
    def _resolve_wait_prompt(interim: dict[str, Any], *, fallback: str) -> str:
        result = interim.get("under_spec_result")
        if isinstance(result, dict):
            questions = result.get("questions", [])
            if isinstance(questions, list) and questions:
                first = str(questions[0]).strip()
                if first:
                    return first
        return str(fallback or "Planner requires additional input.").strip()

    @staticmethod
    def _build_needs_input_outputs(
        *,
        req: PlanningRequest,
        interim: dict[str, Any],
        prompt: str,
        planner_state: dict[str, Any],
    ) -> dict[str, Any]:
        result = interim.get("under_spec_result")
        outputs = dict(result) if isinstance(result, dict) else {}
        outputs["blocked"] = bool(outputs.get("blocked", True))
        questions = outputs.get("questions", [])
        if not isinstance(questions, list):
            questions = [str(questions)] if questions else []
        if prompt and prompt not in questions:
            questions = [prompt, *questions]
        outputs["questions"] = [str(item).strip() for item in questions if str(item).strip()]
        outputs["prompt"] = prompt
        outputs["planner_state"] = planner_state
        outputs["capability"] = req.capability
        return outputs

    def _notify_gate_hook(
        self,
        hook_name: Literal["before_step", "after_step"],
        gate_name: str,
        req: PlanningRequest,
        gates: dict[str, Any],
        result: PlanningResult | None = None,
    ) -> None:
        if hook_name == "before_step":
            hook = self._promotion_adapters.before_step
            if hook is None:
                return
            try:
                hook(gate_name, req, dict(gates))
            except Exception:
                logger.warning(
                    "promotion before_step hook failed for gate=%s", gate_name, exc_info=True
                )
            return
        hook = self._promotion_adapters.after_step
        if hook is None or result is None:
            return
        try:
            hook(gate_name, req, result, dict(gates))
        except Exception:
            logger.warning("promotion after_step hook failed for gate=%s", gate_name, exc_info=True)

    @staticmethod
    def _build_critique_summary(
        *,
        critique_result: PlanningResult,
        critique_route: ModelRouteDecision,
    ) -> dict[str, Any]:
        return {
            "status": critique_result.status,
            "model": critique_route.primary_model,
            "work_type": critique_route.work_type,
            "summary": str(
                (
                    critique_result.outputs.get("decision_text")
                    if isinstance(critique_result.outputs, dict)
                    else ""
                )
                or critique_result.status
            ).strip(),
        }

    @staticmethod
    def _annotate_result_dispatch_metadata(
        result: PlanningResult,
        *,
        model_route: ModelRouteDecision,
        dispatch_gates: dict[str, Any],
        planner_state: dict[str, Any] | None = None,
        next_actions: list[dict[str, Any]] | None = None,
    ) -> None:
        if not isinstance(result.outputs, dict):
            return
        result.outputs.setdefault("model_route", model_route.to_dict())
        if dispatch_gates:
            result.outputs.setdefault("dispatch_gates", dict(dispatch_gates))
        if isinstance(planner_state, dict):
            result.outputs.setdefault("planner_state", planner_state)
        if isinstance(next_actions, list) and next_actions:
            result.outputs.setdefault(
                "next_actions", [dict(row) for row in next_actions if isinstance(row, dict)]
            )

    @staticmethod
    def _normalize_text_list(value: Any) -> list[str]:
        if isinstance(value, str):
            token = value.strip()
            return [token] if token else []
        if not isinstance(value, list):
            return []
        values: list[str] = []
        for row in value:
            token = str(row).strip()
            if token:
                values.append(token)
        return values

    @staticmethod
    def _extract_decision_text(
        *,
        result: PlanningResult,
        outputs: dict[str, Any],
        overridden: bool,
        error_text: str = "",
    ) -> str:
        if error_text:
            return f"ERROR: {error_text}"
        if overridden:
            return f"OVERRIDDEN: {result.status}"
        candidate = str(outputs.get("decision_text", "")).strip()
        if candidate:
            return candidate
        return str(result.status).strip()

    def _extract_decision_assumptions(
        self,
        *,
        outputs: dict[str, Any],
        model_route: ModelRouteDecision,
        dispatch_gates: dict[str, Any],
        requires_external_facts: bool,
        high_risk: bool,
    ) -> list[str]:
        assumptions: list[str] = []
        for key in ("assumptions", "assumption", "implicit_assumptions"):
            assumptions.extend(self._normalize_text_list(outputs.get(key)))
        assumptions.append(f"work_type={model_route.work_type}")
        assumptions.append(f"requires_external_facts={requires_external_facts}")
        assumptions.append(f"high_risk={high_risk}")
        path = str(dispatch_gates.get("path", "")).strip()
        if path:
            assumptions.append(f"dispatch_path={path}")
        return self._dedupe_preserve(assumptions)

    def _extract_decision_evidence_refs(
        self,
        *,
        req: PlanningRequest,
        outputs: dict[str, Any],
    ) -> list[str]:
        refs: list[str] = []
        for key in ("evidence_refs", "evidence_needed", "spec_refs", "code_refs"):
            refs.extend(self._normalize_text_list(outputs.get(key)))
        questions = outputs.get("questions")
        if isinstance(questions, list):
            for question in questions:
                if isinstance(question, dict):
                    refs.extend(self._normalize_text_list(question.get("evidence_needed")))
                    refs.extend(self._normalize_text_list(question.get("evidence_refs")))
        under_spec_events = outputs.get("under_spec_events")
        if isinstance(under_spec_events, list):
            for event in under_spec_events:
                if not isinstance(event, dict):
                    continue
                refs.extend(self._normalize_text_list(event.get("trigger_evidence")))
                refs.extend(self._normalize_text_list(event.get("evidence_refs")))
                refs.extend(self._normalize_text_list(event.get("spec_refs")))
                refs.extend(self._normalize_text_list(event.get("code_refs")))
                refs.extend(self._normalize_text_list(event.get("pin_ref")))
                refs.extend(self._normalize_text_list(event.get("pin_id")))
        req_inputs = req.inputs if isinstance(req.inputs, dict) else {}
        for key in ("evidence_refs", "spec_refs", "code_refs"):
            refs.extend(self._normalize_text_list(req_inputs.get(key)))
        return self._dedupe_preserve(refs)

    def _extract_decision_alternatives(
        self,
        *,
        req: PlanningRequest,
        outputs: dict[str, Any],
        model_route: ModelRouteDecision,
        dispatch_gates: dict[str, Any],
    ) -> list[str]:
        alternatives: list[str] = []
        for key in ("alternatives_considered", "alternatives"):
            alternatives.extend(self._normalize_text_list(outputs.get(key)))
        proposal_models = self._extract_proposal_models(req)
        model_options = self._dedupe_preserve(
            [*proposal_models, model_route.primary_model, model_route.secondary_model]
        )
        if len(model_options) >= 2:
            alternatives.extend([f"model:{model}" for model in model_options if model][:4])
        if self._coerce_bool(dispatch_gates.get("deterministic_local_checked")):
            alternatives.append("dispatch:deterministic_local")
        path = str(dispatch_gates.get("path", "")).strip()
        if path:
            alternatives.append(f"dispatch:{path}")
        if (
            str(req.capability).strip().upper() in {"PLAN", "UNDER_SPEC", "INTEGRATION_ANALYSIS"}
            and len(alternatives) < 2
        ):
            alternatives.extend(["dispatch:deterministic_local", "dispatch:capability_dispatch"])
        return self._dedupe_preserve(alternatives)

    def _extract_discriminative_checks(
        self,
        *,
        result: PlanningResult,
        outputs: dict[str, Any],
        dispatch_gates: dict[str, Any],
    ) -> list[str]:
        checks: list[str] = []
        for key in ("discriminative_checks", "checks"):
            checks.extend(self._normalize_text_list(outputs.get(key)))
        if self._coerce_bool(dispatch_gates.get("integration_analysis_checked")):
            checks.append("Integration-analysis gate outcome can change route selection.")
        if self._coerce_bool(dispatch_gates.get("external_research_required")):
            checks.append("New external evidence can change the selected plan.")
        if self._coerce_bool(dispatch_gates.get("critique_checked")):
            checks.append("A failed critique gate can force a blocked/review decision.")
        questions = outputs.get("questions")
        if result.status == "BLOCKED" and isinstance(questions, list) and questions:
            checks.append("Resolving blocked under-spec questions would change this decision.")
        if result.status == "ERROR":
            checks.append("Successful execution without runtime errors would change this decision.")
        return self._dedupe_preserve(checks)

    def _build_decision_record(
        self,
        *,
        req: PlanningRequest,
        result: PlanningResult,
        model_route: ModelRouteDecision,
        dispatch_gates: dict[str, Any],
        requires_external_facts: bool,
        high_risk: bool,
        overridden: bool = False,
        error_text: str = "",
    ) -> Any:
        from spec_manager.planner.trace import DecisionRecord

        outputs = result.outputs if isinstance(result.outputs, dict) else {}
        decision_text = self._extract_decision_text(
            result=result,
            outputs=outputs,
            overridden=overridden,
            error_text=error_text,
        )
        confidence_raw = outputs.get("confidence", outputs.get("score", 0.0))
        return DecisionRecord(
            decision_text=decision_text,
            confidence=self._clamp_confidence(confidence_raw),
            assumptions=self._extract_decision_assumptions(
                outputs=outputs,
                model_route=model_route,
                dispatch_gates=dispatch_gates,
                requires_external_facts=requires_external_facts,
                high_risk=high_risk,
            ),
            evidence_refs=self._extract_decision_evidence_refs(req=req, outputs=outputs),
            alternatives_considered=self._extract_decision_alternatives(
                req=req,
                outputs=outputs,
                model_route=model_route,
                dispatch_gates=dispatch_gates,
            ),
            discriminative_checks=self._extract_discriminative_checks(
                result=result,
                outputs=outputs,
                dispatch_gates=dispatch_gates,
            ),
        )

    @staticmethod
    def _result_snapshot(result: PlanningResult, decision_record: Any) -> dict[str, Any]:
        outputs = result.outputs if isinstance(result.outputs, dict) else {}
        rationale = str(getattr(decision_record, "decision_text", "") or result.status).strip()
        confidence = getattr(decision_record, "confidence", 0.0)
        return {
            "status": result.status,
            "outputs": _safe_deepcopy(outputs),
            "error": str(result.error or ""),
            "confidence": confidence,
            "rationale": rationale,
        }

    @staticmethod
    def _normalize_graph_payload(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        nodes = payload.get("nodes")
        edges = payload.get("edges")
        if isinstance(nodes, list) and isinstance(edges, list):
            return {
                "nodes": [row for row in nodes if isinstance(row, dict)],
                "edges": [row for row in edges if isinstance(row, dict)],
            }
        for key in ("quality_graph", "code_skeleton_graph", "architecture_topology_graph"):
            nested = payload.get(key)
            graph = GeneralPlanner._normalize_graph_payload(nested)
            if graph is not None:
                return graph
        return None

    def _integration_graph_artifact(self, outputs: dict[str, Any]) -> dict[str, Any] | None:
        for key in (
            "integration_graph",
            "topology",
            "layer_skeleton",
            "discovery",
            "quality_graph",
            "code_skeleton_graph",
            "architecture_topology_graph",
        ):
            graph = self._normalize_graph_payload(outputs.get(key))
            if graph is not None and (graph["nodes"] or graph["edges"]):
                return graph
        return None

    @staticmethod
    def _plan_artifact(outputs: dict[str, Any]) -> dict[str, Any] | None:
        intentions = outputs.get("intentions")
        if not isinstance(intentions, list):
            return None
        plan_payload: dict[str, Any] = {"intentions": _safe_deepcopy(intentions)}
        plan_artifacts = outputs.get("plan_artifacts")
        if isinstance(plan_artifacts, dict):
            plan_payload["plan_artifacts"] = _safe_deepcopy(plan_artifacts)
        for key in ("integration_notes", "decision_requirements", "decision_outcomes"):
            if key in outputs:
                plan_payload[key] = _safe_deepcopy(outputs.get(key))
        return plan_payload

    @staticmethod
    def _under_spec_questions_artifact(result: PlanningResult) -> list[Any] | None:
        outputs = result.outputs if isinstance(result.outputs, dict) else {}
        blocked = bool(outputs.get("blocked", False) or result.status == "BLOCKED")
        if not blocked:
            return None
        questions = outputs.get("questions")
        if isinstance(questions, list):
            return _safe_deepcopy(questions)
        if questions:
            return [str(questions).strip()]
        return []

    def _record_canonical_artifacts(
        self,
        *,
        trace: Any,
        result: PlanningResult,
    ) -> None:
        outputs = result.outputs if isinstance(result.outputs, dict) else {}
        plan_payload = self._plan_artifact(outputs)
        if plan_payload is not None:
            trace.add_artifact("plan", plan_payload)
        graph_payload = self._integration_graph_artifact(outputs)
        if graph_payload is not None:
            trace.add_artifact("integration_graph", graph_payload)
        questions_payload = self._under_spec_questions_artifact(result)
        if questions_payload is not None:
            trace.add_artifact("under_spec_questions", questions_payload)

    def _build_replay_bundle(
        self,
        *,
        trace_id: str,
        decision_key: str,
        req: PlanningRequest,
        selected_model: str,
        model_route: ModelRouteDecision,
        state_machine: PlannerStateMachine,
        executed_actions: list[dict[str, Any]],
        result: PlanningResult,
        trace: Any,
    ) -> ReplayBundle:
        from spec_manager.planner.trace import compute_input_hash

        request_snapshot = _request_snapshot(
            req,
            input_hash=compute_input_hash(req.capability, req.inputs),
            decision_key=decision_key,
            model_id=selected_model,
            planner_version=PLANNER_VERSION,
            model_route=model_route.to_dict(),
        )
        snapshot_files = self._capture_replay_snapshot_files(req)
        return ReplayBundle(
            trace_id=trace_id,
            decision_key=decision_key,
            request=request_snapshot,
            next_actions=[dict(row) for row in executed_actions if isinstance(row, dict)],
            model_route=model_route.to_dict(),
            planner_state=state_machine.to_dict(),
            final_result={
                "status": result.status,
                "outputs": _safe_deepcopy(result.outputs),
                "error": result.error,
            },
            model_calls=[_safe_deepcopy(call.__dict__) for call in trace.model_calls],
            tool_calls=[_safe_deepcopy(call.__dict__) for call in trace.tool_calls],
            snapshot_files=snapshot_files,
        )

    @staticmethod
    def _build_replay_payload(
        *,
        trace: Any,
        replay_bundle: ReplayBundle,
    ) -> dict[str, Any]:
        payload = replay_bundle.to_dict()
        payload["trace_id"] = str(getattr(trace, "trace_id", "") or payload.get("trace_id", ""))
        payload["decision_key"] = str(
            getattr(trace, "decision_key", "") or payload.get("decision_key", "")
        )
        payload["status"] = str(getattr(trace, "status", "") or payload.get("status", ""))
        payload["request_snapshot"] = _safe_deepcopy(replay_bundle.request)
        payload["result"] = _safe_deepcopy(getattr(trace, "result", {}) or {})
        payload["decision"] = (
            _safe_deepcopy(getattr(getattr(trace, "decision", None), "__dict__", {}))
            if getattr(trace, "decision", None) is not None
            else {}
        )
        if isinstance(payload.get("result"), dict):
            payload.setdefault("outputs", payload["result"].get("outputs", {}))
            payload.setdefault("error", payload["result"].get("error", ""))
            payload.setdefault("confidence", payload["result"].get("confidence", 0.0))
            payload.setdefault("rationale", payload["result"].get("rationale", ""))
        return payload

    @staticmethod
    def _is_text_like_file(path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                sample = handle.read(4096)
        except OSError:
            return False
        if b"\x00" in sample:
            return False
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def _capture_replay_snapshot_files(self, req: PlanningRequest) -> dict[str, str]:
        workspace_root = self._workspace_root.resolve()
        files: set[Path] = set()
        slice_root_raw = str(req.context.slice_root or "").strip()
        if slice_root_raw:
            slice_root = Path(slice_root_raw)
            if not slice_root.is_absolute():
                slice_root = workspace_root / slice_root
            if (
                slice_root.exists()
                and slice_root.is_dir()
                and self._is_relative_to(slice_root, workspace_root)
            ):
                for path in slice_root.rglob("*"):
                    if path.is_file() and self._is_text_like_file(path):
                        files.add(path.resolve())
        run_id = str(req.context.run_id or "").strip()
        if run_id:
            run_dir = workspace_root / ".pdd_runs" / run_id
            if run_dir.exists() and run_dir.is_dir():
                for path in run_dir.rglob("*"):
                    if not path.is_file():
                        continue
                    if path.suffix.lower() not in {".json", ".yaml", ".yml", ".md", ".txt"}:
                        continue
                    if self._is_text_like_file(path):
                        files.add(path.resolve())

        snapshot_files: dict[str, str] = {}
        max_files = 800
        max_bytes = 2 * 1024 * 1024
        for path in sorted(files):
            if len(snapshot_files) >= max_files:
                break
            if not self._is_relative_to(path, workspace_root):
                continue
            try:
                if path.stat().st_size > max_bytes:
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel_path = path.relative_to(workspace_root).as_posix()
            snapshot_files[rel_path] = content
        return snapshot_files

    @staticmethod
    def _load_state_machine(req: PlanningRequest) -> PlannerStateMachine:
        metadata = req.context.metadata if isinstance(req.context.metadata, dict) else {}
        payload = metadata.get("planner_state")
        if isinstance(payload, dict):
            return PlannerStateMachine.from_dict(payload)
        inputs = req.inputs if isinstance(req.inputs, dict) else {}
        payload = inputs.get("planner_state")
        if isinstance(payload, dict):
            return PlannerStateMachine.from_dict(payload)
        return PlannerStateMachine()

    @staticmethod
    def _persist_state_machine(req: PlanningRequest, state_machine: PlannerStateMachine) -> None:
        metadata = req.context.metadata if isinstance(req.context.metadata, dict) else {}
        metadata["planner_state"] = state_machine.to_dict()
        req.context.metadata = metadata

    def _extract_proposal_models(self, req: PlanningRequest) -> list[str]:
        models: list[str] = []
        if isinstance(req.inputs, dict):
            models.extend(self._collect_models_from_value(req.inputs.get("proposal_models")))
            events_raw = req.inputs.get("events", [])
            if isinstance(events_raw, list):
                for event in events_raw:
                    if not isinstance(event, dict):
                        continue
                    models.extend(self._collect_models_from_value(event.get("proposal_models")))
                    metadata = event.get("metadata")
                    if isinstance(metadata, dict):
                        models.extend(
                            self._collect_models_from_value(metadata.get("proposal_models")),
                        )
        if isinstance(req.context.metadata, dict):
            models.extend(
                self._collect_models_from_value(req.context.metadata.get("proposal_models"))
            )
        return self._dedupe_preserve(models)

    @staticmethod
    def _collect_models_from_value(value: Any) -> list[str]:
        if isinstance(value, str):
            token = value.strip()
            return [token] if token else []
        if not isinstance(value, list):
            return []
        tokens: list[str] = []
        for row in value:
            token = str(row).strip()
            if token:
                tokens.append(token)
        return tokens

    def _requires_external_facts(self, req: PlanningRequest) -> bool:
        inputs = req.inputs if isinstance(req.inputs, dict) else {}
        metadata = req.context.metadata if isinstance(req.context.metadata, dict) else {}
        for key in (
            "requires_external_facts",
            "web_research_required",
            "needs_web_research",
            "requires_web_research",
            "external_facts_required",
        ):
            if self._coerce_bool(inputs.get(key)) or self._coerce_bool(metadata.get(key)):
                return True

        signal_payload = inputs.get("signal")
        if isinstance(signal_payload, dict):
            token_blob = " ".join(
                [
                    str(signal_payload.get("classification", "")).strip().lower(),
                    str(signal_payload.get("status", "")).strip().lower(),
                    str((signal_payload.get("need") or {}).get("summary", "")).strip().lower()
                    if isinstance(signal_payload.get("need"), dict)
                    else "",
                ]
            )
            if any(
                marker in token_blob
                for marker in (
                    "external",
                    "internet",
                    "latest",
                    "web",
                    "rfc",
                    "cve",
                    "stackoverflow",
                )
            ):
                return True

        return False

    def _is_high_risk_request(self, req: PlanningRequest) -> bool:
        capability = str(req.capability).strip().upper()
        layer = str(req.context.layer or "").strip().lower()
        inputs = req.inputs if isinstance(req.inputs, dict) else {}
        metadata = req.context.metadata if isinstance(req.context.metadata, dict) else {}

        if capability in {"PLAN", "UNDER_SPEC"} and layer in {"l2", "l3"}:
            return True
        if capability == "INTEGRATION_ANALYSIS" and layer == "l3":
            return True

        high_risk_flags = (
            "high_risk",
            "cross_library_contract",
            "introduces_external_dep",
            "introduces_infra",
            "security_privacy_compliance",
            "has_security_privacy_compliance_implication",
        )
        if any(self._coerce_bool(inputs.get(flag)) for flag in high_risk_flags):
            return True
        if any(self._coerce_bool(metadata.get(flag)) for flag in high_risk_flags):
            return True

        touched_raw = inputs.get("touched_files_count", metadata.get("touched_files_count", 0))
        try:
            touched_files_count = int(touched_raw or 0)
        except (TypeError, ValueError):
            touched_files_count = 0
        if touched_files_count >= 3:
            return True

        events = inputs.get("events", [])
        gaps = inputs.get("gaps", [])
        if isinstance(events, list) and len(events) >= 3:
            return True
        return bool(isinstance(gaps, list) and len(gaps) >= 3)

    def _should_run_integration_gate(self, req: PlanningRequest) -> bool:
        capability = str(req.capability).strip().upper()
        if capability == "INTEGRATION_ANALYSIS":
            return False
        return capability in {
            "PLAN",
            "UNDER_SPEC",
            "TRIAGE_SIGNAL",
            "RESOLVE_SIGNAL",
            "GAP",
        }

    def _should_run_critique_gate(
        self,
        req: PlanningRequest,
        model_route: ModelRouteDecision,
    ) -> bool:
        if not model_route.secondary_model:
            return False
        capability = str(req.capability).strip().upper()
        if capability not in {"PLAN", "UNDER_SPEC", "INTEGRATION_ANALYSIS"}:
            return False
        return self._is_high_risk_request(req)

    def _try_deterministic_local_resolution(self, req: PlanningRequest) -> PlanningResult | None:
        """Resolve requests directly from authoritative local constraints when possible."""
        inputs = req.inputs if isinstance(req.inputs, dict) else {}
        target_slice = str(req.context.slice_id or "__system__").strip() or "__system__"

        if req.capability == "UNDER_SPEC":
            events = inputs.get("events", [])
            if not isinstance(events, list) or not events:
                return None
            answers = self._constraint_answer_lookup(target_slice=target_slice)
            resolved: list[dict[str, Any]] = []
            unresolved_questions: list[str] = []
            constraints: dict[str, str] = {}
            for event in events:
                if not isinstance(event, dict):
                    continue
                question = self._event_question(event)
                if not question:
                    continue
                normalized = self._normalize_for_compare(question)
                answer = answers.get(normalized, "")
                if not answer:
                    unresolved_questions.append(question)
                    continue
                constraints[question] = answer
                resolved.append(
                    {
                        "event": event,
                        "resolution": "constraints_store",
                        "answer": answer,
                    }
                )
            if unresolved_questions or not resolved:
                return None
            return PlanningResult(
                status="OK",
                outputs={
                    "blocked": False,
                    "questions": [],
                    "resolved": resolved,
                    "constraints": constraints,
                    "decision_text": "Resolved under-spec via local constraints coverage",
                },
            )

        if req.capability == "RESOLVE_SIGNAL":
            signal = inputs.get("signal")
            if not isinstance(signal, dict):
                return None
            question = self._event_question(signal)
            if not question and isinstance(signal.get("need"), dict):
                question = str((signal.get("need") or {}).get("summary", "")).strip()
            if not question:
                return None
            answers = self._constraint_answer_lookup(target_slice=target_slice)
            answer = answers.get(self._normalize_for_compare(question), "")
            if not answer:
                return None
            return PlanningResult(
                status="OK",
                outputs={
                    "response": {
                        "resolved": True,
                        "source": "constraints_store",
                        "detail": answer,
                    }
                },
            )

        return None

    def _constraint_answer_lookup(self, *, target_slice: str) -> dict[str, str]:
        answers: dict[str, str] = {}
        for fact in self._constraints_store_tool.load_merged(target_slice):
            question = self._normalize_for_compare(getattr(fact, "question", ""))
            answer = str(getattr(fact, "answer", "")).strip()
            if question and answer and question not in answers:
                answers[question] = answer
        return answers

    @staticmethod
    def _event_question(event: dict[str, Any]) -> str:
        return str(event.get("question", event.get("description", ""))).strip()

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return False

    @staticmethod
    def _coerce_id_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, (list, tuple, set)):
            ids: list[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    ids.append(text)
            return ids
        return []

    @staticmethod
    def _dedupe_preserve(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    @staticmethod
    def _extract_decision_requirements(outputs: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract decision requirements from top-level and intention payloads."""
        requirements: list[dict[str, Any]] = []

        top_level = outputs.get("decision_requirements")
        if isinstance(top_level, list):
            for requirement in top_level:
                if isinstance(requirement, dict):
                    requirements.append(requirement)

        intentions = outputs.get("intentions")
        if isinstance(intentions, list):
            for intention in intentions:
                if not isinstance(intention, dict):
                    continue
                embedded_requirements = intention.get("decision_requirements", [])
                if not isinstance(embedded_requirements, list):
                    continue
                for requirement in embedded_requirements:
                    if isinstance(requirement, dict):
                        requirements.append(requirement)

        return requirements

    @staticmethod
    def _extract_update_identifiers(
        outputs: dict[str, Any],
    ) -> tuple[list[str], list[str], list[str]]:
        decision_ids = GeneralPlanner._coerce_id_list(outputs.get("decision_ids"))
        decision_ids.extend(GeneralPlanner._coerce_id_list(outputs.get("decision_id")))
        constraint_ids = GeneralPlanner._coerce_id_list(outputs.get("constraint_ids"))
        constraint_ids.extend(GeneralPlanner._coerce_id_list(outputs.get("constraint_id")))
        canonical_keys = GeneralPlanner._coerce_id_list(outputs.get("canonical_keys"))
        canonical_keys.extend(GeneralPlanner._coerce_id_list(outputs.get("canonical_key")))

        under_spec_events = outputs.get("under_spec_events")
        if isinstance(under_spec_events, list):
            for event in under_spec_events:
                if not isinstance(event, dict):
                    continue
                decision_ids.extend(GeneralPlanner._coerce_id_list(event.get("decision_id")))
                decision_ids.extend(GeneralPlanner._coerce_id_list(event.get("decision_ids")))
                constraint_ids.extend(GeneralPlanner._coerce_id_list(event.get("constraint_id")))
                constraint_ids.extend(GeneralPlanner._coerce_id_list(event.get("constraint_ids")))
                canonical_keys.extend(GeneralPlanner._coerce_id_list(event.get("canonical_key")))
                canonical_keys.extend(GeneralPlanner._coerce_id_list(event.get("canonical_keys")))

        for requirement in GeneralPlanner._extract_decision_requirements(outputs):
            decision_ids.extend(GeneralPlanner._coerce_id_list(requirement.get("decision_id")))
            decision_ids.extend(GeneralPlanner._coerce_id_list(requirement.get("decision_ids")))
            canonical_keys.extend(GeneralPlanner._coerce_id_list(requirement.get("canonical_key")))
            canonical_keys.extend(GeneralPlanner._coerce_id_list(requirement.get("canonical_keys")))

        return (
            GeneralPlanner._dedupe_preserve(decision_ids),
            GeneralPlanner._dedupe_preserve(constraint_ids),
            GeneralPlanner._dedupe_preserve(canonical_keys),
        )

    @staticmethod
    def _extract_review_questions(outputs: dict[str, Any]) -> list[dict[str, Any]]:
        review_questions: list[dict[str, Any]] = []

        for requirement in GeneralPlanner._extract_decision_requirements(outputs):
            requirement_authority = str(requirement.get("authority_required", "")).strip().lower()
            if requirement_authority not in {"human_required", "user_required"}:
                continue
            question_text = (
                str(
                    requirement.get("question")
                    or requirement.get("user_question")
                    or requirement.get("question_text")
                    or "",
                ).strip()
                or "Planner requires user authority for a decision."
            )
            reason = (
                str(requirement.get("reason", "")).strip()
                or f"authority_required={requirement_authority}"
            )
            payload: dict[str, Any] = {}
            requirement_ids = GeneralPlanner._coerce_id_list(
                requirement.get("decision_requirement_id")
            )
            requirement_ids.extend(
                GeneralPlanner._coerce_id_list(requirement.get("decision_requirement_ids"))
            )
            requirement_ids.extend(
                GeneralPlanner._coerce_id_list(requirement.get("requirement_id"))
            )
            requirement_ids.extend(
                GeneralPlanner._coerce_id_list(requirement.get("requirement_ids"))
            )
            requirement_ids = GeneralPlanner._dedupe_preserve(requirement_ids)
            if requirement_ids:
                payload["decision_requirement_ids"] = requirement_ids
            requirement_decision_ids = GeneralPlanner._coerce_id_list(
                requirement.get("decision_id")
            )
            requirement_decision_ids.extend(
                GeneralPlanner._coerce_id_list(requirement.get("decision_ids"))
            )
            requirement_decision_ids = GeneralPlanner._dedupe_preserve(requirement_decision_ids)
            if requirement_decision_ids:
                payload["decision_ids"] = requirement_decision_ids
            requirement_canonical_keys = GeneralPlanner._coerce_id_list(
                requirement.get("canonical_key")
            )
            requirement_canonical_keys.extend(
                GeneralPlanner._coerce_id_list(requirement.get("canonical_keys"))
            )
            requirement_canonical_keys = GeneralPlanner._dedupe_preserve(requirement_canonical_keys)
            if requirement_canonical_keys:
                payload["canonical_keys"] = requirement_canonical_keys
            review_questions.append(
                {
                    "question_text": question_text,
                    "reason": reason,
                    "payload": payload,
                }
            )

        under_spec_events = outputs.get("under_spec_events")
        if isinstance(under_spec_events, list):
            for event in under_spec_events:
                if not isinstance(event, dict):
                    continue
                event_type = str(event.get("type", "")).strip().lower()
                event_authority = str(event.get("authority_required", "")).strip().lower()
                if event_type not in {
                    "authority_required",
                    "decision_required",
                } and event_authority not in {
                    "human_required",
                    "user_required",
                }:
                    continue
                question_text = str(event.get("question", "")).strip()
                if not question_text:
                    question_text = "Planner requires user authority for an under-spec decision."
                reason = str(event.get("reason", "")).strip() or "human authority required"
                payload: dict[str, Any] = {}
                under_spec_event_id = str(event.get("event_id", "")).strip()
                if under_spec_event_id:
                    payload["under_spec_event_id"] = under_spec_event_id
                review_questions.append(
                    {
                        "question_text": question_text,
                        "reason": reason,
                        "payload": payload,
                    }
                )

        explicit_flags = (
            "review_required",
            "requires_review",
            "needs_review",
            "needs_human_review",
            "human_authority_required",
        )
        authority_required = str(outputs.get("authority_required", "")).strip().lower()
        authority_payload = outputs.get("authority")
        if not authority_required and isinstance(authority_payload, dict):
            authority_required = (
                str(
                    authority_payload.get(
                        "required", authority_payload.get("authority_required", "")
                    ),
                )
                .strip()
                .lower()
            )
        if review_questions:
            return review_questions

        review_required = any(
            GeneralPlanner._coerce_bool(outputs.get(flag)) for flag in explicit_flags
        )
        if not review_required and authority_required in {"human_required", "user_required"}:
            review_required = True
        if not review_required:
            return []

        question_text = ""
        for key in ("review_question_text", "user_question", "question"):
            candidate = str(outputs.get(key, "")).strip()
            if candidate:
                question_text = candidate
                break
        if not question_text:
            question_text = "Planner reached a decision that requires user authority review."

        reason = str(outputs.get("review_reason", "")).strip()
        if not reason:
            if authority_required in {"human_required", "user_required"}:
                reason = f"authority_required={authority_required}"
            else:
                reason = "planner flagged review_required"

        return [
            {
                "question_text": question_text,
                "reason": reason,
                "payload": {},
            }
        ]

    @staticmethod
    def _build_review_signal_payload(
        *,
        run_id: str,
        trace_id: str,
        slice_id: str,
        layer: str,
        decision_key: str,
        canonical_keys: list[str],
        decision_ids: list[str],
        constraint_ids: list[str],
        signal_sequence: int,
        question_text: str,
        reason: str,
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if trace_id:
            signal_id = f"{trace_id}:review:{signal_sequence}"
        else:
            signal_id = f"planner-review-{uuid.uuid4().hex[:12]}"
        token = re.sub(r"[^a-zA-Z0-9._-]+", "_", decision_key or signal_id).strip("._-")
        canonical_key_hint = f"planner.review.{token}" if token else "planner.review"
        payload = {
            "event_kind": "decision_review_required",
            "reason": reason,
            "decision_key": decision_key,
            "decision_ids": list(decision_ids),
            "constraint_ids": list(constraint_ids),
            "canonical_keys": list(canonical_keys),
        }
        if extra_payload:
            payload.update(extra_payload)
        return {
            "uq_version": 1,
            "uq_id": f"uq_{uuid.uuid4().hex[:12]}",
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "source": {
                "kind": "PLANNER",
                "trace_id": trace_id,
                "slice_id": slice_id,
                "layer": layer,
                "signal_id": signal_id,
            },
            "question": {
                "text": question_text,
                "taxonomy_hint": "VALIDATION",
                "canonical_key_hint": canonical_key_hint,
                "answer_spec_hint": {
                    "preferred_kind": "choice",
                    "choices": [
                        {"id": "accept_auto", "label": "Accept planner decision"},
                        {"id": "revise_decision", "label": "Revise decision with planner"},
                        {"id": "manual_resolution", "label": "Require manual resolution"},
                    ],
                },
            },
            "context": {
                "blocking": {
                    "severity": "BLOCKING",
                    "blocked_slices": [slice_id] if slice_id else [],
                },
                "spec_refs": [],
                "code_refs": [],
            },
            "payload": payload,
        }

    def _emit_decision_recorded_event(
        self,
        *,
        trace: Any,
        context: PlanningContext,
        capability: str,
        decision_key: str,
        outputs: dict[str, Any],
    ) -> None:
        safe_outputs = outputs if isinstance(outputs, dict) else {}
        decision_ids, constraint_ids, canonical_keys = self._extract_update_identifiers(
            safe_outputs
        )
        review_questions = self._extract_review_questions(safe_outputs)
        review_required = bool(review_questions)
        review_reason = review_questions[0]["reason"] if review_questions else ""
        decision_record_tags = self._dedupe_preserve(
            self._coerce_id_list(safe_outputs.get("decision_record_tags", []))
        )

        decision = getattr(trace, "decision", None)
        decision_text = ""
        if decision is not None:
            decision_text = str(getattr(decision, "decision_text", "") or "")
        base_event: dict[str, Any] = {
            "event_kind": "decision_recorded",
            "event_id": str(getattr(trace, "trace_id", "") or ""),
            "trace_id": str(getattr(trace, "trace_id", "") or ""),
            "created_at": datetime.now(UTC).isoformat(),
            "run_id": context.run_id,
            "slice_id": context.slice_id,
            "layer": str(getattr(trace, "layer", "") or context.layer),
            "capability": capability,
            "decision_key": decision_key,
            "status": str(getattr(trace, "status", "") or ""),
            "decision_text": decision_text,
            "decision_ids": decision_ids,
            "constraint_ids": constraint_ids,
            "canonical_keys": canonical_keys,
            "review_required": review_required,
            "review_reason": review_reason,
        }
        if decision_record_tags:
            base_event["decision_record_tags"] = decision_record_tags
        events_to_emit: list[dict[str, Any]] = []
        if review_questions:
            for sequence, review_question in enumerate(review_questions, start=1):
                event = dict(base_event)
                event["event_id"] = (
                    f"{base_event['event_id']}:{sequence}"
                    if base_event["event_id"]
                    else f"planner-review-event-{uuid.uuid4().hex[:12]}"
                )
                event["created_at"] = datetime.now(UTC).isoformat()
                event["review_reason"] = str(review_question["reason"]).strip()
                event["user_question_signal"] = self._build_review_signal_payload(
                    run_id=context.run_id,
                    trace_id=event["trace_id"],
                    slice_id=context.slice_id,
                    layer=event["layer"],
                    decision_key=decision_key,
                    canonical_keys=canonical_keys,
                    decision_ids=decision_ids,
                    constraint_ids=constraint_ids,
                    signal_sequence=sequence,
                    question_text=str(review_question["question_text"]).strip(),
                    reason=str(review_question["reason"]).strip() or "human authority required",
                    extra_payload=(
                        review_question["payload"]
                        if isinstance(review_question.get("payload"), dict)
                        else {}
                    ),
                )
                events_to_emit.append(event)
        else:
            events_to_emit.append(base_event)

        for event in events_to_emit:
            self._append_planner_update(context.run_id, event)
            if self._on_decision_recorded is not None:
                try:
                    self._on_decision_recorded(event)
                except Exception:
                    logger.warning(
                        "on_decision_recorded callback failed for trace=%s",
                        event["trace_id"],
                        exc_info=True,
                    )

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

    def _append_planner_update(self, run_id: str, event: dict[str, Any]) -> None:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            logger.debug(
                "Planner update not written because run_id is missing (event_kind=%s)",
                event.get("event_kind", ""),
            )
            return
        updates_path = (
            self._workspace_root
            / ".pdd_runs"
            / normalized_run_id
            / "coordination"
            / "planner_updates.jsonl"
        )
        try:
            updates_path.parent.mkdir(parents=True, exist_ok=True)
            with updates_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError:
            logger.warning(
                "Failed to append planner update event_kind=%s run_id=%s",
                event.get("event_kind", ""),
                normalized_run_id,
                exc_info=True,
            )

    def ingest_user_answer(
        self,
        translation: Any,
        *,
        context: PlanningContext | None = None,
        slice_id: str = "",
    ) -> PlanningResult:
        """Ingest an Intent-Agent answer translation through GeneralPlanner.plan()."""
        inputs: dict[str, Any] = {}
        run_id_hint = ""
        if isinstance(translation, Path):
            inputs["translation_path"] = str(translation)
            run_id_hint = self._infer_run_id_from_translation_path(translation)
        elif isinstance(translation, str):
            inputs["translation_path"] = translation
            run_id_hint = self._infer_run_id_from_translation_path(Path(translation))
        elif isinstance(translation, dict):
            inputs["translation"] = translation
            run_id_hint = str(translation.get("run_id", "")).strip()
        elif hasattr(translation, "to_dict") and callable(translation.to_dict):
            payload = translation.to_dict()
            inputs["translation"] = payload
            run_id_hint = str(payload.get("run_id", "")).strip()
        else:
            inputs["translation"] = translation

        if slice_id:
            inputs["slice_id"] = slice_id

        if context is None:
            context = PlanningContext(
                run_id=run_id_hint,
                slice_id=slice_id,
                layer="any",
                mode=self._mode if self._mode in {"auto", "interactive"} else "auto",
                workspace_root=str(self._workspace_root),
            )

        req = PlanningRequest(
            capability="INGEST_USER_ANSWER",
            context=context,
            inputs=inputs,
        )
        return self.plan(req)

    def _handle_ingest_user_answer(self, req: PlanningRequest) -> PlanningResult:
        from spec_manager.orchestration.intent_agent.answer_translation import AnswerTranslation
        from spec_manager.planner.constraints.types import ConstraintFact

        payload, source_ref, payload_errors = self._resolve_ingest_translation_payload(req.inputs)
        if payload is None:
            return PlanningResult(
                status="ERROR",
                outputs={
                    "validation_errors": payload_errors,
                    "decision_record_tags": ["answer_ingestion"],
                    "decision_text": "INGEST_USER_ANSWER rejected invalid payload",
                },
                error="invalid answer translation payload",
            )

        validation_errors = self._validate_ingest_translation_payload(payload)
        if validation_errors:
            return PlanningResult(
                status="ERROR",
                outputs={
                    "validation_errors": validation_errors,
                    "translation_id": str(payload.get("translation_id", "")).strip(),
                    "decision_record_tags": ["answer_ingestion"],
                    "decision_text": "INGEST_USER_ANSWER rejected invalid schema",
                },
                error="invalid answer translation schema",
            )

        try:
            translation = AnswerTranslation.from_dict(payload)
        except Exception as exc:
            return PlanningResult(
                status="ERROR",
                outputs={
                    "translation_id": str(payload.get("translation_id", "")).strip(),
                    "validation_errors": [f"translation deserialization failed: {exc}"],
                    "decision_record_tags": ["answer_ingestion"],
                    "decision_text": "INGEST_USER_ANSWER failed to deserialize translation",
                },
                error=f"translation deserialization failed: {exc}",
            )

        if translation.translation_status != "succeeded":
            return PlanningResult(
                status="NOOP",
                outputs={
                    "translation_id": translation.translation_id,
                    "question_id": translation.question_id,
                    "answer_id": translation.answer_id,
                    "source_ref": source_ref,
                    "translation_status": translation.translation_status,
                    "translation_failures": list(translation.extracted.translation_failures),
                    "decision_record_tags": ["answer_ingestion"],
                    "decision_text": "INGEST_USER_ANSWER skipped failed translation",
                },
            )

        target_slice_id = (
            str(req.inputs.get("slice_id") or req.context.slice_id or "__system__").strip()
            or "__system__"
        )

        authoritative_facts = self._constraints_store_tool.load_merged(target_slice_id)
        existing_by_canonical: dict[str, list[Any]] = {}
        existing_by_question: dict[str, list[Any]] = {}
        for fact in authoritative_facts:
            canonical_key = self._extract_trace_tag(getattr(fact, "trace", []), "canonical_key")
            canonical_norm = self._normalize_for_compare(canonical_key)
            if canonical_norm:
                existing_by_canonical.setdefault(canonical_norm, []).append(fact)
            question_norm = self._normalize_for_compare(getattr(fact, "question", ""))
            if question_norm:
                existing_by_question.setdefault(question_norm, []).append(fact)

        proposals: list[dict[str, Any]] = []
        candidate_validation_errors: list[str] = []
        fallback_key = str(
            translation.canonical_key_hint or translation.question_id or "answer"
        ).strip()

        for idx, candidate in enumerate(translation.extracted.constraint_candidates):
            question = str(candidate.question).strip()
            answer = str(candidate.answer).strip() or str(translation.user_answer.raw_text).strip()
            canonical_key = str(candidate.canonical_key_hint).strip() or fallback_key
            if not question:
                question = f"Constraint answer for {canonical_key or translation.question_id}"
            if not answer:
                candidate_validation_errors.append(
                    f"constraint_candidates[{idx}] missing answer text",
                )
                continue
            scope_kind = str(candidate.scope_kind).strip().upper()
            scope = "system" if scope_kind == "SYSTEM_WIDE" else "intra:LIB"
            proposals.append(
                {
                    "taxonomy": "CONSTRAINT",
                    "canonical_key": canonical_key,
                    "question": question,
                    "answer": answer,
                    "confidence": self._clamp_confidence(candidate.confidence),
                    "scope": scope,
                }
            )

        for idx, candidate in enumerate(translation.extracted.tradeoff_candidates):
            axis = str(candidate.axis).strip()
            preference = str(candidate.preference).strip()
            if not (axis and preference):
                candidate_validation_errors.append(
                    f"tradeoff_candidates[{idx}] requires axis and preference",
                )
                continue
            canonical_suffix = re.sub(r"[^a-z0-9]+", "_", axis.lower()).strip("_") or f"axis_{idx}"
            proposals.append(
                {
                    "taxonomy": "TRADEOFF",
                    "canonical_key": f"{fallback_key}.tradeoff.{canonical_suffix}",
                    "question": f"Tradeoff preference for {axis}",
                    "answer": preference,
                    "confidence": self._clamp_confidence(candidate.confidence),
                    "scope": "intra:LIB",
                }
            )

        for idx, candidate in enumerate(translation.extracted.scope_candidates):
            scope_in = [str(item).strip() for item in candidate.scope_in if str(item).strip()]
            scope_out = [str(item).strip() for item in candidate.scope_out if str(item).strip()]
            if not scope_in and not scope_out:
                candidate_validation_errors.append(
                    f"scope_candidates[{idx}] empty scope_in and scope_out",
                )
                continue
            if scope_in:
                proposals.append(
                    {
                        "taxonomy": "SCOPE",
                        "canonical_key": f"{fallback_key}.scope.in",
                        "question": "In-scope items from user answer",
                        "answer": ", ".join(scope_in),
                        "confidence": 1.0,
                        "scope": "intra:LIB",
                    }
                )
            if scope_out:
                proposals.append(
                    {
                        "taxonomy": "SCOPE",
                        "canonical_key": f"{fallback_key}.scope.out",
                        "question": "Out-of-scope items from user answer",
                        "answer": ", ".join(scope_out),
                        "confidence": 1.0,
                        "scope": "intra:LIB",
                    }
                )

        for idx, candidate in enumerate(translation.extracted.validation_candidates):
            acceptance_statement = str(candidate.acceptance_statement).strip()
            if not acceptance_statement:
                candidate_validation_errors.append(
                    f"validation_candidates[{idx}] missing acceptance_statement",
                )
                continue
            proposals.append(
                {
                    "taxonomy": "VALIDATION",
                    "canonical_key": f"{fallback_key}.validation.{idx + 1}",
                    "question": "Validation criterion from user answer",
                    "answer": acceptance_statement,
                    "confidence": 1.0,
                    "scope": "intra:LIB",
                }
            )

        accepted_facts: list[ConstraintFact] = []
        accepted_constraint_ids: list[str] = []
        accepted_canonical_keys: list[str] = []
        decision_requirements: list[dict[str, Any]] = []
        under_spec_events: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        seen_candidates: set[tuple[str, str, str]] = set()
        seen_canonical_answers: dict[str, str] = {}

        for proposal in proposals:
            taxonomy = str(proposal.get("taxonomy", "")).strip().upper()
            if taxonomy not in _VALID_INGEST_TAXONOMY:
                candidate_validation_errors.append(
                    f"invalid taxonomy {taxonomy!r}; expected one of "
                    f"{sorted(_VALID_INGEST_TAXONOMY)}",
                )
                continue

            canonical_key = str(proposal.get("canonical_key", "")).strip()
            canonical_norm = self._normalize_for_compare(canonical_key)
            question = str(proposal.get("question", "")).strip()
            question_norm = self._normalize_for_compare(question)
            answer = str(proposal.get("answer", "")).strip()
            answer_norm = self._normalize_for_compare(answer)
            if not question_norm or not answer_norm:
                candidate_validation_errors.append(
                    f"{taxonomy} candidate requires non-empty question and answer",
                )
                continue

            dedupe_key = (canonical_norm, question_norm, answer_norm)
            if dedupe_key in seen_candidates:
                continue
            seen_candidates.add(dedupe_key)

            if canonical_norm:
                existing_candidate_answer = seen_canonical_answers.get(canonical_norm, "")
                if existing_candidate_answer and existing_candidate_answer != answer_norm:
                    decision_id = self._build_ingest_decision_id(
                        canonical_key,
                        question,
                        answer,
                        existing_candidate_answer,
                    )
                    conflict_question = (
                        f"User answer provided conflicting values for {canonical_key}. "
                        "Which value should be authoritative?"
                    )
                    decision_requirements.append(
                        {
                            "decision_id": decision_id,
                            "question": conflict_question,
                            "kind": "answer_conflict",
                            "dimension": "software",
                            "scope": "intra:LIB",
                            "impact": "MEDIUM",
                            "options": ["first_value", "latest_value", "manual_resolution"],
                            "needed_for": [target_slice_id],
                            "authority_required": "human_required",
                            "reason": "conflicting answers in same ingestion batch",
                            "canonical_key": canonical_key,
                        }
                    )
                    under_spec_events.append(
                        {
                            "type": "decision_required",
                            "event_id": decision_id,
                            "decision_id": decision_id,
                            "question": conflict_question,
                            "reason": "conflicting answers in same ingestion batch",
                            "canonical_key": canonical_key,
                            "authority_required": "human_required",
                        }
                    )
                    conflicts.append(
                        {
                            "canonical_key": canonical_key,
                            "reason": "batch_conflict",
                        }
                    )
                    continue
                seen_canonical_answers[canonical_norm] = answer_norm

            existing_matches: list[Any] = []
            if canonical_norm:
                existing_matches.extend(existing_by_canonical.get(canonical_norm, []))
            if not existing_matches and question_norm:
                existing_matches.extend(existing_by_question.get(question_norm, []))

            if existing_matches:
                same_answer = any(
                    self._normalize_for_compare(getattr(existing, "answer", "")) == answer_norm
                    for existing in existing_matches
                )
                if same_answer:
                    continue

                existing = existing_matches[0]
                existing_constraint_id = str(getattr(existing, "constraint_id", "")).strip()
                decision_id = self._build_ingest_decision_id(
                    canonical_key,
                    question,
                    answer,
                    existing_constraint_id,
                )
                conflict_question = (
                    f"User answer conflicts with existing authoritative constraint "
                    f"{existing_constraint_id} for '{question}'. Which should apply?"
                )
                decision_requirements.append(
                    {
                        "decision_id": decision_id,
                        "question": conflict_question,
                        "kind": "answer_conflict",
                        "dimension": "software",
                        "scope": "intra:LIB",
                        "impact": "MEDIUM",
                        "options": ["keep_existing", "accept_user_answer", "manual_resolution"],
                        "needed_for": [target_slice_id],
                        "authority_required": "human_required",
                        "reason": "proposed answer conflicts with authoritative constraint",
                        "canonical_key": canonical_key,
                        "existing_constraint_id": existing_constraint_id,
                    }
                )
                under_spec_events.append(
                    {
                        "type": "decision_required",
                        "event_id": decision_id,
                        "decision_id": decision_id,
                        "question": conflict_question,
                        "reason": "proposed answer conflicts with authoritative constraint",
                        "canonical_key": canonical_key,
                        "constraint_id": existing_constraint_id,
                        "authority_required": "human_required",
                    }
                )
                conflicts.append(
                    {
                        "canonical_key": canonical_key,
                        "existing_constraint_id": existing_constraint_id,
                        "reason": "authoritative_conflict",
                    }
                )
                continue

            constraint_id = self._build_ingest_constraint_id(canonical_key, question, answer)
            fact = ConstraintFact(
                constraint_id=constraint_id,
                question=question,
                answer=answer,
                source="user",
                confidence=self._clamp_confidence(proposal.get("confidence", 1.0)),
                validated=True,
                dimension="software",
                authority_required="planner_ok",
                scope=str(proposal.get("scope", "intra:LIB")),
                status="ACTIVE",
                trace=[
                    "ingest_capability=INGEST_USER_ANSWER",
                    f"translation_id={translation.translation_id}",
                    f"answer_id={translation.answer_id}",
                    f"question_id={translation.question_id}",
                    f"taxonomy={taxonomy.lower()}",
                    f"canonical_key={canonical_key}",
                    "authority_input=user_answer",
                    "authority_policy=planner_validated",
                ],
            )
            accepted_facts.append(fact)
            accepted_constraint_ids.append(constraint_id)
            if canonical_key:
                accepted_canonical_keys.append(canonical_key)

        persisted_path = ""
        if accepted_facts:
            persisted_path = str(
                self._constraints_store_tool.save_facts(target_slice_id, accepted_facts)
            )

        decision_ids = self._dedupe_preserve(
            [
                str(item.get("decision_id", "")).strip()
                for item in decision_requirements
                if str(item.get("decision_id", "")).strip()
            ]
        )

        outputs: dict[str, Any] = {
            "translation_id": translation.translation_id,
            "question_id": translation.question_id,
            "answer_id": translation.answer_id,
            "source_ref": source_ref,
            "ingest_slice_id": target_slice_id,
            "constraint_ids": self._dedupe_preserve(accepted_constraint_ids),
            "canonical_keys": self._dedupe_preserve(accepted_canonical_keys),
            "decision_ids": decision_ids,
            "decision_requirements": decision_requirements,
            "under_spec_events": under_spec_events,
            "accepted_constraints": [fact.to_dict() for fact in accepted_facts],
            "conflicts": conflicts,
            "validation_errors": candidate_validation_errors,
            "persisted_constraints_path": persisted_path,
            "decision_record_tags": ["answer_ingestion"],
            "decision_text": (
                "INGEST_USER_ANSWER "
                f"accepted={len(accepted_facts)} "
                f"conflicts={len(conflicts)} "
                f"validation_errors={len(candidate_validation_errors)}"
            ),
        }
        if not accepted_facts and not decision_requirements:
            return PlanningResult(status="NOOP", outputs=outputs)
        return PlanningResult(status="OK", outputs=outputs)

    def _resolve_ingest_translation_payload(
        self,
        inputs: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, list[str]]:
        payload_errors: list[str] = []
        source_ref = ""
        raw_translation = inputs.get("translation")
        raw_translation_path = inputs.get("translation_path")

        if raw_translation_path:
            path = Path(str(raw_translation_path))
            source_ref = str(path)
            if not path.exists():
                return None, source_ref, [f"translation_path does not exist: {path}"]
            try:
                raw_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return None, source_ref, [f"failed to read translation_path: {exc}"]
            if not isinstance(raw_payload, dict):
                return None, source_ref, ["translation_path JSON payload must be an object"]
            return raw_payload, source_ref, payload_errors

        if isinstance(raw_translation, dict):
            source_ref = f"translation:{raw_translation.get('translation_id', '')}"
            return raw_translation, source_ref, payload_errors

        if hasattr(raw_translation, "to_dict") and callable(raw_translation.to_dict):
            payload = raw_translation.to_dict()
            if not isinstance(payload, dict):
                return None, source_ref, ["translation.to_dict() must return an object"]
            source_ref = f"translation:{payload.get('translation_id', '')}"
            return payload, source_ref, payload_errors

        if isinstance(raw_translation, (str, Path)):
            path = Path(str(raw_translation))
            source_ref = str(path)
            if not path.exists():
                return None, source_ref, [f"translation path does not exist: {path}"]
            try:
                raw_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return None, source_ref, [f"failed to read translation path: {exc}"]
            if not isinstance(raw_payload, dict):
                return None, source_ref, ["translation path JSON payload must be an object"]
            return raw_payload, source_ref, payload_errors

        payload_errors.append(
            "INGEST_USER_ANSWER requires translation payload or translation_path input",
        )
        return None, source_ref, payload_errors

    @staticmethod
    def _validate_ingest_translation_payload(payload: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        required_fields = ("translation_id", "question_id", "created_at", "extracted")
        for field_name in required_fields:
            if field_name not in payload:
                errors.append(f"missing required field: {field_name}")

        translation_id = payload.get("translation_id")
        if not isinstance(translation_id, str) or not translation_id.strip():
            errors.append("translation_id must be a non-empty string")

        question_id = payload.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            errors.append("question_id must be a non-empty string")

        extracted = payload.get("extracted")
        if not isinstance(extracted, dict):
            errors.append("extracted must be an object")
            return errors

        extracted_list_fields = (
            "constraint_candidates",
            "scope_candidates",
            "tradeoff_candidates",
            "validation_candidates",
            "followup_question_drafts",
            "followup_omissions",
            "translation_failures",
        )
        for field_name in extracted_list_fields:
            value = extracted.get(field_name, [])
            if not isinstance(value, list):
                errors.append(f"extracted.{field_name} must be a list")

        for idx, followup in enumerate(extracted.get("followup_question_drafts", [])):
            if not isinstance(followup, dict):
                errors.append(f"extracted.followup_question_drafts[{idx}] must be an object")
                continue
            taxonomy_type = str(followup.get("taxonomy_type", "")).strip().upper()
            if taxonomy_type and taxonomy_type not in _VALID_INGEST_TAXONOMY:
                errors.append(
                    "extracted.followup_question_drafts"
                    f"[{idx}].taxonomy_type {taxonomy_type!r} is invalid",
                )

        return errors

    @staticmethod
    def _extract_trace_tag(trace_entries: Any, key: str) -> str:
        key_prefix = f"{key}="
        if not isinstance(trace_entries, list):
            return ""
        for entry in trace_entries:
            entry_text = str(entry)
            if entry_text.startswith(key_prefix):
                return entry_text.split("=", 1)[1].strip()
        return ""

    @staticmethod
    def _normalize_for_compare(value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.0
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _build_ingest_constraint_id(canonical_key: str, question: str, answer: str) -> str:
        seed = f"{canonical_key}|{question}|{answer}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        token = re.sub(r"[^a-zA-Z0-9]+", "-", canonical_key).strip("-").upper()[:24]
        if token:
            return f"ANS-{token}-{digest[:6]}"
        return f"ANS-{digest}"

    @staticmethod
    def _build_ingest_decision_id(
        canonical_key: str,
        question: str,
        proposed_answer: str,
        conflict_ref: str,
    ) -> str:
        seed = f"{canonical_key}|{question}|{proposed_answer}|{conflict_ref}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        return f"DEC-{digest}"

    @staticmethod
    def _infer_run_id_from_translation_path(path: Path) -> str:
        parts = list(path.parts)
        for idx, part in enumerate(parts):
            if part != ".pdd_runs":
                continue
            run_idx = idx + 1
            if run_idx < len(parts):
                return str(parts[run_idx]).strip()
        return ""

    # ------------------------------------------------------------------
    # Convenience adapters for existing call sites
    # ------------------------------------------------------------------

    def resolve_signal(self, signal: Any) -> dict[str, Any] | None:
        """Resolve an ambiguity signal via the planner API wrapper."""
        context = PlanningContext(
            layer="any",
            mode=self._mode if self._mode in {"auto", "interactive"} else "auto",
            workspace_root=str(self._workspace_root),
            signal_ref=signal,
        )
        req = PlanningRequest(
            capability="RESOLVE_SIGNAL",
            context=context,
            inputs={"signal": signal},
        )
        result = self.plan(req)
        outputs = result.outputs if isinstance(result.outputs, dict) else {}
        response = outputs.get("response")
        if response is None:
            return None
        if isinstance(response, dict):
            return dict(response)
        return {"text": str(response)}

    def plan_from_gaps(
        self,
        context: PlanningContext,
    ) -> list[dict[str, Any]]:
        """Generate plan items from EvidenceBundle-backed gaps through planner lifecycle."""
        bundle = context.bundle_ref
        gaps: list[dict[str, Any]] = []
        if isinstance(bundle, dict):
            gaps_payload = bundle.get("gaps")
            if isinstance(gaps_payload, dict):
                raw = gaps_payload.get("open_gaps", [])
                if isinstance(raw, list):
                    gaps = [item for item in raw if isinstance(item, dict)]
        else:
            bundle_gaps = getattr(bundle, "gaps", None)
            raw = getattr(bundle_gaps, "open_gaps", [])
            if isinstance(raw, list):
                gaps = [item for item in raw if isinstance(item, dict)]

        req = PlanningRequest(
            capability="PLAN",
            context=context,
            inputs={"gaps": gaps},
        )
        result = self.plan(req)
        outputs = result.outputs if isinstance(result.outputs, dict) else {}
        plan_items = outputs.get("plan_items", outputs.get("intentions", []))
        if not isinstance(plan_items, list):
            return []
        return [item for item in plan_items if isinstance(item, dict)]

    @staticmethod
    def _extract_under_spec_events(context: PlanningContext) -> list[dict[str, Any]]:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        events = metadata.get("under_spec_events", [])
        if isinstance(events, list):
            normalized = [row for row in events if isinstance(row, dict)]
            if normalized:
                return normalized

        bundle = context.bundle_ref
        if isinstance(bundle, dict):
            impl = bundle.get("implementation")
            if isinstance(impl, dict):
                impl_events = impl.get("under_spec_events", [])
                if isinstance(impl_events, list):
                    return [row for row in impl_events if isinstance(row, dict)]
            direct_events = bundle.get("under_spec_events", [])
            if isinstance(direct_events, list):
                return [row for row in direct_events if isinstance(row, dict)]

        implementation = getattr(bundle, "implementation", None)
        bundle_events = getattr(implementation, "under_spec_events", [])
        if isinstance(bundle_events, list):
            return [row for row in bundle_events if isinstance(row, dict)]
        return []

    def resolve_under_spec(self, context: PlanningContext) -> dict[str, Any]:
        """Resolve or block under-spec events.

        Returns an explicit contract with:
        ``blocked``, ``constraints``, ``questions``, ``resolved``,
        ``routing`` (work items), ``monitors``, and ``expansions``.
        """
        events = self._extract_under_spec_events(context)
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

    def emits_constraint_saved_notifications(self) -> bool:
        """Whether planner constraint persistence emits runtime wake notifications."""
        capability = getattr(
            self._constraints_store_tool, "emits_constraint_saved_notifications", None
        )
        if callable(capability):
            try:
                return bool(capability())
            except Exception:
                logger.warning(
                    "Constraint notification capability probe failed; assuming disabled",
                    exc_info=True,
                )
                return False
        if isinstance(capability, bool):
            return capability
        return False

    def persist_under_spec_constraints(
        self,
        *,
        run_id: str,
        layer: str,
        slice_id: str,
        constraints: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist validated under-spec constraints through Planner authority."""
        from spec_manager.planner.constraints.types import ConstraintFact

        facts: list[ConstraintFact] = []
        canonical_keys: list[str] = []
        constraint_ids: list[str] = []
        target_slice = str(slice_id or "__system__").strip() or "__system__"
        layer_token = str(layer or "any").strip().lower()
        default_layers = [layer_token.upper()] if layer_token in {"l1", "l2", "l3"} else []
        run_token = str(run_id or "").strip()
        authoritative_facts = self._constraints_store_tool.load_merged(target_slice)

        existing_active_by_canonical: dict[str, list[ConstraintFact]] = {}
        existing_active_by_question: dict[str, list[ConstraintFact]] = {}
        for existing_fact in authoritative_facts:
            if str(getattr(existing_fact, "status", "ACTIVE")).strip().upper() != "ACTIVE":
                continue
            existing_canonical_key = self._extract_trace_tag(
                getattr(existing_fact, "trace", []), "canonical_key"
            )
            existing_canonical_norm = self._normalize_for_compare(existing_canonical_key)
            if existing_canonical_norm:
                existing_active_by_canonical.setdefault(existing_canonical_norm, []).append(
                    existing_fact
                )
            existing_question_norm = self._normalize_for_compare(
                getattr(existing_fact, "question", "")
            )
            if existing_question_norm:
                existing_active_by_question.setdefault(existing_question_norm, []).append(
                    existing_fact
                )

        for row in constraints:
            if not isinstance(row, dict):
                continue
            constraint_id = str(row.get("constraint_id", "")).strip()
            question = str(row.get("question", "")).strip()
            answer = str(row.get("answer", "")).strip()
            if not (constraint_id and question and answer):
                continue
            raw_trace = row.get("trace", [])
            trace = [str(item).strip() for item in raw_trace if str(item).strip()]
            canonical_key = self._extract_trace_tag(trace, "canonical_key")
            if not canonical_key:
                canonical_key = f"underspec.{constraint_id}"
                trace.append(f"canonical_key={canonical_key}")
            canonical_key_norm = self._normalize_for_compare(canonical_key)
            question_norm = self._normalize_for_compare(question)
            confidence = self._clamp_confidence(row.get("confidence", 0.7))
            authority_required = str(row.get("authority_required", "planner_ok")).strip().lower()
            if authority_required == "user_required":
                authority_required = "human_required"
            if authority_required not in {"planner_ok", "human_required"}:
                authority_required = "planner_ok"
            if authority_required != "planner_ok":
                continue
            dimension = str(row.get("dimension", "software")).strip().lower()
            if dimension not in _VALID_UNDER_SPEC_DIMENSIONS:
                dimension = "software"
            decision_type = str(row.get("decision_type", "performance")).strip().lower()
            if decision_type not in _VALID_UNDER_SPEC_DECISION_TYPES:
                decision_type = "performance"
            status = str(row.get("status", "ACTIVE")).strip().upper() or "ACTIVE"
            if status not in {"ACTIVE", "SUPERSEDED"}:
                status = "ACTIVE"
            raw_supersedes = row.get("supersedes", [])
            if isinstance(raw_supersedes, list):
                supersedes = [str(item).strip() for item in raw_supersedes if str(item).strip()]
            elif isinstance(raw_supersedes, str):
                supersedes = [raw_supersedes.strip()] if raw_supersedes.strip() else []
            else:
                supersedes = []

            if not supersedes:
                prior_facts: list[ConstraintFact] = []
                if canonical_key_norm:
                    prior_facts = list(existing_active_by_canonical.get(canonical_key_norm, []))
                if not prior_facts and question_norm:
                    prior_facts = list(existing_active_by_question.get(question_norm, []))
                supersedes = [
                    str(existing.constraint_id).strip()
                    for existing in prior_facts
                    if str(existing.constraint_id).strip()
                    and str(existing.constraint_id).strip() != constraint_id
                ]
            supersedes = self._dedupe_preserve(supersedes)

            source = self._coerce_under_spec_constraint_source(row.get("source", "research"))
            applies_to_layers = self._normalize_constraint_layers(
                row.get("applies_to_layers", default_layers),
                fallback=default_layers,
            )
            fact = ConstraintFact(
                constraint_id=constraint_id,
                question=question,
                answer=answer,
                source=source,
                confidence=confidence,
                validated=bool(row.get("validated", True)),
                dimension=dimension,
                authority_required=authority_required,
                decision_type=decision_type,
                scope=str(row.get("scope", "intra:LIB") or "intra:LIB"),
                applies_to_layers=applies_to_layers,
                status=status,
                supersedes=supersedes,
                trace=[
                    *trace,
                    "ingest_capability=UNDER_SPEC",
                    f"layer={layer_token}",
                    f"slice_id={target_slice}",
                ],
            )
            facts.append(fact)
            constraint_ids.append(constraint_id)
            canonical_keys.append(canonical_key)

        if not facts:
            return {"constraints_path": "", "constraint_ids": [], "canonical_keys": []}

        context_token = ConstraintsTool.push_planner_update_context(
            run_id=run_token,
            layer=layer_token,
            capability="UNDER_SPEC",
        )
        try:
            saved_path = self._constraints_store_tool.save_facts(target_slice, facts)
        finally:
            ConstraintsTool.pop_planner_update_context(context_token)

        return {
            "constraints_path": str(saved_path),
            "constraint_ids": self._dedupe_preserve(constraint_ids),
            "canonical_keys": self._dedupe_preserve(canonical_keys),
        }

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
        questions = self._normalize_under_spec_questions(questions_raw)
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

    @staticmethod
    def _normalize_under_spec_questions(raw_questions: Any) -> list[dict[str, Any]]:
        """Normalize blocked-question payloads without flattening away decision structure."""
        if not isinstance(raw_questions, list):
            return []

        questions: list[dict[str, Any]] = []
        for raw_question in raw_questions:
            if isinstance(raw_question, str):
                text = raw_question.strip()
                if not text:
                    continue
                questions.append(
                    {
                        "question": text,
                        "options": [],
                        "evidence_needed": [],
                    }
                )
                continue

            if not isinstance(raw_question, dict):
                continue

            text = str(
                raw_question.get("question")
                or raw_question.get("text")
                or raw_question.get("prompt")
                or ""
            ).strip()
            if not text:
                continue

            options_raw = raw_question.get("options", raw_question.get("choices", []))
            options = (
                [str(option).strip() for option in options_raw if str(option).strip()]
                if isinstance(options_raw, list)
                else []
            )

            evidence_raw = raw_question.get(
                "evidence_needed",
                raw_question.get("evidence_refs", raw_question.get("evidence", [])),
            )
            evidence_needed = (
                [str(ref).strip() for ref in evidence_raw if str(ref).strip()]
                if isinstance(evidence_raw, list)
                else []
            )

            normalized: dict[str, Any] = {
                "question": text,
                "options": options,
                "evidence_needed": evidence_needed,
            }
            for key in (
                "event_id",
                "decision_id",
                "reason",
                "authority_required",
                "dimension",
                "decision_type",
                "needed_for",
            ):
                if key in raw_question:
                    normalized[key] = raw_question[key]

            questions.append(normalized)

        return questions

    @staticmethod
    def _coerce_under_spec_constraint_source(
        value: Any,
    ) -> Literal["user", "research", "steering", "existing"]:
        source = str(value or "").strip().lower()
        if source in {"user", "steering", "existing"}:
            return source
        return "research"

    @staticmethod
    def _normalize_constraint_layers(value: Any, *, fallback: list[str]) -> list[str]:
        raw_values: list[str]
        if isinstance(value, str):
            raw_values = [value]
        elif isinstance(value, list):
            raw_values = [str(item) for item in value]
        else:
            raw_values = []

        normalized: list[str] = []
        for raw in raw_values:
            for token in raw.replace("|", ",").split(","):
                layer = token.strip().upper()
                if layer in {"L1", "L2", "L3"} and layer not in normalized:
                    normalized.append(layer)
        if normalized:
            return normalized

        fallback_layers: list[str] = []
        for raw in fallback:
            layer = str(raw).strip().upper()
            if layer in {"L1", "L2", "L3"} and layer not in fallback_layers:
                fallback_layers.append(layer)
        return fallback_layers

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
            event_proposal_models = self._dedupe_preserve(
                [
                    *self._collect_models_from_value(event.get("proposal_models")),
                    *self._collect_models_from_value(
                        event.get("metadata", {}).get("proposal_models")
                        if isinstance(event.get("metadata"), dict)
                        else []
                    ),
                ]
            )
            triage_metadata: dict[str, Any] = {"source": "UNDER_SPEC_EXPANSION"}
            if event_proposal_models:
                triage_metadata["proposal_models"] = event_proposal_models
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
                metadata=triage_metadata,
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
            if not proposal_models:
                proposal_models = list(event_proposal_models)
            triage_req = PlanningRequest(
                capability="TRIAGE_SIGNAL",
                context=triage_ctx,
                inputs={
                    "signal": signal,
                    "proposal_models": proposal_models,
                },
            )
            proposal_route = self._model_router.resolve(
                triage_req,
                prefer_models=proposal_models,
                requires_external_facts=self._requires_external_facts(triage_req),
                high_risk=False,
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
                metadata["model_route"] = proposal_route.to_dict()
                metadata["consistency_passed"] = consistency_passed
                payload["metadata"] = metadata
                payload["model_route"] = proposal_route.to_dict()
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
                    "model_route": proposal_route.to_dict(),
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
        spec_refs = GeneralPlanner._extract_spec_refs_from_event(
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


# Public API alias defined by the planner contract.
Planner = GeneralPlanner


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
    model_route: dict[str, Any] | None = None,
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
        "model_route": _safe_deepcopy(model_route or {}),
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
