"""File-based constraint persistence.

Extracted from orchestration.under_spec.manager to consolidate all
constraint types under planner.constraints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml

if TYPE_CHECKING:
    from spec_manager.orchestration.under_spec.manager import UnderSpecEvent

logger = logging.getLogger(__name__)


@dataclass
class Constraint:
    """A resolved constraint that answers an under-spec question.

    Attributes:
        constraint_id: Unique identifier (matches event_id it resolves).
        question: The original question.
        answer: The constraint answer text.
        source: How the constraint was obtained.
        confidence: 0.0-1.0 (only relevant for auto-resolved).
        validated: Whether the constraint passed validation.
    """

    constraint_id: str = ""
    question: str = ""
    answer: str = ""
    source: Literal[
        "user",
        "research",
        "steering",
        "existing",
        "planner",
        "research_coordinator",
    ] = "existing"
    confidence: float = 1.0
    validated: bool = True
    dimension: str = "software"
    authority_required: str = "planner_ok"
    scope: str = ""
    applies_to_layers: list[str] = field(default_factory=list)
    status: str = "ACTIVE"
    supersedes: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Constraint:
        return cls(
            constraint_id=d.get("constraint_id", ""),
            question=d.get("question", ""),
            answer=d.get("answer", ""),
            source=d.get("source", "existing"),
            confidence=d.get("confidence", 1.0),
            validated=d.get("validated", True),
            dimension=d.get("dimension", "software"),
            authority_required=d.get("authority_required", "planner_ok"),
            scope=d.get("scope", ""),
            applies_to_layers=d.get("applies_to_layers", []),
            status=d.get("status", "ACTIVE"),
            supersedes=d.get("supersedes", []),
            trace=d.get("trace", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_id": self.constraint_id,
            "question": self.question,
            "answer": self.answer,
            "source": self.source,
            "confidence": self.confidence,
            "validated": self.validated,
            "dimension": self.dimension,
            "authority_required": self.authority_required,
            "scope": self.scope,
            "applies_to_layers": self.applies_to_layers,
            "status": self.status,
            "supersedes": self.supersedes,
            "trace": self.trace,
        }


class ConstraintsStore:
    """File-based constraint persistence.

    Constraints live in ``<workspace>/analysis/constraints/<slice_id>.yaml``.
    """

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root / "analysis" / "constraints"

    def load(self, slice_id: str) -> list[Constraint]:
        """Load all constraints for a slice.

        Accepts both list format ``[{...}, ...]`` and dict format
        ``{"constraints": [{...}, ...]}``.
        """
        path = self._root / f"{slice_id}.yaml"
        if not path.exists():
            return []
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if raw is None:
                return []
            data = raw if isinstance(raw, list) else raw.get("constraints", [])
            return [Constraint.from_dict(c) for c in data]
        except (yaml.YAMLError, KeyError, AttributeError, TypeError) as exc:
            logger.warning("Failed to load constraints for %s: %s", slice_id, exc)
            return []

    def load_merged(self, slice_id: str) -> list[Constraint]:
        """Load constraints from both ``__system__`` and *slice_id*, merged.

        System-level constraints are loaded first, then slice-specific
        constraints are appended (duplicates by constraint_id are skipped).
        """
        system = self.load("__system__")
        if slice_id == "__system__":
            return system
        specific = self.load(slice_id)
        seen_ids = {c.constraint_id for c in system}
        merged = list(system)
        for c in specific:
            if c.constraint_id not in seen_ids:
                merged.append(c)
                seen_ids.add(c.constraint_id)
        return merged

    def save(self, slice_id: str, constraints: list[Constraint]) -> Path:
        """Save constraints for a slice (merges with existing)."""
        existing = self.load(slice_id)
        existing_ids = {c.constraint_id for c in existing}

        merged = list(existing)
        for c in constraints:
            if c.constraint_id not in existing_ids:
                merged.append(c)
                existing_ids.add(c.constraint_id)

        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{slice_id}.yaml"
        path.write_text(
            yaml.safe_dump([c.to_dict() for c in merged], sort_keys=False),
            encoding="utf-8",
        )
        return path

    def find_covering(
        self, slice_id: str, events: list[UnderSpecEvent]
    ) -> tuple[list[UnderSpecEvent], list[UnderSpecEvent]]:
        """Partition events into covered (have constraint) and uncovered.

        Returns:
            (covered, uncovered) --- events with matching constraints vs not.
        """
        constraints = self.load(slice_id)
        constraint_ids = {c.constraint_id for c in constraints}

        covered = []
        uncovered = []
        for event in events:
            if event.event_id in constraint_ids:
                covered.append(event)
            else:
                uncovered.append(event)

        return covered, uncovered
