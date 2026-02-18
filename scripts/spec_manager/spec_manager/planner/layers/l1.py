# TODO(single-layer): RESTRUCTURE -> merge into Libraries phase planner. L1's skeleton
#   analysis (discover functions, spec comments, produce implementation intentions)
#   is what the Libraries phase does. The L1DiscoveryRouter and L1IntentionPlanner
#   logic survives as the Libraries phase's discovery/planning strategy. Remove layer
#   naming; this becomes the primary "discover what needs implementing" capability.
# ALGORITHM(single-layer):
#   References: response3 Sections 8 and 9; evaluation modifications #3 and #5.
#   Data structures:
#     - Rename planner identity to LibrariesPhasePlanner while preserving discovery/planning payload shapes.
#     - LibrariesIntent: {shape_id: ShapeId|None, file_targets: list[str], function_targets: list[str], required_change_type: str, spec_refs: list[str]}.
#   Interface contracts:
#     - def discover(self, ctx: PlanningContext) -> dict[str, Any]
#     - def build_plan(self, ctx: PlanningContext, gaps: list[dict[str, Any]], discovery: dict[str, Any]) -> dict[str, Any]
#   Control flow:
#     1. Iteration 1: discover from spec skeleton/decomposition inputs (L1 behaviors).
#     2. Later iterations: consume queued libraries-phase work items and shape-scoped gaps.
#     3. Preserve under-spec resolution strategy and work-item monitor generation.
#     4. When intent changes shape contracts or shape docs, emit automatic verifier-create/update work item.
#     5. Libraries phase edits code via PromotionLoop IMPLEMENT step (Gap: algorithmic gaps;
#        Plan/Implement: create/edit code+tests; Promote/Verify: deterministic verifiers + routing signals).
#   Error handling:
#     - Missing slice root/spec catalog emits under-spec block, not guessed plan.
#   Integration points:
#     - Selected by PhaseRouter for phase='libraries'.
#     - Emits WorkItem payloads consumed by implementation runner.
# IMPL(single-layer): Libraries intent/work-item emission should adopt the shared
# contract (`shape_id`, `created_in_phase='libraries'`, `required_change_type`,
# `evidence_refs`, `verifier_ids`) and use `WorkItemStore.create/upsert`; when
# shape docs change (`requires_verifier_refresh=True`), emit verifier-refresh work
# items keyed to the same `shape_id`.
#   Test requirements:
#     - First-pass spec-driven discovery.
#     - Subsequent-pass work-item-driven planning.
#     - Verifier-refresh work item emitted on shape changes.

