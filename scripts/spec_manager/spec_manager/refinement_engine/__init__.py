"""Continuous coupling/cohesion refinement engine for PDD.

Detects structural issues (overlap, divergence, overload) in the entity
graph and proposes atomic restructuring operations (create, modify, remove,
split, merge, move).

This module replaces the old discovery/ TF-IDF approach with mechanical,
AST/graph-based detection using the adjacency graph from
``analysis.adjacency``.
"""

from spec_manager.refinement_engine.detector import (
    CouplingIssue,
    detect_all,
    detect_divergence,
    detect_overlap,
    detect_overload,
)
from spec_manager.refinement_engine.executor import RefinementExecutor
from spec_manager.refinement_engine.operations import (
    RefinementOperation,
    propose_operations,
    validate_operation,
)

__all__ = [
    "CouplingIssue",
    "RefinementExecutor",
    "RefinementOperation",
    "detect_all",
    "detect_divergence",
    "detect_overlap",
    "detect_overload",
    "propose_operations",
    "validate_operation",
]
