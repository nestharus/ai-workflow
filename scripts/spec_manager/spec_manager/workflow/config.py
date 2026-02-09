"""Workflow configuration types.

Re-exports TrackedUnit and UnitType from core.provenance for use by
strategy and workflow modules.
"""

from __future__ import annotations

from spec_manager.core.provenance import TrackedUnit, UnitType

__all__ = ["TrackedUnit", "UnitType"]
