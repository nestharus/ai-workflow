"""Pre-decomposition skeleton renderer — system/workflows/entities/interfaces.

Per response2.md Section 6: For intent-level intake, the Intent Agent must
NOT invent library boundaries. The skeleton represents a pre-decomposition
view of the system.

Skeleton structure:
    system/
      intent.md           — problem frame, scope, success metrics, open question IDs,
                            pointers to constraints by ID (no constraint objects)
      workflows/
        <workflow>.py     — domain workflows as function/class stubs
      entities/
        <entity>.py       — domain entities and value objects
      interfaces/
        <interface>.py    — external boundaries (providers, counterparties, etc.)
    analysis/intent/
      intent_snapshot.json — metadata snapshot (no constraint objects)
      question_queue.json  — queue snapshot

Depth rule (Section 6.2): "One level deeper than names"
    - Include workflows + key interfaces + entity shapes
    - Include TODOs tied to question IDs
    - Do NOT implement business logic

Section 5.7: Produce skeleton when:
    - Stable restatement of problem frame exists
    - Core workflows are identifiable
    - Major constraint dimensions have initial coverage or explicit open questions
"""

from __future__ import annotations

import json
import keyword
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _dedupe_non_empty_strings(values: list[str]) -> list[str]:
    """Deduplicate non-empty strings while preserving first-seen order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _safe_artifact_stem(raw_name: Any, *, fallback: str) -> str:
    """Return a safe filename stem for generated skeleton artifacts."""
    name = str(raw_name).strip()
    if not name:
        return fallback
    sanitized = name.replace("/", "_").replace("\\", "_").strip()
    return sanitized or fallback


def _to_python_identifier(raw_name: Any, *, fallback: str) -> str:
    """Normalize arbitrary text to a valid Python identifier."""
    name = str(raw_name).strip()
    if not name:
        name = fallback
    name = re.sub(r"\W+", "_", name).strip("_")
    if not name:
        name = fallback
    if name[0].isdigit():
        name = f"{fallback}_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


def _to_python_class_name(raw_name: Any, *, fallback: str) -> str:
    """Normalize arbitrary text to a valid Python class identifier."""
    name = str(raw_name).strip()
    if not name:
        name = fallback
    parts = re.split(r"[^0-9A-Za-z]+", name)
    normalized = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return _to_python_identifier(normalized, fallback=fallback)


def _normalize_type_hint(raw_type: Any, *, default: str) -> str:
    """Normalize an LLM-provided type hint into a safe Python type expression."""
    text = str(raw_type).strip()
    if not text:
        return default
    normalized = re.sub(r"[^0-9A-Za-z_., \[\]|]", "", text).strip()
    if not normalized:
        return default
    if normalized.lower() == "none":
        return "None"
    return normalized


def _normalize_signature_params(raw_params: Any, *, default: list[str]) -> list[str]:
    """Normalize function parameter shapes for skeleton stub signatures."""
    params: list[str] = []
    if isinstance(raw_params, list):
        for idx, raw in enumerate(raw_params):
            param_name = ""
            param_type = ""
            if isinstance(raw, dict):
                param_name = str(raw.get("name", "")).strip()
                param_type = str(raw.get("type", raw.get("annotation", ""))).strip()
            else:
                token = str(raw).strip()
                if not token:
                    continue
                if ":" in token:
                    left, right = token.split(":", 1)
                    param_name = left.strip()
                    param_type = right.strip()
                else:
                    param_name = token

            normalized_name = _to_python_identifier(param_name, fallback=f"arg_{idx + 1}")
            if param_type:
                normalized_type = _normalize_type_hint(param_type, default="Any")
                params.append(f"{normalized_name}: {normalized_type}")
            else:
                params.append(normalized_name)

    if not params:
        params = [_to_python_identifier(value, fallback="payload") for value in default]

    return _dedupe_non_empty_strings(params)


def _coerce_text_list(value: Any) -> list[str]:
    """Coerce a value into a non-empty list of strings."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for raw in value:
        text = str(raw).strip()
        if text:
            items.append(text)
    return items


def _normalize_frame_assumptions(raw_assumptions: Any) -> list[dict[str, str]]:
    """Normalize frame assumptions into deterministic, display-ready rows."""
    assumptions: list[dict[str, str]] = []
    if not isinstance(raw_assumptions, list):
        return assumptions
    for raw in raw_assumptions:
        if isinstance(raw, dict):
            text = str(raw.get("text", "")).strip()
            status = str(raw.get("status", "HYPOTHESIS")).strip() or "HYPOTHESIS"
            source = str(raw.get("source", "intent_agent")).strip() or "intent_agent"
        else:
            text = str(raw).strip()
            status = "HYPOTHESIS"
            source = "intent_agent"
        if not text:
            continue
        assumptions.append({"text": text, "status": status, "source": source})
    return assumptions