"""L1 layer planner — code-as-spec skeleton analysis.

L1 works with PDD skeleton files that contain spec comments and function
stubs. It discovers code concerns (functions, classes, spec-comment blocks)
and produces function-level implementation intentions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.planner.layers.l2 import _is_relative_to

logger = logging.getLogger(__name__)

_LIBRARIES_PHASE: PhaseId = "libraries"


class L1DiscoveryRouter:
    """Discovers L1 code-as-spec skeleton topology for a slice."""

    def __init__(self, discovery_tool: Any = None, fallback_discovery_tool: Any = None) -> None:
        self._discovery_tool = discovery_tool
        self._fallback_discovery_tool = fallback_discovery_tool

    def discover(self, ctx: Any) -> dict[str, Any]:
        # IMPL(single-layer): This remains the libraries-phase bootstrap discovery path
        # for iteration 1 (proposal Section 9.1/9.4). Missing slice roots should flow
        # into under-spec/block handling, never guessed topology.
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if slice_root is None or not slice_root.exists():
            logger.warning("L1 discover: slice_root missing or does not exist (%s)", ctx.slice_root)
            return {"nodes": [], "edges": [], "file_index": {}, "discovery_issues": []}

        files, file_issues = _collect_slice_files(slice_root)
        if not files:
            return {"nodes": [], "edges": [], "file_index": {}, "discovery_issues": file_issues}

        raw_graph = _run_l1_discovery_tool(
            files=files,
            discovery_tool=self._discovery_tool,
        )
        if raw_graph is None and self._fallback_discovery_tool is not None:
            raw_graph = _run_l1_discovery_tool(
                files=files,
                discovery_tool=self._fallback_discovery_tool,
            )
        nodes, edges, discovery_issues = _normalize_l1_discovery_graph(raw_graph, files)
        discovery_issues.extend(file_issues)

        file_index: dict[str, list[str]] = {}
        for rel_path in files:
            file_index[rel_path] = []
        for node in nodes:
            rel_path = str(node.get("file", "")).strip()
            if rel_path:
                file_index.setdefault(rel_path, []).append(str(node.get("id", "")))

        return {
            "nodes": nodes,
            "edges": edges,
            "file_index": file_index,
            "discovery_issues": discovery_issues,
        }


class L1LayerResearchAdapter:
    """Research + constraints adapter for L1 strategy and under-spec work."""

    def __init__(self, research_tool: Any = None, constraints_tool: Any = None) -> None:
        self._research_tool = research_tool
        self._constraints_tool = constraints_tool

    def run_agent(self, prompt: str) -> str:
        return self._query_text(prompt)

    def resolve_under_spec(
        self,
        ctx: Any,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        nodes = discovery.get("nodes", [])
        node_lookup = {n["id"]: n for n in nodes}
        func_nodes = [n for n in nodes if n.get("kind") == "function"]
        mode = _normalize_mode(getattr(ctx, "mode", "auto"))

        if mode == "interactive":
            questions = _compose_l1_interactive_questions(events, func_nodes, node_lookup)
            return {
                "blocked": bool(questions),
                "questions": questions,
                "resolved": [],
                "constraints": {},
            }

        resolved: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        constraints: dict[str, str] = {}
        resolution_failures: list[dict[str, str]] = []

        for event in events:
            target = str(event.get("target", "")).strip()
            question = str(event.get("question", event.get("description", ""))).strip()
            if not question:
                question = f"Cannot resolve: {target or '?'}"

            # Strategy 1: constraints tool (authoritative source) first.
            constrained_result = self._resolve_from_constraints_result(ctx, question)
            constrained_answer = constrained_result["answer"]
            if constrained_answer:
                constraints[question] = constrained_answer
                resolved.append(
                    {
                        "event": event,
                        "resolution": "constraints_tool",
                        "answer": constrained_answer,
                    }
                )
                continue
            if constrained_result["error"]:
                resolution_failures.append(
                    {
                        "stage": "constraints_tool",
                        "question": question,
                        "error": constrained_result["error"],
                    }
                )

            matched = _match_gap_to_node(target, func_nodes, node_lookup)

            # Strategy 2: local skeleton context.
            if matched and matched.get("spec_comment_ref"):
                resolved.append(
                    {
                        "event": event,
                        "resolution": "local_context",
                        "spec_comment_ref": matched["spec_comment_ref"],
                    }
                )
                continue

            # Strategy 3: unified research tool lookup.
            research_result = self._query_text_result(
                question or target, ctx=ctx, hint="under_spec"
            )
            research_answer = research_result["answer"]
            if research_answer:
                resolved.append(
                    {
                        "event": event,
                        "resolution": "research_tool",
                        "detail": research_answer,
                    }
                )
                continue
            if research_result["error"]:
                resolution_failures.append(
                    {
                        "stage": "research_tool",
                        "question": question or target,
                        "error": research_result["error"],
                    }
                )

            unresolved.append(event)

        blocked = len(unresolved) > 0
        questions = [
            str(e.get("question", f"Cannot resolve: {e.get('target', '?')}")) for e in unresolved
        ]

        return {
            "blocked": blocked,
            "questions": questions,
            "resolved": resolved,
            "constraints": constraints,
            "resolution_failures": resolution_failures,
        }

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        if signal is None:
            return None

        if isinstance(signal, dict):
            target = signal.get("target", signal.get("name", ""))
        else:
            target = getattr(signal, "target", getattr(signal, "name", ""))

        target = str(target).strip()
        if not target:
            return None

        query_result = self._query_text_result(target, ctx=ctx, hint="signal")
        answer = query_result["answer"]
        if not answer:
            if query_result["error"]:
                return {
                    "resolution": "research_tool_error",
                    "target": target,
                    "error": query_result["error"],
                }
            return None
        return {
            "resolution": "research_tool",
            "target": target,
            "detail": answer,
        }

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
            logger.warning("L1 constraints tool failed for question=%s", question, exc_info=True)
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
                        layer=_LIBRARIES_PHASE,
                        slice_id=self._slice_id_from_ctx(ctx),
                        hints={"hint": hint} if hint else {},
                    )
                )
                synthesis = str(getattr(result, "synthesis", "") or "").strip()
                if synthesis:
                    return {"answer": synthesis, "error": ""}

            if hasattr(self._research_tool, "search"):
                search_result = self._research_tool.search(prompt, max_results=1)
                best_hit = getattr(search_result, "best_hit", None)
                if best_hit is not None:
                    return {"answer": str(getattr(best_hit, "text", "") or "").strip(), "error": ""}
        except Exception as exc:
            logger.warning("L1 research query failed", exc_info=True)
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
        context_parts = [f"phase={_LIBRARIES_PHASE}"]
        if mode:
            context_parts.append(f"mode={mode}")
        if run_id:
            context_parts.append(f"run_id={run_id}")
        if hint:
            context_parts.append(f"hint={hint}")
        return " ".join(context_parts)


class L1SkeletonPlanner:
    """Builds L1 plan intentions from gaps + discovery using shared strategies."""

    def __init__(
        self,
        *,
        research_adapter: L1LayerResearchAdapter,
        constraints_store_adapter: Any = None,
    ) -> None:
        self._research_adapter = research_adapter
        self._constraints_store_adapter = constraints_store_adapter

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        nodes = discovery.get("nodes", [])
        func_nodes = [n for n in nodes if n.get("kind") == "function"]
        node_lookup = {n["id"]: n for n in nodes}

        intentions: list[dict[str, Any]] = []

        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            target = gap.get("target", "")
            matched_node = _match_gap_to_node(target, func_nodes, node_lookup)
            intentions.append(
                _build_libraries_intent(
                    gap=gap,
                    matched_node=matched_node,
                    ctx=ctx,
                )
            )

        if not gaps and func_nodes:
            # IMPL(single-layer): Preserve first-pass spec-driven intention bootstrap
            # when explicit gaps are empty; later iterations should feed queued
            # libraries work items/shape-scoped gaps through `gaps` (Section 9.2).
            for fn in func_nodes:
                intentions.append(_build_libraries_intent(gap={}, matched_node=fn, ctx=ctx))

        plan: dict[str, Any] = {"intentions": intentions}
        if self._constraints_store_adapter is None:
            return plan
        if not _should_run_l1_planning_session(ctx, gaps):
            return plan

        pipeline_outputs = self._build_plan_via_strategies(ctx, gaps, discovery, intentions)
        for key in (
            "decision_requirements",
            "new_constraints",
            "under_spec_events",
            "decision_outcomes",
        ):
            if key in pipeline_outputs:
                plan[key] = pipeline_outputs[key]
        return plan

    def _build_plan_via_strategies(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
        base_intentions: list[dict[str, Any]],
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
        triggers = _l1_pipeline_triggers(gaps)
        touched_files_count = _coerce_positive_int(
            metadata.get("touched_files_count", 0),
            default=_estimate_touched_files(gaps),
        )
        security_privacy_compliance = _coerce_bool(
            metadata.get("security_privacy_compliance", False)
        )
        security_privacy_compliance = (
            security_privacy_compliance
            or _coerce_bool(metadata.get("introduces_security_privacy_compliance", False))
            or _coerce_bool(metadata.get("has_security_privacy_compliance_implication", False))
        )
        # IMPL(single-layer): Session context vocabulary must migrate atomically
        # (`layer=L1` -> `phase=libraries`) with strategy consumers and persisted
        # planner artifacts so mixed schemas are never emitted in one run.
        session_ctx: dict[str, Any] = {
            "phase": _LIBRARIES_PHASE,
            "slice_id": getattr(ctx, "slice_id", ""),
            "run_id": getattr(ctx, "run_id", "default"),
            "workspace_root": str(workspace_root),
            "mode": mode,
            "interactive": mode == "interactive",
            "touched_files_count": touched_files_count,
            "introduces_external_dep": triggers["introduces_external_dep"]
            or _coerce_bool(metadata.get("introduces_external_dep", False)),
            "introduces_infra": triggers["introduces_infra"]
            or _coerce_bool(metadata.get("introduces_infra", False)),
            "cross_library_contract": _coerce_bool(metadata.get("cross_library_contract", False)),
            "security_privacy_compliance": security_privacy_compliance,
            "pipeline_triggers": list(triggers["trigger_labels"]),
        }

        session = PlanningSession(
            ctx=session_ctx,
            gaps=gaps,
            discovery=discovery,
            intentions=[dict(i) for i in base_intentions],
        )
        run_agent = self._research_adapter.run_agent
        strategies = [
            ImpactClassifierStrategy(),
            ProblemFramerStrategy(run_agent=run_agent),
            ConstraintBootstrapStrategy(workspace_root),
            ConstraintEnricherStrategy(run_agent=run_agent),
            TradeoffMapperStrategy(workspace_root),
            NonSoftwareChecklistStrategy(),
            CandidateEvaluatorStrategy(),
            AuthorityDeciderStrategy(workspace_root),
            QuestionComposerStrategy(run_agent=run_agent),
        ]
        runner = PlanningSessionRunner(strategies)
        session = runner.run(session)

        result: dict[str, Any] = {}
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


class L1Planner:
    """Planner implementation for libraries-phase code-as-spec discovery."""

    def __init__(
        self,
        research_tool: Callable[..., Any] | None = None,
        integration_tool: Callable[..., Any] | None = None,
        constraints_tool: Any = None,
        constraints_store_adapter: Any = None,
    ) -> None:
        # IMPL(single-layer): Rename/mount this planner as the libraries-phase planner
        # while keeping discover/build/under-spec method contracts stable for
        # `PhaseRouter` dispatch.
        self.planner_id = "LibrariesPhasePlanner"
        self.phase: PhaseId = _LIBRARIES_PHASE
        self.layer_research_adapter = L1LayerResearchAdapter(
            research_tool=research_tool,
            constraints_tool=constraints_tool,
        )
        self.discovery_router = L1DiscoveryRouter(
            discovery_tool=integration_tool,
            fallback_discovery_tool=research_tool,
        )
        self.skeleton_planner = L1SkeletonPlanner(
            research_adapter=self.layer_research_adapter,
            constraints_store_adapter=constraints_store_adapter,
        )
        self._integration_tool = integration_tool
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
                "nodes": len(discovery.get("nodes", [])),
                "edges": len(discovery.get("edges", [])),
            },
        )
        return discovery

    def extract_skeleton(self, ctx: Any, discovery: dict[str, Any]) -> dict[str, Any]:
        # IMPL(single-layer): Exported skeleton artifact key should migrate in one
        # change with planner.api/router (`layer_skeleton` -> `phase_skeleton`);
        # payload structure stays this graph contract for libraries phase.
        return {
            "code_skeleton_graph": {
                "nodes": [row for row in discovery.get("nodes", []) if isinstance(row, dict)],
                "edges": [row for row in discovery.get("edges", []) if isinstance(row, dict)],
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
                "resolved": len(result.get("resolved", [])),
                "questions": len(result.get("questions", [])),
            },
        )
        return result

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        return self.layer_research_adapter.resolve_signal(ctx, signal)

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        """Triage a coordination signal from a halted L1 agent."""
        # IMPL(single-layer): Keep routing externalized as work items (proposal
        # Section 8): no code markers, no implicit in-file TODOs, and monitor-driven
        # wakeup semantics for blocked slices.
        from spec_manager.orchestration.coordination.work_items import (
            SearchQuery,
            WorkItemStore,
        )

        need = signal.get("need", {})
        if not isinstance(need, dict):
            need = {}
        spec_refs = signal.get("spec_refs", [])
        if not isinstance(spec_refs, list):
            spec_refs = []
        search_hints = signal.get("search_hints", {})
        if not isinstance(search_hints, dict):
            search_hints = {}
        signal_shape_id = _resolve_signal_shape_id(
            signal=signal,
            need=need,
            search_hints=search_hints,
        )

        spec_ref_texts = _extract_spec_ref_texts(spec_refs)
        hint_keywords = search_hints.get("keywords", [])
        if not isinstance(hint_keywords, list):
            hint_keywords = []
        keywords = _dedupe_preserve_order(
            [str(k) for k in hint_keywords if isinstance(k, str) and k.strip()]
            + _extract_artifact_channel_tokens(str(need.get("artifact_key", "")))
        )

        query = SearchQuery(
            spec_text="\n".join(spec_ref_texts),
            artifact_key=need.get("artifact_key", ""),
            need_summary=need.get("summary", ""),
            spec_refs=spec_refs,
            keywords=keywords,
            phase=self.phase,
            shape_id=signal_shape_id or None,
        )

        workspace_root = Path(ctx.workspace_root) if ctx.workspace_root else None
        if not workspace_root:
            return {"action": "NOOP", "monitors": []}

        coordination_dir = workspace_root / ".pdd_runs" / ctx.run_id / "coordination"
        store = WorkItemStore(
            coordination_dir,
            semantic_rerank_tool=self.layer_research_adapter.run_agent,
        )
        search_outcome = store.search_with_coverage(query)
        primary_match = search_outcome.get("primary_match")
        secondary_matches = search_outcome.get("secondary_matches", [])
        if not isinstance(secondary_matches, list):
            secondary_matches = []
        coverage = str(search_outcome.get("coverage", "NO_COVERAGE")).upper()
        confidence = float(search_outcome.get("confidence", 0.0) or 0.0)
        why = str(search_outcome.get("why", ""))
        missing_detail = str(search_outcome.get("missing_detail", "")).strip()

        if coverage == "FULL_COVERAGE" and primary_match is not None:
            if primary_match.status in ("MERGED", "DONE", "DECIDED"):
                return {
                    "action": "WAKE_IMMEDIATELY",
                    "monitors": [],
                    "coverage": coverage,
                    "confidence": confidence,
                    "why": why,
                    "missing_detail": "",
                    "wake_instruction": _build_immediate_wake_instruction(
                        signal=signal,
                        work_item_dict=primary_match.to_dict(),
                    ),
                    "matched_work_item": primary_match.to_dict(),
                    "secondary_matches": [m.to_dict() for m in secondary_matches],
                }

            primary_match_dict = primary_match.to_dict()
            monitor = _build_git_symbol_monitor(
                signal=signal,
                need=need,
                ctx=ctx,
                work_item_dict=primary_match_dict,
            )
            if monitor is None:
                monitor = _build_work_item_monitor(
                    signal=signal,
                    work_item_dict=primary_match_dict,
                    ctx=ctx,
                )
            return {
                "action": "WAIT_ON_WORK_ITEM",
                "monitors": [monitor],
                "coverage": coverage,
                "confidence": confidence,
                "why": why,
                "missing_detail": "",
                "matched_work_item": primary_match_dict,
                "secondary_matches": [m.to_dict() for m in secondary_matches],
            }

        if coverage == "PARTIAL_COVERAGE":
            candidate_matches = [m for m in [primary_match, *secondary_matches] if m is not None]
            active_matches = [
                m for m in candidate_matches if m.status not in ("MERGED", "DONE", "DECIDED")
            ]
            if active_matches:
                monitors = _build_partial_match_monitors(
                    signal=signal, matches=active_matches, ctx=ctx
                )
                return {
                    "action": "WAIT_ON_WORK_ITEM",
                    "monitors": monitors,
                    "coverage": coverage,
                    "confidence": confidence,
                    "why": why,
                    "missing_detail": missing_detail,
                    "matched_work_item": primary_match.to_dict()
                    if primary_match is not None
                    else None,
                    "secondary_matches": [m.to_dict() for m in secondary_matches],
                }

        spec_catalog_roots = _resolve_spec_catalog_roots(
            ctx=ctx,
            workspace_root=workspace_root,
            search_hints=search_hints if isinstance(search_hints, dict) else {},
        )
        spec_match, spec_scan_issues = _search_spec_catalog(
            workspace_root,
            need,
            spec_refs,
            scope_roots=spec_catalog_roots,
        )
        if spec_match:
            owner_slice_id = _resolve_owner_slice_id(
                workspace_root=workspace_root,
                run_id=str(getattr(ctx, "run_id", "") or ""),
                spec_match=spec_match,
                search_hints=search_hints if isinstance(search_hints, dict) else {},
                fallback_slice_id=str(getattr(ctx, "slice_id", "") or ""),
            )
            owner_shape_id = _resolve_routed_shape_id(
                workspace_root=workspace_root,
                file_hint=str(spec_match.get("file", "")).strip(),
                hinted_shape_id=signal_shape_id,
                fallback_shape_id=owner_slice_id,
            )
            new_work_item_payload = _create_work_item_from_spec(
                spec_match=spec_match,
                owner_slice_id=owner_slice_id,
                owner_shape_id=owner_shape_id,
                run_id=str(getattr(ctx, "run_id", "")).strip(),
                created_in_phase=self.phase,
                required_change_type=_normalize_required_change_type(
                    need.get("required_change_type"),
                    default="behavior_change",
                ),
                signal=signal,
            )
            try:
                new_work_item = _persist_routed_work_item(
                    store,
                    new_work_item_payload,
                    merge_policy="append_evidence",
                )
            except ValueError as exc:
                return {
                    "action": "BLOCKED",
                    "monitors": [],
                    "coverage": "NO_COVERAGE",
                    "confidence": confidence,
                    "why": "invalid_routing_work_item",
                    "missing_detail": str(exc),
                    "spec_catalog_scan_issues": spec_scan_issues,
                }
            new_work_item_dict = new_work_item.to_dict()
            verifier_refresh_items = _emit_verifier_refresh_work_items_if_needed(
                store=store,
                signal=signal,
                need=need,
                search_hints=search_hints,
                run_id=str(getattr(ctx, "run_id", "")).strip(),
                owner_slice_id=owner_slice_id,
                shape_id=owner_shape_id,
                evidence_refs=list(new_work_item.evidence_refs),
                created_in_phase=self.phase,
                merge_policy="append_evidence",
            )
            monitor = _build_git_symbol_monitor(
                signal=signal,
                need=need,
                ctx=ctx,
                work_item_dict=new_work_item_dict,
            )
            if monitor is None:
                monitor = _build_work_item_monitor(
                    signal=signal,
                    work_item_dict=new_work_item_dict,
                    ctx=ctx,
                )
            return {
                "action": "ROUTE_AND_WAIT",
                "monitors": [monitor],
                "routing": [new_work_item_dict, *verifier_refresh_items],
                "coverage": "NO_COVERAGE",
                "confidence": confidence,
                "why": why or "spec_found_unrouted",
                "missing_detail": "",
                "spec_catalog_candidates": spec_match.get("candidate_matches", []),
                "spec_catalog_scan_issues": spec_scan_issues,
            }

        # IMPL(single-layer): No-coverage catalog outcomes should route to explicit
        # EXPAND_SPEC work (or remain blocked) rather than guessing implementation
        # targets, matching Section 8.2 ambiguity handling and Section 9 authority rules.
        expansion = _build_expansion(signal, need, ctx)
        expansion_owner_slice_id = _resolve_owner_slice_id(
            workspace_root=workspace_root,
            run_id=str(getattr(ctx, "run_id", "") or ""),
            spec_match={},
            search_hints=search_hints if isinstance(search_hints, dict) else {},
            fallback_slice_id=str(getattr(ctx, "slice_id", "") or ""),
        )
        expansion_shape_id = _resolve_routed_shape_id(
            workspace_root=workspace_root,
            file_hint="",
            hinted_shape_id=signal_shape_id,
            fallback_shape_id=expansion_owner_slice_id,
        )
        expansion_work_item_payload = _create_expansion_work_item(
            expansion=expansion,
            signal=signal,
            owner_slice_id=expansion_owner_slice_id,
            owner_shape_id=expansion_shape_id,
            run_id=str(getattr(ctx, "run_id", "")).strip(),
            created_in_phase=self.phase,
            required_change_type=_normalize_required_change_type(
                need.get("required_change_type"),
                default="spec_change",
            ),
        )
        try:
            expansion_work_item = _persist_routed_work_item(
                store,
                expansion_work_item_payload,
                merge_policy="append_evidence",
            )
        except ValueError as exc:
            return {
                "action": "BLOCKED",
                "monitors": [],
                "coverage": "NO_COVERAGE",
                "confidence": confidence,
                "why": "invalid_expansion_work_item",
                "missing_detail": str(exc),
                "spec_catalog_scan_issues": spec_scan_issues,
            }
        expansion_work_item_dict = expansion_work_item.to_dict()
        verifier_refresh_items = _emit_verifier_refresh_work_items_if_needed(
            store=store,
            signal=signal,
            need=need,
            search_hints=search_hints,
            run_id=str(getattr(ctx, "run_id", "")).strip(),
            owner_slice_id=expansion_owner_slice_id,
            shape_id=expansion_shape_id,
            evidence_refs=list(expansion_work_item.evidence_refs),
            created_in_phase=self.phase,
            merge_policy="append_evidence",
        )
        monitor = _build_work_item_monitor(
            signal=signal,
            work_item_dict=expansion_work_item_dict,
            ctx=ctx,
            monitor_kind="spec_expanded",
        )
        scan_issue_summary = "; ".join(spec_scan_issues[:3]) if spec_scan_issues else ""
        combined_missing_detail = (
            missing_detail
            or str(need.get("summary", "")).strip()
            or "Missing spec-level behavior needed by blocked consumer."
        )
        if scan_issue_summary:
            combined_missing_detail = f"{combined_missing_detail} Scan issues: {scan_issue_summary}"
        return {
            "action": "EXPAND_SPEC",
            "monitors": [monitor],
            "routing": [expansion_work_item_dict, *verifier_refresh_items],
            "expansion": expansion,
            "coverage": "NO_COVERAGE",
            "confidence": confidence,
            "why": why
            or (
                "spec_catalog_scan_incomplete"
                if spec_scan_issues
                else "underspecified_no_spec_match"
            ),
            "missing_detail": combined_missing_detail,
            "spec_catalog_scan_issues": spec_scan_issues,
        }


def _emit_trace_event(
    trace: Any | None,
    *,
    layer: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    # IMPL(single-layer): Trace schema migration (`layer_events`/`layer`) to
    # phase-native keys must happen atomically with replay/readers in planner.api/router.
    if trace is None or not hasattr(trace, "add_artifact"):
        return
    existing = getattr(trace, "artifacts", {}).get("layer_events", [])
    events = (
        [row for row in existing if isinstance(row, dict)] if isinstance(existing, list) else []
    )
    events.append({"layer": layer, "event": event, "payload": payload})
    trace.add_artifact("layer_events", events)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_L1_NODE_KINDS = frozenset({"function", "class", "spec_comment_block"})
_L1_EDGE_KINDS = frozenset({"declares", "mentions", "calls"})
_L1_DISCOVERY_CHUNK_SIZE = 12000


def _collect_slice_files(root: Path) -> tuple[dict[str, str], list[str]]:
    """Return readable UTF-8 text files plus surfaced read/decode issues."""
    files: dict[str, str] = {}
    issues: list[str] = []
    if not root.is_dir():
        return files, issues
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if not _is_text_like_file(path):
            continue
        rel = str(path.relative_to(root))
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            issues.append(f"{rel}: utf-8 decode failed ({exc.reason})")
            continue
        except OSError as exc:
            issues.append(f"{rel}: read failed ({exc})")
            continue
        files[rel] = content
    return files, issues


def _is_text_like_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(4096)
    except OSError:
        return False
    return b"\x00" not in sample


def _run_l1_discovery_tool(files: dict[str, str], discovery_tool: Any) -> dict[str, Any] | None:
    if discovery_tool is None:
        return None

    file_payload, file_manifest = _build_l1_discovery_file_payload(files)
    prompt = (
        "Produce a strict JSON object with keys 'nodes' and 'edges' for an L1 skeleton graph. "
        "Files may arrive as multiple chunks for the same path; merge by path/chunk order "
        "before deriving graph structure. "
        "Nodes must have kind=function|class|spec_comment_block and include id/file. "
        "Edges must have kind=declares|mentions|calls and include source/target. "
        "Use best-effort pattern recognition only."
    )
    payload = {
        "task": "l1_discovery",
        # IMPL(single-layer): Request payload key/value should migrate together with
        # tool adapters (`layer=l1` -> `phase=libraries`) to keep integration traces
        # and tool selection deterministic.
        "phase": _LIBRARIES_PHASE,
        "files": file_payload,
        "file_manifest": file_manifest,
    }

    raw: Any = None
    try:
        if callable(discovery_tool):
            for kwargs in (
                {"task": "l1_discovery", "prompt": prompt, "payload": payload},
                {"prompt": prompt, "payload": payload},
                {"payload": payload},
                {"query": prompt},
            ):
                try:
                    raw = discovery_tool(**kwargs)
                    break
                except TypeError:
                    continue
            if raw is None:
                raw = discovery_tool(prompt)
        elif hasattr(discovery_tool, "discover_skeleton_graph"):
            raw = discovery_tool.discover_skeleton_graph(payload)
        elif hasattr(discovery_tool, "discover_l1_graph"):
            raw = discovery_tool.discover_l1_graph(payload)
        elif hasattr(discovery_tool, "discover"):
            raw = discovery_tool.discover(payload)
        elif hasattr(discovery_tool, "research"):
            from spec_manager.planner.tools.research_tool import ResearchQuery

            result = discovery_tool.research(
                ResearchQuery(
                    question=prompt,
                    context=json.dumps(payload, ensure_ascii=True),
                    dimension="auto",
                    layer=_LIBRARIES_PHASE,
                    hints={"task": "l1_discovery"},
                    max_results=1,
                )
            )
            raw = getattr(result, "synthesis", result)
    except Exception:
        logger.warning("L1 discovery tool invocation failed", exc_info=True)
        return None

    return _coerce_json_payload(raw)


def _build_l1_discovery_file_payload(
    files: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    for rel_path, content in files.items():
        chunks = _chunk_text_with_offsets(content, max_chars=_L1_DISCOVERY_CHUNK_SIZE)
        manifest.append(
            {
                "path": rel_path,
                "content_length": len(content),
                "chunk_count": len(chunks),
            }
        )
        for chunk_index, (offset_start, offset_end, chunk_text) in enumerate(chunks):
            payload.append(
                {
                    "path": rel_path,
                    "chunk_index": chunk_index,
                    "chunk_count": len(chunks),
                    "offset_start": offset_start,
                    "offset_end": offset_end,
                    "content_length": len(content),
                    "content": chunk_text,
                }
            )
    return payload, manifest


def _chunk_text_with_offsets(text: str, *, max_chars: int) -> list[tuple[int, int, str]]:
    if max_chars <= 0:
        return [(0, len(text), text)]
    if not text:
        return [(0, 0, "")]
    chunks: list[tuple[int, int, str]] = []
    for offset_start in range(0, len(text), max_chars):
        offset_end = min(offset_start + max_chars, len(text))
        chunks.append((offset_start, offset_end, text[offset_start:offset_end]))
    return chunks


def _coerce_json_payload(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "to_dict") and callable(raw.to_dict):
        payload = raw.to_dict()
        if isinstance(payload, dict):
            return payload

    text = str(raw).strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    for block in re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    json_like = _extract_first_json_object(text)
    if not json_like:
        return None
    try:
        payload = json.loads(json_like)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _normalize_l1_discovery_graph(
    raw_graph: dict[str, Any] | None,
    files: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    issues: list[str] = []
    if raw_graph is None:
        return [], [], ["L1 discovery tool unavailable or returned no graph payload."]

    graph = raw_graph["graph"] if isinstance(raw_graph.get("graph"), dict) else raw_graph

    raw_nodes = graph.get("nodes", [])
    raw_edges = graph.get("edges", [])
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    if not isinstance(raw_edges, list):
        raw_edges = []

    file_refs = set(files.keys())
    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for idx, row in enumerate(raw_nodes):
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind", row.get("type", "")) or "").strip().lower()
        if kind not in _L1_NODE_KINDS:
            continue
        file_ref = str(row.get("file", row.get("path", "")) or "").strip().replace("\\", "/")
        if file_ref and file_ref not in file_refs:
            continue
        node_id = str(row.get("id", "") or "").strip()
        if not node_id:
            name_hint = str(row.get("name", "") or "").strip() or str(idx)
            node_id = f"{file_ref or 'unknown'}:{kind}:{name_hint}"
        if node_id in node_ids:
            continue
        node_ids.add(node_id)

        normalized = {
            "id": node_id,
            "kind": kind,
            "file": file_ref,
            "name": str(row.get("name", "") or "").strip(),
            "line": row.get("line"),
        }
        if kind == "spec_comment_block":
            normalized["text"] = str(row.get("text", "") or "").strip()
        spec_ref = str(row.get("spec_comment_ref", "") or "").strip()
        if spec_ref:
            normalized["spec_comment_ref"] = spec_ref
        nodes.append(normalized)

    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for row in raw_edges:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind", row.get("type", "")) or "").strip().lower()
        if kind not in _L1_EDGE_KINDS:
            continue
        source = str(row.get("source", "") or "").strip()
        target = str(row.get("target", "") or "").strip()
        if not source or not target:
            continue
        if source not in node_ids or target not in node_ids:
            continue
        marker = (source, target, kind)
        if marker in seen_edges:
            continue
        seen_edges.add(marker)
        edges.append({"source": source, "target": target, "kind": kind})

    if not nodes:
        issues.append("L1 discovery produced no nodes from tool output.")

    found_edge_kinds = {edge["kind"] for edge in edges}
    for required in ("declares", "mentions", "calls"):
        if required not in found_edge_kinds:
            issues.append(f"L1 discovery output missing '{required}' edges.")

    return nodes, edges, issues


def _match_gap_to_node(
    target: str,
    func_nodes: list[dict[str, Any]],
    node_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Best-effort match of a gap *target* string against skeleton nodes."""
    if not target:
        return None

    # Exact id match
    if target in node_lookup:
        return node_lookup[target]

    # Name match against function nodes
    for fn in func_nodes:
        if fn.get("name") == target:
            return fn

    # Substring match (target appears in node name or vice-versa)
    for fn in func_nodes:
        name = fn.get("name", "")
        if name and (target in name or name in target):
            return fn

    return None


