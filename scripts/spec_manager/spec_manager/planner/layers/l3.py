"""L3 (quality) layer planner.

L3 is the quality layer -- it works with changed files, quality receipts,
and diffs. Discovery builds a quality graph (nodes: file, function_span,
smell, risk; edges: contains, impacts, depends_on). Planning produces
refactoring intentions with explicit "no behavior change" criteria.

Implements the ``LayerPlanner`` protocol from
``spec_manager.planner.router``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


class _L3IntentionPlannerStrategy:
    """Construct L3 refactor intentions from quality gaps/discovery."""

    @property
    def name(self) -> str:
        return "l3_intention_planner"

    def run(self, session: Any) -> Any:
        graph = session.discovery.get("quality_graph", {})
        smell_nodes = [n for n in graph.get("nodes", []) if n.get("type") == "smell"]

        intentions: list[dict[str, Any]] = []
        for gap in session.gaps:
            gap_file = gap.get("file", "")
            gap_span = gap.get("function_span", "")
            gap_smell = gap.get("smell_type", gap.get("category", "unknown"))

            matching_smell = next(
                (
                    smell
                    for smell in smell_nodes
                    if smell.get("file") == gap_file and smell.get("function_span") == gap_span
                ),
                None,
            )
            severity = (
                matching_smell.get("severity", "info")
                if matching_smell
                else gap.get("severity", "info")
            )

            intentions.append(
                {
                    "file": gap_file,
                    "function_span": gap_span,
                    "smell_type": gap_smell,
                    "refactor_approach": gap.get(
                        "refactor_approach",
                        f"address {gap_smell} smell",
                    ),
                    "behavior_preservation_check": (
                        "No observable behavior change. "
                        "All public API signatures, return types, and "
                        "side effects remain identical."
                    ),
                    "severity": severity,
                    "source_gap": gap,
                }
            )

        session.intentions = intentions
        return session


class L3DiscoveryRouter:
    """Builds L3 quality discovery graph from slice metadata and shared tools."""

    def __init__(self, integration_tool: Any, research_adapter: L3LayerResearchAdapter) -> None:
        self._integration_tool = integration_tool
        self._research_adapter = research_adapter

    def discover(self, ctx: Any) -> dict[str, Any]:
        metadata = getattr(ctx, "metadata", {}) or {}
        changed_files: list[str] = metadata.get("changed_files", [])
        quality_receipts: list[dict[str, Any]] = metadata.get("quality_receipts", [])
        diffs: list[dict[str, Any]] = metadata.get("diffs", [])

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        for filepath in changed_files:
            nodes.append({"id": filepath, "type": "file", "path": filepath})

        for receipt in quality_receipts:
            smell_id = receipt.get("id", f"smell-{len(nodes)}")
            nodes.append(
                {
                    "id": smell_id,
                    "type": "smell",
                    "smell_type": receipt.get("smell_type", "unknown"),
                    "file": receipt.get("file", ""),
                    "function_span": receipt.get("function_span", ""),
                    "severity": receipt.get("severity", "info"),
                }
            )
            if receipt.get("file"):
                edges.append(
                    {
                        "source": receipt["file"],
                        "target": smell_id,
                        "type": "contains",
                    }
                )

        if self._integration_tool is not None and diffs:
            try:
                impact_data = self._integration_tool(diffs)
                for impact in impact_data if isinstance(impact_data, list) else []:
                    edges.append(
                        {
                            "source": impact.get("source", ""),
                            "target": impact.get("target", ""),
                            "type": "impacts",
                        }
                    )
            except Exception:
                logger.warning("L3 discover: integration_tool failed", exc_info=True)

        evidence_summary = self._research_adapter.summarize_quality_evidence(changed_files, ctx)
        return {
            "quality_graph": {
                "nodes": nodes,
                "edges": edges,
            },
            "evidence_summary": evidence_summary,
            "changed_file_count": len(changed_files),
            "smell_count": sum(1 for n in nodes if n.get("type") == "smell"),
        }


class L3SkeletonPlanner:
    """Builds L3 quality intentions using the shared strategy pipeline."""

    def __init__(self, research_adapter: L3LayerResearchAdapter) -> None:
        self._research_adapter = research_adapter

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        from spec_manager.planner.strategies.authority_strategy import AuthorityDeciderStrategy
        from spec_manager.planner.strategies.constraint_strategies import (
            CandidateEvaluatorStrategy,
            ConstraintBootstrapStrategy,
            ConstraintEnricherStrategy,
            ImpactClassifierStrategy,
            NonSoftwareChecklistStrategy,
            ProblemFramerStrategy,
            QuestionComposerStrategy,
            TradeoffMapperStrategy,
        )
        from spec_manager.planner.strategies.protocol import PlanningSession, PlanningSessionRunner

        workspace_root = Path(getattr(ctx, "workspace_root", "") or "")
        mode = _normalize_mode(getattr(ctx, "mode", "auto"))
        metadata = getattr(ctx, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        security_privacy_compliance = _coerce_bool(
            metadata.get("security_privacy_compliance", False)
        )
        security_privacy_compliance = (
            security_privacy_compliance
            or _coerce_bool(metadata.get("introduces_security_privacy_compliance", False))
            or _coerce_bool(metadata.get("has_security_privacy_compliance_implication", False))
        )

        touched_files_count = metadata.get(
            "touched_files_count", discovery.get("changed_file_count", 0)
        )
        try:
            touched_files_count = max(int(touched_files_count), 0)
        except (TypeError, ValueError):
            touched_files_count = max(len(gaps), 0)

        session_ctx: dict[str, Any] = {
            "layer": "L3",
            "slice_id": getattr(ctx, "slice_id", ""),
            "run_id": getattr(ctx, "run_id", "default"),
            "workspace_root": str(workspace_root),
            "mode": mode,
            "interactive": mode == "interactive",
            "touched_files_count": touched_files_count,
            "introduces_external_dep": _coerce_bool(metadata.get("introduces_external_dep", False)),
            "introduces_infra": _coerce_bool(metadata.get("introduces_infra", False)),
            "cross_library_contract": _coerce_bool(metadata.get("cross_library_contract", False)),
            "security_privacy_compliance": security_privacy_compliance,
        }

        session = PlanningSession(
            ctx=session_ctx,
            gaps=gaps,
            discovery=discovery,
        )
        run_agent = self._research_adapter.run_agent
        strategies = [
            ImpactClassifierStrategy(),
            ProblemFramerStrategy(run_agent=run_agent),
            ConstraintBootstrapStrategy(workspace_root),
            ConstraintEnricherStrategy(run_agent=run_agent),
            TradeoffMapperStrategy(workspace_root),
            NonSoftwareChecklistStrategy(),
            _L3IntentionPlannerStrategy(),
            CandidateEvaluatorStrategy(),
            AuthorityDeciderStrategy(workspace_root),
            QuestionComposerStrategy(run_agent=run_agent),
        ]
        runner = PlanningSessionRunner(strategies)
        session = runner.run(session)

        result: dict[str, Any] = {"intentions": session.intentions}
        if session.decision_requirements:
            result["decision_requirements"] = [dr.to_dict() for dr in session.decision_requirements]
        if session.new_constraints:
            result["new_constraints"] = [c.to_dict() for c in session.new_constraints]
        if session.under_spec_events:
            result["under_spec_events"] = session.under_spec_events
        if session.decision_outcomes:
            result["decision_outcomes"] = [o.to_dict() for o in session.decision_outcomes]
        return result


class L3LayerResearchAdapter:
    """Research + constraints adapter for L3 under-spec and strategy calls."""

    def __init__(self, research_tool: Any = None, constraints_tool: Any = None) -> None:
        self._research_tool = research_tool
        self._constraints_tool = constraints_tool

    def run_agent(self, prompt: str) -> str:
        return self._query_text(prompt, dimension="layer")

    def summarize_quality_evidence(self, changed_files: list[str], ctx: Any) -> dict[str, Any]:
        if not changed_files:
            return {}
        summary = self._query_text(
            f"Summarize quality evidence for changed files: {', '.join(changed_files[:20])}",
            dimension="layer",
        )
        if not summary:
            return {}
        return {
            "source": "research_tool",
            "summary": summary,
        }

    def resolve_under_spec(
        self,
        ctx: Any,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        graph = discovery.get("quality_graph", {})
        smell_nodes = {
            n.get("file", "") + "::" + n.get("function_span", ""): n
            for n in graph.get("nodes", [])
            if n.get("type") == "smell"
        }

        resolved_constraints: dict[str, Any] = {}
        questions: list[str] = []

        for event in events:
            event_file = str(event.get("file", "")).strip()
            event_span = str(event.get("function_span", "")).strip()
            key = f"{event_file}::{event_span}" if event_span else event_file
            question = str(event.get("question", "")).strip()
            if not question:
                question = (
                    f"What is the expected refactoring boundary for {key}?"
                    if key
                    else "What is the expected quality refactoring boundary?"
                )

            constrained_answer = self._resolve_from_constraints(ctx, question)
            if constrained_answer:
                resolved_constraints[key or question] = {
                    "source": "constraints_tool",
                    "answer": constrained_answer,
                    "behavior_change": False,
                }
                continue

            matching = smell_nodes.get(key)
            if matching:
                resolved_constraints[key] = {
                    "source": "quality_graph",
                    "smell_type": matching.get("smell_type", "unknown"),
                    "severity": matching.get("severity", "info"),
                    "approach": f"refactor {matching.get('smell_type', 'issue')}",
                    "behavior_change": False,
                }
                continue

            research_answer = self._query_text(question, dimension="layer")
            if research_answer:
                resolved_constraints[key or question] = {
                    "source": "research_tool",
                    "answer": research_answer,
                    "behavior_change": False,
                }
                continue

            questions.append(question)

        return {
            "blocked": bool(questions),
            "constraints": resolved_constraints,
            "questions": questions,
        }

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        return None

    def _resolve_from_constraints(self, ctx: Any, question: str) -> str:
        if not question or self._constraints_tool is None:
            return ""
        slice_id = str(getattr(ctx, "slice_id", "") or "__system__")
        try:
            if hasattr(self._constraints_tool, "check_coverage"):
                coverage = self._constraints_tool.check_coverage(slice_id, [question])
                if isinstance(coverage, dict):
                    record = coverage.get(question)
                    answer = str(getattr(record, "answer", "") or "").strip()
                    if answer:
                        return answer
        except Exception:
            logger.debug("L3 constraints tool failed", exc_info=True)
        return ""

    def _query_text(self, question: str, *, dimension: str) -> str:
        prompt = str(question or "").strip()
        if not prompt or self._research_tool is None:
            return ""

        try:
            if callable(self._research_tool):
                raw = self._research_tool(prompt)
                return str(raw).strip()
            if hasattr(self._research_tool, "research"):
                from spec_manager.planner.tools.research_tool import ResearchQuery

                result = self._research_tool.research(
                    ResearchQuery(question=prompt, dimension=dimension)
                )
                synthesis = str(getattr(result, "synthesis", "") or "").strip()
                if synthesis:
                    return synthesis
        except Exception:
            logger.debug("L3 research query failed", exc_info=True)
        return ""


class L3Planner:
    """Quality-layer planner (L3)."""

    def __init__(
        self,
        research_tool: Any = None,
        integration_tool: Any = None,
        constraints_tool: Any = None,
    ) -> None:
        self.layer: Literal["l3"] = "l3"
        self.layer_research_adapter = L3LayerResearchAdapter(
            research_tool=research_tool,
            constraints_tool=constraints_tool,
        )
        self.discovery_router = L3DiscoveryRouter(
            integration_tool=integration_tool,
            research_adapter=self.layer_research_adapter,
        )
        self.skeleton_planner = L3SkeletonPlanner(self.layer_research_adapter)
        self._trace: Any | None = None

    def bind_trace(self, trace: Any | None) -> None:
        self._trace = trace

    def discover(self, ctx: Any) -> dict[str, Any]:
        discovery = self.discovery_router.discover(ctx)
        _emit_trace_event(
            self._trace,
            layer=self.layer,
            event="discover",
            payload={
                "smell_count": discovery.get("smell_count", 0),
                "changed_file_count": discovery.get("changed_file_count", 0),
            },
        )
        return discovery

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        plan = self.skeleton_planner.build_plan(ctx, gaps, discovery)
        _emit_trace_event(
            self._trace,
            layer=self.layer,
            event="build_plan",
            payload={
                "intentions": len(plan.get("intentions", [])),
                "decision_requirements": len(plan.get("decision_requirements", [])),
            },
        )
        return plan

    def resolve_under_spec(
        self,
        ctx: Any,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.layer_research_adapter.resolve_under_spec(ctx, events, discovery)
        _emit_trace_event(
            self._trace,
            layer=self.layer,
            event="resolve_under_spec",
            payload={
                "blocked": bool(result.get("blocked", False)),
                "resolved_constraints": len(result.get("constraints", {})),
                "questions": len(result.get("questions", [])),
            },
        )
        return result

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        return self.layer_research_adapter.resolve_signal(ctx, signal)

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        return {"action": "NOOP", "monitors": []}


def _emit_trace_event(
    trace: Any | None,
    *,
    layer: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    if trace is None or not hasattr(trace, "add_artifact"):
        return
    existing = getattr(trace, "artifacts", {}).get("layer_events", [])
    events = (
        [row for row in existing if isinstance(row, dict)] if isinstance(existing, list) else []
    )
    events.append({"layer": layer, "event": event, "payload": payload})
    trace.add_artifact("layer_events", events)


def _normalize_mode(mode_value: Any) -> str:
    mode = str(mode_value or "auto").strip().lower()
    if mode == "interactive":
        return "interactive"
    return "auto"


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False