def _normalize_tradeoff_positions(raw_positions: Any) -> list[dict[str, str]]:
    """Normalize tradeoff position records for intent and snapshot rendering."""
    positions: list[dict[str, str]] = []
    if not isinstance(raw_positions, list):
        return positions
    for raw in raw_positions:
        if isinstance(raw, dict):
            axis = str(raw.get("axis", raw.get("dimension", ""))).strip()
            preference = str(raw.get("preference", raw.get("position", ""))).strip()
            rationale = str(raw.get("rationale", raw.get("reason", ""))).strip()
            source_question_id = str(
                raw.get("source_question_id", raw.get("question_id", ""))
            ).strip()
        else:
            axis = ""
            preference = str(raw).strip()
            rationale = ""
            source_question_id = ""
        if not axis and not preference and not rationale:
            continue
        positions.append(
            {
                "axis": axis,
                "preference": preference,
                "rationale": rationale,
                "source_question_id": source_question_id,
            }
        )
    return positions


def _project_problem_frame(problem_frame: dict[str, Any]) -> dict[str, Any]:
    """Project problem frame into a constrained snapshot-safe shape."""
    scope_raw = problem_frame.get("scope", {})
    if isinstance(scope_raw, dict):
        scope_in = _coerce_text_list(scope_raw.get("in", []))
        scope_out = _coerce_text_list(scope_raw.get("out", []))
    else:
        scope_in = _coerce_text_list(problem_frame.get("scope_in", []))
        scope_out = _coerce_text_list(problem_frame.get("scope_out", []))
    return {
        "current_restatement": str(problem_frame.get("current_restatement", "")).strip(),
        "goals": _coerce_text_list(problem_frame.get("goals", [])),
        "non_goals": _coerce_text_list(problem_frame.get("non_goals", [])),
        "scope": {"in": scope_in, "out": scope_out},
        "success_metrics": _coerce_text_list(problem_frame.get("success_metrics", [])),
        "risk_flags": _coerce_text_list(problem_frame.get("risk_flags", [])),
        "frame_assumptions": _normalize_frame_assumptions(
            problem_frame.get("frame_assumptions", [])
        ),
    }


def _project_concept_map(concept_map: dict[str, Any]) -> dict[str, Any]:
    """Project concept map into explicit fields to avoid leaking unknown objects."""
    raw_user_terms = concept_map.get("user_terms", {})
    projected_terms: dict[str, dict[str, Any]] = {}
    if isinstance(raw_user_terms, dict):
        for key, value in raw_user_terms.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            maps_to: list[str] = []
            confidence: float = 0.0
            if isinstance(value, dict):
                maps_to = _coerce_text_list(value.get("maps_to", []))
                raw_confidence = value.get("confidence", 0.0)
                if isinstance(raw_confidence, (int, float)):
                    confidence = float(raw_confidence)
            projected_terms[key_text] = {"maps_to": maps_to, "confidence": confidence}
    raw_normalized_terms = concept_map.get("normalized_terms", {})
    normalized_terms: dict[str, list[str]] = {}
    if isinstance(raw_normalized_terms, dict):
        for key, value in raw_normalized_terms.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            normalized_terms[key_text] = _coerce_text_list(value)
    return {
        "user_terms": projected_terms,
        "normalized_terms": normalized_terms,
        "user_introduced_terms": _coerce_text_list(concept_map.get("user_introduced_terms", [])),
    }


