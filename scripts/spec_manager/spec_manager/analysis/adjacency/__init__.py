"""Adjacency detection from unified relationship facts."""

from __future__ import annotations

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
    "detect_disconnected_components",
    "run_adjacency_analysis",
    "save_report",
]