def _build_libraries_intent(
    *,
    gap: dict[str, Any],
    matched_node: dict[str, Any] | None,
    ctx: Any,
) -> dict[str, Any]:
    shape_id = _resolve_intent_shape_id(gap=gap, ctx=ctx)
    file_targets = _collect_gap_file_targets(gap=gap, matched_node=matched_node)
    function_targets = _collect_gap_function_targets(gap=gap, matched_node=matched_node)
    required_change_type = _normalize_required_change_type(
        gap.get("required_change_type"),
        default="behavior_change",
    )
    spec_refs = _collect_gap_spec_refs(gap=gap, matched_node=matched_node)
    return {
        "shape_id": shape_id,
        "file_targets": file_targets,
        "function_targets": function_targets,
        "required_change_type": required_change_type,
        "spec_refs": spec_refs,
    }


def _resolve_intent_shape_id(*, gap: dict[str, Any], ctx: Any) -> str | None:
    for key in ("shape_id", "owner_shape_id"):
        value = str(gap.get(key, "")).strip()
        if value:
            return value
    metadata = gap.get("metadata", {})
    if isinstance(metadata, dict):
        for key in ("shape_id", "owner_shape_id"):
            value = str(metadata.get(key, "")).strip()
            if value:
                return value
    context_shape = str(getattr(ctx, "slice_id", "")).strip()
    return context_shape or None


