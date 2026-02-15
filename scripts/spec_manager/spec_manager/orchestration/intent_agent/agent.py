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
    2. UserQuestionSignals — from Planner, UnderSpec, PromotionLoop, Lifecycle
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
import uuid
from datetime import UTC, datetime
from pathlib import Path
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
    FrameAssumption,
    IntentEventLog,
    IntentSessionState,
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
    normalize_user_facing_taxonomy,
    reframe_to_user_valid,
)

logger = logging.getLogger(__name__)

_VALID_REDEFINITION_QUESTION_TYPES = frozenset({"VALIDATION", "SCOPE", "TRADEOFF"})
_REDEFINITION_UPDATE_SOURCES = frozenset({"PLANNER"})


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
        mode: str = "interactive",
        run_agent: Any = None,
        on_translation_saved: Any = None,
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

    def _log_quality_checks(self, records: list[QualityCheckRecord]) -> None:
        if self._event_log is None:
            return
        for record in records:
            self._event_log.append("quality_check", record.to_dict())

    def _mark_unaskable(
        self, question_id: str, source: str, reason: str, details: dict[str, Any] | None = None
    ) -> None:
        if self._state is not None:
            bucket = self._state.question_queue_state.setdefault(
                "unaskable_question_ids",
                [],
            )
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
    ) -> None:
        """Emit a planner-directed signal for failed follow-up reformulation."""
        if self._state is None:
            return

        canonical_key = self._coerce_str(draft.canonical_key_hint)
        if not canonical_key:
            canonical_key = f"intent.followup.{parent_question_id}"

        reason = self._coerce_str(
            records[-1].reason if records else "quality gate failed",
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
            logger.debug(
                "No planner signal callback configured; dropped follow-up quality signal "
                "for parent_question_id=%s",
                parent_question_id,
            )
            return

        try:
            self._on_planner_signal(payload)
        except Exception:
            logger.warning(
                "on_planner_signal callback failed for follow-up quality signal (parent=%s)",
                parent_question_id,
                exc_info=True,
            )

    def _coerce_str(self, value: Any, default: str = "") -> str:
        if not isinstance(value, str):
            return default
        text = value.strip()
        return text or default

    def _coerce_str_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [item.strip() for item in (str(item).strip() for item in value) if item.strip()]
        return []

    def _sync_alignment_invariants(self, trigger: dict[str, Any]) -> None:
        if self._state is None:
            return

        raw_invariants = trigger.get("alignment_invariants")
        raw_status = self._coerce_str(trigger.get("invariant_status", "HYPOTHESIS")).upper()
        default_source = self._coerce_str(
            trigger.get("invariant_source", trigger.get("source", "planner")).lower()
        )
        raw_trigger_invariants = raw_invariants if isinstance(raw_invariants, list) else []
        if not isinstance(raw_trigger_invariants, list):
            return

        invariant_status = (
            raw_status if raw_status in {"HYPOTHESIS", "CONFIRMED", "REJECTED"} else "HYPOTHESIS"
        )
        invariant_created_at = datetime.now(UTC).isoformat()
        existing = {
            assumption.text.strip().lower(): assumption
            for assumption in self._state.problem_frame.frame_assumptions
            if assumption.text.strip()
        }

        for raw in raw_trigger_invariants:
            if isinstance(raw, dict):
                text = self._coerce_str(raw.get("text"), "")
                status = self._coerce_str(raw.get("status"), invariant_status).upper()
                source = self._coerce_str(raw.get("source"), default_source)
            else:
                text = self._coerce_str(raw, "")
                status = invariant_status
                source = default_source

            if not text:
                continue
            if status not in {"HYPOTHESIS", "CONFIRMED", "REJECTED"}:
                status = invariant_status

            existing_entry = existing.get(text.lower())
            if existing_entry is not None:
                existing_entry.status = status
                existing_entry.source = source or existing_entry.source
                if not existing_entry.created_at:
                    existing_entry.created_at = invariant_created_at
                continue

            self._state.problem_frame.frame_assumptions.append(
                FrameAssumption(
                    text=text,
                    status=status,
                    source=source or "planner",
                    created_at=invariant_created_at,
                )
            )
            existing[text.lower()] = self._state.problem_frame.frame_assumptions[-1]

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
        question_id = self._coerce_str(replacement.get("new_question_id"), "")

        if not question_id:
            question_id = f"q_{uuid.uuid4().hex[:12]}"

        now = datetime.now(UTC).isoformat()
        system_binding = dict(source_item.system_binding or {})
        system_binding.update(
            {
                "superseded_by": source_item.question_id,
                "replaced_by": question_id,
                "replacement_reason": reason,
            }
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

        existing = self._queue.dedup(replacement_item)
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
        if normalized in {"problem_redefinition", "scope_redefinition", "lifecycle_redefinition"}:
            return "problem_redefinition"
        if normalized in {"alignment_violation", "invariant_violation"}:
            return "alignment_violation"
        return normalized

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
        if explicit_type in _VALID_REDEFINITION_QUESTION_TYPES:
            return explicit_type

        if trigger_type == "alignment_violation":
            return "TRADEOFF"

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

    def _infer_constraint_dimensions_for_item(self, item: QuestionItem) -> list[str]:
        if item.taxonomy_type != QuestionTaxonomy.CONSTRAINT.value:
            return []

        persisted_dims = normalize_constraint_dimensions(
            item.system_binding.get("constraint_dimensions", []),
        )
        if persisted_dims:
            return persisted_dims

        return normalize_constraint_dimensions(
            infer_constraint_dimensions_with_key(
                item.user_prompt.text,
                canonical_key=item.canonical_key,
            )
        )

    def _normalize_question_binding(
        self,
        base_binding: dict[str, Any] | None,
        *,
        taxonomy_type: str,
        text: str,
        canonical_key: str,
    ) -> dict[str, Any]:
        binding = dict(base_binding or {})
        normalized_taxonomy = normalize_user_facing_taxonomy(taxonomy_type)
        if normalized_taxonomy == QuestionTaxonomy.CONSTRAINT.value:
            inferred = infer_constraint_dimensions_with_key(
                text,
                canonical_key=canonical_key,
            )
            binding["constraint_dimensions"] = normalize_constraint_dimensions(
                normalize_constraint_dimensions(binding.get("constraint_dimensions", []))
                + inferred,
            )
        else:
            binding["constraint_dimensions"] = []
        return binding

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

        self._state.question_queue_state.update(
            {
                "open_ids": open_ids,
                "closed_ids": closed_ids,
                "stale_ids": stale_ids,
                "open_constraint_question_ids": open_constraint_ids,
                "closed_constraint_question_ids": closed_constraint_ids,
                "open_constraint_dimensions": sorted(open_constraint_dims),
                "closed_constraint_dimensions": sorted(closed_constraint_dims),
            }
        )

        self._state.question_queue_state.setdefault(
            "unaskable_question_ids",
            [],
        )
        self._state.question_queue_state.setdefault(
            "skeleton_input_signature",
            "",
        )

    def _skeleton_input_signature(self) -> str:
        if self._state is None:
            return ""
        pf = self._state.problem_frame
        qs = self._state.question_queue_state
        signature = {
            "restatement": pf.current_restatement,
            "goals": sorted(set(pf.goals)),
            "open_ids": sorted(qs.get("open_ids", [])),
            "closed_ids": sorted(qs.get("closed_ids", [])),
            "open_constraint_question_ids": sorted(qs.get("open_constraint_question_ids", [])),
            "closed_constraint_question_ids": sorted(qs.get("closed_constraint_question_ids", [])),
            "open_constraint_dimensions": sorted(qs.get("open_constraint_dimensions", [])),
            "closed_constraint_dimensions": sorted(qs.get("closed_constraint_dimensions", [])),
            "open_count": len(qs.get("open_ids", [])),
            "closed_count": len(qs.get("closed_ids", [])),
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
        if not should_produce_skeleton(frame_dict, queue_state):
            return None

        signature = self._skeleton_input_signature()
        last_signature = queue_state.get("skeleton_input_signature", "")
        if force or self._state.skeleton_state.revision == 0 or signature != last_signature:
            produced = self.produce_skeleton()
            queue_state["skeleton_input_signature"] = signature
            return produced

        return None

    # TODO [R2-1.4]: Implement resume() — deterministic resumption
    #   1. Load session_state.json
    #   2. Load question_queue.json
    #   3. Read new UserQuestionSignals since user_question_signal_watermark
    #   4. Read new PlannerUpdates since planner_update_watermark
    #   5. Ingest new signals (classify, draft, quality gate, enqueue)
    #   6. Run reassessment against new planner updates
    #   7. Recompute queue ordering and staleness
    #   8. Return next question to present
    def resume(self) -> QuestionItem | None:
        """Resume from persisted state and return next question."""
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
        self.handle_planner_updates()

        # 6. Recompute staleness so resumed flow is deterministic and
        #    does not present stale questions after planner/store drift.
        stale_ids = sorted(self._queue.mark_stale())
        if self._state is not None:
            self._state.question_queue_state["stale_ids"] = stale_ids

        # 7. Refresh derived queue metadata and skeleton readiness.
        self._refresh_question_queue_state()
        self._maybe_update_skeleton()

        # 8. Return next question.
        return self._queue.next_question() if self._queue else None

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

    def _apply_problem_frame_update(self, text: str) -> None:
        if self._state is None or self._intent_frame is None:
            return
        updated_frame = self._intent_frame.update_frame(
            self._serialize_problem_frame(),
            text,
            self._serialize_concept_map(),
            run_agent=self._run_agent,
        )
        if not isinstance(updated_frame, dict):
            return
        if "current_restatement" in updated_frame:
            self._state.problem_frame.current_restatement = updated_frame["current_restatement"]
        if "goals" in updated_frame:
            self._state.problem_frame.goals = list(updated_frame["goals"])
        if "non_goals" in updated_frame:
            self._state.problem_frame.non_goals = list(updated_frame["non_goals"])
        if "scope" in updated_frame and isinstance(updated_frame["scope"], dict):
            self._state.problem_frame.scope = {
                "in": list(updated_frame["scope"].get("in", [])),
                "out": list(updated_frame["scope"].get("out", [])),
            }
        if "success_metrics" in updated_frame:
            self._state.problem_frame.success_metrics = list(updated_frame["success_metrics"])
        if "risk_flags" in updated_frame:
            self._state.problem_frame.risk_flags = list(updated_frame["risk_flags"])

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
        new_introduced = updated_map.get("user_introduced_terms", [])
        for term in new_introduced:
            if term not in self._state.concept_map.user_introduced_terms:
                self._state.concept_map.user_introduced_terms.append(term)

    def _handle_vague_user_input(self, text: str) -> dict[str, Any] | None:
        if not is_vague_user_input(text):
            return None
        vague_item = self.handle_vague_input(text)
        self._maybe_update_skeleton()
        self.save_state()
        if isinstance(vague_item, QuestionItem) and vague_item.status == "OPEN":
            return {
                "action": "ask",
                "question": vague_item.to_dict(),
                "question_id": vague_item.question_id,
                "immediate_ask": True,
            }
        return None

    def _finalize_user_message(self) -> None:
        self._maybe_update_skeleton()
        self._refresh_question_queue_state()
        self.save_state()

    def handle_user_message(self, text: str) -> dict[str, Any]:
        """Handle a user message. Returns action to take (ask/skeleton/etc)."""
        self._ensure_initialized()
        assert self._state is not None
        assert self._queue is not None

        self._capture_original_intent(text)
        self._log_user_message_event(text)
        self._apply_problem_frame_update(text)
        self._apply_concept_map_update(text)

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
    def ingest_signal(self, signal: UserQuestionSignal) -> QuestionItem | None:
        """Ingest a UserQuestionSignal and produce a queued question (or None)."""
        if self._state is None:
            self._ensure_initialized()
        assert self._state is not None
        assert self._queue is not None

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
                canonical_key_hint=signal.question.canonical_key_hint,
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
        )

        # Log quality check events.
        self._log_quality_checks(records)
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
            canonical_key = self._coerce_str(signal.question.canonical_key_hint)
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
                        source_kind=signal.source.kind,
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
            existing = self._queue.dedup(item)
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
                        source_kind=signal.source.kind,
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
        else:
            # 6. FAIL after retries — mark UNASKABLE.
            failed_candidate = final_candidate or candidate
            failed_taxonomy = normalize_user_facing_taxonomy(
                failed_candidate.taxonomy_type,
            )
            failed_text = self._coerce_str(failed_candidate.text, question_text)
            canonical_key = self._coerce_str(signal.question.canonical_key_hint)
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

        # 7. Update signal watermark.
        self._state.watermarks.user_question_signal_watermark = signal.uq_id

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
            recursion_budget = RecursionBudget(max_followups=2, used_followups=0)
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
                recursion_budget=recursion_budget,
                run_agent=self._run_agent,
            )
            recursion_budget = translation.recursion_budget
        else:
            recursion_budget = RecursionBudget(max_followups=2, used_followups=0)
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

        # 4a. Submit to Planner for ingestion via callback.
        planner_ingest_ok = False
        planner_error = ""
        planner_trace_id = ""
        planner_status = "OK"
        if self._on_translation_saved is not None:
            try:
                ingest_result = self._on_translation_saved(translation)
                if isinstance(ingest_result, dict):
                    planner_trace_id = str(ingest_result.get("trace_id", "")).strip()
                    planner_status = str(ingest_result.get("status", "OK")).upper()
                    planner_error = str(ingest_result.get("error", "")).strip()
                    if planner_status and planner_status not in {"OK", "NOOP"}:
                        planner_error = planner_error or f"planner status {planner_status}"
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
        else:
            # No callback — treat as unsuccessful for deterministic lifecycle.
            # Queue closure must be driven by planner_updates signals.
            planner_ingest_ok = False
            planner_error = "no planner ingestion callback configured"

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
        remaining_followups = max(
            0,
            recursion_budget.max_followups - recursion_budget.used_followups,
        )
        followup_candidates = sorted(
            translation.extracted.followup_question_drafts,
            key=lambda draft: (
                self._coerce_str(draft.canonical_key_hint),
                normalize_user_facing_taxonomy(draft.taxonomy_type),
                self._coerce_str(draft.text),
                self._coerce_str(draft.draft_id),
            ),
        )[:remaining_followups]
        seen_followups: set[tuple[str, str, str, str]] = set()

        for fq_draft in followup_candidates:
            followup_key = (
                self._coerce_str(fq_draft.canonical_key_hint),
                normalize_user_facing_taxonomy(fq_draft.taxonomy_type),
                self._coerce_str(fq_draft.text),
                self._coerce_str(fq_draft.scenario),
            )
            if followup_key in seen_followups:
                continue
            seen_followups.add(followup_key)

            fq_taxonomy = normalize_user_facing_taxonomy(fq_draft.taxonomy_type)
            fq_answer_spec_kind = self._coerce_answer_spec_kind(
                fq_draft.answer_spec.get("kind", "choice"),
            )

            fq_candidate = QualityCheckCandidate(
                text=self._coerce_str(fq_draft.text),
                scenario=self._coerce_str(fq_draft.scenario),
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
            )

            self._log_quality_checks(fq_records)

            if fq_passed and fq_final is not None:
                canonical_key = self._coerce_str(fq_draft.canonical_key_hint)
                fq_final.answer_spec_kind = self._coerce_answer_spec_kind(
                    fq_final.answer_spec_kind,
                )
                scope = classify_scope(fq_final.text)
                fq_item = QuestionItem(
                    question_id=fq_id,
                    status="OPEN",
                    taxonomy_type=fq_taxonomy,
                    scope_kind=scope.value,
                    canonical_key=canonical_key,
                    user_prompt=UserPrompt(
                        text=fq_final.text,
                        scenario=fq_final.scenario,
                        answer_spec=AnswerSpec(kind=fq_final.answer_spec_kind),
                    ),
                    system_binding=self._normalize_question_binding(
                        {},
                        taxonomy_type=fq_taxonomy,
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
                existing = self._queue.dedup(fq_item)
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

            update_type = self._coerce_redefinition_action_type(
                self._coerce_str(update.get("type"), ""),
            )
            if update_type not in {"problem_redefinition", "alignment_violation"}:
                continue
            if not self._is_authorized_redefinition_update(update, update_type=update_type):
                continue

            self._sync_alignment_invariants(update)
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
        reassessment = self._queue.reassess(
            updates,
            question_key_map,
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
                        item.canonical_key = new_canonical_key
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
            return self._empty_reassessment_result(run_id, session_id)
        new_updates = [dict(update) for update in raw_updates if isinstance(update, dict)]
        if not new_updates:
            return self._empty_reassessment_result(run_id, session_id)

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

        # 4. Update planner watermark to the latest update's created_at.
        self._update_planner_watermark(new_updates)
        self._refresh_question_queue_state()
        reassessment["version"] = 1
        reassessment["run_id"] = run_id
        reassessment["session_id"] = session_id

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
    #   - Batch: return next_batch() if applicable
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
            if self._state is not None:
                pf = self._state.problem_frame
                frame_dict = {
                    "current_restatement": pf.current_restatement,
                    "goals": list(pf.goals),
                }
                queue_state = self._state.question_queue_state
                if should_produce_skeleton(frame_dict, queue_state):
                    return {"action": "skeleton"}
            return {"action": "wait"}

        # Immediate-ask rule: if a BLOCKING question exists and last presented
        # was INFO (or queue was empty), present the BLOCKING question immediately.
        blocking_items = [it for it in open_items if it.blockers.severity == "BLOCKING"]
        if blocking_items and self._state is not None:
            last_presented_id = self._state.question_queue_state.get(
                "last_presented_question_id", ""
            )
            last_item = self._queue.get_item(last_presented_id) if last_presented_id else None
            last_was_info = last_item is None or last_item.blockers.severity == "INFO"
            if last_was_info:
                # Preempt: present the highest-priority BLOCKING question
                next_q = blocking_items[0]
                self._state.question_queue_state["last_presented_question_id"] = next_q.question_id
                return {
                    "action": "ask",
                    "question": next_q.to_dict(),
                    "question_id": next_q.question_id,
                    "immediate_ask": True,
                }

        # Get the next question (default priority ordering).
        batch = self._queue.next_batch(run_agent=self._run_agent)
        if not batch:
            return {"action": "wait"}

        if len(batch) > 1:
            if self._state is not None:
                self._state.question_queue_state["last_presented_question_id"] = batch[
                    0
                ].question_id
            return {
                "action": "ask_batch",
                "questions": [item.to_dict() for item in batch],
                "question_ids": [item.question_id for item in batch],
            }

        next_q = batch[0]

        # Track last presented question in state.
        if self._state is not None:
            self._state.question_queue_state["last_presented_question_id"] = next_q.question_id

        return {
            "action": "ask",
            "question": next_q.to_dict(),
            "question_id": next_q.question_id,
        }

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
            candidate = QualityCheckCandidate(
                text=(
                    "Your input could be interpreted in different ways. "
                    "Which of the following best describes what you want to build?"
                ),
                scenario=f'You said: "{text}"',
                answer_spec_kind="choice",
                taxonomy_type="INTENT",
            )

        # Quality gate.
        concept_terms = list(self._state.concept_map.user_introduced_terms)
        final_candidate, records, passed = enforce_quality_gate(
            candidate,
            question_id,
            concept_map_user_terms=concept_terms,
            validator=self._quality_validator,
            repairer=self._question_repairer,
            run_agent=self._run_agent,
        )
        self._log_quality_checks(records)

        used_candidate = final_candidate if passed and final_candidate else candidate

        item = QuestionItem(
            question_id=question_id,
            status="OPEN" if passed else "UNASKABLE",
            taxonomy_type=normalize_user_facing_taxonomy("INTENT"),
            scope_kind="SYSTEM_WIDE",
            canonical_key="intent.disambiguation",
            user_prompt=UserPrompt(
                text=used_candidate.text,
                scenario=used_candidate.scenario,
                answer_spec=AnswerSpec(kind=used_candidate.answer_spec_kind),
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
            existing = self._queue.dedup(item)
            if existing is None:
                self._queue.enqueue(item)
            else:
                item = existing
                self._apply_quality_pass_to_item(item, used_candidate, records)
        else:
            self._mark_unaskable(
                question_id,
                source="vague_input",
                reason=(records[-1].reason if records else "quality gate failed"),
                details={"text": text},
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

        trigger_type = self._coerce_redefinition_action_type(
            self._coerce_str(trigger.get("type"), "problem_redefinition"),
        )
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
            alignment_invariants = trigger.get("alignment_invariants", [])
            if isinstance(alignment_invariants, list):
                for invariant in alignment_invariants:
                    if isinstance(invariant, dict):
                        invariant_text = self._coerce_str(invariant.get("text"), "")
                        invariant_status = self._coerce_str(
                            invariant.get("status"),
                            self._coerce_str(trigger.get("invariant_status", "HYPOTHESIS")),
                        )
                        if invariant_text:
                            changed_items.append(f"{invariant_text} [{invariant_status}]")
                    else:
                        invariant_text = self._coerce_str(invariant, "")
                        if invariant_text:
                            changed_items.append(invariant_text)

        if not changed_items:
            changed_items = [
                "A planning constraint or assumption changed.",
            ]

        if len(changed_items) > 3:
            changed_items = changed_items[:3]

        scope_kind = self._coerce_str(trigger.get("scope_kind"), "SYSTEM_WIDE").upper()
        if scope_kind not in {"SYSTEM_WIDE", "FEATURE_SPECIFIC"}:
            scope_kind = "SYSTEM_WIDE"

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

        source_text = self._coerce_str(trigger.get("source"), "PLANNER").upper()

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
            "The planning scope has changed. Please confirm how you want to proceed "
            "with this updated context."
        )
        if trigger_type == "alignment_violation":
            default_prompt = (
                "Alignment assumptions have changed. Confirm how to proceed with the "
                "current scope and constraints."
            )

        user_text = self._coerce_str(trigger.get("question_text"), default_prompt)

        raw_choices = trigger.get("answer_choices")
        if isinstance(raw_choices, list):
            parsed_choices = [
                {
                    "id": self._coerce_str(item.get("id")),
                    "label": self._coerce_str(item.get("label")),
                }
                for item in raw_choices
                if isinstance(item, dict)
                and self._coerce_str(item.get("id"))
                and self._coerce_str(item.get("label"))
            ]
            if not parsed_choices:
                parsed_choices = []
        else:
            parsed_choices = []

        if not parsed_choices:
            parsed_choices = [
                {"id": "adopt_new", "label": "Adopt the new understanding"},
                {"id": "keep_original", "label": "Keep the original intent"},
                {"id": "partial", "label": "Adopt parts of the new understanding"},
            ]

        trigger_key = self._coerce_str(trigger.get("event_id"), "")

        if existing_item is not None:
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

            if existing_item.status != "OPEN":
                existing_item.status = "OPEN"
            if existing_item.quality_gate.status != "PASS":
                existing_item.quality_gate.status = "PASS"

            if not isinstance(existing_item.system_binding, dict):
                existing_item.system_binding = {}
            redefinition_history = existing_item.system_binding.get("redefinition_history")
            if not isinstance(redefinition_history, list):
                redefinition_history = []
                existing_item.system_binding["redefinition_history"] = redefinition_history
            redefinition_history.append(
                {
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "trigger": trigger_key,
                    "source": source_text.lower(),
                    "taxonomy_type": existing_item.taxonomy_type,
                    "scope_kind": existing_item.scope_kind,
                    "canonical_key": existing_item.canonical_key,
                    "user_prompt_text": existing_item.user_prompt.text,
                    "user_prompt_scenario": existing_item.user_prompt.scenario,
                    "user_prompt_why_it_matters": existing_item.user_prompt.why_it_matters,
                    "answer_spec_kind": existing_item.user_prompt.answer_spec.kind,
                    "answer_spec_choices": [
                        dict(choice) for choice in existing_item.user_prompt.answer_spec.choices
                    ],
                    "answer_spec_value_type": existing_item.user_prompt.answer_spec.value_type,
                    "answer_spec_units_hint": existing_item.user_prompt.answer_spec.units_hint,
                    "answer_spec_text_bounds": dict(
                        existing_item.user_prompt.answer_spec.text_bounds
                    ),
                }
            )

            existing_item.taxonomy_type = question_type
            existing_item.scope_kind = scope_kind
            existing_item.canonical_key = canonical_key
            existing_item.user_prompt.text = user_text
            existing_item.user_prompt.scenario = scenario_text
            existing_item.user_prompt.why_it_matters = (
                "This affects scope, tradeoffs, or project direction."
            )
            existing_item.user_prompt.answer_spec = AnswerSpec(
                kind="choice",
                choices=parsed_choices,
            )
            existing_item.blockers.severity = "BLOCKING"
            existing_item.system_binding.update(
                {
                    "redefinition_trigger": trigger_key,
                    "redefinition_type": trigger_type,
                    "redefinition_stage": stage_text,
                    "redefinition_source": source_text.lower(),
                    "redefinition_canonical_key": canonical_key,
                }
            )

            existing_item.timestamps["updated_at"] = datetime.now(UTC).isoformat()
            existing_item.origins.append(
                QuestionOrigin(
                    source_kind=source_text,
                    trace_id=source_trace,
                    created_at=datetime.now(UTC).isoformat(),
                )
            )
            return existing_item

        item = QuestionItem(
            question_id=question_id,
            status="OPEN",
            taxonomy_type=question_type,
            scope_kind=scope_kind,
            canonical_key=canonical_key,
            user_prompt=UserPrompt(
                text=user_text,
                scenario=scenario_text,
                why_it_matters="This affects scope, tradeoffs, or project direction.",
                answer_spec=AnswerSpec(
                    kind="choice",
                    choices=parsed_choices,
                ),
            ),
            system_binding={
                "redefinition_trigger": trigger_key,
                "redefinition_type": trigger_type,
                "redefinition_stage": stage_text,
                "redefinition_source": source_text.lower(),
                "redefinition_canonical_key": canonical_key,
            },
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
                attempts=1,
                last_checked_at=datetime.now(UTC).isoformat(),
            ),
        )

        existing = self._queue.dedup(item)
        if existing is None:
            self._queue.enqueue(item)
            existing = item
        item = existing

        if item.status != "OPEN":
            item.status = "OPEN"

        # Quality gate (skip LLM unless repair is needed).
        concept_terms = list(self._state.concept_map.user_introduced_terms)
        final_candidate, records, passed = enforce_quality_gate(
            QualityCheckCandidate(
                text=item.user_prompt.text,
                scenario=item.user_prompt.scenario,
                answer_spec_kind="choice",
                taxonomy_type=question_type,
            ),
            item.question_id,
            concept_map_user_terms=concept_terms,
            validator=self._quality_validator,
            repairer=self._question_repairer,
            run_agent=self._run_agent,
        )

        if passed and final_candidate is not None:
            item.user_prompt.text = final_candidate.text
            item.user_prompt.scenario = final_candidate.scenario
            item.quality_gate.status = "PASS"
            item.quality_gate.attempts = len(records)

        # Re-open if this was an older item that had already transitioned.
        item.timestamps["updated_at"] = datetime.now(UTC).isoformat()
        return item

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
        }
        queue_state = self._state.question_queue_state
        if not should_produce_skeleton(frame_dict, queue_state):
            return None

        # Gather open question IDs and constraint refs.
        open_items = self._queue.get_open_items()
        open_question_ids = [it.question_id for it in open_items]
        constraint_refs: list[str] = []
        for ref in self._state.question_key_map.values():
            constraint_refs.extend(ref.planner_constraint_ids)

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
                    "canonical_key": it.canonical_key,
                    "scenario": it.user_prompt.scenario,
                }
                for it in open_items
            ],
            constraint_refs=constraint_refs,
            run_agent=self._run_agent,
        )

        # 3. Render to output directory.
        output_dir = self._run_dir / "intent" / "skeleton"
        created_paths = render_skeleton(spec, output_dir)

        # Also render intent snapshot.
        open_q_dicts = [
            {
                "question_id": it.question_id,
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
            self._state.question_queue_state["open_ids"] = state_ids.get("open_ids", [])
            self._state.question_queue_state["closed_ids"] = state_ids.get("closed_ids", [])
            self._state.question_queue_state["stale_ids"] = state_ids.get("stale_ids", [])

        # 3. Save state.
        if self._state is not None:
            self._state.save(self._run_dir)

        # 4. Save queue.
        if self._queue is not None:
            self._queue.save(self._run_dir)

    @property
    def is_auto_mode(self) -> bool:
        """Check if running in auto mode.

        In auto mode, questions are generated and quality-gated for internal
        documentation but not emitted as user prompts.  Questions requiring
        human authority remain unresolved; the Planner blocks or makes
        best-effort where authority policy permits.
        """
        return self._mode in ("auto", "steering")
