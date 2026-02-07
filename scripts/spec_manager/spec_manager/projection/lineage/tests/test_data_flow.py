"""Tests for DataFlowTracker, SignalSpec, and DataFlowHop."""

from __future__ import annotations

import pytest

from spec_manager.projection.lineage.data_flow import (
    DataFlowHop,
    DataFlowTracker,
    SignalSpec,
)
from spec_manager.schemas.pin_functions import ProjectionType
from spec_manager.projection.lineage.table import ProjectionLineageTable


def _build_tracker_with_edge(
    from_unit: str = "atom_a",
    to_unit: str = "loc_b",
    transformation: ProjectionType = ProjectionType.PASS_THROUGH,
) -> tuple[DataFlowTracker, ProjectionLineageTable]:
    """Build a tracker with a single lineage edge."""
    table = ProjectionLineageTable()
    table.add_edge(from_unit, to_unit, transformation)
    tracker = DataFlowTracker(table)
    return tracker, table


class TestSignalSpec:
    def test_roundtrip_serialization(self):
        """to_dict/from_dict roundtrip preserves all fields."""
        spec = SignalSpec(
            signals_in=["amount", "currency"],
            signals_out=["is_valid", "error_code"],
            stores_read=["config_db"],
            stores_written=["audit_log"],
        )
        data = spec.to_dict()
        restored = SignalSpec.from_dict(data)
        assert restored.signals_in == spec.signals_in
        assert restored.signals_out == spec.signals_out
        assert restored.stores_read == spec.stores_read
        assert restored.stores_written == spec.stores_written

    def test_defaults_are_empty_lists(self):
        """Default values are empty lists."""
        spec = SignalSpec()
        assert spec.signals_in == []
        assert spec.signals_out == []
        assert spec.stores_read == []
        assert spec.stores_written == []


class TestDataFlowHop:
    def test_roundtrip_serialization(self):
        """to_dict/from_dict roundtrip preserves all fields."""
        hop = DataFlowHop(
            source_unit="atom_a",
            target_unit="loc_b",
            signals_passed=["amount"],
            signals_dropped=["debug_info"],
            signals_added=["timestamp"],
            hop_type=ProjectionType.SLICE,
        )
        data = hop.to_dict()
        restored = DataFlowHop.from_dict(data)
        assert restored.source_unit == hop.source_unit
        assert restored.target_unit == hop.target_unit
        assert restored.signals_passed == hop.signals_passed
        assert restored.signals_dropped == hop.signals_dropped
        assert restored.signals_added == hop.signals_added
        assert restored.hop_type == hop.hop_type


class TestDataFlowTracker:
    def test_pass_through_preserves_all_signals(self):
        """No signal loss for PASS_THROUGH when target accepts all source outputs."""
        tracker, _ = _build_tracker_with_edge()

        tracker.register_signal_spec(
            "atom_a",
            SignalSpec(
                signals_in=["input_data"],
                signals_out=["result_a", "result_b"],
            ),
        )
        tracker.register_signal_spec(
            "loc_b",
            SignalSpec(
                signals_in=["result_a", "result_b"],
                signals_out=["final_output"],
            ),
        )

        hop = tracker.compute_flow_projection("atom_a", "loc_b")
        assert hop is not None
        assert sorted(hop.signals_passed) == ["result_a", "result_b"]
        assert hop.signals_dropped == []
        assert hop.signals_added == []

    def test_slice_detects_dropped_signals(self):
        """Subset of signals = signals_dropped populated."""
        tracker, _ = _build_tracker_with_edge(
            transformation=ProjectionType.SLICE,
        )

        tracker.register_signal_spec(
            "atom_a",
            SignalSpec(
                signals_out=["result_a", "result_b", "debug_info"],
            ),
        )
        tracker.register_signal_spec(
            "loc_b",
            SignalSpec(
                signals_in=["result_a"],
            ),
        )

        hop = tracker.compute_flow_projection("atom_a", "loc_b")
        assert hop is not None
        assert hop.signals_passed == ["result_a"]
        assert sorted(hop.signals_dropped) == ["debug_info", "result_b"]

    def test_signals_added_detected(self):
        """Target requires signals not in source output = signals_added."""
        tracker, _ = _build_tracker_with_edge()

        tracker.register_signal_spec(
            "atom_a",
            SignalSpec(signals_out=["amount"]),
        )
        tracker.register_signal_spec(
            "loc_b",
            SignalSpec(signals_in=["amount", "timestamp"]),
        )

        hop = tracker.compute_flow_projection("atom_a", "loc_b")
        assert hop is not None
        assert hop.signals_added == ["timestamp"]

    def test_compute_flow_returns_none_without_specs(self):
        """Returns None when signal specs not registered."""
        tracker, _ = _build_tracker_with_edge()
        hop = tracker.compute_flow_projection("atom_a", "loc_b")
        assert hop is None

    def test_store_touch_graph(self):
        """Correctly maps stores to reading/writing units."""
        tracker, _ = _build_tracker_with_edge()

        tracker.register_signal_spec(
            "atom_a",
            SignalSpec(
                stores_read=["config_db"],
                stores_written=["audit_log"],
            ),
        )
        tracker.register_signal_spec(
            "loc_b",
            SignalSpec(
                stores_read=["audit_log", "config_db"],
                stores_written=[],
            ),
        )

        graph = tracker.get_store_touch_graph()
        assert "config_db" in graph
        assert "audit_log" in graph
        assert sorted(graph["config_db"]) == ["atom_a", "loc_b"]
        assert sorted(graph["audit_log"]) == ["atom_a", "loc_b"]

    def test_find_signal_loss_returns_only_lossy_hops(self):
        """Filters to hops with dropped signals."""
        table = ProjectionLineageTable()
        table.add_edge("a", "b", ProjectionType.SLICE)
        table.add_edge("c", "d", ProjectionType.PASS_THROUGH)
        tracker = DataFlowTracker(table)

        # a -> b has signal loss
        tracker.register_signal_spec("a", SignalSpec(signals_out=["x", "y"]))
        tracker.register_signal_spec("b", SignalSpec(signals_in=["x"]))

        # c -> d has no loss
        tracker.register_signal_spec("c", SignalSpec(signals_out=["z"]))
        tracker.register_signal_spec("d", SignalSpec(signals_in=["z"]))

        lossy = tracker.find_signal_loss()
        assert len(lossy) == 1
        assert lossy[0].source_unit == "a"
        assert lossy[0].signals_dropped == ["y"]

    def test_hop_type_from_lineage_edge(self):
        """Hop type matches the lineage edge transformation."""
        tracker, _ = _build_tracker_with_edge(
            transformation=ProjectionType.EVENT_BRIDGE,
        )
        tracker.register_signal_spec("atom_a", SignalSpec(signals_out=["x"]))
        tracker.register_signal_spec("loc_b", SignalSpec(signals_in=["x"]))

        hop = tracker.compute_flow_projection("atom_a", "loc_b")
        assert hop is not None
        assert hop.hop_type == ProjectionType.EVENT_BRIDGE
