"""Tests for the PinFunctionSchema Pydantic model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spec_manager.schemas.pin_function import PinFunctionSchema


class TestPinFunctionSchema:
    """Tests for PinFunctionSchema validation."""

    def test_valid_minimal(self) -> None:
        schema = PinFunctionSchema(
            pin_id="PIN-0001",
            atom_id="validate_payment",
            architectural_location="services/payment:PaymentService.validate",
            projection_type="pass_through",
        )
        assert schema.pin_id == "PIN-0001"
        assert schema.confidence == 1.0
        assert schema.wrapper_hash is None

    def test_valid_full(self) -> None:
        schema = PinFunctionSchema(
            pin_id="PIN-9999",
            atom_id="apply_discount",
            architectural_location="services/discount:DiscountService.apply",
            projection_type="aggregation",
            confidence=0.85,
            wrapper_hash="abc123",
        )
        assert schema.projection_type == "aggregation"
        assert schema.confidence == 0.85

    def test_invalid_pin_id_format(self) -> None:
        with pytest.raises(ValidationError, match="pin_id must match"):
            PinFunctionSchema(
                pin_id="INVALID",
                atom_id="x",
                architectural_location="y",
                projection_type="pass_through",
            )

    def test_invalid_pin_id_short(self) -> None:
        with pytest.raises(ValidationError, match="pin_id must match"):
            PinFunctionSchema(
                pin_id="PIN-01",
                atom_id="x",
                architectural_location="y",
                projection_type="pass_through",
            )

    def test_invalid_projection_type(self) -> None:
        with pytest.raises(ValidationError):
            PinFunctionSchema(
                pin_id="PIN-0001",
                atom_id="x",
                architectural_location="y",
                projection_type="invalid_type",
            )

    def test_confidence_out_of_range_high(self) -> None:
        with pytest.raises(ValidationError, match="confidence"):
            PinFunctionSchema(
                pin_id="PIN-0001",
                atom_id="x",
                architectural_location="y",
                projection_type="pass_through",
                confidence=1.5,
            )

    def test_confidence_out_of_range_low(self) -> None:
        with pytest.raises(ValidationError, match="confidence"):
            PinFunctionSchema(
                pin_id="PIN-0001",
                atom_id="x",
                architectural_location="y",
                projection_type="pass_through",
                confidence=-0.1,
            )

    def test_all_projection_types(self) -> None:
        for ptype in ("pass_through", "projection", "aggregation", "introduction"):
            schema = PinFunctionSchema(
                pin_id="PIN-0001",
                atom_id="x",
                architectural_location="y",
                projection_type=ptype,
            )
            assert schema.projection_type == ptype
