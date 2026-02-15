"""L1 layer planner — code-as-spec skeleton analysis.

L1 works with PDD skeleton files that contain spec comments and function
stubs.  It discovers code concerns (functions, classes, spec-comment blocks)
and produces function-level implementation intentions.

The planner delegates heavy lifting to injected tools (research, integration,
evidence) so it stays decoupled from the refinement and orchestration layers.
When no tool is supplied the corresponding step is simply skipped.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


class L1Planner:
    """LayerPlanner implementation for the L1 (code-as-spec) layer.

    Parameters
    ----------
    research_tool:
        Optional callable used to perform LLM-backed research queries
        against slice context.
    integration_tool:
        Optional callable used to check integration constraints between
        functions / files within the slice.
    evidence_tool:
        Optional callable used to look up evidence bundles for under-spec
        resolution and signal handling.
    """

    def __init__(
        self,
        research_tool: Callable[..., Any] | None = None,
        integration_tool: Callable[..., Any] | None = None,
        evidence_tool: Callable[..., Any] | None = None,
        constraints_tool: Any = None,
        constraints_store_adapter: Any = None,
    ) -> None:
        self.layer: Literal["l1"] = "l1"
        self._research_tool = research_tool
        self._integration_tool = integration_tool
        self._evidence_tool = evidence_tool
        self._constraints_tool = constraints_tool
        self._constraints_store_adapter = constraints_store_adapter

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    def discover(self, ctx: Any) -> dict[str, Any]:
        """Build a code-as-spec skeleton graph from slice files.

        Reads every text file under ``ctx.slice_root``, classifies each
        into skeleton nodes (function / class / spec_comment_block) and
        best-effort edges (declares / mentions / calls).

        Returns a dict with ``nodes`` and ``edges`` lists plus a
        ``file_index`` mapping filenames to their node ids.
        """
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if slice_root is None or not slice_root.exists():
            logger.warning("L1 discover: slice_root missing or does not exist (%s)", ctx.slice_root)
            return {"nodes": [], "edges": [], "file_index": {}}

        files = _collect_slice_files(slice_root)
        if not files:
            return {"nodes": [], "edges": [], "file_index": {}}

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        file_index: dict[str, list[str]] = {}

        for rel_path, content in files.items():
            file_nodes, file_edges = _parse_skeleton_file(rel_path, content)
            nodes.extend(file_nodes)
            edges.extend(file_edges)
            file_index[rel_path] = [n["id"] for n in file_nodes]

        return {
            "nodes": nodes,
            "edges": edges,
            "file_index": file_index,
        }

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce function implementation intentions from gaps + discovery.

        Each intention is a dict with keys:
        ``function_name``, ``file``, ``approach``, ``spec_comment_ref``,
        ``dependencies``.
        """
        nodes = discovery.get("nodes", [])
        func_nodes = [n for n in nodes if n.get("kind") == "function"]
        node_lookup = {n["id"]: n for n in nodes}

        intentions: list[dict[str, Any]] = []

        for gap in gaps:
            target = gap.get("target", "")
            matched_node = _match_gap_to_node(target, func_nodes, node_lookup)
            intention: dict[str, Any] = {
                "function_name": matched_node.get("name", target) if matched_node else target,
                "file": matched_node.get("file", "") if matched_node else "",
                "approach": gap.get("description", gap.get("approach", "")),
                "spec_comment_ref": matched_node.get("spec_comment_ref", "")
                if matched_node
                else "",
                "dependencies": gap.get("dependencies", []),
            }
            intentions.append(intention)

        # If no gaps were supplied, generate one intention per undiscovered
        # function node so the plan is never empty when discovery found code.
        if not gaps and func_nodes:
            for fn in func_nodes:
                intentions.append(
                    {
                        "function_name": fn.get("name", ""),
                        "file": fn.get("file", ""),
                        "approach": "",
                        "spec_comment_ref": fn.get("spec_comment_ref", ""),
                        "dependencies": [],
                    }
                )

        plan: dict[str, Any] = {"intentions": intentions}
        if self._constraints_store_adapter is None:
            return plan
        if not _should_run_l1_planning_session(ctx, gaps):
            return plan

        pipeline_outputs = self._build_plan_via_strategies(ctx, gaps, discovery)
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
    ) -> dict[str, Any]:
        """Run the shared planning-session strategies for L1 decisions."""
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
        mode = _normalize_mode(getattr(ctx, "mode", "auto"))
        metadata = getattr(ctx, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        triggers = _l1_pipeline_triggers(gaps)
        touched_files_count = _coerce_positive_int(
            metadata.get("touched_files_count", 0),
            default=_estimate_touched_files(gaps),
        )
        session_ctx: dict[str, Any] = {
            "layer": "L1",
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
            "pipeline_triggers": list(triggers["trigger_labels"]),
        }

        session = PlanningSession(
            ctx=session_ctx,
            gaps=gaps,
            discovery=discovery,
        )
        strategies = [
            ImpactClassifierStrategy(),
            ConstraintCollectionStrategy(workspace_root),
            TradeoffMapperStrategy(workspace_root),
            ProblemFramerStrategy(run_agent=self._research_tool),
            ConstraintEnricherStrategy(run_agent=self._research_tool),
            NonSoftwareChecklistStrategy(),
            AuthorityDeciderStrategy(workspace_root),
            QuestionComposerStrategy(run_agent=self._research_tool),
        ]
        runner = PlanningSessionRunner(strategies)
        session = runner.run(session)

        result: dict[str, Any] = {}
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
        """Attempt to resolve under-spec events using local code context.

        Resolution strategy (in order):
        1. Match event target against skeleton nodes — if spec comments
           provide enough context, resolve locally.
        2. Delegate to ``evidence_tool`` if available.
        3. Block with questions for human review.
        """
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

        for event in events:
            target = event.get("target", "")
            matched = _match_gap_to_node(target, func_nodes, node_lookup)

            # Strategy 1: local skeleton context
            if matched and matched.get("spec_comment_ref"):
                resolved.append(
                    {
                        "event": event,
                        "resolution": "local_context",
                        "spec_comment_ref": matched["spec_comment_ref"],
                    }
                )
                continue

            # Strategy 2: evidence tool
            if self._evidence_tool is not None:
                try:
                    evidence_result = self._evidence_tool(target, ctx)
                    if evidence_result:
                        resolved.append(
                            {
                                "event": event,
                                "resolution": "evidence_tool",
                                "detail": evidence_result,
                            }
                        )
                        continue
                except Exception:
                    logger.debug("Evidence tool raised for target=%s", target, exc_info=True)

            # Strategy 3: block
            unresolved.append(event)

        blocked = len(unresolved) > 0
        questions = [
            e.get("question", f"Cannot resolve: {e.get('target', '?')}") for e in unresolved
        ]

        return {
            "blocked": blocked,
            "questions": questions,
            "resolved": resolved,
            "constraints": {},
        }

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        """Try to resolve an ambiguity signal from skeleton context.

        Falls back to the evidence tool if one is wired.  Returns a
        resolution dict or ``None`` when nothing can be done.
        """
        if signal is None:
            return None

        # Extract a target string from various signal shapes.
        if isinstance(signal, dict):
            target = signal.get("target", signal.get("name", ""))
        else:
            target = getattr(signal, "target", getattr(signal, "name", ""))

        if not target:
            return None

        # Evidence tool lookup
        if self._evidence_tool is not None:
            try:
                result = self._evidence_tool(target, ctx)
                if result:
                    return {"resolution": "evidence_tool", "target": target, "detail": result}
            except Exception:
                logger.debug("Evidence tool raised for signal target=%s", target, exc_info=True)

        return None

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        """Triage a coordination signal from a halted L1 agent.

        Algorithm:
        1. Search work items by spec text + artifact channel
        2. Classify: in-progress / unrouted / underspecified
        3. Return action + monitor specs

        Returns dict with:
        - action: ("WAIT_ON_WORK_ITEM" | "ROUTE_AND_WAIT" | "EXPAND_SPEC"
                  | "WAKE_IMMEDIATELY" | "NOOP")
        - monitors: list[dict]  (MonitorSpec-compatible dicts)
        - routing: list[dict]  (new work items to route, if any)
        - expansion: dict | None  (spec expansion details, if needed)
        """
        from spec_manager.orchestration.coordination.work_items import (
            SearchQuery,
            WorkItemStore,
        )

        need = signal.get("need", {})
        spec_refs = signal.get("spec_refs", [])
        search_hints = signal.get("search_hints", {})

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
            spec_refs=spec_refs if isinstance(spec_refs, list) else [],
            keywords=keywords,
        )

        workspace_root = Path(ctx.workspace_root) if ctx.workspace_root else None
        if not workspace_root:
            return {"action": "NOOP", "monitors": []}

        coordination_dir = workspace_root / ".pdd_runs" / ctx.run_id / "coordination"
        store = WorkItemStore(coordination_dir, semantic_rerank_tool=self._research_tool)
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
            if primary_match.status in ("MERGED", "DONE"):
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
            active_matches = [m for m in candidate_matches if m.status not in ("MERGED", "DONE")]
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

        spec_match = _search_spec_catalog(workspace_root, need, spec_refs)
        if spec_match:
            owner_slice_id = _resolve_owner_slice_id(
                workspace_root=workspace_root,
                run_id=str(getattr(ctx, "run_id", "") or ""),
                spec_match=spec_match,
                search_hints=search_hints if isinstance(search_hints, dict) else {},
                fallback_slice_id=str(getattr(ctx, "slice_id", "") or ""),
            )
            new_work_item = _create_work_item_from_spec(
                spec_match=spec_match,
                owner_slice_id=owner_slice_id,
            )
            monitor = _build_git_symbol_monitor(
                signal=signal,
                need=need,
                ctx=ctx,
                work_item_dict=new_work_item,
            )
            if monitor is None:
                monitor = _build_work_item_monitor(
                    signal=signal,
                    work_item_dict=new_work_item,
                    ctx=ctx,
                )
            return {
                "action": "ROUTE_AND_WAIT",
                "monitors": [monitor],
                "routing": [new_work_item],
                "coverage": "NO_COVERAGE",
                "confidence": confidence,
                "why": why or "spec_found_unrouted",
                "missing_detail": "",
            }

        expansion = _build_expansion(signal, need, ctx)
        expansion_owner_slice_id = _resolve_owner_slice_id(
            workspace_root=workspace_root,
            run_id=str(getattr(ctx, "run_id", "") or ""),
            spec_match={},
            search_hints=search_hints if isinstance(search_hints, dict) else {},
            fallback_slice_id=str(getattr(ctx, "slice_id", "") or ""),
        )
        expansion_work_item = _create_expansion_work_item(
            expansion=expansion,
            signal=signal,
            owner_slice_id=expansion_owner_slice_id,
        )
        monitor = _build_work_item_monitor(
            signal=signal,
            work_item_dict=expansion_work_item,
            ctx=ctx,
            monitor_kind="spec_expanded",
        )
        return {
            "action": "EXPAND_SPEC",
            "monitors": [monitor],
            "routing": [expansion_work_item],
            "expansion": expansion,
            "coverage": "NO_COVERAGE",
            "confidence": confidence,
            "why": why or "underspecified_no_spec_match",
            "missing_detail": missing_detail
            or str(need.get("summary", "")).strip()
            or "Missing spec-level behavior needed by blocked consumer.",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TEXT_SUFFIXES = frozenset({".py", ".md", ".txt", ".yaml", ".yml", ".toml", ".json", ".rst"})


def _collect_slice_files(root: Path) -> dict[str, str]:
    """Return ``{relative_path: content}`` for readable text files under *root*."""
    files: dict[str, str] = {}
    if not root.is_dir():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(root))
        files[rel] = content
    return files