def _project_open_questions_for_summary(
    raw_questions: Any,
    *,
    fallback: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Normalize open-question summaries with ID + short text + metadata."""
    (
        question_ids,
        question_texts,
        canonical_keys,
        scenarios,
        omissions,
    ) = _normalize_question_refs(raw_questions, fallback=fallback)
    records = [
        {
            "question_id": qid,
            "question_text": question_text,
            "canonical_key": canonical_key,
            "scenario": scenario,
        }
        for qid, question_text, canonical_key, scenario in zip(
            question_ids, question_texts, canonical_keys, scenarios, strict=True
        )
    ]
    return records, omissions


def _docstring_literal(text: str) -> str:
    """Escape triple-quotes for safe one-line docstrings."""
    return text.replace('"""', '"').strip()


def _extract_json_payload_from_llm_output(output: str) -> str:
    """Extract first decodable JSON object/array from an LLM output string."""
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
            ch = cleaned[idx]
            if ch not in "{[":
                idx += 1
                continue
            try:
                _, end = decoder.raw_decode(cleaned[idx:])
            except json.JSONDecodeError:
                idx += 1
                continue
            return cleaned[idx : idx + end]

    return cleaned[min(starts) :]


def _normalize_question_refs(
    raw_questions: Any,
    *,
    fallback: list[dict[str, str]] | None = None,
) -> tuple[list[str], list[str], list[str], list[str], list[dict[str, Any]]]:
    """Normalize question refs and record every omission or deduplication."""
    normalized: list[tuple[str, str, str, str]] = []
    omissions: list[dict[str, Any]] = []

    def _coerce_original_value(value: Any) -> Any:
        try:
            json.dumps(value)
        except TypeError:
            return repr(value)
        return value

    if isinstance(raw_questions, list):
        for idx, raw in enumerate(raw_questions):
            if isinstance(raw, str):
                qid = raw.strip()
                if qid:
                    normalized.append((qid, "", "", ""))
                else:
                    omissions.append(
                        {
                            "reason": "empty_after_strip",
                            "source": "raw_questions",
                            "index": idx,
                            "original_value": raw,
                        }
                    )
                continue

            if isinstance(raw, dict):
                qid = str(raw.get("question_id", raw.get("id", ""))).strip()
                if not qid:
                    omissions.append(
                        {
                            "reason": "missing_question_id",
                            "source": "raw_questions",
                            "index": idx,
                            "original_value": _coerce_original_value(raw),
                        }
                    )
                    continue
                canonical_key = str(raw.get("canonical_key", "")).strip()
                scenario = str(raw.get("scenario", "")).strip()
                question_text = str(raw.get("question_text", raw.get("text", ""))).strip()
                normalized.append((qid, question_text, canonical_key, scenario))
                continue

            omissions.append(
                {
                    "reason": "unrecognized_type",
                    "source": "raw_questions",
                    "index": idx,
                    "original_value": _coerce_original_value(raw),
                }
            )
    elif raw_questions is not None:
        omissions.append(
            {
                "reason": "raw_questions_not_list",
                "source": "raw_questions",
                "index": None,
                "original_value": _coerce_original_value(raw_questions),
            }
        )

    if not normalized and fallback:
        for idx, raw in enumerate(fallback):
            qid = str(raw.get("question_id", raw.get("id", ""))).strip()
            if not qid:
                omissions.append(
                    {
                        "reason": "missing_question_id",
                        "source": "fallback",
                        "index": idx,
                        "original_value": _coerce_original_value(raw),
                    }
                )
                continue
            canonical_key = str(raw.get("canonical_key", "")).strip()
            scenario = str(raw.get("scenario", "")).strip()
            question_text = str(raw.get("question_text", raw.get("text", ""))).strip()
            normalized.append((qid, question_text, canonical_key, scenario))

    deduped: list[tuple[str, str, str, str]] = []
    seen_ids: set[str] = set()
    for idx, (qid, question_text, canonical_key, scenario) in enumerate(normalized):
        if qid in seen_ids:
            omissions.append(
                {
                    "reason": "duplicate_question_id",
                    "source": "normalized",
                    "index": idx,
                    "question_id": qid,
                    "original_value": {
                        "question_id": qid,
                        "question_text": question_text,
                        "canonical_key": canonical_key,
                        "scenario": scenario,
                    },
                }
            )
            continue
        seen_ids.add(qid)
        deduped.append((qid, question_text, canonical_key, scenario))

    question_ids, question_texts, canonical_keys, scenarios = (
        zip(*deduped, strict=True) if deduped else ((), (), (), ())
    )
    return (
        list(question_ids),
        list(question_texts),
        list(canonical_keys),
        list(scenarios),
        omissions,
    )


def _question_todo_lines(
    subject: str,
    question_ids: list[str],
    canonical_keys: list[str],
    scenarios: list[str],
) -> list[str]:
    """Build canonical_key/scenario tied TODO comments for one stub."""
    lines: list[str] = []
    for idx, qid in enumerate(question_ids):
        if not qid:
            continue
        canonical_key = canonical_keys[idx] if idx < len(canonical_keys) else ""
        scenario = scenarios[idx] if idx < len(scenarios) else ""
        key_suffix = f" (canonical_key: {canonical_key})" if canonical_key else ""
        lines.append(f"# Q:{qid}{key_suffix}")
        if scenario:
            lines.append(f"# Scenario: {scenario}")
        lines.append(f"# TODO: finalize {subject} based on user answer to Q:{qid}.")
    return lines


@dataclass
class WorkflowStub:
    """A domain workflow stub for the skeleton."""

    name: str = ""
    description: str = ""
    parameters: list[str] = field(default_factory=list)
    return_type: str = "Any"
    open_question_ids: list[str] = field(default_factory=list)
    canonical_keys: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)


@dataclass
class EntityStub:
    """A domain entity stub for the skeleton."""

    name: str = ""
    description: str = ""
    fields: list[str] = field(default_factory=list)
    open_question_ids: list[str] = field(default_factory=list)
    canonical_keys: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)


@dataclass
class InterfaceStub:
    """An external boundary stub for the skeleton."""

    @dataclass
    class OperationStub:
        """An operation contract exposed by the external interface."""

        name: str = ""
        description: str = ""
        parameters: list[str] = field(default_factory=list)
        return_type: str = "Any"
        open_question_ids: list[str] = field(default_factory=list)
        canonical_keys: list[str] = field(default_factory=list)
        scenarios: list[str] = field(default_factory=list)

    name: str = ""
    description: str = ""
    direction: str = "inbound"  # inbound | outbound | bidirectional
    operations: list[OperationStub] = field(default_factory=list)
    open_question_ids: list[str] = field(default_factory=list)
    canonical_keys: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)


@dataclass
class SkeletonSpec:
    """Full specification for generating a pre-decomposition skeleton."""

    problem_frame: dict[str, Any] = field(default_factory=dict)
    concept_map: dict[str, Any] = field(default_factory=dict)
    workflows: list[WorkflowStub] = field(default_factory=list)
    entities: list[EntityStub] = field(default_factory=list)
    interfaces: list[InterfaceStub] = field(default_factory=list)
    open_questions: list[dict[str, str]] = field(default_factory=list)
    open_question_ids: list[str] = field(default_factory=list)
    constraint_refs: list[str] = field(default_factory=list)  # planner constraint IDs
    decision_refs: list[str] = field(default_factory=list)  # planner decision IDs
    tradeoff_positions: list[dict[str, str]] = field(default_factory=list)
    question_ref_omissions: list[dict[str, Any]] = field(default_factory=list)


