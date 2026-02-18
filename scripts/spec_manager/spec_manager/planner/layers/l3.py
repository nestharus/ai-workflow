# TODO(single-layer): RESTRUCTURE -> merge into Quality phase planner.
#   L3's quality graph (smells, risks, diffs) and refactor intention planning maps
#   to the Quality phase: emit refactor-only work items, readability tasks,
#   "add test to lock behavior" tasks. The "no behavior change" criteria
#   survives. Remove layer protocol references.
# ALGORITHM(single-layer):
#   References: response3 Section 9.2.
#   Data structures:
#     - Planner identity becomes QualityPhasePlanner.
#     - QualityFinding: {shape_id: ShapeId|None, category: str, required_change_type: Literal['refactor_only'], preserve_behavior: bool, evidence_refs: list[str]}.
#   Interface contracts:
#     - def discover(self, ctx: PlanningContext) -> dict[str, Any]
#     - def build_plan(self, ctx: PlanningContext, gaps: list[dict[str, Any]], discovery: dict[str, Any]) -> dict[str, Any]
#   Control flow:
#     1. Preserve quality graph construction (smells/risks/diffs).
#     2. Emit refactor-only/readability/linting tasks plus optional 'add regression test' tasks.
#     3. Quality phase edits code via PromotionLoop IMPLEMENT step — refactoring (extract helpers,
#        rename, restructure files) but cannot change behavior.
#     4. Reject behavior-changing edits; BLOCK with diagnostics (no reroute to earlier phase).
#   Error handling:
#     - If behavior-preservation cannot be established, emit blocked advisory requiring explicit human decision.
#   Integration points:
#     - Selected by PhaseRouter for phase='quality'.
# IMPL(single-layer): `discover` + `extract_skeleton` are the quality-phase
# skeleton draft/refinement seam from Section 9.2; lifecycle code should record
# freeze completion externally rather than embedding code markers/spec fields here.
# IMPL(single-layer): Quality findings emitted from this planner should converge
# to shared phase-local work-item fields (`shape_id`, `required_change_type=
# 'refactor_only'`, `preserve_behavior`, `evidence_refs`); file/span data remain
# targeting hints only.
# IMPL(single-layer): Any candidate requiring behavior change is out of quality
# authority and must surface as blocked diagnostics (no cross-phase backtracking).
#   Test requirements:
#     - No-behavior-change constraint enforced.
#     - Out-of-authority behavior findings produce block, not cross-phase re-route.

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
from typing import Any

from spec_manager.compliance.promotion.config import PhaseId

logger = logging.getLogger(__name__)

_QUALITY_PHASE: PhaseId = "quality"
_ALLOWED_QUALITY_CHANGE_TYPES = frozenset({"refactor_only"})
_HIGH_RISK_TOKENS = frozenset({"high", "critical", "error", "blocking", "blocker", "sev1", "p0"})


