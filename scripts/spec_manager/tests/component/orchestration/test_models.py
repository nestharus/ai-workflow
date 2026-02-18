"""Component tests for orchestration.models types.

Tests Layer/Lane literal types, LAYER_ORDER, next_layer/prev_layer
navigation, and all dataclass result types.
"""

from __future__ import annotations

from spec_manager.core.layer_types import (
    LAYER_ORDER,
    BatchResult,
    Layer,
    LayerStatus,
    MergeResult,
    PipelineTickResult,
    PropagateResult,
    next_layer,
    prev_layer,
)

# ======================================================================
# LAYER_ORDER
# ======================================================================


class TestLayerOrder:
    """Tests for the LAYER_ORDER constant."""

    def test_layer_order_has_three_entries(self) -> None:
        """LAYER_ORDER contains exactly three layers."""
        assert len(LAYER_ORDER) == 3

    def test_layer_order_values(self) -> None:
        """LAYER_ORDER is [l1, l2, l3] in that sequence."""
        assert LAYER_ORDER == ["l1", "l2", "l3"]

    def test_layer_order_is_list_of_strings(self) -> None:
        """Every element in LAYER_ORDER is a string."""
        for layer in LAYER_ORDER:
            assert isinstance(layer, str)


# ======================================================================
# next_layer / prev_layer
# ======================================================================


class TestNextLayer:
    """Tests for the next_layer() function."""

    def test_l1_next_is_l2(self) -> None:
        """next_layer('l1') returns 'l2'."""
        assert next_layer("l1") == "l2"

    def test_l2_next_is_l3(self) -> None:
        """next_layer('l2') returns 'l3'."""
        assert next_layer("l2") == "l3"

    def test_l3_next_is_none(self) -> None:
        """next_layer('l3') returns None (no layer after l3)."""
        assert next_layer("l3") is None


class TestPrevLayer:
    """Tests for the prev_layer() function."""

    def test_l1_prev_is_none(self) -> None:
        """prev_layer('l1') returns None (no layer before l1)."""
        assert prev_layer("l1") is None

    def test_l2_prev_is_l1(self) -> None:
        """prev_layer('l2') returns 'l1'."""
        assert prev_layer("l2") == "l1"

    def test_l3_prev_is_l2(self) -> None:
        """prev_layer('l3') returns 'l2'."""
        assert prev_layer("l3") == "l2"


class TestNextPrevRoundTrip:
    """Tests that next_layer and prev_layer are inverses where defined."""

    def test_l1_roundtrip(self) -> None:
        """prev_layer(next_layer('l1')) == 'l1'."""
        nl = next_layer("l1")
        assert nl is not None
        assert prev_layer(nl) == "l1"

    def test_l2_roundtrip_forward(self) -> None:
        """prev_layer(next_layer('l2')) == 'l2'."""
        nl = next_layer("l2")
        assert nl is not None
        assert prev_layer(nl) == "l2"

    def test_l2_roundtrip_backward(self) -> None:
        """next_layer(prev_layer('l2')) == 'l2'."""
        pl = prev_layer("l2")
        assert pl is not None
        assert next_layer(pl) == "l2"


# ======================================================================
# MergeResult
# ======================================================================


class TestMergeResult:
    """Tests for the MergeResult dataclass."""

    def test_defaults(self) -> None:
        """MergeResult has correct default values for optional fields."""
        mr = MergeResult(success=True, slice_id="s1", layer="l1")
        assert mr.success is True
        assert mr.slice_id == "s1"
        assert mr.layer == "l1"
        assert mr.merge_sha is None
        assert mr.error == ""
        assert mr.conflict_files == []

    def test_full_construction(self) -> None:
        """MergeResult can be constructed with all fields."""
        mr = MergeResult(
            success=False,
            slice_id="s2",
            layer="l2",
            merge_sha="abc123",
            error="conflict",
            conflict_files=["a.py", "b.py"],
        )
        assert mr.success is False
        assert mr.merge_sha == "abc123"
        assert mr.error == "conflict"
        assert mr.conflict_files == ["a.py", "b.py"]

    def test_conflict_files_not_shared_across_instances(self) -> None:
        """Each MergeResult gets its own conflict_files list."""
        mr1 = MergeResult(success=True, slice_id="s1", layer="l1")
        mr2 = MergeResult(success=True, slice_id="s2", layer="l1")
        mr1.conflict_files.append("x.py")
        assert mr2.conflict_files == []


