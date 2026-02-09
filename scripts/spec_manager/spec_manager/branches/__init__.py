"""Branch organization system for spec manager.

Maintains multiple parallel representations of code (algorithmic,
architectural, analysis), manages promotion workflows between them
via pin-functions, handles downward flow for issue resolution, collapses
untracked systems to Layer 1, and structures horizontal/vertical slices
within each branch.

Delegation pattern
------------------
Several modules in this package delegate their core logic to canonical
implementations elsewhere in the codebase:

- ``gap_detection`` -> ``compliance.detection.comment_scanner``,
  ``compliance.detection.stub_scanner``
- ``compliance`` -> ``compliance.promotion.algorithmic_gates``
- ``promotion`` -> ``compliance.promotion.orchestrator``
- ``analysis`` -> ``analysis.adjacency.graph.AdjacencyGraph``
- ``collapse`` -> ``core.code_analysis.analyze_source`` (via pin_functions orchestrator)
- ``pins`` -> keeps own implementation with documentation pointing to
  ``core.pin_registry.PinRegistryIndex`` for O(1) alternative

Unique modules (no delegation):
- ``types`` -- domain enums and dataclasses
- ``layout`` -- directory structure management
- ``slices`` -- vertical/horizontal slice navigation
- ``downward_flow`` -- issue tracing facade
- ``atoms`` -- in-memory atom store
- ``manager`` -- unified facade
"""

from __future__ import annotations

from .analysis import AnalysisGenerator, AnalysisReport
from .atoms import AtomRegistry
from .collapse import CollapseEngine, CollapseResult
from .compliance import ComplianceChecker, ComplianceGateResult
from .downward_flow import ArchitecturalIssue, DownwardFlowEngine, DownwardTraceResult
from .gap_detection import GapDetector, GapItem
from .layout import BranchLayout
from .manager import BranchManager
from .pins import DriftReport, PinRegistry
from .promotion import PromotionEngine, PromotionResult
from .slices import HorizontalLayer, SliceNavigator
from .types import (
    AtomDescriptor,
    AtomKind,
    BranchKind,
    PinProjection,
    ProjectionType,
    SliceOrientation,
    StoreType,
    VerticalSlice,
)

__all__ = [
    "AnalysisGenerator",
    "AnalysisReport",
    "ArchitecturalIssue",
    "AtomDescriptor",
    "AtomKind",
    "AtomRegistry",
    "BranchKind",
    "BranchLayout",
    "BranchManager",
    "CollapseEngine",
    "CollapseResult",
    "ComplianceChecker",
    "ComplianceGateResult",
    "DownwardFlowEngine",
    "DownwardTraceResult",
    "DriftReport",
    "GapDetector",
    "GapItem",
    "HorizontalLayer",
    "PinProjection",
    "PinRegistry",
    "ProjectionType",
    "PromotionEngine",
    "PromotionResult",
    "SliceNavigator",
    "SliceOrientation",
    "StoreType",
    "VerticalSlice",
]
