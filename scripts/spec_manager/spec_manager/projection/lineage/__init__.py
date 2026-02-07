"""Lineage tracking subpackage for projection module.

Provides:
- ProjectionLineageEdge and ProjectionType: Core data model
- ProjectionLineageTable: Queryable edge collection with forward/backward trace
- ImportGraph and ImportEdge: Static analysis of Python imports
- LineageBuilder and AtomDefinition: Bridge import graph to lineage table
- DataFlowTracker, SignalSpec, DataFlowHop: Data flow projection tracking
- PinDriftDetector, DriftKind, PinDrift: Pin target drift detection
- Persistence utilities: JSON save/load for lineage data

Imports are lazy to avoid circular import issues.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    # Edges (Plan 1)
    "ProjectionLineageEdge",
    "ProjectionType",
    # Table (Plan 2)
    "ProjectionLineageTable",
    # Import Graph (Plan 3)
    "ImportEdge",
    "ImportGraph",
    # Builder (Plan 4)
    "AtomDefinition",
    "LineageBuilder",
    "compute_signature_hash",
    # Data Flow (Plan 5)
    "DataFlowHop",
    "DataFlowTracker",
    "SignalSpec",
    # Drift Detector (Plan 6)
    "DriftKind",
    "PinDrift",
    "PinDriftDetector",
    # Test-Pin Discovery
    "TestPinAssociation",
    "TestPinMap",
    "discover_test_pin_associations",
    # Persistence (Plan 7)
    "load_import_graph",
    "load_lineage_table",
    "save_import_graph",
    "save_lineage_table",
]


def __getattr__(name: str):
    """Lazy import to avoid circular imports."""
    if name in ("ProjectionLineageEdge", "ProjectionType"):
        from spec_manager.projection.lineage.edges import ProjectionLineageEdge
        from spec_manager.schemas.pin_functions import ProjectionType

        return {"ProjectionLineageEdge": ProjectionLineageEdge, "ProjectionType": ProjectionType}[name]

    if name == "ProjectionLineageTable":
        from spec_manager.projection.lineage.table import ProjectionLineageTable

        return ProjectionLineageTable

    if name in ("ImportEdge", "ImportGraph"):
        from spec_manager.projection.lineage.import_graph import (
            ImportEdge,
            ImportGraph,
        )

        return {"ImportEdge": ImportEdge, "ImportGraph": ImportGraph}[name]

    if name in ("AtomDefinition", "LineageBuilder", "compute_signature_hash"):
        from spec_manager.projection.lineage.builder import (
            AtomDefinition,
            LineageBuilder,
            compute_signature_hash,
        )

        return {
            "AtomDefinition": AtomDefinition,
            "LineageBuilder": LineageBuilder,
            "compute_signature_hash": compute_signature_hash,
        }[name]

    if name in ("DataFlowHop", "DataFlowTracker", "SignalSpec"):
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

    if name in ("DriftKind", "PinDrift", "PinDriftDetector"):
        from spec_manager.projection.lineage.drift_detector import (
            DriftKind,
            PinDrift,
            PinDriftDetector,
        )

        return {
            "DriftKind": DriftKind,
            "PinDrift": PinDrift,
            "PinDriftDetector": PinDriftDetector,
        }[name]

    if name in ("TestPinAssociation", "TestPinMap", "discover_test_pin_associations"):
        from spec_manager.projection.lineage.test_pin_discovery import (
            TestPinAssociation,
            TestPinMap,
            discover_test_pin_associations,
        )

        return {
            "TestPinAssociation": TestPinAssociation,
            "TestPinMap": TestPinMap,
            "discover_test_pin_associations": discover_test_pin_associations,
        }[name]

    if name in ("load_import_graph", "load_lineage_table", "save_import_graph", "save_lineage_table"):
        from spec_manager.projection.lineage.persistence import (
            load_import_graph,
            load_lineage_table,
            save_import_graph,
            save_lineage_table,
        )

        return {
            "load_import_graph": load_import_graph,
            "load_lineage_table": load_lineage_table,
            "save_import_graph": save_import_graph,
            "save_lineage_table": save_lineage_table,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