class SkeletonSynthesisTransientParseError(RuntimeError):
    """Retryable LLM parse failure after bounded attempts."""

    def __init__(self, attempts: int, max_attempts: int) -> None:
        self.attempts = attempts
        self.max_attempts = max_attempts
        super().__init__(
            f"Failed to parse skeleton LLM response after {attempts}/{max_attempts} attempts"
        )


# ---------------------------------------------------------------------------
# SkeletonSynthesisStrategy
# ---------------------------------------------------------------------------


# TODO [R2-6.1/6.2]: Implement SkeletonSynthesisStrategy
#   - LLM strategy that produces pre-decomposition skeleton artifacts
#   - Input: problem_frame, concept_map, answered/open questions,
#     constraint references (IDs only, not objects)
#   - Output: SkeletonSpec with workflows, entities, interfaces
#   - Depth: "one level deeper than names" — stubs with TODOs tied
#     to question IDs, no business logic
#   - Must NOT invent library boundaries (that's Phase 0's job)
#   - Skeleton creation is incremental: revised as constraints arrive
class SkeletonSynthesisStrategy:
    """LLM strategy to produce pre-decomposition skeleton spec.

    Per response2.md Section 6: Produces system/workflows/entities/interfaces
    structure. Does NOT decompose into libraries.
    """

    MAX_PARSE_ATTEMPTS: int = 3

    def synthesize(
        self,
        problem_frame: dict[str, Any],
        concept_map: dict[str, Any],
        open_question_ids: list[str],
        open_questions: list[dict[str, str]] | None = None,
        constraint_refs: list[str] | None = None,
        decision_refs: list[str] | None = None,
        *,
        run_agent: Any = None,
    ) -> SkeletonSpec:
        """Produce a pre-decomposition skeleton specification."""
        constraint_refs = _dedupe_non_empty_strings(list(constraint_refs or []))
        decision_refs = _dedupe_non_empty_strings(list(decision_refs or []))
        open_question_records = list(
            open_questions or [{"question_id": qid} for qid in open_question_ids]
        )
        fallback_question_records = [{"question_id": qid} for qid in open_question_ids]
        normalized_open_questions, input_question_omissions = _project_open_questions_for_summary(
            open_question_records,
            fallback=fallback_question_records,
        )
        normalized_open_question_ids = [
            record["question_id"] for record in normalized_open_questions
        ]
        tradeoff_positions = _normalize_tradeoff_positions(
            problem_frame.get("tradeoff_positions", [])
        )

        if run_agent is None:
            return SkeletonSpec(
                problem_frame=problem_frame,
                concept_map=concept_map,
                open_questions=normalized_open_questions,
                open_question_ids=normalized_open_question_ids,
                constraint_refs=constraint_refs,
                decision_refs=decision_refs,
                tradeoff_positions=tradeoff_positions,
                question_ref_omissions=input_question_omissions,
            )

        scope_raw = problem_frame.get("scope", {})
        if isinstance(scope_raw, dict):
            scope_text = json.dumps(scope_raw, indent=2)
        else:
            scope_text = json.dumps(str(scope_raw))

        def _extract_question_metadata(
            item: dict[str, Any],
            fallback: list[dict[str, str]],
        ) -> tuple[list[str], list[str], list[str], list[str], list[dict[str, Any]]]:
            if not isinstance(item, dict):
                return _normalize_question_refs([], fallback=fallback)
            if "open_questions" in item:
                return _normalize_question_refs(item.get("open_questions", []), fallback=fallback)
            if "open_question_ids" in item:
                return _normalize_question_refs(
                    item.get("open_question_ids", []), fallback=fallback
                )
            return _normalize_question_refs([], fallback=fallback)

        prompt = (
            "You are a systems analyst. Given the following problem frame, "
            "produce a pre-decomposition skeleton specification.\n\n"
            "## Problem Frame\n"
            f"Restatement: {problem_frame.get('current_restatement', '')}\n"
            f"Goals: {json.dumps(problem_frame.get('goals', []))}\n"
            f"Non-goals: {json.dumps(problem_frame.get('non_goals', []))}\n"
            f"Scope: {scope_text}\n"
            "Frame assumptions: "
            f"{json.dumps(problem_frame.get('frame_assumptions', []), indent=2)}\n"
            f"Tradeoff positions: {json.dumps(tradeoff_positions, indent=2)}\n\n"
            "## Open Question Metadata\n"
            f"{json.dumps(normalized_open_questions, indent=2)}\n\n"
            f"## Constraint refs (IDs only)\n"
            f"{json.dumps(constraint_refs)}\n"
            "## Decision refs (IDs only)\n"
            f"{json.dumps(decision_refs)}\n\n"
            "Produce a JSON object with exactly three keys:\n"
            '- "workflows": list of {{"name": str, "description": str, '
            '"parameters": list[str], "returns": str, '
            '"open_questions": [{"question_id": str, "canonical_key": str, '
            '"scenario": str, "question_text": str}]}\n'
            '- "entities": list of {{"name": str, "description": str, '
            '"fields": list of str, "open_questions": [{"question_id": str, '
            '"canonical_key": str, "scenario": str, "question_text": str}]}}\n'
            '- "interfaces": list of {{"name": str, "description": str, '
            '"direction": "inbound"|"outbound"|"bidirectional", '
            '"operations": list[{"name": str, "description": str, '
            '"parameters": list[str], "returns": str, '
            '"open_questions": [{"question_id": str, "canonical_key": str, '
            '"scenario": str, "question_text": str}]}], '
            '"open_questions": [{"question_id": str, "canonical_key": str, '
            '"scenario": str, "question_text": str}]}}\n'
            "Do NOT invent library boundaries. Keep stubs shallow — "
            "one level deeper than names. Output ONLY the JSON object."
        )

        data: Any = None
        for attempt in range(1, self.MAX_PARSE_ATTEMPTS + 1):
            raw = run_agent(prompt)
            try:
                extracted = _extract_json_payload_from_llm_output(raw)
                data = json.loads(extracted)
                break
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Failed to parse skeleton LLM response on attempt %d/%d",
                    attempt,
                    self.MAX_PARSE_ATTEMPTS,
                )
                if attempt >= self.MAX_PARSE_ATTEMPTS:
                    raise SkeletonSynthesisTransientParseError(
                        attempts=attempt,
                        max_attempts=self.MAX_PARSE_ATTEMPTS,
                    ) from exc
        if not isinstance(data, dict):
            logger.warning(
                "Skeleton LLM response root is %s, expected object; returning empty spec",
                type(data).__name__,
            )
            return SkeletonSpec(
                problem_frame=problem_frame,
                concept_map=concept_map,
                open_questions=normalized_open_questions,
                open_question_ids=normalized_open_question_ids,
                constraint_refs=constraint_refs,
                decision_refs=decision_refs,
                tradeoff_positions=tradeoff_positions,
                question_ref_omissions=input_question_omissions,
            )

        expected_sections = ("workflows", "entities", "interfaces")
        missing_sections = [section for section in expected_sections if section not in data]
        unexpected_sections = [key for key in data if key not in expected_sections]
        if missing_sections:
            logger.warning(
                "Skeleton LLM response missing sections %s; "
                "defaulting missing sections to empty lists",
                missing_sections,
            )
        if unexpected_sections:
            logger.warning(
                "Skeleton LLM response includes unexpected sections %s; ignoring extras",
                unexpected_sections,
            )

        def _coerce_section(section_name: str) -> list[dict[str, Any]]:
            raw_section = data.get(section_name, [])
            if raw_section is None:
                return []
            if not isinstance(raw_section, list):
                logger.warning(
                    "Skeleton LLM response section %r is %s, expected list; using empty list",
                    section_name,
                    type(raw_section).__name__,
                )
                return []

            normalized_items: list[dict[str, Any]] = []
            for idx, raw_item in enumerate(raw_section):
                if not isinstance(raw_item, dict):
                    logger.warning(
                        "Skeleton LLM response item %s[%d] is %s, expected object; dropping item",
                        section_name,
                        idx,
                        type(raw_item).__name__,
                    )
                    continue
                normalized_items.append(raw_item)
            return normalized_items

        workflow_items = _coerce_section("workflows")
        entity_items = _coerce_section("entities")
        interface_items = _coerce_section("interfaces")

        fallback_records = (
            normalized_open_questions
            if normalized_open_questions
            else [{"question_id": qid} for qid in open_question_ids]
        )

        workflows = []
        question_ref_omissions: list[dict[str, Any]] = list(input_question_omissions)

        for idx, w in enumerate(workflow_items):
            q_ids, _, canonical_keys, scenarios, omissions = _extract_question_metadata(
                w, fallback_records
            )
            question_ref_omissions.extend(
                {
                    "section": "workflows",
                    "item_index": idx,
                    "item_name": str(w.get("name", "")).strip(),
                    **omission,
                }
                for omission in omissions
            )
            workflows.append(
                WorkflowStub(
                    name=_to_python_identifier(w.get("name", ""), fallback=f"workflow_{idx + 1}"),
                    description=str(w.get("description", "")).strip(),
                    parameters=_normalize_signature_params(
                        w.get("parameters", w.get("inputs", [])),
                        default=["input_payload"],
                    ),
                    return_type=_normalize_type_hint(
                        w.get("returns", w.get("return_type", "Any")),
                        default="Any",
                    ),
                    open_question_ids=q_ids,
                    canonical_keys=canonical_keys,
                    scenarios=scenarios,
                )
            )

        entities = []
        for idx, e in enumerate(entity_items):
            q_ids, _, canonical_keys, scenarios, omissions = _extract_question_metadata(
                e, fallback_records
            )
            question_ref_omissions.extend(
                {
                    "section": "entities",
                    "item_index": idx,
                    "item_name": str(e.get("name", "")).strip(),
                    **omission,
                }
                for omission in omissions
            )
            entities.append(
                EntityStub(
                    name=_to_python_class_name(e.get("name", ""), fallback=f"Entity{idx + 1}"),
                    description=str(e.get("description", "")).strip(),
                    fields=_coerce_text_list(e.get("fields", [])),
                    open_question_ids=q_ids,
                    canonical_keys=canonical_keys,
                    scenarios=scenarios,
                )
            )

        interfaces = []
        for idx, i in enumerate(interface_items):
            q_ids, _, canonical_keys, scenarios, omissions = _extract_question_metadata(
                i, fallback_records
            )
            question_ref_omissions.extend(
                {
                    "section": "interfaces",
                    "item_index": idx,
                    "item_name": str(i.get("name", "")).strip(),
                    **omission,
                }
                for omission in omissions
            )

            interface_fallback = [
                {
                    "question_id": qid,
                    "canonical_key": canonical_key,
                    "scenario": scenario,
                }
                for qid, canonical_key, scenario in zip(
                    q_ids, canonical_keys, scenarios, strict=True
                )
            ]
            raw_operations = i.get("operations", i.get("methods", []))
            if not isinstance(raw_operations, list):
                raw_operations = []
            operations: list[InterfaceStub.OperationStub] = []
            for op_idx, raw_operation in enumerate(raw_operations):
                if not isinstance(raw_operation, dict):
                    question_ref_omissions.append(
                        {
                            "section": "interfaces",
                            "item_index": idx,
                            "item_name": str(i.get("name", "")).strip(),
                            "reason": "operation_not_object",
                            "source": "operations",
                            "index": op_idx,
                            "original_value": repr(raw_operation),
                        }
                    )
                    continue
                op_q_ids, _, op_keys, op_scenarios, op_omissions = _extract_question_metadata(
                    raw_operation,
                    interface_fallback,
                )
                question_ref_omissions.extend(
                    {
                        "section": "interfaces.operations",
                        "item_index": idx,
                        "item_name": str(i.get("name", "")).strip(),
                        "operation_index": op_idx,
                        "operation_name": str(raw_operation.get("name", "")).strip(),
                        **omission,
                    }
                    for omission in op_omissions
                )
                operations.append(
                    InterfaceStub.OperationStub(
                        name=_to_python_identifier(
                            raw_operation.get("name", ""),
                            fallback=f"operation_{op_idx + 1}",
                        ),
                        description=str(raw_operation.get("description", "")).strip(),
                        parameters=_normalize_signature_params(
                            raw_operation.get("parameters", raw_operation.get("inputs", [])),
                            default=["payload"],
                        ),
                        return_type=_normalize_type_hint(
                            raw_operation.get("returns", raw_operation.get("return_type", "Any")),
                            default="Any",
                        ),
                        open_question_ids=op_q_ids,
                        canonical_keys=op_keys,
                        scenarios=op_scenarios,
                    )
                )

            direction = str(i.get("direction", "inbound")).strip().lower()
            if direction not in {"inbound", "outbound", "bidirectional"}:
                direction = "inbound"
            interfaces.append(
                InterfaceStub(
                    name=_to_python_class_name(i.get("name", ""), fallback=f"Interface{idx + 1}"),
                    description=str(i.get("description", "")).strip(),
                    direction=direction,
                    operations=operations,
                    open_question_ids=q_ids,
                    canonical_keys=canonical_keys,
                    scenarios=scenarios,
                )
            )

        return SkeletonSpec(
            problem_frame=problem_frame,
            concept_map=concept_map,
            workflows=workflows,
            entities=entities,
            interfaces=interfaces,
            open_questions=normalized_open_questions,
            open_question_ids=normalized_open_question_ids,
            constraint_refs=constraint_refs,
            decision_refs=decision_refs,
            tradeoff_positions=tradeoff_positions,
            question_ref_omissions=question_ref_omissions,
        )


