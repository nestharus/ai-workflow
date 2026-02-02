"""Spec Manager - General-purpose specification management library.

This library provides tools for managing specification folders containing:
- Libraries (domain-specific markdown files)
- libs.md (ID to library assignment registry)
- gaps.md (tracking unresolved gaps and proof obligations)
- Patches (incremental changes to specifications)
- Input files (incoming plans/patches to be decomposed)

The system uses a 4-phase workflow:
1. CLEANING: Validate and legalize incoming content
2. DISCOVERY: Decompose changes into safe batches
3. REVIEW: Apply batches to library files
4. FINALIZATION: Confirm no drift or duplication

Key concepts:
- Annotations: ([=ID]) declarations and (@[+ID]), (@[=ID]) references
- Projections: Transform prose to artifacts (not fact extraction)
- Divergence/Convergence: Detect library split/merge candidates

Usage:
    # CLI
    uv run spec-manager init <spec_folder>
    uv run spec-manager run <spec_folder> --apply

    # Python API
    from spec_manager import WorkspaceManager
    from spec_manager.staging import run_staging  # CLEANING phase
    from spec_manager.planning import run_planning  # DISCOVERY phase
    from spec_manager.merging import run_merging  # REVIEW phase
    from spec_manager.verification import run_verification  # FINALIZATION phase
    from spec_manager.analysis import run_analysis
"""

from __future__ import annotations

import sys
from pathlib import Path

_SPEC_MANAGER_ROOT = Path(__file__).resolve().parent.parent
if str(_SPEC_MANAGER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPEC_MANAGER_ROOT))

__all__ = [
    # Core
    "AnnotationParser",
    "IdValidator",
    "LibsRegistry",
    "SectionExtractor",
    # Discovery
    "CandidateIdentifier",
    "CandidateLibrary",
    "discover_libraries",
    "discover_libraries_sync",
    "ElementLabels",
    "LibraryRefiner",
    "LibraryShape",
    "MultiLabeler",
    "ShapeAggregator",
    # Provenance
    "ProvenanceTracker",
    "SourceLocation",
    "TrackedUnit",
    "UnitStatus",
    "UnitType",
    # Strategies
    "ProcessingContext",
    "Strategy",
    "StrategyPhase",
    "StrategyRegistry",
    "StrategyResult",
    # Workspace
    "WorkspaceManager",
    # Workflow
    "ContextIndex",
    "PatchDependencyGraph",
    "WorkflowConfig",
    "WorkflowOrchestrator",
    "WorkflowPhase",
    "WorkflowState",
    "ingest",
    # Phase runners (legacy names, mapped to new phases)
    "run_analysis",
    "run_merging",  # REVIEW phase
    "run_planning",  # DISCOVERY phase
    "run_staging",  # CLEANING phase
    "run_verification",  # FINALIZATION phase
]


def __getattr__(name: str) -> object:
    """Lazy imports to avoid circular dependencies."""
    if name in ("AnnotationParser", "SectionExtractor", "IdValidator", "LibsRegistry"):
        from .core import (
            AnnotationParser,
            IdValidator,
            LibsRegistry,
            SectionExtractor,  # noqa: F401
        )

        return locals()[name]

    if name in ("TrackedUnit", "SourceLocation", "UnitType", "UnitStatus", "ProvenanceTracker"):
        from .core import (
            ProvenanceTracker,  # noqa: F401
            SourceLocation,  # noqa: F401
            TrackedUnit,  # noqa: F401
            UnitStatus,  # noqa: F401
            UnitType,  # noqa: F401
        )

        return locals()[name]

    if name in (
        "StrategyRegistry",
        "Strategy",
        "StrategyPhase",
        "ProcessingContext",
        "StrategyResult",
    ):
        from .strategies import (
            ProcessingContext,  # noqa: F401
            Strategy,  # noqa: F401
            StrategyPhase,  # noqa: F401
            StrategyRegistry,  # noqa: F401
            StrategyResult,  # noqa: F401
        )

        return locals()[name]

    if name == "WorkspaceManager":
        from .workspace import WorkspaceManager

        return WorkspaceManager

    if name == "run_staging":
        from .staging import run_staging

        return run_staging

    if name == "run_planning":
        from .planning import run_planning

        return run_planning

    if name == "run_merging":
        from .merging import run_merging

        return run_merging

    if name == "run_verification":
        from .verification import run_verification

        return run_verification

    if name == "run_analysis":
        from .analysis import run_analysis

        return run_analysis

    if name in (
        "WorkflowOrchestrator",
        "WorkflowConfig",
        "WorkflowState",
        "WorkflowPhase",
        "PatchDependencyGraph",
        "ingest",
        "ContextIndex",
    ):
        from .workflow import (
            ContextIndex,  # noqa: F401
            PatchDependencyGraph,  # noqa: F401
            WorkflowConfig,  # noqa: F401
            WorkflowOrchestrator,  # noqa: F401
            WorkflowPhase,  # noqa: F401
            WorkflowState,  # noqa: F401
            ingest,  # noqa: F401
        )

        return locals()[name]

    if name in (
        "CandidateLibrary",
        "CandidateIdentifier",
        "ElementLabels",
        "MultiLabeler",
        "LibraryShape",
        "ShapeAggregator",
        "LibraryRefiner",
        "discover_libraries",
        "discover_libraries_sync",
    ):
        from .discovery import (
            CandidateIdentifier,  # noqa: F401
            CandidateLibrary,  # noqa: F401
            ElementLabels,  # noqa: F401
            LibraryRefiner,  # noqa: F401
            LibraryShape,  # noqa: F401
            MultiLabeler,  # noqa: F401
            ShapeAggregator,  # noqa: F401
            discover_libraries,  # noqa: F401
            discover_libraries_sync,  # noqa: F401
        )

        return locals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
