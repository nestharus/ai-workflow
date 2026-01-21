"""Multi-label library discovery module.

This module implements the library discovery workflow where libraries
EMERGE from the data rather than being predefined.

The discovery process:
1. CANDIDATE IDENTIFICATION - Look at all elements, identify BIG systems
2. MULTI-LABEL ASSIGNMENT - Assign confidence scores for each library
3. SHAPE AGGREGATION - Aggregate labels to see library shapes
4. LIBRARY REFINEMENT - Iteratively refine until stable
5. PRIMARY ASSIGNMENT - Each element gets one primary label

Key insight: Libraries EMERGE from the data. You don't predefine them.

Usage:
    from spec_manager.discovery import (
        CandidateIdentifier,
        MultiLabeler,
        ShapeAggregator,
        LibraryRefiner,
        discover_libraries,
    )

    # Full workflow
    labels = await discover_libraries(units)

    # Or step by step:
    identifier = CandidateIdentifier()
    candidates = identifier.discover_with_all_signals(units)

    labeler = MultiLabeler(candidates)
    labels = labeler.label_all(units)

    aggregator = ShapeAggregator(labels)
    shapes = aggregator.aggregate()

    refiner = LibraryRefiner(units)
    result = refiner.refine(candidates)
    final_labels = refiner.finalize()
"""

from spec_manager.discovery.aggregation import (
    LibraryShape,
    ShapeAggregator,
)
from spec_manager.discovery.candidate import (
    CandidateIdentifier,
    CandidateLibrary,
    LibraryEvent,
)
from spec_manager.discovery.labeling import (
    ElementLabels,
    MultiLabeler,
)
from spec_manager.discovery.refinement import (
    LibraryRefiner,
    RefinementResult,
    discover_libraries,
    discover_libraries_keyword_only,
    discover_libraries_sync,
)

__all__ = [
    # Candidate identification
    "CandidateLibrary",
    "CandidateIdentifier",
    "LibraryEvent",
    # Multi-labeling
    "ElementLabels",
    "MultiLabeler",
    # Shape aggregation
    "LibraryShape",
    "ShapeAggregator",
    # Refinement
    "RefinementResult",
    "LibraryRefiner",
    # Workflow functions
    "discover_libraries",
    "discover_libraries_sync",
    "discover_libraries_keyword_only",
]
