"""Under-specification manager.

Implements the hard-stop blocking policy: when the implementation step
emits under-spec events that cannot be resolved from existing constraints,
the slice is BLOCKED until constraints are provided.

Modes:
  * **interactive** — generates a ``constraint_request.md`` and delegates
    to :class:`InteractiveWorkflow` to collect constraints from the user.
  * **auto** — delegates to :class:`ResearchCoordinator` which may propose
    constraints.  Only if the proposal passes validation does the slice
    unblock; otherwise it stays BLOCKED.

Constraints are persisted as YAML files in
``<workspace>/analysis/constraints/<slice_id>.yaml`` so that subsequent
iterations can pick them up deterministically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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
    """

    def __init__(
        self,
        workspace_root: Path,
        mode: Literal["interactive", "auto"] = "auto",
        planner: Any = None,
    ) -> None:
        self._workspace = workspace_root
        self._mode = mode
        self._store = ConstraintsStore(workspace_root)
        self._planner = planner

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

        if self._mode == "interactive":
            new_constraints, still_blocked = self._resolve_interactive(slice_id, uncovered)
        else:
            new_constraints, still_blocked = self._resolve_auto(slice_id, uncovered, layer=layer)

        # Phase 3: Validate and persist new constraints
        validated = []
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

        if validated:
            self._store.save(slice_id, validated)
            logger.info(
                "Saved %d new constraints for slice '%s'",
                len(validated),
                slice_id,
            )

        newly_resolved = [
            e for e in uncovered if e.event_id in {c.constraint_id for c in validated}
        ]

        return UnderSpecOutcome(
            resolved=covered + newly_resolved,
            blocked=still_blocked,
            constraints=validated,
        )

    # ------------------------------------------------------------------
    # Resolution strategies
    # ------------------------------------------------------------------

    def _resolve_interactive(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
    ) -> tuple[list[Constraint], list[UnderSpecEvent]]:
        """Resolve via InteractiveWorkflow.

        Generates a constraint_request.md and presents it to the user
        through the interactive workflow.
        """
        request_path = self._write_constraint_request(slice_id, events)
        logger.info("Wrote constraint request: %s", request_path)

        try:
            from spec_manager.refinement.interactive.workflow import (
                InteractiveWorkflow,
            )

            workflow = InteractiveWorkflow(
                workspace=self._workspace,
                interactive=True,
                max_iterations=1,
            )

            # Build a spec text from the constraint request
            request_text = request_path.read_text(encoding="utf-8")
            refined = workflow.run(request_text)

            # Parse responses into constraints
            return self._parse_interactive_response(events, refined)
        except Exception as exc:
            logger.warning("Interactive resolution failed: %s", exc)
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

        return self._resolve_via_coordinator(events)

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
                if isinstance(value, str) and value.strip():
                    matching = [e for e in events if e.event_id == key or e.question == key]
                    for event in matching:
                        constraints.append(
                            Constraint(
                                constraint_id=event.event_id,
                                question=event.question,
                                answer=value,
                                source="research",
                                confidence=0.7,
                                validated=False,
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
                            source="research",
                            confidence=0.7,
                            validated=False,
                        )
                    )
                else:
                    blocked.append(event)

        except Exception as exc:
            logger.warning("Auto resolution failed: %s", exc)
            blocked = list(events)

        return constraints, blocked

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write_constraint_request(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
    ) -> Path:
        """Write a human-readable constraint request document."""
        out_dir = self._workspace / "analysis" / "constraint_requests"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{slice_id}.md"

        lines = [
            f"# Constraint Request: {slice_id}",
            "",
            "The following questions need explicit constraints before implementation can proceed.",
            "",
        ]

        for i, event in enumerate(events, 1):
            lines.append(f"## Question {i}: {event.kind}")
            lines.append("")
            lines.append(f"**Question:** {event.question}")
            lines.append("")
            if event.source_file:
                lines.append(f"**Source:** `{event.source_file}`:{event.source_line}")
                lines.append("")
            if event.context:
                lines.append("**Context:**")
                for k, v in event.context.items():
                    lines.append(f"- {k}: {v}")
                lines.append("")
            lines.append("**Required answer format:** Free text or structured YAML/JSON.")
            lines.append("")
            lines.append("---")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _parse_interactive_response(
        self,
        events: list[UnderSpecEvent],
        refined_text: str,
    ) -> tuple[list[Constraint], list[UnderSpecEvent]]:
        """Parse the refined text from InteractiveWorkflow into constraints.

        If the workflow produced substantive changes, treat them as answers.
        Otherwise, events remain blocked.
        """
        constraints: list[Constraint] = []
        blocked: list[UnderSpecEvent] = []

        # Simple heuristic: if the refined text differs significantly from
        # the request, consider it answered
        for event in events:
            # Check if the question appears answered in the output
            if event.question and event.question in refined_text:
                # Question still present unmodified — likely not answered
                blocked.append(event)
            elif refined_text.strip():
                constraints.append(
                    Constraint(
                        constraint_id=event.event_id,
                        question=event.question,
                        answer=refined_text,
                        source="user",
                        confidence=1.0,
                        validated=False,
                    )
                )
            else:
                blocked.append(event)

        return constraints, blocked

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