def _collect_gap_file_targets(
    *,
    gap: dict[str, Any],
    matched_node: dict[str, Any] | None,
) -> list[str]:
    files: list[str] = []
    for key in ("file", "target_file", "path", "module_path"):
        value = str(gap.get(key, "")).strip()
        if value:
            files.append(value)
    for key in ("target_files", "file_targets"):
        values = gap.get(key)
        if isinstance(values, list):
            files.extend(str(v).strip() for v in values if str(v).strip())
    file_locations = gap.get("file_locations")
    if isinstance(file_locations, list):
        for location in file_locations:
            if not isinstance(location, dict):
                continue
            file_path = str(location.get("file_path") or location.get("file") or "").strip()
            if file_path:
                files.append(file_path)
    location = gap.get("location")
    if isinstance(location, dict):
        file_path = str(location.get("file") or "").strip()
        if file_path:
            files.append(file_path)
    if matched_node is not None:
        file_path = str(matched_node.get("file", "")).strip()
        if file_path:
            files.append(file_path)
    return _dedupe_preserve_order(files)


def _collect_gap_function_targets(
    *,
    gap: dict[str, Any],
    matched_node: dict[str, Any] | None,
) -> list[str]:
    functions: list[str] = []
    for key in (
        "function_name",
        "target",
        "target_symbol",
        "symbol",
        "symbol_fqn",
        "fqn",
        "needed_for",
        "artifact_key",
    ):
        value = str(gap.get(key, "")).strip()
        if value:
            functions.append(value)
    for key in ("function_targets", "target_symbols"):
        values = gap.get(key)
        if isinstance(values, list):
            functions.extend(str(v).strip() for v in values if str(v).strip())
    location = gap.get("location")
    if isinstance(location, dict):
        symbol = str(location.get("symbol") or "").strip()
        if symbol:
            functions.append(symbol)
    file_locations = gap.get("file_locations")
    if isinstance(file_locations, list):
        for location_item in file_locations:
            if not isinstance(location_item, dict):
                continue
            symbol = str(location_item.get("symbol") or "").strip()
            if symbol:
                functions.append(symbol)
    if matched_node is not None:
        name = str(matched_node.get("name", "")).strip()
        if name:
            functions.append(name)
    return _dedupe_preserve_order(functions)


