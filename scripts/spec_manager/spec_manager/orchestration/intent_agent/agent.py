"""IntentAgentOrchestrator — deterministic event loop for user interaction.

Per response2.md Section 1.2: The orchestrator is deterministic. It handles
user messages + internal question signals + store-change signals. It maintains
queue ordering, deduplication, staleness, batching. It calls LLM strategies
for interpretation/rewriting only. It persists session state and event log.

Per response2.md Section 1.1: Intent Agent is the ONLY user-facing interface.
Planner is the single constraint/decision authority. This boundary is
non-negotiable.

Event sources:
    1. User messages — text input from the user
    2. UserQuestionSignals — from Planner, UnderSpec, PromotionLoop, Intent Agent
    3. PlannerUpdates — constraint_saved, decision_recorded events

Per response2.md Section 1.4: Resumption is deterministic:
    1. Load session_state.json
    2. Read new UserQuestionSignals since watermark
    3. Read new PlannerUpdates since watermark
    4. Recompute queue ordering and staleness
    5. Present the next question
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.orchestration.intent_agent.answer_translation import (
    AnswerTranslateStrategy,
    AnswerTranslation,
    FollowupQuestionDraft,
    RecursionBudget,
)
from spec_manager.orchestration.intent_agent.quality_gate import (
    QualityCheckCandidate,
    QualityCheckRecord,
    QualityValidatorStrategy,
    QuestionDraftStrategy,
    QuestionRepairStrategy,
    enforce_quality_gate,
)
from spec_manager.orchestration.intent_agent.queue import (
    AnswerSpec,
    QualityGateStatus,
    QuestionBlockers,
    QuestionItem,
    QuestionOrigin,
    QuestionQueue,
    ReassessPlannerSignal,
    ReassessQuestionKeySignal,
    UserPrompt,
)
from spec_manager.orchestration.intent_agent.signals import (
    PlannerUpdateStore,
    UserQuestionSignal,
    UserQuestionSignalStore,
)
from spec_manager.orchestration.intent_agent.skeleton import (
    SkeletonSynthesisStrategy,
    render_intent_snapshot,
    render_skeleton,
    should_produce_skeleton,
)
from spec_manager.orchestration.intent_agent.state import (
    AnswerProvenance,
    ConceptMapEntry,
    FrameAssumption,
    IntentEventLog,
    IntentSessionState,
    ResumeProgressSummaryProjection,
    save_answer,
)
from spec_manager.orchestration.intent_agent.taxonomy import (
    QuestionTaxonomy,
    classify_question,
    classify_scope,
    infer_constraint_dimensions_with_key,
    is_prohibited,
    is_vague_user_input,
    normalize_constraint_dimensions,
    normalize_taxonomy_type,
    normalize_user_facing_taxonomy,
    reframe_to_user_valid,
)

logger = logging.getLogger(__name__)

_VALID_REDEFINITION_QUESTION_TYPES = frozenset({"VALIDATION", "SCOPE", "TRADEOFF"})
_VALID_ALIGNMENT_REDEFINITION_QUESTION_TYPES = frozenset({"SCOPE", "TRADEOFF"})
_REDEFINITION_UPDATE_SOURCES = frozenset({"PLANNER"})
_REDEFINITION_CHECK_WORK_ITEM = "REDEFINITION_CHECK"
_ALIGNMENT_INVARIANT_PREFIX = "Invariant checksum: "
_DEFAULT_REDEFINITION_CHOICES = (
    ("adopt_new", "Yes, adopt the new restatement"),
    ("keep_original", "No, keep the original framing"),
    ("partial", "Partially adopt and specify exactly what should change"),
)
_CANONICAL_ORIGIN_KINDS = frozenset(
    {"INTENT_AGENT", "PLANNER", "UNDER_SPEC", "PROMOTION_LOOP", "PDD_LIFECYCLE", "SLICE_AGENT"}
)
_CANONICAL_KEY_INVALID_CHARS_RE = re.compile(r"[^a-z0-9._-]+")
_CANONICAL_KEY_DOT_RUN_RE = re.compile(r"\.+")
_CANONICAL_KEY_UNDERSCORE_RUN_RE = re.compile(r"_+")
_CANONICAL_KEY_TOKEN_RE = re.compile(r"[a-z0-9]+")
_AUTO_RESOLUTION_MIN_CONFIDENCE = 0.8


# ---------------------------------------------------------------------------
# LLM Strategy protocols (pluggable)
# ---------------------------------------------------------------------------


# TODO [R2-1.2]: Implement IntentFrameStrategy
#   - LLM strategy to update problem frame from user text
#   - Input: current problem_frame, user message text, concept_map
#   - Output: updated problem_frame (restatement, goals, non_goals,
#     scope: {in, out}, success_metrics, risk_flags, frame_assumptions)
#   - Must NOT produce constraints — only user-facing framing metadata
class IntentFrameStrategy:
    """LLM strategy to update problem frame from user text."""

    def update_frame(
        self,
        current_frame: dict[str, Any],
        user_text: str,
        concept_map: dict[str, Any] | None = None,
        *,
        run_agent: Any = None,
    ) -> dict[str, Any]:
        """Update problem frame from user text."""
        if run_agent is None:
            return current_frame

        concept_text = json.dumps(concept_map) if concept_map else "{}"
        prompt = (
            "You are updating a problem frame based on new user input. "
            "Produce ONLY user-facing framing metadata — no constraints.\n\n"
            f"CURRENT FRAME:\n{json.dumps(current_frame, indent=2)}\n\n"
            f"USER INPUT:\n{user_text}\n\n"
            f"CONCEPT MAP:\n{concept_text}\n\n"
            "Return a JSON object with these fields (keep existing values where "
            "the user input does not change them):\n"
            "{\n"
            '  "current_restatement": "...",\n'
            '  "goals": ["..."],\n'
            '  "non_goals": ["..."],\n'
            '  "scope": {"in": ["..."], "out": ["..."]},\n'
            '  "success_metrics": ["..."],\n'
            '  "risk_flags": ["..."],\n'
            '  "frame_assumptions": [{"text": "...", "status": "HYPOTHESIS", "source": "user"}]\n'
            "}\n"
            "Output ONLY the JSON object."
        )

        try:
            raw = run_agent(prompt)
            payload = _extract_json_payload(raw)
            parsed = json.loads(payload)
        except Exception:
            logger.warning(
                "IntentFrameStrategy: failed to parse LLM response, returning current frame."
            )
            return current_frame

        # Merge parsed fields into current_frame (only override present keys).
        merged = dict(current_frame)
        for key in (
            "current_restatement",
            "goals",
            "non_goals",
            "scope",
            "success_metrics",
            "risk_flags",
            "frame_assumptions",
        ):
            if key in parsed:
                merged[key] = parsed[key]
        return merged


# TODO [R2-1.2]: Implement ConceptMapStrategy
#   - LLM strategy to maintain mapping between user terms and normalized concepts
#   - Input: current concept_map, user message text
#   - Output: updated concept_map (user_terms, normalized_terms,
#     user_introduced_terms)
#   - user_introduced_terms tracks technical vocabulary the user has used
#     (exception for quality gate rule 1)
class ConceptMapStrategy:
    """LLM strategy to maintain user↔system term mapping."""

    def update_map(
        self,
        current_map: dict[str, Any],
        user_text: str,
        *,
        run_agent: Any = None,
    ) -> dict[str, Any]:
        """Update concept map from user text."""
        if run_agent is None:
            return current_map

        prompt = (
            "You are maintaining a concept map that tracks user terminology. "
            "Identify any NEW terms the user has introduced and map them to "
            "normalized equivalents.\n\n"
            f"CURRENT CONCEPT MAP:\n{json.dumps(current_map, indent=2)}\n\n"
            f"USER TEXT:\n{user_text}\n\n"
            "Return a JSON object with:\n"
            "{\n"
            '  "new_terms": {"<user_term>": {"maps_to": ["<normalized>"], "'
            '"confidence": 0.0-1.0}},\n'
            '  "user_introduced_terms": ["<technical terms the user used>"]\n'
            "}\n"
            "Only include genuinely NEW terms not already in the concept map. "
            "Output ONLY the JSON object."
        )

        try:
            raw = run_agent(prompt)
            payload = _extract_json_payload(raw)
            parsed = json.loads(payload)
        except Exception:
            logger.warning(
                "ConceptMapStrategy: failed to parse LLM response, returning current map."
            )
            return current_map

        # Merge new terms into current map.
        merged = dict(current_map)
        existing_user_terms = dict(merged.get("user_terms", {}))
        existing_normalized = dict(merged.get("normalized_terms", {}))
        existing_introduced = list(merged.get("user_introduced_terms", []))

        new_terms = parsed.get("new_terms", {})
        for term, info in new_terms.items():
            if term not in existing_user_terms:
                existing_user_terms[term] = info
                # Update reverse mapping.
                for norm in info.get("maps_to", []):
                    if norm not in existing_normalized:
                        existing_normalized[norm] = []
                    if term not in existing_normalized[norm]:
                        existing_normalized[norm].append(term)

        new_introduced = parsed.get("user_introduced_terms", [])
        for t in new_introduced:
            if t not in existing_introduced:
                existing_introduced.append(t)

        merged["user_terms"] = existing_user_terms
        merged["normalized_terms"] = existing_normalized
        merged["user_introduced_terms"] = existing_introduced
        return merged


# TODO [R2-2.3]: Implement QueueReassessStrategy
#   - LLM strategy for the LLM pass in queue reassessment
#   - Input: remaining OPEN questions after mechanical pass,
#     updated frame, new authoritative store references
#   - Output: per-question action (KEEP | STALE | SUPERSEDED | REWORD | DISMISSED)
#   - Only called for questions where ambiguity remains after mechanical pass
class QueueReassessStrategy:
    """LLM strategy for queue reassessment after Planner writes."""

    def reassess(
        self,
        open_questions: list[dict[str, Any]],
        problem_frame: dict[str, Any],
        new_constraints: list[dict[str, Any]],
        *,
        run_agent: Any = None,
    ) -> list[dict[str, Any]]:
        """Reassess open questions against updated state.

        Returns list of {question_id, action, reason, replacement?}.
        """
        if run_agent is None:
            return [
                {"question_id": q["question_id"], "action": "KEEP", "reason": "no LLM"}
                for q in open_questions
            ]

        questions_text = json.dumps(open_questions, indent=2)
        frame_text = json.dumps(problem_frame, indent=2)
        constraints_text = json.dumps(new_constraints, indent=2)

        prompt = (
            "You are reassessing open questions after new planner updates. "
            "For each question, decide: KEEP, STALE, SUPERSEDED, REWORD, or DISMISSED.\n\n"
            f"OPEN QUESTIONS:\n{questions_text}\n\n"
            f"UPDATED PROBLEM FRAME:\n{frame_text}\n\n"
            f"NEW CONSTRAINTS:\n{constraints_text}\n\n"
            "Return a JSON array of objects, one per question:\n"
            '[{"question_id": "...", "action": "KEEP|STALE|SUPERSEDED|REWORD|DISMISSED", '
            '"reason": "brief reason"}]\n'
            "Output ONLY the JSON array."
        )

        try:
            raw = run_agent(prompt)
            payload = _extract_json_payload(raw)
            parsed = json.loads(payload)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            logger.warning(
                "QueueReassessStrategy: failed to parse LLM response, returning all KEEP."
            )

        return [
            {"question_id": q["question_id"], "action": "KEEP", "reason": "parse failure"}
            for q in open_questions
        ]


# ---------------------------------------------------------------------------
# IntentAgentOrchestrator
# ---------------------------------------------------------------------------


class IntentAgentOrchestrator:
    """Deterministic event loop for user interaction.

    Per response2.md Section 1.2: Handles user messages, internal signals,
    and store-change signals. Maintains queue ordering, dedup, staleness,
    batching. Calls LLM strategies for interpretation only.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        on_translation_saved: Callable[[AnswerTranslation], Any],
        mode: str = "interactive",
        run_agent: Any = None,
        on_planner_signal: Any = None,
        intent_frame_strategy: IntentFrameStrategy | None = None,
        concept_map_strategy: ConceptMapStrategy | None = None,
        question_draft_strategy: QuestionDraftStrategy | None = None,
        quality_validator: QualityValidatorStrategy | None = None,
        question_repairer: QuestionRepairStrategy | None = None,
        answer_translate_strategy: AnswerTranslateStrategy | None = None,
        queue_reassess_strategy: QueueReassessStrategy | None = None,
        skeleton_synthesis_strategy: SkeletonSynthesisStrategy | None = None,
    ) -> None:
        if not callable(on_translation_saved):
            raise TypeError(
                "IntentAgentOrchestrator requires a callable on_translation_saved planner hook"
            )
        self._run_dir = run_dir
        self._mode = mode
        self._on_translation_saved = on_translation_saved
        self._on_planner_signal = on_planner_signal
        self._run_agent = run_agent
        self._intent_frame = intent_frame_strategy
        self._concept_map = concept_map_strategy
        self._question_draft = question_draft_strategy
        self._quality_validator = quality_validator
        self._question_repairer = question_repairer
        self._answer_translate = answer_translate_strategy
        self._queue_reassess = queue_reassess_strategy

        # State is loaded lazily or on resume
        self._state: IntentSessionState | None = None
        self._queue: QuestionQueue | None = None
        self._signal_store: UserQuestionSignalStore | None = None
        self._planner_store: PlannerUpdateStore | None = None
        self._event_log: IntentEventLog | None = None
        self._skeleton_strategy: SkeletonSynthesisStrategy = (
            skeleton_synthesis_strategy or SkeletonSynthesisStrategy()
        )

    def _ensure_initialized(self) -> None:
        """Ensure state, queue, and stores are initialized."""
        if self._state is None or self._queue is None:
            self.resume()

    def _mark_unaskable(
        self, question_id: str, source: str, reason: str, details: dict[str, Any] | None = None
    ) -> None:
        if self._state is not None:
            queue_state = self._state.question_queue_state
            bucket = queue_state._passthrough_fields.setdefault("unaskable_question_ids", [])
            if not isinstance(bucket, list):
                bucket = []
                queue_state._passthrough_fields["unaskable_question_ids"] = bucket
            if question_id not in bucket:
                bucket.append(question_id)

        if self._event_log is not None:
            payload = {
                "question_id": question_id,
                "source": source,
                "reason": reason,
            }
            if details is not None:
                payload["details"] = details
            self._event_log.append("question_unaskable", payload)

    def _emit_followup_quality_reformulation(
        self,
        parent_question_id: str,
        draft: FollowupQuestionDraft,
        records: list[QualityCheckRecord],
        *,
        reason_override: str = "",
    ) -> None:
        """Emit a planner-directed signal for failed follow-up reformulation."""
        if self._state is None:
            return

        canonical_hint = self._coerce_str(
            draft.canonical_key_hint,
            f"intent.followup.{parent_question_id}",
        )
        canonical_key = self._normalize_canonical_key(
            canonical_hint,
            taxonomy_type=draft.taxonomy_type,
            text=draft.text,
            scope_kind=classify_scope(draft.text).value,
        )

        reason = self._coerce_str(
            reason_override or (records[-1].reason if records else "quality gate failed"),
            "quality gate failed",
        )
        question_type = self._coerce_str(
            draft.taxonomy_type,
            "SCOPE",
        )
        if question_type not in {"VALIDATION", "SCOPE", "TRADEOFF"}:
            question_type = "SCOPE"

        payload: dict[str, Any] = {
            "signal_type": "FOLLOWUP_QUALITY_GATE_FAILED",
            "source": "INTENT_AGENT",
            "target": "PLANNER",
            "run_id": self._state.run_id,
            "session_id": self._state.session_id,
            "created_at": datetime.now(UTC).isoformat(),
            "canonical_key": canonical_key,
            "question_type": question_type,
            "question_text": self._coerce_str(draft.text, "Reformulate follow-up question."),
            "reason": reason,
            "details": {
                "parent_question_id": parent_question_id,
                "taxonomy_type": draft.taxonomy_type,
                "scenario": draft.scenario,
                "attempts": len(records),
                "failure_reason": reason,
            },
        }

        if self._on_planner_signal is None:
            raise RuntimeError(
                "Failed follow-up question cannot be routed to Planner: "
                "on_planner_signal callback is required"
            )

        try:
            self._on_planner_signal(payload)
        except Exception as exc:
            raise RuntimeError(
                "Failed follow-up question could not be routed to Planner "
                f"(parent_question_id={parent_question_id})"
            ) from exc

    def _emit_ingest_quality_reformulation(
        self,
        *,
        signal: UserQuestionSignal,
        question_id: str,
        canonical_key: str,
        taxonomy_type: str,
        question_text: str,
        scenario: str,
        reason: str,
        attempts: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Emit planner-directed escalation for unaskable ingest questions."""
        if self._state is None:
            return

        question_type = self._coerce_str(taxonomy_type, "CONSTRAINT")
        question_type = normalize_user_facing_taxonomy(question_type)
        payload: dict[str, Any] = {
            "signal_type": "INGEST_QUALITY_GATE_FAILED",
            "source": "INTENT_AGENT",
            "target": "PLANNER",
            "run_id": self._state.run_id,
            "session_id": self._state.session_id,
            "created_at": datetime.now(UTC).isoformat(),
            "question_id": question_id,
            "signal_id": signal.uq_id,
            "canonical_key": self._normalize_canonical_key(
                canonical_key,
                taxonomy_type=question_type,
                text=question_text,
                scope_kind=classify_scope(question_text).value,
            ),
            "question_type": question_type,
            "question_text": self._coerce_str(question_text, signal.question.text),
            "reason": self._coerce_str(reason, "quality gate failed"),
            "details": {
                "taxonomy_type": question_type,
                "scenario": self._coerce_str(scenario),
                "attempts": max(0, int(attempts)),
                "source_kind": self._coerce_str(signal.source.kind, "UNKNOWN"),
            },
        }
        if details:
            payload["details"].update(details)

        if self._on_planner_signal is None:
            logger.debug(
                "No planner signal callback configured; dropped ingest quality signal "
                "for signal_id=%s",
                signal.uq_id,
            )
            return

        try:
            self._on_planner_signal(payload)
        except Exception:
            logger.warning(
                "on_planner_signal callback failed for ingest quality signal (signal_id=%s)",
                signal.uq_id,
                exc_info=True,
            )

    def _emit_quality_gate_reformulation(
        self,
        *,
        question_id: str,
        canonical_key: str,
        taxonomy_type: str,
        question_text: str,
        source: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Escalate an UNASKABLE quality-gate failure to Planner."""
        if self._state is None:
            return

        question_type = normalize_user_facing_taxonomy(self._coerce_str(taxonomy_type, "SCOPE"))
        payload: dict[str, Any] = {
            "signal_type": "QUESTION_QUALITY_GATE_FAILED",
            "source": "INTENT_AGENT",
            "target": "PLANNER",
            "run_id": self._state.run_id,
            "session_id": self._state.session_id,
            "created_at": datetime.now(UTC).isoformat(),
            "question_id": self._coerce_str(question_id),
            "canonical_key": self._normalize_canonical_key(
                canonical_key,
                taxonomy_type=question_type,
                text=question_text,
                scope_kind=classify_scope(question_text).value,
            ),
            "question_type": question_type,
            "question_text": self._coerce_str(question_text),
            "reason": self._coerce_str(reason, "quality gate failed"),
            "details": {
                "unaskable_source": self._coerce_str(source, "intent_agent"),
                "failure_reason": self._coerce_str(reason, "quality gate failed"),
                "escalation_path": "planner_reformulation",
            },
        }
        if details:
            payload["details"].update(details)

        if self._on_planner_signal is None:
            logger.debug(
                "No planner signal callback configured; dropped quality failure signal "
                "for question_id=%s",
                question_id,
            )
            return

        try:
            self._on_planner_signal(payload)
        except Exception:
            logger.warning(
                "on_planner_signal callback failed for quality failure signal (question_id=%s)",
                question_id,
                exc_info=True,
            )

    def _coerce_str(self, value: Any, default: str = "") -> str:
        if not isinstance(value, str):
            return default
        text = value.strip()
        return text or default

    def _canonical_origin_kind(self, source_kind: str, *, field_name: str) -> str:
        normalized = self._coerce_str(source_kind).upper()
        if not normalized:
            raise ValueError(f"{field_name} must be a non-empty source kind")
        if normalized not in _CANONICAL_ORIGIN_KINDS:
            raise ValueError(
                f"{field_name} source kind {source_kind!r} is invalid; "
                f"expected one of {sorted(_CANONICAL_ORIGIN_KINDS)}"
            )
        return normalized

    def _coerce_str_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [item.strip() for item in (str(item).strip() for item in value) if item.strip()]
        return []

    def _coerce_float(self, value: Any, default: float = 0.0) -> float:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return default
        return default

    def _serialize_frame_assumptions(self) -> list[dict[str, str]]:
        if self._state is None:
            return []
        return [
            {
                "text": assumption.text,
                "status": assumption.status,
                "source": assumption.source,
                "created_at": assumption.created_at,
            }
            for assumption in self._state.problem_frame.frame_assumptions
            if assumption.text.strip()
        ]

    def _normalize_frame_assumptions(self, raw_assumptions: Any) -> list[FrameAssumption]:
        if not isinstance(raw_assumptions, list):
            return []

        valid_statuses = {"HYPOTHESIS", "CONFIRMED", "REJECTED"}
        valid_sources = {"user", "intent_agent"}
        now_iso = datetime.now(UTC).isoformat()
        existing_by_text: dict[str, FrameAssumption] = {}
        if self._state is not None:
            existing_by_text = {
                item.text.strip().lower(): item
                for item in self._state.problem_frame.frame_assumptions
                if item.text.strip()
            }

        normalized: list[FrameAssumption] = []
        seen: set[str] = set()
        for raw_assumption in raw_assumptions:
            if isinstance(raw_assumption, dict):
                text = self._coerce_str(raw_assumption.get("text"))
                raw_status = self._coerce_str(raw_assumption.get("status"), "HYPOTHESIS").upper()
                raw_source = self._coerce_str(raw_assumption.get("source"), "intent_agent").lower()
                created_at = self._coerce_str(raw_assumption.get("created_at"))
            else:
                text = self._coerce_str(raw_assumption)
                raw_status = "HYPOTHESIS"
                raw_source = "intent_agent"
                created_at = ""

            if not text:
                continue
            canonical_text = text.lower()
            if canonical_text in seen:
                continue
            seen.add(canonical_text)

            status = raw_status if raw_status in valid_statuses else "HYPOTHESIS"
            source = raw_source if raw_source in valid_sources else "intent_agent"
            if not created_at:
                existing = existing_by_text.get(canonical_text)
                created_at = existing.created_at if existing is not None else now_iso

            normalized.append(
                FrameAssumption(
                    text=text,
                    status=status,
                    source=source,
                    created_at=created_at,
                )
            )

        return normalized

    def _normalize_concept_user_terms(self, raw_terms: Any) -> dict[str, ConceptMapEntry]:
        if not isinstance(raw_terms, dict):
            return {}

        normalized: dict[str, ConceptMapEntry] = {}
        for raw_term, raw_entry in raw_terms.items():
            term = self._coerce_str(raw_term)
            if not term or not isinstance(raw_entry, dict):
                continue
            maps_to = self._dedupe_ordered(self._coerce_str_list(raw_entry.get("maps_to", [])))
            confidence = self._coerce_float(raw_entry.get("confidence", 0.0), 0.0)
            confidence = min(1.0, max(0.0, confidence))
            normalized[term] = ConceptMapEntry(
                maps_to=maps_to,
                confidence=confidence,
            )
        return normalized

    def _normalize_concept_normalized_terms(self, raw_terms: Any) -> dict[str, list[str]]:
        if not isinstance(raw_terms, dict):
            return {}
        normalized_terms: dict[str, list[str]] = {}
        for raw_key, raw_values in raw_terms.items():
            key = self._coerce_str(raw_key)
            if not key:
                continue
            normalized_terms[key] = self._dedupe_ordered(self._coerce_str_list(raw_values))
        return normalized_terms

    def _default_vague_intent_choices(self) -> list[dict[str, str]]:
        return [
            {"id": "a", "label": "Order routing + execution"},
            {"id": "b", "label": "Portfolio + risk + reporting"},
            {"id": "c", "label": "Treasury + settlement + reconciliation"},
            {"id": "d", "label": "Another variant (describe in 1-2 sentences)"},
        ]

    def _extract_choice_specs_from_prompt(self, prompt_text: str) -> list[dict[str, str]]:
        line_pattern = re.compile(r"^\s*(?:[-*]\s*)?\(?([A-Za-z])\)?[.)]\s+(.+?)\s*$")
        choices: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for line in self._coerce_str(prompt_text).splitlines():
            match = line_pattern.match(line)
            if match is None:
                continue
            choice_id = match.group(1).lower()
            label = self._coerce_str(match.group(2))
            if not label or choice_id in seen_ids:
                continue
            seen_ids.add(choice_id)
            choices.append({"id": choice_id, "label": label})
        return choices

    def _ensure_choice_prompt_text(
        self,
        prompt_text: str,
        choices: list[dict[str, str]],
    ) -> str:
        base_prompt = self._coerce_str(prompt_text, "Which is closest to what you mean right now?")
        if self._extract_choice_specs_from_prompt(base_prompt):
            return base_prompt
        option_lines = "\n".join(
            f"({chr(ord('A') + index)}) {choice['label']}" for index, choice in enumerate(choices)
        )
        return f"{base_prompt}\n{option_lines}"

    def _candidate_unknown_specs_from_message(self, text: str) -> list[dict[str, str]]:
        if self._state is None:
            return []
        unknown_specs: list[dict[str, str]] = []
        hypothesis_assumptions = [
            assumption
            for assumption in self._state.problem_frame.frame_assumptions
            if assumption.status == "HYPOTHESIS" and assumption.text.strip()
        ]
        for assumption in hypothesis_assumptions[:3]:
            tokens = _CANONICAL_KEY_TOKEN_RE.findall(assumption.text.lower())
            slug = "_".join(tokens[:6]) if tokens else f"assumption_{len(unknown_specs) + 1}"
            unknown_specs.append(
                {
                    "question_text": (
                        "Should we treat this current assumption as true for your request: "
                        f"{assumption.text}"
                    ),
                    "taxonomy_hint": "VALIDATION",
                    "canonical_key_hint": f"intent.user_message.assumption.{slug}",
                    "assumption_text": assumption.text,
                }
            )
        if unknown_specs:
            return unknown_specs

        if is_vague_user_input(text):
            return []
        return [
            {
                "question_text": (
                    "Which workflow should we treat as the primary path for this request?"
                ),
                "taxonomy_hint": "INTENT",
                "canonical_key_hint": "intent.user_message.primary_workflow",
                "assumption_text": "",
            }
        ]

    def _build_user_message_unknown_signal(
        self,
        *,
        user_text: str,
        question_text: str,
        taxonomy_hint: str,
        canonical_key_hint: str,
        assumption_text: str = "",
    ) -> Any:
        assert self._state is not None
        now_iso = datetime.now(UTC).isoformat()
        payload: dict[str, Any] = {
            "source": "user_message",
            "user_text": user_text,
            "text": question_text,
            "domain_description": self._state.problem_frame.current_restatement,
        }
        if assumption_text:
            payload["failure_mode"] = (
                f"The current frame may be wrong if assumption '{assumption_text}' is incorrect."
            )
            payload["frame_assumption"] = assumption_text

        return SimpleNamespace(
            uq_id=f"uq_{uuid.uuid4().hex[:12]}",
            created_at=now_iso,
            source=SimpleNamespace(
                kind="INTENT_AGENT",
                trace_id="user_message_unknown_extraction",
                slice_id="",
                layer="INTENT",
                signal_id="",
            ),
            question=SimpleNamespace(
                text=question_text,
                taxonomy_hint=taxonomy_hint,
                canonical_key_hint=canonical_key_hint,
                answer_spec_hint={},
            ),
            context=SimpleNamespace(
                blocking=SimpleNamespace(severity="INFO", blocked_slices=[]),
            ),
            payload=payload,
        )

    def _ingest_user_message_candidate_unknowns(self, text: str) -> None:
        if self._state is None or self._queue is None:
            return
        if self._run_agent is None:
            return
        unknown_specs = self._candidate_unknown_specs_from_message(text)
        for unknown_spec in unknown_specs:
            signal = self._build_user_message_unknown_signal(
                user_text=text,
                question_text=self._coerce_str(unknown_spec.get("question_text")),
                taxonomy_hint=self._coerce_str(unknown_spec.get("taxonomy_hint"), "INTENT"),
                canonical_key_hint=self._coerce_str(
                    unknown_spec.get("canonical_key_hint"),
                    "intent.user_message.unknown",
                ),
                assumption_text=self._coerce_str(unknown_spec.get("assumption_text")),
            )
            try:
                self.ingest_signal(
                    signal,
                    update_signal_watermark=False,
                    update_skeleton=False,
                )
            except Exception:
                logger.warning(
                    "Failed ingesting user-message candidate unknown signal.",
                    exc_info=True,
                )

    def _is_ready_for_skeleton(self) -> bool:
        if self._state is None or self._queue is None:
            return False
        self._refresh_question_queue_state()
        pf = self._state.problem_frame
        frame_dict = {
            "current_restatement": pf.current_restatement,
            "goals": list(pf.goals),
            "non_goals": list(pf.non_goals),
            "scope": {
                "in": list(pf.scope.get("in", [])),
                "out": list(pf.scope.get("out", [])),
            },
            "success_metrics": list(pf.success_metrics),
            "risk_flags": list(pf.risk_flags),
            "frame_assumptions": self._serialize_frame_assumptions(),
        }
        return should_produce_skeleton(frame_dict, self._state.question_queue_state.to_dict())

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "y", "on"}
        return False

    @staticmethod
    def _coerce_optional_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "y", "on"}:
                return True
            if lowered in {"false", "0", "no", "n", "off"}:
                return False
        return None

    def _normalize_canonical_key(
        self,
        value: Any,
        *,
        taxonomy_type: str = "",
        text: str = "",
        scope_kind: str = "",
    ) -> str:
        """Normalize/validate canonical-key hints into stable dedup keys."""
        resolved_scope_kind = self._coerce_str(scope_kind).upper()
        if resolved_scope_kind not in {"SYSTEM_WIDE", "FEATURE_SPECIFIC"}:
            resolved_scope_kind = classify_scope(text).value if text else "FEATURE_SPECIFIC"
        scope_token = resolved_scope_kind.lower()

        normalized = self._coerce_str(value).lower()
        if normalized:
            normalized = normalized.replace("::", ".").replace("/", ".").replace(" ", "_")
            normalized = _CANONICAL_KEY_INVALID_CHARS_RE.sub("_", normalized)
            normalized = _CANONICAL_KEY_UNDERSCORE_RUN_RE.sub("_", normalized)
            normalized = _CANONICAL_KEY_DOT_RUN_RE.sub(".", normalized)
            normalized = normalized.strip("._-")
            if normalized:
                key_parts = [part for part in normalized.split(".") if part]
                if not key_parts:
                    key_parts = ["intent", scope_token]
                elif key_parts[0] != "intent":
                    key_parts = ["intent", scope_token, *key_parts]
                elif len(key_parts) == 1:
                    key_parts.extend([scope_token])
                elif key_parts[1] in {"system_wide", "feature_specific"}:
                    key_parts[1] = scope_token
                else:
                    key_parts.insert(1, scope_token)
                return ".".join(key_parts)

        taxonomy_key = normalize_user_facing_taxonomy(taxonomy_type).lower()
        if taxonomy_key not in {"intent", "constraint", "tradeoff", "scope", "validation"}:
            taxonomy_key = "constraint"
        token_source = self._coerce_str(text).lower()
        tokens = _CANONICAL_KEY_TOKEN_RE.findall(token_source)
        slug = "_".join(tokens[:6]) if tokens else "question"
        return f"intent.{scope_token}.{taxonomy_key}.{slug}"

    def _normalize_canonical_key_candidate(self, value: Any) -> str:
        normalized = self._coerce_str(value).lower()
        if not normalized:
            return ""
        normalized = normalized.replace("::", ".").replace("/", ".").replace(" ", "_")
        normalized = _CANONICAL_KEY_INVALID_CHARS_RE.sub("_", normalized)
        normalized = _CANONICAL_KEY_UNDERSCORE_RUN_RE.sub("_", normalized)
        normalized = _CANONICAL_KEY_DOT_RUN_RE.sub(".", normalized)
        return normalized.strip("._-")

    def _record_new_blocking_arrival(self, question_id: str) -> None:
        if self._state is None:
            return
        normalized_question_id = self._coerce_str(question_id)
        if not normalized_question_id:
            return
        queue_state = self._state.question_queue_state
        arrivals = queue_state._passthrough_fields.setdefault(
            "new_blocking_arrival_question_ids", []
        )
        if not isinstance(arrivals, list):
            arrivals = []
            queue_state._passthrough_fields["new_blocking_arrival_question_ids"] = arrivals
        if normalized_question_id not in arrivals:
            arrivals.append(normalized_question_id)

    def _consume_new_blocking_arrivals(self) -> list[str]:
        if self._state is None:
            return []
        queue_state = self._state.question_queue_state
        arrivals = self._coerce_str_list(
            queue_state._passthrough_fields.get("new_blocking_arrival_question_ids", []),
        )
        queue_state._passthrough_fields["new_blocking_arrival_question_ids"] = []
        return arrivals

    def _record_presented_action(
        self,
        action: dict[str, Any],
        *,
        suppressed: bool,
        mode: str,
    ) -> None:
        if self._event_log is None:
            return
        action_kind = self._coerce_str(action.get("action"))
        if action_kind not in {"ask", "ask_batch"}:
            return
        question_ids = self._coerce_str_list(action.get("question_ids"))
        if not question_ids:
            fallback_id = self._coerce_str(action.get("question_id"))
            if fallback_id:
                question_ids = [fallback_id]
        self._event_log.append(
            "question_presented",
            {
                "action": action_kind,
                "question_ids": question_ids,
                "suppressed": suppressed,
                "mode": mode,
            },
        )

    def _record_auto_mode_unknown(self, action: dict[str, Any]) -> None:
        if self._state is None:
            return
        question_ids = self._coerce_str_list(action.get("question_ids"))
        if not question_ids:
            fallback_id = self._coerce_str(action.get("question_id"))
            if fallback_id:
                question_ids = [fallback_id]
        if not question_ids:
            return
        queue_state = self._state.question_queue_state
        unknowns = queue_state._passthrough_fields.setdefault("auto_mode_unknowns", [])
        if not isinstance(unknowns, list):
            unknowns = []
            queue_state._passthrough_fields["auto_mode_unknowns"] = unknowns
        seen_ids = {
            str(record.get("question_id", "")).strip()
            for record in unknowns
            if isinstance(record, dict)
        }
        now = datetime.now(UTC).isoformat()
        for question_id in question_ids:
            if question_id in seen_ids:
                continue
            item = self._queue.get_item(question_id) if self._queue is not None else None
            unknowns.append(
                {
                    "question_id": question_id,
                    "canonical_key": item.canonical_key if item is not None else "",
                    "taxonomy_type": item.taxonomy_type if item is not None else "",
                    "severity": item.blockers.severity if item is not None else "",
                    "reason": "auto mode suppresses user prompts",
                    "recorded_at": now,
                }
            )
            seen_ids.add(question_id)

    def _finalize_prompt_action(self, action: dict[str, Any]) -> dict[str, Any]:
        action_kind = self._coerce_str(action.get("action"))
        if action_kind not in {"ask", "ask_batch"}:
            return action
        if not self.is_auto_mode:
            self._record_presented_action(action, suppressed=False, mode=self._mode)
            return action

        self._record_auto_mode_unknown(action)
        self._record_presented_action(action, suppressed=True, mode=self._mode)

        question_ids = self._coerce_str_list(action.get("question_ids"))
        if not question_ids:
            question_id = self._coerce_str(action.get("question_id"))
            if question_id:
                question_ids = [question_id]

        return {
            "action": "wait",
            "reason": "auto_mode_prompt_suppressed",
            "suppressed_action": action_kind,
            "question_ids": question_ids,
        }

    def _dedupe_nonempty_texts(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = self._coerce_str(value)
            canonical = text.lower()
            if not text or canonical in seen:
                continue
            seen.add(canonical)
            deduped.append(text)
        return deduped

    def _redefinition_protocol_choices(self) -> list[dict[str, str]]:
        return [
            {"id": choice_id, "label": label} for choice_id, label in _DEFAULT_REDEFINITION_CHOICES
        ]

    def _normalize_redefinition_choice_id(self, choice_id: str) -> str:
        normalized = self._coerce_str(choice_id).lower().replace("-", "_").replace(" ", "_")
        if normalized in {"a", "adopt", "adopt_new", "accept_new", "accept_restatement", "yes"}:
            return "adopt_new"
        if normalized in {"b", "keep", "keep_original", "keep_current", "reject_new", "no"}:
            return "keep_original"
        if normalized in {"c", "partial", "partial_accept", "partial_adopt", "mixed"}:
            return "partial"
        return ""

    def _infer_redefinition_choice_id(self, raw_text: str) -> str:
        normalized = self._coerce_str(raw_text).lower()
        if not normalized:
            return ""
        direct = self._normalize_redefinition_choice_id(normalized)
        if direct:
            return direct
        if normalized.startswith("(a)") or normalized.startswith("a."):
            return "adopt_new"
        if normalized.startswith("(b)") or normalized.startswith("b."):
            return "keep_original"
        if normalized.startswith("(c)") or normalized.startswith("c."):
            return "partial"
        return ""

    def _is_redefinition_check_item(self, item: QuestionItem | None) -> bool:
        if item is None:
            return False
        raw_binding = item.system_binding if isinstance(item.system_binding, dict) else {}
        work_items = {
            value.strip().upper()
            for value in raw_binding.get("work_items", [])
            if isinstance(value, str) and value.strip()
        }
        return _REDEFINITION_CHECK_WORK_ITEM in work_items

    def _build_redefinition_binding(
        self,
        base_binding: dict[str, Any] | None,
        *,
        taxonomy_type: str,
        text: str,
        canonical_key: str,
    ) -> dict[str, Any]:
        binding = dict(base_binding or {})
        work_items = self._coerce_str_list(binding.get("work_items", []))
        if _REDEFINITION_CHECK_WORK_ITEM not in work_items:
            work_items.append(_REDEFINITION_CHECK_WORK_ITEM)
        binding["work_items"] = work_items
        return self._normalize_question_binding(
            binding,
            taxonomy_type=taxonomy_type,
            text=text,
            canonical_key=canonical_key,
        )

    def _requires_partial_redefinition_details(
        self,
        *,
        item: QuestionItem | None,
        selected_choice_id: str,
        raw_text: str,
    ) -> bool:
        if not self._is_redefinition_check_item(item):
            return False

        normalized_choice = self._normalize_redefinition_choice_id(selected_choice_id)
        if not normalized_choice:
            normalized_choice = self._infer_redefinition_choice_id(raw_text)
        if normalized_choice != "partial":
            return False

        normalized_answer = self._coerce_str(raw_text).lower()
        if not normalized_answer:
            return True

        bare_answers = {
            "partial",
            "partially",
            "c",
            "option c",
            "(c)",
            "adopt parts",
            "adopt parts of the new understanding",
            "partially adopt and specify exactly what should change",
        }
        if normalized_answer in bare_answers:
            return True
        return normalized_answer in {
            "yes",
            "no",
            "keep original",
            "adopt new",
            "adopt_new",
            "keep_original",
        }

    def _collect_alignment_commitments_from_updates(
        self, updates: list[dict[str, Any]]
    ) -> list[str]:
        commitments: list[str] = []
        for update in updates:
            if not isinstance(update, dict):
                continue
            for key in (
                "must_remain_true",
                "confirmed_commitments",
                "confirmed_scope_constraints",
                "confirmed_scope_in",
                "confirmed_scope_out",
                "confirmed_decisions",
            ):
                raw_value = update.get(key)
                if isinstance(raw_value, list):
                    commitments.extend(self._coerce_str_list(raw_value))
                elif isinstance(raw_value, dict):
                    commitments.extend(self._coerce_str_list(raw_value.get("items", [])))
                elif isinstance(raw_value, str):
                    text = self._coerce_str(raw_value)
                    if text:
                        commitments.append(text)
        return self._dedupe_nonempty_texts(commitments)

    def _derive_alignment_invariants(self, updates: list[dict[str, Any]]) -> list[str]:
        if self._state is None:
            return []

        invariants: list[str] = []
        original_intent = self._coerce_str(self._state.original_intent.user_statement)
        if original_intent:
            invariants.append(f"User intent remains anchored to: {original_intent}")

        current_restatement = self._coerce_str(self._state.problem_frame.current_restatement)
        if current_restatement:
            invariants.append(f"Current restatement remains in force: {current_restatement}")

        scope_in = self._dedupe_nonempty_texts(
            self._coerce_str_list(self._state.problem_frame.scope.get("in", [])),
        )
        scope_out = self._dedupe_nonempty_texts(
            self._coerce_str_list(self._state.problem_frame.scope.get("out", [])),
        )
        for item in scope_in:
            invariants.append(f"In scope: {item}")
        for item in scope_out:
            invariants.append(f"Out of scope: {item}")

        confirmed_assumptions = [
            assumption.text
            for assumption in self._state.problem_frame.frame_assumptions
            if assumption.status == "CONFIRMED" and assumption.source in {"user", "intent_agent"}
        ]
        for item in self._dedupe_nonempty_texts(confirmed_assumptions):
            if item.startswith(_ALIGNMENT_INVARIANT_PREFIX):
                continue
            invariants.append(f"Confirmed commitment: {item}")

        invariants.extend(self._collect_alignment_commitments_from_updates(updates))
        return self._dedupe_nonempty_texts(invariants)[:12]

    def _sync_alignment_invariants(self, trigger: dict[str, Any]) -> None:
        if self._state is None:
            return

        now_iso = datetime.now(UTC).isoformat()
        derived_invariants = self._derive_alignment_invariants([trigger])
        canonical_invariant_texts = {
            f"{_ALIGNMENT_INVARIANT_PREFIX}{statement}".strip() for statement in derived_invariants
        }

        queue_state = self._state.question_queue_state
        queue_state._passthrough_fields["alignment_invariants"] = [
            {
                "text": statement,
                "status": "CONFIRMED",
                "source": "intent_agent",
                "created_at": now_iso,
            }
            for statement in derived_invariants
        ]

        existing_assumptions = self._state.problem_frame.frame_assumptions
        retained: list[FrameAssumption] = []
        for assumption in existing_assumptions:
            text = self._coerce_str(assumption.text)
            if not text:
                continue
            is_prior_invariant = (
                assumption.source == "intent_agent"
                and assumption.status == "CONFIRMED"
                and text.startswith(_ALIGNMENT_INVARIANT_PREFIX)
            )
            if is_prior_invariant and text not in canonical_invariant_texts:
                continue
            retained.append(assumption)

        by_text = {
            assumption.text.strip().lower(): assumption
            for assumption in retained
            if assumption.text.strip()
        }
        for invariant_text in sorted(canonical_invariant_texts):
            canonical = invariant_text.lower()
            existing = by_text.get(canonical)
            if existing is None:
                retained.append(
                    FrameAssumption(
                        text=invariant_text,
                        status="CONFIRMED",
                        source="intent_agent",
                        created_at=now_iso,
                    )
                )
                continue
            existing.status = "CONFIRMED"
            existing.source = "intent_agent"
            if not existing.created_at:
                existing.created_at = now_iso

        self._state.problem_frame.frame_assumptions = retained

    def _find_open_queue_item(
        self,
        *,
        question_id: str = "",
        canonical_key: str = "",
    ) -> QuestionItem | None:
        if self._queue is None:
            return None
        if question_id:
            item = self._queue.get_item(question_id)
            if item is not None and item.status == "OPEN":
                return item

        if canonical_key:
            for candidate in self._queue._items.values():
                if candidate.status == "OPEN" and candidate.canonical_key == canonical_key:
                    return candidate
        return None

    def _spawn_replacement_question(
        self,
        source_item: QuestionItem,
        replacement: dict[str, Any],
        *,
        reason: str,
    ) -> str | None:
        if self._queue is None:
            return None

        new_text = self._coerce_str(
            replacement.get("new_user_prompt_text"), source_item.user_prompt.text
        )
        canonical_key = self._coerce_str(
            replacement.get("new_canonical_key"),
            f"{source_item.canonical_key}.replacement",
        )
        canonical_key = self._normalize_canonical_key(
            canonical_key,
            taxonomy_type=source_item.taxonomy_type,
            text=new_text,
            scope_kind=source_item.scope_kind,
        )
        question_id = self._coerce_str(replacement.get("new_question_id"), "")

        if not question_id:
            question_id = f"q_{uuid.uuid4().hex[:12]}"

        now = datetime.now(UTC).isoformat()
        system_binding = self._normalize_question_binding(
            source_item.system_binding,
            taxonomy_type=source_item.taxonomy_type,
            text=new_text,
            canonical_key=canonical_key,
        )
        new_origins = list(source_item.origins)
        replacement_item = QuestionItem(
            question_id=question_id,
            status="OPEN",
            taxonomy_type=source_item.taxonomy_type,
            scope_kind=source_item.scope_kind,
            canonical_key=canonical_key,
            user_prompt=UserPrompt(
                text=new_text,
                scenario=source_item.user_prompt.scenario,
                why_it_matters=source_item.user_prompt.why_it_matters,
                answer_spec=source_item.user_prompt.answer_spec,
            ),
            system_binding=system_binding,
            origins=new_origins,
            blockers=source_item.blockers,
            quality_gate=QualityGateStatus(
                status="PASS",
                attempts=1,
                last_checked_at=now,
            ),
            timestamps={
                "created_at": now,
                "updated_at": now,
            },
        )

        existing = self._queue.dedup(replacement_item, run_agent=self._run_agent)
        item = existing or replacement_item
        if item.status != "OPEN":
            item.status = "OPEN"
            if not item.timestamps.get("updated_at"):
                item.timestamps["updated_at"] = now

        if existing is None:
            self._queue.enqueue(item)

        item.timestamps["updated_at"] = now
        return item.question_id

    def _coerce_redefinition_action_type(self, update_type: str) -> str:
        normalized = self._coerce_str(update_type).lower().replace("-", "_")
        if not normalized:
            return ""
        if normalized in {"problem_redefinition", "scope_redefinition", "lifecycle_redefinition"}:
            return "problem_redefinition"
        if normalized in {"alignment_violation", "invariant_violation"}:
            return "alignment_violation"
        if normalized in {
            "decomposition_scope_change",
            "decomposition_scope_shift",
            "material_scope_change",
            "scope_change",
            "requirement_conflict",
            "requirements_conflict",
            "incompatible_requirements",
            "architecture_expectation_shift",
            "architecture_model_shift",
            "operational_expectation_shift",
        }:
            return "problem_redefinition"
        return normalized

    def _redefinition_update_tokens(self, update: dict[str, Any]) -> set[str]:
        tokens: set[str] = set()
        for raw_value in (
            update.get("type"),
            update.get("event_kind"),
            update.get("classification"),
            update.get("reason"),
            update.get("review_reason"),
            update.get("decision_key"),
        ):
            text = self._coerce_str(raw_value).lower().replace("-", "_")
            if text:
                tokens.update(_CANONICAL_KEY_TOKEN_RE.findall(text))

        for field_name in ("decision_record_tags", "tags", "labels"):
            for tag in self._coerce_update_ids(update.get(field_name, [])):
                tokens.update(_CANONICAL_KEY_TOKEN_RE.findall(tag.lower().replace("-", "_")))
        return tokens

    def _coerce_redefinition_update_type(self, update: dict[str, Any]) -> str:
        for raw_type in (
            update.get("type"),
            update.get("event_kind"),
            update.get("classification"),
        ):
            coerced = self._coerce_redefinition_action_type(self._coerce_str(raw_type))
            if coerced in {"problem_redefinition", "alignment_violation"}:
                return coerced

        tokens = self._redefinition_update_tokens(update)
        has_alignment_violation = ("alignment" in tokens and "violation" in tokens) or (
            "invariant" in tokens and "violation" in tokens
        )
        if has_alignment_violation:
            return "alignment_violation"

        has_scope_shift = (
            "decomposition" in tokens and "scope" in tokens and {"change", "shift"} & tokens
        ) or ("scope" in tokens and "change" in tokens)
        has_requirement_conflict = (
            ("requirement" in tokens and "conflict" in tokens)
            or ("requirements" in tokens and "conflict" in tokens)
            or ("incompatible" in tokens and ("requirement" in tokens or "requirements" in tokens))
        )
        has_architecture_shift = (
            "architecture" in tokens and {"expectation", "operational"} & tokens
        ) and ({"change", "shift", "mismatch"} & tokens)
        has_redefinition_tokens = "redefinition" in tokens or (
            "scope" in tokens and "redefinition" in tokens
        )
        if (
            has_scope_shift
            or has_requirement_conflict
            or has_architecture_shift
            or has_redefinition_tokens
        ):
            return "problem_redefinition"
        return ""

    def _coerce_redefinition_question_type(
        self,
        trigger: dict[str, Any],
        trigger_type: str,
        stage: str = "",
        *,
        canonical_key: str = "",
    ) -> str:
        """Return allowed user-facing taxonomy for redefinition follow-up.

        Reclassification is constrained to VALIDATION / SCOPE / TRADEOFF.
        """
        explicit_type = normalize_user_facing_taxonomy(
            self._coerce_str(trigger.get("question_type"), ""),
        )
        if trigger_type == "alignment_violation":
            if explicit_type in _VALID_ALIGNMENT_REDEFINITION_QUESTION_TYPES:
                return explicit_type
            return "TRADEOFF"

        if explicit_type in _VALID_REDEFINITION_QUESTION_TYPES:
            return explicit_type

        normalized_stage = str(stage).strip().lower()
        if "_to_" in normalized_stage:
            return "VALIDATION"

        canonical_key_text = str(canonical_key).lower()
        if "lifecycle_transition" in canonical_key_text:
            return "VALIDATION"

        return "SCOPE"

    def _is_authorized_redefinition_update(
        self, update: dict[str, Any], *, update_type: str
    ) -> bool:
        source = self._coerce_str(update.get("source"), "PLANNER").upper()
        if source in _REDEFINITION_UPDATE_SOURCES:
            return True

        event_id = self._coerce_str(update.get("event_id"))
        logger.warning(
            "Blocked redefinition update from untrusted source %s for %s (event_id=%s)",
            source,
            update_type,
            event_id,
        )
        if self._event_log is not None:
            self._event_log.append(
                "redefinition_update_blocked",
                {
                    "update_type": update_type,
                    "source": source,
                    "event_id": event_id,
                    "reason": "untrusted_source",
                },
            )
        return False

    def _candidate_problem_frame_payloads(self, update: dict[str, Any]) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = [update]
        queue: list[dict[str, Any]] = [update]
        while queue:
            current = queue.pop(0)
            for key in (
                "payload",
                "details",
                "update",
                "changes",
                "problem_frame",
                "problem_frame_update",
                "updated_problem_frame",
                "frame_update",
            ):
                nested = current.get(key)
                if not isinstance(nested, dict):
                    continue
                if any(nested is existing for existing in payloads):
                    continue
                payloads.append(nested)
                queue.append(nested)
        return payloads

    def _extract_problem_frame_patch(self, update: dict[str, Any]) -> dict[str, Any]:
        if self._state is None:
            return {}

        payloads = self._candidate_problem_frame_payloads(update)
        patch: dict[str, Any] = {}
        has_scope_in = False
        has_scope_out = False
        scope_in_values: list[str] = []
        scope_out_values: list[str] = []

        for payload in payloads:
            if "current_restatement" in payload:
                restatement = self._coerce_str(payload.get("current_restatement"))
                if restatement:
                    patch["current_restatement"] = restatement

            raw_scope = payload.get("scope")
            if isinstance(raw_scope, dict):
                if "in" in raw_scope:
                    has_scope_in = True
                    scope_in_values = self._dedupe_nonempty_texts(
                        self._coerce_str_list(raw_scope.get("in", []))
                    )
                if "out" in raw_scope:
                    has_scope_out = True
                    scope_out_values = self._dedupe_nonempty_texts(
                        self._coerce_str_list(raw_scope.get("out", []))
                    )

            for key in ("scope_in", "in_scope", "scope_include", "scope_includes"):
                if key in payload:
                    has_scope_in = True
                    scope_in_values = self._dedupe_nonempty_texts(
                        self._coerce_str_list(payload.get(key, []))
                    )
                    break
            for key in ("scope_out", "out_scope", "scope_exclude", "scope_excludes"):
                if key in payload:
                    has_scope_out = True
                    scope_out_values = self._dedupe_nonempty_texts(
                        self._coerce_str_list(payload.get(key, []))
                    )
                    break

        if has_scope_in or has_scope_out:
            existing_scope = self._state.problem_frame.scope
            patch["scope"] = {
                "in": scope_in_values
                if has_scope_in
                else self._dedupe_nonempty_texts(
                    self._coerce_str_list(existing_scope.get("in", []))
                ),
                "out": scope_out_values
                if has_scope_out
                else self._dedupe_nonempty_texts(
                    self._coerce_str_list(existing_scope.get("out", []))
                ),
            }
        return patch

    def _apply_authoritative_problem_frame_updates(
        self,
        updates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self._state is None:
            return []

        applied: list[dict[str, Any]] = []
        for update in updates:
            if not isinstance(update, dict):
                continue

            patch = self._extract_problem_frame_patch(update)
            if not patch:
                continue

            update_type = self._coerce_redefinition_update_type(update)
            authority_type = update_type or "problem_frame_update"
            if not self._is_authorized_redefinition_update(update, update_type=authority_type):
                continue

            changed_fields: list[str] = []
            if "current_restatement" in patch:
                current_restatement = self._coerce_str(patch.get("current_restatement"))
                if (
                    current_restatement
                    and current_restatement != self._state.problem_frame.current_restatement
                ):
                    self._state.problem_frame.current_restatement = current_restatement
                    changed_fields.append("current_restatement")

            if "scope" in patch and isinstance(patch.get("scope"), dict):
                raw_scope = patch["scope"]
                new_scope = {
                    "in": self._dedupe_nonempty_texts(
                        self._coerce_str_list(raw_scope.get("in", []))
                    ),
                    "out": self._dedupe_nonempty_texts(
                        self._coerce_str_list(raw_scope.get("out", []))
                    ),
                }
                if new_scope != self._state.problem_frame.scope:
                    self._state.problem_frame.scope = new_scope
                    changed_fields.append("scope")

            if not changed_fields:
                continue

            applied.append(
                {
                    "event_id": self._coerce_str(
                        update.get("event_id", update.get("trace_id", ""))
                    ),
                    "update_type": authority_type,
                    "fields": changed_fields,
                }
            )

        if applied:
            self._sync_alignment_invariants({})
        return applied

    def _infer_constraint_dimensions_for_item(self, item: QuestionItem) -> list[str]:
        if item.taxonomy_type != QuestionTaxonomy.CONSTRAINT.value:
            return []

        persisted_dims = normalize_constraint_dimensions(
            item.system_binding.get("constraint_key_hints", []),
        )
        if persisted_dims:
            return persisted_dims

        inferred_dims = normalize_constraint_dimensions(
            infer_constraint_dimensions_with_key(
                item.user_prompt.text,
                canonical_key=item.canonical_key,
            )
        )
        if inferred_dims:
            return inferred_dims
        return ["operational"]

    def _normalize_binding_str_list(
        self,
        base_binding: dict[str, Any],
        field_name: str,
    ) -> list[str]:
        raw = base_binding.get(field_name)
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise TypeError(f"system_binding.{field_name} must be a list of strings")

        normalized: list[str] = []
        seen: set[str] = set()
        for idx, value in enumerate(raw):
            if not isinstance(value, str):
                raise TypeError(f"system_binding.{field_name}[{idx}] must be a string")
            text = value.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _normalize_question_binding(
        self,
        base_binding: dict[str, Any] | None,
        *,
        taxonomy_type: str,
        text: str,
        canonical_key: str,
    ) -> dict[str, Any]:
        binding = dict(base_binding or {})
        normalized_binding: dict[str, Any] = {}
        for field_name in ("constraint_key_hints", "decision_requirement_ids", "work_items"):
            values = self._normalize_binding_str_list(binding, field_name)
            if values:
                normalized_binding[field_name] = values

        normalized_taxonomy = normalize_user_facing_taxonomy(taxonomy_type)
        if normalized_taxonomy == QuestionTaxonomy.CONSTRAINT.value:
            inferred = infer_constraint_dimensions_with_key(
                text,
                canonical_key=canonical_key,
            )
            normalized_dims = normalize_constraint_dimensions(
                normalize_constraint_dimensions(normalized_binding.get("constraint_key_hints", []))
                + inferred,
            )
            if not normalized_dims:
                normalized_dims = ["operational"]
            normalized_binding["constraint_key_hints"] = normalized_dims
        return normalized_binding

    def _coerce_answer_spec_kind(self, answer_spec_kind: Any) -> str:
        normalized = self._coerce_str(answer_spec_kind, "choice").replace("-", "_").lower()
        if normalized in {"choice", "yes_no", "value", "bounded_text"}:
            return normalized
        return "choice"

    def _apply_quality_pass_to_item(
        self,
        item: QuestionItem,
        final_candidate: QualityCheckCandidate,
        records: list[QualityCheckRecord],
    ) -> None:
        item.taxonomy_type = normalize_user_facing_taxonomy(final_candidate.taxonomy_type)
        item.user_prompt.text = self._coerce_str(final_candidate.text, item.user_prompt.text)
        item.user_prompt.scenario = self._coerce_str(
            final_candidate.scenario,
            item.user_prompt.scenario,
        )
        item.user_prompt.answer_spec = AnswerSpec(
            kind=self._coerce_answer_spec_kind(final_candidate.answer_spec_kind),
        )
        item.system_binding = self._normalize_question_binding(
            item.system_binding,
            taxonomy_type=item.taxonomy_type,
            text=item.user_prompt.text,
            canonical_key=item.canonical_key,
        )
        if item.status == "UNASKABLE":
            item.status = "OPEN"
        item.quality_gate.status = "PASS"
        item.quality_gate.attempts = len(records)
        item.quality_gate.last_quality_record_id = records[-1].record_id if records else ""
        item.quality_gate.last_checked_at = datetime.now(UTC).isoformat()
        item.timestamps["updated_at"] = item.quality_gate.last_checked_at

    def _refresh_question_queue_state(self) -> None:
        if self._state is None or self._queue is None:
            return

        open_ids: list[str] = []
        closed_ids: list[str] = []
        stale_ids: list[str] = []
        open_constraint_ids: list[str] = []
        closed_constraint_ids: list[str] = []
        open_constraint_dims: set[str] = set()
        closed_constraint_dims: set[str] = set()

        for item in self._queue._items.values():
            if item.status == "OPEN":
                open_ids.append(item.question_id)
            elif item.status in {"ANSWERED", "SUPERSEDED", "DISMISSED", "UNASKABLE"}:
                closed_ids.append(item.question_id)
            elif item.status == "STALE":
                stale_ids.append(item.question_id)

            if item.taxonomy_type == QuestionTaxonomy.CONSTRAINT.value:
                dimensions = self._infer_constraint_dimensions_for_item(item)
                if item.status == "OPEN":
                    open_constraint_ids.append(item.question_id)
                    open_constraint_dims.update(dimensions)
                elif item.status in {"ANSWERED", "SUPERSEDED", "DISMISSED", "UNASKABLE"}:
                    closed_constraint_ids.append(item.question_id)
                    closed_constraint_dims.update(dimensions)

        queue_state = self._state.question_queue_state
        queue_state.open_ids = open_ids
        queue_state.closed_ids = closed_ids
        queue_state.stale_ids = stale_ids
        queue_state._passthrough_fields["open_constraint_question_ids"] = open_constraint_ids
        queue_state._passthrough_fields["closed_constraint_question_ids"] = closed_constraint_ids
        queue_state._passthrough_fields["open_constraint_dimensions"] = sorted(open_constraint_dims)
        queue_state._passthrough_fields["closed_constraint_dimensions"] = sorted(
            closed_constraint_dims
        )
        queue_state._passthrough_fields.setdefault("unaskable_question_ids", [])
        queue_state._passthrough_fields.setdefault("new_blocking_arrival_question_ids", [])
        queue_state._passthrough_fields.setdefault("skeleton_input_signature", "")

        # Active batch metadata is only valid while the anchor question remains OPEN.
        active_batch_id = self._coerce_str(queue_state.active_batch_id)
        if active_batch_id and active_batch_id not in open_ids:
            queue_state.active_batch_id = ""

    def _skeleton_input_signature(self) -> str:
        if self._state is None:
            return ""
        pf = self._state.problem_frame
        qs = self._state.question_queue_state
        signature = {
            "restatement": pf.current_restatement,
            "goals": sorted(set(pf.goals)),
            "open_ids": sorted(qs.open_ids),
            "closed_ids": sorted(qs.closed_ids),
            "open_constraint_question_ids": sorted(
                self._coerce_str_list(
                    qs._passthrough_fields.get("open_constraint_question_ids", []),
                )
            ),
            "closed_constraint_question_ids": sorted(
                self._coerce_str_list(
                    qs._passthrough_fields.get("closed_constraint_question_ids", [])
                )
            ),
            "open_constraint_dimensions": sorted(
                self._coerce_str_list(qs._passthrough_fields.get("open_constraint_dimensions", []))
            ),
            "closed_constraint_dimensions": sorted(
                self._coerce_str_list(
                    qs._passthrough_fields.get("closed_constraint_dimensions", []),
                )
            ),
            "open_count": len(qs.open_ids),
            "closed_count": len(qs.closed_ids),
        }
        return json.dumps(signature, sort_keys=True)

    def _maybe_update_skeleton(self, *, force: bool = False) -> list[Path] | None:
        if self._state is None or self._queue is None:
            return None

        self._refresh_question_queue_state()

        pf = self._state.problem_frame
        frame_dict = {
            "current_restatement": pf.current_restatement,
            "goals": list(pf.goals),
            "non_goals": list(pf.non_goals),
            "scope": {
                "in": list(pf.scope.get("in", [])),
                "out": list(pf.scope.get("out", [])),
            },
            "success_metrics": list(pf.success_metrics),
            "risk_flags": list(pf.risk_flags),
        }
        queue_state = self._state.question_queue_state
        queue_state_dict = queue_state.to_dict()
        if not should_produce_skeleton(frame_dict, queue_state_dict):
            return None

        signature = self._skeleton_input_signature()
        last_signature = self._coerce_str(
            queue_state._passthrough_fields.get("skeleton_input_signature", ""),
        )
        if force or self._state.skeleton_state.revision == 0 or signature != last_signature:
            produced = self.produce_skeleton()
            queue_state._passthrough_fields["skeleton_input_signature"] = signature
            return produced

        return None

    @staticmethod
    def _dedupe_ordered(values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    def _planner_update_type_counts(self, updates: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for update in updates:
            event_kind = self._coerce_str(
                update.get("event_kind", update.get("type", "unknown")),
                "unknown",
            ).lower()
            counts[event_kind] = counts.get(event_kind, 0) + 1
        return counts

    def _slice_progress_from_updates(
        self,
        updates: list[dict[str, Any]],
    ) -> tuple[list[str], dict[str, int]]:
        slice_ids: set[str] = set()
        status_counts: dict[str, int] = {}

        for update in updates:
            for slice_id in self._coerce_update_ids(update.get("slice_id", "")):
                slice_ids.add(slice_id)
            for slice_id in self._coerce_update_ids(update.get("slice_ids", [])):
                slice_ids.add(slice_id)

            raw_status = self._coerce_str(update.get("slice_status", ""))
            if raw_status:
                normalized = raw_status.upper()
                status_counts[normalized] = status_counts.get(normalized, 0) + 1

            raw_statuses = update.get("slice_statuses")
            if isinstance(raw_statuses, list):
                for entry in raw_statuses:
                    if isinstance(entry, dict):
                        entry_slice_id = self._coerce_str(entry.get("slice_id"))
                        if entry_slice_id:
                            slice_ids.add(entry_slice_id)
                        entry_status = self._coerce_str(entry.get("status"))
                        if entry_status:
                            normalized = entry_status.upper()
                            status_counts[normalized] = status_counts.get(normalized, 0) + 1
                    elif isinstance(entry, str) and entry.strip():
                        normalized = entry.strip().upper()
                        status_counts[normalized] = status_counts.get(normalized, 0) + 1

            status_map = update.get("slice_status_by_id")
            if isinstance(status_map, dict):
                for raw_slice_id, raw_status_value in status_map.items():
                    slice_id = self._coerce_str(raw_slice_id)
                    if slice_id:
                        slice_ids.add(slice_id)
                    status_text = self._coerce_str(raw_status_value)
                    if status_text:
                        normalized = status_text.upper()
                        status_counts[normalized] = status_counts.get(normalized, 0) + 1

        return sorted(slice_ids), status_counts

    def _build_resume_progress_summary(
        self,
        updates: list[dict[str, Any]],
        reassessment: dict[str, Any],
    ) -> ResumeProgressSummaryProjection:
        planner_update_types = self._planner_update_type_counts(updates)
        slice_ids, slice_status_counts = self._slice_progress_from_updates(updates)

        action_counts: dict[str, int] = {}
        for action in reassessment.get("actions", []):
            if not isinstance(action, dict):
                continue
            action_kind = self._coerce_str(action.get("action"), "KEEP").upper()
            if not action_kind:
                action_kind = "KEEP"
            action_counts[action_kind] = action_counts.get(action_kind, 0) + 1

        latest_planner_update_at = ""
        for update in updates:
            created_at = self._coerce_str(update.get("created_at", ""))
            if created_at > latest_planner_update_at:
                latest_planner_update_at = created_at

        planner_watermark = ""
        if self._state is not None:
            planner_watermark = self._state.watermarks.planner_update_watermark

        resolved_count = sum(count for action, count in action_counts.items() if action != "KEEP")
        return ResumeProgressSummaryProjection(
            planner_watermark=planner_watermark,
            planner_updates_seen=len(updates),
            planner_update_types=planner_update_types,
            slice_ids=slice_ids,
            slice_status_counts=slice_status_counts,
            latest_planner_update_at=latest_planner_update_at,
            reassess_action_counts=action_counts,
            reassess_resolved_count=resolved_count,
        )

    def _project_reassess_planner_updates(
        self,
        updates: list[dict[str, Any]],
    ) -> list[ReassessPlannerSignal]:
        projected: list[ReassessPlannerSignal] = []
        for update in updates:
            event_kind = self._coerce_str(
                update.get("event_kind", update.get("type", "unknown")),
                "unknown",
            ).lower()
            event_ref = self._coerce_str(
                update.get(
                    "event_id",
                    update.get(
                        "trace_id",
                        update.get("decision_id", update.get("constraint_id", "")),
                    ),
                ),
            )
            affected_canonical_keys = self._dedupe_ordered(
                self._coerce_update_ids(update.get("affected_canonical_keys", []))
                + self._coerce_update_ids(update.get("canonical_keys", []))
                + self._coerce_update_ids(update.get("canonical_key", ""))
            )
            affected_constraint_ids = self._dedupe_ordered(
                self._coerce_update_ids(update.get("affected_constraint_ids", []))
                + self._coerce_update_ids(update.get("constraint_ids", []))
                + self._coerce_update_ids(update.get("constraint_id", ""))
            )
            affected_decision_ids = self._dedupe_ordered(
                self._coerce_update_ids(update.get("affected_decision_ids", []))
                + self._coerce_update_ids(update.get("decision_ids", []))
                + self._coerce_update_ids(update.get("decision_id", ""))
            )
            affected_question_ids = self._dedupe_ordered(
                self._coerce_update_ids(update.get("affected_question_ids", []))
                + self._coerce_update_ids(update.get("question_ids", []))
                + self._coerce_update_ids(update.get("question_id", ""))
            )
            superseded_question_ids = self._dedupe_ordered(
                self._coerce_update_ids(update.get("superseded_question_ids", []))
                + self._coerce_update_ids(update.get("replaced_question_ids", []))
                + self._coerce_update_ids(update.get("supersedes_question_id", ""))
            )
            superseded_canonical_keys = self._dedupe_ordered(
                self._coerce_update_ids(update.get("superseded_canonical_keys", []))
                + self._coerce_update_ids(update.get("obsolete_canonical_keys", []))
            )

            projected.append(
                ReassessPlannerSignal(
                    event_kind=event_kind,
                    event_ref=event_ref,
                    affected_canonical_keys=tuple(affected_canonical_keys),
                    affected_constraint_ids=tuple(affected_constraint_ids),
                    affected_decision_ids=tuple(affected_decision_ids),
                    affected_question_ids=tuple(affected_question_ids),
                    superseded_question_ids=tuple(superseded_question_ids),
                    superseded_canonical_keys=tuple(superseded_canonical_keys),
                )
            )
        return projected

    def _project_reassess_question_key_map(
        self,
        question_key_map: dict[str, Any],
    ) -> dict[str, ReassessQuestionKeySignal]:
        projected: dict[str, ReassessQuestionKeySignal] = {}
        for raw_canonical_key, raw_ref in question_key_map.items():
            canonical_key = self._coerce_str(raw_canonical_key)
            if not canonical_key:
                continue

            if isinstance(raw_ref, dict):
                planner_constraint_ids = self._coerce_update_ids(
                    raw_ref.get("planner_constraint_ids", []),
                )
                planner_decision_ids = self._coerce_update_ids(
                    raw_ref.get("planner_decision_ids", []),
                )
            else:
                planner_constraint_ids = self._coerce_update_ids(
                    getattr(raw_ref, "planner_constraint_ids", []),
                )
                planner_decision_ids = self._coerce_update_ids(
                    getattr(raw_ref, "planner_decision_ids", []),
                )

            projected[canonical_key] = ReassessQuestionKeySignal(
                canonical_key=canonical_key,
                resolved_constraint_ids=tuple(self._dedupe_ordered(planner_constraint_ids)),
                related_decision_ids=tuple(self._dedupe_ordered(planner_decision_ids)),
            )
        return projected

    def _extract_review_question_signal(self, update: dict[str, Any]) -> UserQuestionSignal | None:
        if not self._coerce_bool(update.get("review_required")):
            return None

        raw_signal = update.get("user_question_signal")
        if raw_signal is None:
            raw_signal = update.get("review_question_signal")
        if not isinstance(raw_signal, dict):
            logger.warning(
                "Planner update requested review without user_question_signal payload: %s",
                json.dumps(update, sort_keys=True),
            )
            return None
        try:
            signal = UserQuestionSignal.from_dict(raw_signal)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Invalid planner-provided user_question_signal: %s (event=%s)",
                exc,
                self._coerce_str(update.get("event_id", update.get("trace_id", ""))),
            )
            return None
        return signal

    def _ingest_review_decision_signal(self, update: dict[str, Any]) -> str | None:
        signal = self._extract_review_question_signal(update)
        if signal is None:
            return None
        item = self.ingest_signal(signal)
        if item is None:
            return None
        return item.question_id

    def _related_planner_updates_for_question(
        self,
        *,
        question_id: str,
        item: QuestionItem | None,
        updates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized_question_id = self._coerce_str(question_id)
        normalized_canonical_key = (
            self._normalize_canonical_key_candidate(item.canonical_key) if item is not None else ""
        )
        related_decision_ids: set[str] = set()
        related_constraint_ids: set[str] = set()
        if self._state is not None and normalized_canonical_key:
            key_ref = self._state.question_key_map.get(normalized_canonical_key)
            if key_ref is None:
                for raw_key, raw_ref in self._state.question_key_map.items():
                    if self._normalize_canonical_key_candidate(raw_key) == normalized_canonical_key:
                        key_ref = raw_ref
                        break
            if key_ref is not None:
                if isinstance(key_ref, dict):
                    related_decision_ids = set(
                        self._coerce_update_ids(key_ref.get("planner_decision_ids", [])),
                    )
                    related_constraint_ids = set(
                        self._coerce_update_ids(key_ref.get("planner_constraint_ids", [])),
                    )
                else:
                    related_decision_ids = set(
                        self._coerce_update_ids(getattr(key_ref, "planner_decision_ids", [])),
                    )
                    related_constraint_ids = set(
                        self._coerce_update_ids(getattr(key_ref, "planner_constraint_ids", [])),
                    )

        related_updates: list[dict[str, Any]] = []
        for update in updates:
            if not isinstance(update, dict):
                continue

            update_question_ids = set(
                self._coerce_update_ids(update.get("question_id", ""))
                + self._coerce_update_ids(update.get("question_ids", []))
                + self._coerce_update_ids(update.get("affected_question_ids", []))
                + self._coerce_update_ids(update.get("superseded_question_ids", []))
            )
            update_canonical_keys = {
                normalized
                for normalized in (
                    self._normalize_canonical_key_candidate(raw_key)
                    for raw_key in (
                        self._coerce_update_ids(update.get("canonical_key", ""))
                        + self._coerce_update_ids(update.get("canonical_keys", []))
                        + self._coerce_update_ids(update.get("affected_canonical_keys", []))
                        + self._coerce_update_ids(update.get("superseded_canonical_keys", []))
                    )
                )
                if normalized
            }
            update_decision_ids = set(
                self._coerce_update_ids(update.get("decision_id", ""))
                + self._coerce_update_ids(update.get("decision_ids", []))
                + self._coerce_update_ids(update.get("affected_decision_ids", []))
            )
            update_constraint_ids = set(
                self._coerce_update_ids(update.get("constraint_id", ""))
                + self._coerce_update_ids(update.get("constraint_ids", []))
                + self._coerce_update_ids(update.get("affected_constraint_ids", []))
            )
            if normalized_question_id and normalized_question_id in update_question_ids:
                related_updates.append(update)
                continue
            if normalized_canonical_key and normalized_canonical_key in update_canonical_keys:
                related_updates.append(update)
                continue
            if related_decision_ids and (related_decision_ids & update_decision_ids):
                related_updates.append(update)
                continue
            if related_constraint_ids and (related_constraint_ids & update_constraint_ids):
                related_updates.append(update)
                continue
        return related_updates

    def _extract_auto_resolution_flags(
        self,
        action: dict[str, Any],
        related_updates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payloads: list[dict[str, Any]] = [action]
        for payload in (action, *related_updates):
            if not isinstance(payload, dict):
                continue
            for key in (
                "auto_resolution",
                "resolution",
                "resolution_evidence",
                "eligibility",
                "authority",
                "payload",
            ):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    payloads.append(nested)
            signal_payload = payload.get("user_question_signal")
            if isinstance(signal_payload, dict):
                payloads.append(signal_payload)
                signal_context = signal_payload.get("payload")
                if isinstance(signal_context, dict):
                    payloads.append(signal_context)

        def _first_bool(keys: tuple[str, ...]) -> bool | None:
            for payload in payloads:
                for key in keys:
                    if key not in payload:
                        continue
                    parsed = self._coerce_optional_bool(payload.get(key))
                    if parsed is not None:
                        return parsed
            return None

        requires_human_authority = _first_bool(
            (
                "requires_human_authority",
                "human_authority_required",
                "requires_user_authority",
                "requires_human_review",
            ),
        )
        review_required = _first_bool(
            ("review_required", "requires_review", "needs_review", "needs_human_review"),
        )
        if review_required is True:
            requires_human_authority = True
        elif review_required is False and requires_human_authority is None:
            requires_human_authority = False

        if requires_human_authority is None:
            for payload in payloads:
                authority_required = self._coerce_str(
                    payload.get("authority_required", payload.get("authority", "")),
                ).lower()
                if not authority_required:
                    continue
                if authority_required in {"human_required", "user_required"}:
                    requires_human_authority = True
                    break
                if authority_required in {"planner_ok", "auto_ok", "none", "not_required"}:
                    requires_human_authority = False
                    break

        tool_resolvable = _first_bool(
            (
                "tool_resolvable",
                "research_resolvable",
                "resolvable_with_tools",
                "can_resolve_with_research",
                "can_resolve_with_tools",
            ),
        )
        if tool_resolvable is None:
            for payload in payloads:
                resolution_method = self._coerce_str(
                    payload.get("resolution_method", payload.get("method", "")),
                ).lower()
                if not resolution_method:
                    continue
                if any(token in resolution_method for token in ("tool", "research", "evidence")):
                    tool_resolvable = True
                    break
                if any(token in resolution_method for token in ("manual", "human")):
                    tool_resolvable = False
                    break

        confidence_checked = _first_bool(
            (
                "confidence_checked",
                "confident_inference",
                "confidence_ok",
                "inference_confident",
                "confidence_verified",
            ),
        )
        if confidence_checked is None:
            for payload in payloads:
                for key in ("confidence", "inference_confidence", "resolution_confidence"):
                    raw_value = payload.get(key)
                    if not isinstance(raw_value, (int, float)):
                        continue
                    confidence_checked = float(raw_value) >= _AUTO_RESOLUTION_MIN_CONFIDENCE
                    break
                if confidence_checked is not None:
                    break

        ambiguity_safe = _first_bool(
            (
                "ambiguity_safe",
                "block_on_ambiguity_passed",
                "ambiguity_resolved",
                "ambiguity_clear",
            ),
        )
        if ambiguity_safe is None:
            for payload in payloads:
                ambiguity_status = self._coerce_str(payload.get("ambiguity_status", "")).lower()
                if ambiguity_status in {"clear", "resolved", "none"}:
                    ambiguity_safe = True
                    break
                if ambiguity_status in {"open", "unresolved", "blocked", "unknown"}:
                    ambiguity_safe = False
                    break
            if ambiguity_safe is None:
                for payload in payloads:
                    combined_text = " ".join(
                        [
                            self._coerce_str(payload.get("reason")),
                            self._coerce_str(payload.get("failure_reason")),
                        ],
                    ).lower()
                    if "ambigu" not in combined_text:
                        continue
                    ambiguity_safe = False
                    break

        return {
            "requires_human_authority": requires_human_authority,
            "tool_resolvable": tool_resolvable,
            "confidence_checked": confidence_checked,
            "ambiguity_safe": ambiguity_safe,
        }

    def _auto_resolution_eligibility(
        self,
        action: dict[str, Any],
        related_updates: list[dict[str, Any]],
    ) -> tuple[bool, dict[str, Any]]:
        flags = self._extract_auto_resolution_flags(action, related_updates)
        authority_safe = flags["requires_human_authority"] is False
        tool_resolvable = flags["tool_resolvable"] is True
        confidence_checked = flags["confidence_checked"] is True
        ambiguity_safe = flags["ambiguity_safe"] is True
        eligible = authority_safe and tool_resolvable and confidence_checked and ambiguity_safe
        return eligible, {
            "eligible": eligible,
            "requires_human_authority": flags["requires_human_authority"],
            "tool_resolvable": flags["tool_resolvable"],
            "confidence_checked": flags["confidence_checked"],
            "ambiguity_safe": flags["ambiguity_safe"],
            "checks": {
                "authority_safe": authority_safe,
                "tool_resolvable": tool_resolvable,
                "confidence_checked": confidence_checked,
                "ambiguity_safe": ambiguity_safe,
            },
        }

    def _apply_auto_mode_planner_outcomes(
        self,
        updates: list[dict[str, Any]],
        reassessment: dict[str, Any],
    ) -> dict[str, Any]:
        if self._mode != "auto" or self._queue is None:
            return {
                "auto_answered_question_ids": [],
                "auto_resolution_rejected_question_ids": [],
                "review_decision_question_ids": [],
            }

        actions = reassessment.get("actions", [])
        auto_answered_ids: list[str] = []
        rejected_ids: list[str] = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            if self._coerce_str(action.get("action")).upper() != "ANSWERED":
                continue
            question_id = self._coerce_str(action.get("question_id"))
            if not question_id:
                continue
            item = self._queue.get_item(question_id)
            related_updates = self._related_planner_updates_for_question(
                question_id=question_id,
                item=item,
                updates=updates,
            )
            eligible, eligibility = self._auto_resolution_eligibility(action, related_updates)
            action["auto_resolution_eligibility"] = eligibility
            if not eligible:
                rejection_reason = "auto resolution rejected: eligibility gate failed"
                if item is not None and item.status == "ANSWERED":
                    item.status = "OPEN"
                    item.last_transition_reason = rejection_reason
                    item.timestamps["updated_at"] = datetime.now(UTC).isoformat()
                action["action"] = "KEEP"
                action["reason"] = rejection_reason
                action["provenance"] = "auto resolution rejected"
                rejected_ids.append(question_id)
                continue
            if item is None or item.status != "ANSWERED":
                continue
            item.last_transition_reason = "auto resolution"
            item.timestamps["updated_at"] = datetime.now(UTC).isoformat()
            action["reason"] = "auto resolution"
            action["provenance"] = "auto resolution"
            auto_answered_ids.append(question_id)

        review_question_ids: list[str] = []
        for update in updates:
            review_question_id = self._ingest_review_decision_signal(update)
            if review_question_id:
                review_question_ids.append(review_question_id)

        return {
            "auto_answered_question_ids": sorted(set(auto_answered_ids)),
            "auto_resolution_rejected_question_ids": sorted(set(rejected_ids)),
            "review_decision_question_ids": sorted(set(review_question_ids)),
        }

    def _next_up_preview(self, limit: int = 3) -> list[dict[str, Any]]:
        if self._queue is None:
            return []
        open_items = self._queue.get_open_items()[: max(0, limit)]
        return [
            {
                "question_id": item.question_id,
                "canonical_key": item.canonical_key,
                "severity": item.blockers.severity,
            }
            for item in open_items
        ]

    # TODO [R2-1.4]: Implement resume() — deterministic resumption
    #   1. Load session_state.json
    #   2. Load question_queue.json
    #   3. Read new UserQuestionSignals since user_question_signal_watermark
    #   4. Read new PlannerUpdates since planner_update_watermark
    #   5. Ingest new signals (classify, draft, quality gate, enqueue)
    #   6. Run reassessment against new planner updates
    #   7. Recompute queue ordering and staleness
    #   8. Return next action to present (question or batch)
    def resume(self) -> dict[str, Any] | None:
        """Resume from persisted state and return next action."""
        # 1. Init stores.
        self._signal_store = UserQuestionSignalStore(self._run_dir)
        self._planner_store = PlannerUpdateStore(self._run_dir)
        self._event_log = IntentEventLog(self._run_dir)

        # 2. Try loading session state; create fresh if not found.
        try:
            self._state = IntentSessionState.load(self._run_dir)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.debug("No existing session state found; creating fresh state.")
            self._state = IntentSessionState(
                session_id=f"s_{uuid.uuid4().hex[:12]}",
            )

        # 3. Try loading queue; create fresh if not found.
        try:
            self._queue = QuestionQueue.load(self._run_dir)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.debug("No existing queue found; creating fresh queue.")
            self._queue = QuestionQueue()

        # 4. Read new signals since watermark and ingest each.
        watermark = self._state.watermarks.user_question_signal_watermark
        new_signals = self._signal_store.read_since(watermark)
        for signal in new_signals:
            self.ingest_signal(signal)

        # 5. Read new planner updates and run reassessment.
        reassessment = self.handle_planner_updates()
        progress_summary = ResumeProgressSummaryProjection.from_dict(
            reassessment.get("resume_progress_summary", {}),
        )

        # 6. Recompute staleness so resumed flow is deterministic and
        #    does not present stale questions after planner/store drift.
        stale_ids = sorted(self._queue.mark_stale())
        if self._state is not None:
            self._state.question_queue_state.stale_ids = stale_ids

        # 7. Refresh derived queue metadata and skeleton readiness.
        self._refresh_question_queue_state()
        self._maybe_update_skeleton()

        # Persist the resume checkpoint so replay starts from this watermark/state.
        self.save_state()

        # 8. Return next action via the same path as normal prompting flow.
        action = self.next_action()
        if action is None:
            action = {"action": "wait"}
        action["resume_progress"] = progress_summary.to_dict()
        action["next_up"] = self._next_up_preview()
        return action

    # TODO [R2-5.1/5.2]: Implement handle_user_message(text) — user input handler
    #   - Update problem frame via IntentFrameStrategy
    #   - Update concept map via ConceptMapStrategy
    #   - Extract candidate unknowns (potential questions)
    #   - Choose: ask highest-value question OR produce/update skeleton
    #   - "Enough to proceed" check (Section 5.7):
    #     core workflows identifiable + major constraint dimensions covered
    def _capture_original_intent(self, text: str) -> None:
        if self._state is None or self._state.original_intent.user_statement:
            return
        self._state.original_intent.user_statement = text
        self._state.original_intent.captured_at = datetime.now(UTC).isoformat()
        # Preserve the user's exact statement as the initial frame anchor.
        if not self._state.problem_frame.current_restatement.strip():
            self._state.problem_frame.current_restatement = text.strip()

    def _log_user_message_event(self, text: str) -> None:
        if self._event_log is None:
            return
        self._event_log.append("user_message", {"text": text})

    def _serialize_problem_frame(self) -> dict[str, Any]:
        assert self._state is not None
        pf = self._state.problem_frame
        return {
            "current_restatement": pf.current_restatement,
            "goals": list(pf.goals),
            "non_goals": list(pf.non_goals),
            "scope": {
                "in": list(pf.scope.get("in", [])),
                "out": list(pf.scope.get("out", [])),
            },
            "success_metrics": list(pf.success_metrics),
            "risk_flags": list(pf.risk_flags),
            "frame_assumptions": self._serialize_frame_assumptions(),
        }

    def _serialize_concept_map(self) -> dict[str, Any]:
        assert self._state is not None
        cm = self._state.concept_map
        return {
            "user_terms": {
                k: {"maps_to": list(v.maps_to), "confidence": v.confidence}
                for k, v in cm.user_terms.items()
            },
            "normalized_terms": dict(cm.normalized_terms),
            "user_introduced_terms": list(cm.user_introduced_terms),
        }

    def _apply_concept_map_update(self, text: str) -> None:
        if self._state is None or self._concept_map is None:
            return
        updated_map = self._concept_map.update_map(
            self._serialize_concept_map(),
            text,
            run_agent=self._run_agent,
        )
        if not isinstance(updated_map, dict):
            return
        if "user_terms" in updated_map and isinstance(updated_map.get("user_terms"), dict):
            self._state.concept_map.user_terms = self._normalize_concept_user_terms(
                updated_map.get("user_terms"),
            )
        if "normalized_terms" in updated_map and isinstance(
            updated_map.get("normalized_terms"),
            dict,
        ):
            self._state.concept_map.normalized_terms = self._normalize_concept_normalized_terms(
                updated_map.get("normalized_terms"),
            )
        if "user_introduced_terms" in updated_map and isinstance(
            updated_map.get("user_introduced_terms"),
            list,
        ):
            introduced_terms = self._dedupe_ordered(
                self._coerce_str_list(updated_map.get("user_introduced_terms", [])),
            )
            if self._state.concept_map.user_terms:
                for term in self._state.concept_map.user_terms:
                    if term not in introduced_terms:
                        introduced_terms.append(term)
            self._state.concept_map.user_introduced_terms = introduced_terms

    def _handle_vague_user_input(self, text: str) -> dict[str, Any] | None:
        if not is_vague_user_input(text):
            return None
        vague_item = self.handle_vague_input(text)
        self._refresh_question_queue_state()
        self.save_state()
        if isinstance(vague_item, QuestionItem) and vague_item.status == "OPEN":
            action = {
                "action": "ask",
                "question": vague_item.to_dict(),
                "question_id": vague_item.question_id,
                "immediate_ask": True,
            }
            return self._finalize_prompt_action(action)
        return None

    def _finalize_user_message(self) -> None:
        self._refresh_question_queue_state()
        self.save_state()

    def handle_user_message(self, text: str) -> dict[str, Any]:
        """Handle a user message. Returns action to take (ask/skeleton/etc)."""
        self._ensure_initialized()
        assert self._state is not None
        assert self._queue is not None

        self._capture_original_intent(text)
        self._log_user_message_event(text)
        self._apply_concept_map_update(text)
        self._ingest_user_message_candidate_unknowns(text)

        if self._is_ready_for_skeleton():
            created_paths = self._maybe_update_skeleton()
            self._refresh_question_queue_state()
            self.save_state()
            action: dict[str, Any] = {"action": "skeleton"}
            if created_paths:
                action["artifact_paths"] = [str(path) for path in created_paths]
            return action

        vague_action = self._handle_vague_user_input(text)
        if vague_action is not None:
            return vague_action

        self._finalize_user_message()
        return self.next_action()

    # TODO [R2-3.3]: Implement ingest_signal(signal) — signal→question pipeline
    #   1. Classify taxonomy type (may be prohibited)
    #   2. If prohibited → reframe to user-valid type
    #   3. Draft user question via QuestionDraftStrategy
    #   4. Run quality gate pipeline (enforce_quality_gate)
    #   5. If PASS → dedup check → enqueue
    #   6. If FAIL after retries → mark UNASKABLE, escalate to Planner
    #   7. Update watermark
    def ingest_signal(
        self,
        signal: UserQuestionSignal,
        *,
        update_signal_watermark: bool = True,
        update_skeleton: bool = True,
    ) -> QuestionItem | None:
        """Ingest a UserQuestionSignal and produce a queued question (or None)."""
        if self._state is None:
            self._ensure_initialized()
        assert self._state is not None
        assert self._queue is not None
        source_kind = self._canonical_origin_kind(
            signal.source.kind,
            field_name="signal.source.kind",
        )

        if self._event_log is not None:
            self._event_log.append(
                "signal_received",
                {
                    "signal_id": signal.uq_id,
                    "source_kind": source_kind,
                    "canonical_key_hint": signal.question.canonical_key_hint,
                },
            )

        question_text = signal.question.text

        # 1. Classify taxonomy type.
        taxonomy = classify_question(
            question_text,
            context=signal.payload,
            run_agent=self._run_agent,
        )

        # 2. If prohibited, reframe to user-valid type.
        reframed_text = question_text
        reframed_taxonomy = taxonomy
        scenario_from_reframe = ""
        reframe_failure_reason = ""
        if is_prohibited(taxonomy):
            reframed = reframe_to_user_valid(
                question_text,
                taxonomy,
                context=signal.payload,
                run_agent=self._run_agent,
            )
            if reframed is not None:
                reframed_text = reframed.reframed_text
                reframed_taxonomy = reframed.reframed_type
                scenario_from_reframe = reframed.scenario
            else:
                reframe_failure_reason = (
                    "Ambiguous prohibited request; could not reframe to a user-valid question."
                )
                scenario_from_reframe = f"{reframe_failure_reason} Original input: {question_text}"
                reframed_taxonomy = QuestionTaxonomy.CONSTRAINT

        canonical_key_hint = self._normalize_canonical_key(
            signal.question.canonical_key_hint,
            taxonomy_type=reframed_taxonomy.value,
            text=reframed_text,
            scope_kind=classify_scope(reframed_text).value,
        )

        # 3. Draft user question via QuestionDraftStrategy.
        if self._question_draft is not None:
            concept_terms = list(self._state.concept_map.user_introduced_terms)
            pf = self._state.problem_frame
            frame_dict = {
                "current_restatement": pf.current_restatement,
                "goals": list(pf.goals),
            }
            candidate = self._question_draft.draft(
                signal_text=reframed_text,
                taxonomy_hint=reframed_taxonomy.value,
                canonical_key_hint=canonical_key_hint,
                context=signal.payload,
                problem_frame=frame_dict,
                concept_map_user_terms=concept_terms,
                run_agent=self._run_agent,
            )
        else:
            candidate = QualityCheckCandidate(
                text=reframed_text,
                scenario=scenario_from_reframe,
                answer_spec_kind="choice",
                taxonomy_type=reframed_taxonomy.value,
            )

        # 4. Run quality gate pipeline.
        question_id = f"q_{uuid.uuid4().hex[:12]}"
        concept_terms = list(self._state.concept_map.user_introduced_terms)

        final_candidate, records, passed = enforce_quality_gate(
            candidate,
            question_id,
            concept_map_user_terms=concept_terms,
            signal_context=signal.payload,
            validator=self._quality_validator,
            repairer=self._question_repairer,
            run_agent=self._run_agent,
            event_log=self._event_log,
        )
        if self._event_log is not None:
            self._event_log.append(
                "signal_ingested",
                {
                    "question_id": question_id,
                    "signal_id": signal.uq_id,
                },
            )
        if reframe_failure_reason:
            # A prohibited signal that cannot be reframed is intentionally blocked
            # from downstream consumption until classification ambiguity is resolved.
            passed = False

        if passed and final_candidate is not None:
            candidate_taxonomy = QuestionTaxonomy(
                normalize_taxonomy_type(final_candidate.taxonomy_type),
            )
            if is_prohibited(candidate_taxonomy):
                reframed_candidate = reframe_to_user_valid(
                    final_candidate.text,
                    candidate_taxonomy,
                    context=signal.payload,
                    run_agent=self._run_agent,
                )
                if reframed_candidate is None:
                    reframe_failure_reason = (
                        "Prohibited taxonomy persisted after quality "
                        "repair and could not be reframed."
                    )
                    passed = False
                else:
                    final_candidate.text = self._coerce_str(
                        reframed_candidate.reframed_text,
                        final_candidate.text,
                    )
                    final_candidate.scenario = self._coerce_str(
                        reframed_candidate.scenario,
                        final_candidate.scenario,
                    )
                    final_candidate.taxonomy_type = reframed_candidate.reframed_type.value

        # 5. If PASS, dedup check and enqueue.
        if passed and final_candidate is not None:
            final_candidate.taxonomy_type = normalize_user_facing_taxonomy(
                final_candidate.taxonomy_type,
            )
            final_candidate.answer_spec_kind = self._coerce_answer_spec_kind(
                final_candidate.answer_spec_kind,
            )
            final_taxonomy = final_candidate.taxonomy_type
            scope = classify_scope(final_candidate.text)
            canonical_key = self._normalize_canonical_key(
                canonical_key_hint,
                taxonomy_type=final_taxonomy,
                text=final_candidate.text,
                scope_kind=scope.value,
            )
            system_binding = self._normalize_question_binding(
                signal.payload,
                taxonomy_type=final_taxonomy,
                text=final_candidate.text,
                canonical_key=canonical_key,
            )
            item = QuestionItem(
                question_id=question_id,
                status="OPEN",
                taxonomy_type=final_taxonomy,
                scope_kind=scope.value,
                canonical_key=canonical_key,
                user_prompt=UserPrompt(
                    text=final_candidate.text,
                    scenario=final_candidate.scenario,
                    why_it_matters="",
                    answer_spec=AnswerSpec(kind=final_candidate.answer_spec_kind),
                ),
                system_binding=system_binding,
                origins=[
                    QuestionOrigin(
                        source_kind=source_kind,
                        trace_id=signal.source.trace_id,
                        signal_id=signal.uq_id,
                        slice_id=signal.source.slice_id,
                        layer=signal.source.layer,
                        created_at=signal.created_at,
                    ),
                ],
                blockers=QuestionBlockers(
                    severity=signal.context.blocking.severity,
                    blocked_slices=list(signal.context.blocking.blocked_slices),
                ),
                quality_gate=QualityGateStatus(
                    status="PASS",
                    attempts=len(records),
                    last_quality_record_id=records[-1].record_id if records else "",
                    last_checked_at=datetime.now(UTC).isoformat(),
                ),
            )

            # Dedup check.
            existing = self._queue.dedup(item, run_agent=self._run_agent)
            if existing is None:
                self._queue.enqueue(item)
            else:
                # Merged into existing item; use existing.
                item = existing
                item.taxonomy_type = final_taxonomy
                item.scope_kind = scope.value
                item.canonical_key = canonical_key
                item.system_binding = system_binding
                item.origins.append(
                    QuestionOrigin(
                        source_kind=source_kind,
                        trace_id=signal.source.trace_id,
                        signal_id=signal.uq_id,
                        slice_id=signal.source.slice_id,
                        layer=signal.source.layer,
                        created_at=signal.created_at,
                    )
                )
                item.user_prompt.why_it_matters = ""
                item.user_prompt.answer_spec.kind = final_candidate.answer_spec_kind
                item.user_prompt.text = final_candidate.text
                item.user_prompt.scenario = final_candidate.scenario
            self._apply_quality_pass_to_item(item, final_candidate, records)
            if item.status == "OPEN" and item.blockers.severity == "BLOCKING":
                self._record_new_blocking_arrival(item.question_id)
        else:
            # 6. FAIL after retries — mark UNASKABLE.
            failed_candidate = final_candidate or candidate
            failed_taxonomy = normalize_user_facing_taxonomy(
                failed_candidate.taxonomy_type,
            )
            failed_text = self._coerce_str(failed_candidate.text, question_text)
            failed_scope_kind = classify_scope(failed_text).value
            canonical_key = self._normalize_canonical_key(
                canonical_key_hint,
                taxonomy_type=failed_taxonomy,
                text=failed_text,
                scope_kind=failed_scope_kind,
            )
            system_binding = self._normalize_question_binding(
                signal.payload,
                taxonomy_type=failed_taxonomy,
                text=failed_text,
                canonical_key=canonical_key,
            )
            item = QuestionItem(
                question_id=question_id,
                status="UNASKABLE",
                taxonomy_type=failed_taxonomy,
                scope_kind=failed_scope_kind,
                canonical_key=canonical_key,
                user_prompt=UserPrompt(
                    text=failed_text,
                    scenario=scenario_from_reframe,
                ),
                system_binding=system_binding,
                quality_gate=QualityGateStatus(
                    status="FAIL",
                    attempts=len(records),
                    last_quality_record_id=records[-1].record_id if records else "",
                    last_checked_at=datetime.now(UTC).isoformat(),
                ),
            )
            logger.info(
                "Signal %s produced UNASKABLE question %s after %d quality gate attempts.",
                signal.uq_id,
                question_id,
                len(records),
            )
            failure_reason = reframe_failure_reason or (
                records[-1].reason if records else "quality gate failed"
            )
            failure_details: dict[str, Any] = {
                "signal_id": signal.uq_id,
                "attempts": len(records),
            }
            if reframe_failure_reason:
                failure_details["classification_status"] = "unclassifiable_prohibited_signal"
                failure_details["original_question_text"] = question_text
            self._mark_unaskable(
                question_id,
                source="ingest_signal",
                reason=failure_reason,
                details=failure_details,
            )
            self._emit_ingest_quality_reformulation(
                signal=signal,
                question_id=question_id,
                canonical_key=canonical_key,
                taxonomy_type=failed_taxonomy,
                question_text=failed_text,
                scenario=scenario_from_reframe,
                reason=failure_reason,
                attempts=len(records),
                details=failure_details,
            )

        # 7. Update signal watermark.
        if update_signal_watermark:
            self._state.watermarks.user_question_signal_watermark = signal.uq_id

        if update_skeleton:
            self._maybe_update_skeleton()
        return item

    # TODO [R2-4.1]: Implement handle_answer(question_id, raw_text, choice_id)
    #   1. Record raw answer provenance
    #   2. Produce AnswerTranslation via AnswerTranslateStrategy
    #   3. Save translation artifact
    #   4. Submit to Planner for ingestion
    #   5. Handle follow-up question drafts (quality gate, recursion budget)
    #   6. Return translation artifact reference
    def handle_answer(
        self,
        question_id: str,
        raw_text: str,
        selected_choice_id: str = "",
    ) -> AnswerTranslation:
        """Handle a user answer to a presented question."""
        self._ensure_initialized()
        assert self._state is not None
        assert self._queue is not None

        # 1. Find the question in the queue.
        question = self._queue.get_item(question_id)
        normalized_choice_id = self._normalize_redefinition_choice_id(selected_choice_id)
        if normalized_choice_id:
            selected_choice_id = normalized_choice_id
        if self._requires_partial_redefinition_details(
            item=question,
            selected_choice_id=selected_choice_id,
            raw_text=raw_text,
        ):
            raise ValueError(
                "Partial redefinition confirmation requires specific change details "
                "in the answer text."
            )

        # Record raw answer provenance.
        now = datetime.now(UTC).isoformat()
        answer_id = f"a_{uuid.uuid4().hex[:12]}"
        provenance = AnswerProvenance(
            answer_id=answer_id,
            question_id=question_id,
            raw_text=raw_text,
            created_at=now,
        )
        self._state.answer_provenance.append(provenance)
        save_answer(self._run_dir, provenance)

        if self._event_log is not None:
            self._event_log.append(
                "answer_recorded",
                {
                    "answer_id": answer_id,
                    "question_id": question_id,
                    "raw_text": raw_text,
                },
            )

        # 2. Produce AnswerTranslation via strategy.
        if self._answer_translate is not None and question is not None:
            pf = self._state.problem_frame
            frame_dict = {
                "current_restatement": pf.current_restatement,
                "goals": list(pf.goals),
            }
            cm = self._state.concept_map
            concept_dict = {
                "user_introduced_terms": list(cm.user_introduced_terms),
            }
            translation = self._answer_translate.translate(
                question_id=question_id,
                taxonomy_type=question.taxonomy_type,
                canonical_key=question.canonical_key,
                user_prompt_text=question.user_prompt.text,
                raw_answer=raw_text,
                selected_choice_id=selected_choice_id,
                problem_frame=frame_dict,
                concept_map=concept_dict,
                recursion_budget=RecursionBudget(max_followups=2, used_followups=0),
                run_agent=self._run_agent,
            )
        else:
            from spec_manager.orchestration.intent_agent.answer_translation import (
                ExtractedContent,
                UserAnswer,
            )

            translation = AnswerTranslation(
                question_id=question_id,
                user_answer=UserAnswer(
                    raw_text=raw_text,
                    selected_choice_id=selected_choice_id,
                ),
                extracted=ExtractedContent(),
            )

        # Set provenance references.
        translation.answer_id = answer_id
        translation.run_id = self._state.run_id
        translation.session_id = self._state.session_id

        # 3. Save translation artifact.
        translation.save(self._run_dir)

        # 4a. Submit to Planner for ingestion through the required planner hook.
        planner_ingest_ok = False
        planner_error = ""
        planner_trace_id = ""
        planner_status = "OK"
        try:
            ingest_result = self._on_translation_saved(translation)
            if isinstance(ingest_result, dict):
                planner_trace_id = str(ingest_result.get("trace_id", "")).strip()
                planner_status = str(ingest_result.get("status", "OK")).upper()
                planner_error = str(ingest_result.get("error", "")).strip()
                if planner_status and planner_status not in {"OK", "NOOP"}:
                    planner_error = planner_error or f"planner status {planner_status}"
            elif ingest_result is None:
                planner_status = "OK"
            elif hasattr(ingest_result, "status"):
                planner_status = str(getattr(ingest_result, "status", "OK")).upper()
                planner_trace_id = str(getattr(ingest_result, "trace_id", "")).strip()
                planner_error = str(getattr(ingest_result, "error", "")).strip()
                if planner_status and planner_status not in {"OK", "NOOP"}:
                    planner_error = planner_error or f"planner status {planner_status}"
            else:
                planner_error = "planner callback returned unsupported response type"
        except Exception:
            logger.warning(
                "on_translation_saved callback failed for translation %s",
                translation.translation_id,
                exc_info=True,
            )
            planner_error = "callback exception"
        if planner_status not in {"OK", "NOOP"}:
            planner_error = planner_error or f"planner status {planner_status}"
        planner_ingest_ok = not planner_error

        provenance.answer_translation_ref = translation.translation_id
        if planner_trace_id:
            provenance.planner_ingest_trace_id = planner_trace_id

        if self._event_log is not None:
            self._event_log.append(
                "translation_produced",
                {
                    "translation_id": translation.translation_id,
                    "question_id": question_id,
                    "planner_status": planner_status,
                    "planner_ingest_ok": planner_ingest_ok,
                    "planner_error": planner_error,
                },
            )

        # 4b. Enqueue follow-ups only when planner ingest succeeded.
        if not planner_ingest_ok:
            logger.warning(
                "Planner ingest failed; question %s remains OPEN pending retry",
                question_id,
            )
            self.save_state()
            return translation

        # 5. Handle follow-up question drafts (quality gate each, enqueue if pass).
        followup_candidates = sorted(
            translation.extracted.followup_question_drafts,
            key=lambda draft: (
                self._coerce_str(draft.canonical_key_hint),
                normalize_taxonomy_type(draft.taxonomy_type),
                self._coerce_str(draft.text),
                self._coerce_str(draft.draft_id),
            ),
        )
        seen_followups: set[tuple[str, str, str, str]] = set()

        for fq_draft in followup_candidates:
            draft_taxonomy = normalize_taxonomy_type(fq_draft.taxonomy_type)
            followup_key = (
                self._coerce_str(fq_draft.canonical_key_hint),
                draft_taxonomy,
                self._coerce_str(fq_draft.text),
                self._coerce_str(fq_draft.scenario),
            )
            if followup_key in seen_followups:
                continue
            seen_followups.add(followup_key)

            fq_taxonomy_enum = QuestionTaxonomy(draft_taxonomy)
            fq_text = self._coerce_str(fq_draft.text)
            fq_scenario = self._coerce_str(fq_draft.scenario)
            if is_prohibited(fq_taxonomy_enum):
                reframe_context = {
                    "question_text": question.user_prompt.text if question is not None else "",
                    "prior_classifications": [question.taxonomy_type]
                    if question is not None
                    else [],
                    "domain_hints": list(self._state.concept_map.user_introduced_terms),
                }
                reframed_followup = reframe_to_user_valid(
                    fq_text,
                    fq_taxonomy_enum,
                    context=reframe_context,
                    run_agent=self._run_agent,
                )
                if reframed_followup is None:
                    fq_id = f"q_{uuid.uuid4().hex[:12]}"
                    reframe_reason = (
                        "Prohibited follow-up taxonomy could not be reframed to a user-valid type."
                    )
                    self._mark_unaskable(
                        fq_id,
                        source="followup_question",
                        reason=reframe_reason,
                        details={
                            "translation_id": translation.translation_id,
                            "parent_question_id": question_id,
                            "original_taxonomy_type": fq_taxonomy_enum.value,
                            "attempts": 0,
                        },
                    )
                    self._emit_followup_quality_reformulation(
                        parent_question_id=question_id,
                        draft=fq_draft,
                        records=[],
                        reason_override=reframe_reason,
                    )
                    continue
                fq_text = self._coerce_str(reframed_followup.reframed_text, fq_text)
                fq_scenario = self._coerce_str(reframed_followup.scenario, fq_scenario)
                fq_taxonomy_enum = reframed_followup.reframed_type

            fq_taxonomy = normalize_user_facing_taxonomy(fq_taxonomy_enum.value)
            fq_answer_spec_kind = self._coerce_answer_spec_kind(
                fq_draft.answer_spec.get("kind", "choice"),
            )

            fq_candidate = QualityCheckCandidate(
                text=fq_text,
                scenario=fq_scenario,
                answer_spec_kind=fq_answer_spec_kind,
                taxonomy_type=fq_taxonomy,
            )
            fq_id = f"q_{uuid.uuid4().hex[:12]}"
            concept_terms = list(self._state.concept_map.user_introduced_terms)

            fq_final, fq_records, fq_passed = enforce_quality_gate(
                fq_candidate,
                fq_id,
                concept_map_user_terms=concept_terms,
                validator=self._quality_validator,
                repairer=self._question_repairer,
                run_agent=self._run_agent,
                event_log=self._event_log,
            )

            if fq_passed and fq_final is not None:
                fq_final.taxonomy_type = normalize_user_facing_taxonomy(fq_final.taxonomy_type)
                fq_final.answer_spec_kind = self._coerce_answer_spec_kind(
                    fq_final.answer_spec_kind,
                )
                scope = classify_scope(fq_final.text)
                canonical_key = self._normalize_canonical_key(
                    fq_draft.canonical_key_hint,
                    taxonomy_type=fq_final.taxonomy_type,
                    text=fq_final.text,
                    scope_kind=scope.value,
                )
                fq_item = QuestionItem(
                    question_id=fq_id,
                    status="OPEN",
                    taxonomy_type=fq_final.taxonomy_type,
                    scope_kind=scope.value,
                    canonical_key=canonical_key,
                    user_prompt=UserPrompt(
                        text=fq_final.text,
                        scenario=fq_final.scenario,
                        answer_spec=AnswerSpec(kind=fq_final.answer_spec_kind),
                    ),
                    system_binding=self._normalize_question_binding(
                        {},
                        taxonomy_type=fq_final.taxonomy_type,
                        text=fq_final.text,
                        canonical_key=canonical_key,
                    ),
                    origins=[
                        QuestionOrigin(
                            source_kind="INTENT_AGENT",
                            trace_id=translation.translation_id,
                            created_at=datetime.now(UTC).isoformat(),
                        ),
                    ],
                    quality_gate=QualityGateStatus(
                        status="PASS",
                        attempts=len(fq_records),
                        last_quality_record_id=fq_records[-1].record_id if fq_records else "",
                        last_checked_at=datetime.now(UTC).isoformat(),
                    ),
                )
                existing = self._queue.dedup(fq_item, run_agent=self._run_agent)
                if existing is None:
                    self._queue.enqueue(fq_item)
                    item = fq_item
                else:
                    item = existing
                    if item.status == "UNASKABLE":
                        item.status = "OPEN"
                self._apply_quality_pass_to_item(item, fq_final, fq_records)
            else:
                self._mark_unaskable(
                    fq_id,
                    source="followup_question",
                    reason=(fq_records[-1].reason if fq_records else "quality gate failed"),
                    details={
                        "translation_id": translation.translation_id,
                        "parent_question_id": question_id,
                        "attempts": len(fq_records),
                    },
                )
                self._emit_followup_quality_reformulation(
                    parent_question_id=question_id,
                    draft=fq_draft,
                    records=fq_records,
                )

        # Constraint coverage may change after follow-up enqueueing.
        self._maybe_update_skeleton()

        # Persist state.
        self.save_state()

        # 6. Return the translation.
        return translation

    # TODO [R2-2.3]: Implement handle_planner_updates() — reassessment trigger
    #   1. Read new planner updates since watermark
    #   2. Run mechanical pass (canonical_key match → ANSWERED, blockers cleared → STALE)
    #   3. Run LLM reassess pass for remaining ambiguous OPEN questions
    #   4. Apply actions to queue
    #   5. Update watermark
    def _empty_reassessment_result(self, run_id: str, session_id: str) -> dict[str, Any]:
        return {
            "version": 1,
            "run_id": run_id,
            "session_id": session_id,
            "trigger": {"kind": "USER_ANSWER_INGESTED", "ref": ""},
            "created_at": datetime.now(UTC).isoformat(),
            "actions": [],
        }

    def _coerce_update_ids(self, raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw] if raw else []
        if isinstance(raw, list):
            return [str(item) for item in raw if str(item)]
        return []

    def _resolve_update_canonical_keys(
        self,
        update: dict[str, Any],
        question_key_map: dict[str, Any],
    ) -> list[str]:
        cids = self._coerce_update_ids(update.get("constraint_ids", []))
        if not cids:
            cids = self._coerce_update_ids(update.get("constraint_id", ""))

        dids = self._coerce_update_ids(update.get("decision_ids", []))
        if not dids:
            dids = self._coerce_update_ids(update.get("decision_id", ""))

        canonical_candidates_set = set(self._coerce_update_ids(update.get("canonical_key", "")))
        if canonical_candidates_set:
            return list(canonical_candidates_set)

        canonical_update_constraint_ids = set(cids)
        canonical_update_decision_ids = set(dids)
        for key_ref in question_key_map.values():
            if isinstance(key_ref, dict):
                raw_canonical = str(key_ref.get("canonical_key", "")).strip()
                constraint_ids = key_ref.get("planner_constraint_ids", [])
                decision_ids = key_ref.get("planner_decision_ids", [])
            else:
                raw_canonical = str(getattr(key_ref, "canonical_key", "")).strip()
                constraint_ids = getattr(key_ref, "planner_constraint_ids", [])
                decision_ids = getattr(key_ref, "planner_decision_ids", [])

            if not raw_canonical:
                continue

            ref_ids = set(self._coerce_update_ids(constraint_ids)) | set(
                self._coerce_update_ids(decision_ids)
            )
            if canonical_update_constraint_ids & ref_ids or canonical_update_decision_ids & ref_ids:
                canonical_candidates_set.add(raw_canonical)

        return list(canonical_candidates_set)

    def _reconcile_question_key_map(
        self,
        updates: list[dict[str, Any]],
        question_key_map: dict[str, Any],
    ) -> None:
        for update in updates:
            if not isinstance(update, dict):
                continue

            cids = self._coerce_update_ids(update.get("constraint_ids", []))
            if not cids:
                cids = self._coerce_update_ids(update.get("constraint_id", ""))

            dids = self._coerce_update_ids(update.get("decision_ids", []))
            if not dids:
                dids = self._coerce_update_ids(update.get("decision_id", ""))

            canonical_keys = self._resolve_update_canonical_keys(update, question_key_map)
            if not canonical_keys:
                logger.warning(
                    "No canonical key resolved for planner update %s; update cannot be "
                    "applied to question_key_map",
                    json.dumps(update, sort_keys=True),
                )
                continue

            for canonical_key in canonical_keys:
                if not canonical_key:
                    continue
                if canonical_key in question_key_map:
                    ref = question_key_map[canonical_key]
                    ref.planner_constraint_ids = list(set(ref.planner_constraint_ids) | set(cids))
                    ref.planner_decision_ids = list(set(ref.planner_decision_ids) | set(dids))
                else:
                    from spec_manager.orchestration.intent_agent.state import QuestionKeyRef

                    question_key_map[canonical_key] = QuestionKeyRef(
                        canonical_key=canonical_key,
                        planner_constraint_ids=list(set(cids)),
                        planner_decision_ids=list(set(dids)),
                    )

    def _apply_redefinition_updates(self, updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for update in updates:
            if not isinstance(update, dict):
                continue

            update_type = self._coerce_redefinition_update_type(update)
            if update_type not in {"problem_redefinition", "alignment_violation"}:
                continue
            if not self._is_authorized_redefinition_update(update, update_type=update_type):
                continue

            replacement_action = self._coerce_str(update.get("action"), "").upper()
            replacement_requested = replacement_action in {
                "REPLACE",
                "SUPERSEDE",
                "SUPERSEDED",
                "REPLACED",
            }
            replacement_payload = update.get("replacement")
            replacement_hint = (
                self._coerce_str(update.get("replace_question_id"))
                or self._coerce_str(update.get("replaces_question_id"))
                or self._coerce_str(update.get("supersedes_question_id"))
                or self._coerce_str(update.get("question_id"))
            )
            trigger_question_id = self._coerce_str(update.get("question_id"))
            try:
                redefined = self.handle_redefinition(update)
            except Exception:
                logger.warning(
                    "Failed to process redefinition planner update %s",
                    json.dumps(update, sort_keys=True),
                    exc_info=True,
                )
                continue

            action = "REDEFINITION"
            if replacement_requested and (
                (replacement_hint and redefined.question_id != replacement_hint)
                or (
                    isinstance(replacement_payload, dict)
                    and (
                        self._coerce_str(replacement_payload.get("new_question_id"))
                        or self._coerce_str(replacement_payload.get("new_canonical_key"))
                    )
                )
                or (trigger_question_id and redefined.question_id != trigger_question_id)
            ):
                action = "REPLACE"

            actions.append(
                {
                    "question_id": redefined.question_id,
                    "action": action,
                    "reason": self._coerce_str(
                        update.get("reason"),
                        f"Planner update triggered redefinition ({update_type})",
                    ),
                    "redefinition_type": update_type,
                    "event_id": self._coerce_str(update.get("event_id")),
                    "source": self._coerce_str(update.get("source", "PLANNER")),
                }
            )
        return actions

    def _run_mechanical_reassess_pass(
        self,
        updates: list[dict[str, Any]],
        question_key_map: dict[str, Any],
        *,
        run_id: str,
        session_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        assert self._queue is not None
        projected_updates = self._project_reassess_planner_updates(updates)
        projected_question_key_map = self._project_reassess_question_key_map(question_key_map)
        reassessment = self._queue.reassess(
            projected_updates,
            projected_question_key_map,
            run_id=run_id,
            session_id=session_id,
        )
        actions = [dict(item) for item in reassessment.get("actions", []) if isinstance(item, dict)]
        return reassessment, actions

    def _run_llm_reassess_pass(
        self,
        updates: list[dict[str, Any]],
        valid_actions: set[str],
    ) -> list[dict[str, Any]]:
        if self._queue is None or self._state is None or self._queue_reassess is None:
            return []
        remaining_open = self._queue.get_open_items()
        if not remaining_open:
            return []

        open_dicts = [
            {
                "question_id": item.question_id,
                "canonical_key": item.canonical_key,
                "text": item.user_prompt.text,
                "taxonomy_type": item.taxonomy_type,
            }
            for item in remaining_open
        ]
        pf = self._state.problem_frame
        frame_dict = {
            "current_restatement": pf.current_restatement,
            "goals": list(pf.goals),
        }
        reassess_results = self._queue_reassess.reassess(
            open_dicts,
            frame_dict,
            updates,
            run_agent=self._run_agent,
        )

        actions: list[dict[str, Any]] = []
        for result in reassess_results:
            if not isinstance(result, dict):
                continue
            question_id = str(result.get("question_id", "")).strip()
            if not question_id:
                continue
            action = str(result.get("action", "KEEP")).strip().upper()
            if action not in valid_actions:
                action = "KEEP"
            reason = str(result.get("reason", "")).strip()
            action_record: dict[str, Any] = {
                "question_id": question_id,
                "action": action,
                "reason": reason,
            }
            for passthrough_key in (
                "auto_resolution",
                "resolution",
                "resolution_evidence",
                "eligibility",
                "authority",
                "payload",
                "confidence",
                "confidence_checked",
                "confident_inference",
                "tool_resolvable",
                "research_resolvable",
                "ambiguity_safe",
                "review_required",
                "human_authority_required",
                "authority_required",
                "resolution_method",
            ):
                if passthrough_key in result:
                    action_record[passthrough_key] = result[passthrough_key]

            replacement = result.get("replacement")
            if isinstance(replacement, dict):
                action_record["replacement"] = {
                    "new_question_id": str(replacement.get("new_question_id", "")),
                    "new_canonical_key": str(replacement.get("new_canonical_key", "")),
                    "new_user_prompt_text": str(replacement.get("new_user_prompt_text", "")),
                }
            item = self._queue.get_item(question_id)

            if action == "KEEP":
                actions.append(action_record)
                continue

            if action in {"SUPERSEDED", "REPLACE"} and item is not None and item.status == "OPEN":
                if self._queue.set_status(item.question_id, "SUPERSEDED", reason):
                    if action == "REPLACE" and replacement and isinstance(replacement, dict):
                        replacement_question_id = self._spawn_replacement_question(
                            item,
                            {
                                "new_question_id": self._coerce_str(
                                    replacement.get("new_question_id"),
                                ),
                                "new_canonical_key": self._coerce_str(
                                    replacement.get("new_canonical_key"),
                                    item.canonical_key,
                                ),
                                "new_user_prompt_text": self._coerce_str(
                                    replacement.get("new_user_prompt_text"),
                                    item.user_prompt.text,
                                ),
                            },
                            reason=reason,
                        )
                        if replacement_question_id:
                            action_record["replacement"] = {
                                "new_question_id": replacement_question_id,
                                "new_canonical_key": self._coerce_str(
                                    replacement.get("new_canonical_key"),
                                    item.canonical_key,
                                ),
                                "new_user_prompt_text": self._coerce_str(
                                    replacement.get("new_user_prompt_text"),
                                ),
                            }
                            action_record["action"] = "REPLACE"
                            actions.append(action_record)
                            continue
                    actions.append(action_record)
                continue

            if action == "REWORD":
                if (
                    item is not None
                    and item.status == "OPEN"
                    and replacement
                    and isinstance(replacement, dict)
                ):
                    prompt_text = str(replacement.get("new_user_prompt_text", "")).strip()
                    if prompt_text:
                        item.user_prompt.text = prompt_text
                    new_canonical_key = str(replacement.get("new_canonical_key", "")).strip()
                    if new_canonical_key:
                        item.canonical_key = self._normalize_canonical_key(
                            new_canonical_key,
                            taxonomy_type=item.taxonomy_type,
                            text=item.user_prompt.text,
                            scope_kind=item.scope_kind,
                        )
                actions.append(action_record)
                continue

            if action == "ANSWERED" and item is not None and item.status == "OPEN":
                if self._queue.mark_answered(question_id, reason):
                    actions.append(action_record)
                continue

            if action in {"STALE", "DISMISSED"} and item is not None and item.status == "OPEN":
                if self._queue.set_status(question_id, action, reason):
                    actions.append(action_record)
                continue

        return actions

    def _dedupe_reassess_actions(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen_action_keys: set[tuple[str, str]] = set()
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_key = (str(action.get("question_id", "")), str(action.get("action", "")))
            if action_key in seen_action_keys:
                continue
            seen_action_keys.add(action_key)
            deduped.append(action)
        return deduped

    def _update_planner_watermark(self, updates: list[dict[str, Any]]) -> None:
        if self._state is None:
            return
        latest_ts = ""
        for update in updates:
            ts = update.get("created_at", "")
            if ts > latest_ts:
                latest_ts = ts
        if latest_ts:
            self._state.watermarks.planner_update_watermark = latest_ts

    def _persist_reassess_result(self, reassessment: dict[str, Any]) -> None:
        reassess_dir = self._run_dir / "intent" / "reassess_results"
        reassess_dir.mkdir(parents=True, exist_ok=True)
        reassess_path = (
            reassess_dir / f"reassess_{reassessment['created_at'].replace(':', '-')}.json"
        )
        try:
            reassess_path.write_text(json.dumps(reassessment, indent=2), encoding="utf-8")
        except Exception:
            logger.debug("Failed to persist QueueReassessResult", exc_info=True)

    def handle_planner_updates(self) -> dict[str, Any]:
        """Process new Planner updates and reassess queue."""
        if self._state is None or self._queue is None or self._planner_store is None:
            return self._empty_reassessment_result("", "")

        run_id = self._state.run_id
        session_id = self._state.session_id

        # 1. Read new planner updates since watermark.
        watermark = self._state.watermarks.planner_update_watermark
        raw_updates = self._planner_store.read_since(watermark)
        if not raw_updates:
            reassessment = self._empty_reassessment_result(run_id, session_id)
            reassessment["resume_progress_summary"] = ResumeProgressSummaryProjection(
                planner_watermark=watermark,
            ).to_dict()
            return reassessment
        new_updates = [update.to_dict() for update in raw_updates]
        if not new_updates:
            reassessment = self._empty_reassessment_result(run_id, session_id)
            reassessment["resume_progress_summary"] = ResumeProgressSummaryProjection(
                planner_watermark=watermark,
            ).to_dict()
            return reassessment

        if self._event_log is not None:
            for update in new_updates:
                self._event_log.append(
                    "planner_update_received",
                    {
                        "event_kind": self._coerce_str(
                            update.get("event_kind", update.get("type", "unknown")),
                            "unknown",
                        ),
                        "event_id": self._coerce_str(update.get("event_id")),
                        "created_at": self._coerce_str(update.get("created_at")),
                    },
                )

        valid_actions = {
            "KEEP",
            "ANSWERED",
            "STALE",
            "SUPERSEDED",
            "REWORD",
            "DISMISSED",
            "REDEFINITION",
            "REPLACE",
        }

        question_key_map = self._state.question_key_map
        self._reconcile_question_key_map(new_updates, question_key_map)

        all_actions: list[dict[str, Any]] = []
        all_actions.extend(self._apply_redefinition_updates(new_updates))
        authoritative_frame_updates = self._apply_authoritative_problem_frame_updates(new_updates)

        reassessment, mechanical_actions = self._run_mechanical_reassess_pass(
            new_updates,
            question_key_map,
            run_id=run_id,
            session_id=session_id,
        )
        all_actions.extend(mechanical_actions)

        llm_actions = self._run_llm_reassess_pass(new_updates, valid_actions)
        all_actions.extend(llm_actions)

        reassessment["actions"] = self._dedupe_reassess_actions(all_actions)
        auto_outcomes = self._apply_auto_mode_planner_outcomes(new_updates, reassessment)
        for question_id in auto_outcomes["review_decision_question_ids"]:
            reassessment["actions"].append(
                {
                    "question_id": question_id,
                    "action": "REVIEW_DECISION",
                    "reason": "decision taken without user authority",
                }
            )
        reassessment["actions"] = self._dedupe_reassess_actions(reassessment["actions"])
        if auto_outcomes["review_decision_question_ids"]:
            self._refresh_question_queue_state()

        # 4. Update planner watermark to the latest update's created_at.
        self._update_planner_watermark(new_updates)
        self._refresh_question_queue_state()
        reassessment["version"] = 1
        reassessment["run_id"] = run_id
        reassessment["session_id"] = session_id
        resume_progress = self._build_resume_progress_summary(new_updates, reassessment)
        resume_progress._passthrough_fields["authoritative_problem_frame_updates"] = (
            authoritative_frame_updates
        )
        resume_progress._passthrough_fields.update(auto_outcomes)
        reassessment["resume_progress_summary"] = resume_progress.to_dict()
        self._state.question_queue_state._passthrough_fields["resume_progress_summary"] = (
            resume_progress.to_dict()
        )

        self._persist_reassess_result(reassessment)

        if self._event_log is not None:
            self._event_log.append(
                "queue_reassess",
                {
                    "actions": reassessment["actions"],
                },
            )

        self._maybe_update_skeleton()
        return reassessment

    # TODO [R2-3.4]: Implement next_action() — decide what to present
    #   - If queue empty → return None (or produce skeleton if ready)
    #   - Immediate ask: if queue has BLOCKING and current is INFO
    #   - Default: return next_question() from queue
    def next_action(self) -> dict[str, Any] | None:
        """Determine the next action (ask question, produce skeleton, wait).

        Per response2.md Section 3.4 immediate-ask rule: if the queue has a
        BLOCKING question and the last presented question was INFO, the
        BLOCKING question preempts.
        """
        if self._queue is None:
            return {"action": "wait"}

        # Check for skeleton readiness if no open questions.
        open_items = self._queue.get_open_items()
        if not open_items:
            if self._is_ready_for_skeleton():
                return {"action": "skeleton"}
            return {"action": "wait"}

        # Immediate-ask rule applies only to newly-arrived BLOCKING questions.
        newly_arrived_blocking_ids = (
            self._consume_new_blocking_arrivals() if self._state is not None else []
        )
        if newly_arrived_blocking_ids and self._state is not None:
            arrival_set = set(newly_arrived_blocking_ids)
            blocking_items = [
                item
                for item in open_items
                if item.question_id in arrival_set and item.blockers.severity == "BLOCKING"
            ]
        else:
            blocking_items = []

        if blocking_items and self._state is not None:
            queue_state = self._state.question_queue_state
            last_presented_id = self._coerce_str(queue_state.last_presented_question_id)
            last_item = self._queue.get_item(last_presented_id) if last_presented_id else None
            queue_is_idle = last_item is None
            last_was_info = last_item is not None and last_item.blockers.severity == "INFO"
            if queue_is_idle or last_was_info:
                # Preempt: present the highest-priority BLOCKING question
                next_q = blocking_items[0]
                queue_state.last_presented_question_id = next_q.question_id
                queue_state.active_batch_id = ""
                action = {
                    "action": "ask",
                    "question": next_q.to_dict(),
                    "question_id": next_q.question_id,
                    "immediate_ask": True,
                }
                return self._finalize_prompt_action(action)

        # Get the next question (default priority ordering).
        next_q = self._queue.next_question(run_agent=self._run_agent)
        if next_q is None:
            return {"action": "wait"}

        # Track last presented question in state.
        if self._state is not None:
            self._state.question_queue_state.last_presented_question_id = next_q.question_id
            self._state.question_queue_state.active_batch_id = ""

        action = {
            "action": "ask",
            "question": next_q.to_dict(),
            "question_id": next_q.question_id,
        }
        return self._finalize_prompt_action(action)

    # TODO [R2-5.3]: Implement handle_vague_input(text) — vague input handler
    #   - If user input is vague, ask a single INTENT question that
    #     disambiguates between plausible frames
    #   - Must be scenario-grounded and bounded (choice set)
    def handle_vague_input(self, text: str) -> QuestionItem:
        """Handle vague user input by asking a disambiguating INTENT question."""
        self._ensure_initialized()
        assert self._state is not None
        assert self._queue is not None

        question_id = f"q_{uuid.uuid4().hex[:12]}"

        # Draft a disambiguating INTENT question.
        if self._question_draft is not None:
            candidate = self._question_draft.draft(
                signal_text=text,
                taxonomy_hint="INTENT",
                canonical_key_hint="intent.disambiguation",
                context={"vague_input": text},
                run_agent=self._run_agent,
            )
        else:
            default_choices = self._default_vague_intent_choices()
            candidate = QualityCheckCandidate(
                text=self._ensure_choice_prompt_text(
                    "Your input could be interpreted in different ways. Which is closest to what "
                    "you mean right now?",
                    default_choices,
                ),
                scenario=f'You said: "{text}"',
                answer_spec_kind="choice",
                taxonomy_type="INTENT",
            )
        candidate.answer_spec_kind = "choice"
        parsed_candidate_choices = self._extract_choice_specs_from_prompt(candidate.text)
        if not parsed_candidate_choices:
            default_choices = self._default_vague_intent_choices()
            candidate.text = self._ensure_choice_prompt_text(candidate.text, default_choices)
            parsed_candidate_choices = default_choices

        # Quality gate.
        concept_terms = list(self._state.concept_map.user_introduced_terms)
        final_candidate, records, passed = enforce_quality_gate(
            candidate,
            question_id,
            concept_map_user_terms=concept_terms,
            validator=self._quality_validator,
            repairer=self._question_repairer,
            run_agent=self._run_agent,
            event_log=self._event_log,
        )

        used_candidate = final_candidate if passed and final_candidate else candidate
        used_candidate.answer_spec_kind = "choice"
        parsed_choices = self._extract_choice_specs_from_prompt(used_candidate.text)
        if not parsed_choices:
            parsed_choices = parsed_candidate_choices or self._default_vague_intent_choices()
            used_candidate.text = self._ensure_choice_prompt_text(
                used_candidate.text,
                parsed_choices,
            )
        used_candidate_taxonomy = normalize_user_facing_taxonomy("INTENT")
        canonical_key = self._normalize_canonical_key(
            "intent.disambiguation",
            taxonomy_type=used_candidate_taxonomy,
            text=used_candidate.text,
            scope_kind="SYSTEM_WIDE",
        )

        item = QuestionItem(
            question_id=question_id,
            status="OPEN" if passed else "UNASKABLE",
            taxonomy_type=used_candidate_taxonomy,
            scope_kind="SYSTEM_WIDE",
            canonical_key=canonical_key,
            user_prompt=UserPrompt(
                text=used_candidate.text,
                scenario=used_candidate.scenario,
                answer_spec=AnswerSpec(
                    kind="choice",
                    choices=parsed_choices,
                ),
            ),
            origins=[
                QuestionOrigin(
                    source_kind="INTENT_AGENT",
                    created_at=datetime.now(UTC).isoformat(),
                ),
            ],
            quality_gate=QualityGateStatus(
                status="PASS" if passed else "FAIL",
                attempts=len(records),
                last_quality_record_id=records[-1].record_id if records else "",
                last_checked_at=datetime.now(UTC).isoformat(),
            ),
        )

        # Enqueue (dedup first).
        if passed:
            existing = self._queue.dedup(item, run_agent=self._run_agent)
            if existing is None:
                self._queue.enqueue(item)
            else:
                item = existing
                self._apply_quality_pass_to_item(item, used_candidate, records)
        else:
            failure_reason = records[-1].reason if records else "quality gate failed"
            failure_details = {
                "text": text,
                "attempts": len(records),
            }
            self._mark_unaskable(
                question_id,
                source="vague_input",
                reason=failure_reason,
                details=failure_details,
            )
            self._emit_quality_gate_reformulation(
                question_id=question_id,
                canonical_key=canonical_key,
                taxonomy_type=used_candidate_taxonomy,
                question_text=used_candidate.text,
                source="vague_input",
                reason=failure_reason,
                details=failure_details,
            )

        return item

    # TODO [R2-7.1/7.2]: Implement handle_redefinition(trigger) — problem redefinition
    #   - Triggered by Planner (scope change, requirement conflict, etc.)
    #   - Produce a single queue item showing:
    #     original intent, current restatement, what changed (1-3 bullets)
    #   - Ask bounded confirmation: adopt new / keep original / partial
    #   - Authoritative only after Planner ingests the AnswerTranslation
    def handle_redefinition(self, trigger: dict[str, Any]) -> QuestionItem:
        """Handle a problem redefinition trigger from Planner."""
        self._ensure_initialized()
        assert self._state is not None
        assert self._queue is not None

        self._sync_alignment_invariants(trigger)

        trigger_type = self._coerce_redefinition_update_type(trigger) or "problem_redefinition"
        if not self._is_authorized_redefinition_update(trigger, update_type=trigger_type):
            source = self._coerce_str(trigger.get("source"), "PLANNER").upper()
            raise ValueError(f"Unauthorized redefinition source: {source}")
        stage = self._coerce_str(trigger.get("stage"), "")

        canonical_key = self._coerce_str(trigger.get("canonical_key"), "")
        if not canonical_key:
            if stage:
                canonical_key = f"intent.redefinition.{stage}"
            elif trigger_type == "alignment_violation":
                canonical_key = "intent.alignment_violation"
            else:
                canonical_key = "intent.redefinition"

        question_type = self._coerce_redefinition_question_type(
            trigger,
            trigger_type=trigger_type,
            stage=stage,
            canonical_key=canonical_key,
        )

        stage_text = f" Stage: {stage}." if stage else ""

        changed_items = self._coerce_str_list(trigger.get("what_changed"))
        if not changed_items:
            trigger_reason = self._coerce_str(trigger.get("reason"))
            if trigger_reason:
                changed_items = [trigger_reason]

        if not changed_items:
            changed_items = [
                "Planner identified a material scope/requirement shift.",
            ]

        if len(changed_items) > 3:
            changed_items = changed_items[:3]

        scope_kind = self._coerce_str(trigger.get("scope_kind"), "SYSTEM_WIDE").upper()
        if scope_kind not in {"SYSTEM_WIDE", "FEATURE_SPECIFIC"}:
            scope_kind = "SYSTEM_WIDE"
        canonical_key = self._normalize_canonical_key(
            canonical_key,
            taxonomy_type=question_type,
            text=stage or trigger_type,
            scope_kind=scope_kind,
        )

        existing_id = self._coerce_str(trigger.get("question_id"), "")
        replacement_id = self._coerce_str(
            trigger.get("replace_question_id"),
            self._coerce_str(
                trigger.get("replaces_question_id"),
                self._coerce_str(
                    trigger.get("supersedes_question_id"),
                    existing_id,
                ),
            ),
        )
        existing_item = None
        replacement_payload = trigger.get("replacement")
        replacement_action = self._coerce_str(trigger.get("action")).upper()
        replacement_requested = replacement_action in {
            "REPLACE",
            "SUPERSEDE",
            "SUPERSEDED",
            "REPLACED",
        }

        if replacement_id:
            existing_item = self._find_open_queue_item(question_id=replacement_id)
        if existing_item is None and existing_id:
            existing_item = self._find_open_queue_item(question_id=existing_id)
        if existing_item is None:
            existing_item = self._find_open_queue_item(canonical_key=canonical_key)

        question_id = existing_id
        if not question_id:
            question_id = f"q_{uuid.uuid4().hex[:12]}"

        source_text = self._canonical_origin_kind(
            self._coerce_str(trigger.get("source"), "PLANNER"),
            field_name="redefinition.source",
        )

        source_trace = self._coerce_str(
            trigger.get("event_id"),
            self._coerce_str(trigger.get("trace_id"), ""),
        )
        original_intent = self._state.original_intent.user_statement
        change_bullets = "\n".join(f"- {c}" for c in changed_items)

        scenario_text = (
            f"Original intent: {original_intent}\n"
            f"Current restatement: {self._state.problem_frame.current_restatement}\n"
            f"What changed:{stage_text}\n{change_bullets}"
        )

        default_prompt = (
            "Planner identified a material shift in framing. Confirm which framing to use."
        )
        if trigger_type == "alignment_violation":
            default_prompt = (
                "A proposed plan conflicts with current alignment invariants. "
                "Confirm which direction to commit to."
            )

        parsed_choices = self._redefinition_protocol_choices()
        user_text = self._coerce_str(trigger.get("question_text"), default_prompt)
        user_text = self._ensure_choice_prompt_text(user_text, parsed_choices)

        trigger_key = self._coerce_str(trigger.get("event_id"), "")

        if existing_item is not None:
            existing_item.system_binding = self._build_redefinition_binding(
                existing_item.system_binding,
                taxonomy_type=question_type,
                text=user_text,
                canonical_key=canonical_key,
            )
            if isinstance(replacement_payload, dict) and (
                replacement_requested
                or self._coerce_str(replacement_payload.get("new_user_prompt_text"))
                or self._coerce_str(replacement_payload.get("new_canonical_key"))
                or self._coerce_str(replacement_payload.get("new_question_id"))
            ):
                replacement_text = self._coerce_str(
                    replacement_payload.get("new_user_prompt_text"),
                    user_text,
                )
                replacement_key = self._coerce_str(
                    replacement_payload.get("new_canonical_key"),
                    existing_item.canonical_key,
                )
                replacement_reason = self._coerce_str(
                    trigger.get("reason"),
                    f"Problem redefinition update {trigger_key}",
                )
                replacement_question_id = self._spawn_replacement_question(
                    existing_item,
                    {
                        "new_question_id": self._coerce_str(
                            replacement_payload.get("new_question_id")
                        ),
                        "new_canonical_key": replacement_key,
                        "new_user_prompt_text": replacement_text,
                    },
                    reason=replacement_reason,
                )
                if replacement_question_id:
                    if (
                        replacement_question_id != existing_item.question_id
                        and existing_item.status == "OPEN"
                    ):
                        self._queue.set_status(
                            existing_item.question_id,
                            "SUPERSEDED",
                            replacement_reason,
                        )
                    replacement_item = self._queue.get_item(replacement_question_id)
                    if replacement_item is not None:
                        return replacement_item

            concept_terms = list(self._state.concept_map.user_introduced_terms)
            final_candidate, records, passed = enforce_quality_gate(
                QualityCheckCandidate(
                    text=user_text,
                    scenario=scenario_text,
                    answer_spec_kind="choice",
                    taxonomy_type=question_type,
                ),
                existing_item.question_id,
                concept_map_user_terms=concept_terms,
                validator=self._quality_validator,
                repairer=self._question_repairer,
                run_agent=self._run_agent,
                event_log=self._event_log,
            )

            if not passed or final_candidate is None:
                failure_reason = records[-1].reason if records else "quality gate failed"
                failure_details = {
                    "attempts": len(records),
                    "redefinition_trigger": trigger_key,
                }
                existing_item.status = "UNASKABLE"
                existing_item.quality_gate.status = "FAIL"
                existing_item.quality_gate.attempts = len(records)
                existing_item.quality_gate.last_quality_record_id = (
                    records[-1].record_id if records else ""
                )
                existing_item.quality_gate.last_checked_at = datetime.now(UTC).isoformat()
                existing_item.timestamps["updated_at"] = existing_item.quality_gate.last_checked_at
                self._mark_unaskable(
                    existing_item.question_id,
                    source="redefinition",
                    reason=failure_reason,
                    details=failure_details,
                )
                self._emit_quality_gate_reformulation(
                    question_id=existing_item.question_id,
                    canonical_key=canonical_key,
                    taxonomy_type=question_type,
                    question_text=user_text,
                    source="redefinition",
                    reason=failure_reason,
                    details=failure_details,
                )
                return existing_item

            if existing_item.status != "OPEN":
                existing_item.status = "OPEN"
            existing_item.taxonomy_type = question_type
            existing_item.scope_kind = scope_kind
            existing_item.canonical_key = canonical_key
            existing_item.user_prompt.text = self._coerce_str(final_candidate.text, user_text)
            existing_item.user_prompt.scenario = self._coerce_str(
                final_candidate.scenario,
                scenario_text,
            )
            existing_item.user_prompt.why_it_matters = (
                "This affects scope, tradeoffs, or project direction."
            )
            existing_item.user_prompt.answer_spec = AnswerSpec(
                kind="choice",
                choices=parsed_choices,
            )
            existing_item.blockers.severity = "BLOCKING"
            existing_item.system_binding = self._build_redefinition_binding(
                existing_item.system_binding,
                taxonomy_type=question_type,
                text=existing_item.user_prompt.text,
                canonical_key=canonical_key,
            )
            existing_item.quality_gate.status = "PASS"
            existing_item.quality_gate.attempts = len(records)
            existing_item.quality_gate.last_quality_record_id = (
                records[-1].record_id if records else ""
            )
            existing_item.quality_gate.last_checked_at = datetime.now(UTC).isoformat()
            existing_item.timestamps["updated_at"] = existing_item.quality_gate.last_checked_at
            existing_item.origins.append(
                QuestionOrigin(
                    source_kind=source_text,
                    trace_id=source_trace,
                    created_at=datetime.now(UTC).isoformat(),
                )
            )
            return existing_item

        concept_terms = list(self._state.concept_map.user_introduced_terms)
        final_candidate, records, passed = enforce_quality_gate(
            QualityCheckCandidate(
                text=user_text,
                scenario=scenario_text,
                answer_spec_kind="choice",
                taxonomy_type=question_type,
            ),
            question_id,
            concept_map_user_terms=concept_terms,
            validator=self._quality_validator,
            repairer=self._question_repairer,
            run_agent=self._run_agent,
            event_log=self._event_log,
        )

        if not passed or final_candidate is None:
            failed_candidate = final_candidate or QualityCheckCandidate(
                text=user_text,
                scenario=scenario_text,
                answer_spec_kind="choice",
                taxonomy_type=question_type,
            )
            item = QuestionItem(
                question_id=question_id,
                status="UNASKABLE",
                taxonomy_type=question_type,
                scope_kind=scope_kind,
                canonical_key=canonical_key,
                user_prompt=UserPrompt(
                    text=self._coerce_str(failed_candidate.text, user_text),
                    scenario=self._coerce_str(failed_candidate.scenario, scenario_text),
                    why_it_matters="This affects scope, tradeoffs, or project direction.",
                    answer_spec=AnswerSpec(
                        kind="choice",
                        choices=parsed_choices,
                    ),
                ),
                system_binding=self._build_redefinition_binding(
                    {},
                    taxonomy_type=question_type,
                    text=self._coerce_str(failed_candidate.text, user_text),
                    canonical_key=canonical_key,
                ),
                origins=[
                    QuestionOrigin(
                        source_kind=source_text,
                        trace_id=source_trace,
                        created_at=datetime.now(UTC).isoformat(),
                    ),
                ],
                blockers=QuestionBlockers(
                    severity="BLOCKING",
                ),
                quality_gate=QualityGateStatus(
                    status="FAIL",
                    attempts=len(records),
                    last_quality_record_id=records[-1].record_id if records else "",
                    last_checked_at=datetime.now(UTC).isoformat(),
                ),
            )
            failure_reason = records[-1].reason if records else "quality gate failed"
            failure_details = {
                "attempts": len(records),
                "redefinition_trigger": trigger_key,
            }
            self._mark_unaskable(
                question_id,
                source="redefinition",
                reason=failure_reason,
                details=failure_details,
            )
            self._emit_quality_gate_reformulation(
                question_id=question_id,
                canonical_key=canonical_key,
                taxonomy_type=question_type,
                question_text=item.user_prompt.text,
                source="redefinition",
                reason=failure_reason,
                details=failure_details,
            )
            return item

        item = QuestionItem(
            question_id=question_id,
            status="OPEN",
            taxonomy_type=question_type,
            scope_kind=scope_kind,
            canonical_key=canonical_key,
            user_prompt=UserPrompt(
                text=self._coerce_str(final_candidate.text, user_text),
                scenario=self._coerce_str(final_candidate.scenario, scenario_text),
                why_it_matters="This affects scope, tradeoffs, or project direction.",
                answer_spec=AnswerSpec(
                    kind="choice",
                    choices=parsed_choices,
                ),
            ),
            system_binding=self._build_redefinition_binding(
                {},
                taxonomy_type=question_type,
                text=self._coerce_str(final_candidate.text, user_text),
                canonical_key=canonical_key,
            ),
            origins=[
                QuestionOrigin(
                    source_kind=source_text,
                    trace_id=source_trace,
                    created_at=datetime.now(UTC).isoformat(),
                ),
            ],
            blockers=QuestionBlockers(
                severity="BLOCKING",
            ),
            quality_gate=QualityGateStatus(
                status="PASS",
                attempts=len(records),
                last_quality_record_id=records[-1].record_id if records else "",
                last_checked_at=datetime.now(UTC).isoformat(),
            ),
        )

        existing = self._queue.dedup(item, run_agent=self._run_agent)
        if existing is None:
            self._queue.enqueue(item)
            existing = item
        item = existing

        if item.status != "OPEN":
            item.status = "OPEN"
        item.taxonomy_type = question_type
        item.scope_kind = scope_kind
        item.canonical_key = canonical_key
        item.user_prompt.text = self._coerce_str(final_candidate.text, user_text)
        item.user_prompt.scenario = self._coerce_str(final_candidate.scenario, scenario_text)
        item.user_prompt.why_it_matters = "This affects scope, tradeoffs, or project direction."
        item.user_prompt.answer_spec = AnswerSpec(
            kind="choice",
            choices=parsed_choices,
        )
        item.blockers.severity = "BLOCKING"
        item.system_binding = self._build_redefinition_binding(
            item.system_binding,
            taxonomy_type=question_type,
            text=item.user_prompt.text,
            canonical_key=canonical_key,
        )
        item.quality_gate.status = "PASS"
        item.quality_gate.attempts = len(records)
        item.quality_gate.last_quality_record_id = records[-1].record_id if records else ""
        item.quality_gate.last_checked_at = datetime.now(UTC).isoformat()

        # Re-open if this was an older item that had already transitioned.
        item.timestamps["updated_at"] = item.quality_gate.last_checked_at
        return item

    def _load_phase0_evidence_for_skeleton(self) -> dict[str, Any] | None:
        """Load structured Phase 0 outputs for optional skeleton prefill."""
        libraries_root = self._run_dir / "libraries"
        if not libraries_root.exists() or not libraries_root.is_dir():
            return None

        library_records: list[dict[str, Any]] = []
        top_level_constraint_refs: list[dict[str, str]] = []
        for lib_dir in sorted(p for p in libraries_root.iterdir() if p.is_dir()):
            lib_id = lib_dir.name
            charter_path = lib_dir / "charter.md"
            constraints_path = lib_dir / "constraints_index.json"

            overview_lines: list[str] = []
            responsibilities: list[str] = []
            boundaries: list[str] = []
            if charter_path.exists():
                section = ""
                collecting_overview = False
                for raw_line in charter_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if line.startswith("## "):
                        section = line[3:].strip().lower()
                        collecting_overview = section == "overview"
                        continue
                    if collecting_overview:
                        if line.startswith("- ") or line.startswith("### "):
                            collecting_overview = False
                        elif line:
                            overview_lines.append(line)
                    if line.startswith("- "):
                        bullet = line[2:].strip()
                        if not bullet:
                            continue
                        if "responsibil" in section:
                            responsibilities.append(bullet)
                        elif "boundar" in section:
                            boundaries.append(bullet)

            lib_constraint_refs: list[dict[str, str]] = []
            if constraints_path.exists():
                try:
                    raw_constraints = json.loads(constraints_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    raw_constraints = []
                if isinstance(raw_constraints, list):
                    for raw_constraint in raw_constraints:
                        if not isinstance(raw_constraint, dict):
                            continue
                        element_id = str(raw_constraint.get("element_id", "")).strip()
                        if not element_id:
                            continue
                        ref = {"constraint_id": element_id, "source": "phase0"}
                        lib_constraint_refs.append(ref)
                        top_level_constraint_refs.append(ref)

            library_records.append(
                {
                    "lib_id": lib_id,
                    "name": lib_id,
                    "description": " ".join(overview_lines).strip(),
                    "responsibilities": responsibilities,
                    "boundaries": boundaries,
                    "constraint_refs": lib_constraint_refs,
                }
            )

        if not library_records and not top_level_constraint_refs:
            return None
        return {
            "libraries": library_records,
            "constraint_refs": top_level_constraint_refs,
        }

    # TODO [R2-6.1]: Implement produce_skeleton() — skeleton generation
    #   - Check should_produce_skeleton() first
    #   - Use SkeletonSynthesisStrategy to produce SkeletonSpec
    #   - Render to output directory
    #   - Update skeleton_state in session
    def produce_skeleton(self) -> list[Path] | None:
        """Produce or update the pre-decomposition skeleton."""
        self._ensure_initialized()
        assert self._state is not None
        assert self._queue is not None

        # 1. Check readiness.
        pf = self._state.problem_frame
        frame_dict = {
            "current_restatement": pf.current_restatement,
            "goals": list(pf.goals),
            "non_goals": list(pf.non_goals),
            "scope": {
                "in": list(pf.scope.get("in", [])),
                "out": list(pf.scope.get("out", [])),
            },
            "success_metrics": list(pf.success_metrics),
            "risk_flags": list(pf.risk_flags),
            "frame_assumptions": [
                {
                    "text": item.text,
                    "status": item.status,
                    "source": item.source,
                }
                for item in pf.frame_assumptions
            ],
        }
        queue_state = self._state.question_queue_state
        raw_tradeoff_positions = queue_state._passthrough_fields.get("tradeoff_positions", [])
        frame_dict["tradeoff_positions"] = (
            list(raw_tradeoff_positions) if isinstance(raw_tradeoff_positions, list) else []
        )
        if not should_produce_skeleton(frame_dict, queue_state.to_dict()):
            return None

        # Gather open question IDs and planner refs.
        open_items = self._queue.get_open_items()
        open_question_ids = [it.question_id for it in open_items]
        constraint_refs: list[dict[str, str]] = []
        decision_refs: list[str] = []
        seen_constraint_ids: set[str] = set()
        for ref in self._state.question_key_map.values():
            for constraint_id in ref.planner_constraint_ids:
                if constraint_id in seen_constraint_ids:
                    continue
                seen_constraint_ids.add(constraint_id)
                constraint_refs.append(
                    {
                        "constraint_id": constraint_id,
                        "source": "planner",
                    }
                )
            decision_refs.extend(ref.planner_decision_ids)
        decision_refs = self._dedupe_ordered(decision_refs)
        phase0_evidence = self._load_phase0_evidence_for_skeleton()

        # Concept map dict.
        cm = self._state.concept_map
        concept_dict = {
            "user_terms": {
                k: {"maps_to": list(v.maps_to), "confidence": v.confidence}
                for k, v in cm.user_terms.items()
            },
            "normalized_terms": dict(cm.normalized_terms),
            "user_introduced_terms": list(cm.user_introduced_terms),
        }

        # 2. Use SkeletonSynthesisStrategy to produce SkeletonSpec.
        spec = self._skeleton_strategy.synthesize(
            problem_frame=frame_dict,
            concept_map=concept_dict,
            open_question_ids=open_question_ids,
            open_questions=[
                {
                    "question_id": it.question_id,
                    "question_text": it.user_prompt.text,
                    "canonical_key": it.canonical_key,
                    "scenario": it.user_prompt.scenario,
                }
                for it in open_items
            ],
            constraint_refs=constraint_refs,
            decision_refs=decision_refs,
            phase0_outputs=phase0_evidence,
            run_agent=self._run_agent,
        )

        # 3. Render to output directory.
        output_dir = self._run_dir / "intent" / "skeleton"
        created_paths = render_skeleton(spec, output_dir)

        # Also render intent snapshot.
        open_q_dicts = [
            {
                "question_id": it.question_id,
                "question_text": it.user_prompt.text,
                "canonical_key": it.canonical_key,
                "scenario": it.user_prompt.scenario,
            }
            for it in open_items
        ]
        snapshot_path = render_intent_snapshot(
            frame_dict,
            concept_dict,
            open_q_dicts,
            constraint_refs,
            output_dir,
            decision_refs=decision_refs,
            tradeoff_positions=frame_dict.get("tradeoff_positions", []),
        )
        created_paths.append(snapshot_path)

        # 4. Update skeleton_state in session.
        now = datetime.now(UTC).isoformat()
        self._state.skeleton_state.revision += 1
        self._state.skeleton_state.artifact_paths = [str(p) for p in created_paths]
        self._state.skeleton_state.last_generated_at = now

        if self._event_log is not None:
            self._event_log.append(
                "skeleton_updated",
                {
                    "revision": self._state.skeleton_state.revision,
                    "paths": [str(p) for p in created_paths],
                },
            )

        return created_paths

    # TODO [R2-9.1]: Implement save_state() — persist all state
    #   - Save session_state.json
    #   - Save question_queue.json
    #   - Append to events.jsonl
    def save_state(self) -> None:
        """Persist all state to disk."""
        # 1. Ensure intent directory exists.
        intent_dir = self._run_dir / "intent"
        intent_dir.mkdir(parents=True, exist_ok=True)

        # 2. Sync queue state into session state before saving.
        if self._queue is not None and self._state is not None:
            state_ids = self._queue.state_ids()
            self._state.question_queue_state.open_ids = state_ids.get("open_ids", [])
            self._state.question_queue_state.closed_ids = state_ids.get("closed_ids", [])
            self._state.question_queue_state.stale_ids = state_ids.get("stale_ids", [])

        # 3. Save state.
        if self._state is not None:
            self._state.save(self._run_dir)

        # 4. Save queue.
        if self._queue is not None:
            self._queue.save(self._run_dir)

    @property
    def is_auto_mode(self) -> bool:
        """Check if prompt output should be suppressed.

        Both ``auto`` and ``steering`` suppress prompt emission. Autonomous
        self-resolution eligibility is stricter and is enforced only when
        ``self._mode == "auto"``.
        """
        return self._mode in ("auto", "steering")