# ---------------------------------------------------------------------------
# Skeleton renderer
# ---------------------------------------------------------------------------


# TODO [R2-6.1]: Implement render_skeleton(spec, output_dir)
#   - Takes a SkeletonSpec and renders the directory structure:
#     system/intent.md — problem frame, scope, metrics, open Qs, constraint refs
#     system/workflows/<name>.py — function/class stubs with TODO comments
#     system/entities/<name>.py — entity stubs with field shapes
#     system/interfaces/<name>.py — external boundary stubs
#   - Workflow stubs must include TODO comments referencing question IDs:
#     # Q:<question_id> (canonical_key: <key>)
#     # Scenario: <scenario text>
#     # TODO: finalize <aspect> based on user answer.
#   - Must NOT embed constraint objects — only reference by ID
def render_skeleton(spec: SkeletonSpec, output_dir: Path) -> list[Path]:
    """Render skeleton artifacts to the output directory.

    Returns list of created file paths.
    """
    created: list[Path] = []

    # --- system/intent.md ---
    system_dir = output_dir / "system"
    system_dir.mkdir(parents=True, exist_ok=True)

    projected_problem_frame = _project_problem_frame(spec.problem_frame)
    scope_in = projected_problem_frame["scope"]["in"]
    scope_out = projected_problem_frame["scope"]["out"]
    assumptions = projected_problem_frame["frame_assumptions"]
    tradeoff_positions = _normalize_tradeoff_positions(
        spec.tradeoff_positions or spec.problem_frame.get("tradeoff_positions", [])
    )
    open_question_fallback = [{"question_id": qid} for qid in spec.open_question_ids]
    open_question_records, open_question_omissions = _project_open_questions_for_summary(
        spec.open_questions,
        fallback=open_question_fallback,
    )
    constraint_refs = _dedupe_non_empty_strings(spec.constraint_refs)
    decision_refs = _dedupe_non_empty_strings(spec.decision_refs)

    intent_lines = [
        "# Intent",
        "",
        "## Problem Frame",
        f"Restatement: {projected_problem_frame.get('current_restatement', '')}",
        f"Goals: {json.dumps(projected_problem_frame.get('goals', []))}",
        f"Non-goals: {json.dumps(projected_problem_frame.get('non_goals', []))}",
        f"Scope In: {json.dumps(scope_in)}",
        f"Scope Out: {json.dumps(scope_out)}",
        "",
        "## Success Metrics",
        json.dumps(projected_problem_frame.get("success_metrics", []), indent=2),
        "",
        "## Confirmed Constraints (refs by ID)",
    ]
    if constraint_refs:
        for constraint_id in constraint_refs:
            intent_lines.append(f"- {constraint_id}")
    else:
        intent_lines.append("- None yet")

    intent_lines.append("")
    intent_lines.append("## Assumptions (clearly marked)")
    if assumptions:
        for assumption in assumptions:
            intent_lines.append(
                f"- [{assumption['status']}] {assumption['text']} (source: {assumption['source']})"
            )
    else:
        intent_lines.append("- None recorded")

    intent_lines.append("")
    intent_lines.append("## Tradeoff Positions")
    if tradeoff_positions:
        for position in tradeoff_positions:
            axis = position.get("axis", "")
            preference = position.get("preference", "")
            rationale = position.get("rationale", "")
            source_question_id = position.get("source_question_id", "")
            label_parts = [part for part in [axis, preference] if part]
            detail_parts = []
            if rationale:
                detail_parts.append(f"rationale: {rationale}")
            if source_question_id:
                detail_parts.append(f"from {source_question_id}")
            title = " -> ".join(label_parts) if label_parts else "position"
            suffix = f" ({'; '.join(detail_parts)})" if detail_parts else ""
            intent_lines.append(f"- {title}{suffix}")
    else:
        intent_lines.append("- None recorded")

    intent_lines.append("")
    intent_lines.append("## Open Questions")
    if open_question_records:
        for question in open_question_records:
            question_text = (
                question.get("question_text") or question.get("scenario") or "text pending"
            )
            canonical_key = question.get("canonical_key", "")
            canonical_suffix = f" (canonical_key: {canonical_key})" if canonical_key else ""
            intent_lines.append(f"- {question['question_id']}: {question_text}{canonical_suffix}")
    else:
        intent_lines.append("- None")

    intent_lines.append("")
    intent_lines.append("## Decision Refs (by ID)")
    if decision_refs:
        for decision_id in decision_refs:
            intent_lines.append(f"- {decision_id}")
    else:
        intent_lines.append("- None yet")

    if open_question_omissions:
        intent_lines.append("")
        intent_lines.append("## Open Question Metadata Omissions")
        intent_lines.append("```json")
        intent_lines.append(json.dumps(open_question_omissions, indent=2))
        intent_lines.append("```")

    intent_path = system_dir / "intent.md"
    intent_path.write_text("\n".join(intent_lines), encoding="utf-8")
    created.append(intent_path)

    # --- system/workflows/<name>.py ---
    wf_dir = system_dir / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    for idx, w in enumerate(spec.workflows):
        workflow_name = _to_python_identifier(w.name, fallback=f"workflow_{idx + 1}")
        workflow_parameters = _normalize_signature_params(w.parameters, default=["input_payload"])
        workflow_return = _normalize_type_hint(w.return_type, default="Any")
        lines = [f'"""{_docstring_literal(w.description)}"""', ""]
        lines.extend(
            _question_todo_lines(
                workflow_name,
                list(w.open_question_ids),
                list(w.canonical_keys),
                list(w.scenarios),
            )
        )
        lines.append("")
        lines.append(f"def {workflow_name}({', '.join(workflow_parameters)}) -> {workflow_return}:")
        if w.description.strip():
            lines.append(f'    """{_docstring_literal(w.description)}"""')
        lines.append("    raise NotImplementedError")
        lines.append("")
        wf_path = wf_dir / f"{_safe_artifact_stem(w.name, fallback=workflow_name)}.py"
        wf_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(wf_path)

    # --- system/entities/<name>.py ---
    ent_dir = system_dir / "entities"
    ent_dir.mkdir(parents=True, exist_ok=True)
    for e in spec.entities:
        lines = [f'"""{e.description}"""', ""]
        lines.extend(
            _question_todo_lines(
                f"entity {e.name}",
                list(e.open_question_ids),
                list(e.canonical_keys),
                list(e.scenarios),
            )
        )
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"class {e.name}:")
        if e.fields:
            for field_name in e.fields:
                lines.append(f"    {field_name} = None")
        else:
            lines.append("    pass")
        lines.append("")
        ent_path = ent_dir / f"{e.name}.py"
        ent_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(ent_path)

    # --- system/interfaces/<name>.py ---
    iface_dir = system_dir / "interfaces"
    iface_dir.mkdir(parents=True, exist_ok=True)
    for idx, i in enumerate(spec.interfaces):
        interface_name = _to_python_class_name(i.name, fallback=f"Interface{idx + 1}")
        lines = [f'"""{_docstring_literal(i.description)}"""', ""]
        lines.extend(
            _question_todo_lines(
                f"interface {interface_name}",
                list(i.open_question_ids),
                list(i.canonical_keys),
                list(i.scenarios),
            )
        )
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"# direction: {i.direction}")
        lines.append("")
        lines.append(f"class {interface_name}:")
        if i.description.strip():
            lines.append(f'    """{_docstring_literal(i.description)}"""')
        rendered_operation = False
        for op_idx, operation in enumerate(i.operations):
            op_name = _to_python_identifier(operation.name, fallback=f"operation_{op_idx + 1}")
            op_params = _normalize_signature_params(operation.parameters, default=["payload"])
            op_params = [
                param
                for param in op_params
                if param.split(":", 1)[0].split("=", 1)[0].strip() != "self"
            ]
            op_return = _normalize_type_hint(operation.return_type, default="Any")
            op_question_ids = operation.open_question_ids or i.open_question_ids
            op_canonical_keys = operation.canonical_keys or i.canonical_keys
            op_scenarios = operation.scenarios or i.scenarios

            if rendered_operation:
                lines.append("")
            for comment_line in _question_todo_lines(
                f"interface operation {op_name}",
                list(op_question_ids),
                list(op_canonical_keys),
                list(op_scenarios),
            ):
                lines.append(f"    {comment_line}")
            method_signature_params = ", ".join(["self", *op_params]) if op_params else "self"
            lines.append(f"    def {op_name}({method_signature_params}) -> {op_return}:")
            if operation.description.strip():
                lines.append(f'        """{_docstring_literal(operation.description)}"""')
            lines.append("        raise NotImplementedError")
            rendered_operation = True
        if not rendered_operation:
            lines.append("    def execute(self, payload: Any) -> Any:")
            lines.append("        raise NotImplementedError")
        lines.append("")
        iface_path = iface_dir / f"{_safe_artifact_stem(i.name, fallback=interface_name)}.py"
        iface_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(iface_path)

    return created


