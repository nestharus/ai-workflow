"""Tests for pin-function change propagation engine (Plan 4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from spec_manager.core.pin_registry import PinRegistryIndex
from spec_manager.projection.drift import DriftItem
from spec_manager.projection.pin_propagation import (
    PinChange,
    PinChangePropagator,
    PropagationItem,
    PropagationReport,
    convert_propagation_to_drift,
)
from spec_manager.schemas.pin_functions import (
    ImportEdge,
    PinFunction,
    PinFunctionRegistry,
)


def _make_pf(
    pin_func_id: str = "PFUNC-0001",
    function_name: str = "validate",
    content_hash: str = "a" * 64,
    signature: str = "(data: dict) -> bool",
    **kwargs,
) -> PinFunction:
    defaults = dict(
        pin_func_id=pin_func_id,
        function_name=function_name,
        module_path="atoms.pay",
        file_path="atoms/pay.py",
        line_start=1,
        line_end=10,
        signature=signature,
        docstring="Validate.",
        content_hash=content_hash,
    )
    defaults.update(kwargs)
    return PinFunction(**defaults)


def _make_edge(
    edge_id: str = "IMEDGE-0001",
    pin_func_id: str = "PFUNC-0001",
    projection_type: str = "pass_through",
    arch_location: str = "handler.py:handle",
    **kwargs,
) -> ImportEdge:
    defaults = dict(
        edge_id=edge_id,
        pin_func_id=pin_func_id,
        arch_location=arch_location,
        arch_file_path="handler.py",
        arch_line=10,
        projection_type=projection_type,
    )
    defaults.update(kwargs)
    return ImportEdge(**defaults)


def _make_registry(
    pin_functions: list[PinFunction],
    import_edges: list[ImportEdge] | None = None,
) -> PinFunctionRegistry:
    return PinFunctionRegistry(
        pin_functions=pin_functions,
        import_edges=import_edges or [],
        created_at=datetime.now(UTC).isoformat(),
    )


class TestChangeDetection:
    """Tests for detecting changes between registries."""

    def test_body_modification_detected(self):
        old_reg = _make_registry([_make_pf(content_hash="a" * 64)])
        new_reg = _make_registry([_make_pf(content_hash="b" * 64)])

        index = PinRegistryIndex.from_registry(new_reg)
        propagator = PinChangePropagator(index)

        changes = propagator.detect_changes(old_reg, new_reg)
        assert len(changes) == 1
        assert changes[0].change_type == "modified"
        assert changes[0].old_content_hash == "a" * 64
        assert changes[0].new_content_hash == "b" * 64

    def test_signature_change_detected(self):
        old_reg = _make_registry(
            [
                _make_pf(signature="(data: dict) -> bool"),
            ]
        )
        new_reg = _make_registry(
            [
                _make_pf(signature="(data: dict, strict: bool) -> bool"),
            ]
        )

        index = PinRegistryIndex.from_registry(new_reg)
        propagator = PinChangePropagator(index)

        changes = propagator.detect_changes(old_reg, new_reg)
        assert len(changes) == 1
        assert changes[0].change_type == "signature_changed"

    def test_function_added_detected(self):
        old_reg = _make_registry([_make_pf(pin_func_id="PFUNC-0001")])
        new_reg = _make_registry(
            [
                _make_pf(pin_func_id="PFUNC-0001"),
                _make_pf(
                    pin_func_id="PFUNC-0002",
                    function_name="compute_tax",
                    content_hash="c" * 64,
                ),
            ]
        )

        index = PinRegistryIndex.from_registry(new_reg)
        propagator = PinChangePropagator(index)

        changes = propagator.detect_changes(old_reg, new_reg)
        assert len(changes) == 1
        assert changes[0].change_type == "added"
        assert changes[0].function_name == "compute_tax"

    def test_function_removed_detected(self):
        old_reg = _make_registry(
            [
                _make_pf(pin_func_id="PFUNC-0001"),
                _make_pf(
                    pin_func_id="PFUNC-0002",
                    function_name="compute_tax",
                    content_hash="c" * 64,
                ),
            ]
        )
        new_reg = _make_registry([_make_pf(pin_func_id="PFUNC-0001")])

        index = PinRegistryIndex.from_registry(new_reg)
        propagator = PinChangePropagator(index)

        changes = propagator.detect_changes(old_reg, new_reg)
        assert len(changes) == 1
        assert changes[0].change_type == "removed"
        assert changes[0].function_name == "compute_tax"

    def test_no_changes_detected(self):
        reg = _make_registry([_make_pf()])

        index = PinRegistryIndex.from_registry(reg)
        propagator = PinChangePropagator(index)

        changes = propagator.detect_changes(reg, reg)
        assert changes == []


class TestPropagation:
    """Tests for change propagation to architectural locations."""

    def test_pass_through_auto_propagated(self):
        edge = _make_edge(projection_type="pass_through")
        reg = _make_registry(
            [_make_pf()],
            [edge],
        )
        index = PinRegistryIndex.from_registry(reg)
        propagator = PinChangePropagator(index)

        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="modified",
            old_content_hash="a" * 64,
            new_content_hash="b" * 64,
            diff_summary="Body modified",
        )

        report = propagator.propagate([change])
        assert report.auto_propagated_count == 1
        assert report.review_required_count == 0
        assert report.breaking_change_count == 0
        assert len(report.propagation_items) == 1
        assert report.propagation_items[0].review_urgency == "auto_propagated"

    def test_wrap_review_required(self):
        edge = _make_edge(projection_type="middleware_wrap")
        reg = _make_registry([_make_pf()], [edge])
        index = PinRegistryIndex.from_registry(reg)
        propagator = PinChangePropagator(index)

        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="modified",
            diff_summary="Body modified",
        )

        report = propagator.propagate([change])
        assert report.review_required_count == 1
        assert report.propagation_items[0].review_urgency == "review_required"

    def test_smear_review_required(self):
        edge = _make_edge(projection_type="smear")
        reg = _make_registry([_make_pf()], [edge])
        index = PinRegistryIndex.from_registry(reg)
        propagator = PinChangePropagator(index)

        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="modified",
            diff_summary="Body modified",
        )

        report = propagator.propagate([change])
        assert report.review_required_count == 1

    def test_signature_change_breaking(self):
        edge = _make_edge(projection_type="pass_through")
        reg = _make_registry([_make_pf()], [edge])
        index = PinRegistryIndex.from_registry(reg)
        propagator = PinChangePropagator(index)

        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="signature_changed",
            old_signature="(data: dict) -> bool",
            new_signature="(data: dict, strict: bool) -> bool",
            diff_summary="Signature changed",
        )

        report = propagator.propagate([change])
        assert report.breaking_change_count == 1
        assert report.propagation_items[0].review_urgency == "breaking_change"

    def test_removed_function_breaking(self):
        edge = _make_edge(projection_type="pass_through")
        reg = _make_registry([_make_pf()], [edge])
        index = PinRegistryIndex.from_registry(reg)
        propagator = PinChangePropagator(index)

        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="removed",
            diff_summary="Function removed",
        )

        report = propagator.propagate([change])
        assert report.breaking_change_count == 1

    def test_added_function_no_propagation(self):
        reg = _make_registry([_make_pf()], [])
        index = PinRegistryIndex.from_registry(reg)
        propagator = PinChangePropagator(index)

        change = PinChange(
            pin_func_id="PFUNC-0002",
            function_name="new_func",
            change_type="added",
            diff_summary="Function added",
        )

        report = propagator.propagate([change])
        assert len(report.propagation_items) == 0

    def test_empty_changes_no_propagation(self):
        reg = _make_registry([_make_pf()], [])
        index = PinRegistryIndex.from_registry(reg)
        propagator = PinChangePropagator(index)

        report = propagator.propagate([])
        assert report.propagation_items == []
        assert report.auto_propagated_count == 0
        assert report.review_required_count == 0
        assert report.breaking_change_count == 0

    def test_multiple_edges_for_same_change(self):
        """Test that one change propagates to all importers."""
        edges = [
            _make_edge(
                edge_id="IMEDGE-0001",
                projection_type="pass_through",
                arch_location="handler1.py:handle",
            ),
            _make_edge(
                edge_id="IMEDGE-0002",
                projection_type="middleware_wrap",
                arch_location="handler2.py:wrapped",
            ),
            _make_edge(
                edge_id="IMEDGE-0003", projection_type="smear", arch_location="handler3.py:combined"
            ),
        ]
        reg = _make_registry([_make_pf()], edges)
        index = PinRegistryIndex.from_registry(reg)
        propagator = PinChangePropagator(index)

        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="modified",
            diff_summary="Body modified",
        )

        report = propagator.propagate([change])
        assert len(report.propagation_items) == 3
        assert report.auto_propagated_count == 1  # PASS_THROUGH
        assert report.review_required_count == 2  # WRAP + SMEAR


class TestConvertPropagationToDrift:
    """Tests for converting PropagationReport to DriftItem objects."""

    def test_conversion_creates_drift_items(self):
        edge = _make_edge(projection_type="pass_through")
        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="modified",
            diff_summary="Body modified",
        )
        item = PropagationItem(
            import_edge=edge,
            pin_change=change,
            review_urgency="auto_propagated",
            reason="Auto-propagated change",
        )
        report = PropagationReport(
            changes=[change],
            propagation_items=[item],
            auto_propagated_count=1,
        )

        drift_items = convert_propagation_to_drift(report)
        assert len(drift_items) == 1
        assert isinstance(drift_items[0], DriftItem)
        assert drift_items[0].drift_type == "PLAN_ONLY"
        assert drift_items[0].pin_id == "PFUNC-0001"

    def test_breaking_change_produces_mismatch(self):
        edge = _make_edge(projection_type="pass_through")
        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="signature_changed",
            diff_summary="Signature changed",
        )
        item = PropagationItem(
            import_edge=edge,
            pin_change=change,
            review_urgency="breaking_change",
            reason="Breaking change",
        )
        report = PropagationReport(
            changes=[change],
            propagation_items=[item],
            breaking_change_count=1,
        )

        drift_items = convert_propagation_to_drift(report)
        assert drift_items[0].drift_type == "MISMATCH"
        assert drift_items[0].best_match_score == 0.0

    def test_empty_report_produces_no_drift(self):
        report = PropagationReport()
        drift_items = convert_propagation_to_drift(report)
        assert drift_items == []

    def test_review_required_produces_mismatch(self):
        edge = _make_edge(projection_type="middleware_wrap")
        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="modified",
            diff_summary="Body modified",
        )
        item = PropagationItem(
            import_edge=edge,
            pin_change=change,
            review_urgency="review_required",
            reason="Review required",
        )
        report = PropagationReport(
            changes=[change],
            propagation_items=[item],
            review_required_count=1,
        )

        drift_items = convert_propagation_to_drift(report)
        assert drift_items[0].drift_type == "MISMATCH"
        assert drift_items[0].best_match_score == 0.5


class TestUrgencyClassification:
    """Tests for classify_urgency method."""

    @pytest.fixture()
    def propagator(self) -> PinChangePropagator:
        reg = _make_registry([_make_pf()])
        index = PinRegistryIndex.from_registry(reg)
        return PinChangePropagator(index)

    def test_modified_pass_through(self, propagator):
        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="modified",
        )
        edge = _make_edge(projection_type="pass_through")
        assert propagator.classify_urgency(change, edge) == "auto_propagated"

    def test_modified_wrap(self, propagator):
        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="modified",
        )
        edge = _make_edge(projection_type="middleware_wrap")
        assert propagator.classify_urgency(change, edge) == "review_required"

    def test_modified_smear(self, propagator):
        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="modified",
        )
        edge = _make_edge(projection_type="smear")
        assert propagator.classify_urgency(change, edge) == "review_required"

    def test_signature_changed_any(self, propagator):
        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="signature_changed",
        )
        for pt in ["pass_through", "middleware_wrap", "smear", "introduction"]:
            edge = _make_edge(projection_type=pt)
            assert propagator.classify_urgency(change, edge) == "breaking_change"

    def test_removed_any(self, propagator):
        change = PinChange(
            pin_func_id="PFUNC-0001",
            function_name="validate",
            change_type="removed",
        )
        edge = _make_edge(projection_type="pass_through")
        assert propagator.classify_urgency(change, edge) == "breaking_change"
