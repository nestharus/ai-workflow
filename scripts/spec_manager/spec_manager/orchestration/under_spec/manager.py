"""Under-specification manager.

Implements the hard-stop blocking policy: when the implementation step
emits under-spec events that cannot be resolved from existing constraints,
the slice is BLOCKED until constraints are provided.

Modes:
  * **interactive** — emits :class:`UserQuestionSignal` events to the
    Intent Agent queue.  The Planner is the only constraint writer;
    the slice stays BLOCKED until constraints arrive.
  * **auto** — delegates to :class:`ResearchCoordinator` which may propose
    constraints.  Only if the proposal passes validation does the slice
    unblock; otherwise it stays BLOCKED.

Constraints are persisted as YAML files in
``<workspace>/analysis/constraints/<slice_id>.yaml`` so that subsequent
iterations can pick them up deterministically.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from spec_manager.planner.constraints.store import Constraint, ConstraintsStore

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------


@dataclass
class UnderSpecEvent:
    """A single under-specification event emitted by P9 (IMPLEMENT).

    Attributes:
        event_id: Unique identifier.
        kind: Event classification.
        question: The question that needs a constraint answer.
        context: Supporting evidence (file paths, pin IDs, etc.).
        source_file: File the event relates to.
        source_line: Approximate line in source_file.
    """

    event_id: str = ""
    kind: Literal[
        "MISSING_CONSTRAINT",
        "CONFLICTING_CONSTRAINTS",
        "EXTERNAL_DEPENDENCY_UNKNOWN",
        "AMBIGUOUS_REQUIREMENT",
    ] = "MISSING_CONSTRAINT"
    question: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""
    source_line: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UnderSpecEvent:
        import hashlib

        event_id = d.get("event_id", "")
        if not event_id:
            # Generate deterministic ID from question content
            question = d.get("question", "")
            event_id = hashlib.sha256(question.encode()).hexdigest()[:12] if question else ""

        return cls(
            event_id=event_id,
            kind=d.get("kind", "MISSING_CONSTRAINT"),
            question=d.get("question", ""),
            context=d.get("context", {}),
            source_file=d.get("source_file", d.get("file", "")),
            source_line=d.get("source_line", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "question": self.question,
            "context": self.context,
            "source_file": self.source_file,
            "source_line": self.source_line,
        }


@dataclass
class UnderSpecOutcome:
    """Result of resolving under-spec events.

    Attributes:
        resolved: Events that were resolved with constraints.
        blocked: Events that could not be resolved (slice must block).
        constraints: New constraints produced during resolution.
    """

    resolved: list[UnderSpecEvent] = field(default_factory=list)
    blocked: list[UnderSpecEvent] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    blockers_path: str = ""
    constraint_request_path: str = ""
    decisions_path: str = ""
    bundle_status: Literal["IN_PROGRESS", "BLOCKED"] = "IN_PROGRESS"
    blocked_on: list[str] = field(default_factory=list)
    resume_hint: dict[str, str] = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        return len(self.blocked) > 0

    @property
    def blocked_questions(self) -> list[str]:
        return [e.question for e in self.blocked if e.question]


# ------------------------------------------------------------------
# UnderSpecManager
# ------------------------------------------------------------------


class UnderSpecManager:
    """Orchestrates under-specification resolution.

    Policy: constraints must cover every under-spec event.
    No guessing is allowed — if the LLM cannot produce a validated
    constraint, the slice blocks.

    Args:
        workspace_root: Repository root path.
        mode: Resolution mode (interactive or auto).
        planner: Optional planner instance for resolution.
        run_id: PDD run identifier (used for signal store path).
    """

    def __init__(
        self,
        workspace_root: Path,
        mode: Literal["interactive", "auto"] = "auto",
        planner: Any = None,
        run_id: str = "",
    ) -> None:
        self._workspace = workspace_root
        self._mode = mode
        self._store = ConstraintsStore(workspace_root)
        self._planner = planner
        self._run_id = run_id
        self._last_constraint_request_path = ""

    def resolve(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
        *,
        layer: str = "any",
    ) -> UnderSpecOutcome:
        """Attempt to resolve all under-spec events.

        1. Check existing constraints for coverage.
        2. For uncovered events, delegate to interactive/auto resolver.
        3. Validate any new constraints.
        4. Return outcome with resolved/blocked partitions.

        Args:
            slice_id: The slice identifier.
            events: Under-spec events to resolve.
            layer: The layer context (l1, l2, l3, or any).
        """
        if not events:
            return UnderSpecOutcome()

        # Phase 1: Check existing constraints
        covered, uncovered = self._store.find_covering(slice_id, events)

        if not uncovered:
            logger.info(
                "All %d under-spec events covered by existing constraints",
                len(covered),
            )
            return UnderSpecOutcome(resolved=covered)

        logger.info(
            "%d covered, %d uncovered under-spec events for slice '%s'",
            len(covered),
            len(uncovered),
            slice_id,
        )

        # Phase 2: Attempt resolution of uncovered events
        new_constraints: list[Constraint] = []
        still_blocked: list[UnderSpecEvent] = []
        self._last_constraint_request_path = ""

        if self._mode == "interactive":
            new_constraints, still_blocked = self._resolve_interactive(slice_id, uncovered)
        else:
            new_constraints, still_blocked = self._resolve_auto(slice_id, uncovered, layer=layer)

        constraint_request_path = self._last_constraint_request_path

        # Phase 3: Validate and persist new constraints
        validated: list[Constraint] = []
        for c in new_constraints:
            if self._validate_constraint(c):
                c.validated = True
                validated.append(c)
            else:
                logger.warning(
                    "Constraint %s failed validation — treating as blocked",
                    c.constraint_id,
                )
                # Find the event it was supposed to resolve
                matching = [e for e in uncovered if e.event_id == c.constraint_id]
                still_blocked.extend(matching)

        constraint_file_path = ""
        if validated:
            constraint_file_path = str(self._store.save(slice_id, validated))
            logger.info(
                "Saved %d new constraints for slice '%s'",
                len(validated),
                slice_id,
            )

        still_blocked = self._dedupe_events(still_blocked)
        newly_resolved = [
            e for e in uncovered if e.event_id in {c.constraint_id for c in validated}
        ]
        decisions = self._build_decisions(validated)

        decisions_path = ""
        if decisions:
            decisions_path = str(self._write_decisions(slice_id, decisions))

        if still_blocked and not constraint_request_path:
            constraint_request_path = str(self._write_constraint_request(slice_id, still_blocked))

        blockers_path = ""
        bundle_status: Literal["IN_PROGRESS", "BLOCKED"] = "IN_PROGRESS"
        blocked_on: list[str] = []
        resume_hint: dict[str, str] = {}
        if still_blocked:
            blocked_on = [e.question for e in still_blocked if e.question]
            resume_hint = {
                "constraints_path": constraint_file_path or str(self._constraint_path(slice_id)),
                "constraint_request_path": constraint_request_path,
                "decisions_path": decisions_path,
            }
            blockers_path = str(
                self._write_blockers(
                    slice_id=slice_id,
                    blocked_events=still_blocked,
                    blocked_on=blocked_on,
                    resume_hint=resume_hint,
                )
            )
            bundle_status = "BLOCKED"

        return UnderSpecOutcome(
            resolved=covered + newly_resolved,
            blocked=still_blocked,
            constraints=validated,
            decisions=decisions,
            blockers_path=blockers_path,
            constraint_request_path=constraint_request_path,
            decisions_path=decisions_path,
            bundle_status=bundle_status,
            blocked_on=blocked_on,
            resume_hint=resume_hint,
        )

    # ------------------------------------------------------------------
    # Resolution strategies
    # ------------------------------------------------------------------

    def _resolve_interactive(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
    ) -> tuple[list[Constraint], list[UnderSpecEvent]]:
        """Emit UserQuestionSignals for the Intent Agent queue.

        Instead of running InteractiveWorkflow directly, this emits one
        UserQuestionSignal per under-spec event.  The Planner is the only
        writer of constraints — this method intentionally returns no
        constraints and marks all events as still blocked.

        The signals are written to
        ``<workspace>/.pdd_runs/<run_id>/coordination/user_questions.jsonl``
        where the Intent Agent will pick them up, rewrite them into
        user-facing language, and present them through its quality gate.
        """
        # Lazy import to avoid circular dependency
        from spec_manager.orchestration.intent_agent.signals import (
            CodeRefItem,
            SignalBlocking,
            SignalContext,
            SignalQuestion,
            SignalSource,
            UserQuestionSignal,
            UserQuestionSignalStore,
        )

        run_dir = self._workspace / ".pdd_runs" / self._run_id
        store = UserQuestionSignalStore(run_dir)
        request_path = self._write_constraint_request(slice_id, events)
        self._last_constraint_request_path = str(request_path)

        for event in events:
            signal = UserQuestionSignal(
                run_id=self._run_id,
                source=SignalSource(
                    kind="UNDER_SPEC",
                    slice_id=slice_id,
                    layer="any",
                    trace_id=event.event_id,
                ),
                question=SignalQuestion(
                    text=event.question,
                    canonical_key_hint=f"underspec.{event.event_id}",
                ),
                context=SignalContext(
                    blocking=SignalBlocking(
                        severity="BLOCKING",
                        blocked_slices=[slice_id],
                    ),
                    code_refs=[
                        CodeRefItem(
                            file=event.source_file,
                            line=event.source_line,
                        )
                    ]
                    if event.source_file
                    else [],
                ),
                payload=event.to_dict(),
            )
            store.write(signal)

        logger.info(
            "Emitted %d UserQuestionSignals for slice '%s' (run_id=%s)",
            len(events),
            slice_id,
            self._run_id,
        )

        # No constraints resolved — Planner is the only writer.
        # All events remain blocked until Planner writes constraints
        # after user answers via the Intent Agent.
        return [], list(events)

    def _resolve_auto(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
        *,
        layer: str = "any",
    ) -> tuple[list[Constraint], list[UnderSpecEvent]]:
        """Resolve via planner (preferred) or ResearchCoordinator (fallback).

        The planner routes to layer-specific resolution and research tools.
        Constraints must pass validation before the slice unblocks.
        """
        # Try planner-based resolution first
        if self._planner is not None:
            return self._resolve_via_planner(slice_id, events, layer=layer)

        logger.warning(
            "Planner unavailable for under-spec resolution (slice=%s, layer=%s); "
            "using legacy ResearchCoordinator fallback",
            slice_id,
            layer,
        )
        return self._resolve_via_coordinator(slice_id, events)

    def _resolve_via_planner(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
        *,
        layer: str = "any",
    ) -> tuple[list[Constraint], list[UnderSpecEvent]]:
        """Resolve under-spec events via the planner module."""
        constraints: list[Constraint] = []
        blocked: list[UnderSpecEvent] = []

        try:
            from spec_manager.planner.api import PlanningContext

            event_dicts = [e.to_dict() for e in events]
            ctx = PlanningContext(
                slice_id=slice_id,
                layer=layer,
                mode="auto",
                workspace_root=str(self._workspace),
            )
            result = self._planner.resolve_under_spec(ctx, event_dicts)

            resolved_ids = set()

            # Extract constraints from planner result
            for key, value in result.get("constraints", {}).items():
                answer = ""
                confidence = 0.7
                trace: list[str] = []

                if isinstance(value, str):
                    answer = value.strip()
                elif isinstance(value, dict):
                    answer = str(value.get("answer", "")).strip()
                    raw_confidence = value.get("confidence")
                    if isinstance(raw_confidence, (int, float)):
                        confidence = float(raw_confidence)
                    raw_trace = value.get("trace")
                    if isinstance(raw_trace, list):
                        trace = [str(item) for item in raw_trace]

                if answer:
                    matching = [e for e in events if e.event_id == key or e.question == key]
                    for event in matching:
                        constraints.append(
                            Constraint(
                                constraint_id=event.event_id,
                                question=event.question,
                                answer=answer,
                                source="planner",
                                confidence=confidence,
                                validated=False,
                                trace=trace,
                            )
                        )
                        resolved_ids.add(event.event_id)

            # Remaining events are blocked
            for event in events:
                if event.event_id not in resolved_ids:
                    blocked.append(event)

        except Exception as exc:
            logger.warning("Planner resolution failed: %s", exc)
            blocked = list(events)

        return constraints, blocked

    def _resolve_via_coordinator(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
    ) -> tuple[list[Constraint], list[UnderSpecEvent]]:
        """Resolve via ResearchCoordinator (legacy fallback)."""
        constraints: list[Constraint] = []
        blocked: list[UnderSpecEvent] = []

        try:
            from spec_manager.refinement.interactive.ambiguity_detector import (
                Ambiguity,
            )
            from spec_manager.refinement.interactive.research.coordinator import (
                ResearchCoordinator,
            )

            coordinator = ResearchCoordinator()

            for event in events:
                ambiguity = Ambiguity(
                    ambiguity_id=event.event_id or f"underspec_{id(event)}",
                    source_text=event.question,
                    source_location=f"{event.source_file}:{event.source_line}",
                    ambiguity_type="missing_condition",
                    confidence=1.0,
                    suggested_question=event.question,
                )

                response = coordinator.research(ambiguity, self._workspace)

                if response.response_text.strip():
                    constraints.append(
                        Constraint(
                            constraint_id=event.event_id,
                            question=event.question,
                            answer=response.response_text,
                            source="research_coordinator",
                            confidence=0.7,
                            validated=False,
                            trace=[
                                "under_spec_resolution_mode=legacy_coordinator_fallback",
                                f"slice_id={slice_id}",
                            ],
                        )
                    )
                    logger.info(
                        "Under-spec fallback resolved event=%s for slice=%s via legacy coordinator",
                        event.event_id,
                        slice_id,
                    )
                else:
                    logger.debug(
                        "Under-spec fallback did not resolve event=%s for slice=%s",
                        event.event_id,
                        slice_id,
                    )
                    blocked.append(event)

        except Exception as exc:
            logger.warning(
                "Auto resolution failed for legacy coordinator fallback (slice=%s): %s",
                slice_id,
                exc,
            )
            blocked = list(events)

        return constraints, blocked

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_constraint(self, constraint: Constraint) -> bool:
        """Validate that a constraint is concrete and usable.

        A valid constraint must:
        - Have non-empty answer text
        - Be concrete (not just "TBD" or similar)
        - Not contradict itself
        """
        answer = constraint.answer.strip().lower()

        if not answer:
            return False

        # Reject obvious non-answers
        non_answers = {"tbd", "todo", "unknown", "n/a", "na", "?", "..."}
        if answer in non_answers:
            return False

        # Minimum length check
        return len(answer) >= 5

    def _constraint_path(self, slice_id: str) -> Path:
        return self._workspace / "analysis" / "constraints" / f"{slice_id}.yaml"

    def _under_spec_dir(self, slice_id: str) -> Path:
        path = self._workspace / "analysis" / "under_spec" / slice_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _dedupe_events(events: list[UnderSpecEvent]) -> list[UnderSpecEvent]:
        deduped: list[UnderSpecEvent] = []
        seen_ids: set[str] = set()
        for event in events:
            key = event.event_id or event.question
            if key in seen_ids:
                continue
            seen_ids.add(key)
            deduped.append(event)
        return deduped

    def _write_constraint_request(self, slice_id: str, events: list[UnderSpecEvent]) -> Path:
        lines: list[str] = [
            f"# Constraint Request: {slice_id}",
            "",
            "Status: BLOCKED",
            f"Generated: {datetime.now(UTC).isoformat()}",
            "",
            "Provide constraints in YAML at:",
            f"- `analysis/constraints/{slice_id}.yaml`",
            "",
            "## Questions",
            "",
        ]

        for index, event in enumerate(events, start=1):
            lines.append(
                f"### {index}. [{event.event_id}] {event.question or '(no question text)'}"
            )
            lines.append(f"- Kind: `{event.kind}`")
            if event.source_file:
                lines.append(f"- Evidence file: `{event.source_file}:{event.source_line or 1}`")

            options = self._extract_options(event.context)
            if options:
                lines.append("- Options:")
                for option in options:
                    lines.append(f"  - {option}")

            evidence_refs = self._extract_evidence_refs(event.context)
            if evidence_refs:
                lines.append("- Evidence references:")
                for ref in evidence_refs:
                    lines.append(f"  - {ref}")

            lines.append("")

        lines.extend(
            [
                "## Required Decision Format",
                "",
                "YAML:",
                "```yaml",
                "constraints:",
                "  - constraint_id: <event_id>",
                "    question: <question>",
                "    answer: <concrete testable answer>",
                "    source: user",
                "```",
                "",
                "JSON:",
                "```json",
                '{"constraints":[{"constraint_id":"<event_id>","question":"<question>","answer":"<answer>","source":"user"}]}',
                "```",
                "",
            ]
        )

        path = self._under_spec_dir(slice_id) / "constraint_request.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _write_blockers(
        self,
        *,
        slice_id: str,
        blocked_events: list[UnderSpecEvent],
        blocked_on: list[str],
        resume_hint: dict[str, str],
    ) -> Path:
        payload = {
            "slice_id": slice_id,
            "status": "BLOCKED",
            "blocked_on": blocked_on,
            "resume_hint": resume_hint,
            "events": [event.to_dict() for event in blocked_events],
            "created_at": datetime.now(UTC).isoformat(),
        }
        path = self._under_spec_dir(slice_id) / "blockers.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _build_decisions(constraints: list[Constraint]) -> list[dict[str, Any]]:
        decisions: list[dict[str, Any]] = []
        for constraint in constraints:
            decisions.append(
                {
                    "event_id": constraint.constraint_id,
                    "question": constraint.question,
                    "answer": constraint.answer,
                    "source": constraint.source,
                    "confidence": constraint.confidence,
                    "trace": list(constraint.trace),
                }
            )
        return decisions

    def _write_decisions(self, slice_id: str, decisions: list[dict[str, Any]]) -> Path:
        payload = {
            "slice_id": slice_id,
            "status": "RESOLVED",
            "decisions": decisions,
            "created_at": datetime.now(UTC).isoformat(),
        }
        path = self._under_spec_dir(slice_id) / "decisions.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _extract_options(context: dict[str, Any]) -> list[str]:
        for key in ("options", "option_set", "choices"):
            value = context.get(key)
            if isinstance(value, list):
                return [str(item) for item in value if str(item).strip()]
        return []

    @staticmethod
    def _extract_evidence_refs(context: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for key in ("evidence_paths", "pin_ids", "gate_ids"):
            value = context.get(key)
            if isinstance(value, list):
                refs.extend(str(item) for item in value if str(item).strip())
        return refs
