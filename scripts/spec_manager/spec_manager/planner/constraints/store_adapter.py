"""Adapter between planner constraint types and the orchestration ConstraintsStore.

Provides load/save operations that convert between the richer
:class:`ConstraintFact` / :class:`ConstraintHypothesis` types used by the
planner and the simpler :class:`Constraint` type used by the store.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextvars import ContextVar, Token
from datetime import UTC, datetime
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
            invoked for each constraint persisted via :meth:`save_facts`
            after the structural planner update event is written.
    """

    def __init__(
        self,
        workspace_root: Path,
        on_constraint_saved: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._workspace = workspace_root
        self._store = ConstraintsStore(workspace_root)
        self._on_constraint_saved = on_constraint_saved

    # Planner update context shared across adapter instances created during a
    # single planner.plan() call (including strategy-owned adapters).
    _planner_update_context: ContextVar[dict[str, str]] = ContextVar(
        "constraint_store_adapter_planner_update_context",
    )

    @classmethod
    def push_planner_update_context(
        cls,
        *,
        run_id: str,
        layer: str = "",
        capability: str = "",
    ) -> Token[dict[str, str]]:
        return cls._planner_update_context.set(
            {
                "run_id": str(run_id or "").strip(),
                "layer": str(layer or "").strip(),
                "capability": str(capability or "").strip(),
            }
        )

    @classmethod
    def pop_planner_update_context(cls, token: Token[dict[str, str]]) -> None:
        cls._planner_update_context.reset(token)

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
        Always emits ``constraint_saved`` planner update events to
        ``.pdd_runs/<run_id>/coordination/planner_updates.jsonl`` when
        planner context is available, then invokes ``on_constraint_saved``
        callbacks as an additional in-process hook.

        Returns:
            Path to the saved constraints file.
        """
        constraints = [self._fact_to_constraint(f) for f in facts]
        path = self._store.save(slice_id, constraints)

        self._emit_constraint_saved_events(slice_id, facts)

        return path

    def _emit_constraint_saved_events(self, slice_id: str, facts: list[ConstraintFact]) -> None:
        context = self._planner_update_context.get({})
        run_id = str(context.get("run_id", "")).strip()
        layer = str(context.get("layer", "")).strip()
        capability = str(context.get("capability", "")).strip()

        if not run_id:
            logger.debug(
                "save_facts persisted %d facts for slice %s but planner update context "
                "has no run_id; skipping planner_updates.jsonl emission",
                len(facts),
                slice_id,
            )

        for fact in facts:
            if not fact.constraint_id:
                continue
            canonical_key = self._extract_canonical_key(fact)
            event = {
                "event_kind": "constraint_saved",
                "event_id": fact.constraint_id,
                "created_at": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "slice_id": slice_id,
                "layer": layer,
                "capability": capability,
                "constraint_id": fact.constraint_id,
                "constraint_ids": [fact.constraint_id],
                "canonical_key": canonical_key,
                "canonical_keys": [canonical_key] if canonical_key else [],
            }
            if run_id:
                self._append_planner_update_event(run_id, event)

            if self._on_constraint_saved is not None:
                try:
                    self._on_constraint_saved(slice_id, fact.constraint_id, canonical_key)
                except Exception:
                    logger.warning(
                        "on_constraint_saved callback failed for %s/%s",
                        slice_id,
                        fact.constraint_id,
                        exc_info=True,
                    )

    def _append_planner_update_event(self, run_id: str, event: dict[str, object]) -> None:
        updates_path = (
            self._workspace / ".pdd_runs" / run_id / "coordination" / "planner_updates.jsonl"
        )
        try:
            updates_path.parent.mkdir(parents=True, exist_ok=True)
            with updates_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError:
            logger.warning(
                "Failed to append constraint_saved planner update for event_id=%s",
                event.get("event_id", ""),
                exc_info=True,
            )

    @staticmethod
    def _extract_canonical_key(fact: ConstraintFact) -> str:
        for trace_entry in fact.trace:
            if trace_entry.startswith("canonical_key="):
                return trace_entry.split("=", 1)[1]
        return ""

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
            decision_type=c.decision_type,
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
            decision_type=f.decision_type,
            scope=f.scope,
            applies_to_layers=list(f.applies_to_layers),
            status=f.status,
            supersedes=list(f.supersedes),
            trace=list(f.trace),
        )