def _collect_gap_spec_refs(
    *,
    gap: dict[str, Any],
    matched_node: dict[str, Any] | None,
) -> list[str]:
    refs: list[str] = []
    for key in ("spec_comment_ref", "spec_ref"):
        ref = str(gap.get(key, "")).strip()
        if ref:
            refs.append(ref)
    spec_refs = gap.get("spec_refs")
    if isinstance(spec_refs, list):
        for item in spec_refs:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    refs.append(text)
                continue
            if not isinstance(item, dict):
                continue
            for key in ("spec_text", "spec_ref", "ref"):
                text = str(item.get(key, "")).strip()
                if text:
                    refs.append(text)
                    break
    if matched_node is not None:
        ref = str(matched_node.get("spec_comment_ref", "")).strip()
        if ref:
            refs.append(ref)
    return _dedupe_preserve_order(refs)


# ---------------------------------------------------------------------------
# Triage helpers
# ---------------------------------------------------------------------------


def _build_work_item_monitor(
    signal: dict[str, Any],
    work_item_dict: dict[str, Any],
    ctx: Any,
    monitor_kind: str = "work_item_status",
) -> dict[str, Any]:
    """Build a monitor payload that watches a work item for completion."""
    target_statuses = work_item_dict.get("target_statuses", [])
    if isinstance(target_statuses, list) and target_statuses:
        required_status = str(target_statuses[0])
    else:
        kind = str(work_item_dict.get("kind", "")).strip().upper()
        if kind == "ARCH_DECISION":
            required_status = "DECIDED"
            target_statuses = ["DECIDED"]
        else:
            required_status = "MERGED"
            target_statuses = ["MERGED", "DONE"]
    return {
        "type": "work_item_done",
        "work_item_id": work_item_dict.get("work_item_id", ""),
        "required_status": required_status,
        "target_statuses": target_statuses,
        "kind": monitor_kind,
        "signal_id": signal.get("signal_id", ""),
        "run_id": getattr(ctx, "run_id", ""),
        "timeout_seconds": 3600,
    }


def _build_partial_match_monitors(
    signal: dict[str, Any],
    matches: list[Any],
    ctx: Any,
) -> list[dict[str, Any]]:
    """Build whitelisted work-item monitors for partial coverage matches."""
    monitors: list[dict[str, Any]] = []
    for m in matches:
        kind = str(getattr(m, "kind", "")).strip().upper()
        statuses = ["DECIDED"] if kind == "ARCH_DECISION" else ["MERGED", "DONE"]
        for required_status in statuses:
            monitors.append(
                {
                    "type": "work_item_done",
                    "work_item_id": m.work_item_id,
                    "required_status": required_status,
                    "kind": "work_item_status",
                    "signal_id": signal.get("signal_id", ""),
                    "run_id": getattr(ctx, "run_id", ""),
                    "timeout_seconds": 3600,
                }
            )
    return monitors


