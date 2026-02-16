"""Data flow projection tracking.

Tracks how data signals transform through architectural hops.
For each lineage edge, records which signals pass through, are dropped
(slice), or are added (enrichment).

Based on ALGORITHM.md Phase 5 signal tracing: pass-through,
projection/slice, and aggregation/smear.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from spec_manager.projection.lineage.table import ProjectionLineageTable
from spec_manager.schemas.pin_functions import ProjectionType


@dataclass
class SignalSpec:
    """Data signal specification for a function/step.

    Attributes:
        signals_in: Input signal names (parameter names or types).
        signals_out: Output signal names (return type fields).
        stores_read: Stores read from.
        stores_written: Stores written to.
    """

    signals_in: list[str] = field(default_factory=list)
    signals_out: list[str] = field(default_factory=list)
    stores_read: list[str] = field(default_factory=list)
    stores_written: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "signals_in": self.signals_in,
            "signals_out": self.signals_out,
            "stores_read": self.stores_read,
            "stores_written": self.stores_written,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignalSpec:
        """Deserialize from dictionary."""
        return cls(
            signals_in=data.get("signals_in", []),
            signals_out=data.get("signals_out", []),
            stores_read=data.get("stores_read", []),
            stores_written=data.get("stores_written", []),
        )


@dataclass
class DataFlowHop:
    """A single hop in data flow through architecture.

    Attributes:
        source_unit: Where signal comes from.
        target_unit: Where signal goes to.
        signals_passed: Which signals are passed through.
        signals_dropped: Which signals are dropped (slice).
        signals_added: Which signals are added (enrichment).
        hop_type: The transformation type for this hop.
    """

    source_unit: str
    target_unit: str
    signals_passed: list[str] = field(default_factory=list)
    signals_dropped: list[str] = field(default_factory=list)
    signals_added: list[str] = field(default_factory=list)
    hop_type: ProjectionType | None = ProjectionType.PASS_THROUGH
    assessed: bool = True
    assessment_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "source_unit": self.source_unit,
            "target_unit": self.target_unit,
            "signals_passed": self.signals_passed,
            "signals_dropped": self.signals_dropped,
            "signals_added": self.signals_added,
            "hop_type": self.hop_type.value if self.hop_type is not None else None,
            "assessed": self.assessed,
            "assessment_reason": self.assessment_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataFlowHop:
        """Deserialize from dictionary."""
        return cls(
            source_unit=data["source_unit"],
            target_unit=data["target_unit"],
            signals_passed=data.get("signals_passed", []),
            signals_dropped=data.get("signals_dropped", []),
            signals_added=data.get("signals_added", []),
            hop_type=ProjectionType(data["hop_type"]) if data.get("hop_type") else None,
            assessed=bool(data.get("assessed", True)),
            assessment_reason=str(data.get("assessment_reason", "")),
        )


class DataFlowTracker:
    """Tracks data signal projections through architectural hops.

    For each lineage edge, tracks which signals pass through,
    which are dropped (slice), and which are added.
    """

    def __init__(self, lineage_table: ProjectionLineageTable) -> None:
        self.lineage_table = lineage_table
        self._signal_specs: dict[str, SignalSpec] = {}

    def register_signal_spec(
        self,
        unit_id: str,
        spec: SignalSpec,
    ) -> None:
        """Register the signal specification for a unit.

        Args:
            unit_id: The unit (atom or arch location) to register for.
            spec: The signal specification describing inputs/outputs.
        """
        self._signal_specs[unit_id] = spec

    def compute_flow_projection(
        self,
        from_unit: str,
        to_unit: str,
    ) -> DataFlowHop | None:
        """Compute the data flow projection between two units.

        Compares the signal specs of the source and target units
        to determine which signals are passed through, dropped,
        or added at this hop.

        Args:
            from_unit: Source unit ID.
            to_unit: Target unit ID.

        Returns:
            DataFlowHop describing the signal transformation, or None
            if signal specs are not available for both units.
        """
        source_spec = self._signal_specs.get(from_unit)
        target_spec = self._signal_specs.get(to_unit)

        if source_spec is None or target_spec is None:
            return None

        # Find the lineage edge to get the transformation type
        edges = self.lineage_table.trace_forward(from_unit)
        hop_type: ProjectionType | None = None
        for edge in edges:
            if edge.to_unit == to_unit:
                hop_type = edge.transformation
                break
        if hop_type is None:
            return DataFlowHop(
                source_unit=from_unit,
                target_unit=to_unit,
                hop_type=None,
                assessed=False,
                assessment_reason="missing_lineage_edge",
            )

        source_out = set(source_spec.signals_out)
        target_in = set(target_spec.signals_in)

        # Signals that pass through: present in source output AND target input
        signals_passed = sorted(source_out & target_in)
        # Signals dropped: in source output but NOT in target input
        signals_dropped = sorted(source_out - target_in)
        # Signals added: in target input but NOT in source output
        signals_added = sorted(target_in - source_out)

        return DataFlowHop(
            source_unit=from_unit,
            target_unit=to_unit,
            signals_passed=signals_passed,
            signals_dropped=signals_dropped,
            signals_added=signals_added,
            hop_type=hop_type,
            assessed=True,
            assessment_reason="",
        )

    def find_signal_loss(self) -> list[DataFlowHop]:
        """Find all hops where signals are dropped.

        Returns:
            List of DataFlowHop entries that have non-empty signals_dropped.
        """
        lossy_hops: list[DataFlowHop] = []
        for edge in self.lineage_table.edges:
            source_spec = self._signal_specs.get(edge.from_unit)
            target_spec = self._signal_specs.get(edge.to_unit)
            if source_spec is None or target_spec is None:
                missing: list[str] = []
                if source_spec is None:
                    missing.append(f"missing_source_spec:{edge.from_unit}")
                if target_spec is None:
                    missing.append(f"missing_target_spec:{edge.to_unit}")
                lossy_hops.append(
                    DataFlowHop(
                        source_unit=edge.from_unit,
                        target_unit=edge.to_unit,
                        hop_type=edge.transformation,
                        assessed=False,
                        assessment_reason=";".join(missing),
                    )
                )
                continue

            hop = self.compute_flow_projection(edge.from_unit, edge.to_unit)
            if hop is None:
                lossy_hops.append(
                    DataFlowHop(
                        source_unit=edge.from_unit,
                        target_unit=edge.to_unit,
                        hop_type=edge.transformation,
                        assessed=False,
                        assessment_reason="projection_unavailable",
                    )
                )
                continue

            if not hop.assessed or hop.signals_dropped:
                lossy_hops.append(hop)
        return lossy_hops

    def get_store_touch_graph(self) -> dict[str, list[str]]:
        """Build a graph mapping stores to units that touch them.

        Includes both reads and writes. Each store maps to a list of
        unit IDs that read from or write to that store.

        Returns:
            Dictionary mapping store names to lists of touching unit IDs.
        """
        store_graph: dict[str, list[str]] = defaultdict(list)
        for unit_id, spec in self._signal_specs.items():
            for store in spec.stores_read:
                if unit_id not in store_graph[store]:
                    store_graph[store].append(unit_id)
            for store in spec.stores_written:
                if unit_id not in store_graph[store]:
                    store_graph[store].append(unit_id)
        return dict(store_graph)


__all__ = [
    "DataFlowHop",
    "DataFlowTracker",
    "SignalSpec",
]
