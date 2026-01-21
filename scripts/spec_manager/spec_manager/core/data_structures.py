"""
Core data structures for spec_manager v2.0 state schema.

This module provides the foundational data structures for evidence-based gap tracking,
conflict resolution, compliance metrics, and strategy execution records.

Key Concepts:
    - Evidence-based gaps: Gaps are identified through collected evidence, with stable
      IDs computed from evidence signatures for reproducibility across runs.
    - Conflict resolution: Duplicate elements are bundled with heuristic scoring to
      recommend resolution strategies.
    - Compliance metrics: Quality gates based on format compliance, annotation coverage,
      and ID normalization thresholds.
    - Strategy records: Execution history tracking for strategy applications with
      validation status and metrics.

Related Modules:
    - gaps.py: Contains Severity enum and legacy Gap/GapEvidence structures
    - state.py: State management using these data structures
    - provenance.py: Unit tracking and provenance chains

Usage:
    from spec_manager.core.data_structures import (
        ComplianceMetrics,
        ConflictBundle,
        Gap,
        GapEvidence,
        RemainderQueue,
        StrategyRecord,
        compute_evidence_signature,
    )

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
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from spec_manager.core.gaps import Severity


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
    """
    Quality metrics for specification compliance.

    Tracks format compliance, annotation coverage, and ID normalization
    percentages. Provides a quality gate check against a configurable threshold.

    Attributes:
        format_compliance: Percentage of IDs matching canonical patterns (0.0-1.0).
        annotation_coverage: Percentage of elements with proper annotations (0.0-1.0).
        id_normalization: Percentage of IDs properly normalized (0.0-1.0).
        gate_threshold: Minimum threshold for passing quality gate (default 0.95).
    """

    format_compliance: float
    annotation_coverage: float
    id_normalization: float
    gate_threshold: float = 0.95

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
    """
    A single variant of a conflicting element.

    When multiple elements share the same ID, each occurrence is tracked
    as a variant with its content, location, and heuristic scoring.

    Attributes:
        variant_id: Unique identifier for this variant (distinguishes among duplicates).
        id: The conflicting ID (shared by all variants in a bundle).
        content: Content of this variant.
        source_location: Where this variant appears (file:line).
        heuristic_score: Ranking score based on heuristics (0.0-1.0).
        reasons: List of reasons for the score (e.g., "has_annotation", "longer_content").
    """

    variant_id: str
    id: str
    content: str
    source_location: str
    heuristic_score: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "variant_id": self.variant_id,
            "id": self.id,
            "content": self.content,
            "source_location": self.source_location,
            "heuristic_score": self.heuristic_score,
            "reasons": self.reasons,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictVariant:
        """Deserialize from dictionary."""
        return cls(
            variant_id=data["variant_id"],
            id=data["id"],
            content=data["content"],
            source_location=data["source_location"],
            heuristic_score=data["heuristic_score"],
            reasons=data.get("reasons", []),
        )


@dataclass
class ConflictBundle:
    """
    Bundle of conflicting variants for a single ID.

    Groups all variants of a duplicate ID together with resolution status
    and recommended variant selection.

    Attributes:
        conflicting_id: The ID that has duplicates.
        variants: All variants found.
        recommended_variant: Unique variant_id of recommended variant (highest score).
        resolution_status: One of "pending", "auto_resolved", "manual_required".
    """

    conflicting_id: str
    variants: list[ConflictVariant] = field(default_factory=list)
    recommended_variant: str | None = None
    resolution_status: str = STATUS_PENDING

    def rank_variants(self) -> None:
        """Sort variants by heuristic_score descending and set recommended_variant."""
        if not self.variants:
            self.recommended_variant = None
            return

        self.variants.sort(key=lambda v: v.heuristic_score, reverse=True)
        self.recommended_variant = self.variants[0].variant_id

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
        """Deserialize from dictionary."""
        return cls(
            conflicting_id=data["conflicting_id"],
            variants=[ConflictVariant.from_dict(v) for v in data.get("variants", [])],
            recommended_variant=data.get("recommended_variant"),
            resolution_status=data.get("resolution_status", STATUS_PENDING),
        )


# =============================================================================
# Gap Evidence and Gap Structures
# =============================================================================


@dataclass
class GapEvidence:
    """
    Evidence supporting a gap identification.

    Extends the concept from gaps.py with invariant family classification
    and confidence scoring for evidence-based gap synthesis.

    Attributes:
        invariant_family: Which invariant family this evidence relates to
            (e.g., "format", "coverage", "sequence").
        description: Human-readable description of the evidence.
        details: Additional structured details.
        confidence: Confidence level (0.0-1.0).
        location: Where found (file:line), optional.
        detector: Which detector found this, optional.
    """

    invariant_family: str
    description: str
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    location: str | None = None
    detector: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "invariant_family": self.invariant_family,
            "description": self.description,
            "details": self.details,
            "confidence": self.confidence,
            "location": self.location,
            "detector": self.detector,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GapEvidence:
        """Deserialize from dictionary."""
        return cls(
            invariant_family=data["invariant_family"],
            description=data["description"],
            details=data.get("details", {}),
            confidence=data.get("confidence", 1.0),
            location=data.get("location"),
            detector=data.get("detector"),
        )


@dataclass
class Gap:
    """
    First-class gap element with evidence-based identification.

    Gaps are synthesized from clustered evidence and tracked as first-class
    elements with stable IDs computed from evidence signatures.

    Attributes:
        id: Stable evidence-based ID (e.g., "GAP-abc12345").
        severity: Severity level from gaps.py.
        evidence: All evidence supporting this gap.
        status: One of "open", "resolved", "bypassed", "deferred".
        affected_elements: Element IDs affected by this gap.
        created_at: ISO timestamp of gap creation.
        resolved_at: ISO timestamp of resolution, if resolved.
        resolution_notes: Notes explaining the resolution.
    """

    id: str
    severity: Severity
    evidence: list[GapEvidence] = field(default_factory=list)
    status: str = STATUS_OPEN
    affected_elements: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: str | None = None
    resolution_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "severity": self.severity.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "status": self.status,
            "affected_elements": self.affected_elements,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution_notes": self.resolution_notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Gap:
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            severity=Severity(data["severity"]),
            evidence=[GapEvidence.from_dict(e) for e in data.get("evidence", [])],
            status=data.get("status", STATUS_OPEN),
            affected_elements=data.get("affected_elements", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            resolved_at=data.get("resolved_at"),
            resolution_notes=data.get("resolution_notes"),
        )


# =============================================================================
# Remainder Queue Structure
# =============================================================================


@dataclass
class RemainderQueue:
    """
    Queue of remainder units with stagnation detection.

    Tracks units that haven't been processed yet and detects when
    processing has stalled (no progress across iterations).

    Attributes:
        items: List of remainder unit IDs.
        stagnation_count: Number of iterations without progress.
        stagnation_threshold: Max iterations before flagging as stagnant.
        last_size: Size from previous iteration.
        is_stagnant: Whether queue is stagnant.
    """

    items: list[str] = field(default_factory=list)
    stagnation_count: int = 0
    stagnation_threshold: int = 3
    last_size: int = 0
    is_stagnant: bool = False

    def update(self, current_items: list[str]) -> None:
        """Update queue with current items and check for stagnation."""
        current_size = len(current_items)

        if current_size >= self.last_size and self.last_size > 0:
            self.stagnation_count += 1
        else:
            self.stagnation_count = 0

        self.items = current_items
        self.last_size = current_size
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
            last_size=data.get("last_size", 0),
            is_stagnant=data.get("is_stagnant", False),
        )


# =============================================================================
# Strategy Record Structure
# =============================================================================


@dataclass
class StrategyRecord:
    """
    Record of a strategy execution.

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


