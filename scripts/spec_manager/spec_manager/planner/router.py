"""Layer, capability, and work-type model routing for the planner module.

LayerRouter selects the correct per-layer planner (L1/L2/L3) based on
the request's layer field. CapabilityRouter dispatches within a layer
planner by capability and resolves an orthogonal model route by work type.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Re-use the type aliases from the api module at runtime; we define the
# same literals here to avoid a circular import (api imports router).
Layer = Literal["l1", "l2", "l3", "any"]
PlannerWorkType = Literal[
    "integration_analysis",
    "plan_synthesis",
    "under_spec_resolution",
    "web_research_execution",
    "research_query_generation",
    "plan_lint",
    "normalization",
]

_DEFAULT_CAPABILITY_WORK_TYPES: dict[str, PlannerWorkType] = {
    "RESOLVE_SIGNAL": "under_spec_resolution",
    "GAP": "integration_analysis",
    "PLAN": "plan_synthesis",
    "UNDER_SPEC": "under_spec_resolution",
    "INTEGRATION_ANALYSIS": "integration_analysis",
    "TRIAGE_SIGNAL": "research_query_generation",
    "INGEST_USER_ANSWER": "normalization",
}

_DEFAULT_WORK_TYPE_MODELS: dict[PlannerWorkType, tuple[str, str]] = {
    "integration_analysis": ("opus", "gpt-5.2-xhigh"),
    "plan_synthesis": ("gpt-5.2-xhigh", "opus"),
    "under_spec_resolution": ("opus", "gpt-5.2-xhigh"),
    "web_research_execution": ("glm-4.7", "gpt-5.2-xhigh"),
    "research_query_generation": ("opus", ""),
    "plan_lint": ("opus", ""),
    "normalization": ("gpt-5.2-xhigh", ""),
}


@dataclass(frozen=True)
class ModelRouteDecision:
    """Resolved model route for a request's work type."""

    work_type: PlannerWorkType
    primary_model: str
    secondary_model: str = ""
    requires_critique_gate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_type": self.work_type,
            "primary_model": self.primary_model,
            "secondary_model": self.secondary_model,
            "requires_critique_gate": self.requires_critique_gate,
        }


