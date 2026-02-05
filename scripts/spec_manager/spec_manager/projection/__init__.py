"""Projection module for generating L2 documents from L1 sources.

This module provides:
- generator: Plan projection generator (ALG-PROJ-0001)
- drift: Atom-aware drift comparator (ALG-PROJ-0002/0003)

Phase 7: Projection Pins, Atom-Aware Drift, and Legacy Removal

Imports are lazy to avoid circular import issues with spec_manager.core.gaps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Lazy imports to avoid circular import with spec_manager.core.gaps
# which transitively imports many modules
__all__ = [
    # Generator
    "ProjectionGenerator",
    "generate_plan_from_libraries",
    # Drift
    "AtomAwareDriftComparator",
    "AtomAlignment",
    "DriftItem",
    "DriftPolicy",
    "DriftReport",
    "convert_drift_to_gaps",
]


def __getattr__(name: str):
    """Lazy import to avoid circular imports."""
    if name in ("ProjectionGenerator", "generate_plan_from_libraries"):
        from spec_manager.projection.generator import (
            ProjectionGenerator,
            generate_plan_from_libraries,
        )

        if name == "ProjectionGenerator":
            return ProjectionGenerator
        return generate_plan_from_libraries

    if name in (
        "AtomAwareDriftComparator",
        "AtomAlignment",
        "DriftItem",
        "DriftPolicy",
        "DriftReport",
        "convert_drift_to_gaps",
    ):
        from spec_manager.projection.drift import (
            AtomAwareDriftComparator,
            AtomAlignment,
            DriftItem,
            DriftPolicy,
            DriftReport,
            convert_drift_to_gaps,
        )

        return {
            "AtomAwareDriftComparator": AtomAwareDriftComparator,
            "AtomAlignment": AtomAlignment,
            "DriftItem": DriftItem,
            "DriftPolicy": DriftPolicy,
            "DriftReport": DriftReport,
            "convert_drift_to_gaps": convert_drift_to_gaps,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
