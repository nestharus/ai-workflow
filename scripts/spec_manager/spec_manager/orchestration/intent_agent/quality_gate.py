"""Question quality gate — hard enforcement of 5 mandatory rules.

Per response2.md Section 5.5: Every user-facing question must pass ALL
five rules before entering the queue:
    1. Domain language only (no arch/impl jargon unless user introduced)
    2. Bounded answerability (choice/yes_no/value/bounded_text — no open-ended)
    3. Specific behavior or property (concrete, not abstract dimensions)
    4. Scenario grounded (includes scenario or failure mode)
    5. One question per interaction (one atomic decision per QuestionItem)

Enforcement pipeline (Section 5.5.2):
    QuestionDraftStrategy produces candidate →
    QualityValidatorStrategy evaluates (pass/fail + reasons) →
    PASS: enqueue
    FAIL: QuestionRepairStrategy retries (max 2) →
    FAIL after retries: mark UNASKABLE + escalate to Planner
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


_VALID_ANSWER_SPEC_KINDS = {"choice", "yes_no", "value", "bounded_text"}
_VALID_TAXONOMY_TYPES = {
    "INTENT",
    "CONSTRAINT",
    "TRADEOFF",
    "SCOPE",
    "VALIDATION",
}


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_answer_spec_kind(value: str) -> str:
    normalized = _normalize_text(value).replace("-", "_").lower()
    return normalized if normalized in _VALID_ANSWER_SPEC_KINDS else "choice"


def _normalize_taxonomy_type(value: str) -> str:
    normalized = _normalize_text(value).upper()
    return normalized if normalized in _VALID_TAXONOMY_TYPES else "CONSTRAINT"


def _normalize_candidate(candidate: QualityCheckCandidate) -> QualityCheckCandidate:
    return QualityCheckCandidate(
        text=_normalize_text(candidate.text),
        scenario=_normalize_text(candidate.scenario),
        answer_spec_kind=_normalize_answer_spec_kind(candidate.answer_spec_kind),
        taxonomy_type=_normalize_taxonomy_type(candidate.taxonomy_type),
    )


# ---------------------------------------------------------------------------
# QualityCheckRecord
# ---------------------------------------------------------------------------


@dataclass
class QualityChecks:
    """Individual check results for the five quality rules."""

    domain_language_only: bool = False
    bounded_answerability: bool = False
    specific_behavior: bool = False
    scenario_grounded: bool = False
    single_question: bool = False

    @property
    def all_pass(self) -> bool:
        return all([
            self.domain_language_only,
            self.bounded_answerability,
            self.specific_behavior,
            self.scenario_grounded,
            self.single_question,
        ])


@dataclass
class QualityCheckCandidate:
    """The question candidate being evaluated."""

    text: str = ""
    scenario: str = ""
    answer_spec_kind: str = "choice"  # choice | yes_no | value | bounded_text
    taxonomy_type: str = "CONSTRAINT"


@dataclass
class QualityCheckRecord:
    """Record of a quality gate evaluation attempt.

    Per response2.md Section 5.5 QualityCheckRecord JSON schema.
    All attempts are logged in the event log.
    """

    record_id: str = ""
    question_id: str = ""
    attempt: int = 1
    created_at: str = ""
    candidate: QualityCheckCandidate = field(default_factory=QualityCheckCandidate)
    checks: QualityChecks = field(default_factory=QualityChecks)
    result: str = "FAIL"  # PASS | FAIL
    reason: str = ""
    validator_version: str = "qv_1.0"

    def __post_init__(self) -> None:
        if not self.record_id:
            self.record_id = f"qc_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "record_id": self.record_id,
            "question_id": self.question_id,
            "attempt": self.attempt,
            "created_at": self.created_at,
            "candidate": {
                "text": self.candidate.text,
                "scenario": self.candidate.scenario,
                "answer_spec_kind": self.candidate.answer_spec_kind,
                "taxonomy_type": self.candidate.taxonomy_type,
            },
            "checks": {
                "domain_language_only": self.checks.domain_language_only,
                "bounded_answerability": self.checks.bounded_answerability,
                "specific_behavior": self.checks.specific_behavior,
                "scenario_grounded": self.checks.scenario_grounded,
                "single_question": self.checks.single_question,
            },
            "result": self.result,
            "reason": self.reason,
            "validator_version": self.validator_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> QualityCheckRecord:
        """Deserialize from a dict."""
        cand_d = d.get("candidate", {})
        candidate = QualityCheckCandidate(
            text=cand_d.get("text", ""),
            scenario=cand_d.get("scenario", ""),
            answer_spec_kind=cand_d.get("answer_spec_kind", "choice"),
            taxonomy_type=cand_d.get("taxonomy_type", "CONSTRAINT"),
        )
        checks_d = d.get("checks", {})
        checks = QualityChecks(
            domain_language_only=checks_d.get("domain_language_only", False),
            bounded_answerability=checks_d.get("bounded_answerability", False),
            specific_behavior=checks_d.get("specific_behavior", False),
            scenario_grounded=checks_d.get("scenario_grounded", False),
            single_question=checks_d.get("single_question", False),
        )
        return cls(
            record_id=d.get("record_id", ""),
            question_id=d.get("question_id", ""),
            attempt=d.get("attempt", 1),
            created_at=d.get("created_at", ""),
            candidate=candidate,
            checks=checks,
            result=d.get("result", "FAIL"),
            reason=d.get("reason", ""),
            validator_version=d.get("validator_version", "qv_1.0"),
        )


# ---------------------------------------------------------------------------
# QualityValidatorStrategy
# ---------------------------------------------------------------------------


# TODO [R2-5.5.1]: Implement QualityValidatorStrategy
#   - LLM strategy that evaluates a question candidate against the 5 rules
#   - Input: candidate text, scenario, answer_spec_kind, taxonomy_type,
#     concept_map (user_introduced_terms for rule 1 exception)
#   - Output: QualityCheckRecord with per-rule pass/fail and overall result
#   - Rule 1 (domain_language_only): check no arch/impl jargon UNLESS
#     term is in concept_map.user_introduced_terms
#   - Rule 2 (bounded_answerability): must have concrete answer space
#     (choice/yes_no/value/bounded_text, no open-ended)
#   - Rule 3 (specific_behavior): references concrete behavior/outcome,
#     not abstract dimensions like "consistency", "scalability"
#   - Rule 4 (scenario_grounded): includes scenario or failure mode
#   - Rule 5 (single_question): one atomic decision per item
class QualityValidatorStrategy:
    """LLM strategy to evaluate question quality against the five rules.

    Per response2.md Section 5.5.1: pass/fail for each of the five rules.
    Uses LLM to judge domain language and specificity checks.
    """

    def run(
        self,
        candidate_text: str,
        scenario: str,
        answer_spec_kind: str,
        taxonomy_type: str,
        concept_map_user_terms: list[str] | None = None,
        *,
        run_agent: Any = None,
    ) -> QualityCheckRecord:
        """Evaluate a question candidate against the five quality rules."""
        candidate = _normalize_candidate(
            QualityCheckCandidate(
                text=candidate_text,
                scenario=scenario,
                answer_spec_kind=answer_spec_kind,
                taxonomy_type=taxonomy_type,
            )
        )

        checks = QualityChecks()
        deterministic_failures: list[str] = []
        if not candidate.text:
            deterministic_failures.append("Question text is empty.")
            checks.single_question = False
        else:
            checks.single_question = True

        if candidate.answer_spec_kind in _VALID_ANSWER_SPEC_KINDS:
            checks.bounded_answerability = True
        else:
            deterministic_failures.append(
                f"Invalid answer_spec_kind '{candidate.answer_spec_kind}'.",
            )
        if candidate.scenario:
            checks.scenario_grounded = True
        else:
            deterministic_failures.append("Scenario is missing.")

        if not candidate_text.strip():
            checks.single_question = False

        if deterministic_failures:
            return QualityCheckRecord(
                candidate=candidate,
                checks=checks,
                result="FAIL",
                reason="Quality gate deterministic checks failed: "
                + "; ".join(deterministic_failures),
            )

        if run_agent is None:
            logger.debug("No run_agent provided; returning FAIL record.")
            return QualityCheckRecord(
                candidate=candidate,
                checks=QualityChecks(),
                result="FAIL",
                reason="No LLM available for validation.",
            )

        user_terms = concept_map_user_terms or []
        user_terms_text = ", ".join(user_terms) if user_terms else "(none)"

        prompt = (
            "You are a question quality gate evaluator. Evaluate the following "
            "user-facing question candidate against five mandatory rules.\n\n"
            f"CANDIDATE TEXT: {candidate.text}\n"
            f"SCENARIO: {candidate.scenario}\n"
            f"ANSWER SPEC KIND: {candidate.answer_spec_kind}\n"
            f"TAXONOMY TYPE: {candidate.taxonomy_type}\n"
            f"USER-INTRODUCED TERMS (exception for rule 1): {user_terms_text}\n\n"
            "RULES:\n"
            "1. domain_language_only — The question must not use architecture or "
            "implementation jargon (e.g. 'microservice', 'cache layer', 'ORM'). "
            "EXCEPTION: terms listed in USER-INTRODUCED TERMS above are allowed "
            "because the user introduced them.\n"
            "2. bounded_answerability — The question must have a concrete, bounded "
            "answer space: choice, yes/no, value, or bounded text. No open-ended "
            "questions.\n"
            "3. specific_behavior — The question must reference a concrete behavior, "
            "outcome, or property. Not abstract dimensions like 'consistency', "
            "'scalability', 'performance' without context.\n"
            "4. scenario_grounded — The question must include or reference a specific "
            "scenario or failure mode to anchor the decision.\n"
            "5. single_question — The question must ask exactly one atomic decision. "
            "No compound questions.\n\n"
            "Respond with ONLY a JSON object (no other text):\n"
            '{"domain_language_only": true/false, "bounded_answerability": true/false, '
            '"specific_behavior": true/false, "scenario_grounded": true/false, '
            '"single_question": true/false, "reason": "brief explanation of any failures"}'
        )

        try:
            raw_response = run_agent(prompt)
        except Exception:
            logger.exception("LLM call failed during quality validation.")
            return QualityCheckRecord(
                candidate=candidate,
                checks=checks,
                result="FAIL",
                reason="LLM call failed.",
            )

        # Parse LLM response into checks.
        from spec_manager.core.json_extraction import _extract_json_payload

        try:
            import json
            payload = _extract_json_payload(raw_response)
            parsed = json.loads(payload)
        except Exception:
            logger.warning("Failed to parse LLM quality gate response.")
            return QualityCheckRecord(
                candidate=candidate,
                checks=checks,
                result="FAIL",
                reason=f"Unparseable LLM response: {raw_response[:200]}",
            )

        parsed_checks = QualityChecks(
            domain_language_only=bool(parsed.get("domain_language_only", False)),
            bounded_answerability=checks.bounded_answerability,
            specific_behavior=bool(parsed.get("specific_behavior", False)),
            scenario_grounded=checks.scenario_grounded
            and bool(parsed.get("scenario_grounded", False)),
            single_question=checks.single_question
            and bool(parsed.get("single_question", False)),
        )
        checks.domain_language_only = parsed_checks.domain_language_only
        checks.specific_behavior = parsed_checks.specific_behavior
        checks.scenario_grounded = parsed_checks.scenario_grounded
        checks.single_question = parsed_checks.single_question
        reason = str(parsed.get("reason", ""))
        result = "PASS" if checks.all_pass else "FAIL"

        return QualityCheckRecord(
            candidate=candidate,
            checks=checks,
            result=result,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# QuestionRepairStrategy
# ---------------------------------------------------------------------------


# TODO [R2-5.5.2]: Implement QuestionRepairStrategy
#   - LLM strategy that repairs a failed question draft
#   - Input: failed QualityCheckRecord (with per-rule failures) +
#     original signal context
#   - Output: repaired candidate (text, scenario, answer_spec)
#   - Max 2 retries: attempt 1 (original) + attempt 2 (repair 1) +
#     attempt 3 (repair 2). If still fails → UNASKABLE
#   - Must NOT degrade quality to pass: if it cannot fix, return None
#   - Each repair attempt is a new QualityCheckRecord in the event log
class QuestionRepairStrategy:
    """LLM strategy to repair failed question drafts.

    Per response2.md Section 5.5.2: max 2 retries. If repair still fails,
    the question is marked UNASKABLE and escalated to Planner for
    reformulation or auto-resolution (never degrade and ask anyway).
    """

    MAX_RETRIES: int = 2

    def repair(
        self,
        failed_record: QualityCheckRecord,
        signal_context: dict[str, Any] | None = None,
        *,
        run_agent: Any = None,
    ) -> QualityCheckCandidate | None:
        """Attempt to repair a failed question draft.

        Returns repaired candidate or None if repair not possible.
        """
        if run_agent is None:
            logger.debug("No run_agent provided; cannot repair.")
            return None

        checks = failed_record.checks
        failures: list[str] = []
        if not checks.domain_language_only:
            failures.append(
                "domain_language_only: uses architecture/implementation jargon"
            )
        if not checks.bounded_answerability:
            failures.append(
                "bounded_answerability: answer space is not bounded "
                "(must be choice/yes_no/value/bounded_text)"
            )
        if not checks.specific_behavior:
            failures.append(
                "specific_behavior: too abstract, needs concrete behavior/outcome"
            )
        if not checks.scenario_grounded:
            failures.append(
                "scenario_grounded: missing scenario or failure mode"
            )
        if not checks.single_question:
            failures.append(
                "single_question: compound question, must ask one atomic decision"
            )

        failures_text = "\n".join(f"  - {f}" for f in failures)
        context_text = ""
        if signal_context:
            context_text = (
                f"\nSIGNAL CONTEXT: {signal_context}\n"
            )

        prompt = (
            "You are a question repair assistant. A user-facing question draft "
            "failed quality checks. Repair it so it passes ALL rules.\n\n"
            f"ORIGINAL TEXT: {failed_record.candidate.text}\n"
            f"ORIGINAL SCENARIO: {failed_record.candidate.scenario}\n"
            f"ANSWER SPEC KIND: {failed_record.candidate.answer_spec_kind}\n"
            f"TAXONOMY TYPE: {failed_record.candidate.taxonomy_type}\n"
            f"FAILURE REASON: {failed_record.reason}\n"
            f"FAILED CHECKS:\n{failures_text}\n"
            f"{context_text}\n"
            "Produce a repaired question that passes all five rules:\n"
            "1. domain_language_only — no arch/impl jargon\n"
            "2. bounded_answerability — concrete answer space\n"
            "3. specific_behavior — concrete behavior/outcome\n"
            "4. scenario_grounded — includes scenario or failure mode\n"
            "5. single_question — one atomic decision\n\n"
            "Respond with ONLY a JSON object (no other text):\n"
            '{"text": "repaired question text", "scenario": "scenario text", '
            '"answer_spec_kind": "choice|yes_no|value|bounded_text", '
            '"taxonomy_type": "CONSTRAINT|TRADEOFF|SCOPE|VALIDATION|INTENT"}'
        )

        try:
            raw_response = run_agent(prompt)
        except Exception:
            logger.exception("LLM call failed during question repair.")
            return None

        from spec_manager.core.json_extraction import _extract_json_payload

        try:
            import json
            payload = _extract_json_payload(raw_response)
            parsed = json.loads(payload)
        except Exception:
            logger.warning("Failed to parse LLM repair response.")
            return None

        text = parsed.get("text", "")
        if not text:
            return None

        return _normalize_candidate(
            QualityCheckCandidate(
                text=text,
                scenario=parsed.get("scenario", ""),
                answer_spec_kind=parsed.get(
                    "answer_spec_kind",
                    failed_record.candidate.answer_spec_kind,
                ),
                taxonomy_type=parsed.get(
                    "taxonomy_type",
                    failed_record.candidate.taxonomy_type,
                ),
            )
        )


# ---------------------------------------------------------------------------
# QuestionDraftStrategy
# ---------------------------------------------------------------------------


# TODO [R2-3.3]: Implement QuestionDraftStrategy
#   - LLM strategy that converts a UserQuestionSignal into a user-facing
#     question draft at constraint level
#   - Input: signal (text, taxonomy_hint, canonical_key_hint, context),
#     problem_frame, concept_map
#   - Output: draft with text, scenario, why_it_matters, answer_spec
#   - Must reframe prohibited types (ARCHITECTURE → CONSTRAINT/TRADEOFF etc.)
#     using the reframe patterns from Section 5.4.2
#   - Draft passes through quality gate pipeline before enqueue
class QuestionDraftStrategy:
    """LLM strategy to produce user-facing question drafts from signals.

    Converts internal technical signals into domain-language questions
    with scenarios and bounded answer specs.
    """

    def draft(
        self,
        signal_text: str,
        taxonomy_hint: str,
        canonical_key_hint: str,
        context: dict[str, Any] | None = None,
        problem_frame: dict[str, Any] | None = None,
        concept_map_user_terms: list[str] | None = None,
        *,
        run_agent: Any = None,
    ) -> QualityCheckCandidate:
        """Draft a user-facing question from an internal signal."""
        if run_agent is None:
            logger.debug("No run_agent provided; returning default candidate.")
            return QualityCheckCandidate(
                text=signal_text,
                scenario="",
                answer_spec_kind="choice",
                taxonomy_type=taxonomy_hint or "CONSTRAINT",
            )

        user_terms = concept_map_user_terms or []
        user_terms_text = ", ".join(user_terms) if user_terms else "(none)"
        context_text = ""
        if context:
            context_text = f"\nADDITIONAL CONTEXT: {context}\n"
        frame_text = ""
        if problem_frame:
            frame_text = f"\nPROBLEM FRAME: {problem_frame}\n"

        prompt = (
            "You are a question drafting assistant. Convert the following "
            "internal signal into a user-facing question that a non-technical "
            "stakeholder can answer.\n\n"
            f"INTERNAL SIGNAL: {signal_text}\n"
            f"TAXONOMY HINT: {taxonomy_hint}\n"
            f"CANONICAL KEY: {canonical_key_hint}\n"
            f"USER-KNOWN TERMS: {user_terms_text}\n"
            f"{context_text}{frame_text}\n"
            "Requirements:\n"
            "1. Use ONLY domain language (no architecture/implementation jargon)\n"
            "2. Include a concrete scenario or failure mode\n"
            "3. Ensure the answer space is bounded (choice/yes_no/value/bounded_text)\n"
            "4. Ask exactly ONE atomic decision\n"
            "5. Reference specific behavior or outcome, not abstract qualities\n\n"
            "Respond with ONLY a JSON object (no other text):\n"
            '{"text": "the user-facing question", "scenario": "scenario text", '
            '"answer_spec_kind": "choice|yes_no|value|bounded_text", '
            '"taxonomy_type": "CONSTRAINT|TRADEOFF|SCOPE|VALIDATION|INTENT"}'
        )

        try:
            raw_response = run_agent(prompt)
        except Exception:
            logger.exception("LLM call failed during question drafting.")
            return QualityCheckCandidate(
                text=signal_text,
                scenario="",
                answer_spec_kind="choice",
                taxonomy_type=taxonomy_hint or "CONSTRAINT",
            )

        from spec_manager.core.json_extraction import _extract_json_payload

        try:
            import json
            payload = _extract_json_payload(raw_response)
            parsed = json.loads(payload)
        except Exception:
            logger.warning("Failed to parse LLM draft response.")
            return QualityCheckCandidate(
                text=signal_text,
                scenario="",
                answer_spec_kind="choice",
                taxonomy_type=taxonomy_hint or "CONSTRAINT",
            )

        return QualityCheckCandidate(
            text=parsed.get("text", signal_text),
            scenario=parsed.get("scenario", ""),
            answer_spec_kind=parsed.get("answer_spec_kind", "choice"),
            taxonomy_type=parsed.get("taxonomy_type", taxonomy_hint or "CONSTRAINT"),
        )


# ---------------------------------------------------------------------------
# Quality enforcement pipeline
# ---------------------------------------------------------------------------


# TODO [R2-5.5.2]: Implement enforce_quality_gate() — full pipeline
#   - Takes a QuestionDraftStrategy candidate and runs the enforcement pipeline:
#     1. QualityValidatorStrategy evaluates candidate
#     2. If PASS → return (candidate, record, True)
#     3. If FAIL → QuestionRepairStrategy repairs (up to MAX_RETRIES)
#     4. Re-evaluate after each repair
#     5. If FAIL after all retries → return (None, records, False)
#   - All QualityCheckRecords are returned for event log persistence
#   - Used by IntentAgentOrchestrator.ingest_signal()
def enforce_quality_gate(
    candidate: QualityCheckCandidate,
    question_id: str,
    concept_map_user_terms: list[str] | None = None,
    signal_context: dict[str, Any] | None = None,
    *,
    validator: QualityValidatorStrategy | None = None,
    repairer: QuestionRepairStrategy | None = None,
    run_agent: Any = None,
) -> tuple[QualityCheckCandidate | None, list[QualityCheckRecord], bool]:
    """Run the full quality enforcement pipeline.

    Returns (final_candidate_or_None, all_records, passed).
    """
    if validator is None:
        validator = QualityValidatorStrategy()
    if repairer is None:
        repairer = QuestionRepairStrategy()

    records: list[QualityCheckRecord] = []
    current_candidate = _normalize_candidate(candidate)

    # Attempt 1: validate original candidate.
    record = validator.run(
        candidate_text=current_candidate.text,
        scenario=current_candidate.scenario,
        answer_spec_kind=current_candidate.answer_spec_kind,
        taxonomy_type=current_candidate.taxonomy_type,
        concept_map_user_terms=concept_map_user_terms,
        run_agent=run_agent,
    )
    record.question_id = question_id
    record.attempt = 1
    records.append(record)

    if record.result == "PASS":
        return (current_candidate, records, True)

    # Repair loop: up to MAX_RETRIES repair attempts.
    for retry in range(repairer.MAX_RETRIES):
        repaired = repairer.repair(
            failed_record=record,
            signal_context=signal_context,
            run_agent=run_agent,
        )
        if repaired is None:
            logger.info(
                "Repair attempt %d returned None; stopping retries.",
                retry + 1,
            )
            break

        current_candidate = _normalize_candidate(repaired)

        # Re-validate the repaired candidate.
        record = validator.run(
            candidate_text=current_candidate.text,
            scenario=current_candidate.scenario,
            answer_spec_kind=current_candidate.answer_spec_kind,
            taxonomy_type=current_candidate.taxonomy_type,
            concept_map_user_terms=concept_map_user_terms,
            run_agent=run_agent,
        )
        record.question_id = question_id
        record.attempt = retry + 2  # attempt 2, 3, ...
        records.append(record)

        if record.result == "PASS":
            return (current_candidate, records, True)

    # All retries exhausted — FAIL.
    logger.warning(
        "Quality gate failed for question %s after %d attempts.",
        question_id,
        len(records),
    )
    return (None, records, False)
