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

        if self._constraints_store_adapter is not None:
            decision_requirements = _extract_decision_requirements(gaps)
            if decision_requirements:
                plan["decision_requirements"] = decision_requirements

        return plan

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
        - action: "WAIT_ON_WORK_ITEM" | "ROUTE_AND_WAIT" | "EXPAND_SPEC" | "NOOP"
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
        coverage = str(search_outcome.get("coverage", "NONE")).upper()
        confidence = float(search_outcome.get("confidence", 0.0) or 0.0)
        why = str(search_outcome.get("why", ""))

        if coverage == "FULL" and primary_match is not None:
            if primary_match.status in ("MERGED", "DONE"):
                return {
                    "action": "WAKE_IMMEDIATELY",
                    "monitors": [],
                    "coverage": coverage,
                    "confidence": confidence,
                    "why": why,
                    "primary_match": primary_match.to_dict(),
                    "secondary_matches": [m.to_dict() for m in secondary_matches],
                }

            monitor = _build_work_item_monitor(
                signal=signal,
                work_item_dict=primary_match.to_dict(),
                ctx=ctx,
            )
            return {
                "action": "WAIT_ON_WORK_ITEM",
                "monitors": [monitor],
                "coverage": coverage,
                "confidence": confidence,
                "why": why,
                "primary_match": primary_match.to_dict(),
                "secondary_matches": [m.to_dict() for m in secondary_matches],
            }

        if coverage == "PARTIAL":
            candidate_matches = [m for m in [primary_match, *secondary_matches] if m is not None]
            active_matches = [m for m in candidate_matches if m.status not in ("MERGED", "DONE")]
            if active_matches:
                monitor = _build_partial_match_monitor(
                    signal=signal, matches=active_matches, ctx=ctx
                )
                return {
                    "action": "WAIT_ON_WORK_ITEM",
                    "monitors": [monitor],
                    "coverage": coverage,
                    "confidence": confidence,
                    "why": why,
                    "primary_match": primary_match.to_dict() if primary_match is not None else None,
                    "secondary_matches": [m.to_dict() for m in secondary_matches],
                }

        spec_match = _search_spec_catalog(workspace_root, need, spec_refs)
        if spec_match:
            new_work_item = _create_work_item_from_spec(spec_match, ctx)
            monitor = _build_git_symbol_monitor(
                signal=signal,
                need=need,
                ctx=ctx,
            )
            return {
                "action": "ROUTE_AND_WAIT",
                "monitors": [monitor],
                "routing": [new_work_item],
                "coverage": "NONE",
            }

        expansion = _build_expansion(signal, need, ctx)
        monitor = _build_expansion_monitor(signal, expansion, ctx)
        return {
            "action": "EXPAND_SPEC",
            "monitors": [monitor],
            "expansion": expansion,
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
        "kind": "work_item_status",
        "signal_id": signal.get("signal_id", ""),
        "run_id": getattr(ctx, "run_id", ""),
        "timeout_seconds": 3600,
    }


def _build_partial_match_monitor(
    signal: dict[str, Any],
    matches: list[Any],
    ctx: Any,
) -> dict[str, Any]:
    """Build OR-monitor when multiple work items partially cover a need."""
    sub_conditions: list[dict[str, Any]] = []
    for m in matches:
        sub_conditions.append(
            {
                "type": "work_item_done",
                "work_item_id": m.work_item_id,
                "required_status": "MERGED",
            }
        )
        sub_conditions.append(
            {
                "type": "work_item_done",
                "work_item_id": m.work_item_id,
                "required_status": "DONE",
            }
        )

    return {
        "type": "compound",
        "operator": "OR",
        "conditions": sub_conditions,
        "kind": "work_item_status_any",
        "signal_id": signal.get("signal_id", ""),
        "run_id": getattr(ctx, "run_id", ""),
        "timeout_seconds": 3600,
    }


def _build_git_symbol_monitor(
    signal: dict[str, Any],
    need: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Build a monitor payload that watches for a symbol to appear."""
    artifact_key = need.get("artifact_key", "")
    return {
        "type": "git_symbol_exists",
        "symbol_fqn": artifact_key,
        "artifact_key": artifact_key,
        "kind": "symbol_available",
        "signal_id": signal.get("signal_id", ""),
        "run_id": getattr(ctx, "run_id", ""),
        "timeout_seconds": 3600,
    }


def _build_expansion_monitor(
    signal: dict[str, Any],
    expansion: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Build an expansion monitor payload."""
    return {
        "kind": "spec_expanded",
        "expansion_id": expansion.get("expansion_id", ""),
        "signal_id": signal.get("signal_id", ""),
        "run_id": getattr(ctx, "run_id", ""),
        "timeout_seconds": 7200,
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
    ctx: Any,
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
        "owner_slice_id": getattr(ctx, "slice_id", ""),
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


_SENSITIVE_KEYWORDS: dict[str, str] = {
    "external": "Which external dependency should be used and why?",
    "dependency": "Which external dependency should be used and why?",
    "security": "What security approach should be adopted?",
    "auth": "What authentication/authorization strategy should be used?",
    "payment": "Which payment provider should be integrated?",
    "encryption": "What encryption strategy should be used?",
    "credential": "How should credentials be managed?",
}


def _extract_decision_requirements(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract decision requirements from gaps with sensitive dimensions."""
    requirements: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for gap in gaps:
        description = (gap.get("description", "") or "").lower()
        for keyword, question in _SENSITIVE_KEYWORDS.items():
            if keyword in description and question not in seen_questions:
                seen_questions.add(question)
                requirements.append(
                    {
                        "question": question,
                        "trigger": keyword,
                        "gap_target": gap.get("target", ""),
                    }
                )
    return requirements


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