def _build_git_symbol_monitor(
    signal: dict[str, Any],
    need: dict[str, Any],
    ctx: Any,
    work_item_dict: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a monitor payload that watches for an artifact symbol to appear."""
    location: dict[str, Any] = {}
    item_file_locations = []
    if isinstance(work_item_dict, dict):
        raw_locations = work_item_dict.get("file_locations", [])
        if isinstance(raw_locations, list):
            item_file_locations = [item for item in raw_locations if isinstance(item, dict)]
        if item_file_locations:
            location = item_file_locations[0]
        elif isinstance(work_item_dict.get("location"), dict):
            location = work_item_dict["location"]
    item_symbol = str(location.get("symbol", "")).strip()
    item_file = str(location.get("file_path") or location.get("file") or "").strip()
    artifact_key = str(need.get("artifact_key", "")).strip()
    symbol_fqn = item_symbol or artifact_key
    if not symbol_fqn:
        return None
    if "." not in symbol_fqn and "::" not in symbol_fqn and symbol_fqn.lower() == symbol_fqn:
        return None
    file_glob = item_file or str(need.get("file_glob", "")).strip() or "**/*.py"
    symbol_leaf = symbol_fqn.split(".")[-1] if "." in symbol_fqn else symbol_fqn
    expected_shape = need.get("expected_shape", {})
    expected_signature_hint = (
        str(expected_shape.get("signature_hint", "")).strip()
        if isinstance(expected_shape, dict)
        else ""
    )
    if not expected_signature_hint:
        expected_signature_hint = symbol_fqn
    return {
        "type": "git_symbol_exists",
        "symbol_fqn": symbol_fqn,
        "artifact_key": artifact_key or symbol_fqn,
        "ref": "HEAD",
        "file_glob": file_glob,
        "signature_regex": rf"\b{re.escape(symbol_leaf)}\b",
        "expected_signature_hint": expected_signature_hint,
        "kind": "symbol_available",
        "signal_id": signal.get("signal_id", ""),
        "run_id": getattr(ctx, "run_id", ""),
        "timeout_seconds": 3600,
    }


def _build_immediate_wake_instruction(
    signal: dict[str, Any],
    work_item_dict: dict[str, Any],
) -> dict[str, Any]:
    """Build consumer-facing wake guidance for already merged work."""
    metadata = work_item_dict.get("metadata", {}) if isinstance(work_item_dict, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    target_ref = (
        str(metadata.get("merged_ref", "")).strip()
        or str(metadata.get("source_branch", "")).strip()
        or "upstream/latest"
    )
    summary = (
        str(work_item_dict.get("description", "")).strip()
        or str(work_item_dict.get("title", "")).strip()
        or str(work_item_dict.get("spec_text", "")).strip()
    )
    return {
        "operation": "rebase_or_pull",
        "target_ref": target_ref,
        "instruction": (
            "Dependency is already merged/done. Sync your worktree with upstream "
            "(pull --rebase or rebase onto target_ref) before retrying."
        ),
        "work_item_id": str(work_item_dict.get("work_item_id", "")).strip(),
        "summary": summary,
        "signal_id": signal.get("signal_id", ""),
    }


def _normalize_required_change_type(value: Any, *, default: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"behavior_change", "wiring_only", "refactor_only", "spec_change"}:
        return normalized
    return str(default).strip().lower() or "behavior_change"


def _resolve_signal_shape_id(
    *,
    signal: dict[str, Any],
    need: dict[str, Any],
    search_hints: dict[str, Any],
) -> str:
    for source in (signal, need, search_hints):
        if not isinstance(source, dict):
            continue
        for key in ("shape_id", "owner_shape_id"):
            value = str(source.get(key, "")).strip()
            if value:
                return value
    for source in (signal, need, search_hints):
        if not isinstance(source, dict):
            continue
        metadata = source.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        for key in ("shape_id", "owner_shape_id"):
            value = str(metadata.get(key, "")).strip()
            if value:
                return value
    possible_owner_slices = search_hints.get("possible_owner_slices", [])
    if isinstance(possible_owner_slices, list) and len(possible_owner_slices) == 1:
        value = str(possible_owner_slices[0]).strip()
        if value:
            return value
    return ""


def _resolve_routed_shape_id(
    *,
    workspace_root: Path,
    file_hint: str,
    hinted_shape_id: str,
    fallback_shape_id: str,
) -> str:
    if hinted_shape_id:
        return hinted_shape_id
    file_ref = str(file_hint).strip()
    if file_ref:
        try:
            from spec_manager.routing import load_shape_pack, resolve_shape_for_file

            shape_index = load_shape_pack(workspace_root)
            resolved_shape = resolve_shape_for_file(file_ref, shape_index)
            resolved_text = str(resolved_shape or "").strip()
            if resolved_text:
                return resolved_text
        except Exception:
            logger.debug("L1 triage: unable to resolve shape for %s", file_ref, exc_info=True)
    return str(fallback_shape_id).strip()


def _persist_routed_work_item(
    store: Any,
    payload: dict[str, Any],
    *,
    merge_policy: Literal["replace", "append_evidence"] = "append_evidence",
) -> Any:
    from spec_manager.orchestration.coordination.work_items import WorkItem

    work_item = WorkItem.from_dict(payload)
    existing = store.get(work_item.work_item_id)
    if existing is None:
        return store.create(work_item)
    return store.upsert(work_item, merge_policy=merge_policy)


def _requires_verifier_refresh(
    *,
    signal: dict[str, Any],
    need: dict[str, Any],
    search_hints: dict[str, Any],
) -> bool:
    for source in (signal, need, search_hints):
        if not isinstance(source, dict):
            continue
        if _coerce_bool(source.get("requires_verifier_refresh", False)):
            return True
        metadata = source.get("metadata", {})
        if isinstance(metadata, dict):
            if _coerce_bool(metadata.get("requires_verifier_refresh", False)):
                return True
            shape_status = str(metadata.get("shape_status", "")).strip().upper()
            if shape_status == "PROPOSAL":
                return True
    return False


def _extract_signal_verifier_ids(signal: dict[str, Any]) -> list[str]:
    verifier_ids: list[str] = []
    candidate_containers: list[Any] = [
        signal,
        signal.get("need", {}),
        signal.get("search_hints", {}),
    ]
    for container in candidate_containers:
        if not isinstance(container, dict):
            continue
        for key in ("verifier_ids", "verifiers"):
            values = container.get(key)
            if isinstance(values, list):
                verifier_ids.extend(str(v).strip() for v in values if str(v).strip())
        metadata = container.get("metadata", {})
        if isinstance(metadata, dict):
            for key in ("verifier_ids", "verifiers"):
                values = metadata.get(key)
                if isinstance(values, list):
                    verifier_ids.extend(str(v).strip() for v in values if str(v).strip())
    return _dedupe_preserve_order(verifier_ids)


def _emit_verifier_refresh_work_items_if_needed(
    *,
    store: Any,
    signal: dict[str, Any],
    need: dict[str, Any],
    search_hints: dict[str, Any],
    run_id: str,
    owner_slice_id: str,
    shape_id: str,
    evidence_refs: list[str],
    created_in_phase: PhaseId,
    merge_policy: Literal["replace", "append_evidence"] = "append_evidence",
) -> list[dict[str, Any]]:
    if not _requires_verifier_refresh(signal=signal, need=need, search_hints=search_hints):
        return []
    normalized_shape = str(shape_id).strip()
    if not normalized_shape:
        return []
    verifier_ids = _extract_signal_verifier_ids(signal)
    seed = (
        f"verifier_refresh|{run_id}|{owner_slice_id}|{normalized_shape}|"
        f"{','.join(sorted(verifier_ids))}"
    )
    work_item_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    summary = f"Refresh verifier coverage for shape {normalized_shape}."
    combined_evidence = _dedupe_preserve_order(
        [*evidence_refs, *_build_signal_evidence_refs(signal), "requires_verifier_refresh"]
    )
    payload = {
        "work_item_id": work_item_id,
        "run_id": run_id,
        "slice_id": owner_slice_id,
        "title": summary,
        "description": summary,
        "shape_id": normalized_shape,
        "created_in_phase": created_in_phase,
        "required_change_type": "spec_change",
        "status": "NEW",
        "kind": "SPEC_WORK",
        "priority": "high",
        "evidence_refs": combined_evidence,
        "verifier_ids": verifier_ids,
        "metadata": {
            "requires_verifier_refresh": True,
            "source_signal_id": str(signal.get("signal_id", "")).strip(),
        },
    }
    try:
        persisted = _persist_routed_work_item(store, payload, merge_policy=merge_policy)
    except ValueError:
        logger.warning(
            "Failed to emit verifier refresh work item for shape=%s",
            normalized_shape,
            exc_info=True,
        )
        return []
    return [persisted.to_dict()]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _extract_spec_ref_texts(spec_refs: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for ref in spec_refs:
        if not isinstance(ref, dict):
            continue
        text = ref.get("spec_text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    return texts


def _extract_artifact_channel_tokens(artifact_key: str) -> list[str]:
    if not artifact_key:
        return []
    expanded = re.sub(r"([a-z])([A-Z])", r"\1 \2", artifact_key)
    parts = re.split(r"[^a-zA-Z0-9]+", expanded)
    tokens = [part.lower() for part in parts if part]
    return _dedupe_preserve_order(tokens)


def _resolve_owner_slice_id(
    *,
    workspace_root: Path,
    run_id: str,
    spec_match: dict[str, Any],
    search_hints: dict[str, Any],
    fallback_slice_id: str,
) -> str:
    """Resolve owner slice from hints and spec location, with deterministic fallback."""
    raw_possible = (
        search_hints.get("possible_owner_slices", []) if isinstance(search_hints, dict) else []
    )
    possible_owner_slices = (
        _dedupe_preserve_order([str(v).strip() for v in raw_possible if str(v).strip()])
        if isinstance(raw_possible, list)
        else []
    )
    file_hint = str(spec_match.get("file", "")).strip()
    discovered_slice_ids = _discover_l1_slice_ids(workspace_root=workspace_root, run_id=run_id)

    if possible_owner_slices:
        matched_preferred = _best_slice_match(
            file_hint=file_hint, candidate_slice_ids=possible_owner_slices
        )
        if matched_preferred:
            return matched_preferred
        if len(possible_owner_slices) == 1:
            return possible_owner_slices[0]
        logger.warning(
            "L1 triage: ambiguous owner slice candidates for file=%s candidates=%s",
            file_hint,
            possible_owner_slices,
        )

    matched_discovered = _best_slice_match(
        file_hint=file_hint, candidate_slice_ids=discovered_slice_ids
    )
    if matched_discovered:
        return matched_discovered

    inferred_library_slice = _infer_library_slice_from_file(file_hint)
    if inferred_library_slice:
        return inferred_library_slice

    return fallback_slice_id


def _discover_l1_slice_ids(*, workspace_root: Path, run_id: str) -> list[str]:
    """Discover L1 slice IDs from run state, then library directory names."""
    candidates: list[str] = []
    run_slices_dir = workspace_root / ".pdd_runs" / run_id / "slices"
    if run_slices_dir.exists():
        for child in sorted(run_slices_dir.iterdir()):
            if child.is_dir():
                candidates.append(child.name)
    libraries_dir = workspace_root / "libraries"
    if libraries_dir.exists():
        for child in sorted(libraries_dir.iterdir()):
            if child.is_dir():
                candidates.append(child.name)
    return _dedupe_preserve_order([c for c in candidates if c])


def _best_slice_match(file_hint: str, candidate_slice_ids: list[str]) -> str:
    """Return best matching slice ID for a file path hint."""
    if not file_hint or not candidate_slice_ids:
        return ""
    normalized = file_hint.replace("\\", "/").strip().strip("/")
    if not normalized:
        return ""
    path_segments = {seg.lower() for seg in normalized.split("/") if seg}

    best_slice_id = ""
    best_score = 0
    for slice_id in candidate_slice_ids:
        raw = str(slice_id).strip()
        if not raw:
            continue
        tokens = [raw.lower()]
        if raw.startswith("arch-"):
            tokens.append(raw.removeprefix("arch-").lower())
        if raw.startswith("cq-"):
            tokens.append(raw.removeprefix("cq-").lower())
        for token in _dedupe_preserve_order([t for t in tokens if t]):
            if token in path_segments:
                score = len(token) + 20
            elif f"/{token}/" in f"/{normalized.lower()}/":
                score = len(token) + 10
            else:
                score = 0
            if score > best_score:
                best_score = score
                best_slice_id = raw
    return best_slice_id


def _infer_library_slice_from_file(file_hint: str) -> str:
    """Infer slice ID from libraries/<lib-id>/... paths."""
    if not file_hint:
        return ""
    parts = [p for p in file_hint.replace("\\", "/").split("/") if p]
    lowered = [p.lower() for p in parts]
    if "libraries" in lowered:
        idx = lowered.index("libraries")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _strip_comment_prefix(line: str) -> str:
    stripped = line.strip()
    for prefix in ("#", "//", "/*", "*", "--", ";"):
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return stripped


def _extract_nearest_spec_text(lines: list[str], match_index: int) -> tuple[str, int]:
    """Return verbatim spec-like text nearest to a matched line."""
    current_line = lines[match_index].strip()
    current_text = _strip_comment_prefix(current_line)
    if current_line.startswith(("#", "//", "/*", "*", "--", ";")) or "spec" in current_text.lower():
        return current_text, match_index + 1

    for offset in range(1, 8):
        probe = match_index - offset
        if probe < 0:
            break
        candidate = lines[probe].strip()
        if not candidate:
            continue
        candidate_text = _strip_comment_prefix(candidate)
        if candidate.startswith(("#", "//", "/*", "*", "--", ";")):
            return candidate_text, probe + 1
        if "spec" in candidate_text.lower():
            return candidate_text, probe + 1

    return current_text, match_index + 1


def _resolve_spec_catalog_roots(
    *,
    ctx: Any,
    workspace_root: Path,
    search_hints: dict[str, Any],
) -> list[Path]:
    try:
        workspace_root = workspace_root.resolve()
    except OSError:
        return []
    roots: list[Path] = []
    seen: set[Path] = set()

    def _append(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.resolve()
        except OSError:
            return
        if not resolved.is_dir() or resolved in seen:
            return
        if not _is_relative_to(resolved, workspace_root):
            return
        seen.add(resolved)
        roots.append(resolved)

    slice_root_value = str(getattr(ctx, "slice_root", "") or "").strip()
    if slice_root_value:
        _append(Path(slice_root_value))

    slice_id = str(getattr(ctx, "slice_id", "") or "").strip()
    if slice_id:
        _append(workspace_root / "libraries" / slice_id)

    possible_owner_slices = search_hints.get("possible_owner_slices", [])
    if isinstance(possible_owner_slices, list):
        for slice_name in possible_owner_slices:
            text = str(slice_name).strip()
            if text:
                _append(workspace_root / "libraries" / text)

    # Single-library layout fallback remains bounded to workspace root.
    if not roots and not (workspace_root / "libraries").exists():
        _append(workspace_root)

    return roots


def _search_spec_catalog(
    workspace_root: Path,
    need: dict[str, Any],
    spec_refs: list[dict[str, Any]],
    *,
    scope_roots: list[Path],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Search for matching spec text in workspace slice files.

    Scans text-like files under scoped roots for spec comment blocks that
    mention the needed artifact. Returns a match dict on success, None if
    nothing found.
    """
    try:
        workspace_root = workspace_root.resolve()
    except OSError:
        return None, ["Workspace root could not be resolved for spec catalog scanning."]

    issues: list[str] = []
    candidates: list[dict[str, Any]] = []

    def _add_candidate(candidate: dict[str, Any]) -> None:
        spec_text = str(candidate.get("spec_text", "")).strip()
        if not spec_text:
            return
        candidates.append(candidate)

    # Prefer verbatim signal spec references when provided.
    for index, ref in enumerate(spec_refs):
        if not isinstance(ref, dict):
            continue
        spec_text = str(ref.get("spec_text", "")).strip()
        if not spec_text:
            continue
        _add_candidate(
            {
                "spec_text": spec_text,
                "file": str(ref.get("source_file", "")).strip(),
                "symbol": str(ref.get("source_symbol", "")).strip(),
                "line_hint": int(ref.get("source_line_hint", 0) or 0),
                "matched_in": "signal_spec_ref",
                "match_score": 10_000 - index,
            }
        )

    artifact_key = str(need.get("artifact_key", "")).strip()
    if not artifact_key and candidates:
        ranked = sorted(candidates, key=lambda row: int(row.get("match_score", 0)), reverse=True)
        candidate_matches = [
            {k: v for k, v in row.items() if k != "match_score"} for row in ranked[:10]
        ]
        top = dict(candidate_matches[0])
        top["candidate_matches"] = candidate_matches
        return top, issues
    if not artifact_key:
        return None, issues

    search_terms = [artifact_key.lower(), *_extract_artifact_channel_tokens(artifact_key)]
    search_terms = [term for term in _dedupe_preserve_order(search_terms) if term]
    if not search_terms:
        return None, issues

    normalized_roots: list[Path] = []
    seen_roots: set[Path] = set()
    for root in scope_roots:
        try:
            resolved_root = root.resolve()
        except OSError:
            continue
        if not resolved_root.is_dir() or resolved_root in seen_roots:
            continue
        if not _is_relative_to(resolved_root, workspace_root):
            continue
        seen_roots.add(resolved_root)
        normalized_roots.append(resolved_root)

    if not normalized_roots:
        issues.append("No scoped roots were available for spec catalog scanning.")
        if candidates:
            ranked = sorted(
                candidates, key=lambda row: int(row.get("match_score", 0)), reverse=True
            )
            candidate_matches = [
                {k: v for k, v in row.items() if k != "match_score"} for row in ranked[:10]
            ]
            top = dict(candidate_matches[0])
            top["candidate_matches"] = candidate_matches
            return top, issues
        return None, issues

    seen_files: set[Path] = set()
    for root in normalized_roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path in seen_files:
                continue
            seen_files.add(path)
            if not _is_text_like_file(path):
                continue
            rel = (
                str(path.relative_to(workspace_root))
                if _is_relative_to(path, workspace_root)
                else str(path.relative_to(root))
            )
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                issues.append(f"{rel}: utf-8 decode failed ({exc.reason})")
                continue
            except OSError as exc:
                issues.append(f"{rel}: read failed ({exc})")
                continue
            content_lower = content.lower()
            if not any(term in content_lower for term in search_terms):
                continue

            lines = content.splitlines()
            for idx, line in enumerate(lines):
                line_lower = line.lower()
                term_hits = sum(1 for term in search_terms if term in line_lower)
                if term_hits == 0:
                    continue
                spec_text, line_hint = _extract_nearest_spec_text(lines, idx)
                if not spec_text:
                    continue
                _add_candidate(
                    {
                        "spec_text": spec_text,
                        "file": rel,
                        "symbol": "",
                        "line_hint": line_hint,
                        "matched_in": "spec_catalog_scan",
                        "match_score": term_hits,
                    }
                )

    if not candidates:
        return None, issues

    ranked = sorted(candidates, key=lambda row: int(row.get("match_score", 0)), reverse=True)
    candidate_matches = [
        {k: v for k, v in row.items() if k != "match_score"} for row in ranked[:10]
    ]
    top = dict(candidate_matches[0])
    top["candidate_matches"] = candidate_matches
    return top, issues


def _create_work_item_from_spec(
    spec_match: dict[str, Any],
    owner_slice_id: str,
    owner_shape_id: str,
    run_id: str,
    created_in_phase: PhaseId,
    required_change_type: str,
    signal: dict[str, Any],
) -> dict[str, Any]:
    """Create a work-item dict from a spec catalog match."""
    # IMPL(single-layer): Migrate this emitted payload to shared routing contract
    # fields (`shape_id`, `created_in_phase='libraries'`, `required_change_type`,
    # `evidence_refs`) and persist via WorkItemStore.create/upsert.
    from spec_manager.orchestration.coordination.work_items import _fingerprint

    spec_text = str(spec_match.get("spec_text", "")).strip()
    file_path = str(spec_match.get("file", "")).strip()
    symbol = str(spec_match.get("symbol", "")).strip()
    try:
        line_hint = int(spec_match.get("line_hint", 0) or 0)
    except (TypeError, ValueError):
        line_hint = 0
    line_start = line_hint if line_hint > 0 else None
    spec_fingerprint = _fingerprint(spec_text) if spec_text else ""
    normalized_change_type = _normalize_required_change_type(
        required_change_type,
        default="behavior_change",
    )
    identity_seed = (
        f"{created_in_phase}|{normalized_change_type}|{owner_shape_id}|"
        f"{spec_fingerprint}|{file_path}|{symbol}|{line_hint}"
    )
    work_item_id = hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()[:16]
    evidence_refs = _build_spec_match_evidence_refs(spec_match, signal=signal)
    title = spec_text or f"Implement shape behavior for {owner_shape_id}."

    return {
        "work_item_id": work_item_id,
        "run_id": run_id,
        "slice_id": owner_slice_id,
        "title": title,
        "description": title,
        "shape_id": owner_shape_id,
        "created_in_phase": created_in_phase,
        "required_change_type": normalized_change_type,
        "status": "NEW",
        "priority": "normal",
        "file_locations": (
            [
                {
                    "file_path": file_path,
                    "line_start": line_start,
                    "line_end": line_start,
                    "symbol": symbol or None,
                }
            ]
            if file_path or symbol
            else []
        ),
        "kind": "SPEC_WORK",
        "evidence_refs": evidence_refs,
        "verifier_ids": _extract_signal_verifier_ids(signal),
        "metadata": {
            "spec_fingerprint": spec_fingerprint,
            "matched_in": spec_match.get("matched_in", ""),
            "candidate_matches": spec_match.get("candidate_matches", []),
        },
    }


def _create_expansion_work_item(
    expansion: dict[str, Any],
    signal: dict[str, Any],
    owner_slice_id: str,
    owner_shape_id: str,
    run_id: str,
    created_in_phase: PhaseId,
    required_change_type: str,
) -> dict[str, Any]:
    """Create a routed expansion work item for underspecified needs."""
    # IMPL(single-layer): Expansion/spec-change work items should be able to carry
    # `requires_verifier_refresh=True` + verifier identifiers when shape/spec
    # contracts change (evaluation modification #3).
    from spec_manager.orchestration.coordination.work_items import _fingerprint

    expansion_id = str(expansion.get("expansion_id", "")).strip()
    artifact_key = str(expansion.get("artifact_key", "")).strip()
    reason = str(expansion.get("reason", "underspecified")).strip() or "underspecified"
    summary = str((signal.get("need") or {}).get("summary", "")).strip()
    spec_text = summary or f"Expand spec coverage for {artifact_key or 'unspecified artifact'}."
    identity_seed = f"expansion|{expansion_id}|{artifact_key}|{reason}|{spec_text}"
    work_item_id = hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()[:16]
    spec_fingerprint = _fingerprint(spec_text)

    spec_refs = signal.get("spec_refs", [])
    first_ref = spec_refs[0] if isinstance(spec_refs, list) and spec_refs else {}
    if not isinstance(first_ref, dict):
        first_ref = {}
    file_path = str(first_ref.get("source_file", "")).strip()
    symbol = str(first_ref.get("source_symbol", "")).strip()
    line_hint_raw = first_ref.get("source_line_hint", 0)
    try:
        line_hint = int(line_hint_raw or 0)
    except (TypeError, ValueError):
        line_hint = 0
    line_start = line_hint if line_hint > 0 else None
    normalized_change_type = _normalize_required_change_type(
        required_change_type,
        default="spec_change",
    )
    evidence_refs = _build_signal_evidence_refs(signal)
    if artifact_key:
        evidence_refs = _dedupe_preserve_order(
            [*evidence_refs, f"artifact:{artifact_key}"]
        )

    return {
        "work_item_id": work_item_id,
        "run_id": run_id,
        "slice_id": owner_slice_id,
        "title": spec_text,
        "description": spec_text,
        "shape_id": owner_shape_id,
        "created_in_phase": created_in_phase,
        "required_change_type": normalized_change_type,
        "status": "NEW",
        "priority": "high",
        "file_locations": (
            [
                {
                    "file_path": file_path,
                    "line_start": line_start,
                    "line_end": line_start,
                    "symbol": symbol or None,
                }
            ]
            if file_path or symbol
            else []
        ),
        "kind": "SPEC_WORK",
        "evidence_refs": evidence_refs,
        "verifier_ids": _extract_signal_verifier_ids(signal),
        "metadata": {
            "spec_fingerprint": spec_fingerprint,
            "expansion_id": expansion_id,
            "artifact_key": artifact_key,
            "reason": reason,
            "requested_by_slice_id": str(signal.get("slice_id", "")).strip(),
            "signal_id": str(signal.get("signal_id", "")).strip(),
        },
    }


def _build_signal_evidence_refs(signal: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    signal_id = str(signal.get("signal_id", "")).strip()
    if signal_id:
        refs.append(f"signal:{signal_id}")
    spec_refs = signal.get("spec_refs", [])
    if isinstance(spec_refs, list):
        for ref in spec_refs:
            if not isinstance(ref, dict):
                continue
            source_file = str(ref.get("source_file", "")).strip()
            source_symbol = str(ref.get("source_symbol", "")).strip()
            source_line = ref.get("source_line_hint", 0)
            try:
                line_hint = int(source_line or 0)
            except (TypeError, ValueError):
                line_hint = 0
            if source_file and line_hint > 0:
                refs.append(f"{source_file}:{line_hint}")
            elif source_file:
                refs.append(source_file)
            if source_symbol:
                refs.append(f"symbol:{source_symbol}")
    return _dedupe_preserve_order(refs)


def _build_spec_match_evidence_refs(
    spec_match: dict[str, Any],
    *,
    signal: dict[str, Any],
) -> list[str]:
    refs = _build_signal_evidence_refs(signal)
    file_path = str(spec_match.get("file", "")).strip()
    line_hint_raw = spec_match.get("line_hint", 0)
    try:
        line_hint = int(line_hint_raw or 0)
    except (TypeError, ValueError):
        line_hint = 0
    matched_in = str(spec_match.get("matched_in", "")).strip()
    if file_path and line_hint > 0:
        refs.append(f"{file_path}:{line_hint}")
    elif file_path:
        refs.append(file_path)
    if matched_in:
        refs.append(f"matched_in:{matched_in}")
    return _dedupe_preserve_order(refs)


_L1_EXTERNAL_DEP_KEYWORDS = (
    "external dependency",
    "third-party",
    "third party",
    "dependency",
    "package",
    "sdk",
    "vendor",
)
_L1_INFRA_KEYWORDS = (
    "storage",
    "database",
    "db",
    "cache",
    "concurrency",
    "concurrent",
    "async",
    "thread",
    "lock",
    "race",
    "parallel",
    "io",
    "i/o",
    "network",
    "socket",
    "http",
    "file system",
    "filesystem",
    "security",
    "auth",
    "authentication",
    "authorization",
    "encryption",
    "credential",
    "secret",
    "token",
)


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


def _coerce_positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(default, 0)
    return max(parsed, 0)


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


def _l1_pipeline_triggers(gaps: list[dict[str, Any]]) -> dict[str, Any]:
    labels: set[str] = set()
    for gap in gaps:
        text_parts: list[str] = []
        for key in ("target", "description", "summary", "kind", "approach"):
            value = gap.get(key)
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip().lower())
        for key in ("dependencies", "target_files", "pin_refs"):
            value = gap.get(key)
            if isinstance(value, list):
                text_parts.extend(str(item).strip().lower() for item in value if str(item).strip())
        gap_text = " ".join(text_parts)
        if any(keyword in gap_text for keyword in _L1_EXTERNAL_DEP_KEYWORDS):
            labels.add("external_dep")
        if any(keyword in gap_text for keyword in _L1_INFRA_KEYWORDS):
            labels.add("infra")
    return {
        "trigger_labels": sorted(labels),
        "introduces_external_dep": "external_dep" in labels,
        "introduces_infra": "infra" in labels,
        "triggered": bool(labels),
    }


def _should_run_l1_planning_session(ctx: Any, gaps: list[dict[str, Any]]) -> bool:
    metadata = getattr(ctx, "metadata", {})
    if isinstance(metadata, dict):
        if _coerce_bool(metadata.get("introduces_external_dep", False)):
            return True
        if _coerce_bool(metadata.get("introduces_infra", False)):
            return True
        if _coerce_bool(metadata.get("cross_library_contract", False)):
            return True
    return bool(_l1_pipeline_triggers(gaps)["triggered"])


def _compose_l1_interactive_questions(
    events: list[dict[str, Any]],
    func_nodes: list[dict[str, Any]],
    node_lookup: dict[str, dict[str, Any]],
) -> list[str]:
    questions: list[str] = []
    for event in events:
        target = str(event.get("target", "")).strip()
        base_question = str(event.get("question", event.get("description", ""))).strip()
        if not base_question and target:
            base_question = f"What requirement should govern {target}?"
        if not base_question:
            base_question = "What requirement should govern this unresolved change?"

        matched = _match_gap_to_node(target, func_nodes, node_lookup) if target else None
        context_parts: list[str] = []
        if matched:
            name = str(matched.get("name", "")).strip()
            file_name = str(matched.get("file", "")).strip()
            if name and file_name:
                context_parts.append(f"code target: {name} in {file_name}")
            elif name:
                context_parts.append(f"code target: {name}")
            spec_ref = str(matched.get("spec_comment_ref", "")).strip()
            if spec_ref:
                context_parts.append(f"spec reference: {spec_ref}")

        reason = str(event.get("reason", "")).strip()
        if reason:
            context_parts.append(f"why unresolved: {reason}")
        if context_parts:
            base_question = f"{base_question} Context: {'; '.join(context_parts)}."
        questions.append(base_question)
    return questions


def _build_expansion(
    signal: dict[str, Any],
    need: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Build a spec expansion request for underspecified needs."""
    import uuid as _uuid

    return {
        "expansion_id": _uuid.uuid4().hex[:12],
        "artifact_key": need.get("artifact_key", ""),
        "reason": need.get("reason", "underspecified"),
        "signal_id": signal.get("signal_id", ""),
        "slice_id": getattr(ctx, "slice_id", ""),
    }