class _L3IntentionPlannerStrategy:
    """Construct L3 refactor intentions from quality gaps/discovery."""

    @property
    def name(self) -> str:
        return "l3_intention_planner"

    def run(self, session: Any) -> Any:
        # IMPL(single-layer): This projection step is the migration seam where
        # quality evidence + gaps become phase-local quality findings/work items.
        graph = session.discovery.get("quality_graph", {})
        smell_nodes = [
            n
            for n in graph.get("nodes", [])
            if isinstance(n, dict) and str(n.get("kind", n.get("type", ""))).strip() == "smell"
        ]

        intentions: list[dict[str, Any]] = []
        for gap_index, gap in enumerate(session.gaps):
            if not isinstance(gap, dict):
                continue
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
            required_change_type = _normalize_required_change_type(
                gap.get("required_change_type"), default="refactor_only"
            )
            preserve_behavior = _resolve_preserve_behavior(gap, matching_smell)
            behavior_preservation_check = (
                str(gap.get("behavior_preservation_check", "") or "").strip()
                or "No observable behavior change. "
                "All public API signatures, return types, and "
                "side effects remain identical."
            )

            intentions.append(
                {
                    "id": f"quality-finding:{gap_index + 1}",
                    "shape_id": _resolve_shape_id(gap, matching_smell),
                    "category": _resolve_quality_category(
                        gap.get("category", ""),
                        smell_type=gap_smell,
                    ),
                    "required_change_type": required_change_type,
                    "preserve_behavior": preserve_behavior,
                    "evidence_refs": _collect_evidence_refs(gap, matching_smell),
                    "file": gap_file,
                    "function_span": gap_span,
                    "smell_type": gap_smell,
                    "refactor_approach": gap.get(
                        "refactor_approach",
                        f"address {gap_smell} smell",
                    ),
                    "behavior_preservation_check": behavior_preservation_check,
                    # IMPL(single-layer): Export this constraint as explicit
                    # `preserve_behavior=True` when adopting the shared quality
                    # finding/work-item payload contract.
                    "severity": severity,
                    "add_regression_test": _requires_regression_test(gap, matching_smell, severity),
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
        # IMPL(single-layer): `quality_graph` discovery is the quality-phase
        # skeleton draft artifact for Section 9.2 (propose/refine lifecycle).
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
            "phase": _QUALITY_PHASE,
            "layer": "L3",
            # IMPL(single-layer): Migrate context identity atomically to
            # `phase='quality'` with strategy consumers and trace readers so
            # mixed layer/phase schemas are never emitted in one run.
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

        # IMPL(single-layer): Result shaping is where quality-phase outputs should
        # include `refactor_only` authority metadata and blocked diagnostics for
        # behavior-changing candidates instead of rerouting to earlier phases.
        fallback_shape_id = str(getattr(ctx, "slice_id", "") or "").strip()
        intentions, blocked_findings = _normalize_quality_findings(
            session.intentions,
            gaps,
            fallback_shape_id=fallback_shape_id,
        )
        if not intentions and gaps:
            gap_findings, gap_blocked = _build_gap_quality_findings(
                gaps,
                fallback_shape_id=fallback_shape_id,
            )
            intentions = gap_findings
            blocked_findings.extend(gap_blocked)
        intentions = [
            finding
            for finding in intentions
            if finding.get("required_change_type") in _ALLOWED_QUALITY_CHANGE_TYPES
        ]
        result: dict[str, Any] = {"intentions": intentions}
        if blocked_findings:
            result["blocked"] = True
            result["blocked_findings"] = blocked_findings
            result["diagnostics"] = [
                str(finding.get("diagnostic", "")).strip()
                for finding in blocked_findings
                if str(finding.get("diagnostic", "")).strip()
            ]
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
        # IMPL(single-layer): Unresolved quality ambiguity remains a phase-local
        # block (`blocked=True` + diagnostics/questions), not a demotion/reroute.
        graph = discovery.get("quality_graph", {})
        smell_nodes = {
            n.get("file", "") + "::" + n.get("function_span", ""): n
            for n in graph.get("nodes", [])
            if str(n.get("kind", n.get("type", ""))).strip() == "smell"
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
                resolved_constraints[key or question] = {
                    "source": "quality_graph",
                    "answer": (
                        "Refactor within the existing function boundary, preserve behavior, "
                        "and focus on smell remediation only."
                    ),
                    "behavior_change": False,
                    "evidence": {
                        "smell_type": matching.get("smell_type", "unknown"),
                        "severity": matching.get("severity", "info"),
                    },
                }
                continue

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
                        layer=_QUALITY_PHASE,
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
        context_parts = [f"phase={_QUALITY_PHASE}"]
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
        # IMPL(single-layer): This planner remains the PhaseRouter target for
        # `phase='quality'`; rename to QualityPhasePlanner when router/api/tool
        # schemas migrate together.
        self.planner_id = "QualityPhasePlanner"
        self.phase: PhaseId = _QUALITY_PHASE
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
            layer=self.phase,
            event="discover",
            payload={
                "smell_count": discovery.get("smell_count", 0),
                "changed_file_count": discovery.get("changed_file_count", 0),
            },
        )
        return discovery

    def extract_skeleton(self, ctx: Any, discovery: dict[str, Any]) -> dict[str, Any]:
        # IMPL(single-layer): Treat this payload as quality-phase skeleton state
        # (Section 9.2); freeze completion should reflect internal organization
        # decisions and no-behavior-change refactor closure.
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
            layer=self.phase,
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
            layer=self.phase,
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
    # IMPL(single-layer): Trace artifact keys (`layer_events`/`layer`) should
    # migrate atomically to phase-native keys with planner.api/router readers.
    if trace is None or not hasattr(trace, "add_artifact"):
        return
    existing = getattr(trace, "artifacts", {}).get("layer_events", [])
    events = (
        [row for row in existing if isinstance(row, dict)] if isinstance(existing, list) else []
    )
    events.append({"layer": layer, "event": event, "payload": payload})
    trace.add_artifact("layer_events", events)


def _normalize_required_change_type(value: Any, *, default: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"behavior_change", "wiring_only", "spec_change", "refactor_only"}:
        return normalized
    return str(default).strip().lower() or "refactor_only"


def _resolve_shape_id(*payloads: Any, fallback: str = "") -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ("shape_id", "owner_shape_id"):
            value = str(payload.get(key, "")).strip()
            if value:
                return value
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            for key in ("shape_id", "owner_shape_id"):
                value = str(metadata.get(key, "")).strip()
                if value:
                    return value
    return str(fallback).strip()


def _resolve_quality_category(category_value: Any, *, smell_type: Any) -> str:
    category = str(category_value or "").strip().lower()
    if category:
        return category
    smell = str(smell_type or "").strip().lower()
    if any(token in smell for token in ("lint", "pep8", "style", "whitespace", "flake", "format")):
        return "linting"
    if any(token in smell for token in ("readability", "long_method", "naming", "duplication")):
        return "readability"
    return "refactor"


def _collect_evidence_refs(*payloads: Any) -> list[str]:
    refs: list[str] = []

    def _extend(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                refs.append(text)
            return
        if isinstance(value, list | tuple | set):
            for item in value:
                _extend(item)
            return
        if isinstance(value, dict):
            for key in (
                "evidence_refs",
                "trigger_evidence",
                "source_refs",
                "spec_ref",
                "spec_comment_ref",
                "ref",
                "source_file",
                "file",
                "path",
            ):
                if key in value:
                    _extend(value.get(key))

    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in (
            "evidence_refs",
            "trigger_evidence",
            "source_refs",
            "spec_refs",
            "spec_ref",
            "spec_comment_ref",
        ):
            _extend(payload.get(key))

    return _dedupe_non_empty(refs)


def _collect_target_files(*payloads: Any) -> list[str]:
    files: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        file_value = str(payload.get("file", payload.get("path", "")) or "").strip()
        if file_value:
            files.append(file_value)
        target_files = payload.get("target_files", [])
        if isinstance(target_files, list):
            for item in target_files:
                text = str(item).strip()
                if text:
                    files.append(text)
    return _dedupe_non_empty(files)


def _resolve_summary(*payloads: Any) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ("summary", "details", "description", "reason", "refactor_approach"):
            value = str(payload.get(key, "")).strip()
            if value and value not in {"stub_proposal", "parse_error", "No LLM available"}:
                return value
    return ""


def _resolve_behavior_preservation_check(*payloads: Any) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        check = str(payload.get("behavior_preservation_check", "") or "").strip()
        if check:
            return check
    return (
        "No observable behavior change. "
        "All public API signatures, return types, and side effects remain identical."
    )


def _resolve_preserve_behavior(*payloads: Any) -> bool | None:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ("preserve_behavior", "behavior_preserving", "no_behavior_change"):
            if key in payload:
                coerced = _coerce_optional_bool(payload.get(key))
                if coerced is not None:
                    return coerced
        required_change_type = _normalize_required_change_type(
            payload.get("required_change_type"), default="refactor_only"
        )
        if required_change_type == "behavior_change":
            return False
        if _coerce_bool(payload.get("behavior_change", False)):
            return False
        guardrail = str(payload.get("behavior_preservation_check", "") or "").strip().lower()
        if guardrail and any(token in guardrail for token in ("unknown", "unclear", "cannot", "tbd")):
            return None
    return True


def _requires_regression_test(*payloads: Any) -> bool:
    severity_tokens: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ("add_regression_test", "requires_regression_test", "needs_regression_test"):
            if key in payload:
                explicit = _coerce_optional_bool(payload.get(key))
                if explicit is not None:
                    return explicit
        severity_tokens.extend(
            [
                str(payload.get("severity", "")).strip().lower(),
                str(payload.get("risk_level", payload.get("risk", ""))).strip().lower(),
            ]
        )
    return any(token in _HIGH_RISK_TOKENS for token in severity_tokens if token)


def _build_quality_finding(
    *,
    intention: dict[str, Any],
    gap: dict[str, Any],
    fallback_shape_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    required_change_type = _normalize_required_change_type(
        intention.get("required_change_type", gap.get("required_change_type", "")),
        default="refactor_only",
    )
    category = _resolve_quality_category(
        intention.get("category", gap.get("category", "")),
        smell_type=intention.get("smell_type", gap.get("smell_type", "")),
    )
    shape_id = _resolve_shape_id(intention, gap, fallback=fallback_shape_id)
    evidence_refs = _collect_evidence_refs(intention, gap)
    preserve_behavior = _resolve_preserve_behavior(intention, gap)
    behavior_check = _resolve_behavior_preservation_check(intention, gap)
    target_files = _collect_target_files(intention, gap)
    summary = _resolve_summary(intention, gap)

    if required_change_type != "refactor_only":
        blocked = {
            "shape_id": shape_id,
            "category": category,
            "required_change_type": required_change_type,
            "preserve_behavior": bool(preserve_behavior),
            "evidence_refs": evidence_refs,
            "target_files": target_files,
            "created_in_phase": _QUALITY_PHASE,
            "diagnostic": (
                "Quality finding requires behavior change and is outside quality authority."
                if required_change_type == "behavior_change"
                else "Quality phase accepts refactor-only findings; non-refactor change was blocked."
            ),
        }
        if summary:
            blocked["summary"] = summary
        return None, blocked

    if preserve_behavior is not True:
        blocked = {
            "shape_id": shape_id,
            "category": category,
            "required_change_type": "refactor_only",
            "preserve_behavior": bool(preserve_behavior),
            "evidence_refs": evidence_refs,
            "target_files": target_files,
            "created_in_phase": _QUALITY_PHASE,
            "diagnostic": (
                "Behavior-preservation cannot be established for this quality finding; "
                "explicit human decision is required."
            ),
            "behavior_preservation_check": behavior_check,
        }
        if summary:
            blocked["summary"] = summary
        return None, blocked

    finding: dict[str, Any] = {
        "shape_id": shape_id or None,
        "category": category,
        "required_change_type": "refactor_only",
        "preserve_behavior": True,
        "evidence_refs": evidence_refs,
        "created_in_phase": _QUALITY_PHASE,
        "behavior_preservation_check": behavior_check,
    }
    if summary:
        finding["summary"] = summary

    file_hint = str(intention.get("file", gap.get("file", "")) or "").strip()
    function_span = str(intention.get("function_span", gap.get("function_span", "")) or "").strip()
    if file_hint:
        finding["file"] = file_hint
    if function_span:
        finding["function_span"] = function_span
    smell_type = str(intention.get("smell_type", gap.get("smell_type", "")) or "").strip()
    if smell_type:
        finding["smell_type"] = smell_type
    severity = str(intention.get("severity", gap.get("severity", "")) or "").strip()
    if severity:
        finding["severity"] = severity
    if target_files:
        finding["target_files"] = target_files

    if _requires_regression_test(intention, gap):
        finding["add_regression_test"] = True

    return finding, None


def _build_gap_quality_findings(
    gaps: list[dict[str, Any]],
    *,
    fallback_shape_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    blocked_findings: list[dict[str, Any]] = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        finding, blocked = _build_quality_finding(
            intention={},
            gap=gap,
            fallback_shape_id=fallback_shape_id,
        )
        if finding is not None:
            findings.append(finding)
        if blocked is not None:
            blocked_findings.append(blocked)
    return findings, blocked_findings


def _normalize_quality_findings(
    intentions: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    *,
    fallback_shape_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized: list[dict[str, Any]] = []
    blocked_findings: list[dict[str, Any]] = []
    for index, intention in enumerate(intentions):
        if not isinstance(intention, dict):
            continue
        gap = gaps[index] if index < len(gaps) and isinstance(gaps[index], dict) else {}
        finding, blocked = _build_quality_finding(
            intention=intention,
            gap=gap,
            fallback_shape_id=fallback_shape_id,
        )
        if finding is not None:
            normalized.append(finding)
        if blocked is not None:
            blocked_findings.append(blocked)
    return normalized, blocked_findings


def _dedupe_non_empty(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return None


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
