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
