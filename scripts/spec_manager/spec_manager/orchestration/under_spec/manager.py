"""Under-specification manager.

Resolves under-spec events by either:

* routing planner-validated constraints through Planner-owned persistence, or
* emitting UserQuestionSignals and pausing in ``WAITING`` until Planner
  records authoritative answers.

Modes:
  * **interactive** — emits :class:`UserQuestionSignal` events only.
  * **auto** — delegates to Planner (preferred) or legacy coordinator;
    low-confidence / contradictory expansions are escalated to interactive
    signal emission.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from spec_manager.planner.constraints.store import Constraint, ConstraintsStore
from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter

logger = logging.getLogger(__name__)

_VALID_DIMENSIONS = {
    "software",
    "legal",
    "economic",
    "organizational",
    "temporal",
    "operational",
}
_NON_SOFTWARE_DIMENSIONS = _VALID_DIMENSIONS - {"software"}
_VALID_DECISION_TYPES = {
    "dependency",
    "infrastructure",
    "data_policy",
    "security",
    "performance",
    "architecture",
}
_DECISION_TYPE_ALIASES = {
    "architecture_decision": "architecture",
    "dep": "dependency",
    "dependency_decision": "dependency",
    "infra": "infrastructure",
    "data": "data_policy",
    "privacy": "data_policy",
    "compliance": "security",
    "perf": "performance",
}
_IMPACT_TRIGGER_LEVELS = {"MEDIUM", "HIGH"}
_LOW_IMPACT_LEVELS = {"LOW"}
_NON_SOFTWARE_TRIGGER_DECISION_TYPES = {
    "dependency",
    "infrastructure",
    "data_policy",
    "security",
    "architecture",
}


def _normalize_dimension(value: Any, *, fallback: str = "software") -> str:
    text = str(value).strip().lower()
    if text in _VALID_DIMENSIONS:
        return text
    return fallback


def _normalize_authority_required(value: Any, *, fallback: str = "planner_ok") -> str:
    text = str(value).strip().lower()
    if text == "user_required":
        return "human_required"
    if text in {"planner_ok", "human_required"}:
        return text
    return fallback


def _infer_decision_type(
    raw_value: Any,
    *,
    kind: str = "",
    question: str = "",
    context: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    raw_text = str(raw_value).strip().lower()
    if raw_text in _VALID_DECISION_TYPES:
        return raw_text, False
    if raw_text in _DECISION_TYPE_ALIASES:
        return _DECISION_TYPE_ALIASES[raw_text], False

    fragments = [raw_text, str(kind).strip().lower(), str(question).strip().lower()]
    if context:
        for key in (
            "decision_type",
            "kind",
            "subtype",
            "impact",
            "reason",
            "question",
            "needed_for",
            "target",
            "dependency",
            "provider",
            "vendor",
        ):
            value = context.get(key)
            if isinstance(value, str):
                fragments.append(value.strip().lower())
    text = " ".join(fragment for fragment in fragments if fragment)

    if any(token in text for token in ("dependency", "package", "library", "module", "vendor")):
        return "dependency", False
    if any(
        token in text for token in ("infrastructure", "infra", "provider", "runtime", "platform")
    ):
        return "infrastructure", False
    if any(
        token in text for token in ("data policy", "retention", "privacy", "pii", "gdpr", "ccpa")
    ):
        return "data_policy", False
    if any(token in text for token in ("security", "auth", "encryption", "vulnerability", "soc2")):
        return "security", False
    if any(token in text for token in ("performance", "latency", "throughput", "slow", "speed")):
        return "performance", False
    if any(token in text for token in ("architecture", "coupling", "boundary", "design")):
        return "architecture", False

    if raw_text:
        return "architecture", True
    return "performance", False


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
        "EXTERNAL_DEP_UNKNOWN",
        "AMBIGUOUS_REQUIREMENT",
        "REVIEW_UNDER_SPEC",
    ] = "MISSING_CONSTRAINT"
    question: str = ""
    dimension: Literal[
        "software",
        "legal",
        "economic",
        "organizational",
        "temporal",
        "operational",
    ] = "software"
    authority_required: Literal["planner_ok", "human_required"] = "planner_ok"
    decision_type: Literal[
        "dependency",
        "infrastructure",
        "data_policy",
        "security",
        "performance",
        "architecture",
    ] = "performance"
    context: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""
    source_line: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UnderSpecEvent:
        import hashlib

        raw_context = d.get("context", {})
        context = raw_context if isinstance(raw_context, dict) else {}
        event_id = d.get("event_id", "")
        if not event_id:
            # Generate deterministic ID from question content
            question = d.get("question", "")
            event_id = hashlib.sha256(question.encode()).hexdigest()[:12] if question else ""

        kind = str(d.get("kind", "MISSING_CONSTRAINT")).strip() or "MISSING_CONSTRAINT"
        question = str(d.get("question", "")).strip()
        dimension = _normalize_dimension(
            d.get("dimension", "software"),
            fallback="software",
        )
        authority_required = _normalize_authority_required(
            d.get(
                "authority_required",
                d.get("authority", "planner_ok"),
            ),
            fallback="human_required" if dimension in _NON_SOFTWARE_DIMENSIONS else "planner_ok",
        )
        decision_type, _ = _infer_decision_type(
            d.get("decision_type", ""),
            kind=kind,
            question=question,
            context=context,
        )

        return cls(
            event_id=event_id,
            kind=kind,
            question=question,
            dimension=dimension,  # type: ignore[arg-type]
            authority_required=authority_required,  # type: ignore[arg-type]
            decision_type=decision_type,  # type: ignore[arg-type]
            context=context,
            source_file=d.get("source_file", d.get("file", "")),
            source_line=d.get("source_line", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "question": self.question,
            "dimension": self.dimension,
            "authority_required": self.authority_required,
            "decision_type": self.decision_type,
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
    bundle_status: Literal["IN_PROGRESS", "WAITING", "BLOCKED"] = "IN_PROGRESS"
    blocked_on: list[str] = field(default_factory=list)
    resume_hint: dict[str, str] = field(default_factory=dict)
    routing: list[dict[str, Any]] = field(default_factory=list)
    monitors: list[dict[str, Any]] = field(default_factory=list)
    expansions: list[dict[str, Any]] = field(default_factory=list)
    expansion_path: str = ""

    @property
    def is_blocked(self) -> bool:
        return len(self.blocked) > 0 and self.bundle_status != "WAITING"

    @property
    def is_waiting(self) -> bool:
        return self.bundle_status == "WAITING"

    @property
    def blocked_questions(self) -> list[str]:
        return [e.question for e in self.blocked if e.question]


@dataclass
class _ResolutionPayload:
    """Internal resolution payload shared across auto/interactive paths."""

    constraints: list[Constraint] = field(default_factory=list)
    blocked: list[UnderSpecEvent] = field(default_factory=list)
    routing: list[dict[str, Any]] = field(default_factory=list)
    monitors: list[dict[str, Any]] = field(default_factory=list)
    expansions: list[dict[str, Any]] = field(default_factory=list)
    needs_interactive_review: list[UnderSpecEvent] = field(default_factory=list)


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

    _MIN_CONSTRAINT_CONFIDENCE = 0.70
    _MIN_EXPANSION_CONFIDENCE = 0.75

    def __init__(
        self,
        workspace_root: Path,
        mode: Literal["interactive", "auto"] = "auto",
        planner: Any = None,
        run_id: str = "",
    ) -> None:
        if not isinstance(run_id, str):
            raise TypeError("UnderSpecManager run_id must be a string")
        normalized_run_id = run_id.strip()
        if not normalized_run_id:
            normalized_run_id = "default"
        self._workspace = workspace_root
        self._mode = mode
        self._store = ConstraintsStore(workspace_root)
        self._constraints_adapter = ConstraintStoreAdapter(workspace_root)
        self._planner = planner
        self._run_id = normalized_run_id
        self._interactive_questions_emitted = False

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
        covered, uncovered = self._find_covering(slice_id, events)
        refinement_candidates = self._build_refinement_candidates(
            slice_id=slice_id,
            covered_events=covered,
        )
        resolution_targets = uncovered + refinement_candidates
        uncovered_event_ids = {event.event_id for event in uncovered if event.event_id}

        if not resolution_targets:
            logger.info(
                "All %d under-spec events covered by existing constraints",
                len(covered),
            )
            return UnderSpecOutcome(resolved=covered)

        logger.info(
            "%d covered, %d uncovered, %d refinable under-spec events for slice '%s'",
            len(covered),
            len(uncovered),
            len(refinement_candidates),
            slice_id,
        )

        # Phase 2: Attempt resolution for uncovered events and eligible refinements.
        self._interactive_questions_emitted = False

        if self._mode == "interactive":
            constraints, blocked = self._resolve_interactive(
                slice_id,
                resolution_targets,
                layer=layer,
            )
            resolution = _ResolutionPayload(constraints=constraints, blocked=blocked)
        else:
            resolution = self._resolve_auto(slice_id, resolution_targets, layer=layer)
            if resolution.needs_interactive_review:
                logger.info(
                    "Escalating %d under-spec expansion candidate(s) to interactive "
                    "review for slice '%s'",
                    len(resolution.needs_interactive_review),
                    slice_id,
                )
                _, escalated_blocked = self._resolve_interactive(
                    slice_id,
                    resolution.needs_interactive_review,
                    layer=layer,
                )
                resolution.blocked.extend(escalated_blocked)

        new_constraints = resolution.constraints
        still_blocked = [
            event
            for event in resolution.blocked
            if event.event_id and event.event_id in uncovered_event_ids
        ]
        routed_work_items = resolution.routing
        routed_monitors = resolution.monitors
        expansions = resolution.expansions

        # Phase 3: Validate planner-returned constraints and persist through Planner.
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
                resolved_event_id = self._constraint_event_id(c)
                if resolved_event_id not in uncovered_event_ids:
                    continue
                matching = [e for e in uncovered if e.event_id == resolved_event_id]
                still_blocked.extend(matching)

        constraint_file_path, persisted_constraint_ids = self._persist_constraints_via_planner(
            slice_id=slice_id,
            layer=layer,
            constraints=validated,
        )
        if validated and not persisted_constraint_ids:
            logger.warning(
                "Planner persistence unavailable for %d under-spec constraints (slice=%s); "
                "keeping events in blocked state",
                len(validated),
                slice_id,
            )
            still_blocked.extend(
                event
                for event in uncovered
                if event.event_id
                in {
                    self._constraint_event_id(c)
                    for c in validated
                    if self._constraint_event_id(c) in uncovered_event_ids
                }
            )
            validated = []
            persisted_constraint_ids = set()

        persisted_event_ids = {
            self._constraint_event_id(constraint)
            for constraint in validated
            if constraint.constraint_id in persisted_constraint_ids
            and self._constraint_event_id(constraint)
        }
        missing_uncovered_event_ids = {
            self._constraint_event_id(constraint)
            for constraint in validated
            if constraint.constraint_id not in persisted_constraint_ids
            and self._constraint_event_id(constraint) in uncovered_event_ids
        }
        if missing_uncovered_event_ids:
            still_blocked.extend(
                event for event in uncovered if event.event_id in missing_uncovered_event_ids
            )

        still_blocked = self._dedupe_events(still_blocked)
        newly_resolved = [e for e in uncovered if e.event_id in persisted_event_ids]
        decisions = self._build_decisions(validated)
        decisions.extend(self._build_expansion_decisions(expansions))

        decisions_path = ""

        expansion_path = ""
        if routed_work_items or routed_monitors or expansions:
            expansion_path = str(
                self._write_expansion_artifacts(
                    slice_id=slice_id,
                    work_items=routed_work_items,
                    monitors=routed_monitors,
                    expansions=expansions,
                )
            )

        blockers_path = ""
        bundle_status: Literal["IN_PROGRESS", "WAITING", "BLOCKED"] = "IN_PROGRESS"
        blocked_on: list[str] = []
        resume_hint: dict[str, str] = {}
        if still_blocked:
            blocked_on = [e.question for e in still_blocked if e.question]
            if self._interactive_questions_emitted and not routed_monitors:
                routed_monitors = self._build_constraint_wait_monitors(
                    slice_id=slice_id,
                    blocked_events=still_blocked,
                )
            resume_hint = {
                "constraints_path": constraint_file_path or str(self._constraint_path(slice_id)),
                "planner_updates_path": str(
                    self._workspace
                    / ".pdd_runs"
                    / self._run_id
                    / "coordination"
                    / "planner_updates.jsonl"
                ),
            }
            if expansion_path:
                resume_hint["expansion_path"] = expansion_path
            if routed_monitors:
                resume_hint["monitor_count"] = str(len(routed_monitors))
            bundle_status = "WAITING" if self._interactive_questions_emitted else "BLOCKED"
            blockers_path = str(
                self._write_blockers(
                    slice_id=slice_id,
                    blocked_events=still_blocked,
                    blocked_on=blocked_on,
                    resume_hint=resume_hint,
                    status=bundle_status,
                )
            )

        return UnderSpecOutcome(
            resolved=covered + newly_resolved,
            blocked=still_blocked,
            constraints=validated,
            decisions=decisions,
            blockers_path=blockers_path,
            constraint_request_path="",
            decisions_path=decisions_path,
            bundle_status=bundle_status,
            blocked_on=blocked_on,
            resume_hint=resume_hint,
            routing=routed_work_items,
            monitors=routed_monitors,
            expansions=expansions,
            expansion_path=expansion_path,
        )

    # ------------------------------------------------------------------
    # Resolution strategies
    # ------------------------------------------------------------------

    def _resolve_interactive(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
        *,
        layer: str = "any",
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
        emission_candidates = [
            event for event in events if self._should_emit_interactive_question(event)
        ]
        deferred_without_question = len(events) - len(emission_candidates)
        self._interactive_questions_emitted = self._interactive_questions_emitted or bool(
            emission_candidates
        )
        if not emission_candidates:
            logger.info(
                "Deferred %d under-spec event(s) without interactive question emission for "
                "slice '%s' (run_id=%s)",
                len(events),
                slice_id,
                self._run_id,
            )
            return [], list(events)

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
        refined_questions = self._refine_interactive_questions(
            slice_id=slice_id,
            events=emission_candidates,
            layer=layer,
        )

        for event in emission_candidates:
            event_key = self._interactive_event_key(event)
            question_text = str(refined_questions.get(event_key, event.question)).strip()
            if not question_text:
                question_text = event.question
            signal = UserQuestionSignal(
                run_id=self._run_id,
                source=SignalSource(
                    kind="UNDER_SPEC",
                    slice_id=slice_id,
                    layer=layer,
                    trace_id=event.event_id,
                    signal_id=f"underspec:{slice_id}:{event.event_id}",
                ),
                question=SignalQuestion(
                    text=question_text,
                    taxonomy_hint=self._question_taxonomy_hint(event),
                    canonical_key_hint=f"underspec.{event.event_id}",
                    answer_spec_hint=self._answer_spec_hint_for_event(event),
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
            "Emitted %d UserQuestionSignals for slice '%s' (run_id=%s, deferred=%d)",
            len(emission_candidates),
            slice_id,
            self._run_id,
            deferred_without_question,
        )

        # No constraints resolved — Planner is the only writer.
        # All events remain blocked until Planner writes constraints
        # after user answers via the Intent Agent.
        return [], list(events)

    @staticmethod
    def _interactive_event_key(event: UnderSpecEvent) -> str:
        event_id = str(event.event_id).strip()
        if event_id:
            return event_id
        return str(event.question).strip()

    def _refine_interactive_questions(
        self,
        *,
        slice_id: str,
        events: list[UnderSpecEvent],
        layer: str,
    ) -> dict[str, str]:
        """Optionally refine interactive under-spec questions through planner strategy."""
        if self._planner is None or not events:
            return {}

        try:
            from spec_manager.planner.api import PlanningContext

            constraints_snapshot = [
                {
                    "constraint_id": constraint.constraint_id,
                    "question": constraint.question,
                    "answer": constraint.answer,
                    "dimension": constraint.dimension,
                    "authority_required": constraint.authority_required,
                    "scope": constraint.scope,
                }
                for constraint in self._load_merged_constraints(slice_id)
            ]
            local_context = [
                {
                    "event_id": event.event_id,
                    "kind": event.kind,
                    "source_file": event.source_file,
                    "source_line": event.source_line,
                    "context": dict(event.context or {}),
                }
                for event in events
            ]
            context = PlanningContext(
                run_id=self._run_id,
                slice_id=slice_id,
                layer=layer,
                mode="interactive",
                workspace_root=str(self._workspace),
                metadata={
                    "under_spec_question_refinement": {
                        "constraints_snapshot": constraints_snapshot,
                        "local_context": local_context,
                    }
                },
            )
            outputs = self._planner.resolve_under_spec(
                context,
                [event.to_dict() for event in events],
            )
        except Exception:
            logger.debug(
                "Interactive question refinement failed for slice '%s'",
                slice_id,
                exc_info=True,
            )
            return {}

        questions = outputs.get("questions", []) if isinstance(outputs, dict) else []
        if not isinstance(questions, list):
            return {}

        refined: dict[str, str] = {}
        for index, raw_question in enumerate(questions):
            if index >= len(events):
                break
            question_text = str(raw_question).strip()
            if not question_text:
                continue
            refined[self._interactive_event_key(events[index])] = question_text
        return refined

    def _resolve_auto(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
        *,
        layer: str = "any",
    ) -> _ResolutionPayload:
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
        constraints, blocked = self._resolve_via_coordinator(slice_id, events)
        return _ResolutionPayload(constraints=constraints, blocked=blocked)

    def _resolve_via_planner(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
        *,
        layer: str = "any",
    ) -> _ResolutionPayload:
        """Resolve under-spec events via the planner module."""
        constraints: list[Constraint] = []
        blocked: list[UnderSpecEvent] = []
        routing: list[dict[str, Any]] = []
        monitors: list[dict[str, Any]] = []
        expansions: list[dict[str, Any]] = []
        needs_interactive_review: list[UnderSpecEvent] = []

        try:
            from spec_manager.planner.api import PlanningContext

            event_dicts = [e.to_dict() for e in events]
            ctx = PlanningContext(
                run_id=self._run_id,
                slice_id=slice_id,
                layer=layer,
                mode="auto",
                workspace_root=str(self._workspace),
            )
            result = self._planner.resolve_under_spec(ctx, event_dicts)

            resolved_ids: set[str] = set()
            policy_dimensions = self._policy_dimensions_for_slice(slice_id)

            # Extract constraints from planner result
            for key, value in result.get("constraints", {}).items():
                answer = ""
                confidence = 0.7
                trace: list[str] = []
                authority_required = "planner_ok"
                dimension = "software"
                decision_type = "performance"
                decision_type_unknown = False
                constraint_id = ""
                question = ""
                status = "ACTIVE"
                scope = "intra:LIB"
                applies_to_layers = self._default_applies_to_layers(layer)
                supersedes: list[str] = []

                if isinstance(value, str):
                    answer = value.strip()
                elif isinstance(value, dict):
                    answer = str(value.get("answer", "")).strip()
                    question = str(value.get("question", "")).strip()
                    constraint_id = str(value.get("constraint_id", "")).strip()
                    raw_confidence = value.get("confidence")
                    if isinstance(raw_confidence, (int, float)):
                        confidence = float(raw_confidence)
                    raw_trace = value.get("trace")
                    if isinstance(raw_trace, list):
                        trace = [str(item) for item in raw_trace]
                    authority_required = _normalize_authority_required(
                        value.get("authority_required", "planner_ok"),
                        fallback="planner_ok",
                    )
                    dimension = _normalize_dimension(
                        value.get("dimension", "software"),
                        fallback="software",
                    )
                    decision_type, decision_type_unknown = _infer_decision_type(
                        value.get("decision_type", ""),
                        kind="",
                        question=question,
                        context=value,
                    )
                    scope = str(value.get("scope", scope)).strip() or scope
                    applies_to_layers = self._normalize_applies_to_layers(
                        value.get("applies_to_layers", applies_to_layers),
                        fallback=applies_to_layers,
                    )
                    status = str(value.get("status", "ACTIVE")).strip().upper() or "ACTIVE"
                    if status not in {"ACTIVE", "SUPERSEDED"}:
                        status = "ACTIVE"
                    supersedes_raw = value.get("supersedes", [])
                    if isinstance(supersedes_raw, list):
                        supersedes = [
                            str(item).strip() for item in supersedes_raw if str(item).strip()
                        ]
                    elif isinstance(supersedes_raw, str):
                        supersedes = [supersedes_raw.strip()] if supersedes_raw.strip() else []

                if answer:
                    matching = [e for e in events if e.event_id == key or e.question == key]
                    for event in matching:
                        resolved_event_id = event.event_id
                        effective_constraint_id = constraint_id or resolved_event_id
                        question_text = question or event.question
                        resolved_dimension = _normalize_dimension(
                            event.dimension if dimension == "software" else dimension,
                            fallback="software",
                        )
                        resolved_decision_type = decision_type
                        raw_decision_type = (
                            str(value.get("decision_type", "")).strip()
                            if isinstance(value, dict)
                            else ""
                        )
                        if not raw_decision_type:
                            resolved_decision_type, _ = _infer_decision_type(
                                "",
                                kind=event.kind,
                                question=question_text,
                                context=event.context,
                            )
                        authority_from_event = _normalize_authority_required(
                            event.authority_required,
                            fallback=authority_required,
                        )
                        effective_authority_required = authority_required
                        if authority_from_event == "human_required":
                            effective_authority_required = "human_required"
                        requires_policy = resolved_dimension in _NON_SOFTWARE_DIMENSIONS
                        policy_covered = (not requires_policy) or (
                            resolved_dimension in policy_dimensions
                        )
                        if requires_policy and not policy_covered:
                            effective_authority_required = "human_required"
                        gate_reason = ""
                        if effective_authority_required != "planner_ok":
                            gate_reason = "human_authority_required"
                        elif decision_type_unknown:
                            gate_reason = "unknown_decision_type"
                        elif confidence < self._MIN_CONSTRAINT_CONFIDENCE:
                            gate_reason = "confidence_below_threshold"
                        if gate_reason:
                            blocked_event = UnderSpecEvent.from_dict(event.to_dict())
                            gate_ctx = dict(blocked_event.context or {})
                            gate_ctx["auto_resolve_gate"] = {
                                "decision": "blocked",
                                "reason": gate_reason,
                                "authority_required": effective_authority_required,
                                "dimension": resolved_dimension,
                                "policy_dimension_covered": policy_covered,
                                "decision_type": resolved_decision_type,
                                "decision_type_unknown": decision_type_unknown,
                                "confidence": confidence,
                            }
                            blocked_event.context = gate_ctx
                            blocked.append(blocked_event)
                            continue

                        event_trace = list(trace)
                        signal_id = (
                            str(event.context.get("signal_id", "")).strip()
                            if isinstance(event.context, dict)
                            else ""
                        )
                        if not signal_id:
                            signal_id = event.event_id
                        if signal_id:
                            event_trace.append(f"signal_id={signal_id}")
                        if event.source_file:
                            event_trace.append(
                                f"spec_ref={event.source_file}:{event.source_line or 1}"
                            )
                        if isinstance(value, dict):
                            event_trace.append("resolution_kind=decision_constraint")
                        if resolved_event_id:
                            event_trace.append(f"resolves_event_id={resolved_event_id}")
                        event_trace.append(f"dimension={resolved_dimension}")
                        event_trace.append(f"decision_type={resolved_decision_type}")
                        event_trace.append(
                            f"policy_dimension_covered={str(policy_covered).lower()}"
                        )
                        event_trace.append("auto_resolve_gate=passed")
                        constraints.append(
                            Constraint(
                                constraint_id=effective_constraint_id,
                                question=question_text,
                                answer=answer,
                                source="planner",
                                confidence=confidence,
                                validated=False,
                                dimension=resolved_dimension,
                                authority_required=effective_authority_required,
                                decision_type=resolved_decision_type,
                                scope=scope,
                                applies_to_layers=applies_to_layers,
                                status=status,
                                supersedes=supersedes,
                                trace=event_trace,
                            )
                        )
                        resolved_ids.add(event.event_id)

            routing_raw = result.get("routing", [])
            if isinstance(routing_raw, list):
                routing = [row for row in routing_raw if isinstance(row, dict)]
            monitors_raw = result.get("monitors", [])
            if isinstance(monitors_raw, list):
                monitors = [row for row in monitors_raw if isinstance(row, dict)]
            expansions_raw = result.get("expansions", [])
            if isinstance(expansions_raw, list):
                expansions = [row for row in expansions_raw if isinstance(row, dict)]
            if not expansions and routing:
                global_confidence_raw = result.get("confidence", 0.0)
                try:
                    global_confidence = float(global_confidence_raw)
                except (TypeError, ValueError):
                    global_confidence = 0.0
                for event in events:
                    event_routing = [
                        row for row in routing if self._expansion_event_id(row) == event.event_id
                    ]
                    if not event_routing:
                        continue
                    first_metadata = event_routing[0].get("metadata", {})
                    first_metadata = first_metadata if isinstance(first_metadata, dict) else {}
                    signal_id = str(first_metadata.get("signal_id", "")).strip()
                    event_monitors = [
                        row
                        for row in monitors
                        if (
                            str(row.get("signal_id", "")).strip() == signal_id
                            if signal_id
                            else True
                        )
                    ]
                    expansions.append(
                        {
                            "event_id": event.event_id,
                            "signal_id": signal_id,
                            "action": str(result.get("action", "EXPAND_SPEC")).strip().upper()
                            or "EXPAND_SPEC",
                            "confidence": first_metadata.get("confidence", global_confidence),
                            "proposal_models": first_metadata.get("proposal_models", []),
                            "consistency_passed": bool(
                                first_metadata.get("consistency_passed", False)
                            ),
                            "contradictions": result.get("contradictions", []),
                            "spec_refs": first_metadata.get("spec_refs", []),
                            "routing": event_routing,
                            "monitors": event_monitors,
                            "why": str(result.get("why", "")).strip(),
                            "missing_detail": str(result.get("missing_detail", "")).strip(),
                        }
                    )

            for expansion in expansions:
                event_id = self._expansion_event_id(expansion)
                if not event_id:
                    continue
                event = next((e for e in events if e.event_id == event_id), None)
                if event is None:
                    continue
                valid, reasons = self._validate_expansion(expansion)
                expansion["validation"] = {
                    "passed": valid,
                    "reasons": reasons,
                }
                if valid:
                    resolved_ids.add(event_id)
                else:
                    blocked.append(event)
                    needs_interactive_review.append(event)

            accepted_event_ids = {
                self._expansion_event_id(expansion)
                for expansion in expansions
                if isinstance(expansion.get("validation"), dict)
                and bool(expansion["validation"].get("passed", False))
            }
            accepted_event_ids.discard("")
            if accepted_event_ids:
                routing = [
                    row for row in routing if self._expansion_event_id(row) in accepted_event_ids
                ]
                monitors = [
                    row
                    for row in monitors
                    if self._monitor_event_id(row, expansions) in accepted_event_ids
                ]
            else:
                routing = []
                monitors = []

            # Remaining events are blocked
            for event in events:
                if event.event_id not in resolved_ids:
                    blocked.append(event)

        except Exception as exc:
            logger.warning("Planner resolution failed: %s", exc)
            blocked = list(events)

        return _ResolutionPayload(
            constraints=constraints,
            blocked=self._dedupe_events(blocked),
            routing=routing,
            monitors=monitors,
            expansions=expansions,
            needs_interactive_review=self._dedupe_events(needs_interactive_review),
        )

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
                    blocked_event = UnderSpecEvent.from_dict(event.to_dict())
                    gate_ctx = dict(blocked_event.context or {})
                    gate_ctx["auto_resolve_gate"] = {
                        "decision": "blocked",
                        "reason": "legacy_fallback_requires_human_authority",
                        "authority_required": "human_required",
                        "confidence": 0.7,
                    }
                    gate_ctx["legacy_fallback_suggestion"] = response.response_text.strip()
                    blocked_event.context = gate_ctx
                    blocked.append(blocked_event)
                    logger.info(
                        "Under-spec fallback suggested an answer for event=%s slice=%s; "
                        "routing as human-required",
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
        - Meet confidence threshold
        - Not advertise contradiction / failed consistency checks in trace
        """
        answer = constraint.answer.strip().lower()

        if not answer:
            return False

        # Reject obvious non-answers
        non_answers = {"tbd", "todo", "unknown", "n/a", "na", "?", "..."}
        if answer in non_answers:
            return False

        # Minimum length check
        if len(answer) < 5:
            return False

        try:
            confidence = float(constraint.confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < self._MIN_CONSTRAINT_CONFIDENCE:
            return False

        trace_tokens = [str(item).strip().lower() for item in constraint.trace if str(item).strip()]
        return not self._trace_has_contradiction(trace_tokens)

    @staticmethod
    def _trace_has_contradiction(trace_tokens: list[str]) -> bool:
        contradiction_markers = (
            "contradiction=true",
            "contradiction_detected",
            "consistency_check=failed",
            "consistency_passed=false",
        )
        return any(marker in token for token in trace_tokens for marker in contradiction_markers)

    def _validate_expansion(self, expansion: dict[str, Any]) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        confidence_raw = expansion.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < self._MIN_EXPANSION_CONFIDENCE:
            reasons.append("low_confidence")

        contradictions_raw = expansion.get("contradictions", [])
        contradictions = (
            [str(item).strip() for item in contradictions_raw if str(item).strip()]
            if isinstance(contradictions_raw, list)
            else []
        )
        if contradictions:
            reasons.append("contradictions_detected")

        if "consistency_passed" in expansion and not bool(
            expansion.get("consistency_passed", False)
        ):
            reasons.append("consistency_check_failed")

        signal_id = str(expansion.get("signal_id", "")).strip()
        if not signal_id:
            reasons.append("missing_signal_id")

        spec_refs_raw = expansion.get("spec_refs", [])
        valid_spec_refs = [
            row
            for row in (spec_refs_raw if isinstance(spec_refs_raw, list) else [])
            if isinstance(row, dict)
            and (str(row.get("spec_text", "")).strip() or str(row.get("source_file", "")).strip())
        ]
        if not valid_spec_refs:
            reasons.append("missing_spec_refs")

        proposal_models_raw = expansion.get("proposal_models", [])
        if self._mode == "auto" and isinstance(proposal_models_raw, list) and proposal_models_raw:
            normalized_models = {
                str(model).strip() for model in proposal_models_raw if str(model).strip()
            }
            if len(normalized_models) < 3:
                reasons.append("insufficient_model_diversity")

        routing_raw = expansion.get("routing", [])
        routing = (
            [row for row in routing_raw if isinstance(row, dict)]
            if isinstance(routing_raw, list)
            else []
        )
        if not routing:
            reasons.append("missing_routing")

        monitors_raw = expansion.get("monitors", [])
        monitors = (
            [row for row in monitors_raw if isinstance(row, dict)]
            if isinstance(monitors_raw, list)
            else []
        )
        if not monitors:
            reasons.append("missing_monitors")

        return len(reasons) == 0, reasons

    @staticmethod
    def _expansion_event_id(payload: dict[str, Any]) -> str:
        metadata = payload.get("metadata", {})
        if isinstance(metadata, dict):
            event_id = str(metadata.get("event_id", "")).strip()
            if event_id:
                return event_id
        return str(payload.get("event_id", "")).strip()

    @classmethod
    def _monitor_event_id(
        cls,
        monitor: dict[str, Any],
        expansions: list[dict[str, Any]],
    ) -> str:
        event_id = cls._expansion_event_id(monitor)
        if event_id:
            return event_id
        signal_id = str(monitor.get("signal_id", "")).strip()
        if not signal_id:
            return ""
        for expansion in expansions:
            if str(expansion.get("signal_id", "")).strip() == signal_id:
                return cls._expansion_event_id(expansion)
        return ""

    def _constraint_path(self, slice_id: str) -> Path:
        return self._workspace / "analysis" / "constraints" / f"{slice_id}.json"

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
            "Decision-gap answers must be written as constraints in JSON at:",
            f"- `analysis/constraints/{slice_id}.json`",
            "",
            "Code/spec expansion gaps must be routed as expansion work-items.",
            "Accepted expansion forms:",
            "1. New spec comments in skeleton files (preferred).",
            "2. New stub function(s) with spec comments.",
            "3. Constraint entries (decision gaps only).",
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
                "Use this format only for decision constraints. Code/spec expansion",
                "changes should be represented as routed work-items, not inline answers.",
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
        status: Literal["WAITING", "BLOCKED"],
    ) -> Path:
        payload = {
            "slice_id": slice_id,
            "status": status,
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

    @staticmethod
    def _build_expansion_decisions(expansions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        decisions: list[dict[str, Any]] = []
        for expansion in expansions:
            signal_id = str(expansion.get("signal_id", "")).strip()
            event_id = str(expansion.get("event_id", "")).strip()
            action = str(expansion.get("action", "")).strip()
            validation = expansion.get("validation", {})
            reasons = (
                [str(reason) for reason in validation.get("reasons", [])]
                if isinstance(validation, dict) and isinstance(validation.get("reasons"), list)
                else []
            )
            decisions.append(
                {
                    "event_id": event_id,
                    "signal_id": signal_id,
                    "action": action,
                    "resolution_type": "spec_expansion",
                    "confidence": expansion.get("confidence", 0.0),
                    "validation_passed": bool(validation.get("passed", False))
                    if isinstance(validation, dict)
                    else False,
                    "validation_reasons": reasons,
                    "spec_refs": expansion.get("spec_refs", []),
                    "routing_count": len(expansion.get("routing", []))
                    if isinstance(expansion.get("routing", []), list)
                    else 0,
                    "monitor_count": len(expansion.get("monitors", []))
                    if isinstance(expansion.get("monitors", []), list)
                    else 0,
                }
            )
        return decisions

    def _write_expansion_artifacts(
        self,
        *,
        slice_id: str,
        work_items: list[dict[str, Any]],
        monitors: list[dict[str, Any]],
        expansions: list[dict[str, Any]],
    ) -> Path:
        payload = {
            "slice_id": slice_id,
            "status": "PENDING_PROVIDER_EXPANSION",
            "work_items": work_items,
            "monitors": monitors,
            "expansions": expansions,
            "created_at": datetime.now(UTC).isoformat(),
        }
        path = self._under_spec_dir(slice_id) / "expansion_routing.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _default_applies_to_layers(layer: str) -> list[str]:
        normalized = str(layer or "").strip().upper()
        return [normalized] if normalized in {"L1", "L2", "L3"} else []

    @classmethod
    def _normalize_applies_to_layers(
        cls,
        raw_value: Any,
        *,
        fallback: list[str],
    ) -> list[str]:
        values: list[str] = []
        if isinstance(raw_value, str):
            values = [raw_value]
        elif isinstance(raw_value, list):
            values = [str(item) for item in raw_value]

        normalized: list[str] = []
        for value in values:
            for token in value.replace("|", ",").split(","):
                layer = token.strip().upper()
                if layer in {"L1", "L2", "L3"} and layer not in normalized:
                    normalized.append(layer)

        if normalized:
            return normalized
        deduped_fallback: list[str] = []
        for layer in fallback:
            upper = str(layer).strip().upper()
            if upper in {"L1", "L2", "L3"} and upper not in deduped_fallback:
                deduped_fallback.append(upper)
        return deduped_fallback

    def _policy_dimensions_for_slice(self, slice_id: str) -> set[str]:
        """Return non-software dimensions covered by explicit human policy."""
        policy_dimensions: set[str] = set()
        for constraint in self._load_merged_constraints(slice_id):
            if str(constraint.status).strip().upper() != "ACTIVE":
                continue
            dimension = _normalize_dimension(constraint.dimension, fallback="")
            if dimension not in _NON_SOFTWARE_DIMENSIONS:
                continue
            source = str(constraint.source).strip().lower()
            trace_tokens = {
                str(token).strip().lower() for token in constraint.trace if str(token).strip()
            }
            if source in {"user", "steering"}:
                policy_dimensions.add(dimension)
                continue
            if any(
                marker in trace_token
                for trace_token in trace_tokens
                for marker in (
                    "authority_input=user_answer",
                    "human_policy",
                    "policy_constraint",
                    "source=user",
                    "source=steering",
                )
            ):
                policy_dimensions.add(dimension)
        return policy_dimensions

    def _answer_spec_hint_for_event(self, event: UnderSpecEvent) -> dict[str, Any]:
        choices = [
            {"id": option, "label": option} for option in self._extract_options(event.context)
        ]
        if event.decision_type == "dependency":
            return {
                "preferred_kind": "structured_object",
                "constraints": {
                    "must_be_concrete": True,
                    "max_choices": 3,
                },
                "fields": [
                    "allowed_licenses",
                    "budget_constraints_cost_sensitivity",
                    "allowed_vendors_providers",
                    "operational_constraints",
                    "team_constraints",
                    "delivery_timeline_constraints",
                    "risk_posture",
                ],
                "field_prompts": {
                    "allowed_licenses": "Allowed licenses",
                    "budget_constraints_cost_sensitivity": "Budget constraints / cost sensitivity",
                    "allowed_vendors_providers": "Allowed vendors/providers",
                    "operational_constraints": (
                        "Operational constraints (oncall, managed vs self-hosted)"
                    ),
                    "team_constraints": "Team constraints (language/runtime, expertise)",
                    "delivery_timeline_constraints": "Delivery timeline constraints",
                    "risk_posture": "Risk posture (security/compliance baseline)",
                },
                "choices": choices,
            }
        return {
            "preferred_kind": "free_text",
            "constraints": {
                "must_be_concrete": True,
                "max_choices": 3,
            },
            "choices": choices,
        }

    def _should_emit_interactive_question(self, event: UnderSpecEvent) -> bool:
        context = event.context if isinstance(event.context, dict) else {}
        impact = self._normalize_event_impact(context)
        has_trigger = self._is_non_software_trigger(event)
        low_impact = impact in _LOW_IMPACT_LEVELS
        reversible = self._context_flag(
            context,
            keys=("reversible", "is_reversible", "easy_to_reverse"),
        )
        stdlib_or_internal = self._context_flag(
            context,
            keys=(
                "is_stdlib",
                "stdlib",
                "approved_internal",
                "approved_internal_module",
                "is_internal_module",
            ),
        )

        if impact in _IMPACT_TRIGGER_LEVELS and has_trigger:
            return True
        if has_trigger and event.dimension in _NON_SOFTWARE_DIMENSIONS:
            return True
        return not (low_impact and reversible and (stdlib_or_internal or not has_trigger))

    @staticmethod
    def _normalize_event_impact(context: dict[str, Any]) -> str:
        for key in ("impact", "impact_level", "blast_radius"):
            value = context.get(key)
            text = str(value).strip().upper()
            if text in {"LOW", "MEDIUM", "HIGH"}:
                return text
        return ""

    @staticmethod
    def _context_flag(context: dict[str, Any], *, keys: tuple[str, ...]) -> bool:
        truthy = {"1", "true", "yes", "y", "on"}
        for key in keys:
            value = context.get(key)
            if isinstance(value, bool):
                if value:
                    return True
                continue
            if isinstance(value, (int, float)) and value != 0:
                return True
            if isinstance(value, str) and value.strip().lower() in truthy:
                return True
        return False

    def _is_non_software_trigger(self, event: UnderSpecEvent) -> bool:
        if event.dimension in _NON_SOFTWARE_DIMENSIONS:
            return True
        if event.decision_type in _NON_SOFTWARE_TRIGGER_DECISION_TYPES:
            return True
        kind = str(event.kind).strip().upper()
        if kind in {"EXTERNAL_DEPENDENCY_UNKNOWN", "EXTERNAL_DEP_UNKNOWN"}:
            return True
        context = event.context if isinstance(event.context, dict) else {}
        if self._context_flag(
            context,
            keys=(
                "changes_external_dependency",
                "changes_infrastructure",
                "changes_provider",
                "changes_data_policy",
                "changes_security_posture",
                "adds_operational_burden",
                "irreversible_coupling",
            ),
        ):
            return True
        searchable_context = " ".join(
            str(context.get(key, "")).strip().lower()
            for key in (
                "reason",
                "question",
                "needed_for",
                "target",
                "risk",
                "note",
            )
        )
        return any(
            token in searchable_context
            for token in (
                "dependency",
                "provider",
                "vendor",
                "license",
                "budget",
                "cost",
                "retention",
                "privacy",
                "security",
                "oncall",
                "coupling",
            )
        )

    @staticmethod
    def _question_taxonomy_hint(event: UnderSpecEvent) -> str:
        kind = str(event.kind).strip().upper()
        if kind == "AMBIGUOUS_REQUIREMENT":
            return "SCOPE"
        if kind == "EXTERNAL_DEPENDENCY_UNKNOWN":
            return "TRADEOFF"
        return "CONSTRAINT"

    @staticmethod
    def _canonical_key_for_event(event: UnderSpecEvent) -> str:
        return f"underspec.{event.event_id}".strip(".")

    def _build_constraint_wait_monitors(
        self,
        *,
        slice_id: str,
        blocked_events: list[UnderSpecEvent],
    ) -> list[dict[str, Any]]:
        monitors: list[dict[str, Any]] = []
        for event in blocked_events:
            constraint_key = self._canonical_key_for_event(event)
            monitors.append(
                {
                    "signal_id": f"underspec:{slice_id}:{event.event_id}",
                    "kind": "constraint_present",
                    "type": "constraint_present",
                    "constraint_key": constraint_key,
                    "constraint_dir": "analysis/constraints",
                    "constraint_id": event.event_id,
                    "slice_id": slice_id,
                    "mode": "hybrid",
                    "event_triggers": [
                        "CONSTRAINT_SAVED",
                        "SLICE_MERGED",
                        "GIT_DIRTY_ADVANCED",
                    ],
                    "poll_interval_sec": 20,
                    "timeout_seconds": 3600,
                }
            )
        return monitors

    def _persist_constraints_via_planner(
        self,
        *,
        slice_id: str,
        layer: str,
        constraints: list[Constraint],
    ) -> tuple[str, set[str]]:
        if not constraints:
            return "", set()
        if self._planner is None or not hasattr(self._planner, "persist_under_spec_constraints"):
            return "", set()
        try:
            result = self._planner.persist_under_spec_constraints(
                run_id=self._run_id,
                layer=layer,
                slice_id=slice_id,
                constraints=[constraint.to_dict() for constraint in constraints],
            )
        except Exception:
            logger.warning(
                "Planner constraint persistence failed for slice=%s layer=%s",
                slice_id,
                layer,
                exc_info=True,
            )
            return "", set()
        if not isinstance(result, dict):
            return "", set()
        persisted_constraint_ids_raw = result.get("constraint_ids", [])
        persisted_constraint_ids = (
            {str(item).strip() for item in persisted_constraint_ids_raw if str(item).strip()}
            if isinstance(persisted_constraint_ids_raw, list)
            else set()
        )
        if persisted_constraint_ids and not self._planner_has_constraint_saved_callback():
            self._emit_constraint_saved_wake_events(
                slice_id=slice_id,
                layer=layer,
                constraints=constraints,
                persisted_constraint_ids=persisted_constraint_ids,
            )
        return str(result.get("constraints_path", "")).strip(), persisted_constraint_ids

    def _load_merged_constraints(self, slice_id: str) -> list[Any]:
        """Load constraints from merged system + slice view with safe fallback."""
        try:
            return self._constraints_adapter.load_merged(slice_id)
        except Exception:
            logger.warning(
                "Adapter merged load failed for slice '%s'; using store fallback",
                slice_id,
                exc_info=True,
            )
            return self._store.load_merged(slice_id)

    def _find_covering(
        self,
        slice_id: str,
        events: list[UnderSpecEvent],
    ) -> tuple[list[UnderSpecEvent], list[UnderSpecEvent]]:
        constraints = self._load_merged_constraints(slice_id)
        active_constraint_ids = {
            str(constraint.constraint_id).strip()
            for constraint in constraints
            if str(constraint.constraint_id).strip()
            and str(getattr(constraint, "status", "ACTIVE")).strip().upper() == "ACTIVE"
        }

        covered: list[UnderSpecEvent] = []
        uncovered: list[UnderSpecEvent] = []
        for event in events:
            if event.event_id in active_constraint_ids:
                covered.append(event)
            else:
                uncovered.append(event)
        return covered, uncovered

    def _planner_has_constraint_saved_callback(self) -> bool:
        adapter = getattr(self._planner, "_constraints_adapter", None)
        callback = getattr(adapter, "_on_constraint_saved", None)
        return callable(callback)

    def _emit_constraint_saved_wake_events(
        self,
        *,
        slice_id: str,
        layer: str,
        constraints: list[Constraint],
        persisted_constraint_ids: set[str],
    ) -> None:
        try:
            from spec_manager.orchestration.coordination.wake_queue import WakeEvent, WakeQueue
        except Exception:
            logger.warning(
                "Wake queue import failed while emitting fallback constraint_saved wake events",
                exc_info=True,
            )
            return

        if not persisted_constraint_ids:
            return

        canonical_by_id: dict[str, str] = {}
        for constraint in constraints:
            constraint_id = str(constraint.constraint_id).strip()
            if not constraint_id:
                continue
            canonical_by_id[constraint_id] = self._canonical_key_for_constraint(constraint)

        coordination_dir = self._workspace / ".pdd_runs" / self._run_id / "coordination"
        try:
            queue = WakeQueue(coordination_dir)
            for constraint_id in sorted(persisted_constraint_ids):
                canonical_key = canonical_by_id.get(constraint_id, f"underspec.{constraint_id}")
                queue.enqueue(
                    WakeEvent(
                        signal_id=f"underspec:{slice_id}:{constraint_id}",
                        slice_id=slice_id,
                        layer=str(layer),
                        reason="constraint_saved_fallback",
                        artifact_key=f"constraint:{constraint_id}",
                        wake_payload={
                            "constraint_id": constraint_id,
                            "canonical_key": canonical_key,
                            "source_slice_id": slice_id,
                        },
                    )
                )
        except Exception:
            logger.warning(
                "Failed to emit fallback constraint_saved wake events for slice '%s'",
                slice_id,
                exc_info=True,
            )

    @staticmethod
    def _canonical_key_for_constraint(constraint: Constraint) -> str:
        for token in constraint.trace:
            token_text = str(token).strip()
            if token_text.startswith("canonical_key="):
                return token_text.split("=", 1)[1].strip()
        return f"underspec.{constraint.constraint_id}"

    @staticmethod
    def _constraint_event_id(constraint: Constraint) -> str:
        for token in constraint.trace:
            token_text = str(token).strip()
            if token_text.startswith("resolves_event_id="):
                return token_text.split("=", 1)[1].strip()
        return str(constraint.constraint_id).strip()

    def _build_refinement_candidates(
        self,
        *,
        slice_id: str,
        covered_events: list[UnderSpecEvent],
    ) -> list[UnderSpecEvent]:
        if self._mode != "auto" or self._planner is None:
            return []
        if not covered_events:
            return []

        constraints = self._load_merged_constraints(slice_id)
        active_constraints = {
            constraint.constraint_id: constraint
            for constraint in constraints
            if str(constraint.constraint_id).strip()
            and str(constraint.status).strip().upper() == "ACTIVE"
        }

        refinement_candidates: list[UnderSpecEvent] = []
        for event in covered_events:
            active = active_constraints.get(event.event_id)
            if active is None:
                continue
            refined_event = UnderSpecEvent.from_dict(event.to_dict())
            ctx = dict(refined_event.context or {})
            ctx["refinement_candidate"] = {
                "existing_constraint_id": active.constraint_id,
                "existing_question": active.question,
                "existing_answer": active.answer,
                "existing_trace": list(active.trace),
                "existing_supersedes": list(active.supersedes),
            }
            refined_event.context = ctx
            refinement_candidates.append(refined_event)
        return refinement_candidates

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
