"""L2 (architecture) layer planner.

L2 operates on *component manifests*, *pins registries*, *entrypoints*,
and *wiring declarations*.  Its discovery phase builds an architecture
topology graph (nodes: component, pin, edge, handler, route; edges:
provides, consumes, wired_to, declared_in) and its plan phase produces
wiring intentions that reference graph edges, pins, and components.

Tools (research, integration, evidence) are injected at construction
time and are optional -- ``None`` means "skip that capability for now".
Actual LLM invocations will be wired through the tool callables later;
this module structures the data and delegates.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Type alias for injected tool callables (all are optional).
_ToolFn = Callable[..., Any] | None


# ---------------------------------------------------------------------------
# Architecture topology helpers
# ---------------------------------------------------------------------------

_ARCH_FILE_GLOBS: list[str] = [
    "**/component_manifest.yaml",
    "**/component_manifest.yml",
    "**/pins_registry.yaml",
    "**/pins_registry.yml",
    "**/entrypoints.yaml",
    "**/entrypoints.yml",
    "**/wiring.yaml",
    "**/wiring.yml",
]

_NODE_TYPES = frozenset({"component", "pin", "edge", "handler", "route"})
_EDGE_TYPES = frozenset({"provides", "consumes", "wired_to", "declared_in"})


def _empty_topology() -> dict[str, Any]:
    """Return an empty architecture topology skeleton."""
    return {
        "nodes": [],
        "edges": [],
        "arch_files": [],
    }


def _discover_arch_files(workspace_root: str) -> list[str]:
    """Return relative paths for architecture-relevant files in *workspace_root*.

    Uses simple glob expansion; no language-specific parsing.
    """
    if not workspace_root:
        return []
    root = Path(workspace_root)
    if not root.is_dir():
        return []

    found: list[str] = []
    for pattern in _ARCH_FILE_GLOBS:
        for match in sorted(root.glob(pattern)):
            found.append(str(match.relative_to(root)))
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# L2Planner
# ---------------------------------------------------------------------------


class L2Planner:
    """Architecture-layer planner.

    Satisfies the ``LayerPlanner`` protocol defined in
    ``spec_manager.planner.router``.

    Parameters
    ----------
    research_tool:
        Optional callable for research queries (e.g. LLM-based arch
        reasoning).  ``None`` to skip.
    integration_tool:
        Optional callable for integration / topology analysis.
        ``None`` to skip.
    evidence_tool:
        Optional callable for evidence-store lookups.
        ``None`` to skip.
    constraints_store_adapter:
        Optional :class:`ConstraintStoreAdapter` for loading/saving
        constraints.  When provided, ``build_plan`` uses the strategy
        pipeline.
    """

    def __init__(
        self,
        research_tool: _ToolFn = None,
        integration_tool: _ToolFn = None,
        evidence_tool: _ToolFn = None,
        constraints_tool: _ToolFn = None,
        constraints_store_adapter: Any = None,
        work_item_store: Any = None,
        wait_graph: Any = None,
    ) -> None:
        self.layer: Literal["l2"] = "l2"
        self._research_tool = research_tool
        self._integration_tool = integration_tool
        self._evidence_tool = evidence_tool
        self._constraints_tool = constraints_tool
        self._constraints_store_adapter = constraints_store_adapter
        self._work_item_store = work_item_store
        self._wait_graph = wait_graph

    # ------------------------------------------------------------------
    # LayerPlanner interface
    # ------------------------------------------------------------------

    def discover(self, ctx: Any) -> dict[str, Any]:
        """Scan the workspace for arch files and build a topology summary.

        If an ``integration_tool`` is available it is invoked with the
        discovered file list to produce a richer topology graph.
        Otherwise a lightweight skeleton listing the arch files is
        returned.
        """
        workspace_root = getattr(ctx, "workspace_root", "") or ""
        arch_files = _discover_arch_files(workspace_root)

        topology = _empty_topology()
        topology["arch_files"] = arch_files
        discovery_issues: list[str] = []

        if not arch_files:
            discovery_issues.append(
                "No architecture manifest files were discovered "
                "(component_manifest/pins_registry/entrypoints/wiring)."
            )

        if self._integration_tool is None:
            discovery_issues.append("No integration tool is configured for L2 topology discovery.")
        else:
            try:
                enriched: Any
                if callable(self._integration_tool):
                    enriched = self._integration_tool(
                        workspace_root=workspace_root,
                        arch_files=arch_files,
                    )
                elif hasattr(self._integration_tool, "build_graph"):
                    absolute_arch_files = [
                        str((Path(workspace_root) / rel).resolve()) for rel in arch_files if rel
                    ]
                    enriched = self._integration_tool.build_graph(absolute_arch_files)
                    if hasattr(enriched, "to_dict"):
                        enriched = enriched.to_dict()
                else:
                    enriched = None

                if isinstance(enriched, dict):
                    topology["nodes"] = enriched.get("nodes", [])
                    topology["edges"] = enriched.get("edges", [])
                else:
                    discovery_issues.append(
                        "Integration tool did not return a topology payload "
                        "(dict with nodes/edges)."
                    )
            except Exception:
                logger.warning(
                    "L2 integration_tool failed; using lightweight topology",
                    exc_info=True,
                )
                discovery_issues.append(
                    "Integration tool failed during topology discovery; "
                    "graph enrichment unavailable."
                )

        if not topology["nodes"] and not topology["edges"]:
            discovery_issues.append(
                "Topology graph is empty (no nodes/edges); L2 continuity checks are blocked."
            )

        topology["discovery_status"] = "ready" if not discovery_issues else "incomplete"
        topology["discovery_issues"] = discovery_issues

        logger.debug(
            "L2 discover: %d arch files, %d nodes, %d edges, %d issues",
            len(arch_files),
            len(topology["nodes"]),
            len(topology["edges"]),
            len(discovery_issues),
        )
        return topology

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce wiring intentions from *gaps* and architecture *discovery*.

        When a ``constraints_store_adapter`` is available, uses the full
        strategy pipeline (impact classification, constraint loading,
        problem framing, architecture decisions, authority checks).

        Otherwise falls back to direct gap-to-intention mapping.
        """
        if self._constraints_store_adapter is not None:
            return self._build_plan_via_strategies(ctx, gaps, discovery)

        if self._research_tool is not None:
            try:
                result = self._research_tool(
                    layer="l2",
                    gaps=gaps,
                    topology=discovery,
                    ctx_metadata=getattr(ctx, "metadata", {}),
                )
                if isinstance(result, dict):
                    return result
            except Exception:
                logger.warning(
                    "L2 research_tool failed in build_plan; falling back to local mapping",
                    exc_info=True,
                )

        # Fallback: produce topology-aware intentions from gaps.
        nodes = [n for n in discovery.get("nodes", []) if isinstance(n, dict)]
        edges = [e for e in discovery.get("edges", []) if isinstance(e, dict)]
        pin_node_ids = {
            str(n.get("id") or n.get("name") or "")
            for n in nodes
            if str(n.get("type", n.get("kind", ""))).lower() == "pin"
        }

        intentions: list[dict[str, Any]] = []
        for gap in gaps:
            text_bits: list[str] = []
            for key in ("description", "summary", "component_id", "id", "target", "file"):
                value = gap.get(key)
                if isinstance(value, str) and value.strip():
                    text_bits.append(value.strip())
            for list_key in ("pin_refs", "target_files", "dependencies"):
                value = gap.get(list_key)
                if isinstance(value, list):
                    text_bits.extend(str(item) for item in value if item)
            search_text = " ".join(text_bits).lower()

            matched_nodes: list[str] = []
            matched_files: list[str] = []
            for node in nodes:
                node_id = str(node.get("id") or node.get("name") or "")
                node_fields = [
                    node_id,
                    str(node.get("name", "")),
                    str(node.get("type", node.get("kind", ""))),
                    str(node.get("file", "")),
                ]
                if not node_id:
                    continue
                if any(field and field.lower() in search_text for field in node_fields):
                    matched_nodes.append(node_id)
                    node_file = str(node.get("file", "")).strip()
                    if node_file:
                        matched_files.append(node_file)

            matched_node_set = set(matched_nodes)
            matched_edges: list[str] = []
            for edge in edges:
                source = str(edge.get("source", "")).strip()
                target = str(edge.get("target", "")).strip()
                edge_type = str(edge.get("type", edge.get("edge_type", ""))).strip()
                edge_ref = f"{source}->{target}:{edge_type}" if source or target else edge_type
                if not edge_ref:
                    continue
                if (
                    source in matched_node_set
                    or target in matched_node_set
                    or edge_ref.lower() in search_text
                    or edge_type.lower() in search_text
                ):
                    matched_edges.append(edge_ref)

            target_files = gap.get("target_files", [])
            if not target_files and matched_files:
                target_files = sorted(set(matched_files))

            component_id = gap.get("component_id", "")
            if not component_id and matched_nodes:
                component_id = matched_nodes[0]

            pin_refs = [str(p) for p in gap.get("pin_refs", []) if p]
            pin_refs.extend(node_id for node_id in matched_nodes if node_id in pin_node_ids)
            pin_refs = sorted(set(pin_refs))

            dependencies = [str(dep) for dep in gap.get("dependencies", []) if dep]
            dependencies.extend(edge for edge in matched_edges if edge)
            dependencies = sorted(set(dependencies))

            approach = gap.get("description", gap.get("summary", ""))
            if matched_edges:
                approach = (
                    f"{approach} (graph refs: {', '.join(matched_edges[:3])})"
                    if approach
                    else f"Wire graph refs: {', '.join(matched_edges[:3])}"
                )

            intentions.append(
                {
                    "component_id": component_id or gap.get("id", ""),
                    "target_files": target_files,
                    "approach": approach,
                    "pin_refs": pin_refs,
                    "dependencies": dependencies,
                    "graph_targets": {
                        "nodes": matched_nodes,
                        "edges": matched_edges,
                    },
                }
            )
        return {"intentions": intentions}

    def _build_plan_via_strategies(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the strategy pipeline for L2 plan building."""
        from spec_manager.planner.strategies.architecture_strategy import (
            ArchitecturePlannerStrategy,
        )
        from spec_manager.planner.strategies.authority_strategy import AuthorityDeciderStrategy
        from spec_manager.planner.strategies.constraint_strategies import (
            ConstraintCollectionStrategy,
            ConstraintEnricherStrategy,
            ImpactClassifierStrategy,
            NonSoftwareChecklistStrategy,
            ProblemFramerStrategy,
            QuestionComposerStrategy,
            TradeoffMapperStrategy,
        )
        from spec_manager.planner.strategies.protocol import PlanningSession, PlanningSessionRunner

        workspace_root = Path(getattr(ctx, "workspace_root", "") or "")

        session_ctx: dict[str, Any] = {
            "layer": "L2",
            "slice_id": getattr(ctx, "slice_id", ""),
            "run_id": getattr(ctx, "run_id", "default"),
            "workspace_root": str(workspace_root),
        }

        session = PlanningSession(
            ctx=session_ctx,
            gaps=gaps,
            discovery=discovery,
        )

        run_agent = self._research_tool

        strategies = [
            ImpactClassifierStrategy(),
            ConstraintCollectionStrategy(workspace_root),
            TradeoffMapperStrategy(workspace_root),
            ProblemFramerStrategy(run_agent=run_agent),
            ConstraintEnricherStrategy(run_agent=run_agent),
            NonSoftwareChecklistStrategy(),
            ArchitecturePlannerStrategy(
                workspace_root,
                run_agent=run_agent,
                work_item_store=self._work_item_store,
                wait_graph=self._wait_graph,
            ),
            AuthorityDeciderStrategy(workspace_root),
            QuestionComposerStrategy(run_agent=run_agent),
        ]

        runner = PlanningSessionRunner(strategies)
        session = runner.run(session)

        result: dict[str, Any] = {
            "intentions": session.intentions,
        }
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
        """Try to resolve under-spec events using architecture context.

        Resolution strategy (in order):
        1. Use architecture topology from *discovery* to see if the
           answer is derivable from known wiring / pins.
        2. If an ``evidence_tool`` is available, query it for prior
           findings that could fill the gap.
        3. If still unresolved, return ``blocked=True`` with questions
           for human input.
        """

        nodes = [n for n in discovery.get("nodes", []) if isinstance(n, dict)]
        edges = [e for e in discovery.get("edges", []) if isinstance(e, dict)]
        resolved_constraints: dict[str, str] = {}
        remaining_questions: list[str] = []

        for event in events:
            event_id = event.get("id", event.get("event_id", ""))
            question = event.get("question", event.get("description", ""))
            constraint_key = event_id or question

            # Strategy 1: resolve from known topology graph.
            topology_answer = self._resolve_event_from_topology(event, question, nodes, edges)
            if topology_answer:
                resolved_constraints[constraint_key] = topology_answer
                continue

            # Strategy 2: evidence lookup.
            if self._evidence_tool is not None:
                try:
                    evidence_hit: Any
                    if callable(self._evidence_tool):
                        evidence_hit = self._evidence_tool(
                            query=question,
                            layer="l2",
                            ctx_metadata=getattr(ctx, "metadata", {}),
                        )
                    elif hasattr(self._evidence_tool, "search"):
                        evidence_hit = self._evidence_tool.search(question, max_results=1)
                    else:
                        evidence_hit = None

                    answer = self._coerce_evidence_answer(evidence_hit)
                    if answer:
                        resolved_constraints[constraint_key] = answer
                        continue
                except Exception:
                    logger.warning(
                        "L2 evidence_tool failed for event %s",
                        event_id,
                        exc_info=True,
                    )

            # Strategy 3: cannot resolve -- block.
            if question:
                remaining_questions.append(question)
            elif constraint_key:
                remaining_questions.append(f"Cannot resolve under-spec event: {constraint_key}")

        blocked = len(remaining_questions) > 0
        return {
            "blocked": blocked,
            "constraints": resolved_constraints,
            "questions": remaining_questions,
        }

    @staticmethod
    def _resolve_event_from_topology(
        event: dict[str, Any],
        question: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> str | None:
        """Return a constraint answer derived from topology graph, if possible."""
        terms: set[str] = set()
        for key in (
            "component_id",
            "target",
            "file",
            "symbol",
            "source_component",
            "target_component",
            "pin_id",
            "pin_ref",
        ):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                terms.add(value.strip().lower())
        pin_refs = event.get("pin_refs")
        if isinstance(pin_refs, list):
            for pin in pin_refs:
                if isinstance(pin, str) and pin.strip():
                    terms.add(pin.strip().lower())
        if isinstance(question, str) and question.strip():
            terms.add(question.strip().lower())

        matched_nodes: list[str] = []
        for node in nodes:
            node_id = str(node.get("id") or node.get("name") or "").strip()
            if not node_id:
                continue
            fields = [
                node_id.lower(),
                str(node.get("name", "")).lower(),
                str(node.get("file", "")).lower(),
                str(node.get("type", node.get("kind", ""))).lower(),
            ]
            if any(term and any(term in field for field in fields if field) for term in terms):
                matched_nodes.append(node_id)

        if not matched_nodes:
            src = str(event.get("source_component", "")).strip()
            tgt = str(event.get("target_component", "")).strip()
            if src and tgt:
                for edge in edges:
                    if (
                        str(edge.get("source", "")).strip() == src
                        and str(edge.get("target", "")).strip() == tgt
                    ):
                        edge_type = str(edge.get("type", edge.get("edge_type", "wired_to"))).strip()
                        return (
                            f"Topology already contains edge {src}->{tgt}"
                            f" ({edge_type or 'wired_to'})."
                        )
            return None

        node_set = set(matched_nodes)
        matched_edges: list[str] = []
        for edge in edges:
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            edge_type = str(edge.get("type", edge.get("edge_type", ""))).strip()
            if source in node_set or target in node_set:
                matched_edges.append(f"{source}->{target}:{edge_type}")

        if matched_edges:
            return (
                f"Topology-derived resolution: related nodes={', '.join(sorted(node_set)[:5])}; "
                f"related edges={', '.join(matched_edges[:5])}."
            )
        return f"Topology-derived resolution: related nodes={', '.join(sorted(node_set)[:5])}."

    @staticmethod
    def _coerce_evidence_answer(evidence_hit: Any) -> str:
        """Normalize evidence-tool responses to a persisted string answer."""
        if evidence_hit is None:
            return ""
        if isinstance(evidence_hit, str):
            return evidence_hit.strip()
        if isinstance(evidence_hit, dict):
            for key in ("answer", "text", "synthesis", "detail"):
                value = evidence_hit.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        best_hit = getattr(evidence_hit, "best_hit", None)
        if best_hit is not None:
            text = getattr(best_hit, "text", "")
            if isinstance(text, str) and text.strip():
                return text.strip()
        text = getattr(evidence_hit, "text", "")
        if isinstance(text, str) and text.strip():
            return text.strip()
        rendered = str(evidence_hit).strip()
        return rendered[:1000] if rendered else ""

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        """Attempt to resolve an ambiguity signal from architecture context.

        If an ``evidence_tool`` is available, look up prior evidence
        that might clarify the signal.  Returns a resolution dict or
        ``None`` when the signal cannot be resolved at this layer.
        """
        if signal is None:
            return None

        signal_text = signal if isinstance(signal, str) else getattr(signal, "text", str(signal))

        if self._evidence_tool is not None:
            try:
                result = self._evidence_tool(
                    query=signal_text,
                    layer="l2",
                    ctx_metadata=getattr(ctx, "metadata", {}),
                )
                if result:
                    return {
                        "resolved": True,
                        "source": "evidence",
                        "detail": result,
                    }
            except Exception:
                logger.warning(
                    "L2 evidence_tool failed in resolve_signal",
                    exc_info=True,
                )

        # Cannot resolve at this layer.
        return None

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        """Triage a coordination signal.  L2 defers — returns NOOP."""
        return {"action": "NOOP", "monitors": []}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
