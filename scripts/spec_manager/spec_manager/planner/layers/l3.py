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
        smell_nodes = [n for n in graph.get("nodes", []) if n.get("kind") == "smell"]

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
        node_ids: set[str] = set()
        edge_markers: set[tuple[str, str, str]] = set()

        def add_node(node: dict[str, Any]) -> None:
            node_id = str(node.get("id", "")).strip()
            if not node_id or node_id in node_ids:
                return
            node_ids.add(node_id)
            nodes.append(node)

        def add_edge(source: str, target: str, kind: str) -> None:
            source_id = str(source).strip()
            target_id = str(target).strip()
            kind_id = str(kind).strip()
            if not source_id or not target_id or not kind_id:
                return
            marker = (source_id, target_id, kind_id)
            if marker in edge_markers:
                return
            edge_markers.add(marker)
            edges.append({"source": source_id, "target": target_id, "kind": kind_id})

        def ensure_file_node(path: str) -> str:
            file_path = str(path or "").strip()
            if not file_path:
                return ""
            node_id = f"file:{file_path}"
            add_node({"id": node_id, "kind": "file", "path": file_path, "file": file_path})
            return node_id

        for filepath in changed_files:
            ensure_file_node(filepath)

        for index, receipt in enumerate(quality_receipts):
            if not isinstance(receipt, dict):
                continue
            file_path = str(receipt.get("file", receipt.get("path", "")) or "").strip()
            function_span = str(receipt.get("function_span", "") or "").strip()
            file_node_id = ensure_file_node(file_path)

            span_node_id = ""
            if file_path and function_span:
                span_node_id = f"function_span:{file_path}:{function_span}"
                add_node(
                    {
                        "id": span_node_id,
                        "kind": "function_span",
                        "file": file_path,
                        "function_span": function_span,
                        "start_line": receipt.get("start_line"),
                        "end_line": receipt.get("end_line"),
                    }
                )
                add_edge(file_node_id, span_node_id, "contains")

            smell_id = str(receipt.get("id", "") or "").strip() or f"smell:{file_path}:{index}"
            add_node(
                {
                    "id": smell_id,
                    "kind": "smell",
                    "smell_type": receipt.get("smell_type", receipt.get("category", "unknown")),
                    "file": file_path,
                    "function_span": function_span,
                    "severity": receipt.get("severity", "info"),
                }
            )
            if span_node_id:
                add_edge(span_node_id, smell_id, "contains")
            elif file_node_id:
                add_edge(file_node_id, smell_id, "contains")

            risk_level = str(receipt.get("risk_level", receipt.get("risk", "")) or "").strip()
            risk_reason = str(
                receipt.get("risk_reason", receipt.get("rationale", "")) or ""
            ).strip()
            if risk_level or risk_reason:
                risk_id = f"risk:{smell_id}"
                add_node(
                    {
                        "id": risk_id,
                        "kind": "risk",
                        "level": risk_level or "unknown",
                        "file": file_path,
                        "function_span": function_span,
                        "rationale": risk_reason,
                    }
                )
                add_edge(smell_id, risk_id, "impacts")

        for index, diff in enumerate(diffs):
            if not isinstance(diff, dict):
                continue
            source_file = str(
                diff.get("file", diff.get("path", diff.get("source_file", diff.get("source", ""))))
                or ""
            ).strip()
            source_file_id = ensure_file_node(source_file)

            dependencies = diff.get("depends_on", diff.get("dependencies", []))
            if not isinstance(dependencies, list):
                dependencies = []
            for dep in dependencies:
                dep_id = ensure_file_node(str(dep))
                if source_file_id and dep_id:
                    add_edge(source_file_id, dep_id, "depends_on")

            risk_level = str(diff.get("risk_level", diff.get("risk", "")) or "").strip()
            risk_reason = str(diff.get("risk_reason", diff.get("summary", "")) or "").strip()
            if risk_level or risk_reason:
                risk_id = f"risk:diff:{index}"
                add_node(
                    {
                        "id": risk_id,
                        "kind": "risk",
                        "level": risk_level or "unknown",
                        "file": source_file,
                        "rationale": risk_reason,
                    }
                )
                if source_file_id:
                    add_edge(source_file_id, risk_id, "impacts")

        if self._integration_tool is not None and diffs:
            try:
                impact_data = (
                    self._integration_tool(diffs) if callable(self._integration_tool) else []
                )
                for impact in impact_data if isinstance(impact_data, list) else []:
                    if not isinstance(impact, dict):
                        continue
                    source_ref = str(
                        impact.get("source", impact.get("source_file", "")) or ""
                    ).strip()
                    target_ref = str(
                        impact.get("target", impact.get("target_file", "")) or ""
                    ).strip()
                    source_id = ensure_file_node(source_ref)
                    target_id = ensure_file_node(target_ref)
                    edge_kind = str(impact.get("kind", impact.get("type", "impacts")) or "").strip()
                    edge_kind = "depends_on" if edge_kind.lower() == "depends_on" else "impacts"
                    if source_id and target_id:
                        add_edge(source_id, target_id, edge_kind)
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
            "smell_count": sum(1 for n in nodes if n.get("kind") == "smell"),
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
            unresolved_constraints = [
                constraint.to_dict()
                for constraint in session.new_constraints
                if constraint.authority_required != "planner_ok"
            ]
            if unresolved_constraints:
                result["new_constraints"] = unresolved_constraints
        if session.under_spec_events:
            result["under_spec_events"] = session.under_spec_event_dicts()
        if session.decision_outcomes:
            result["decision_outcomes"] = [o.to_dict() for o in session.decision_outcomes]
        return result


