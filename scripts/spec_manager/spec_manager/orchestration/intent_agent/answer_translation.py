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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spec_manager.orchestration.intent_agent.taxonomy import normalize_user_facing_taxonomy

logger = logging.getLogger(__name__)


_VALID_FOLLOWUP_ANSWER_SPEC_KINDS = frozenset({
    "choice",
    "yes_no",
    "value",
    "bounded_text",
})


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

    draft_id: str = ""
    taxonomy_type: str = "CONSTRAINT"
    canonical_key_hint: str = ""
    text: str = ""
    scenario: str = ""
    answer_spec: dict[str, Any] = field(default_factory=lambda: {"kind": "choice"})

    def __post_init__(self) -> None:
        if not self.draft_id:
            self.draft_id = f"fq_{uuid.uuid4().hex[:8]}"


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


@dataclass
class RecursionBudget:
    """Recursion budget for follow-up questions."""

    max_followups: int = 2
    used_followups: int = 0

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
    user_answer: UserAnswer = field(default_factory=UserAnswer)
    extracted: ExtractedContent = field(default_factory=ExtractedContent)
    recursion_budget: RecursionBudget = field(default_factory=RecursionBudget)
    provenance: TranslationProvenance = field(default_factory=TranslationProvenance)

    def __post_init__(self) -> None:
        if not self.translation_id:
            self.translation_id = f"at_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

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
                        "scope_in": s.scope_in,
                        "scope_out": s.scope_out,
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
        ua_raw = d.get("user_answer", {})
        user_answer = UserAnswer(
            raw_text=ua_raw.get("raw_text", ""),
            selected_choice_id=ua_raw.get("selected_choice_id", ""),
            parsed_values=ua_raw.get("parsed_values", {}),
        )

        ext_raw = d.get("extracted", {})
        extracted = ExtractedContent(
            constraint_candidates=[
                ConstraintCandidate(**c)
                for c in ext_raw.get("constraint_candidates", [])
            ],
            scope_candidates=[
                ScopeCandidate(
                    scope_in=s.get("scope_in", []),
                    scope_out=s.get("scope_out", []),
                )
                for s in ext_raw.get("scope_candidates", [])
            ],
            tradeoff_candidates=[
                TradeoffCandidate(**t)
                for t in ext_raw.get("tradeoff_candidates", [])
            ],
            validation_candidates=[
                ValidationCandidate(**v)
                for v in ext_raw.get("validation_candidates", [])
            ],
            followup_question_drafts=[
                FollowupQuestionDraft(
                    draft_id=fq.get("draft_id", ""),
                    taxonomy_type=normalize_user_facing_taxonomy(
                        fq.get("taxonomy_type", "CONSTRAINT"),
                    ),
                    canonical_key_hint=fq.get("canonical_key_hint", ""),
                    text=fq.get("text", ""),
                    scenario=fq.get("scenario", ""),
                    answer_spec=_normalize_followup_answer_spec(
                        fq.get("answer_spec"),
                    ),
                )
                for fq in ext_raw.get("followup_question_drafts", [])
            ],
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
            translation_id=d.get("translation_id", ""),
            run_id=d.get("run_id", ""),
            session_id=d.get("session_id", ""),
            question_id=d.get("question_id", ""),
            canonical_key_hint=d.get("canonical_key_hint", ""),
            answer_id=d.get("answer_id", ""),
            created_at=d.get("created_at", ""),
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

        from spec_manager.core.json_extraction import _extract_json_payload

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
            "2. scope_candidates — each with: scope_in (list[str]), scope_out (list[str])\n"
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
            prompt += (
                "5. followup_question_drafts — MUST be empty (recursion budget exhausted)\n"
            )

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

        try:
            raw = run_agent(prompt)
            payload = _extract_json_payload(raw)
            import json
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.debug("AnswerTranslateStrategy LLM parse failed (%s)", exc)
            return AnswerTranslation(
                question_id=question_id,
                user_answer=user_answer,
                extracted=ExtractedContent(),
                recursion_budget=recursion_budget,
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
                scope_in=s.get("scope_in", []),
                scope_out=s.get("scope_out", []),
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
        if not isinstance(raw_followups, list):
            raw_followups = []
        # Enforce global recursion budget — strip all follow-ups if exhausted
        if budget_exhausted:
            raw_followups = []
        else:
            raw_followups = raw_followups[:remaining_followups]

        followup_question_drafts = [
            FollowupQuestionDraft(
                taxonomy_type=normalize_user_facing_taxonomy(
                    fq.get("taxonomy_type", "CONSTRAINT"),
                ),
                canonical_key_hint=fq.get("canonical_key_hint", ""),
                text=fq.get("text", ""),
                scenario=fq.get("scenario", ""),
                answer_spec=_normalize_followup_answer_spec(fq.get("answer_spec")),
            )
            for fq in raw_followups
            if isinstance(fq, dict)
        ]

        extracted = ExtractedContent(
            constraint_candidates=constraint_candidates,
            scope_candidates=scope_candidates,
            tradeoff_candidates=tradeoff_candidates,
            validation_candidates=validation_candidates,
            followup_question_drafts=followup_question_drafts,
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


def _normalize_followup_answer_spec(raw_spec: Any) -> dict[str, Any]:
    if not isinstance(raw_spec, dict):
        return {"kind": "choice"}

    kind = str(raw_spec.get("kind", "choice")).strip().lower()
    if kind not in _VALID_FOLLOWUP_ANSWER_SPEC_KINDS:
        kind = "choice"

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
