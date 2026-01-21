"""Core data structures for spec_manager v2.0 state schema.

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

Type Naming (collision avoidance):
    This module defines v2.0 canonical types. To avoid import collisions:

    - GapEvidence (this module): v2.0 evidence with invariant_family, confidence
    - DetectorFinding (gaps.py): Raw detector output (simpler structure)

    - Gap (this module): v2.0 first-class gap with evidence-based ID
    - GapElement (gaps.py): Synthesized gap for gaps.md output

    - WorkflowEvidence (orchestrator.py): Evidence collected during workflow

    When importing, be explicit about which module you need:
        from spec_manager.core.data_structures import Gap, GapEvidence  # v2.0
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
    from spec_manager.core.gaps import Severity

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
from pathlib import Path
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
# Gap Evidence and Gap Structures (v2.0 Canonical Types)
# =============================================================================


@dataclass
class GapEvidence:
    """v2.0 evidence supporting a gap identification.

    This is the canonical v2.0 evidence type with invariant family classification
    and confidence scoring for evidence-based gap synthesis.

    Note: This is distinct from DetectorFinding in gaps.py which is simpler
    raw detector output. Use this type for v2.0 state schema operations.

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

    @staticmethod
    def _serialize_details(details: dict[str, Any]) -> dict[str, Any]:
        """Convert details dict to JSON-serializable form.

        Handles common non-JSON types (Path, datetime) by converting them to
        strings. Other non-JSON types raise ValueError to prevent silent data loss.

        Args:
            details: Dictionary of evidence details.

        Returns:
            JSON-serializable dictionary.

        Raises:
            ValueError: If details contains unsupported non-JSON types.
        """

        def make_serializable(obj: object) -> object:
            if obj is None or isinstance(obj, (bool, int, float, str)):
                return obj
            if isinstance(obj, (list, tuple)):
                return [make_serializable(item) for item in obj]
            if isinstance(obj, dict):
                return {str(k): make_serializable(v) for k, v in obj.items()}
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise ValueError(
                f"Unsupported type in details: {type(obj).__name__}. "
                f"Details must contain only JSON-serializable types, Path, or datetime. "
                f"Got: {obj!r}"
            )

        return {str(k): make_serializable(v) for k, v in details.items()}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary.

        Details are converted to JSON-serializable form (Path -> str, datetime -> ISO str).
        """
        return {
            "invariant_family": self.invariant_family,
            "description": self.description,
            "details": self._serialize_details(self.details),
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
    """v2.0 first-class gap element with evidence-based identification.

    This is the canonical v2.0 gap type. Gaps are synthesized from clustered
    GapEvidence and tracked as first-class elements with stable IDs computed
    from evidence signatures.

    Note: This is distinct from:
    - LegacyGap in gaps.py (deprecated wrapper with gap_type field)
    - GapElement in gaps.py (synthesized gap for gaps.md markdown output)

    Use this type for v2.0 state schema operations and persistent storage.

    Attributes:
        id: Stable evidence-based ID (e.g., "GAP-abc12345").
        severity: Severity level from gaps.py.
        evidence: All GapEvidence supporting this gap.
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


# =============================================================================
# Evidence Signature Computation
# =============================================================================


def _safe_serialize_details(details: dict[str, Any]) -> str:
    """Safely serialize details dict to a deterministic JSON string.

    Handles common non-JSON-serializable types with deterministic conversions
    (Path, datetime) and raises ValueError for unsupported types so callers
    can sanitize details before hashing.

    Args:
        details: Dictionary of evidence details.

    Returns:
        Deterministic JSON string representation.

    Raises:
        ValueError: If details contains unsupported types that cannot be
            deterministically serialized.
    """
    if not details:
        return "{}"

    def make_serializable(obj: object) -> object:
        """Convert non-serializable objects to serializable form."""
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        if isinstance(obj, (list, tuple)):
            return [make_serializable(item) for item in obj]
        if isinstance(obj, dict):
            return {str(k): make_serializable(v) for k, v in sorted(obj.items())}
        # Handle common types with deterministic conversions
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        # Reject unsupported types to prevent non-deterministic signatures
        raise ValueError(
            f"Unsupported type in evidence details: {type(obj).__name__}. "
            f"Details must contain only JSON-serializable types, Path, or datetime. "
            f"Got: {obj!r}"
        )

    serializable_details = make_serializable(details)
    return json.dumps(serializable_details, sort_keys=True)


def compute_evidence_signature(evidence_list: list[GapEvidence]) -> str:
    """Compute a stable signature from a list of gap evidence.

    The signature is deterministic - the same evidence will always produce
    the same signature, enabling stable gap IDs across runs. All evidence
    fields are included to prevent collisions.

    Signature Contract:
        - Evidence is sorted by ALL fields (invariant_family, description,
          details_canonical, location, detector, confidence) to ensure full
          determinism even when primary fields match.
        - Confidence values are rounded to 2 decimal places. This means
          0.951 and 0.954 will both round to 0.95 and produce the same
          signature contribution. This is intentional to handle floating
          point precision variations across runs.
        - Empty evidence lists are not allowed since gaps must have supporting
          evidence. Use the evidence to identify the gap.
        - Non-JSON-serializable values in details (except Path and datetime)
          will raise ValueError to prevent non-deterministic signatures.

    Args:
        evidence_list: List of GapEvidence objects to compute signature from.
            Must not be empty.

    Returns:
        First 8 characters of the SHA-256 hex digest (e.g., "abc12345").

    Raises:
        ValueError: If evidence_list is empty. Gaps must have evidence.

    Example:
        >>> evidence = [GapEvidence(invariant_family="format", description="test", details={})]
        >>> sig = compute_evidence_signature(evidence)
        >>> gap_id = f"GAP-{sig}"  # e.g., "GAP-abc12345"
    """
    if not evidence_list:
        raise ValueError(
            "Cannot compute signature for empty evidence list. "
            "Gaps must have at least one piece of supporting evidence."
        )

    def _make_sort_key(e: GapEvidence) -> tuple[str, str, str, str, str, float]:
        """Create a complete sort key including all fields for full determinism."""
        location = e.location if e.location is not None else ""
        detector = e.detector if e.detector is not None else ""
        # Round confidence to 2 decimals for stability across floating point variations
        confidence = round(e.confidence, 2)
        details_canonical = _safe_serialize_details(e.details)
        return (
            e.invariant_family,
            e.description,
            details_canonical,
            location,
            detector,
            confidence,
        )

    # Sort evidence by all fields for fully deterministic ordering
    sorted_evidence = sorted(evidence_list, key=_make_sort_key)

    # Create canonical representation including all fields
    canonical_parts = []
    for e in sorted_evidence:
        # Normalize None values to empty string for consistency
        location = e.location if e.location is not None else ""
        detector = e.detector if e.detector is not None else ""
        # Round confidence to 2 decimal places (documented in signature contract)
        confidence = round(e.confidence, 2)
        # Use safe serialization for details to handle non-JSON types
        details_str = _safe_serialize_details(e.details)

        # Include all fields in canonical representation
        canonical_parts.append(
            f"{e.invariant_family}:{e.description}:{details_str}:{location}:{detector}:{confidence}"
        )

    canonical_str = "|".join(canonical_parts)

    # Compute SHA-256 hash
    hash_digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    # Return first 8 characters
    return hash_digest[:8]