class L3LayerResearchAdapter:
    """Research + constraints adapter for L3 under-spec and strategy calls."""

    def __init__(self, research_tool: Any = None, constraints_tool: Any = None) -> None:
        self._research_tool = research_tool
        self._constraints_tool = constraints_tool

    def run_agent(self, prompt: str) -> str:
        return self._query_text_result(prompt)["answer"]

    def summarize_quality_evidence(self, changed_files: list[str], ctx: Any) -> dict[str, Any]:
        if not changed_files:
            return {}
        summary = self._query_text(
            f"Summarize quality evidence for changed files: {', '.join(changed_files[:20])}",
            ctx=ctx,
            hint="quality_summary",
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
            if n.get("kind") == "smell"
        }

        resolved_constraints: dict[str, Any] = {}
        questions: list[str] = []
        resolution_failures: list[dict[str, str]] = []

        for event_index, event in enumerate(events):
            event_file = str(event.get("file", "")).strip()
            event_span = str(event.get("function_span", "")).strip()
            key = f"{event_file}::{event_span}" if event_span else event_file
            if not key:
                key = f"event:{event_index + 1}"
            question = str(event.get("question", "")).strip()
            if not question:
                question = (
                    f"What is the expected refactoring boundary for {key}?"
                    if key
                    else "What is the expected quality refactoring boundary?"
                )

            constrained_result = self._resolve_from_constraints_result(ctx, question)
            constrained_answer = constrained_result["answer"]
            if constrained_answer:
                resolved_constraints[key or question] = {
                    "source": "constraints_tool",
                    "answer": constrained_answer,
                    "behavior_change": False,
                }
                continue
            if constrained_result["error"]:
                resolution_failures.append(
                    {
                        "stage": "constraints_tool",
                        "event_key": key,
                        "question": question,
                        "error": constrained_result["error"],
                    }
                )

            matching = smell_nodes.get(key)
            smell_evidence = ""
            if matching:
                smell_evidence = (
                    f"smell_type={matching.get('smell_type', 'unknown')}, "
                    f"severity={matching.get('severity', 'info')}, key={key}"
                )

            research_prompt = question
            if smell_evidence:
                research_prompt = (
                    f"{question}\nKnown quality evidence: {smell_evidence}\n"
                    "Use this evidence as context only and avoid speculative commitments."
                )
            research_result = self._query_text_result(research_prompt, ctx=ctx, hint="under_spec")
            research_answer = research_result["answer"]
            if research_answer:
                resolved_constraints[key or question] = {
                    "source": "research_tool",
                    "answer": research_answer,
                    "behavior_change": False,
                }
                continue
            if research_result["error"]:
                resolution_failures.append(
                    {
                        "stage": "research_tool",
                        "event_key": key,
                        "question": question,
                        "error": research_result["error"],
                    }
                )

            if smell_evidence:
                questions.append(f"{question} Known quality evidence: {smell_evidence}")
            else:
                questions.append(question)

        return {
            "blocked": bool(questions),
            "constraints": resolved_constraints,
            "questions": questions,
            "resolution_failures": resolution_failures,
        }

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        return None

    def _resolve_from_constraints(self, ctx: Any, question: str) -> str:
        return self._resolve_from_constraints_result(ctx, question)["answer"]

    def _resolve_from_constraints_result(self, ctx: Any, question: str) -> dict[str, str]:
        if not question or self._constraints_tool is None:
            return {"answer": "", "error": ""}
        slice_id = str(getattr(ctx, "slice_id", "") or "__system__")
        try:
            if hasattr(self._constraints_tool, "check_coverage"):
                coverage = self._constraints_tool.check_coverage(slice_id, [question])
                if isinstance(coverage, dict):
                    record = coverage.get(question)
                    answer = str(getattr(record, "answer", "") or "").strip()
                    if answer:
                        return {"answer": answer, "error": ""}
        except Exception as exc:
            logger.warning("L3 constraints tool failed", exc_info=True)
            return {"answer": "", "error": str(exc).strip() or "constraints tool failure"}
        return {"answer": "", "error": ""}

    def _query_text(self, question: str, *, ctx: Any | None = None, hint: str = "") -> str:
        return self._query_text_result(question, ctx=ctx, hint=hint)["answer"]

    def _query_text_result(
        self,
        question: str,
        *,
        ctx: Any | None = None,
        hint: str = "",
    ) -> dict[str, str]:
        prompt = str(question or "").strip()
        if not prompt or self._research_tool is None:
            return {"answer": "", "error": ""}

        try:
            if callable(self._research_tool):
                raw = self._research_tool(prompt)
                return {"answer": str(raw).strip(), "error": ""}
            if hasattr(self._research_tool, "research"):
                from spec_manager.planner.tools.research_tool import ResearchQuery

                layer_context = self._build_research_context(ctx, hint)
                result = self._research_tool.research(
                    ResearchQuery(
                        question=prompt,
                        context=layer_context,
                        dimension="auto",
                        layer="l3",
                        slice_id=self._slice_id_from_ctx(ctx),
                        hints={"hint": hint} if hint else {},
                    )
                )
                synthesis = str(getattr(result, "synthesis", "") or "").strip()
                if synthesis:
                    return {"answer": synthesis, "error": ""}
        except Exception as exc:
            logger.warning("L3 research query failed", exc_info=True)
            return {"answer": "", "error": str(exc).strip() or "research tool failure"}
        return {"answer": "", "error": ""}

    @staticmethod
    def _slice_id_from_ctx(ctx: Any | None) -> str:
        if ctx is None:
            return ""
        return str(getattr(ctx, "slice_id", "") or "").strip()

    @staticmethod
    def _build_research_context(ctx: Any | None, hint: str) -> str:
        if ctx is None:
            return hint
        mode = str(getattr(ctx, "mode", "") or "").strip().lower()
        run_id = str(getattr(ctx, "run_id", "") or "").strip()
        context_parts = ["layer=l3"]
        if mode:
            context_parts.append(f"mode={mode}")
        if run_id:
            context_parts.append(f"run_id={run_id}")
        if hint:
            context_parts.append(f"hint={hint}")
        return " ".join(context_parts)


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

    def extract_skeleton(self, ctx: Any, discovery: dict[str, Any]) -> dict[str, Any]:
        quality_graph = discovery.get("quality_graph", {})
        if not isinstance(quality_graph, dict):
            quality_graph = {}
        return {
            "quality_graph": {
                "nodes": [row for row in quality_graph.get("nodes", []) if isinstance(row, dict)],
                "edges": [row for row in quality_graph.get("edges", []) if isinstance(row, dict)],
            }
        }

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
