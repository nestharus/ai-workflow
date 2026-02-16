"""File-based constraint persistence.

Extracted from orchestration.under_spec.manager to consolidate all
constraint types under planner.constraints.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Protocol, TypeVar

from spec_manager.planner.constraints.types import ConstraintFact

logger = logging.getLogger(__name__)


Constraint = ConstraintFact


class ConstraintLoadError(RuntimeError):
    """Raised when constraint persistence cannot be loaded as authoritative data."""


class HasEventId(Protocol):
    """Boundary contract for coverage checks."""

    event_id: str


EventT = TypeVar("EventT", bound=HasEventId)


class ConstraintsStore:
    """File-based constraint persistence.

    Constraints live in ``<workspace>/analysis/constraints/<slice_id>.json``.
    """

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root / "analysis" / "constraints"

    def load(self, slice_id: str) -> list[Constraint]:
        """Load all constraints for a slice.

        Accepts both list format ``[{...}, ...]`` and dict format
        ``{"constraints": [{...}, ...]}``.
        """
        path = self._root / f"{slice_id}.json"
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw is None:
                raise ConstraintLoadError(f"Constraints file {path} is null payload")
            if isinstance(raw, list):
                data = raw
            elif isinstance(raw, dict):
                data = raw.get("constraints", [])
            else:
                raise ConstraintLoadError(
                    f"Constraints file {path} is neither list nor mapping payload",
                )
            return [Constraint.from_dict(c) for c in data]
        except (json.JSONDecodeError, OSError, KeyError, AttributeError, TypeError) as exc:
            logger.warning("Failed to load constraints for %s: %s", slice_id, exc)
            raise ConstraintLoadError(f"Failed to load constraints for slice '{slice_id}'") from exc

    def load_merged(self, slice_id: str) -> list[Constraint]:
        """Load constraints from both ``__system__`` and *slice_id*, merged.

        System-level constraints are loaded first, then slice-specific
        constraints override by ``constraint_id``. For duplicate IDs within a
        source, the latest record wins.
        """
        system = self.load("__system__")
        if slice_id == "__system__":
            return self._collapse_latest(system)
        specific = self.load(slice_id)

        merged_by_id = self._latest_by_id(self._collapse_latest(system))
        for constraint_id, constraint in self._latest_by_id(
            self._collapse_latest(specific)
        ).items():
            merged_by_id[constraint_id] = constraint

        merged = list(merged_by_id.values())
        merged.extend(self._constraints_without_id(system))
        merged.extend(self._constraints_without_id(specific))
        return merged

    def snapshot_hash(self, slice_id: str) -> str:
        """Return a deterministic hash of merged ACTIVE constraints for *slice_id*."""
        merged = self.load_merged(slice_id)
        active_payloads: list[dict[str, Any]] = []
        for constraint in merged:
            status = str(constraint.status or "ACTIVE").strip().upper()
            if status != "ACTIVE":
                continue
            payload = constraint.to_dict()
            payload["constraint_id"] = str(payload.get("constraint_id", "")).strip()
            payload["question"] = str(payload.get("question", "")).strip()
            payload["answer"] = str(payload.get("answer", "")).strip()
            payload["applies_to_layers"] = sorted(
                str(item).strip().upper()
                for item in payload.get("applies_to_layers", [])
                if str(item).strip()
            )
            payload["supersedes"] = sorted(
                str(item).strip() for item in payload.get("supersedes", []) if str(item).strip()
            )
            payload["trace"] = [
                str(item).strip() for item in payload.get("trace", []) if str(item).strip()
            ]
            active_payloads.append(payload)

        active_payloads.sort(
            key=lambda item: (
                str(item.get("constraint_id", "")),
                str(item.get("question", "")),
                str(item.get("answer", "")),
            )
        )
        canonical = json.dumps(
            active_payloads,
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def save(self, slice_id: str, constraints: list[Constraint]) -> Path:
        """Save constraints for a slice (append-only, supersession-aware)."""
        merged = list(self.load(slice_id))
        latest_index_by_id = {
            c.constraint_id: idx for idx, c in enumerate(merged) if str(c.constraint_id).strip()
        }

        for incoming in constraints:
            for superseded_id in (str(item).strip() for item in incoming.supersedes):
                if not superseded_id:
                    continue
                latest_index = latest_index_by_id.get(superseded_id)
                if latest_index is None:
                    continue
                prior = merged[latest_index]
                if prior.status == "SUPERSEDED":
                    continue
                prior.status = "SUPERSEDED"
                superseded_by = str(incoming.constraint_id).strip()
                if superseded_by:
                    marker = f"superseded_by={superseded_by}"
                    if marker not in prior.trace:
                        prior.trace.append(marker)

            if self._contains_constraint(merged, incoming):
                continue

            merged.append(incoming)
            incoming_id = str(incoming.constraint_id).strip()
            if incoming_id:
                latest_index_by_id[incoming_id] = len(merged) - 1

        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{slice_id}.json"
        path.write_text(
            json.dumps([c.to_dict() for c in merged], indent=2),
            encoding="utf-8",
        )
        return path

    def find_covering(
        self,
        slice_id: str,
        events: list[EventT],
    ) -> tuple[list[EventT], list[EventT]]:
        """Partition events into covered (have constraint) and uncovered.

        Returns:
            (covered, uncovered) --- events with matching constraints vs not.
        """
        constraints = self._collapse_latest(self.load(slice_id))
        constraint_ids = {
            c.constraint_id
            for c in constraints
            if str(c.constraint_id).strip() and str(c.status).strip().upper() == "ACTIVE"
        }

        covered: list[EventT] = []
        uncovered: list[EventT] = []
        for event in events:
            event_id = str(getattr(event, "event_id", "")).strip()
            if not event_id:
                raise ValueError("Event is missing required event_id for coverage matching")
            if event_id in constraint_ids:
                covered.append(event)
            else:
                uncovered.append(event)

        return covered, uncovered

    @staticmethod
    def _contains_constraint(existing: list[Constraint], candidate: Constraint) -> bool:
        payload = candidate.to_dict()
        return any(current.to_dict() == payload for current in existing)

    @classmethod
    def _collapse_latest(cls, constraints: list[Constraint]) -> list[Constraint]:
        """Collapse duplicate constraint IDs so the latest record per ID wins."""
        by_id = cls._latest_by_id(constraints)
        collapsed = list(by_id.values())
        collapsed.extend(cls._constraints_without_id(constraints))
        return collapsed

    @staticmethod
    def _latest_by_id(constraints: list[Constraint]) -> dict[str, Constraint]:
        by_id: dict[str, Constraint] = {}
        for constraint in constraints:
            constraint_id = str(constraint.constraint_id).strip()
            if not constraint_id:
                continue
            by_id[constraint_id] = constraint
        return by_id

    @staticmethod
    def _constraints_without_id(constraints: list[Constraint]) -> list[Constraint]:
        return [c for c in constraints if not str(c.constraint_id).strip()]
