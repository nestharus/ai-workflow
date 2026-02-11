"""L1 layer planner — code-as-spec skeleton analysis.

L1 works with PDD skeleton files that contain spec comments and function
stubs.  It discovers code concerns (functions, classes, spec-comment blocks)
and produces function-level implementation intentions.

The planner delegates heavy lifting to injected tools (research, integration,
evidence) so it stays decoupled from the refinement and orchestration layers.
When no tool is supplied the corresponding step is simply skipped.
"""

from __future__ import annotations

import logging
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
    ) -> None:
        self.layer: Literal["l1"] = "l1"
        self._research_tool = research_tool
        self._integration_tool = integration_tool
        self._evidence_tool = evidence_tool

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

        return {"intentions": intentions}

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
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    current_spec_block: list[str] | None = None
    spec_block_start: int | None = None

    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()

        # Spec-comment blocks: contiguous lines starting with #
        if stripped.startswith("#") and not stripped.startswith("#!"):
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
        if stripped.startswith("def "):
            name = _extract_name(stripped, "def ")
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
        elif stripped.startswith("class "):
            name = _extract_name(stripped, "class ")
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