# TODO [R2-6.3]: Implement render_intent_snapshot(state, queue, output_dir)
#   - Renders analysis/intent/intent_snapshot.json containing:
#     problem_frame, concept_map, queue open question IDs + canonical keys,
#     references to planner-authored constraints/decisions by ID
#   - Must NOT embed constraint objects
def render_intent_snapshot(
    problem_frame: dict[str, Any],
    concept_map: dict[str, Any],
    open_questions: list[dict[str, str]],
    constraint_refs: list[str],
    output_dir: Path,
    *,
    decision_refs: list[str] | None = None,
    tradeoff_positions: list[dict[str, Any]] | None = None,
) -> Path:
    """Render the intent metadata snapshot."""
    snapshot_dir = output_dir / "analysis" / "intent"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    (
        question_ids,
        question_texts,
        canonical_keys,
        scenarios,
        question_ref_omissions,
    ) = _normalize_question_refs(
        open_questions,
        fallback=[],
    )
    projected_problem_frame = _project_problem_frame(problem_frame)
    projected_concept_map = _project_concept_map(concept_map)
    projected_tradeoff_positions = _normalize_tradeoff_positions(
        tradeoff_positions
        if tradeoff_positions is not None
        else problem_frame.get("tradeoff_positions", [])
    )
    snapshot = {
        "problem_frame": projected_problem_frame,
        "concept_map": projected_concept_map,
        "open_questions": [
            {
                "question_id": qid,
                "question_text": question_text,
                "canonical_key": canonical_key,
                "scenario": scenario,
            }
            for qid, question_text, canonical_key, scenario in zip(
                question_ids, question_texts, canonical_keys, scenarios, strict=True
            )
        ],
        "tradeoff_positions": projected_tradeoff_positions,
        "open_question_ref_omissions": question_ref_omissions,
        "constraint_refs": _dedupe_non_empty_strings(constraint_refs),
        "decision_refs": _dedupe_non_empty_strings(list(decision_refs or [])),
    }

    path = snapshot_dir / "intent_snapshot.json"
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return path