# ---------------------------------------------------------------------------
# LayerPlanner protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LayerPlanner(Protocol):
    """Protocol that every per-layer planner must satisfy.

    Each layer planner is composed from three collaborators:
    ``discovery_router``, ``skeleton_planner``, and
    ``layer_research_adapter``.
    """

    layer: Layer
    discovery_router: Any
    skeleton_planner: Any
    layer_research_adapter: Any

    def bind_trace(self, trace: Any | None) -> None:
        """Bind per-request trace context for layer-level instrumentation."""
        ...

    def discover(self, ctx: Any) -> dict[str, Any]:
        """Gather layer-specific discovery data for the slice."""
        ...

    def build_plan(
        self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        """Synthesize plan intentions from gaps + discovery."""
        ...

    def resolve_under_spec(
        self, ctx: Any, events: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve or block under-spec events."""
        ...

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        """Resolve an ambiguity signal.  May return None for no-op."""
        ...

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        """Triage a coordination signal — search work items, classify, route."""
        ...


# ---------------------------------------------------------------------------
# Stub layer planners (NOOP — filled in by layer modules later)
# ---------------------------------------------------------------------------


class _StubPlanner:
    """Placeholder layer planner that returns NOOP for every operation."""

    def __init__(self, layer: Layer) -> None:
        self.layer: Layer = layer
        self.discovery_router = _StubDiscoveryRouter()
        self.skeleton_planner = _StubSkeletonPlanner()
        self.layer_research_adapter = _StubResearchAdapter()
        self._trace: Any | None = None

    def bind_trace(self, trace: Any | None) -> None:
        self._trace = trace

    def discover(self, ctx: Any) -> dict[str, Any]:
        return self.discovery_router.discover(ctx)

    def build_plan(
        self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        return self.skeleton_planner.build_plan(ctx, gaps, discovery)

    def resolve_under_spec(
        self, ctx: Any, events: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        return self.layer_research_adapter.resolve_under_spec(ctx, events, discovery)

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        return self.layer_research_adapter.resolve_signal(ctx, signal)

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        return {"action": "NOOP", "monitors": []}


class _StubDiscoveryRouter:
    def discover(self, ctx: Any) -> dict[str, Any]:
        return {}


class _StubSkeletonPlanner:
    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        return {"intentions": []}


class _StubResearchAdapter:
    def resolve_under_spec(
        self,
        ctx: Any,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        return {"blocked": False, "constraints": {}}

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        return None


# ---------------------------------------------------------------------------
# LayerRouter
# ---------------------------------------------------------------------------


class LayerRouter:
    """Routes planning requests to the appropriate layer planner.

    Each layer (l1/l2/l3) has a registered ``LayerPlanner``.  Requesting
    ``"any"`` returns the L1 planner as the default.
    """

    def __init__(self) -> None:
        self._planners: dict[Layer, LayerPlanner] = {
            "l1": _StubPlanner("l1"),
            "l2": _StubPlanner("l2"),
            "l3": _StubPlanner("l3"),
        }

    def register(self, layer: Layer, planner: LayerPlanner) -> None:
        """Replace the stub planner for *layer* with a real implementation."""
        if layer == "any":
            raise ValueError("Cannot register a planner for 'any'; use a concrete layer.")
        self._planners[layer] = planner

    def select(self, layer: Layer) -> LayerPlanner:
        """Return the planner for *layer*.  ``"any"`` resolves to L1."""
        if layer == "any":
            return self._planners["l1"]
        planner = self._planners.get(layer)
        if planner is None:
            raise ValueError(f"No planner registered for layer {layer!r}")
        return planner


# ---------------------------------------------------------------------------
# CapabilityRouter
# ---------------------------------------------------------------------------


class CapabilityRouter:
    """Routes within a layer planner based on capability and work type."""

    def __init__(self, *, default_model_id: str = "") -> None:
        self._default_model_id = str(default_model_id).strip()

    def resolve_model_route(
        self,
        req: Any,
        *,
        prefer_models: list[str] | None = None,
        requires_external_facts: bool = False,
        high_risk: bool = False,
    ) -> ModelRouteDecision:
        """Resolve primary/secondary model selection for *req*."""
        work_type = self._resolve_work_type(req, requires_external_facts=requires_external_facts)
        default_primary, default_secondary = _DEFAULT_WORK_TYPE_MODELS[work_type]
        preferred = self._normalize_models(prefer_models)

        primary = preferred[0] if preferred else default_primary
        secondary = preferred[1] if len(preferred) > 1 else default_secondary
        if not primary:
            primary = self._default_model_id
        if not high_risk:
            secondary = ""

        return ModelRouteDecision(
            work_type=work_type,
            primary_model=primary,
            secondary_model=secondary,
            requires_critique_gate=bool(secondary),
        )

    def route(
        self,
        planner: LayerPlanner,
        req: Any,
        *,
        model_route: ModelRouteDecision | None = None,
    ) -> Any:
        """Dispatch *req* to the correct method on *planner*.

        Returns a ``PlanningResult`` (imported lazily to avoid circular deps).
        """
        # Lazy import to avoid circular reference (api -> router -> api).
        from spec_manager.planner.api import PlanningResult

        resolved_model_route = model_route or self.resolve_model_route(req)
        self._bind_model_route_context(req, resolved_model_route)

        capability = req.capability
        ctx = req.context
        inputs = req.inputs

        if capability == "RESOLVE_SIGNAL":
            signal = inputs.get("signal")
            response = planner.resolve_signal(ctx, signal)
            if response is None:
                return PlanningResult(status="NOOP", outputs={})
            return PlanningResult(status="OK", outputs={"response": response})

        if capability == "GAP":
            discovery = planner.discover(ctx)
            raw_gaps = inputs.get("raw_gaps", [])
            normalized_raw_gaps = (
                [dict(gap) for gap in raw_gaps if isinstance(gap, dict)]
                if isinstance(raw_gaps, list)
                else []
            )

            deduped_gaps: list[dict[str, Any]] = []
            seen_fingerprints: set[str] = set()
            for gap in normalized_raw_gaps:
                fingerprint = json.dumps(
                    {
                        "kind": str(gap.get("kind", "")).strip(),
                        "file": str(gap.get("file", "")).strip(),
                        "component_id": str(gap.get("component_id", "")).strip(),
                        "anchor": str(gap.get("anchor", "")).strip(),
                        "description": str(gap.get("description", "")).strip(),
                    },
                    sort_keys=True,
                )
                if fingerprint in seen_fingerprints:
                    continue
                seen_fingerprints.add(fingerprint)
                deduped_gaps.append(gap)

            severity_order = {"BLOCKER": 0, "MAJOR": 1, "MINOR": 2}
            prioritized_gaps = sorted(
                deduped_gaps,
                key=lambda gap: (
                    severity_order.get(str(gap.get("severity", "MAJOR")).strip().upper(), 1),
                    str(gap.get("file", "")).strip(),
                    str(gap.get("description", "")).strip(),
                ),
            )

            integration_notes: list[dict[str, Any]] = []
            decision_requirements: list[dict[str, Any]] = []
            for index, gap in enumerate(prioritized_gaps, start=1):
                component_id = str(gap.get("component_id", "")).strip()
                file_path = str(gap.get("file", "")).strip()
                anchor = str(gap.get("anchor", "")).strip()
                integration_notes.append(
                    {
                        "gap_id": str(gap.get("gap_id", "")) or f"gap_{index}",
                        "implicated_components": [component_id] if component_id else [],
                        "implicated_files": [file_path] if file_path else [],
                        "anchor": anchor,
                    }
                )

                embedded_requirements = gap.get("decision_requirements", [])
                if isinstance(embedded_requirements, list):
                    for requirement in embedded_requirements:
                        if isinstance(requirement, dict):
                            decision_requirements.append(requirement)

                question = str(gap.get("question", "")).strip()
                options_raw = gap.get("options", [])
                options = (
                    [str(item).strip() for item in options_raw if str(item).strip()]
                    if isinstance(options_raw, list)
                    else []
                )
                if question and options:
                    decision_requirements.append(
                        {
                            "decision_id": str(gap.get("decision_id", "")).strip()
                            or f"GAP-{index}",
                            "question": question,
                            "options": options,
                            "needed_for": str(gap.get("file", "")).strip(),
                            "reason": "gap_requires_architecture_decision",
                        }
                    )

            return PlanningResult(
                status="OK",
                outputs={
                    "discovery": discovery,
                    "gaps": prioritized_gaps,
                    "clustered_gaps": deduped_gaps,
                    "prioritized_gaps": prioritized_gaps,
                    "integration_notes": integration_notes,
                    "decision_requirements": decision_requirements,
                },
            )

        if capability == "PLAN":
            gaps = inputs.get("gaps", [])
            gap_analysis = inputs.get("gap_analysis", {})
            prior_artifacts = inputs.get("prior_artifacts", {})
            metadata = getattr(ctx, "metadata", {}) if hasattr(ctx, "metadata") else {}
            metadata = dict(metadata) if isinstance(metadata, dict) else {}
            if isinstance(gap_analysis, dict) and gap_analysis:
                metadata["gap_analysis"] = dict(gap_analysis)
            if isinstance(prior_artifacts, dict) and prior_artifacts:
                metadata["prior_artifacts"] = dict(prior_artifacts)
            if hasattr(ctx, "metadata"):
                ctx.metadata = metadata
            discovery = planner.discover(ctx)
            plan = planner.build_plan(ctx, gaps, discovery)
            outputs: dict[str, Any] = {"intentions": plan.get("intentions", [])}
            for key, value in plan.items():
                if key == "intentions":
                    continue
                outputs[key] = value
            if "plan_artifacts" not in outputs:
                outputs["plan_artifacts"] = {
                    key: value for key, value in outputs.items() if key != "intentions"
                }
            return PlanningResult(status="OK", outputs=outputs)

        if capability == "UNDER_SPEC":
            events = inputs.get("events", [])
            discovery = planner.discover(ctx)
            result = planner.resolve_under_spec(ctx, events, discovery)
            blocked = result.get("blocked", False)
            status = "BLOCKED" if blocked else "OK"
            return PlanningResult(status=status, outputs=result)

        if capability == "INTEGRATION_ANALYSIS":
            discovery = planner.discover(ctx)
            return PlanningResult(status="OK", outputs={"discovery": discovery})

        if capability == "TRIAGE_SIGNAL":
            signal = inputs.get("signal", {})
            triage_result = planner.triage_signal(ctx, signal)
            action = str(triage_result.get("action", "NOOP")).strip().upper()
            if action == "NOOP":
                status = "NOOP"
            elif action == "WAKE_IMMEDIATELY":
                status = "OK"
            else:
                status = "WAITING"
            return PlanningResult(status=status, outputs=triage_result)

        if capability == "INGEST_USER_ANSWER":
            # Normally handled in GeneralPlanner.plan() before reaching the router.
            # If reached here, return ERROR since it requires root-planner state.
            return PlanningResult(
                status="ERROR",
                error="INGEST_USER_ANSWER must be handled by GeneralPlanner, not LayerPlanner",
            )

        return PlanningResult(
            status="ERROR",
            error=f"Unknown capability: {capability!r}",
        )

    @staticmethod
    def _normalize_models(models: list[str] | None) -> list[str]:
        if not models:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for model in models:
            token = str(model).strip()
            if not token or token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized

    def _resolve_work_type(
        self,
        req: Any,
        *,
        requires_external_facts: bool,
    ) -> PlannerWorkType:
        capability = str(getattr(req, "capability", "")).strip().upper()
        inputs = getattr(req, "inputs", {})
        if not isinstance(inputs, dict):
            inputs = {}
        if capability == "PLAN" and (
            bool(inputs.get("plan_lint")) or bool(inputs.get("lint_only"))
        ):
            return "plan_lint"
        if requires_external_facts and capability in {
            "UNDER_SPEC",
            "RESOLVE_SIGNAL",
            "TRIAGE_SIGNAL",
        }:
            return "web_research_execution"
        return _DEFAULT_CAPABILITY_WORK_TYPES.get(capability, "integration_analysis")

    @staticmethod
    def _bind_model_route_context(req: Any, model_route: ModelRouteDecision) -> None:
        context = getattr(req, "context", None)
        if context is None:
            return
        metadata = getattr(context, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            context.metadata = metadata
        metadata["model_route"] = model_route.to_dict()
        metadata["planner_work_type"] = model_route.work_type
        metadata["primary_model"] = model_route.primary_model
        if model_route.secondary_model:
            metadata["secondary_model"] = model_route.secondary_model
        elif "secondary_model" in metadata:
            metadata.pop("secondary_model", None)
