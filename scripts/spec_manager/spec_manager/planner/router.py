"""Layer routing, model routing, and NextAction planning for planner execution.

LayerRouter selects per-layer planners (L1/L2/L3). ModelRouter resolves
work-type model decisions. CapabilityRouter expresses capability execution as
``NextAction`` steps; execution is handled by GeneralPlanner.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from spec_manager.planner.jit.actions import ActionType, NextAction
from spec_manager.planner.jit.state_machine import PlanPhase
from spec_manager.planner.trace import ModelCallRecord, ToolCallRecord, canonical_json, content_hash

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


@dataclass(frozen=True)
class ReviewPack:
    """Declarative review configuration for critique/validation passes."""

    name: str
    agents: list[dict[str, Any]]
    merge_strategy: str
    acceptance_checks: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "agents": [dict(agent) for agent in self.agents],
            "merge_strategy": self.merge_strategy,
            "acceptance_checks": list(self.acceptance_checks),
        }


class IntegrationAnalyzer:
    """Compute integration graph diffs and risk profiles for planner requests."""

    def analyze(self, *, req: Any, discovery: dict[str, Any]) -> dict[str, Any]:
        baseline_graph = self._extract_graph(discovery)
        proposed_graph = self._extract_proposed_graph(req, baseline_graph)

        baseline_nodes = self._node_ids(baseline_graph)
        proposed_nodes = self._node_ids(proposed_graph)
        baseline_edges = self._edge_ids(baseline_graph)
        proposed_edges = self._edge_ids(proposed_graph)

        added_nodes = sorted(proposed_nodes - baseline_nodes)
        removed_nodes = sorted(baseline_nodes - proposed_nodes)
        added_edges = sorted(proposed_edges - baseline_edges)
        removed_edges = sorted(baseline_edges - proposed_edges)

        changed_targets = set(added_nodes + removed_nodes)
        changed_targets.update(self._collect_changed_targets(req))

        impacted_nodes = self._estimate_impacted_nodes(
            graph=proposed_graph,
            changed_nodes=changed_targets,
        )
        impacted_files = sorted(
            {
                str(node.get("file", "")).strip()
                for node in proposed_graph.get("nodes", [])
                if isinstance(node, dict)
                and str(node.get("id", "")).strip() in impacted_nodes
                and str(node.get("file", "")).strip()
            }
        )

        blast_radius = len(impacted_nodes)
        if blast_radius >= 10:
            risk_level = "high"
        elif blast_radius >= 4:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "integration_diff": {
                "added_nodes": added_nodes,
                "removed_nodes": removed_nodes,
                "added_edges": [self._edge_tuple_to_dict(edge) for edge in added_edges],
                "removed_edges": [self._edge_tuple_to_dict(edge) for edge in removed_edges],
            },
            "risk_profile": {
                "blast_radius": blast_radius,
                "risk_level": risk_level,
                "impacted_nodes": sorted(impacted_nodes),
                "impacted_files": impacted_files,
                "rationale": (
                    f"{len(changed_targets)} changed targets affect {blast_radius} reachable nodes"
                ),
            },
        }

    @staticmethod
    def _extract_graph(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"nodes": [], "edges": []}
        if isinstance(payload.get("nodes"), list) and isinstance(payload.get("edges"), list):
            return {
                "nodes": [row for row in payload.get("nodes", []) if isinstance(row, dict)],
                "edges": [row for row in payload.get("edges", []) if isinstance(row, dict)],
            }
        quality_graph = payload.get("quality_graph")
        if isinstance(quality_graph, dict):
            return {
                "nodes": [row for row in quality_graph.get("nodes", []) if isinstance(row, dict)],
                "edges": [row for row in quality_graph.get("edges", []) if isinstance(row, dict)],
            }
        return {"nodes": [], "edges": []}

    def _extract_proposed_graph(self, req: Any, baseline_graph: dict[str, Any]) -> dict[str, Any]:
        inputs = getattr(req, "inputs", {})
        if not isinstance(inputs, dict):
            return baseline_graph
        for key in (
            "proposed_graph",
            "integration_graph",
            "topology",
            "integration_analysis",
        ):
            payload = inputs.get(key)
            if isinstance(payload, dict):
                graph = self._extract_graph(payload)
                if graph["nodes"] or graph["edges"]:
                    return graph
        return baseline_graph

    @staticmethod
    def _node_ids(graph: dict[str, Any]) -> set[str]:
        node_ids: set[str] = set()
        for node in graph.get("nodes", []):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", "")).strip()
            if node_id:
                node_ids.add(node_id)
        return node_ids

    @staticmethod
    def _edge_ids(graph: dict[str, Any]) -> set[tuple[str, str, str]]:
        edge_ids: set[tuple[str, str, str]] = set()
        for edge in graph.get("edges", []):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            edge_type = (
                str(edge.get("type", edge.get("kind", "depends_on"))).strip() or "depends_on"
            )
            if source and target:
                edge_ids.add((source, target, edge_type))
        return edge_ids

    @staticmethod
    def _edge_tuple_to_dict(edge: tuple[str, str, str]) -> dict[str, str]:
        return {"source": edge[0], "target": edge[1], "type": edge[2]}

    @staticmethod
    def _collect_changed_targets(req: Any) -> list[str]:
        inputs = getattr(req, "inputs", {})
        if not isinstance(inputs, dict):
            return []
        changed: list[str] = []
        for key in ("changed_nodes", "impacted_nodes"):
            rows = inputs.get(key)
            if isinstance(rows, list):
                for row in rows:
                    token = str(row).strip()
                    if token:
                        changed.append(token)
        for key in ("gaps", "raw_gaps"):
            rows = inputs.get(key)
            if not isinstance(rows, list):
                continue
            for gap in rows:
                if not isinstance(gap, dict):
                    continue
                for attr in ("component_id", "target", "file"):
                    token = str(gap.get(attr, "")).strip()
                    if token:
                        changed.append(token)
        return changed

    @staticmethod
    def _estimate_impacted_nodes(
        *,
        graph: dict[str, Any],
        changed_nodes: set[str],
    ) -> set[str]:
        adjacency: dict[str, set[str]] = {}
        for edge in graph.get("edges", []):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            if not source or not target:
                continue
            adjacency.setdefault(source, set()).add(target)

        visited: set[str] = set(changed_nodes)
        frontier = list(changed_nodes)
        while frontier:
            current = frontier.pop(0)
            for nxt in adjacency.get(current, set()):
                if nxt in visited:
                    continue
                visited.add(nxt)
                frontier.append(nxt)
        return visited


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

    def extract_skeleton(self, ctx: Any, discovery: dict[str, Any]) -> dict[str, Any]:
        """Return layer-typed skeleton graph payload for planner lifecycle steps."""
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
# LayerRouter
# ---------------------------------------------------------------------------


class LayerRouter:
    """Routes planning requests to the appropriate layer planner.

    Each layer (l1/l2/l3) has a registered ``LayerPlanner``.  Requesting
    ``"any"`` returns the L1 planner as the default.
    """

    def __init__(self) -> None:
        self._planners: dict[Layer, LayerPlanner] = {}

    def register(self, layer: Layer, planner: LayerPlanner) -> None:
        """Register a planner for *layer*."""
        if layer == "any":
            raise ValueError("Cannot register a planner for 'any'; use a concrete layer.")
        self._planners[layer] = planner

    def select(self, layer: Layer) -> LayerPlanner:
        """Return the planner for *layer*.  ``"any"`` resolves to L1."""
        if layer == "any":
            planner = self._planners.get("l1")
            if planner is None:
                raise ValueError("No planner registered for layer 'l1'")
            return planner
        planner = self._planners.get(layer)
        if planner is None:
            raise ValueError(f"No planner registered for layer {layer!r}")
        return planner


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """Resolve model-selection decisions independently from capability routing."""

    def __init__(self, *, default_model_id: str = "") -> None:
        self._default_model_id = str(default_model_id).strip()

    def resolve(
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

        decision = ModelRouteDecision(
            work_type=work_type,
            primary_model=primary,
            secondary_model=secondary,
            requires_critique_gate=bool(secondary),
        )
        self.bind_context(req, decision)
        return decision

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
    def bind_context(req: Any, model_route: ModelRouteDecision) -> None:
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


# ---------------------------------------------------------------------------
# CapabilityRouter
# ---------------------------------------------------------------------------


class CapabilityRouter:
    """Express capability flow as NextAction steps for executor consumption."""

    def __init__(self, *, integration_analyzer: IntegrationAnalyzer | None = None) -> None:
        self._integration_analyzer = integration_analyzer or IntegrationAnalyzer()
        self._trace: Any | None = None

    def bind_trace(self, trace: Any | None) -> None:
        self._trace = trace

    def plan_actions(
        self,
        req: Any,
        *,
        requires_external_facts: bool = False,
    ) -> list[NextAction]:
        capability = str(getattr(req, "capability", "")).strip().upper()

        if capability == "RESOLVE_SIGNAL":
            actions: list[NextAction] = []
            if requires_external_facts:
                actions.append(
                    NextAction(
                        action=ActionType.RUN_TOOL,
                        tool="web_research",
                        inputs={"phase": PlanPhase.RESEARCH.value},
                    ),
                )
            actions.extend(
                [
                    NextAction(
                        action=ActionType.CALL_AGENT,
                        agent="resolve_signal",
                        inputs={"phase": PlanPhase.GAP_UNDERSTANDING.value},
                    ),
                    NextAction(
                        action=ActionType.CALL_AGENT,
                        agent="decide",
                        inputs={"phase": PlanPhase.DECIDE.value},
                    ),
                    NextAction(
                        action=ActionType.COMPLETE,
                        inputs={"phase": PlanPhase.VALIDATE.value},
                    ),
                ]
            )
            return actions

        if capability == "GAP":
            return [
                NextAction(
                    action=ActionType.RUN_TOOL,
                    tool="discover",
                    inputs={"phase": PlanPhase.DISCOVER.value},
                ),
                NextAction(
                    action=ActionType.CALL_AGENT,
                    agent="gap_understanding",
                    inputs={"phase": PlanPhase.GAP_UNDERSTANDING.value},
                ),
                NextAction(
                    action=ActionType.CALL_AGENT,
                    agent="decide",
                    inputs={"phase": PlanPhase.DECIDE.value},
                ),
                NextAction(
                    action=ActionType.COMPLETE,
                    inputs={"phase": PlanPhase.VALIDATE.value},
                ),
            ]

        if capability == "PLAN":
            return [
                NextAction(
                    action=ActionType.RUN_TOOL,
                    tool="discover",
                    inputs={"phase": PlanPhase.DISCOVER.value},
                ),
                NextAction(
                    action=ActionType.RUN_TOOL,
                    tool="extract_layer_skeleton",
                    inputs={"phase": PlanPhase.DISCOVER.value},
                ),
                NextAction(
                    action=ActionType.CALL_AGENT,
                    agent="decide",
                    inputs={"phase": PlanPhase.DECIDE.value},
                ),
                NextAction(
                    action=ActionType.CALL_AGENT,
                    agent="build_plan",
                    inputs={"phase": PlanPhase.DESIGN.value},
                ),
                NextAction(
                    action=ActionType.COMPLETE,
                    inputs={"phase": PlanPhase.VALIDATE.value},
                ),
            ]

        if capability == "UNDER_SPEC":
            actions = [
                NextAction(
                    action=ActionType.RUN_TOOL,
                    tool="discover",
                    inputs={"phase": PlanPhase.DISCOVER.value},
                ),
                NextAction(
                    action=ActionType.CALL_AGENT,
                    agent="resolve_under_spec",
                    inputs={"phase": PlanPhase.GAP_UNDERSTANDING.value},
                ),
            ]
            if requires_external_facts:
                actions.append(
                    NextAction(
                        action=ActionType.RUN_TOOL,
                        tool="web_research",
                        inputs={"phase": PlanPhase.RESEARCH.value},
                    )
                )
            actions.extend(
                [
                    NextAction(
                        action=ActionType.CALL_AGENT,
                        agent="decide",
                        inputs={"phase": PlanPhase.DECIDE.value},
                    ),
                    NextAction(
                        action=ActionType.USER_INPUT,
                        prompt="Planner needs user input to resolve under-spec questions.",
                        inputs={"phase": PlanPhase.VALIDATE.value},
                    ),
                    NextAction(
                        action=ActionType.COMPLETE,
                        inputs={"phase": PlanPhase.VALIDATE.value},
                    ),
                ]
            )
            return actions

        if capability == "INTEGRATION_ANALYSIS":
            return [
                NextAction(
                    action=ActionType.RUN_TOOL,
                    tool="discover",
                    inputs={"phase": PlanPhase.DISCOVER.value},
                ),
                NextAction(
                    action=ActionType.RUN_TOOL,
                    tool="integration_analyzer",
                    inputs={"phase": PlanPhase.INTEGRATION_ANALYSIS.value},
                ),
                NextAction(
                    action=ActionType.CALL_AGENT,
                    agent="decide",
                    inputs={"phase": PlanPhase.DECIDE.value},
                ),
                NextAction(
                    action=ActionType.COMPLETE,
                    inputs={"phase": PlanPhase.VALIDATE.value},
                ),
            ]

        if capability == "TRIAGE_SIGNAL":
            actions = [
                NextAction(
                    action=ActionType.CALL_AGENT,
                    agent="triage_signal",
                    inputs={
                        "phase": (
                            PlanPhase.RESEARCH.value
                            if requires_external_facts
                            else PlanPhase.GAP_UNDERSTANDING.value
                        )
                    },
                ),
                NextAction(
                    action=ActionType.CALL_AGENT,
                    agent="decide",
                    inputs={"phase": PlanPhase.DECIDE.value},
                ),
                NextAction(
                    action=ActionType.COMPLETE,
                    inputs={"phase": PlanPhase.VALIDATE.value},
                ),
            ]
            return actions

        if capability == "INGEST_USER_ANSWER":
            return [
                NextAction(
                    action=ActionType.ERROR,
                    prompt="INGEST_USER_ANSWER must be handled by GeneralPlanner",
                )
            ]

        return [
            NextAction(
                action=ActionType.ERROR,
                prompt=f"Unknown capability: {capability!r}",
            )
        ]

    def run_tool(
        self,
        *,
        planner: LayerPlanner,
        req: Any,
        tool_name: str,
        action_inputs: dict[str, Any] | None = None,
        interim: dict[str, Any],
    ) -> None:
        ctx = req.context
        started = time.perf_counter()
        output_payload: Any = None
        if tool_name == "discover":
            output_payload = planner.discover(ctx)
            interim["discovery"] = output_payload
            self._record_tool_invocation(
                req=req,
                tool_name=tool_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        if tool_name == "extract_layer_skeleton":
            discovery = self._ensure_discovery(planner=planner, ctx=ctx, interim=interim)
            output_payload = self._extract_layer_skeleton(
                planner=planner,
                ctx=ctx,
                discovery=discovery,
            )
            interim["layer_skeleton"] = output_payload
            self._record_tool_invocation(
                req=req,
                tool_name=tool_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        if tool_name == "integration_analyzer":
            discovery = self._ensure_discovery(planner=planner, ctx=ctx, interim=interim)
            output_payload = self._integration_analyzer.analyze(
                req=req,
                discovery=discovery,
            )
            interim["integration_analysis"] = output_payload
            self._record_tool_invocation(
                req=req,
                tool_name=tool_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        if tool_name == "web_research":
            interim.setdefault("research", {})
            interim["research"]["status"] = "requested"
            output_payload = {"status": "requested"}
            self._record_tool_invocation(
                req=req,
                tool_name=tool_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        raise ValueError(f"Unknown tool action: {tool_name}")

    def run_agent(
        self,
        *,
        planner: LayerPlanner,
        req: Any,
        agent_name: str,
        action_inputs: dict[str, Any] | None = None,
        interim: dict[str, Any],
    ) -> None:
        ctx = req.context
        inputs = req.inputs if isinstance(req.inputs, dict) else {}
        started = time.perf_counter()
        output_payload: Any = None

        if agent_name == "resolve_signal":
            signal = inputs.get("signal")
            output_payload = planner.resolve_signal(ctx, signal)
            interim["resolve_signal_response"] = output_payload
            self._record_agent_invocation(
                req=req,
                agent_name=agent_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        if agent_name == "gap_understanding":
            raw_gaps = inputs.get("raw_gaps", [])
            normalized_raw_gaps = (
                [dict(gap) for gap in raw_gaps if isinstance(gap, dict)]
                if isinstance(raw_gaps, list)
                else []
            )
            deduped_gaps = CapabilityRouter._dedupe_gaps(normalized_raw_gaps)
            prioritized_gaps = CapabilityRouter._prioritize_gaps(deduped_gaps)
            integration_notes, decision_requirements = CapabilityRouter._derive_gap_artifacts(
                prioritized_gaps
            )
            output_payload = {
                "gaps": prioritized_gaps,
                "clustered_gaps": deduped_gaps,
                "prioritized_gaps": prioritized_gaps,
                "integration_notes": integration_notes,
                "decision_requirements": decision_requirements,
            }
            interim["gap_outputs"] = output_payload
            self._record_agent_invocation(
                req=req,
                agent_name=agent_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        if agent_name == "decide":
            output_payload = self._build_decision_payload(req=req, interim=interim)
            interim["decision"] = output_payload
            self._record_agent_invocation(
                req=req,
                agent_name=agent_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        if agent_name == "build_plan":
            discovery = interim.get("discovery")
            if not isinstance(discovery, dict):
                discovery = planner.discover(ctx)
                interim["discovery"] = discovery
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
            output_payload = planner.build_plan(ctx, gaps, discovery)
            interim["plan"] = output_payload
            self._record_agent_invocation(
                req=req,
                agent_name=agent_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        if agent_name == "resolve_under_spec":
            events = inputs.get("events", [])
            discovery = interim.get("discovery")
            if not isinstance(discovery, dict):
                discovery = planner.discover(ctx)
                interim["discovery"] = discovery
            output_payload = planner.resolve_under_spec(ctx, events, discovery)
            interim["under_spec_result"] = output_payload
            self._record_agent_invocation(
                req=req,
                agent_name=agent_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        if agent_name == "triage_signal":
            signal = inputs.get("signal", {})
            output_payload = planner.triage_signal(ctx, signal)
            interim["triage_result"] = output_payload
            self._record_agent_invocation(
                req=req,
                agent_name=agent_name,
                action_inputs=action_inputs,
                output_payload=output_payload,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
            return

        raise ValueError(f"Unknown agent action: {agent_name}")

    @staticmethod
    def _build_decision_payload(*, req: Any, interim: dict[str, Any]) -> dict[str, Any]:
        capability = str(getattr(req, "capability", "")).strip().upper()
        decision: dict[str, Any] = {
            "capability": capability,
            "decision": "proceed",
            "decision_text": f"{capability} advanced through DECIDE phase",
        }

        under_spec = interim.get("under_spec_result")
        if isinstance(under_spec, dict):
            blocked = bool(under_spec.get("blocked", False))
            decision["decision"] = "block" if blocked else "proceed"
            decision["blocked"] = blocked
            questions = under_spec.get("questions", [])
            decision["question_count"] = len(questions) if isinstance(questions, list) else 0
            decision["decision_text"] = (
                "UNDER_SPEC requires user authority"
                if blocked
                else "UNDER_SPEC resolved with available evidence"
            )
            return decision

        triage = interim.get("triage_result")
        if isinstance(triage, dict):
            action = str(triage.get("action", "NOOP")).strip().upper() or "NOOP"
            decision["action"] = action
            decision["decision"] = (
                "wait" if action not in {"NOOP", "WAKE_IMMEDIATELY"} else "proceed"
            )
            decision["decision_text"] = f"TRIAGE_SIGNAL classified action={action}"
            return decision

        plan = interim.get("plan")
        if isinstance(plan, dict):
            intentions = plan.get("intentions", [])
            decision["intention_count"] = len(intentions) if isinstance(intentions, list) else 0
            decision["decision_text"] = "PLAN selected design strategy from available constraints"
            return decision

        gap_outputs = interim.get("gap_outputs")
        if isinstance(gap_outputs, dict):
            prioritized = gap_outputs.get("prioritized_gaps", [])
            decision["gap_count"] = len(prioritized) if isinstance(prioritized, list) else 0
            decision["decision_text"] = "GAP selected prioritized backlog for downstream planning"
            return decision

        integration = interim.get("integration_analysis")
        if isinstance(integration, dict):
            risk = integration.get("risk_profile", {})
            if isinstance(risk, dict):
                decision["risk_level"] = str(risk.get("risk_level", "low")).strip()
            decision["decision_text"] = (
                "INTEGRATION_ANALYSIS computed risk profile and change impact"
            )
            return decision

        resolved_signal = interim.get("resolve_signal_response")
        if resolved_signal is not None:
            decision["decision_text"] = "RESOLVE_SIGNAL generated steering response"

        return decision

    @staticmethod
    def _context_metadata(req: Any) -> dict[str, Any]:
        context = getattr(req, "context", None)
        metadata = getattr(context, "metadata", None)
        if isinstance(metadata, dict):
            return metadata
        return {}

    @staticmethod
    def _extract_usage_tokens(payload: Any) -> tuple[int, int]:
        if not isinstance(payload, dict):
            return 0, 0
        usage = payload.get("usage")
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

    @staticmethod
    def _to_prompt_text(
        *,
        req: Any,
        invocation_kind: str,
        invocation_name: str,
        action_inputs: dict[str, Any] | None,
    ) -> str:
        context = getattr(req, "context", None)
        payload = {
            "capability": str(getattr(req, "capability", "")).strip().upper(),
            "layer": str(getattr(context, "layer", "")).strip().lower(),
            "invocation_kind": invocation_kind,
            "invocation_name": invocation_name,
            "action_inputs": dict(action_inputs) if isinstance(action_inputs, dict) else {},
            "request_inputs": dict(getattr(req, "inputs", {}))
            if isinstance(getattr(req, "inputs", {}), dict)
            else {},
        }
        return canonical_json(payload)

    @staticmethod
    def _to_response_text(output_payload: Any) -> str:
        if isinstance(output_payload, (dict, list)):
            return canonical_json(output_payload)
        return str(output_payload)

    @staticmethod
    def _tool_output_summary(tool_name: str, output_payload: Any) -> str:
        if isinstance(output_payload, dict):
            if "status" in output_payload:
                return str(output_payload.get("status", "")).strip()
            if "blocked" in output_payload:
                return "blocked" if bool(output_payload.get("blocked")) else "ok"
            keys = sorted(output_payload.keys())
            return f"{tool_name} -> keys={','.join(keys[:8])}"
        if isinstance(output_payload, list):
            return f"{tool_name} -> list[{len(output_payload)}]"
        return str(output_payload).strip()[:240]

    def _record_agent_invocation(
        self,
        *,
        req: Any,
        agent_name: str,
        action_inputs: dict[str, Any] | None,
        output_payload: Any,
        duration_ms: float,
    ) -> None:
        trace = self._trace
        if trace is None or not hasattr(trace, "record_model_call"):
            return
        metadata = self._context_metadata(req)
        route = metadata.get("model_route") if isinstance(metadata.get("model_route"), dict) else {}
        model_id = str(route.get("primary_model", metadata.get("primary_model", ""))).strip()
        context_layer = str(getattr(getattr(req, "context", None), "layer", "")).strip().lower()
        tokens_in, tokens_out = self._extract_usage_tokens(output_payload)
        prompt_text = self._to_prompt_text(
            req=req,
            invocation_kind="agent",
            invocation_name=agent_name,
            action_inputs=action_inputs,
        )
        response_text = self._to_response_text(output_payload)
        trace.record_model_call(
            ModelCallRecord(
                agent_name=agent_name,
                model=model_id,
                duration_ms=duration_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model_params={
                    "capability": str(getattr(req, "capability", "")).strip().upper(),
                    "layer": context_layer,
                    "work_type": str(route.get("work_type", "")).strip(),
                    "secondary_model": str(route.get("secondary_model", "")).strip(),
                },
                prompt_text=prompt_text,
                response_text=response_text,
                prompt_hash=content_hash(prompt_text),
                output_hash=content_hash(response_text),
            )
        )

    def _record_tool_invocation(
        self,
        *,
        req: Any,
        tool_name: str,
        action_inputs: dict[str, Any] | None,
        output_payload: Any,
        duration_ms: float,
    ) -> None:
        trace = self._trace
        if trace is None or not hasattr(trace, "record_tool_call"):
            return
        metadata = self._context_metadata(req)
        route = metadata.get("model_route") if isinstance(metadata.get("model_route"), dict) else {}
        context_layer = str(getattr(getattr(req, "context", None), "layer", "")).strip().lower()
        invocation_payload = {
            "capability": str(getattr(req, "capability", "")).strip().upper(),
            "tool_name": tool_name,
            "action_inputs": dict(action_inputs) if isinstance(action_inputs, dict) else {},
            "request_inputs": dict(getattr(req, "inputs", {}))
            if isinstance(getattr(req, "inputs", {}), dict)
            else {},
        }
        tokens_in, tokens_out = self._extract_usage_tokens(output_payload)
        trace.record_tool_call(
            ToolCallRecord(
                tool_name=tool_name,
                inputs_hash=content_hash(canonical_json(invocation_payload)),
                output_summary=self._tool_output_summary(tool_name, output_payload),
                duration_ms=duration_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tool_params={
                    "capability": str(getattr(req, "capability", "")).strip().upper(),
                    "layer": context_layer,
                    "work_type": str(route.get("work_type", "")).strip(),
                    "model": str(
                        route.get("primary_model", metadata.get("primary_model", ""))
                    ).strip(),
                },
            )
        )

    @staticmethod
    def finalize(req: Any, interim: dict[str, Any]) -> Any:
        """Compose a PlanningResult from capability-specific interim outputs."""
        # Lazy import to avoid circular reference (api -> router -> api).
        from spec_manager.planner.api import PlanningResult

        capability = req.capability
        discovery = interim.get("discovery")
        if not isinstance(discovery, dict):
            discovery = {}

        if capability == "RESOLVE_SIGNAL":
            response = interim.get("resolve_signal_response")
            if response is None:
                return PlanningResult(status="NOOP", outputs={})
            return PlanningResult(status="OK", outputs={"response": response})

        if capability == "GAP":
            gap_outputs = interim.get("gap_outputs")
            if not isinstance(gap_outputs, dict):
                gap_outputs = {}
            return PlanningResult(
                status="OK",
                outputs={
                    "discovery": discovery,
                    "gaps": gap_outputs.get("gaps", []),
                    "clustered_gaps": gap_outputs.get("clustered_gaps", []),
                    "prioritized_gaps": gap_outputs.get("prioritized_gaps", []),
                    "integration_notes": gap_outputs.get("integration_notes", []),
                    "decision_requirements": gap_outputs.get("decision_requirements", []),
                },
            )

        if capability == "PLAN":
            plan = interim.get("plan")
            if not isinstance(plan, dict):
                plan = {}
            outputs: dict[str, Any] = {"intentions": plan.get("intentions", [])}
            for key, value in plan.items():
                if key == "intentions":
                    continue
                outputs[key] = value
            layer_skeleton = interim.get("layer_skeleton")
            if isinstance(layer_skeleton, dict):
                outputs.setdefault("layer_skeleton", layer_skeleton)
            if "plan_artifacts" not in outputs:
                outputs["plan_artifacts"] = {
                    key: value
                    for key, value in outputs.items()
                    if key not in {"intentions", "plan_artifacts"}
                }
            return PlanningResult(status="OK", outputs=outputs)

        if capability == "UNDER_SPEC":
            result = interim.get("under_spec_result")
            if not isinstance(result, dict):
                result = {}
            blocked = bool(result.get("blocked", False))
            status = "BLOCKED" if blocked else "OK"
            return PlanningResult(status=status, outputs=result)

        if capability == "INTEGRATION_ANALYSIS":
            integration_analysis = interim.get("integration_analysis")
            if not isinstance(integration_analysis, dict):
                integration_analysis = {}
            outputs = {"discovery": discovery, **integration_analysis}
            return PlanningResult(status="OK", outputs=outputs)

        if capability == "TRIAGE_SIGNAL":
            triage_result = interim.get("triage_result")
            if not isinstance(triage_result, dict):
                triage_result = {}
            action = str(triage_result.get("action", "NOOP")).strip().upper()
            if action == "NOOP":
                status = "NOOP"
            elif action == "WAKE_IMMEDIATELY":
                status = "OK"
            else:
                status = "WAITING"
            return PlanningResult(status=status, outputs=triage_result)

        if capability == "INGEST_USER_ANSWER":
            return PlanningResult(
                status="ERROR",
                error="INGEST_USER_ANSWER must be handled by GeneralPlanner, not LayerPlanner",
            )

        return PlanningResult(status="ERROR", error=f"Unknown capability: {capability!r}")

    @staticmethod
    def _ensure_discovery(
        *,
        planner: LayerPlanner,
        ctx: Any,
        interim: dict[str, Any],
    ) -> dict[str, Any]:
        discovery = interim.get("discovery")
        if isinstance(discovery, dict):
            return discovery
        discovery = planner.discover(ctx)
        interim["discovery"] = discovery
        return discovery

    @staticmethod
    def _extract_layer_skeleton(
        *,
        planner: LayerPlanner,
        ctx: Any,
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        if hasattr(planner, "extract_skeleton") and callable(planner.extract_skeleton):
            extracted = planner.extract_skeleton(ctx, discovery)
            if isinstance(extracted, dict):
                return extracted

        layer = str(getattr(ctx, "layer", "") or getattr(planner, "layer", "")).strip().lower()
        if layer == "l1":
            return {
                "code_skeleton_graph": {
                    "nodes": [row for row in discovery.get("nodes", []) if isinstance(row, dict)],
                    "edges": [row for row in discovery.get("edges", []) if isinstance(row, dict)],
                }
            }
        if layer == "l2":
            return {
                "architecture_topology_graph": {
                    "nodes": [row for row in discovery.get("nodes", []) if isinstance(row, dict)],
                    "edges": [row for row in discovery.get("edges", []) if isinstance(row, dict)],
                }
            }
        quality_graph = discovery.get("quality_graph")
        if isinstance(quality_graph, dict):
            return {
                "quality_graph": {
                    "nodes": [
                        row for row in quality_graph.get("nodes", []) if isinstance(row, dict)
                    ],
                    "edges": [
                        row for row in quality_graph.get("edges", []) if isinstance(row, dict)
                    ],
                }
            }
        return {"layer_skeleton": {"nodes": [], "edges": []}}

    @staticmethod
    def _dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped_gaps: list[dict[str, Any]] = []
        seen_fingerprints: set[str] = set()
        for gap in gaps:
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
        return deduped_gaps

    @staticmethod
    def _prioritize_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        severity_order = {"BLOCKER": 0, "MAJOR": 1, "MINOR": 2}
        return sorted(
            gaps,
            key=lambda gap: (
                severity_order.get(str(gap.get("severity", "MAJOR")).strip().upper(), 1),
                str(gap.get("file", "")).strip(),
                str(gap.get("description", "")).strip(),
            ),
        )

    @staticmethod
    def _derive_gap_artifacts(
        prioritized_gaps: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
                        "decision_id": str(gap.get("decision_id", "")).strip() or f"GAP-{index}",
                        "question": question,
                        "options": options,
                        "needed_for": str(gap.get("file", "")).strip(),
                        "reason": "gap_requires_architecture_decision",
                    }
                )
        return integration_notes, decision_requirements
