"""Core data structures for spec_manager v2.0 state schema.

This module provides conflict-resolution, metrics, and queue data structures.
Canonical gap domain types are sourced from ``spec_manager.core.gap``.

Key Concepts:
    - Evidence-based gaps: Gaps are identified through collected evidence, with stable
      IDs computed from evidence signatures for reproducibility across runs.
    - Conflict resolution: Duplicate elements are bundled with heuristic scoring to
      recommend resolution strategies.
    - Compliance metrics: Quality gates based on format compliance, annotation coverage,
      and ID normalization thresholds.
    - Strategy records: Execution history tracking for strategy applications with
      validation status and metrics.

Type Naming (collision avoidance):
    Gap domain types are imported from core.gap:

    - GapEvidence (core.gap): evidence with invariant_family, confidence
    - DetectorFinding (gaps.py): Raw detector output (simpler structure)

    - Gap (core.gap): first-class gap with evidence-based ID
    - GapElement (gaps.py): Synthesized gap for gaps.md output

    - WorkflowEvidence (orchestrator.py): Evidence collected during workflow

    When importing, be explicit about which module you need:
        from spec_manager.core.data_structures import Gap, GapEvidence
        from spec_manager.core.gaps import DetectorFinding, GapElement  # synthesis

Related Modules:
    - gaps.py: Contains Severity enum, DetectorFinding, GapElement
    - state.py: State management using these data structures
    - provenance.py: Unit tracking and provenance chains

Usage:
    from spec_manager.core.data_structures import (
        STATUS_OPEN,
        ComplianceMetrics,
        ConflictBundle,
        Gap,
        GapEvidence,
        RemainderQueue,
        StrategyRecord,
        compute_evidence_signature,
    )
    from .gaps import Severity

    # Create compliance metrics and check quality gate
    metrics = ComplianceMetrics(
        format_compliance=0.98,
        annotation_coverage=0.95,
        id_normalization=0.99,
    )
    if metrics.gate_passed():
        print("Quality gate passed")

    # Track gap evidence and compute stable ID
    evidence = [
        GapEvidence(
            invariant_family="format",
            description="Invalid ID pattern",
            details={"expected": "P#I#", "found": "I#"},
            confidence=0.95,
        )
    ]
    signature = compute_evidence_signature(evidence)
    gap = Gap(
        id=f"GAP-{signature}",
        severity=Severity.WARNING,
        evidence=evidence,
        status=STATUS_OPEN,
    )
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import gap as _gap_domain

Gap = _gap_domain.Gap
GapEvidence = _gap_domain.GapEvidence
_safe_serialize_details = _gap_domain._safe_serialize_details
compute_evidence_signature = _gap_domain.compute_evidence_signature

# =============================================================================
# Status Constants
# =============================================================================

STATUS_PENDING: str = "pending"
STATUS_OPEN: str = "open"
STATUS_RESOLVED: str = "resolved"
STATUS_BYPASSED: str = "bypassed"
STATUS_DEFERRED: str = "deferred"
STATUS_PASSED: str = "passed"
STATUS_FAILED: str = "failed"
STATUS_AUTO_RESOLVED: str = "auto_resolved"
STATUS_MANUAL_REQUIRED: str = "manual_required"
STATUS_IN_PROGRESS: str = "in_progress"


# =============================================================================
# Type Aliases
# =============================================================================

ValidationStatus = str
ResolutionStatus = str


# =============================================================================
# Compliance Metrics
# =============================================================================


@dataclass
class ComplianceMetrics:
    """Quality metrics for specification compliance.

    Tracks format compliance, annotation coverage, and ID normalization
    percentages. Provides a quality gate check against a configurable threshold.

    All metric values must be in the range [0.0, 1.0]. Values outside this range
    will raise a ValueError during instantiation.

    Attributes:
        format_compliance: Percentage of IDs matching canonical patterns (0.0-1.0).
        annotation_coverage: Percentage of elements with proper annotations (0.0-1.0).
        id_normalization: Percentage of IDs properly normalized (0.0-1.0).
        gate_threshold: Minimum threshold for passing quality gate (default 0.95).

    Raises:
        ValueError: If any metric value is outside the [0.0, 1.0] range.
    """

    format_compliance: float
    annotation_coverage: float
    id_normalization: float
    gate_threshold: float = 0.95

    def __post_init__(self) -> None:
        """Validate that all metric values are within [0.0, 1.0]."""
        metrics = {
            "format_compliance": self.format_compliance,
            "annotation_coverage": self.annotation_coverage,
            "id_normalization": self.id_normalization,
            "gate_threshold": self.gate_threshold,
        }
        for name, value in metrics.items():
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be in range [0.0, 1.0], got {value}")

    def gate_passed(self) -> bool:
        """Check if all metrics meet or exceed the gate threshold."""
        return (
            self.format_compliance >= self.gate_threshold
            and self.annotation_coverage >= self.gate_threshold
            and self.id_normalization >= self.gate_threshold
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "format_compliance": self.format_compliance,
            "annotation_coverage": self.annotation_coverage,
            "id_normalization": self.id_normalization,
            "gate_threshold": self.gate_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComplianceMetrics:
        """Deserialize from dictionary."""
        return cls(
            format_compliance=data["format_compliance"],
            annotation_coverage=data["annotation_coverage"],
            id_normalization=data["id_normalization"],
            gate_threshold=data.get("gate_threshold", 0.95),
        )


# =============================================================================
# Conflict Resolution Structures
# =============================================================================


@dataclass
class ConflictVariant:
    """A single variant of a conflicting element.

    When multiple elements share the same ID, each occurrence is tracked
    as a variant with its content, location, and heuristic scoring.

    Attributes:
        id: Unique identifier for this specific variant instance
            (e.g., "REQ-001-v1", "REQ-001-v2"). Used to distinguish among
            duplicates that share the same conflicting ID.
        content: Content of this variant.
        source_location: Where this variant appears (file:line).
        heuristic_score: Ranking score based on heuristics (0.0-1.0).
        reasons: List of reasons for the score (e.g., "has_annotation", "longer_content").
    """

    id: str
    content: str
    source_location: str
    heuristic_score: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "source_location": self.source_location,
            "heuristic_score": self.heuristic_score,
            "reasons": self.reasons,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictVariant:
        """Deserialize from dictionary.

        Args:
            data: Dictionary with variant data. Must contain 'id' key.

        Returns:
            ConflictVariant instance.

        Raises:
            KeyError: If required keys are missing.
        """
        return cls(
            id=data["id"],
            content=data["content"],
            source_location=data["source_location"],
            heuristic_score=data["heuristic_score"],
            reasons=data.get("reasons", []),
        )


@dataclass
class ConflictBundle:
    """Bundle of conflicting variants for a single ID.

    Groups all variants of a duplicate ID together with resolution status
    and recommended variant selection.

    Attributes:
        conflicting_id: The original element ID that has duplicates (e.g., "REQ-001").
        variants: All variants found for this conflicting_id.
        recommended_variant: The id of the recommended variant
            (the one with the highest heuristic_score). This references the
            id field of a ConflictVariant.
        resolution_status: One of "pending", "auto_resolved", "manual_required".
    """

    conflicting_id: str
    variants: list[ConflictVariant] = field(default_factory=list)
    recommended_variant: str | None = None
    resolution_status: str = STATUS_PENDING

    def rank_variants(self) -> None:
        """Sort variants by heuristic_score descending and set recommended_variant.

        Sorting is deterministic: variants are sorted by heuristic_score descending,
        then by id ascending as a tie-breaker. This ensures the recommended variant
        is stable across runs even when heuristic scores tie.
        """
        if not self.variants:
            self.recommended_variant = None
            return

        # Sort by heuristic_score descending, then by id ascending for deterministic tie-breaking
        self.variants.sort(key=lambda v: (-v.heuristic_score, v.id))
        self.recommended_variant = self.variants[0].id

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "conflicting_id": self.conflicting_id,
            "variants": [v.to_dict() for v in self.variants],
            "recommended_variant": self.recommended_variant,
            "resolution_status": self.resolution_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictBundle:
        """Deserialize from dictionary.

        Args:
            data: Dictionary with bundle data. Must contain 'conflicting_id' key.
                May contain 'recommended_variant' for the recommended variant.

        Returns:
            ConflictBundle instance.

        Raises:
            KeyError: If required keys are missing.
        """
        return cls(
            conflicting_id=data["conflicting_id"],
            variants=[ConflictVariant.from_dict(v) for v in data.get("variants", [])],
            recommended_variant=data.get("recommended_variant"),
            resolution_status=data.get("resolution_status", STATUS_PENDING),
        )


# =============================================================================
# Canonical gap domain types
# =============================================================================


# =============================================================================
# Remainder Queue Structure
# =============================================================================


@dataclass
class RemainderQueue:
    """Queue of remainder units with stagnation detection.

    Tracks units that haven't been processed yet and detects when
    processing has stalled (no progress across iterations).

    Stagnation is detected by comparing the content hash of items (as a sorted
    frozenset), not just the length. This ensures that changes in queue
    composition are detected even when the length stays the same.

    Attributes:
        items: List of remainder unit IDs.
        stagnation_count: Number of iterations without progress.
        stagnation_threshold: Max iterations before flagging as stagnant.
        last_content_hash: Hash of previous iteration's items (for content comparison).
        last_size: Length of previous iteration's items (for metrics).
        is_stagnant: Whether queue is stagnant.
    """

    items: list[str] = field(default_factory=list)
    stagnation_count: int = 0
    stagnation_threshold: int = 3
    last_content_hash: str = ""
    last_size: int = 0
    is_stagnant: bool = False

    @staticmethod
    def _compute_content_hash(items: list[str]) -> str:
        """Compute a deterministic hash of the items set."""
        if not items:
            return ""
        # Use sorted frozenset for order-independent comparison
        canonical = "|".join(sorted(set(items)))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def update(self, current_items: list[str]) -> None:
        """Update queue with current items and check for stagnation.

        Stagnation is detected when the content hash (sorted set of items)
        remains unchanged across iterations, indicating no progress was made
        even if the list order changed.
        """
        current_hash = self._compute_content_hash(current_items)

        # Stagnation occurs when content is unchanged AND we had items before
        if current_hash == self.last_content_hash and self.last_content_hash:
            self.stagnation_count += 1
        else:
            self.stagnation_count = 0

        self.items = current_items
        self.last_content_hash = current_hash
        self.last_size = len(current_items)
        self.is_stagnant = self.stagnation_count >= self.stagnation_threshold

    def mark_progress(self) -> None:
        """Reset stagnation counter to indicate progress was made."""
        self.stagnation_count = 0
        self.is_stagnant = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "items": self.items,
            "stagnation_count": self.stagnation_count,
            "stagnation_threshold": self.stagnation_threshold,
            "last_content_hash": self.last_content_hash,
            "last_size": self.last_size,
            "is_stagnant": self.is_stagnant,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemainderQueue:
        """Deserialize from dictionary."""
        return cls(
            items=data.get("items", []),
            stagnation_count=data.get("stagnation_count", 0),
            stagnation_threshold=data.get("stagnation_threshold", 3),
            last_content_hash=data.get("last_content_hash", ""),
            last_size=data.get("last_size", 0),
            is_stagnant=data.get("is_stagnant", False),
        )


# =============================================================================
# Strategy Record Structure
# =============================================================================


@dataclass
class StrategyRecord:
    """Record of a strategy execution.

    Tracks strategy application history including input/output units,
    validation status, and strategy-specific metrics.

    Attributes:
        strategy_name: Name of the strategy applied.
        applied_at: ISO timestamp of application.
        input_unit_ids: Units processed by the strategy.
        output_unit_ids: Units produced by the strategy.
        validation_status: One of "pending", "passed", "failed".
        validation_errors: Validation error messages if failed.
        metrics: Strategy-specific metrics.
        notes: Additional notes about the execution.
    """

    strategy_name: str
    applied_at: str = field(default_factory=lambda: datetime.now().isoformat())
    input_unit_ids: list[str] = field(default_factory=list)
    output_unit_ids: list[str] = field(default_factory=list)
    validation_status: str = STATUS_PENDING
    validation_errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    def mark_validated(self, passed: bool, errors: list[str] | None = None) -> None:
        """Mark the strategy execution as validated with pass/fail status."""
        self.validation_status = STATUS_PASSED if passed else STATUS_FAILED
        if passed:
            # Clear stale errors when validation passes
            self.validation_errors = []
        else:
            # Set errors list (empty if None provided)
            self.validation_errors = errors if errors is not None else []

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "strategy_name": self.strategy_name,
            "applied_at": self.applied_at,
            "input_unit_ids": self.input_unit_ids,
            "output_unit_ids": self.output_unit_ids,
            "validation_status": self.validation_status,
            "validation_errors": self.validation_errors,
            "metrics": self.metrics,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyRecord:
        """Deserialize from dictionary."""
        return cls(
            strategy_name=data["strategy_name"],
            applied_at=data.get("applied_at", datetime.now().isoformat()),
            input_unit_ids=data.get("input_unit_ids", []),
            output_unit_ids=data.get("output_unit_ids", []),
            validation_status=data.get("validation_status", STATUS_PENDING),
            validation_errors=data.get("validation_errors", []),
            metrics=data.get("metrics", {}),
            notes=data.get("notes"),
        )
