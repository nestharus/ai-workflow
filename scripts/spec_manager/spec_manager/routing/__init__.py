# TODO(single-layer): NEW — Shape-based routing package (Section 12.4).
#   Three modules: shapes.py, verifiers.py, matcher.py.
#   Replaces PIN system + layer pipeline with external structural pattern matching.
#   Used across all 3 forward-only phases: Libraries → Architecture → Quality.
# ALGORITHM(single-layer):
#   References: response3 Section 12.4.
#   Phase model: 3 forward-only phases — Libraries → Architecture → Quality.
#     PhaseId = Literal['libraries', 'architecture', 'quality'].
#     Each phase edits code via its own PromotionLoop with IMPLEMENT step.
#     No backtracking: phases block (not demote) if they encounter something
#     outside their authority.
#   Data structures:
#     - No new data model; this package is the canonical export surface for Shape, ShapeMatchReport, VerifierResult, and loader/runner helpers.
#   Interface contracts:
#     - Re-export from shapes.py: Shape, ShapeId, ShapePackIndex, load_shape_pack, resolve_shape_for_file.
#     - Re-export from verifiers.py: VerifierResult, run_shape_verifiers, run_all_active_shape_verifiers.
#     - Re-export from matcher.py: ShapeMatchReport, match_all_shapes, generate_work_items_from_reports.
# IMPL(single-layer): Keep matcher access package-scoped through these re-exports;
# avoid direct `from spec_manager.routing.matcher ...` imports in downstream modules.
# IMPL(single-layer): Keep verifier runner/result usage package-scoped as well;
# downstream modules should consume verifier APIs through this module.
# IMPL(single-layer): Keep orchestration-facing verifier contracts package-scoped too
# (`VerifierRunSummary`, `enforce_non_ship_policy`) so gate/lifecycle callers do not
# bind to `routing.verifiers` module-local paths.
#   Control flow:
#     1. Keep __all__ explicit and stable.
#     2. Avoid backward-compat aliases to pin/layer terminology.
# IMPL(single-layer): Treat package re-export wiring as one-way API composition;
# routing internals continue sibling-module imports to avoid `routing.__init__`
# re-entry/cycle risk during module import.
#   Error handling:
#     - Import errors must fail fast; do not silently mask missing modules.
#   Integration points:
#     - Called by orchestration/planner/compliance modules as single routing entrypoint.
#     - All 3 phases (libraries, architecture, quality) use this package for shape-based routing.
# IMPL(single-layer): This module is the external import boundary for routing APIs;
# direct `routing.shapes|verifiers|matcher` imports are implementation details.
#   Test requirements:
#     - Public API smoke test verifies symbols exist and resolve to intended modules.

"""Shape-based routing: parse shapes, run verifiers, match declared vs observed."""

from __future__ import annotations

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.routing.matcher import (
    ShapeMatchReport,
    generate_work_items_from_reports,
    match_all_shapes,
)
from spec_manager.routing.shapes import (
    Shape,
    ShapeId,
    ShapePackIndex,
    load_shape_pack,
    resolve_shape_for_file,
)
from spec_manager.routing.verifiers import (
    VerifierResult,
    VerifierRunSummary,
    enforce_non_ship_policy,
    run_all_active_shape_verifiers,
    run_shape_verifiers,
)

__all__ = [
    "PhaseId",
    "Shape",
    "ShapeId",
    "ShapeMatchReport",
    "ShapePackIndex",
    "VerifierResult",
    "VerifierRunSummary",
    "enforce_non_ship_policy",
    "generate_work_items_from_reports",
    "load_shape_pack",
    "match_all_shapes",
    "resolve_shape_for_file",
    "run_all_active_shape_verifiers",
    "run_shape_verifiers",
]
