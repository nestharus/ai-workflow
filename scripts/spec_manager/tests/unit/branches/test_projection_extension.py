"""Tests for the ATOM_FUNCTION extension to the Pin schema."""

from __future__ import annotations

from spec_manager.schemas.projection import Pin


class TestPinAtomFunction:
    """Verify Pin now supports ATOM_FUNCTION target_kind."""

    def test_atom_function_kind_accepted(self) -> None:
        pin = Pin(
            pin_id="PIN-0001",
            from_projection_offset=0,
            target_id="validate_payment",
            target_kind="ATOM_FUNCTION",
        )
        assert pin.target_kind == "ATOM_FUNCTION"

    def test_original_kinds_still_work(self) -> None:
        for kind in ("LIBRARY", "ELEMENT", "ATOM_RANGE"):
            pin = Pin(
                pin_id="PIN-0001",
                from_projection_offset=0,
                target_id="TEST-0001",
                target_kind=kind,
            )
            assert pin.target_kind == kind