def should_produce_skeleton(
    problem_frame: dict[str, Any],
    queue_state: dict[str, Any],
) -> bool:
    """Check if there is enough information to produce a skeleton.

    Returns True when all of these hold:
      1. Stable restatement of problem frame exists (even if tentative).
      2. Core workflows are identifiable (at least one goal defined).
      3. Major constraint dimensions have either at least one answered
         constraint (closed question) OR an explicit queued question
         (not silent assumptions).
    """
    # 1. Stable restatement exists
    has_restatement = bool(problem_frame.get("current_restatement", ""))

    # 2. Core workflows identifiable — goals serve as proxy
    goals = problem_frame.get("goals", [])
    has_goals = len(goals) >= 1

    # 3. Constraint dimension coverage (or explicit open constraint questions).
    open_constraint_ids = set(queue_state.get("open_constraint_question_ids", []) or [])
    closed_constraint_ids = set(queue_state.get("closed_constraint_question_ids", []) or [])
    open_constraint_dimensions = set(queue_state.get("open_constraint_dimensions", []) or [])
    closed_constraint_dimensions = set(queue_state.get("closed_constraint_dimensions", []) or [])
    has_constraint_coverage_keys = (
        "open_constraint_question_ids" in queue_state
        or "closed_constraint_question_ids" in queue_state
        or "open_constraint_dimensions" in queue_state
        or "closed_constraint_dimensions" in queue_state
    )

    has_constraint_coverage = False
    if has_constraint_coverage_keys:
        has_constraint_coverage = (
            bool(open_constraint_ids)
            or bool(closed_constraint_ids)
            or bool(open_constraint_dimensions)
            or bool(closed_constraint_dimensions)
        )

    return has_restatement and has_goals and has_constraint_coverage
