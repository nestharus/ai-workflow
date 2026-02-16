"""Integration analysis tool for the planner.

Performs graph-based integration analysis: skeleton extraction,
diff analysis, blast radius estimation, and risk assessment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IntegrationNode:
    """A node in the integration graph."""

    node_id: str
    node_type: str  # function | class | component | file | pin
    name: str
    file: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntegrationEdge:
    """An edge in the integration graph."""

    source: str  # node_id
    target: str  # node_id
    edge_type: str  # calls | imports | wired_to | depends_on
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntegrationGraph:
    """A lightweight graph of code/architecture relationships."""

    nodes: list[IntegrationNode] = field(default_factory=list)
    edges: list[IntegrationEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": n.node_id, "type": n.node_type, "name": n.name, "file": n.file, **n.metadata}
                for n in self.nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target, "type": e.edge_type, **e.metadata}
                for e in self.edges
            ],
        }


@dataclass
class RiskAssessment:
    """Risk assessment for a proposed change."""

    blast_radius: int = 0  # number of impacted nodes
    risk_level: str = "low"  # low | medium | high
    impacted_files: list[str] = field(default_factory=list)
    rationale: str = ""


class IntegrationAnalyzer:
    """Compute integration diffs and risk profiles from discovery/request payloads."""

    def analyze(self, *, req: Any, discovery: dict[str, Any]) -> dict[str, Any]:
        baseline_graph = self._extract_graph(discovery)
        proposed_graph = self._extract_proposed_graph(req, baseline_graph)

        baseline_nodes = self._node_ids(baseline_graph)
        proposed_nodes = self._node_ids(proposed_graph)
        baseline_edges = self._edge_ids(baseline_graph)
        proposed_edges = self._edge_ids(proposed_graph)

        added_nodes = sorted(proposed_nodes - baseline_nodes)
        removed_nodes = sorted(baseline_nodes - proposed_nodes)
        added_edges = sorted(proposed_edges - baseline_edges)
        removed_edges = sorted(baseline_edges - proposed_edges)

        changed_targets = set(added_nodes + removed_nodes)
        changed_targets.update(self._collect_changed_targets(req))

        impacted_nodes = self._estimate_impacted_nodes(
            graph=proposed_graph,
            changed_nodes=changed_targets,
        )
        impacted_files = sorted(
            {
                str(node.get("file", "")).strip()
                for node in proposed_graph.get("nodes", [])
                if isinstance(node, dict)
                and str(node.get("id", "")).strip() in impacted_nodes
                and str(node.get("file", "")).strip()
            }
        )

        blast_radius = len(impacted_nodes)
        if blast_radius >= 10:
            risk_level = "high"
        elif blast_radius >= 4:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "integration_diff": {
                "added_nodes": added_nodes,
                "removed_nodes": removed_nodes,
                "added_edges": [self._edge_tuple_to_dict(edge) for edge in added_edges],
                "removed_edges": [self._edge_tuple_to_dict(edge) for edge in removed_edges],
            },
            "risk_profile": {
                "blast_radius": blast_radius,
                "risk_level": risk_level,
                "impacted_nodes": sorted(impacted_nodes),
                "impacted_files": impacted_files,
                "rationale": (
                    f"{len(changed_targets)} changed targets affect {blast_radius} reachable nodes"
                ),
            },
        }

    @staticmethod
    def _extract_graph(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"nodes": [], "edges": []}
        if isinstance(payload.get("nodes"), list) and isinstance(payload.get("edges"), list):
            return {
                "nodes": [row for row in payload.get("nodes", []) if isinstance(row, dict)],
                "edges": [row for row in payload.get("edges", []) if isinstance(row, dict)],
            }
        quality_graph = payload.get("quality_graph")
        if isinstance(quality_graph, dict):
            return {
                "nodes": [row for row in quality_graph.get("nodes", []) if isinstance(row, dict)],
                "edges": [row for row in quality_graph.get("edges", []) if isinstance(row, dict)],
            }
        return {"nodes": [], "edges": []}

    def _extract_proposed_graph(self, req: Any, baseline_graph: dict[str, Any]) -> dict[str, Any]:
        inputs = getattr(req, "inputs", {})
        if not isinstance(inputs, dict):
            return baseline_graph
        for key in (
            "proposed_graph",
            "integration_graph",
            "topology",
            "integration_analysis",
        ):
            payload = inputs.get(key)
            if isinstance(payload, dict):
                graph = self._extract_graph(payload)
                if graph["nodes"] or graph["edges"]:
                    return graph
        return baseline_graph

    @staticmethod
    def _node_ids(graph: dict[str, Any]) -> set[str]:
        node_ids: set[str] = set()
        for node in graph.get("nodes", []):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", "")).strip()
            if node_id:
                node_ids.add(node_id)
        return node_ids

    @staticmethod
    def _edge_ids(graph: dict[str, Any]) -> set[tuple[str, str, str]]:
        edge_ids: set[tuple[str, str, str]] = set()
        for edge in graph.get("edges", []):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            edge_type = (
                str(edge.get("type", edge.get("kind", "depends_on"))).strip() or "depends_on"
            )
            if source and target:
                edge_ids.add((source, target, edge_type))
        return edge_ids

    @staticmethod
    def _edge_tuple_to_dict(edge: tuple[str, str, str]) -> dict[str, str]:
        return {"source": edge[0], "target": edge[1], "type": edge[2]}

    @staticmethod
    def _collect_changed_targets(req: Any) -> list[str]:
        inputs = getattr(req, "inputs", {})
        if not isinstance(inputs, dict):
            return []
        changed: list[str] = []
        for key in ("changed_nodes", "impacted_nodes"):
            rows = inputs.get(key)
            if isinstance(rows, list):
                for row in rows:
                    token = str(row).strip()
                    if token:
                        changed.append(token)
        for key in ("gaps", "raw_gaps"):
            rows = inputs.get(key)
            if not isinstance(rows, list):
                continue
            for gap in rows:
                if not isinstance(gap, dict):
                    continue
                for attr in ("component_id", "target", "file"):
                    token = str(gap.get(attr, "")).strip()
                    if token:
                        changed.append(token)
        return changed

    @staticmethod
    def _estimate_impacted_nodes(
        *,
        graph: dict[str, Any],
        changed_nodes: set[str],
    ) -> set[str]:
        adjacency: dict[str, set[str]] = {}
        for edge in graph.get("edges", []):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            if not source or not target:
                continue
            adjacency.setdefault(source, set()).add(target)

        visited: set[str] = set(changed_nodes)
        frontier = list(changed_nodes)
        while frontier:
            current = frontier.pop(0)
            for nxt in adjacency.get(current, set()):
                if nxt in visited:
                    continue
                visited.add(nxt)
                frontier.append(nxt)
        return visited


class IntegrationTool:
    """Planner-facing integration analysis tool.

    Builds lightweight integration graphs from workspace files and
    assesses blast radius / risk for proposed changes.

    Dependencies are injected optionally:
    - source_cache: SourceAnalysisCache for cached code analysis
    """

    def __init__(
        self,
        source_cache: Any = None,
        workspace: Path | None = None,
    ) -> None:
        self._source_cache = source_cache
        self._workspace = workspace
        self._analyzer = IntegrationAnalyzer()

    def analyze(self, *, req: Any, discovery: dict[str, Any]) -> dict[str, Any]:
        """Compute integration-diff and risk payloads for planner routing."""
        return self._analyzer.analyze(req=req, discovery=discovery)

    def build_graph(self, file_paths: list[str]) -> IntegrationGraph:
        """Build an integration graph from the given files.

        Uses source_cache if available for function/class extraction.
        Otherwise returns an empty graph (LLM-based extraction will
        be wired in later steps).
        """
        graph = IntegrationGraph()

        if not self._source_cache:
            return graph

        for fp in file_paths:
            path = Path(fp)
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                analysis = self._source_cache.analyze_with_cache(content, fp)

                # Add function nodes
                for func in analysis.functions:
                    node_id = f"{fp}::{func.name}"
                    graph.nodes.append(
                        IntegrationNode(
                            node_id=node_id,
                            node_type="function",
                            name=func.name,
                            file=fp,
                            metadata={
                                "start_line": func.start_line,
                                "end_line": func.end_line,
                            },
                        )
                    )
            except Exception:
                logger.debug("Failed to analyze %s for integration graph", fp)

        return graph

    def assess_risk(self, graph: IntegrationGraph, changed_nodes: list[str]) -> RiskAssessment:
        """Assess blast radius and risk for changes to the given nodes.

        Walks edges from changed_nodes to find impacted files.
        """
        if not graph.edges:
            return RiskAssessment(
                blast_radius=len(changed_nodes),
                risk_level="low",
                impacted_files=[],
                rationale="No edges in graph; blast radius equals changed set.",
            )

        # BFS from changed nodes
        visited: set[str] = set(changed_nodes)
        frontier = list(changed_nodes)
        while frontier:
            current = frontier.pop(0)
            for edge in graph.edges:
                if edge.source == current and edge.target not in visited:
                    visited.add(edge.target)
                    frontier.append(edge.target)

        impacted_files = list({n.file for n in graph.nodes if n.node_id in visited and n.file})

        blast = len(visited)
        level = "low" if blast <= 3 else ("medium" if blast <= 10 else "high")

        return RiskAssessment(
            blast_radius=blast,
            risk_level=level,
            impacted_files=impacted_files,
            rationale=f"{blast} nodes reachable from {len(changed_nodes)} changed nodes.",
        )
