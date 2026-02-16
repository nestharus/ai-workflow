"""Constraints tool adapters for planner/runtime subsystems.

This module is the single adapter boundary for planner constraint access:
loading/saving authoritative facts, hypothesis persistence, and read-only
coverage checks used by planning and research workflows.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from spec_manager.planner.constraints.store import Constraint, ConstraintsStore
from spec_manager.planner.constraints.types import ConstraintFact, ConstraintHypothesis

logger = logging.getLogger(__name__)


@dataclass
class ConstraintRecord:
    """A lightweight constraint projection for lookup/read APIs."""

    constraint_id: str
    question: str
    answer: str
    source: str = ""
    confidence: float = 0.0


@dataclass
class ConstraintsSnapshot:
    """Snapshot of known constraints for a slice."""

    slice_id: str
    constraints: list[ConstraintRecord] = field(default_factory=list)

    def covers(self, question: str) -> ConstraintRecord | None:
        """Return the first matching record for *question* (case-insensitive)."""
        normalized = question.lower().strip()
        for constraint in self.constraints:
            if constraint.question.lower().strip() == normalized:
                return constraint
        return None


class ConstraintsTool:
    """Planner-facing adapter over :class:`ConstraintsStore`.

    This is the authoritative integration boundary for planner constraint
    operations and supersedes planner-owned adapters under ``constraints/``.
    """

    _planner_update_context: ContextVar[dict[str, str]] = ContextVar(
        "constraints_tool_planner_update_context",
    )

    def __init__(
        self,
        workspace_root: Path | None = None,
        on_constraint_saved: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._workspace = Path(workspace_root) if workspace_root is not None else None
        self._store = ConstraintsStore(self._workspace) if self._workspace is not None else None
        self._on_constraint_saved = on_constraint_saved

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

    def load_constraints(self, slice_id: str) -> ConstraintsSnapshot:
        """Load constraints for *slice_id* as lightweight records."""
        if self._store is None:
            return ConstraintsSnapshot(slice_id=slice_id)

        try:
            rows = self._store.load(slice_id)
        except Exception as exc:
            logger.debug("Failed to load constraints for slice %s", slice_id, exc_info=True)
            raise RuntimeError(f"Failed to load constraints for slice '{slice_id}'") from exc

        records = [
            ConstraintRecord(
                constraint_id=str(row.constraint_id or ""),
                question=str(row.question or ""),
                answer=str(row.answer or ""),
                source=str(row.source or ""),
                confidence=float(row.confidence or 0.0),
            )
            for row in rows
        ]
        return ConstraintsSnapshot(slice_id=slice_id, constraints=records)

    def check_coverage(
        self,
        slice_id: str,
        questions: list[str],
    ) -> dict[str, ConstraintRecord | None]:
        """Return question -> record coverage map for *slice_id*."""
        snapshot = self.load_constraints(slice_id)
        return {question: snapshot.covers(question) for question in questions}

    def load_merged(self, slice_id: str) -> list[ConstraintFact]:
        """Load merged constraints from ``__system__`` and *slice_id*."""
        if self._store is None:
            return []
        return [
            self._constraint_to_fact(constraint) for constraint in self._store.load_merged(slice_id)
        ]

    def emits_constraint_saved_notifications(self) -> bool:
        """Whether save operations invoke a runtime notification callback."""
        return self._on_constraint_saved is not None

    def save_facts(self, slice_id: str, facts: list[ConstraintFact]) -> Path:
        """Persist planner facts and emit planner-update events/callbacks."""
        if self._store is None:
            raise RuntimeError("ConstraintsTool.save_facts requires workspace_root")

        constraints = [self._fact_to_constraint(fact) for fact in facts]
        path = self._store.save(slice_id, constraints)
        self._emit_constraint_saved_events(slice_id, facts)
        return path

    def _emit_constraint_saved_events(self, slice_id: str, facts: list[ConstraintFact]) -> None:
        context = self._planner_update_context.get({})
        run_id = str(context.get("run_id", "")).strip()
        layer = str(context.get("layer", "")).strip()
        capability = str(context.get("capability", "")).strip()
        planner_updates_run_id = run_id or "__orphan__"

        if not run_id:
            logger.warning(
                "save_facts persisted %d facts for slice %s without run_id context; "
                "planner updates will be written under run_id=%s with trace_status=orphaned",
                len(facts),
                slice_id,
                planner_updates_run_id,
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
                "trace_status": "complete" if run_id else "orphaned",
            }
            if not run_id:
                event["trace_error"] = "missing_run_id_context"
            self._append_planner_update_event(planner_updates_run_id, event)

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
        if self._workspace is None:
            logger.debug("Cannot append planner update without workspace root")
            return

        updates_path = (
            self._workspace / ".pdd_runs" / run_id / "coordination" / "planner_updates.jsonl"
        )
        try:
            updates_path.parent.mkdir(parents=True, exist_ok=True)
            with updates_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError as exc:
            logger.warning(
                "Failed to append constraint_saved planner update for event_id=%s",
                event.get("event_id", ""),
                exc_info=True,
            )
            raise RuntimeError(
                "Failed to append constraint_saved planner update "
                f"for event_id='{event.get('event_id', '')}' to '{updates_path}'"
            ) from exc

    @staticmethod
    def _extract_canonical_key(fact: ConstraintFact) -> str:
        for trace_entry in fact.trace:
            if trace_entry.startswith("canonical_key="):
                return trace_entry.split("=", 1)[1]
        return ""

    def save_hypotheses(self, slice_id: str, hypotheses: list[ConstraintHypothesis]) -> Path:
        """Persist hypotheses to ``analysis/constraints_hypotheses``."""
        if self._workspace is None:
            raise RuntimeError("ConstraintsTool.save_hypotheses requires workspace_root")

        out_dir = self._workspace / "analysis" / "constraints_hypotheses"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{slice_id}.json"
        path.write_text(
            json.dumps([hypothesis.to_dict() for hypothesis in hypotheses], indent=2),
            encoding="utf-8",
        )
        return path

    def load_hypotheses(self, slice_id: str) -> list[ConstraintHypothesis]:
        """Load hypotheses for *slice_id* (empty only when unavailable)."""
        if self._workspace is None:
            return []

        path = self._workspace / "analysis" / "constraints_hypotheses" / f"{slice_id}.json"
        if not path.exists():
            return []

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise TypeError(f"Expected hypotheses list, got {type(data).__name__}")
            return [ConstraintHypothesis.from_dict(row) for row in data]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Failed to load hypotheses for %s: %s", slice_id, exc)
            raise RuntimeError(
                f"Failed to load hypotheses for slice '{slice_id}' from '{path}'"
            ) from exc

    @staticmethod
    def _constraint_to_fact(constraint: Constraint) -> ConstraintFact:
        return ConstraintFact(
            constraint_id=constraint.constraint_id,
            question=constraint.question,
            answer=constraint.answer,
            source=constraint.source,
            confidence=constraint.confidence,
            validated=constraint.validated,
            dimension=constraint.dimension,
            authority_required=constraint.authority_required,
            decision_type=constraint.decision_type,
            scope=constraint.scope,
            applies_to_layers=list(constraint.applies_to_layers),
            status=constraint.status,
            supersedes=list(constraint.supersedes),
            trace=list(constraint.trace),
        )

    @staticmethod
    def _fact_to_constraint(fact: ConstraintFact) -> Constraint:
        return Constraint(
            constraint_id=fact.constraint_id,
            question=fact.question,
            answer=fact.answer,
            source=fact.source,
            confidence=fact.confidence,
            validated=fact.validated,
            dimension=fact.dimension,
            authority_required=fact.authority_required,
            decision_type=fact.decision_type,
            scope=fact.scope,
            applies_to_layers=list(fact.applies_to_layers),
            status=fact.status,
            supersedes=list(fact.supersedes),
            trace=list(fact.trace),
        )
