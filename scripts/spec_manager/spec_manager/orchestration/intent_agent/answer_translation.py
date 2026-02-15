"""Answer translation — non-authoritative projection of user answers.

Per response2.md Section 4.4: The AnswerTranslation artifact is a boundary
projection. It is non-authoritative. The Intent Agent produces it; the
Planner ingests and validates it; only the Planner writes to ConstraintsStore.

Per response2.md Section 4.3: AnswerTranslateStrategy may propose follow-up
questions, but:
    - Follow-ups must pass the same quality gate as all other questions
    - Recursion cap: max 2 follow-up questions per user answer
    - Follow-ups that fail quality gate are routed to Planner for
      auto-resolution, never surfaced as degraded questions
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec_manager.orchestration.intent_agent.taxonomy import normalize_user_facing_taxonomy

logger = logging.getLogger(__name__)


_VALID_FOLLOWUP_ANSWER_SPEC_KINDS = frozenset(
    {
        "choice",
        "yes_no",
        "value",
        "bounded_text",
    }
)

TRANSLATION_STATUS_SUCCEEDED = "succeeded"
TRANSLATION_STATUS_FAILED = "failed"


# ---------------------------------------------------------------------------
# AnswerTranslation artifact
# ---------------------------------------------------------------------------


@dataclass
class ConstraintCandidate:
    """Non-authoritative constraint candidate extracted from user answer."""

    canonical_key_hint: str = ""
    question: str = ""  # proposed constraint question (domain language)
    answer: str = ""  # proposed constraint answer (domain language)
    scope_kind: str = "FEATURE_SPECIFIC"  # SYSTEM_WIDE | FEATURE_SPECIFIC
    target_slice_id: str = ""
    confidence: float = 0.0
    rationale: str = ""


@dataclass
class ScopeCandidate:
    """Non-authoritative scope candidate extracted from user answer."""

    # Wire format uses keys "in"/"out"; dataclass fields avoid reserved keyword.
    scope_in: list[str] = field(default_factory=list)
    scope_out: list[str] = field(default_factory=list)


@dataclass
class TradeoffCandidate:
    """Non-authoritative tradeoff candidate extracted from user answer."""

    axis: str = ""  # domain-level tradeoff axis (no implementation terms)
    preference: str = ""  # user preference phrased as a priority
    confidence: float = 0.0


@dataclass
class ValidationCandidate:
    """Non-authoritative validation criterion from user answer."""

    acceptance_statement: str = ""


@dataclass
class FollowupQuestionDraft:
    """Draft follow-up question; must pass the same quality gate before enqueue."""

    taxonomy_type: str
    canonical_key_hint: str
    text: str
    scenario: str
    answer_spec: dict[str, Any]
    draft_id: str = ""

    def __post_init__(self) -> None:
        if not self.draft_id:
            self.draft_id = f"fq_{uuid.uuid4().hex[:8]}"
        if not isinstance(self.taxonomy_type, str) or not self.taxonomy_type.strip():
            raise ValueError("followup_question_draft.taxonomy_type is required")
        if not isinstance(self.scenario, str) or not self.scenario.strip():
            raise ValueError("followup_question_draft.scenario is required")
        normalized_answer_spec = _normalize_followup_answer_spec(self.answer_spec)
        if normalized_answer_spec is None:
            raise ValueError("followup_question_draft.answer_spec is invalid")
        self.taxonomy_type = normalize_user_facing_taxonomy(self.taxonomy_type)
        self.answer_spec = normalized_answer_spec


@dataclass
class UserAnswer:
    """Captured user answer data."""

    raw_text: str = ""
    selected_choice_id: str = ""
    parsed_values: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedContent:
    """All candidates extracted from the user answer."""

    constraint_candidates: list[ConstraintCandidate] = field(default_factory=list)
    scope_candidates: list[ScopeCandidate] = field(default_factory=list)
    tradeoff_candidates: list[TradeoffCandidate] = field(default_factory=list)
    validation_candidates: list[ValidationCandidate] = field(default_factory=list)
    followup_question_drafts: list[FollowupQuestionDraft] = field(default_factory=list)
    followup_omissions: list[dict[str, Any]] = field(default_factory=list)
    translation_failures: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RecursionBudget:
    """Recursion budget for follow-up questions."""

    max_followups: int = 2
    used_followups: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.max_followups, int):
            raise TypeError("recursion_budget.max_followups must be an integer")
        if self.max_followups != 2:
            raise ValueError("recursion_budget.max_followups must be exactly 2")
        if not isinstance(self.used_followups, int):
            raise TypeError("recursion_budget.used_followups must be an integer")
        if self.used_followups < 0:
            raise ValueError("recursion_budget.used_followups must be >= 0")

    @property
    def remaining(self) -> int:
        return max(0, self.max_followups - self.used_followups)


@dataclass
class TranslationProvenance:
    """Provenance for the translation artifact."""

    produced_by: str = "INTENT_AGENT"
    model_id: str = ""


@dataclass
class AnswerTranslation:
    """Non-authoritative translation of a user answer.

    Per response2.md Section 4.4 JSON schema. This artifact is produced
    by the Intent Agent and consumed by the Planner. The Planner validates
    it and decides what becomes authoritative.

    The Intent Agent NEVER writes constraints — it only produces this
    projection artifact.
    """

    version: int = 1
    translation_id: str = ""
    run_id: str = ""
    session_id: str = ""
    question_id: str = ""
    canonical_key_hint: str = ""
    answer_id: str = ""
    created_at: str = ""
    translation_status: str = TRANSLATION_STATUS_SUCCEEDED
    user_answer: UserAnswer = field(default_factory=UserAnswer)
    extracted: ExtractedContent = field(default_factory=ExtractedContent)
    recursion_budget: RecursionBudget = field(default_factory=RecursionBudget)
    provenance: TranslationProvenance = field(default_factory=TranslationProvenance)

    def __post_init__(self) -> None:
        if not self.translation_id:
            self.translation_id = f"at_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the translation artifact to a plain dict."""
        return {
            "version": self.version,
            "translation_id": self.translation_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "question_id": self.question_id,
            "canonical_key_hint": self.canonical_key_hint,
            "answer_id": self.answer_id,
            "created_at": self.created_at,
            "translation_status": self.translation_status,
            "user_answer": {
                "raw_text": self.user_answer.raw_text,
                "selected_choice_id": self.user_answer.selected_choice_id,
                "parsed_values": self.user_answer.parsed_values,
            },
            "extracted": {
                "constraint_candidates": [
                    {
                        "canonical_key_hint": c.canonical_key_hint,
                        "question": c.question,
                        "answer": c.answer,
                        "scope_kind": c.scope_kind,
                        "target_slice_id": c.target_slice_id,
                        "confidence": c.confidence,
                        "rationale": c.rationale,
                    }
                    for c in self.extracted.constraint_candidates
                ],
                "scope_candidates": [
                    {
                        "in": s.scope_in,
                        "out": s.scope_out,
                    }
                    for s in self.extracted.scope_candidates
                ],
                "tradeoff_candidates": [
                    {
                        "axis": t.axis,
                        "preference": t.preference,
                        "confidence": t.confidence,
                    }
                    for t in self.extracted.tradeoff_candidates
                ],
                "validation_candidates": [
                    {
                        "acceptance_statement": v.acceptance_statement,
                    }
                    for v in self.extracted.validation_candidates
                ],
                "followup_question_drafts": [
                    {
                        "draft_id": fq.draft_id,
                        "taxonomy_type": fq.taxonomy_type,
                        "canonical_key_hint": fq.canonical_key_hint,
                        "text": fq.text,
                        "scenario": fq.scenario,
                        "answer_spec": fq.answer_spec,
                    }
                    for fq in self.extracted.followup_question_drafts
                ],
                "followup_omissions": self.extracted.followup_omissions,
                "translation_failures": self.extracted.translation_failures,
            },
            "recursion_budget": {
                "max_followups": self.recursion_budget.max_followups,
                "used_followups": self.recursion_budget.used_followups,
            },
            "provenance": {
                "produced_by": self.provenance.produced_by,
                "model_id": self.provenance.model_id,
            },
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AnswerTranslation:
        """Reconstruct an AnswerTranslation from a plain dict."""
        required_fields = (
            "translation_id",
            "run_id",
            "session_id",
            "question_id",
            "answer_id",
            "created_at",
            "user_answer",
            "extracted",
        )
        missing_fields = [field_name for field_name in required_fields if field_name not in d]
        if missing_fields:
            raise ValueError(
                "AnswerTranslation deserialization missing required fields: "
                + ", ".join(missing_fields),
            )

        translation_id = d["translation_id"]
        run_id = d["run_id"]
        session_id = d["session_id"]
        question_id = d["question_id"]
        answer_id = d["answer_id"]
        created_at = d["created_at"]
        ua_raw = d["user_answer"]
        ext_raw = d["extracted"]
        if not isinstance(translation_id, str) or not translation_id:
            raise ValueError(
                "AnswerTranslation deserialization invalid required field: translation_id",
            )
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(
                "AnswerTranslation deserialization invalid required field: run_id",
            )
        if not isinstance(session_id, str) or not session_id:
            raise ValueError(
                "AnswerTranslation deserialization invalid required field: session_id",
            )
        if not isinstance(question_id, str) or not question_id:
            raise ValueError(
                "AnswerTranslation deserialization invalid required field: question_id",
            )
        if not isinstance(answer_id, str) or not answer_id:
            raise ValueError(
                "AnswerTranslation deserialization invalid required field: answer_id",
            )
        if not isinstance(created_at, str) or not created_at:
            raise ValueError(
                "AnswerTranslation deserialization invalid required field: created_at",
            )
        if not isinstance(ua_raw, dict):
            raise TypeError(
                "AnswerTranslation deserialization invalid required field: user_answer",
            )
        if not isinstance(ext_raw, dict):
            raise TypeError(
                "AnswerTranslation deserialization invalid required field: extracted",
            )

        if "raw_text" not in ua_raw:
            raise ValueError(
                "AnswerTranslation deserialization missing required field: user_answer.raw_text",
            )
        raw_text = ua_raw["raw_text"]
        if not isinstance(raw_text, str):
            raise TypeError(
                "AnswerTranslation deserialization invalid required field: user_answer.raw_text",
            )
        user_answer = UserAnswer(
            raw_text=raw_text,
            selected_choice_id=ua_raw.get("selected_choice_id", ""),
            parsed_values=ua_raw.get("parsed_values", {}),
        )

        followup_question_drafts, followup_omission_records = _parse_followup_question_drafts(
            ext_raw.get("followup_question_drafts", []),
        )
        existing_followup_omissions = ext_raw.get("followup_omissions", [])
        if not isinstance(existing_followup_omissions, list):
            existing_followup_omissions = [
                {
                    "reason": "invalid_followup_omissions_container",
                    "container_type": type(existing_followup_omissions).__name__,
                    "dropped_count": 1,
                }
            ]

        extracted = ExtractedContent(
            constraint_candidates=[
                ConstraintCandidate(**c) for c in ext_raw.get("constraint_candidates", [])
            ],
            scope_candidates=[
                ScopeCandidate(
                    scope_in=s.get("in", []),
                    scope_out=s.get("out", []),
                )
                for s in ext_raw.get("scope_candidates", [])
            ],
            tradeoff_candidates=[
                TradeoffCandidate(**t) for t in ext_raw.get("tradeoff_candidates", [])
            ],
            validation_candidates=[
                ValidationCandidate(**v) for v in ext_raw.get("validation_candidates", [])
            ],
            followup_question_drafts=followup_question_drafts,
            followup_omissions=existing_followup_omissions + followup_omission_records,
            translation_failures=ext_raw.get("translation_failures", []),
        )

        rb_raw = d.get("recursion_budget", {})
        recursion_budget = RecursionBudget(
            max_followups=rb_raw.get("max_followups", 2),
            used_followups=rb_raw.get("used_followups", 0),
        )

        prov_raw = d.get("provenance", {})
        provenance = TranslationProvenance(
            produced_by=prov_raw.get("produced_by", "INTENT_AGENT"),
            model_id=prov_raw.get("model_id", ""),
        )

        return cls(
            version=d.get("version", 1),
            translation_id=translation_id,
            run_id=run_id,
            session_id=session_id,
            question_id=question_id,
            canonical_key_hint=d.get("canonical_key_hint", ""),
            answer_id=answer_id,
            created_at=created_at,
            translation_status=d.get("translation_status", TRANSLATION_STATUS_SUCCEEDED),
            user_answer=user_answer,
            extracted=extracted,
            recursion_budget=recursion_budget,
            provenance=provenance,
        )

    def save(self, run_dir: Path) -> Path:
        """Persist translation artifact to the run directory."""
        import json

        out_dir = run_dir / "intent" / "answer_translations"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{self.translation_id}.json"
        out_path.write_text(
            json.dumps(
                self.to_dict(),
                indent=2,
                sort_keys=True,
                separators=(",", ": "),
            ),
            encoding="utf-8",
        )
        return out_path

    @classmethod
    def load(cls, run_dir: Path, translation_id: str) -> AnswerTranslation:
        """Load a translation artifact from the run directory."""
        import json

        path = run_dir / "intent" / "answer_translations" / f"{translation_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# AnswerTranslateStrategy
# ---------------------------------------------------------------------------


class AnswerTranslateStrategy:
    """LLM strategy to translate user answers into AnswerTranslation artifacts.

    Per response2.md Section 4: Produces non-authoritative projections
    that the Planner ingests, validates, and decides what becomes
    authoritative.
    """

    def translate(
        self,
        question_id: str,
        taxonomy_type: str,
        canonical_key: str,
        user_prompt_text: str,
        raw_answer: str,
        selected_choice_id: str = "",
        problem_frame: dict[str, Any] | None = None,
        concept_map: dict[str, Any] | None = None,
        recursion_budget: RecursionBudget | None = None,
        *,
        run_agent: Any = None,
    ) -> AnswerTranslation:
        """Translate a user answer into an AnswerTranslation artifact.

        Uses LLM to extract constraint, scope, tradeoff, and validation
        candidates from the raw user answer.  If ``run_agent`` is None,
        returns a minimal translation with only the raw text recorded.
        """
        if recursion_budget is None:
            recursion_budget = RecursionBudget()

        # Enforce global budget: if no remaining follow-ups, strip follow-up generation
        budget_exhausted = recursion_budget.remaining <= 0

        user_answer = UserAnswer(
            raw_text=raw_answer,
            selected_choice_id=selected_choice_id,
        )

        # Minimal fallback when no LLM is available
        if run_agent is None:
            return AnswerTranslation(
                question_id=question_id,
                canonical_key_hint=canonical_key,
                user_answer=user_answer,
                extracted=ExtractedContent(),
                recursion_budget=recursion_budget,
            )

        context_parts: list[str] = []
        if problem_frame:
            context_parts.append(f"Problem frame: {problem_frame}")
        if concept_map:
            context_parts.append(f"Concept map: {concept_map}")
        context_block = "\n".join(context_parts)

        remaining_followups = recursion_budget.remaining

        prompt = (
            "You are translating a user's answer into structured candidates "
            "for a specification planner. This is a NON-AUTHORITATIVE projection.\n\n"
            f"Original question (taxonomy: {taxonomy_type}, key: {canonical_key}):\n"
            f"  {user_prompt_text}\n\n"
            f"User's answer:\n  {raw_answer}\n"
        )
        if selected_choice_id:
            prompt += f"\nSelected choice: {selected_choice_id}\n"
        if context_block:
            prompt += f"\n{context_block}\n"

        prompt += (
            "\nExtract from the user's answer the following (each list may be "
            "empty if nothing relevant is found):\n\n"
            "1. constraint_candidates — each with: canonical_key_hint (str), "
            "question (str), answer (str), scope_kind (SYSTEM_WIDE|FEATURE_SPECIFIC), "
            "target_slice_id (str, empty if unknown), confidence (0.0-1.0), "
            "rationale (str)\n"
            "2. scope_candidates — each with: in (list[str]), out (list[str])\n"
            "3. tradeoff_candidates — each with: axis (str), preference (str), "
            "confidence (0.0-1.0)\n"
            "4. validation_candidates — each with: acceptance_statement (str)\n"
        )

        if remaining_followups > 0:
            prompt += (
                f"5. followup_question_drafts (max {remaining_followups}) — each with: "
                "taxonomy_type (INTENT|CONSTRAINT|TRADEOFF|SCOPE|VALIDATION), "
                "canonical_key_hint (str), text (str), scenario (str), "
                'answer_spec (object with "kind" key)\n'
            )
        else:
            prompt += "5. followup_question_drafts — MUST be empty (recursion budget exhausted)\n"

        prompt += (
            "\nRespond with JSON:\n"
            "{\n"
            '  "constraint_candidates": [...],\n'
            '  "scope_candidates": [...],\n'
            '  "tradeoff_candidates": [...],\n'
            '  "validation_candidates": [...],\n'
            '  "followup_question_drafts": [...]\n'
            "}"
        )

        import json

        raw_llm_output = ""
        extracted_payload = ""
        try:
            raw = run_agent(prompt)
            raw_llm_output = raw if isinstance(raw, str) else repr(raw)
            payload = _extract_translation_json_payload(raw)
            extracted_payload = payload if isinstance(payload, str) else repr(payload)
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.debug("AnswerTranslateStrategy LLM parse failed (%s)", exc)
            extracted = ExtractedContent(
                translation_failures=[
                    {
                        "reason": "llm_parse_failure",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "raw_llm_output": raw_llm_output,
                        "json_payload": extracted_payload,
                    }
                ]
            )
            return AnswerTranslation(
                question_id=question_id,
                canonical_key_hint=canonical_key,
                user_answer=user_answer,
                extracted=extracted,
                recursion_budget=recursion_budget,
                translation_status=TRANSLATION_STATUS_FAILED,
            )

        # Build extracted content from parsed data
        constraint_candidates = [
            ConstraintCandidate(
                canonical_key_hint=c.get("canonical_key_hint", ""),
                question=c.get("question", ""),
                answer=c.get("answer", ""),
                scope_kind=c.get("scope_kind", "FEATURE_SPECIFIC"),
                target_slice_id=c.get("target_slice_id", ""),
                confidence=float(c.get("confidence", 0.0)),
                rationale=c.get("rationale", ""),
            )
            for c in data.get("constraint_candidates", [])
            if isinstance(c, dict)
        ]

        scope_candidates = [
            ScopeCandidate(
                scope_in=s.get("in", []),
                scope_out=s.get("out", []),
            )
            for s in data.get("scope_candidates", [])
            if isinstance(s, dict)
        ]

        tradeoff_candidates = [
            TradeoffCandidate(
                axis=t.get("axis", ""),
                preference=t.get("preference", ""),
                confidence=float(t.get("confidence", 0.0)),
            )
            for t in data.get("tradeoff_candidates", [])
            if isinstance(t, dict)
        ]

        validation_candidates = [
            ValidationCandidate(
                acceptance_statement=v.get("acceptance_statement", ""),
            )
            for v in data.get("validation_candidates", [])
            if isinstance(v, dict)
        ]

        raw_followups = data.get("followup_question_drafts", [])
        followup_omissions: list[dict[str, Any]] = []
        if not isinstance(raw_followups, list):
            followup_omissions.append(
                {
                    "reason": "invalid_followup_container",
                    "container_type": type(raw_followups).__name__,
                    "dropped_count": 1,
                }
            )
            raw_followups = []
        else:
            received_followups = len(raw_followups)
            if budget_exhausted:
                if received_followups > 0:
                    followup_omissions.append(
                        {
                            "reason": "budget_exhausted",
                            "dropped_count": received_followups,
                            "remaining_budget": remaining_followups,
                        }
                    )
                raw_followups = []
            else:
                if received_followups > remaining_followups:
                    followup_omissions.append(
                        {
                            "reason": "budget_limited",
                            "dropped_count": received_followups - remaining_followups,
                            "remaining_budget": remaining_followups,
                        }
                    )
                raw_followups = raw_followups[:remaining_followups]

        followup_question_drafts, followup_metadata_omissions = _parse_followup_question_drafts(
            raw_followups,
        )
        followup_omissions.extend(followup_metadata_omissions)

        extracted = ExtractedContent(
            constraint_candidates=constraint_candidates,
            scope_candidates=scope_candidates,
            tradeoff_candidates=tradeoff_candidates,
            validation_candidates=validation_candidates,
            followup_question_drafts=followup_question_drafts,
            followup_omissions=followup_omissions,
        )

        # Update recursion budget with how many follow-ups we produced
        new_budget = RecursionBudget(
            max_followups=recursion_budget.max_followups,
            used_followups=recursion_budget.used_followups + len(followup_question_drafts),
        )

        return AnswerTranslation(
            question_id=question_id,
            canonical_key_hint=canonical_key,
            user_answer=user_answer,
            extracted=extracted,
            recursion_budget=new_budget,
        )


def _parse_followup_question_drafts(
    raw_followups: Any,
) -> tuple[list[FollowupQuestionDraft], list[dict[str, Any]]]:
    drafts: list[FollowupQuestionDraft] = []
    omissions: list[dict[str, Any]] = []
    if not isinstance(raw_followups, list):
        omissions.append(
            {
                "reason": "invalid_followup_container",
                "container_type": type(raw_followups).__name__,
                "dropped_count": 1,
            }
        )
        return drafts, omissions

    for index, raw_followup in enumerate(raw_followups):
        if not isinstance(raw_followup, dict):
            omissions.append(
                {
                    "reason": "invalid_followup_item",
                    "index": index,
                    "item_type": type(raw_followup).__name__,
                    "dropped_count": 1,
                }
            )
            continue

        missing_fields: list[str] = []
        invalid_fields: list[str] = []

        taxonomy_value = raw_followup.get("taxonomy_type")
        if not isinstance(taxonomy_value, str) or not taxonomy_value.strip():
            missing_fields.append("taxonomy_type")

        scenario_value = raw_followup.get("scenario")
        if not isinstance(scenario_value, str) or not scenario_value.strip():
            missing_fields.append("scenario")

        if "answer_spec" not in raw_followup:
            missing_fields.append("answer_spec")
            normalized_answer_spec = None
        else:
            normalized_answer_spec = _normalize_followup_answer_spec(
                raw_followup.get("answer_spec")
            )
            if normalized_answer_spec is None:
                invalid_fields.append("answer_spec")

        if missing_fields or invalid_fields:
            omission_record: dict[str, Any] = {
                "reason": "incomplete_followup_metadata",
                "index": index,
                "dropped_count": 1,
            }
            if missing_fields:
                omission_record["missing_fields"] = missing_fields
            if invalid_fields:
                omission_record["invalid_fields"] = invalid_fields
            omissions.append(omission_record)
            continue

        draft_id = raw_followup.get("draft_id", "")
        canonical_key_hint = raw_followup.get("canonical_key_hint", "")
        text = raw_followup.get("text", "")
        drafts.append(
            FollowupQuestionDraft(
                draft_id=draft_id if isinstance(draft_id, str) else "",
                taxonomy_type=normalize_user_facing_taxonomy(taxonomy_value),
                canonical_key_hint=(
                    canonical_key_hint if isinstance(canonical_key_hint, str) else ""
                ),
                text=text if isinstance(text, str) else "",
                scenario=scenario_value,
                answer_spec=normalized_answer_spec,
            )
        )

    return drafts, omissions


def _normalize_followup_answer_spec(raw_spec: Any) -> dict[str, Any] | None:
    if not isinstance(raw_spec, dict):
        return None

    kind_raw = raw_spec.get("kind")
    if not isinstance(kind_raw, str) or not kind_raw.strip():
        return None
    kind = kind_raw.strip().lower()
    if kind not in _VALID_FOLLOWUP_ANSWER_SPEC_KINDS:
        return None

    normalized: dict[str, Any] = {"kind": kind}
    if kind == "choice":
        choices = raw_spec.get("choices", [])
        if isinstance(choices, list):
            normalized["choices"] = [str(choice) for choice in choices]
    if "direction" in raw_spec:
        normalized["direction"] = raw_spec.get("direction", "")
    if "value_type" in raw_spec:
        normalized["value_type"] = str(raw_spec.get("value_type", "")).strip()
    if "units_hint" in raw_spec:
        normalized["units_hint"] = str(raw_spec.get("units_hint", "")).strip()
    if "text_bounds" in raw_spec and isinstance(raw_spec.get("text_bounds"), dict):
        text_bounds = raw_spec["text_bounds"]
        normalized["text_bounds"] = {
            str(k): int(v)
            for k, v in text_bounds.items()
            if str(k) in {"max_items", "max_chars"} and isinstance(v, int | float)
        }
    return normalized


def _extract_translation_json_payload(output: str) -> str:
    """Extract the first valid JSON object/array from an answer-translation output."""
    import json

    cleaned = output.strip()
    if not cleaned:
        return cleaned

    lines = [line for line in cleaned.splitlines() if not line.startswith("[agent-exec]")]
    cleaned = "\n".join(lines).strip()

    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            fence_end = cleaned.find("```", first_newline + 1)
            if fence_end != -1:
                cleaned = cleaned[first_newline + 1 : fence_end].strip()

    decoder = json.JSONDecoder()
    first_obj = cleaned.find("{")
    first_list = cleaned.find("[")
    starts = [idx for idx in (first_obj, first_list) if idx != -1]
    if not starts:
        return cleaned

    for start in sorted(starts):
        idx = start
        while idx < len(cleaned):
            if cleaned[idx] not in "{[":
                idx += 1
                continue
            try:
                _, end = decoder.raw_decode(cleaned[idx:])
            except json.JSONDecodeError:
                idx += 1
                continue
            return cleaned[idx : idx + end]

    return cleaned[min(starts) :]
