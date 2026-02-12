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
    """

    def __init__(
        self,
        research_tool: _ToolFn = None,
        integration_tool: _ToolFn = None,
        evidence_tool: _ToolFn = None,
        constraints_tool: _ToolFn = None,
    ) -> None:
        self.layer: Literal["l2"] = "l2"
        self._research_tool = research_tool
        self._integration_tool = integration_tool
        self._evidence_tool = evidence_tool
        self._constraints_tool = constraints_tool

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

        if self._integration_tool is not None:
            try:
                enriched = self._integration_tool(
                    workspace_root=workspace_root,
                    arch_files=arch_files,
                )
                if isinstance(enriched, dict):
                    topology["nodes"] = enriched.get("nodes", [])
                    topology["edges"] = enriched.get("edges", [])
            except Exception:
                logger.warning(
                    "L2 integration_tool failed; using lightweight topology",
                    exc_info=True,
                )

        logger.debug(
            "L2 discover: %d arch files, %d nodes, %d edges",
            len(arch_files),
            len(topology["nodes"]),
            len(topology["edges"]),
        )
        return topology

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce wiring intentions from *gaps* and architecture *discovery*.

        Each intention contains:
        - ``component_id``: target component
        - ``target_files``: files to touch
        - ``approach``: human-readable description
        - ``pin_refs``: related pins / edges
        - ``dependencies``: other component ids this depends on

        If a ``research_tool`` is available it is called with the gaps
        and topology for LLM-driven intention generation.  Otherwise a
        one-to-one gap-to-intention mapping is produced locally.
        """
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

        # Fallback: produce a minimal intention per gap.
        intentions: list[dict[str, Any]] = []
        for gap in gaps:
            intentions.append(
                {
                    "component_id": gap.get("component_id", gap.get("id", "")),
                    "target_files": gap.get("target_files", []),
                    "approach": gap.get("description", gap.get("summary", "")),
                    "pin_refs": gap.get("pin_refs", []),
                    "dependencies": gap.get("dependencies", []),
                }
            )
        return {"intentions": intentions}

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
        topology_nodes = discovery.get("nodes", [])
        topology_edges = discovery.get("edges", [])

        resolved_constraints: dict[str, Any] = {}
        remaining_questions: list[str] = []

        for event in events:
            event_id = event.get("id", "")
            question = event.get("question", event.get("description", ""))

            # Strategy 1: check if any topology node/edge answers this.
            resolved_from_topology = _try_resolve_from_topology(
                question, topology_nodes, topology_edges
            )
            if resolved_from_topology is not None:
                resolved_constraints[event_id] = resolved_from_topology
                continue

            # Strategy 2: evidence lookup.
            if self._evidence_tool is not None:
                try:
                    evidence_hit = self._evidence_tool(
                        query=question,
                        layer="l2",
                        ctx_metadata=getattr(ctx, "metadata", {}),
                    )
                    if evidence_hit:
                        resolved_constraints[event_id] = evidence_hit
                        continue
                except Exception:
                    logger.warning(
                        "L2 evidence_tool failed for event %s",
                        event_id,
                        exc_info=True,
                    )

            # Strategy 3: cannot resolve -- block.
            remaining_questions.append(question)

        blocked = len(remaining_questions) > 0
        return {
            "blocked": blocked,
            "constraints": resolved_constraints,
            "questions": remaining_questions,
        }

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _try_resolve_from_topology(
    question: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Check whether *question* can be answered by existing topology data.

    This is intentionally a placeholder for future LLM-based matching.
    Currently it returns ``None`` unconditionally -- real resolution
    requires an LLM call that will be wired through the tools layer.
    """
    # Future: pass question + topology to an LLM to see if it can derive
    # the answer.  For now, always return None (unresolved).
    return None
