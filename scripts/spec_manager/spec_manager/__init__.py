"""Spec Manager - General-purpose specification management library.

This library provides tools for managing specification folders containing:
- Libraries (domain-specific markdown files)
- libs.md (ID to library assignment registry)
- gaps.md (tracking unresolved gaps and proof obligations)
- Patches (incremental changes to specifications)
- Input files (incoming plans/patches to be decomposed)

The system consists of:
1. Refinement Pipeline: 19-phase modern orchestration for spec refinement
2. PDD Modules: Standalone packages for prototype-driven development
   - branches: Branch lifecycle management
   - pin_functions: Pin-function management
   - planning: Algorithmic planning (code parser, inserter, reverser)
   - compliance: Detection, promotion, and coverage analysis

Key concepts:
- Annotations: ([=ID]) declarations and (@[+ID]), (@[=ID]) references
- Projections: Transform prose to artifacts (not fact extraction)
- Divergence/Convergence: Detect library split/merge candidates

Usage:
    # CLI
    uv run spec refine <run_id> --auto
    uv run spec branches run <run_id>

    # Python API
    from spec_manager.analysis import run_analysis
"""

from __future__ import annotations

import sys
from pathlib import Path

_SPEC_MANAGER_ROOT = Path(__file__).resolve().parent.parent
if str(_SPEC_MANAGER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPEC_MANAGER_ROOT))

__all__ = [
    "AnnotationParser",
    "IdValidator",
    "LibsRegistry",
    "ProcessingContext",
    "ProvenanceTracker",
    "SectionExtractor",
    "SourceLocation",
    "Strategy",
    "StrategyPhase",
    "StrategyRegistry",
    "StrategyResult",
    "TrackedUnit",
    "UnitStatus",
    "UnitType",
    "run_analysis",
]


def __getattr__(name: str) -> object:
    """Lazy imports to avoid circular dependencies."""
    if name in ("AnnotationParser", "SectionExtractor", "IdValidator", "LibsRegistry"):
        from .core import (
            AnnotationParser,  # noqa: F401
            IdValidator,  # noqa: F401
            LibsRegistry,  # noqa: F401
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

    if name == "run_analysis":
        from .analysis import run_analysis

        return run_analysis

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
