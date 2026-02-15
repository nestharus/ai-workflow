"""L2 (architecture) layer planner.

L2 routes architecture source artifacts (manifests, pin registries,
entrypoints, wiring declarations) into a decision-point planning loop.
Discovery is scoped to the current slice context rather than scanning
the full workspace graph up front.

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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _normalize_mode(mode_value: Any) -> str:
    mode = str(mode_value or "auto").strip().lower()
    if mode == "interactive":
        return "interactive"
    return "auto"


def _estimate_touched_files(gaps: list[dict[str, Any]]) -> int:
    files: set[str] = set()
    for gap in gaps:
        file_value = gap.get("file")
        if isinstance(file_value, str) and file_value.strip():
            files.add(file_value.strip())
        target_files = gap.get("target_files")
        if isinstance(target_files, list):
            for item in target_files:
                text = str(item).strip()
                if text:
                    files.add(text)
    return len(files)


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


def _is_relative_to(path: Path, candidate_parent: Path) -> bool:
    try:
        path.relative_to(candidate_parent)
    except ValueError:
        return False
    return True


def _discover_arch_files(*, workspace_root: Path | None, scope_roots: list[Path]) -> list[str]:
    """Return architecture file paths scoped to the current slice roots."""
    found: list[str] = []
    for scope_root in scope_roots:
        if not scope_root.is_dir():
            continue
        for pattern in _ARCH_FILE_GLOBS:
            for match in sorted(scope_root.glob(pattern)):
                if workspace_root is not None and _is_relative_to(match, workspace_root):
                    found.append(str(match.relative_to(workspace_root)))
                else:
                    found.append(str(match.relative_to(scope_root)))
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
        """Route slice-scoped architecture artifacts into a discovery summary."""
        workspace_root, scope_roots = self._resolve_discovery_roots(ctx)
        arch_files = _discover_arch_files(
            workspace_root=workspace_root,
            scope_roots=scope_roots,
        )

        topology = _empty_topology()
        topology["arch_files"] = arch_files
        topology["scope_roots"] = [str(root) for root in scope_roots]
        discovery_issues: list[str] = []

        if not scope_roots:
            discovery_issues.append("No scoped architecture roots were resolved for this slice.")

        if not arch_files:
            discovery_issues.append(
                "No architecture manifest files were discovered in scoped roots "
                "(component_manifest/pins_registry/entrypoints/wiring)."
            )

        if self._integration_tool is None:
            discovery_issues.append("No integration tool is configured for L2 topology discovery.")
        else:
            try:
                enriched: Any
                if callable(self._integration_tool):
                    enriched = self._integration_tool(
                        workspace_root=str(workspace_root) if workspace_root is not None else "",
                        scope_roots=[str(root) for root in scope_roots],
                        arch_files=arch_files,
                    )
                elif hasattr(self._integration_tool, "build_graph"):
                    absolute_arch_files = [
                        str((workspace_root / rel).resolve())
                        for rel in arch_files
                        if rel and workspace_root is not None
                    ]
                    enriched = (
                        self._integration_tool.build_graph(absolute_arch_files)
                        if absolute_arch_files
                        else {}
                    )
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
                    "topology enrichment unavailable."
                )

        if not topology["nodes"] and not topology["edges"]:
            discovery_issues.append(
                "Topology graph is empty (no nodes/edges); L2 continuity checks are blocked."
            )

        topology["discovery_status"] = "ready" if not discovery_issues else "incomplete"
        topology["discovery_issues"] = discovery_issues

        logger.debug(
            "L2 discover: %d scoped roots, %d arch files, %d nodes, %d edges, %d issues",
            len(scope_roots),
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

        Without a store adapter, this method still uses the same
        decision-point planning structure with lighter internals.
        """
        if self._constraints_store_adapter is not None:
            return self._build_plan_via_strategies(ctx, gaps, discovery)

        return self._build_plan_without_store(ctx, gaps, discovery)

    def _build_plan_without_store(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Run L2 architecture decisions without constraint-store bootstrapping."""
        from spec_manager.planner.constraints.types import ImpactClassification
        from spec_manager.planner.strategies.architecture_strategy import (
            ArchitecturePlannerStrategy,
        )
        from spec_manager.planner.strategies.protocol import PlanningSession

        impact_level = self._classify_fallback_impact(ctx, gaps, discovery)
        run_agent = self._research_tool if impact_level in {"MEDIUM", "HIGH"} else None
        effective_impact = impact_level if impact_level in {"MEDIUM", "HIGH"} else "MEDIUM"

        metadata = getattr(ctx, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        workspace_root = Path(getattr(ctx, "workspace_root", "") or "")
        mode = _normalize_mode(getattr(ctx, "mode", "auto"))
        session = PlanningSession(
            ctx={
                "layer": "L2",
                "slice_id": getattr(ctx, "slice_id", ""),
                "run_id": getattr(ctx, "run_id", "default"),
                "workspace_root": str(workspace_root),
                "mode": mode,
                "interactive": mode == "interactive",
                "touched_files_count": _estimate_touched_files(gaps),
                "bundle_ref": getattr(ctx, "bundle_ref", None),
                "metadata": metadata,
            },
            gaps=gaps,
            discovery=discovery,
            impact=ImpactClassification(
                impact=effective_impact,
                blast_radius="SLICE",
            ),
        )
        strategy = ArchitecturePlannerStrategy(
            workspace_root=workspace_root,
            run_agent=run_agent,
            work_item_store=self._work_item_store,
            wait_graph=self._wait_graph,
            evidence_tool=self._evidence_tool,
        )
        session = strategy.run(session)

        normalized_intentions = self._normalize_decision_loop_intentions(session.intentions, gaps)
        result: dict[str, Any] = {"intentions": normalized_intentions}
        if session.decision_requirements:
            result["decision_requirements"] = [dr.to_dict() for dr in session.decision_requirements]
        if session.new_constraints:
            result["new_constraints"] = [c.to_dict() for c in session.new_constraints]
        if session.under_spec_events:
            result["under_spec_events"] = session.under_spec_events
        if session.decision_outcomes:
            result["decision_outcomes"] = [o.to_dict() for o in session.decision_outcomes]
        return result

    def _classify_fallback_impact(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> str:
        """Classify impact for no-store fallback so LLM calls stay proportionate."""
        from spec_manager.planner.strategies.constraint_strategies import ImpactClassifierStrategy
        from spec_manager.planner.strategies.protocol import PlanningSession

        metadata = getattr(ctx, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        session_ctx: dict[str, Any] = {
            "layer": "L2",
            "slice_id": getattr(ctx, "slice_id", ""),
            "run_id": getattr(ctx, "run_id", "default"),
            "workspace_root": str(Path(getattr(ctx, "workspace_root", "") or "")),
            "mode": _normalize_mode(getattr(ctx, "mode", "auto")),
            "interactive": _normalize_mode(getattr(ctx, "mode", "auto")) == "interactive",
            "touched_files_count": _estimate_touched_files(gaps),
            "introduces_external_dep": _coerce_bool(metadata.get("introduces_external_dep", False)),
            "introduces_infra": _coerce_bool(metadata.get("introduces_infra", False)),
            "cross_library_contract": _coerce_bool(metadata.get("cross_library_contract", False)),
            "security_privacy_compliance": _coerce_bool(
                metadata.get("security_privacy_compliance", False)
            )
            or _coerce_bool(metadata.get("introduces_security_privacy_compliance", False))
            or _coerce_bool(metadata.get("has_security_privacy_compliance_implication", False)),
        }

        session = PlanningSession(
            ctx=session_ctx,
            gaps=gaps,
            discovery=discovery,
        )
        session = ImpactClassifierStrategy().run(session)
        if session.impact is None:
            return "LOW"
        return session.impact.impact

    @staticmethod
    def _normalize_decision_loop_intentions(
        intentions: list[dict[str, Any]],
        gaps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Project decision-loop outputs onto the L2 wiring intention contract."""
        normalized: list[dict[str, Any]] = []
        for index, intention in enumerate(intentions):
            if not isinstance(intention, dict):
                continue
            if "component_id" in intention:
                normalized.append(dict(intention))
                continue

            gap = gaps[index] if index < len(gaps) and isinstance(gaps[index], dict) else {}
            target_files = gap.get("target_files", [])
            if not isinstance(target_files, list):
                target_files = []
            if (
                not target_files
                and isinstance(gap.get("file"), str)
                and gap.get("file", "").strip()
            ):
                target_files = [gap["file"]]

            approach = str(intention.get("approach", "")).strip()
            if approach in {"stub_proposal", "parse_error"}:
                approach = ""
            if not approach:
                approach = str(intention.get("details", "")).strip()
            if approach == "No LLM available":
                approach = ""
            if not approach:
                approach = str(gap.get("description", gap.get("summary", ""))).strip()

            normalized.append(
                {
                    "component_id": str(
                        gap.get("component_id") or gap.get("id") or intention.get("source") or ""
                    ).strip(),
                    "target_files": [
                        str(path).strip() for path in target_files if str(path).strip()
                    ],
                    "approach": approach,
                    "pin_refs": [
                        str(ref).strip() for ref in gap.get("pin_refs", []) if str(ref).strip()
                    ]
                    if isinstance(gap.get("pin_refs"), list)
                    else [],
                    "dependencies": [
                        str(dep).strip() for dep in gap.get("dependencies", []) if str(dep).strip()
                    ]
                    if isinstance(gap.get("dependencies"), list)
                    else [],
                }
            )
        return normalized

    @staticmethod
    def _resolve_discovery_roots(ctx: Any) -> tuple[Path | None, list[Path]]:
        """Resolve directory roots to scan for architecture artifacts."""
        roots: list[Path] = []
        seen: set[Path] = set()

        workspace_value = str(getattr(ctx, "workspace_root", "") or "").strip()
        workspace_root = Path(workspace_value) if workspace_value else None
        if workspace_root is not None:
            try:
                workspace_root = workspace_root.resolve()
            except OSError:
                workspace_root = None
        if workspace_root is not None and not workspace_root.is_dir():
            workspace_root = None

        def _append_root(path: Path | None) -> None:
            if path is None:
                return
            try:
                resolved = path.resolve()
            except OSError:
                return
            if not resolved.is_dir() or resolved in seen:
                return
            seen.add(resolved)
            roots.append(resolved)

        slice_root_value = str(getattr(ctx, "slice_root", "") or "").strip()
        if slice_root_value:
            _append_root(Path(slice_root_value))

        slice_id = str(getattr(ctx, "slice_id", "") or "").strip()
        if workspace_root is not None and slice_id:
            _append_root(workspace_root / "libraries" / slice_id)

        metadata = getattr(ctx, "metadata", {})
        if isinstance(metadata, dict) and workspace_root is not None:
            for key in ("focus_libraries", "libraries", "library_ids"):
                libs = metadata.get(key)
                if not isinstance(libs, list):
                    continue
                for lib in libs:
                    lib_name = str(lib).strip()
                    if lib_name:
                        _append_root(workspace_root / "libraries" / lib_name)

        if not roots and workspace_root is not None:
            _append_root(workspace_root)

        return workspace_root, roots

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

        session_ctx: dict[str, Any] = {
            "layer": "L2",
            "slice_id": getattr(ctx, "slice_id", ""),
            "run_id": getattr(ctx, "run_id", "default"),
            "workspace_root": str(workspace_root),
            "mode": mode,
            "interactive": mode == "interactive",
            "touched_files_count": _estimate_touched_files(gaps),
            "introduces_external_dep": _coerce_bool(metadata.get("introduces_external_dep", False)),
            "introduces_infra": _coerce_bool(metadata.get("introduces_infra", False)),
            "cross_library_contract": _coerce_bool(metadata.get("cross_library_contract", False)),
            "security_privacy_compliance": security_privacy_compliance,
            "bundle_ref": getattr(ctx, "bundle_ref", None),
            "metadata": metadata,
        }

        session = PlanningSession(
            ctx=session_ctx,
            gaps=gaps,
            discovery=discovery,
        )

        run_agent = self._research_tool

        strategies = [
            ImpactClassifierStrategy(),
            ProblemFramerStrategy(run_agent=run_agent),
            ConstraintBootstrapStrategy(workspace_root),
            ConstraintEnricherStrategy(run_agent=run_agent),
            TradeoffMapperStrategy(workspace_root),
            NonSoftwareChecklistStrategy(),
            ArchitecturePlannerStrategy(
                workspace_root,
                run_agent=run_agent,
                work_item_store=self._work_item_store,
                wait_graph=self._wait_graph,
                evidence_tool=self._evidence_tool,
            ),
            CandidateEvaluatorStrategy(),
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
        mode = _normalize_mode(getattr(ctx, "mode", "auto"))
        if mode == "interactive":
            questions = self._compose_interactive_under_spec_questions(events, discovery)
            return {
                "blocked": bool(questions),
                "constraints": {},
                "questions": questions,
            }

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

    def _compose_interactive_under_spec_questions(
        self,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> list[str]:
        """Build question-first under-spec prompts with topology context."""
        nodes = [n for n in discovery.get("nodes", []) if isinstance(n, dict)]
        edges = [e for e in discovery.get("edges", []) if isinstance(e, dict)]
        questions: list[str] = []

        for event in events:
            event_id = str(event.get("id", event.get("event_id", ""))).strip()
            base_question = str(event.get("question", event.get("description", ""))).strip()
            if not base_question and event_id:
                base_question = f"What requirement should resolve decision {event_id}?"
            if not base_question:
                base_question = "What requirement should resolve this architecture ambiguity?"

            topology_context = self._resolve_event_from_topology(event, base_question, nodes, edges)
            if topology_context:
                questions.append(f"{base_question} Known topology: {topology_context}")
                continue

            questions.append(
                f"{base_question} Missing topology detail: specify source/target components, "
                "pins, or interfaces."
            )
        return questions

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
