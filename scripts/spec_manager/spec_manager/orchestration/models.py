"""Backward-compatibility re-exports — canonical location is core.layer_types."""

from spec_manager.core.layer_types import *  # noqa: F403
from spec_manager.core.layer_types import (  # explicit re-exports for type checkers
    LAYER_ORDER,
    BatchResult,
    Lane,
    Layer,
    LayerStatus,
    MergeResult,
    PipelineTickResult,
    PropagateResult,
    next_layer,
    prev_layer,
)

__all__ = [
    "LAYER_ORDER",
    "BatchResult",
    "Lane",
    "Layer",
    "LayerStatus",
    "MergeResult",
    "PipelineTickResult",
    "PropagateResult",
    "next_layer",
    "prev_layer",
]
