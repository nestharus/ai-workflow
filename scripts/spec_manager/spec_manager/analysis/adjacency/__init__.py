"""Adjacency detection for algorithmic dependency analysis.

Constructs and unions four graph types (call, event, store touch, co-occurrence)
to detect disconnected components and reveal missed dependencies.
"""

from __future__ import annotations

from spec_manager.analysis.adjacency.adapters import (
    cooccurrence_from_atom_sections,
    graph_to_atom_adjacency,
    store_touch_from_definitions,
)
from spec_manager.analysis.adjacency.detector import (
    AdjacencyReport,
    ComponentReport,
    IsolationClassification,
    build_unified_graph,
    detect_disconnected_components,
)
from spec_manager.analysis.adjacency.graph import (
    AdjacencyGraph,
    Edge,
    EdgeSignal,
    NodeInfo,
    SignalType,
)
from spec_manager.analysis.adjacency.runner import (
    AdjacencyAnalysisConfig,
    run_adjacency_analysis,
    save_report,
)

__all__ = [
    "AdjacencyAnalysisConfig",
    "AdjacencyGraph",
    "AdjacencyReport",
    "ComponentReport",
    "Edge",
    "EdgeSignal",
    "IsolationClassification",
    "NodeInfo",
    "SignalType",
    "build_unified_graph",
    "cooccurrence_from_atom_sections",
    "detect_disconnected_components",
    "graph_to_atom_adjacency",
    "run_adjacency_analysis",
    "save_report",
    "store_touch_from_definitions",
]
