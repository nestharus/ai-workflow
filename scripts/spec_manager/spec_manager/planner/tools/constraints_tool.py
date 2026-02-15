"""Constraints tool adapter for the planner.

Wraps the persistent constraints store and under-spec lifecycle,
providing a unified interface for the planner.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ConstraintRecord:
    """A single constraint from the store."""

    constraint_id: str
    question: str
    answer: str
    source: str = ""  # user | research | steering | existing
    confidence: float = 0.0


@dataclass
class ConstraintsSnapshot:
    """Snapshot of all known constraints for a slice."""

    slice_id: str
    constraints: list[ConstraintRecord] = field(default_factory=list)

    def covers(self, question: str) -> ConstraintRecord | None:
        """Check if any existing constraint answers the question."""
        q_lower = question.lower().strip()
        for c in self.constraints:
            if c.question.lower().strip() == q_lower:
                return c
        return None


class ConstraintsTool:
    """Planner-facing constraints adapter.

    Reads/writes constraint files from the workspace analysis directory.
    Does NOT replace UnderSpecManager — it provides read access for
    the planner to check existing constraints before escalating.
    """

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace = workspace_root

    def load_constraints(self, slice_id: str) -> ConstraintsSnapshot:
        """Load existing constraints for a slice from disk."""
        if not self._workspace:
            return ConstraintsSnapshot(slice_id=slice_id)

        path = self._workspace / "analysis" / "constraints" / f"{slice_id}.json"
        if not path.exists():
            return ConstraintsSnapshot(slice_id=slice_id)

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data is None:
                return ConstraintsSnapshot(slice_id=slice_id)
            constraints_list = data if isinstance(data, list) else data.get("constraints", [])
            records = []
            for c in constraints_list:
                records.append(
                    ConstraintRecord(
                        constraint_id=c.get("constraint_id", ""),
                        question=c.get("question", ""),
                        answer=c.get("answer", ""),
                        source=c.get("source", ""),
                        confidence=c.get("confidence", 0.0),
                    )
                )
            return ConstraintsSnapshot(slice_id=slice_id, constraints=records)
        except Exception:
            logger.debug("Failed to load constraints for slice %s", slice_id)
            return ConstraintsSnapshot(slice_id=slice_id)

    def check_coverage(
        self, slice_id: str, questions: list[str]
    ) -> dict[str, ConstraintRecord | None]:
        """Check which questions are already answered by constraints.

        Returns a mapping of question -> ConstraintRecord (or None if not covered).
        """
        snapshot = self.load_constraints(slice_id)
        return {q: snapshot.covers(q) for q in questions}
