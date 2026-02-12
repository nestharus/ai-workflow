"""Planner constraints sub-package: types, store, bootstrap, impact, authority."""

from __future__ import annotations

from spec_manager.planner.constraints.store import Constraint, ConstraintsStore
from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter
from spec_manager.planner.constraints.types import (
    ConflictReport,
    ConstraintContext,
    ConstraintFact,
    ConstraintHypothesis,
    ConstraintIndexEntry,
    DecisionRequirement,
    ImpactClassification,
    ProblemFrame,
)

__all__ = [
    "ConflictReport",
    "Constraint",
    "ConstraintContext",
    "ConstraintFact",
    "ConstraintHypothesis",
    "ConstraintIndexEntry",
    "ConstraintStoreAdapter",
    "ConstraintsStore",
    "DecisionRequirement",
    "ImpactClassification",
    "ProblemFrame",
]