def _parse_skeleton_file(
    rel_path: str, content: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Lightweight structural scan of a skeleton file.

    Produces *nodes* (function / class / spec_comment_block) and *edges*
    (declares / mentions) using simple line-based heuristics.  This is
    intentionally NOT a language parser — real analysis is deferred to
    LLM calls wired in later.
    """
    from spec_manager.core.language import CLASS_KEYWORDS, COMMENT_PREFIX, FUNCTION_KEYWORDS

    comment_char = COMMENT_PREFIX.rstrip()  # e.g. "#"

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    current_spec_block: list[str] | None = None
    spec_block_start: int | None = None

    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()

        # Spec-comment blocks: contiguous lines starting with comment prefix
        if stripped.startswith(comment_char) and not stripped.startswith("#!"):
            if current_spec_block is None:
                current_spec_block = []
                spec_block_start = lineno
            current_spec_block.append(stripped.lstrip("# "))
            continue

        # Flush accumulated spec-comment block
        if current_spec_block is not None:
            block_id = f"{rel_path}:spec:{spec_block_start}"
            nodes.append(
                {
                    "id": block_id,
                    "kind": "spec_comment_block",
                    "file": rel_path,
                    "line": spec_block_start,
                    "text": "\n".join(current_spec_block),
                }
            )
            current_spec_block = None
            spec_block_start = None

        # Function definitions
        if any(stripped.startswith(kw) for kw in FUNCTION_KEYWORDS):
            matched_kw = next(kw for kw in FUNCTION_KEYWORDS if stripped.startswith(kw))
            name = _extract_name(stripped, matched_kw)
            node_id = f"{rel_path}:function:{name}"
            spec_ref = (
                nodes[-1]["id"] if nodes and nodes[-1]["kind"] == "spec_comment_block" else ""
            )
            nodes.append(
                {
                    "id": node_id,
                    "kind": "function",
                    "name": name,
                    "file": rel_path,
                    "line": lineno,
                    "spec_comment_ref": spec_ref,
                }
            )
            if spec_ref:
                edges.append({"source": spec_ref, "target": node_id, "kind": "declares"})

        # Class definitions
        elif any(stripped.startswith(kw) for kw in CLASS_KEYWORDS):
            matched_kw = next(kw for kw in CLASS_KEYWORDS if stripped.startswith(kw))
            name = _extract_name(stripped, matched_kw)
            node_id = f"{rel_path}:class:{name}"
            nodes.append(
                {
                    "id": node_id,
                    "kind": "class",
                    "name": name,
                    "file": rel_path,
                    "line": lineno,
                }
            )

    # Flush trailing spec-comment block
    if current_spec_block is not None:
        block_id = f"{rel_path}:spec:{spec_block_start}"
        nodes.append(
            {
                "id": block_id,
                "kind": "spec_comment_block",
                "file": rel_path,
                "line": spec_block_start,
                "text": "\n".join(current_spec_block),
            }
        )

    return nodes, edges


def _extract_name(line: str, keyword: str) -> str:
    """Pull the identifier immediately after *keyword* (``def `` or ``class ``)."""
    rest = line[len(keyword) :]
    name = ""
    for ch in rest:
        if ch in ("(", ":", " ", "\t"):
            break
        name += ch
    return name


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
        monitors.append(
            {
                "type": "work_item_done",
                "work_item_id": m.work_item_id,
                "required_status": "MERGED",
                "kind": "work_item_status",
                "signal_id": signal.get("signal_id", ""),
                "run_id": getattr(ctx, "run_id", ""),
                "timeout_seconds": 3600,
            }
        )
        monitors.append(
            {
                "type": "work_item_done",
                "work_item_id": m.work_item_id,
                "required_status": "DONE",
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
    location = (
        work_item_dict.get("location", {})
        if isinstance(work_item_dict, dict) and isinstance(work_item_dict.get("location"), dict)
        else {}
    )
    item_symbol = str(location.get("symbol", "")).strip()
    item_file = str(location.get("file", "")).strip()
    artifact_key = str(need.get("artifact_key", "")).strip()
    symbol_fqn = item_symbol or artifact_key
    if not symbol_fqn:
        return None
    if "." not in symbol_fqn and "::" not in symbol_fqn and symbol_fqn.lower() == symbol_fqn:
        return None
    file_glob = item_file or str(need.get("file_glob", "")).strip() or "**/*.py"
    symbol_leaf = symbol_fqn.split(".")[-1] if "." in symbol_fqn else symbol_fqn
    return {
        "type": "git_symbol_exists",
        "symbol_fqn": symbol_fqn,
        "artifact_key": artifact_key or symbol_fqn,
        "ref": "HEAD",
        "file_glob": file_glob,
        "signature_regex": rf"\b{re.escape(symbol_leaf)}\b",
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
    summary = str(work_item_dict.get("spec_text", "")).strip()
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
        return possible_owner_slices[0]

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


def _search_spec_catalog(
    workspace_root: Path,
    need: dict[str, Any],
    spec_refs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Search for matching spec text in workspace slice files.

    Scans .py and .md files under the workspace for spec comment blocks
    that mention the needed artifact.  Returns a match dict on success,
    None if nothing found.
    """
    # Prefer verbatim signal spec references when provided.
    for ref in spec_refs:
        if not isinstance(ref, dict):
            continue
        spec_text = str(ref.get("spec_text", "")).strip()
        if not spec_text:
            continue
        return {
            "spec_text": spec_text,
            "file": str(ref.get("source_file", "")).strip(),
            "symbol": str(ref.get("source_symbol", "")).strip(),
            "line_hint": int(ref.get("source_line_hint", 0) or 0),
            "matched_in": "signal_spec_ref",
        }

    artifact_key = str(need.get("artifact_key", "")).strip()
    if not artifact_key:
        return None

    search_terms = [artifact_key.lower(), *_extract_artifact_channel_tokens(artifact_key)]
    search_terms = [term for term in _dedupe_preserve_order(search_terms) if term]
    if not search_terms:
        return None

    for path in sorted(workspace_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        content_lower = content.lower()
        if not any(term in content_lower for term in search_terms):
            continue

        rel = str(path.relative_to(workspace_root))
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            line_lower = line.lower()
            if not any(term in line_lower for term in search_terms):
                continue
            spec_text, line_hint = _extract_nearest_spec_text(lines, idx)
            if spec_text:
                return {
                    "spec_text": spec_text,
                    "file": rel,
                    "symbol": "",
                    "line_hint": line_hint,
                    "matched_in": "spec_catalog_scan",
                }

    return None


def _create_work_item_from_spec(
    spec_match: dict[str, Any],
    owner_slice_id: str,
) -> dict[str, Any]:
    """Create a work-item dict from a spec catalog match."""
    from spec_manager.orchestration.coordination.work_items import _fingerprint

    spec_text = str(spec_match.get("spec_text", "")).strip()
    file_path = str(spec_match.get("file", "")).strip()
    symbol = str(spec_match.get("symbol", "")).strip()
    line_hint = int(spec_match.get("line_hint", 0) or 0)
    spec_fingerprint = _fingerprint(spec_text) if spec_text else ""
    identity_seed = f"{spec_fingerprint}|{file_path}|{symbol}|{line_hint}"
    work_item_id = hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()[:16]

    return {
        "work_item_id": work_item_id,
        "spec_text": spec_text,
        "file": file_path,
        "owner_slice_id": owner_slice_id,
        "status": "NEW",
        "location": {
            "file": file_path,
            "symbol": symbol,
            "line_hint": line_hint,
        },
        "kind": "SPEC_WORK",
        "metadata": {
            "spec_fingerprint": spec_fingerprint,
            "matched_in": spec_match.get("matched_in", ""),
        },
    }


def _create_expansion_work_item(
    expansion: dict[str, Any],
    signal: dict[str, Any],
    owner_slice_id: str,
) -> dict[str, Any]:
    """Create a routed expansion work item for underspecified needs."""
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

    return {
        "work_item_id": work_item_id,
        "spec_text": spec_text,
        "owner_slice_id": owner_slice_id,
        "status": "NEW",
        "location": {
            "file": file_path,
            "symbol": symbol,
            "line_hint": line_hint,
        },
        "kind": "EXPANSION",
        "metadata": {
            "spec_fingerprint": spec_fingerprint,
            "expansion_id": expansion_id,
            "artifact_key": artifact_key,
            "reason": reason,
            "requested_by_slice_id": str(signal.get("slice_id", "")).strip(),
            "signal_id": str(signal.get("signal_id", "")).strip(),
        },
    }


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
