"""Tests for wait graph and cycle detection."""

from __future__ import annotations

import pytest
from spec_manager.orchestration.coordination.wait_graph import (
    CyclicDependencyError,
    WaitEdge,
    WaitGraph,
)

# ------------------------------------------------------------------
# WaitEdge tests
# ------------------------------------------------------------------


class TestWaitEdge:
    def test_round_trip(self):
        edge = WaitEdge(
            waiting_slice="a",
            provider_slice="b",
            artifact_key="X.do",
            signal_id="sig-1",
            monitor_id="mon-1",
        )
        restored = WaitEdge.from_dict(edge.to_dict())
        assert restored.waiting_slice == "a"
        assert restored.provider_slice == "b"
        assert restored.artifact_key == "X.do"
        assert restored.signal_id == "sig-1"
        assert restored.monitor_id == "mon-1"

    def test_defaults(self):
        edge = WaitEdge()
        assert edge.waiting_slice == ""
        assert edge.provider_slice == ""


# ------------------------------------------------------------------
# WaitGraph: basic operations
# ------------------------------------------------------------------


class TestWaitGraphBasic:
    def test_add_and_query(self):
        g = WaitGraph()
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        assert len(g.get_waiting_on("a")) == 1
        assert len(g.get_providers_for("b")) == 1
        assert g.get_waiting_on("b") == []
        assert g.get_providers_for("a") == []

    def test_multiple_edges(self):
        g = WaitGraph()
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="c", signal_id="s2"))
        g.add_edge(WaitEdge(waiting_slice="d", provider_slice="b", signal_id="s3"))
        assert len(g.get_waiting_on("a")) == 2
        assert len(g.get_providers_for("b")) == 2

    def test_remove_edge_by_signal(self):
        g = WaitGraph()
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="c", signal_id="s2"))
        g.remove_edge("s1")
        assert len(g.get_waiting_on("a")) == 1
        assert g.get_waiting_on("a")[0].provider_slice == "c"

    def test_remove_edges_for_slice(self):
        g = WaitGraph()
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="c", signal_id="s2"))
        g.add_edge(WaitEdge(waiting_slice="d", provider_slice="a", signal_id="s3"))
        g.remove_edges_for_slice("a")
        assert g.get_waiting_on("a") == []
        # Edge from d->a should still exist
        assert len(g.get_providers_for("a")) == 1


# ------------------------------------------------------------------
# WaitGraph: cycle detection
# ------------------------------------------------------------------


class TestWaitGraphCycles:
    def test_self_loop_raises(self):
        g = WaitGraph()
        with pytest.raises(CyclicDependencyError) as exc_info:
            g.add_edge(WaitEdge(waiting_slice="a", provider_slice="a", signal_id="s1"))
        assert "a" in exc_info.value.cycle

    def test_direct_cycle_raises(self):
        g = WaitGraph()
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        with pytest.raises(CyclicDependencyError) as exc_info:
            g.add_edge(WaitEdge(waiting_slice="b", provider_slice="a", signal_id="s2"))
        assert "a" in exc_info.value.cycle
        assert "b" in exc_info.value.cycle

    def test_transitive_cycle_raises(self):
        g = WaitGraph()
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        g.add_edge(WaitEdge(waiting_slice="b", provider_slice="c", signal_id="s2"))
        with pytest.raises(CyclicDependencyError):
            g.add_edge(WaitEdge(waiting_slice="c", provider_slice="a", signal_id="s3"))

    def test_no_cycle_linear_chain(self):
        g = WaitGraph()
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        g.add_edge(WaitEdge(waiting_slice="b", provider_slice="c", signal_id="s2"))
        g.add_edge(WaitEdge(waiting_slice="c", provider_slice="d", signal_id="s3"))
        assert not g.has_cycle()
        assert g.get_cycle() is None

    def test_no_cycle_diamond(self):
        g = WaitGraph()
        # a -> b, a -> c, b -> d, c -> d (diamond, no cycle)
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="c", signal_id="s2"))
        g.add_edge(WaitEdge(waiting_slice="b", provider_slice="d", signal_id="s3"))
        g.add_edge(WaitEdge(waiting_slice="c", provider_slice="d", signal_id="s4"))
        assert not g.has_cycle()

    def test_has_cycle_false_for_empty(self):
        g = WaitGraph()
        assert not g.has_cycle()
        assert g.get_cycle() is None

    def test_cycle_removed_after_edge_removal(self):
        """After removing an edge that was part of a potential cycle path,
        adding the previously rejected edge should succeed."""
        g = WaitGraph()
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        g.add_edge(WaitEdge(waiting_slice="b", provider_slice="c", signal_id="s2"))
        # c->a would cycle
        with pytest.raises(CyclicDependencyError):
            g.add_edge(WaitEdge(waiting_slice="c", provider_slice="a", signal_id="s3"))
        # Remove b->c
        g.remove_edge("s2")
        # Now c->a is fine
        g.add_edge(WaitEdge(waiting_slice="c", provider_slice="a", signal_id="s4"))
        assert not g.has_cycle()

    def test_cyclic_dependency_error_message(self):
        g = WaitGraph()
        g.add_edge(WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1"))
        with pytest.raises(CyclicDependencyError) as exc_info:
            g.add_edge(WaitEdge(waiting_slice="b", provider_slice="a", signal_id="s2"))
        assert "Cyclic dependency detected" in str(exc_info.value)


# ------------------------------------------------------------------
# WaitGraph: serialization
# ------------------------------------------------------------------


class TestWaitGraphSerialization:
    def test_round_trip_empty(self):
        g = WaitGraph()
        d = g.to_dict()
        restored = WaitGraph.from_dict(d)
        assert restored.to_dict() == d

    def test_round_trip_with_edges(self):
        g = WaitGraph()
        g.add_edge(
            WaitEdge(waiting_slice="a", provider_slice="b", signal_id="s1", artifact_key="X")
        )
        g.add_edge(WaitEdge(waiting_slice="c", provider_slice="d", signal_id="s2", monitor_id="m1"))
        d = g.to_dict()
        restored = WaitGraph.from_dict(d)
        assert len(restored.get_waiting_on("a")) == 1
        assert len(restored.get_waiting_on("c")) == 1
        assert restored.to_dict() == d

    def test_from_dict_skips_cycle_check(self):
        """from_dict should load even if edges form a cycle
        (the persisted graph was valid when saved)."""
        d = {
            "edges": [
                {"waiting_slice": "a", "provider_slice": "b", "signal_id": "s1"},
                {"waiting_slice": "b", "provider_slice": "a", "signal_id": "s2"},
            ]
        }
        g = WaitGraph.from_dict(d)
        assert len(g.get_waiting_on("a")) == 1
        assert len(g.get_waiting_on("b")) == 1
        # has_cycle should detect it
        assert g.has_cycle()
