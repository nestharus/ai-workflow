"""Shared types for the multi-layer promotion pipeline.

Defines Layer, Lane, and result types used by WorktreeManager,
PromotionLoop, and the batch CI pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Layer = Literal["l1", "l2", "l3"]
Lane = Literal["dirty", "clean"]

LAYER_ORDER: list[Layer] = ["l1", "l2", "l3"]


def next_layer(layer: Layer) -> Layer | None:
    """Return the next layer in the pipeline, or None if at L3."""
    idx = LAYER_ORDER.index(layer)
    if idx + 1 < len(LAYER_ORDER):
        return LAYER_ORDER[idx + 1]
    return None


def prev_layer(layer: Layer) -> Layer | None:
    """Return the previous layer in the pipeline, or None if at L1."""
    idx = LAYER_ORDER.index(layer)
    if idx > 0:
        return LAYER_ORDER[idx - 1]
    return None


@dataclass
class MergeResult:
    """Result of merging a slice branch into a layer's dirty worktree."""

    success: bool
    slice_id: str
    layer: Layer
    merge_sha: str | None = None
    error: str = ""
    conflict_files: list[str] = field(default_factory=list)


@dataclass
class BatchResult:
    """Result of promoting dirty to clean at a single layer."""

    success: bool
    layer: Layer
    candidate_sha: str | None = None
    clean_sha: str | None = None
    gates_passed: bool = True
    tests_passed: bool = True
    error: str = ""
    demotion_tickets: list[str] = field(default_factory=list)


@dataclass
class PropagateResult:
    """Result of propagating clean from one layer to the next layer's dirty."""

    success: bool
    from_layer: Layer
    to_layer: Layer
    merge_sha: str | None = None
    error: str = ""
    conflict_files: list[str] = field(default_factory=list)


@dataclass
class PipelineTickResult:
    """Result of one tick_pipeline() call across all layers."""

    layer_results: dict[Layer, BatchResult] = field(default_factory=dict)
    propagation_results: list[PropagateResult] = field(default_factory=list)
    main_updated: bool = False
    main_sha: str | None = None
    demotion_tickets: list[str] = field(default_factory=list)


@dataclass
class LayerStatus:
    """Status snapshot for a single layer."""

    layer: Layer
    dirty_sha: str | None = None
    clean_sha: str | None = None
    candidate_sha: str | None = None
    is_clean: bool = False
    pending_commits: int = 0
    upstream_accepted_sha: str | None = None
