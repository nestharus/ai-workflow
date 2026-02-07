"""Projection module for generating L2 documents from L1 sources.

This module provides:
- generator: Plan projection generator (ALG-PROJ-0001)
- drift: Atom-aware drift comparator (ALG-PROJ-0002/0003)

Phase 7: Projection Pins, Atom-Aware Drift, and Legacy Removal

Imports are lazy to avoid circular import issues with spec_manager.core.gaps.
"""

from __future__ import annotations

from typing import Any

# Lazy imports to avoid circular import with spec_manager.core.gaps
# which transitively imports many modules
__all__ = [
    "AtomAlignment",
    "AtomAwareDriftComparator",
    "AtomDefinition",
    "DataFlowHop",
    "DataFlowTracker",
    "DriftItem",
    "DriftKind",
    "DriftPolicy",
    "DriftReport",
    "ImportEdge",
    "ImportGraph",
    "LineageBuilder",
    "PinChange",
    "PinChangePropagator",
    "PinDrift",
    "PinDriftDetector",
    "ProjectionGenerator",
    "ProjectionLineageEdge",
    "ProjectionLineageTable",
    "ProjectionType",
    "PropagationItem",
    "PropagationReport",
    "SignalSpec",
    "convert_drift_to_gaps",
    "convert_propagation_to_drift",
    "generate_plan_from_libraries",
]


def __getattr__(name: str) -> Any:  # noqa: ANN401
    """Lazy import to avoid circular imports."""
    if name in ("ProjectionGenerator", "generate_plan_from_libraries"):
        from spec_manager.projection.generator import (
            ProjectionGenerator,
            generate_plan_from_libraries,
        )

        if name == "ProjectionGenerator":
            return ProjectionGenerator
        return generate_plan_from_libraries

    if name in (
        "AtomAwareDriftComparator",
        "AtomAlignment",
        "DriftItem",
        "DriftPolicy",
        "DriftReport",
        "convert_drift_to_gaps",
    ):
        from spec_manager.projection.drift import (
            AtomAlignment,
            AtomAwareDriftComparator,
            DriftItem,
            DriftPolicy,
            DriftReport,
            convert_drift_to_gaps,
        )

        return {
            "AtomAwareDriftComparator": AtomAwareDriftComparator,
            "AtomAlignment": AtomAlignment,
            "DriftItem": DriftItem,
            "DriftPolicy": DriftPolicy,
            "DriftReport": DriftReport,
            "convert_drift_to_gaps": convert_drift_to_gaps,
        }[name]

    if name in (
        "PinChange",
        "PinChangePropagator",
        "PropagationItem",
        "PropagationReport",
        "convert_propagation_to_drift",
    ):
        from spec_manager.projection.pin_propagation import (
            PinChange,
            PinChangePropagator,
            PropagationItem,
            PropagationReport,
            convert_propagation_to_drift,
        )

        return {
            "PinChange": PinChange,
            "PinChangePropagator": PinChangePropagator,
            "PropagationItem": PropagationItem,
            "PropagationReport": PropagationReport,
            "convert_propagation_to_drift": convert_propagation_to_drift,
        }[name]

    # Lineage tracking symbols
    _lineage_edge_names = {"ProjectionLineageEdge", "ProjectionType"}
    _lineage_table_names = {"ProjectionLineageTable"}
    _lineage_import_names = {"ImportEdge", "ImportGraph"}
    _lineage_builder_names = {"AtomDefinition", "LineageBuilder"}
    _lineage_flow_names = {"DataFlowHop", "DataFlowTracker", "SignalSpec"}
    _lineage_drift_names = {"DriftKind", "PinDrift", "PinDriftDetector"}

    if name in _lineage_edge_names:
        from spec_manager.projection.lineage.edges import (
            ProjectionLineageEdge,
        )
        from spec_manager.schemas.pin_functions import ProjectionType

        return {
            "ProjectionLineageEdge": ProjectionLineageEdge,
            "ProjectionType": ProjectionType,
        }[name]

    if name in _lineage_table_names:
        from spec_manager.projection.lineage.table import ProjectionLineageTable

        return ProjectionLineageTable

    if name in _lineage_import_names:
        from spec_manager.projection.lineage.import_graph import ImportEdge, ImportGraph

        return {"ImportEdge": ImportEdge, "ImportGraph": ImportGraph}[name]

    if name in _lineage_builder_names:
        from spec_manager.projection.lineage.builder import AtomDefinition, LineageBuilder

        return {"AtomDefinition": AtomDefinition, "LineageBuilder": LineageBuilder}[name]

    if name in _lineage_flow_names:
        from spec_manager.projection.lineage.data_flow import (
            DataFlowHop,
            DataFlowTracker,
            SignalSpec,
        )

        return {
            "DataFlowHop": DataFlowHop,
            "DataFlowTracker": DataFlowTracker,
            "SignalSpec": SignalSpec,
        }[name]

    if name in _lineage_drift_names:
        from spec_manager.projection.lineage.drift_detector import (
            DriftKind,
            PinDrift,
            PinDriftDetector,
        )

        return {"DriftKind": DriftKind, "PinDrift": PinDrift, "PinDriftDetector": PinDriftDetector}[
            name
        ]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