# =============================================================================
# Evidence Signature Computation
# =============================================================================


def compute_evidence_signature(evidence_list: list[GapEvidence]) -> str:
    """
    Compute a stable signature from a list of gap evidence.

    The signature is deterministic - the same evidence will always produce
    the same signature, enabling stable gap IDs across runs. All evidence
    fields are included to prevent collisions.

    Args:
        evidence_list: List of GapEvidence objects to compute signature from.

    Returns:
        First 8 characters of the SHA-256 hex digest (e.g., "abc12345").

    Example:
        >>> evidence = [GapEvidence(invariant_family="format", description="test", details={})]
        >>> sig = compute_evidence_signature(evidence)
        >>> gap_id = f"GAP-{sig}"  # e.g., "GAP-abc12345"
    """
    if not evidence_list:
        return "00000000"

    # Sort evidence for deterministic ordering
    sorted_evidence = sorted(
        evidence_list,
        key=lambda e: (e.invariant_family, e.description),
    )

    # Create canonical representation including all fields
    canonical_parts = []
    for e in sorted_evidence:
        # Normalize None values to empty string for consistency
        location = e.location if e.location is not None else ""
        detector = e.detector if e.detector is not None else ""
        # Round confidence to 2 decimal places for stability
        confidence = round(e.confidence, 2)

        # Include all fields in canonical representation
        canonical_parts.append(
            f"{e.invariant_family}:{e.description}:{json.dumps(e.details, sort_keys=True)}"
            f":{location}:{detector}:{confidence}"
        )

    canonical_str = "|".join(canonical_parts)

    # Compute SHA-256 hash
    hash_digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    # Return first 8 characters
    return hash_digest[:8]