# ======================================================================
# BatchResult
# ======================================================================


class TestBatchResult:
    """Tests for the BatchResult dataclass."""

    def test_defaults(self) -> None:
        """BatchResult has correct default values."""
        br = BatchResult(success=True, layer="l1")
        assert br.success is True
        assert br.layer == "l1"
        assert br.candidate_sha is None
        assert br.clean_sha is None
        assert br.gates_passed is True
        assert br.tests_passed is True
        assert br.error == ""
        assert br.demotion_tickets == []

    def test_failure_construction(self) -> None:
        """BatchResult can represent a failed batch promotion."""
        br = BatchResult(
            success=False,
            layer="l2",
            error="gate failed",
            gates_passed=False,
            demotion_tickets=["t1", "t2"],
        )
        assert br.success is False
        assert br.gates_passed is False
        assert len(br.demotion_tickets) == 2


# ======================================================================
# PropagateResult
# ======================================================================


class TestPropagateResult:
    """Tests for the PropagateResult dataclass."""

    def test_defaults(self) -> None:
        """PropagateResult has correct default values."""
        pr = PropagateResult(success=True, from_layer="l1", to_layer="l2")
        assert pr.success is True
        assert pr.from_layer == "l1"
        assert pr.to_layer == "l2"
        assert pr.merge_sha is None
        assert pr.error == ""
        assert pr.conflict_files == []

    def test_conflict_construction(self) -> None:
        """PropagateResult can represent a merge conflict."""
        pr = PropagateResult(
            success=False,
            from_layer="l2",
            to_layer="l3",
            error="conflict in main.py",
            conflict_files=["main.py"],
        )
        assert pr.success is False
        assert pr.conflict_files == ["main.py"]


# ======================================================================
# PipelineTickResult
# ======================================================================


class TestPipelineTickResult:
    """Tests for the PipelineTickResult dataclass."""

    def test_defaults(self) -> None:
        """PipelineTickResult has empty defaults."""
        ptr = PipelineTickResult()
        assert ptr.layer_results == {}
        assert ptr.propagation_results == []
        assert ptr.main_updated is False
        assert ptr.main_sha is None
        assert ptr.demotion_tickets == []

    def test_aggregated_results(self) -> None:
        """PipelineTickResult accumulates per-layer batch results."""
        ptr = PipelineTickResult()
        ptr.layer_results["l1"] = BatchResult(success=True, layer="l1")
        ptr.layer_results["l2"] = BatchResult(success=True, layer="l2")
        assert len(ptr.layer_results) == 2
        assert ptr.layer_results["l1"].success is True

    def test_demotion_tickets_not_shared(self) -> None:
        """Each PipelineTickResult gets its own demotion_tickets list."""
        p1 = PipelineTickResult()
        p2 = PipelineTickResult()
        p1.demotion_tickets.append("t1")
        assert p2.demotion_tickets == []


# ======================================================================
# LayerStatus
# ======================================================================


class TestLayerStatus:
    """Tests for the LayerStatus dataclass."""

    def test_defaults(self) -> None:
        """LayerStatus has correct default values."""
        ls = LayerStatus(layer="l1")
        assert ls.layer == "l1"
        assert ls.dirty_sha is None
        assert ls.clean_sha is None
        assert ls.candidate_sha is None
        assert ls.is_clean is False
        assert ls.pending_commits == 0
        assert ls.upstream_accepted_sha is None

    def test_fully_clean_layer(self) -> None:
        """LayerStatus can represent a fully clean layer."""
        ls = LayerStatus(
            layer="l2",
            dirty_sha="abc123",
            clean_sha="abc123",
            is_clean=True,
            pending_commits=0,
        )
        assert ls.is_clean is True
        assert ls.dirty_sha == ls.clean_sha

    def test_dirty_layer_with_pending(self) -> None:
        """LayerStatus tracks pending commit count between dirty and clean."""
        ls = LayerStatus(
            layer="l1",
            dirty_sha="def456",
            clean_sha="abc123",
            is_clean=False,
            pending_commits=5,
        )
        assert ls.pending_commits == 5
        assert ls.is_clean is False
