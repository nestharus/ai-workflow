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
from typing import Any, Literal

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.layer: Literal["l3"] = "l3"
        self._research_tool = research_tool
        self._integration_tool = integration_tool
        self._evidence_tool = evidence_tool

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
        """Produce refactor intentions grouped by function-span.

        Each intention carries:

        * ``file`` -- target file path
        * ``function_span`` -- function or method being refactored
        * ``smell_type`` -- the quality smell addressed
        * ``refactor_approach`` -- short description of the refactor
        * ``behavior_preservation_check`` -- assertion that no behavior
          changes (L3 must never alter observable semantics)
        """
        graph = discovery.get("quality_graph", {})
        smell_nodes = [n for n in graph.get("nodes", []) if n.get("type") == "smell"]

        intentions: list[dict[str, Any]] = []

        for gap in gaps:
            # Match gap to a smell node if possible
            gap_file = gap.get("file", "")
            gap_span = gap.get("function_span", "")
            gap_smell = gap.get("smell_type", gap.get("category", "unknown"))

            # Find matching smell node from discovery for context
            matching_smell = next(
                (
                    s
                    for s in smell_nodes
                    if s.get("file") == gap_file and s.get("function_span") == gap_span
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
                    "refactor_approach": gap.get("refactor_approach", f"address {gap_smell} smell"),
                    "behavior_preservation_check": (
                        "No observable behavior change. "
                        "All public API signatures, return types, and "
                        "side effects remain identical."
                    ),
                    "severity": severity,
                    "source_gap": gap,
                }
            )

        return {"intentions": intentions}

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
