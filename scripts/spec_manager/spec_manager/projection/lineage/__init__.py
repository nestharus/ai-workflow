"""Lineage tracking subpackage for projection module.

Provides:
- ProjectionLineageEdge and ProjectionType: Core data model
- ProjectionLineageTable: Queryable edge collection with forward/backward trace
- RawImportRecord and registry-edge projection helpers
- LineageBuilder and AtomDefinition: Bridge import records to lineage table
- DataFlowTracker, SignalSpec, DataFlowHop: Data flow projection tracking
- PinDriftDetector, DriftKind, PinDrift: Pin target drift detection
- Persistence utilities: JSON save/load for lineage data

Imports are lazy to avoid circular import issues.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AtomDefinition",
    "DataFlowHop",
    "DataFlowTracker",
    "DriftKind",
    "LineageBuilder",
    "PinDrift",
    "PinDriftDetector",
    "ProjectionLineageEdge",
    "ProjectionLineageTable",
    "ProjectionType",
    "RawImportRecord",
    "SignalSpec",
    "TestPinAssociation",
    "TestPinMap",
    "compute_signature_hash",
    "discover_test_pin_associations",
    "import_records_from_pin_registry",
    "load_lineage_table",
    "save_lineage_table",
]


def __getattr__(name: str) -> Any:
    """Lazy import to avoid circular imports."""
    if name in ("ProjectionLineageEdge", "ProjectionType"):
        from spec_manager.projection.lineage.edges import ProjectionLineageEdge
        from spec_manager.schemas.pin_functions import ProjectionType

        return {"ProjectionLineageEdge": ProjectionLineageEdge, "ProjectionType": ProjectionType}[
            name
        ]

    if name == "ProjectionLineageTable":
        from spec_manager.projection.lineage.table import ProjectionLineageTable

        return ProjectionLineageTable

    if name in (
        "AtomDefinition",
        "LineageBuilder",
        "RawImportRecord",
        "compute_signature_hash",
        "import_records_from_pin_registry",
    ):
        from spec_manager.projection.lineage.builder import (
            AtomDefinition,
            LineageBuilder,
            RawImportRecord,
            compute_signature_hash,
            import_records_from_pin_registry,
        )

        return {
            "AtomDefinition": AtomDefinition,
            "LineageBuilder": LineageBuilder,
            "RawImportRecord": RawImportRecord,
            "compute_signature_hash": compute_signature_hash,
            "import_records_from_pin_registry": import_records_from_pin_registry,
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

    if name in ("load_lineage_table", "save_lineage_table"):
        from spec_manager.projection.lineage.persistence import (
            load_lineage_table,
            save_lineage_table,
        )

        return {
            "load_lineage_table": load_lineage_table,
            "save_lineage_table": save_lineage_table,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
