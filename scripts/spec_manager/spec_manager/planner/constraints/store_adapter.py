"""Adapter between planner constraint types and the orchestration ConstraintsStore.

Provides load/save operations that convert between the richer
:class:`ConstraintFact` / :class:`ConstraintHypothesis` types used by the
planner and the simpler :class:`Constraint` type used by the store.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from spec_manager.planner.constraints.store import (
    Constraint,
    ConstraintsStore,
)
from spec_manager.planner.constraints.types import (
    ConstraintFact,
    ConstraintHypothesis,
)

logger = logging.getLogger(__name__)


class ConstraintStoreAdapter:
    """Planner-facing adapter over the file-based :class:`ConstraintsStore`.

    Converts between the planner's richer :class:`ConstraintFact` type and the
    store's :class:`Constraint` type, and manages hypothesis persistence
    separately.

    Args:
        workspace_root: Path to the workspace directory.
        on_constraint_saved: Optional callback
            ``(slice_id, constraint_id, canonical_key) -> None``
            invoked for each constraint persisted via :meth:`save_facts`.
            Used to emit wake events when constraints arrive.
    """

    def __init__(
        self,
        workspace_root: Path,
        on_constraint_saved: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._workspace = workspace_root
        self._store = ConstraintsStore(workspace_root)
        self._on_constraint_saved = on_constraint_saved

    # ------------------------------------------------------------------
    # Facts
    # ------------------------------------------------------------------

    def load_merged(self, slice_id: str) -> list[ConstraintFact]:
        """Load constraints from ``__system__`` and *slice_id*, merged.

        System-level constraints act as defaults; slice-level constraints
        override them (by ``constraint_id``).

        Returns:
            Merged list of :class:`ConstraintFact` objects.
        """
        system = self._store.load("__system__")
        local = self._store.load(slice_id)

        by_id: dict[str, ConstraintFact] = {}
        for c in system:
            by_id[c.constraint_id] = self._constraint_to_fact(c)
        for c in local:
            by_id[c.constraint_id] = self._constraint_to_fact(c)

        return list(by_id.values())

    def save_facts(self, slice_id: str, facts: list[ConstraintFact]) -> Path:
        """Persist :class:`ConstraintFact` objects via the underlying store.

        Converts each fact to a :class:`Constraint` before saving.
        Invokes the ``on_constraint_saved`` callback for each fact so that
        coordination infrastructure (e.g. WakeQueue) can react.

        Returns:
            Path to the saved constraints file.
        """
        constraints = [self._fact_to_constraint(f) for f in facts]
        path = self._store.save(slice_id, constraints)

        if self._on_constraint_saved is not None:
            for f in facts:
                if f.constraint_id:
                    # Extract canonical_key from trace entries like "canonical_key=..."
                    canonical_key = ""
                    for t in f.trace:
                        if t.startswith("canonical_key="):
                            canonical_key = t.split("=", 1)[1]
                            break
                    try:
                        self._on_constraint_saved(slice_id, f.constraint_id, canonical_key)
                    except Exception:
                        logger.warning(
                            "on_constraint_saved callback failed for %s/%s",
                            slice_id,
                            f.constraint_id,
                            exc_info=True,
                        )

        # Planner update signals (constraint_saved) are emitted via the
        # on_constraint_saved callback above.  The Planner wires this callback
        # to write to .pdd_runs/<run_id>/coordination/planner_updates.jsonl
        # when constructed with the appropriate run context.
        logger.debug(
            "save_facts: %d facts persisted for slice %s; "
            "planner update signals delegated to on_constraint_saved callback",
            len(facts),
            slice_id,
        )

        return path

    # ------------------------------------------------------------------
    # Hypotheses
    # ------------------------------------------------------------------

    def save_hypotheses(self, slice_id: str, hypotheses: list[ConstraintHypothesis]) -> Path:
        """Persist hypotheses to a separate JSON file.

        Hypotheses live in ``analysis/constraints_hypotheses/<slice_id>.json``.

        Returns:
            Path to the saved hypotheses file.
        """
        out_dir = self._workspace / "analysis" / "constraints_hypotheses"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{slice_id}.json"

        data = [h.to_dict() for h in hypotheses]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load_hypotheses(self, slice_id: str) -> list[ConstraintHypothesis]:
        """Load hypotheses for a slice.

        Returns:
            List of :class:`ConstraintHypothesis` objects (empty if not found).
        """
        path = self._workspace / "analysis" / "constraints_hypotheses" / f"{slice_id}.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [ConstraintHypothesis.from_dict(h) for h in data]
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to load hypotheses for %s: %s", slice_id, exc)
            return []

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _constraint_to_fact(c: Constraint) -> ConstraintFact:
        """Convert a store :class:`Constraint` to a :class:`ConstraintFact`."""
        return ConstraintFact(
            constraint_id=c.constraint_id,
            question=c.question,
            answer=c.answer,
            source=c.source,
            confidence=c.confidence,
            validated=c.validated,
            dimension=c.dimension,
            authority_required=c.authority_required,
            scope=c.scope,
            applies_to_layers=list(c.applies_to_layers),
            status=c.status,
            supersedes=list(c.supersedes),
            trace=list(c.trace),
        )

    @staticmethod
    def _fact_to_constraint(f: ConstraintFact) -> Constraint:
        """Convert a :class:`ConstraintFact` to a store :class:`Constraint`."""
        return Constraint(
            constraint_id=f.constraint_id,
            question=f.question,
            answer=f.answer,
            source=f.source,
            confidence=f.confidence,
            validated=f.validated,
            dimension=f.dimension,
            authority_required=f.authority_required,
            scope=f.scope,
            applies_to_layers=list(f.applies_to_layers),
            status=f.status,
            supersedes=list(f.supersedes),
            trace=list(f.trace),
        )
