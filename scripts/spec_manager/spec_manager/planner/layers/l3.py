"""L3 (quality) layer planner.

L3 is the quality layer -- it works with changed files, quality receipts,
and diffs.  Discovery builds a quality graph (nodes: file, function_span,
smell, risk; edges: contains, impacts, depends_on).  Planning produces
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


class L3Planner:
    """Quality-layer planner (L3).

    Parameters
    ----------
    research_tool:
        Optional tool for querying quality receipts and code-smell
        databases.  When ``None``, discovery returns a skeleton graph.
    integration_tool:
        Optional tool for cross-file dependency analysis (used to
        evaluate diff-impact).  When ``None``, impact edges are omitted.
    evidence_tool:
        Optional tool for fetching evidence bundles (test results,
        coverage, lint reports).  When ``None``, evidence sections are
        empty.
    """

    def __init__(
        self,
        research_tool: Any = None,
        integration_tool: Any = None,
        evidence_tool: Any = None,
        constraints_tool: Any = None,
    ) -> None:
        self.layer: Literal["l3"] = "l3"
        self._research_tool = research_tool
        self._integration_tool = integration_tool
        self._evidence_tool = evidence_tool
        self._constraints_tool = constraints_tool

    # ------------------------------------------------------------------
    # LayerPlanner protocol
    # ------------------------------------------------------------------

    def discover(self, ctx: Any) -> dict[str, Any]:
        """Scan quality receipts and diffs, return a quality graph.

        The quality graph is a dynamic JSON structure:

        * **nodes** -- ``file``, ``function_span``, ``smell``, ``risk``
        * **edges** -- ``contains``, ``impacts``, ``depends_on``

        When tools are unavailable the graph is returned as an empty
        skeleton so downstream consumers can still operate on the shape.
        """
        metadata = getattr(ctx, "metadata", {}) or {}
        changed_files: list[str] = metadata.get("changed_files", [])
        quality_receipts: list[dict[str, Any]] = metadata.get("quality_receipts", [])
        diffs: list[dict[str, Any]] = metadata.get("diffs", [])

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        # -- file nodes from changed_files ---------------------------------
        for filepath in changed_files:
            nodes.append({"id": filepath, "type": "file", "path": filepath})

        # -- smell / risk nodes from quality receipts ----------------------
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
            # Edge: file -> contains -> smell
            if receipt.get("file"):
                edges.append(
                    {
                        "source": receipt["file"],
                        "target": smell_id,
                        "type": "contains",
                    }
                )

        # -- diff-impact edges (requires integration_tool) -----------------
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

        # -- evidence enrichment (requires evidence_tool) ------------------
        evidence_summary: dict[str, Any] = {}
        if self._evidence_tool is not None:
            try:
                evidence_summary = self._evidence_tool(changed_files) or {}
            except Exception:
                logger.warning("L3 discover: evidence_tool failed", exc_info=True)

        return {
            "quality_graph": {
                "nodes": nodes,
                "edges": edges,
            },
            "evidence_summary": evidence_summary,
            "changed_file_count": len(changed_files),
            "smell_count": sum(1 for n in nodes if n.get("type") == "smell"),
        }

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce L3 intentions by running planner-composed strategies."""
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
        strategies = [
            ImpactClassifierStrategy(),
            ProblemFramerStrategy(run_agent=self._research_tool),
            ConstraintBootstrapStrategy(workspace_root),
            ConstraintEnricherStrategy(run_agent=self._research_tool),
            TradeoffMapperStrategy(workspace_root),
            NonSoftwareChecklistStrategy(),
            _L3IntentionPlannerStrategy(),
            CandidateEvaluatorStrategy(),
            AuthorityDeciderStrategy(workspace_root),
            QuestionComposerStrategy(run_agent=self._research_tool),
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

    def resolve_under_spec(
        self,
        ctx: Any,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Attempt to resolve under-spec events from quality context.

        L3 under-spec events are typically missing quality criteria or
        ambiguous refactoring scope.  If the quality graph contains
        enough context (matching smell nodes, known patterns) the event
        can be resolved with inferred constraints.  Otherwise the event
        is marked as blocked with clarifying questions.
        """
        graph = discovery.get("quality_graph", {})
        smell_nodes = {
            n.get("file", "") + "::" + n.get("function_span", ""): n
            for n in graph.get("nodes", [])
            if n.get("type") == "smell"
        }

        resolved_constraints: dict[str, Any] = {}
        questions: list[str] = []
        blocked = False

        for event in events:
            event_file = event.get("file", "")
            event_span = event.get("function_span", "")
            key = f"{event_file}::{event_span}"
            matching = smell_nodes.get(key)

            if matching:
                # We have quality context -- resolve with inferred constraints
                resolved_constraints[key] = {
                    "smell_type": matching.get("smell_type", "unknown"),
                    "severity": matching.get("severity", "info"),
                    "approach": f"refactor {matching.get('smell_type', 'issue')}",
                    "behavior_change": False,
                }
            else:
                # No quality context available -- block and ask
                blocked = True
                questions.append(
                    f"Cannot resolve quality scope for {event_file}"
                    + (f"::{event_span}" if event_span else "")
                    + ". What is the expected refactoring boundary?"
                )

        return {
            "blocked": blocked,
            "constraints": resolved_constraints,
            "questions": questions,
        }

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        """Resolve an ambiguity signal.

        Quality/style signals typically require human judgement (e.g.,
        naming conventions, complexity thresholds).  Returns ``None``
        to indicate no automatic resolution.
        """
        return None

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        """Triage a coordination signal.  L3 defers — returns NOOP."""
        return {"action": "NOOP", "monitors": []}


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
