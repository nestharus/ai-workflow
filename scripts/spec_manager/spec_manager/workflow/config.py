"""Workflow configuration and state classes.

WorkflowConfig: Configuration for the workflow with compliance gate settings.
WorkflowState: Current state of the workflow including phase tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from spec_manager.core.provenance import MembershipEvidence


class WorkflowPhase(Enum):
    """Phases in the ingest workflow."""

    INIT = "init"
    CLEANING = "cleaning"  # With compliance gate
    COMPOSITING = "compositing"  # Merge + remainder partition
    DISCOVERY = "discovery"  # Only after compliance gate passes
    REVIEW = "review"  # Concrete resolution actions
    SYNC = "sync"  # plan.md ↔ libraries synchronization
    FINALIZE = "finalize"  # Stamps removed, relations written
    COMPLETE = "complete"


class UnitType(Enum):
    """Types of tracked units."""

    ALGORITHM = "algorithm"
    CLAIM = "claim"
    INVARIANT = "invariant"
    GOAL = "goal"
    DATA_STRUCTURE = "data_structure"
    PROOF = "proof"
    LEAN = "lean"
    PROSE = "prose"
    UNKNOWN = "unknown"


class UnitStatus(Enum):
    """Status of a tracked unit."""

    ACTIVE = "active"
    PENDING = "pending"
    NON_AUTHORITATIVE = "non_authoritative"
    ARCHIVED = "archived"
    DROPPED = "dropped"


@dataclass
class TrackedUnit:
    """A unit of content tracked through the workflow.

    Units are the atomic elements being processed - algorithms, claims,
    data structures, etc. Each unit has provenance tracking.
    """

    id: str
    content: str
    unit_type: UnitType
    source: str
    introduced_by: str
    modified_by: list[str] = field(default_factory=list)
    declarations: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    status: UnitStatus = UnitStatus.ACTIVE

    # Atom-based membership tracking
    source_atom_ids: list[str] = field(default_factory=list)
    membership_evidence: dict[str, MembershipEvidence] = field(default_factory=dict)

    # Explicit lineage tracking
    parents: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)

    # Library assignment
    primary_library: str | None = None
    relation_libraries: list[str] = field(default_factory=list)

    def add_membership(
        self, target_id: str, rationale: str, confidence: float = 1.0, method: str = "exact"
    ) -> None:
        """Record a membership mapping with evidence."""
        self.membership_evidence[target_id] = MembershipEvidence(
            rationale=rationale, confidence=confidence, method=method
        )

    def add_parent(self, parent_id: str) -> None:
        """Record a lineage parent."""
        if parent_id not in self.parents:
            self.parents.append(parent_id)

    def add_child(self, child_id: str) -> None:
        """Record a lineage child."""
        if child_id not in self.children:
            self.children.append(child_id)


@dataclass
class WorkflowConfig:
    """Configuration for the workflow."""

    max_cleaning_passes: int = 5
    max_discovery_iterations: int = 10
    save_intermediates: bool = True
    apply_strategies: bool = True
    verbose: bool = False

    # Compliance gate configuration
    compliance_threshold: float = 0.90  # 90% format compliance required
    compliance_gate_mode: str = "block"  # "block" (default) or "warn"
    max_remainder_ratio: float = 0.05  # Max 5% atoms in remainder queue
    max_unit_content_length: int = 50_000  # Max chars per unit before truncation guard
    require_no_critical_errors: bool = True  # Block on any critical error


@dataclass
class WorkflowState:
    """Current state of the workflow."""

    phase: WorkflowPhase = WorkflowPhase.INIT
    cleaning_pass: int = 0
    discovery_iteration: int = 0

    # Tracked content
    units: list[TrackedUnit] = field(default_factory=list)
    remainders: list[TrackedUnit] = field(default_factory=list)

    # Discovery state
    candidate_libraries: list[str] = field(default_factory=list)
    library_shapes: dict[str, Any] = field(default_factory=dict)
    final_labels: dict[str, Any] = field(default_factory=dict)

    # Compliance state
    compliance_passed: bool = False
    compliance_score: float = 0.0
    compliance_details: dict[str, Any] = field(default_factory=dict)

    # Review state
    review_actions: list[dict] = field(default_factory=list)
    non_authoritative_units: list[str] = field(default_factory=list)

    # Sync state
    sync_drift: list[dict] = field(default_factory=list)
    plan_only_remainder: list[dict] = field(default_factory=list)

    # Metrics
    started_at: datetime = field(default_factory=datetime.now)
    errors: list[str] = field(default_factory=list)

    # Projection path tracking
    current_projection_path: Any = None  # Path to the current intermediate projection


@dataclass
class UnitLabels:
    """Library assignment labels for a unit."""

    primary: str | None = None
    relations: list[str] = field(default_factory=list)
    confidence: float = 0.0
