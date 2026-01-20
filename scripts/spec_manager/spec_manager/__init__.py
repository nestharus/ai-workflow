"""
Spec Manager - General-purpose specification management library.

This library provides tools for managing specification folders containing:
- Libraries (domain-specific markdown files)
- libs.md (ID to library assignment registry)
- gaps.md (tracking unresolved gaps and proof obligations)
- Patches (incremental changes to specifications)
- Input files (incoming plans/patches to be decomposed)

The system uses a 4-phase workflow:
1. STAGING: Validate and legalize incoming content
2. PLANNING: Decompose changes into safe batches
3. MERGING: Apply batches to library files
4. VERIFICATION: Confirm no drift or duplication

Key concepts:
- Annotations: ([=ID]) declarations and (@[+ID]), (@[=ID]) references
- Projections: Transform prose to artifacts (not fact extraction)
- Divergence/Convergence: Detect library split/merge candidates

Usage:
    # CLI
    uv run python -m scripts.spec_manager init <spec_folder>
    uv run python -m scripts.spec_manager run <spec_folder> --apply

    # Python API
    from spec_manager import WorkspaceManager
    from spec_manager.staging import run_staging
    from spec_manager.planning import run_planning
    from spec_manager.merging import run_merging
    from spec_manager.verification import run_verification
    from spec_manager.analysis import run_analysis
"""

__all__ = [
    # Core
    "AnnotationParser",
    "SectionExtractor",
    "IdValidator",
    "LibsRegistry",
    # Provenance
    "TrackedUnit",
    "SourceLocation",
    "UnitType",
    "UnitStatus",
    "ProvenanceTracker",
    # Strategies
    "StrategyRegistry",
    "Strategy",
    "StrategyPhase",
    "ProcessingContext",
    "StrategyResult",
    # Discovery
    "CandidateLibrary",
    "CandidateIdentifier",
    "ElementLabels",
    "MultiLabeler",
    "LibraryShape",
    "ShapeAggregator",
    "LibraryRefiner",
    "discover_libraries",
    "discover_libraries_sync",
    # Workspace
    "WorkspaceManager",
    # Workflow
    "WorkflowOrchestrator",
    "WorkflowConfig",
    "WorkflowState",
    "WorkflowPhase",
    "PatchDependencyGraph",
    "ContextIndex",
    "ingest",
    # Phase runners
    "run_staging",
    "run_planning",
    "run_merging",
    "run_verification",
    "run_analysis",
]


def __getattr__(name: str):
    """Lazy imports to avoid circular dependencies."""
    if name in ("AnnotationParser", "SectionExtractor", "IdValidator", "LibsRegistry"):
        from spec_manager.core import (
            AnnotationParser,
            SectionExtractor,
            IdValidator,
            LibsRegistry,
        )
        return locals()[name]

    if name in ("TrackedUnit", "SourceLocation", "UnitType", "UnitStatus", "ProvenanceTracker"):
        from spec_manager.core import (
            TrackedUnit,
            SourceLocation,
            UnitType,
            UnitStatus,
            ProvenanceTracker,
        )
        return locals()[name]

    if name in ("StrategyRegistry", "Strategy", "StrategyPhase", "ProcessingContext", "StrategyResult"):
        from spec_manager.strategies import (
            StrategyRegistry,
            Strategy,
            StrategyPhase,
            ProcessingContext,
            StrategyResult,
        )
        return locals()[name]

    if name == "WorkspaceManager":
        from spec_manager.workspace import WorkspaceManager
        return WorkspaceManager

    if name == "run_staging":
        from spec_manager.staging import run_staging
        return run_staging

    if name == "run_planning":
        from spec_manager.planning import run_planning
        return run_planning

    if name == "run_merging":
        from spec_manager.merging import run_merging
        return run_merging

    if name == "run_verification":
        from spec_manager.verification import run_verification
        return run_verification

    if name == "run_analysis":
        from spec_manager.analysis import run_analysis
        return run_analysis

    if name in ("WorkflowOrchestrator", "WorkflowConfig", "WorkflowState", "WorkflowPhase",
                "PatchDependencyGraph", "ContextIndex", "ingest"):
        from spec_manager.workflow import (
            WorkflowOrchestrator,
            WorkflowConfig,
            WorkflowState,
            WorkflowPhase,
            PatchDependencyGraph,
            ContextIndex,
            ingest,
        )
        return locals()[name]

    if name in ("CandidateLibrary", "CandidateIdentifier", "ElementLabels", "MultiLabeler",
                "LibraryShape", "ShapeAggregator", "LibraryRefiner",
                "discover_libraries", "discover_libraries_sync"):
        from spec_manager.discovery import (
            CandidateLibrary,
            CandidateIdentifier,
            ElementLabels,
            MultiLabeler,
            LibraryShape,
            ShapeAggregator,
            LibraryRefiner,
            discover_libraries,
            discover_libraries_sync,
        )
        return locals()[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
