"""Planner module: single auto-mode decision authority across the spec manager lifecycle.

The planner owns all gap-analysis, plan-synthesis, under-spec resolution,
and signal-routing decisions.  It dispatches to per-layer planners (L1/L2/L3)
via a LayerRouter, producing structured PlanningResults that downstream
consumers (PromotionLoop steps, interactive steering, etc.) can consume
without knowledge of layer-specific logic.

Key types:
    PlanningContext  -- per-request context (run, slice, layer, bundle refs)
    PlanningRequest  -- capability + context + inputs
    PlanningResult   -- status + outputs + trace
    Planner          -- main entry point; routes to layer planners
"""

from __future__ import annotations

from spec_manager.planner.api import (
    Planner,
    PlanningContext,
    PlanningRequest,
    PlanningResult,
)

__all__ = [
    "Planner",
    "PlanningContext",
    "PlanningRequest",
    "PlanningResult",
]
