"""Question queue — item lifecycle, dedup, priority, batching, reassessment.

Per response2.md Section 2: Queue items represent underlying unknowns in
user-facing taxonomy types. A question only enters the user queue if it
is classified as a valid user-facing type AND passes the mandatory quality
gate.

Key behaviors:
    - Priority scoring: deterministic base + optional LLM tie-break (top 5)
    - Reassessment: triggered by Planner update signals, not by Intent Agent
      writing constraints. Mechanical pass first, LLM for ambiguous.
    - Dedup: canonical_key → decision_requirement_id → semantic LLM
    - Batching: one question at a time default, batch ≤ 3 only when
      same domain concern + answering together reduces ambiguity
    - Staleness: no blockers → STALE
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


def _question_queue_snapshot_dir(run_dir: Path) -> Path:
    """Return canonical path for `question_queue.json`."""
    return run_dir / "intent" / "skeleton" / "analysis" / "intent"


def _question_queue_history_dir(run_dir: Path) -> Path:
    """Return directory where additive queue snapshots are stored."""
    return _question_queue_snapshot_dir(run_dir) / "history"


_QUEUE_HISTORY_RETENTION_LIMIT = 100
_QUEUE_HISTORY_SNAPSHOT_GLOB = "question_queue.*.json"
_QUEUE_HISTORY_PRUNE_LOG = "question_queue.history.prune.jsonl"


_VALID_STATUSES = frozenset({"OPEN", "ANSWERED", "STALE", "SUPERSEDED", "DISMISSED", "UNASKABLE"})
_VALID_TAXONOMY_TYPES = frozenset(
    {"INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION"},
)
_VALID_SCOPE_KINDS = frozenset({"SYSTEM_WIDE", "FEATURE_SPECIFIC"})
_VALID_SOURCE_KINDS = frozenset(
    {"INTENT_AGENT", "PLANNER", "UNDER_SPEC", "PROMOTION_LOOP", "PDD_LIFECYCLE", "SLICE_AGENT"}
)
_VALID_SEVERITY = frozenset({"BLOCKING", "HIGH_RISK", "MEDIUM_RISK", "INFO"})
_VALID_QG_STATUSES = frozenset({"PASS", "FAIL", "PENDING"})
_VALID_ANSWER_KINDS = frozenset({"choice", "yes_no", "value", "bounded_text"})
_VALID_TRIGGER_KINDS = frozenset(
    {
        "PLANNER_CONSTRAINT_SAVED",
        "PLANNER_DECISION_RECORDED",
        "USER_ANSWER_INGESTED",
        "PLANNER_EVENT_UNRECOGNIZED",
    },
)
_VALID_ANSWER_VALUE_TYPES = frozenset(
    {"integer", "number", "currency", "duration", "date", "string"},
)

_TRIGGER_BY_EVENT = {
    "constraint_saved": "PLANNER_CONSTRAINT_SAVED",
    "decision_recorded": "PLANNER_DECISION_RECORDED",
}


class QueueValidationError(ValueError):
    """Raised when queue payload does not satisfy strict schema rules."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _ensure_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise QueueValidationError(f"{field_name} must be a string")
    return value


def _ensure_list_of_str(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise QueueValidationError(f"{field_name} must be a list")
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise QueueValidationError(
                f"{field_name}[{i}] must be a string, got {type(item).__name__}",
            )
    return value


def _ensure_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int):
        raise QueueValidationError(f"{field_name} must be an int")
    return value


def _ensure_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QueueValidationError(f"{field_name} must be a number")
    return float(value)


def _ensure_float_range(value: Any, field_name: str, min_incl: float, max_incl: float) -> float:
    number = _ensure_number(value, field_name)
    if not (min_incl <= number <= max_incl):
        raise QueueValidationError(
            f"{field_name} must be between {min_incl} and {max_incl}, got {number}",
        )
    return number


def _ensure_iso_datetime(value: Any, field_name: str) -> str:
    text = _ensure_str(value, field_name)
    # Allow Z-terminated timestamps and validate shape.
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:  # pragma: no cover - exercised by callers in validation tests
        raise QueueValidationError(f"{field_name} must be ISO-8601: {text}") from exc
    return text


def _ensure_no_extra_keys(payload: dict[str, Any], allowed: set[str], field_name: str) -> None:
    extra = set(payload) - allowed
    if extra:
        raise QueueValidationError(f"{field_name} has disallowed fields: {sorted(extra)}")


def _coerce_id(value: Any, field_name: str) -> str:
    if isinstance(value, bool) or value is None:
        raise QueueValidationError(f"{field_name} must be a non-empty string or int")
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        raise QueueValidationError(f"{field_name} must be a non-empty string or int")
    normalized = value.strip()
    if not normalized:
        raise QueueValidationError(f"{field_name} must be a non-empty string or int")
    return normalized


def _coerce_id_list(value: Any, field_name: str, *, allow_scalar: bool = False) -> list[str]:
    if value is None:
        return []
    if allow_scalar and isinstance(value, (int, str)):
        return [_coerce_id(value, field_name)]
    if isinstance(value, (list, tuple, set)):
        ids = [_coerce_id(item, field_name) for item in value]
        if isinstance(value, set):
            return sorted(ids)
        return ids
    raise QueueValidationError(
        f"{field_name} must be a string/int or list/tuple/set of strings/ints"
    )


def _coerce_system_binding(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise QueueValidationError("system_binding must be a dict")

    allowed_fields = {
        "constraint_key_hints",
        "decision_requirement_ids",
        "work_items",
    }
    _ensure_no_extra_keys(value, allowed_fields, "system_binding")

    system_binding: dict[str, Any] = {}
    for field in sorted(allowed_fields):
        if field not in value:
            continue
        system_binding[field] = list(_ensure_list_of_str(value[field], f"system_binding.{field}"))
    return system_binding


def _canonical_source_kind(value: Any, field_name: str) -> str:
    raw = _ensure_str(value, field_name).strip().upper()
    if raw not in _VALID_SOURCE_KINDS:
        raise QueueValidationError(
            f"{field_name} {value!r} is invalid; expected one of {sorted(_VALID_SOURCE_KINDS)}"
        )
    return raw


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    return False


def _ensure_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QueueValidationError(f"{field_name} must be a dict")
    return value


def _ensure_choice_specs(choices: Any, field_name: str) -> list[dict[str, str]]:
    if not isinstance(choices, list):
        raise QueueValidationError(f"{field_name} must be a list")
    normalized: list[dict[str, str]] = []
    for idx, choice in enumerate(choices):
        if not isinstance(choice, dict):
            raise QueueValidationError(
                f"{field_name}[{idx}] must be an object",
            )
        _ensure_no_extra_keys(
            choice,
            {"id", "label"},
            f"{field_name}[{idx}]",
        )
        normalized.append(
            {
                "id": _ensure_str(choice.get("id", ""), f"{field_name}[{idx}].id"),
                "label": _ensure_str(choice.get("label", ""), f"{field_name}[{idx}].label"),
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# Question item
# ---------------------------------------------------------------------------


@dataclass
class AnswerSpec:
    """Bounded answer specification for a question."""

    kind: str = "choice"  # choice | yes_no | value | bounded_text
    choices: list[dict[str, str]] = dataclass_field(default_factory=list)  # [{id, label}]
    value_type: str = ""  # integer | number | currency | duration | date | string
    units_hint: str = ""
    text_bounds: dict[str, int] = dataclass_field(default_factory=dict)  # {max_items, max_chars}


@dataclass
class UserPrompt:
    """User-facing question text with scenario and answer spec."""

    text: str = ""
    scenario: str = ""
    why_it_matters: str = ""
    answer_spec: AnswerSpec = dataclass_field(default_factory=AnswerSpec)


@dataclass
class QuestionOrigin:
    """Provenance for where a question came from."""

    source_kind: str = (
        ""  # INTENT_AGENT | PLANNER | UNDER_SPEC | PROMOTION_LOOP | PDD_LIFECYCLE | SLICE_AGENT
    )
    trace_id: str = ""
    signal_id: str = ""
    slice_id: str = ""
    layer: str = ""
    created_at: str = ""
    spec_refs: list[dict[str, Any]] = dataclass_field(default_factory=list)
    code_refs: list[dict[str, Any]] = dataclass_field(default_factory=list)


@dataclass
class QuestionBlockers:
    """What this question blocks."""

    severity: str = "INFO"  # BLOCKING | HIGH_RISK | MEDIUM_RISK | INFO
    blocked_slices: list[str] = dataclass_field(default_factory=list)
    blocked_layers: list[str] = dataclass_field(default_factory=list)
    blocked_steps: list[str] = dataclass_field(default_factory=list)


@dataclass
class QualityGateStatus:
    """Quality gate status embedded in the question item."""

    status: str = "PENDING"  # PASS | FAIL | PENDING
    attempts: int = 0
    last_quality_record_id: str = ""
    last_checked_at: str = dataclass_field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        _ensure_iso_datetime(self.last_checked_at, "quality_gate.last_checked_at")


@dataclass
class QuestionItem:
    """A single question in the Intent Agent queue.

    Per response2.md Section 2.1 JSON schema. Represents an underlying
    unknown classified as a user-valid taxonomy type.
    """

    question_id: str = ""
    status: str = "OPEN"  # OPEN | ANSWERED | STALE | SUPERSEDED | DISMISSED | UNASKABLE
    taxonomy_type: str = "CONSTRAINT"  # INTENT | CONSTRAINT | TRADEOFF | SCOPE | VALIDATION
    scope_kind: str = "FEATURE_SPECIFIC"  # SYSTEM_WIDE | FEATURE_SPECIFIC
    canonical_key: str = ""
    user_prompt: UserPrompt = dataclass_field(default_factory=UserPrompt)
    system_binding: dict[str, Any] = dataclass_field(default_factory=dict)
    origins: list[QuestionOrigin] = dataclass_field(default_factory=list)
    blockers: QuestionBlockers = dataclass_field(default_factory=QuestionBlockers)
    priority: dict[str, Any] = dataclass_field(
        default_factory=lambda: {"score": 0.0, "explanation": ""}
    )
    quality_gate: QualityGateStatus = dataclass_field(default_factory=QualityGateStatus)
    last_transition_reason: str = ""
    timestamps: dict[str, str] = dataclass_field(
        default_factory=lambda: {"created_at": "", "updated_at": ""}
    )

    def __post_init__(self) -> None:
        if not self.question_id:
            self.question_id = f"q_{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()
        if not self.timestamps.get("created_at"):
            self.timestamps["created_at"] = now
        if not self.timestamps.get("updated_at"):
            self.timestamps["updated_at"] = now

    def validate(self) -> None:
        if not isinstance(self.question_id, str) or not self.question_id.strip():
            raise QueueValidationError("question_id must be a non-empty string")
        if self.status not in _VALID_STATUSES:
            raise QueueValidationError(f"status {self.status!r} is not valid")
        if self.taxonomy_type not in _VALID_TAXONOMY_TYPES:
            raise QueueValidationError(f"taxonomy_type {self.taxonomy_type!r} is not valid")
        if self.scope_kind not in _VALID_SCOPE_KINDS:
            raise QueueValidationError(f"scope_kind {self.scope_kind!r} is not valid")

        if not isinstance(self.canonical_key, str):
            raise QueueValidationError("canonical_key must be a non-empty string")
        self.canonical_key = self.canonical_key.strip()
        if not self.canonical_key:
            raise QueueValidationError("canonical_key must be a non-empty string")

        if not isinstance(self.user_prompt, UserPrompt):
            raise QueueValidationError("user_prompt must be a UserPrompt")
        up = self.user_prompt
        _ensure_str(up.text, "user_prompt.text")
        _ensure_str(up.scenario, "user_prompt.scenario")
        _ensure_str(up.why_it_matters, "user_prompt.why_it_matters")
        if not isinstance(up.answer_spec, AnswerSpec):
            raise QueueValidationError("user_prompt.answer_spec must be an AnswerSpec")

        aspec = up.answer_spec
        if aspec.kind not in _VALID_ANSWER_KINDS:
            raise QueueValidationError(f"answer_spec.kind {aspec.kind!r} is not valid")
        _ensure_no_extra_keys(
            vars(aspec),
            {"kind", "choices", "value_type", "units_hint", "text_bounds"},
            "user_prompt.answer_spec",
        )
        if aspec.value_type and aspec.value_type not in _VALID_ANSWER_VALUE_TYPES:
            raise QueueValidationError(
                f"answer_spec.value_type {aspec.value_type!r} is not valid",
            )
        aspec.choices = _ensure_choice_specs(aspec.choices, "user_prompt.answer_spec.choices")
        if aspec.text_bounds:
            _ensure_no_extra_keys(
                aspec.text_bounds,
                {"max_items", "max_chars"},
                "user_prompt.answer_spec.text_bounds",
            )
            if not isinstance(aspec.text_bounds, dict):
                raise QueueValidationError("user_prompt.answer_spec.text_bounds must be a dict")
            for bound_key, bound_value in aspec.text_bounds.items():
                if bound_key not in {"max_items", "max_chars"}:
                    raise QueueValidationError(
                        f"user_prompt.answer_spec.text_bounds has unexpected key {bound_key!r}"
                    )
                _ensure_int(bound_value, f"user_prompt.answer_spec.text_bounds[{bound_key}]")
                if bound_value < 1:
                    raise QueueValidationError(
                        f"user_prompt.answer_spec.text_bounds[{bound_key}] must be >= 1"
                    )

        self.system_binding = _coerce_system_binding(self.system_binding)

        if not isinstance(self.origins, list) or not self.origins:
            raise QueueValidationError("origins must be a non-empty list")
        for idx, origin in enumerate(self.origins):
            if not isinstance(origin, QuestionOrigin):
                raise QueueValidationError(f"origins[{idx}] must be a QuestionOrigin")
            origin.source_kind = _canonical_source_kind(
                origin.source_kind,
                f"origins[{idx}].source_kind",
            )
            _ensure_no_extra_keys(
                vars(origin),
                {
                    "source_kind",
                    "trace_id",
                    "signal_id",
                    "slice_id",
                    "layer",
                    "created_at",
                    "spec_refs",
                    "code_refs",
                },
                f"origins[{idx}]",
            )
            _ensure_str(origin.created_at, f"origins[{idx}].created_at")
            _ensure_iso_datetime(origin.created_at, f"origins[{idx}].created_at")
            if not isinstance(origin.spec_refs, list):
                raise QueueValidationError(f"origins[{idx}].spec_refs must be a list")
            for r_idx, ref in enumerate(origin.spec_refs):
                if not isinstance(ref, dict):
                    raise QueueValidationError(f"origins[{idx}].spec_refs[{r_idx}] must be a dict")
                _ensure_no_extra_keys(
                    ref,
                    {"spec_text", "source_file", "source_line_hint"},
                    f"origins[{idx}].spec_refs[{r_idx}]",
                )
                _ensure_str(
                    ref.get("spec_text", ""), f"origins[{idx}].spec_refs[{r_idx}].spec_text"
                )
                _ensure_str(
                    ref.get("source_file", ""), f"origins[{idx}].spec_refs[{r_idx}].source_file"
                )
                _ensure_int(
                    ref.get("source_line_hint", 0),
                    f"origins[{idx}].spec_refs[{r_idx}].source_line_hint",
                )
            for r_idx, ref in enumerate(origin.code_refs):
                if not isinstance(ref, dict):
                    raise QueueValidationError(f"origins[{idx}].code_refs[{r_idx}] must be a dict")
                _ensure_no_extra_keys(
                    ref,
                    {"file", "symbol", "line"},
                    f"origins[{idx}].code_refs[{r_idx}]",
                )
                _ensure_str(ref.get("file", ""), f"origins[{idx}].code_refs[{r_idx}].file")
                _ensure_str(ref.get("symbol", ""), f"origins[{idx}].code_refs[{r_idx}].symbol")
                _ensure_int(ref.get("line", 0), f"origins[{idx}].code_refs[{r_idx}].line")

        if not isinstance(self.blockers, QuestionBlockers):
            raise QueueValidationError("blockers must be a QuestionBlockers")
        _ensure_no_extra_keys(
            vars(self.blockers),
            {"severity", "blocked_slices", "blocked_layers", "blocked_steps"},
            "blockers",
        )
        if self.blockers.severity not in _VALID_SEVERITY:
            raise QueueValidationError(f"blockers.severity {self.blockers.severity!r} is invalid")
        _ensure_list_of_str(self.blockers.blocked_slices, "blockers.blocked_slices")
        _ensure_list_of_str(self.blockers.blocked_layers, "blockers.blocked_layers")
        _ensure_list_of_str(self.blockers.blocked_steps, "blockers.blocked_steps")

        if not isinstance(self.priority, dict):
            raise QueueValidationError("priority must be a dict")
        if "score" not in self.priority or "explanation" not in self.priority:
            raise QueueValidationError("priority must include score and explanation")
        _ensure_float_range(self.priority["score"], "priority.score", 0.0, 1.0)
        _ensure_str(self.priority["explanation"], "priority.explanation")
        _ensure_str(self.last_transition_reason, "last_transition_reason")

        if not isinstance(self.quality_gate, QualityGateStatus):
            raise QueueValidationError("quality_gate must be a QualityGateStatus")
        _ensure_no_extra_keys(
            vars(self.quality_gate),
            {"status", "attempts", "last_quality_record_id", "last_checked_at"},
            "quality_gate",
        )
        if self.quality_gate.status not in _VALID_QG_STATUSES:
            raise QueueValidationError(
                f"quality_gate.status {self.quality_gate.status!r} is invalid"
            )
        attempts = _ensure_int(self.quality_gate.attempts, "quality_gate.attempts")
        if attempts < 0:
            raise QueueValidationError("quality_gate.attempts must be >= 0")
        _ensure_str(self.quality_gate.last_quality_record_id, "quality_gate.last_quality_record_id")
        _ensure_iso_datetime(self.quality_gate.last_checked_at, "quality_gate.last_checked_at")

        if not isinstance(self.timestamps, dict):
            raise QueueValidationError("timestamps must be a dict")
        _ensure_no_extra_keys(
            self.timestamps,
            {"created_at", "updated_at"},
            "timestamps",
        )
        if "created_at" not in self.timestamps or "updated_at" not in self.timestamps:
            raise QueueValidationError("timestamps must include created_at and updated_at")
        _ensure_iso_datetime(self.timestamps["created_at"], "timestamps.created_at")
        _ensure_iso_datetime(self.timestamps["updated_at"], "timestamps.updated_at")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        answer_spec_payload = {
            "kind": self.user_prompt.answer_spec.kind,
            "choices": list(self.user_prompt.answer_spec.choices),
            "units_hint": self.user_prompt.answer_spec.units_hint,
            "text_bounds": dict(self.user_prompt.answer_spec.text_bounds),
        }
        if self.user_prompt.answer_spec.value_type:
            answer_spec_payload["value_type"] = self.user_prompt.answer_spec.value_type
        return {
            "question_id": self.question_id,
            "status": self.status,
            "taxonomy_type": self.taxonomy_type,
            "scope_kind": self.scope_kind,
            "canonical_key": self.canonical_key,
            "user_prompt": {
                "text": self.user_prompt.text,
                "scenario": self.user_prompt.scenario,
                "why_it_matters": self.user_prompt.why_it_matters,
                "answer_spec": answer_spec_payload,
            },
            "system_binding": dict(self.system_binding),
            "origins": [
                {
                    "source_kind": origin.source_kind,
                    "trace_id": origin.trace_id,
                    "signal_id": origin.signal_id,
                    "slice_id": origin.slice_id,
                    "layer": origin.layer,
                    "created_at": origin.created_at,
                    "spec_refs": [dict(r) for r in origin.spec_refs],
                    "code_refs": [dict(r) for r in origin.code_refs],
                }
                for origin in self.origins
            ],
            "blockers": {
                "severity": self.blockers.severity,
                "blocked_slices": list(self.blockers.blocked_slices),
                "blocked_layers": list(self.blockers.blocked_layers),
                "blocked_steps": list(self.blockers.blocked_steps),
            },
            "priority": dict(self.priority),
            "quality_gate": {
                "status": self.quality_gate.status,
                "attempts": self.quality_gate.attempts,
                "last_quality_record_id": self.quality_gate.last_quality_record_id,
                "last_checked_at": self.quality_gate.last_checked_at,
            },
            "last_transition_reason": self.last_transition_reason,
            "timestamps": dict(self.timestamps),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> QuestionItem:
        if not isinstance(d, dict):
            raise QueueValidationError("question payload must be an object")

        required_fields = {
            "question_id",
            "status",
            "taxonomy_type",
            "scope_kind",
            "canonical_key",
            "user_prompt",
            "origins",
            "blockers",
            "priority",
            "quality_gate",
            "timestamps",
        }
        allowed_fields = required_fields | {"system_binding", "last_transition_reason"}
        _ensure_no_extra_keys(d, allowed_fields, "question")
        missing = required_fields - set(d)
        if missing:
            raise QueueValidationError(
                f"question payload missing required fields: {sorted(missing)}"
            )

        user_prompt_raw = d["user_prompt"]
        if not isinstance(user_prompt_raw, dict):
            raise QueueValidationError("user_prompt must be an object")
        required_prompt = {"text", "scenario", "why_it_matters", "answer_spec"}
        _ensure_no_extra_keys(user_prompt_raw, required_prompt, "user_prompt")
        missing_prompt = required_prompt - set(user_prompt_raw)
        if missing_prompt:
            raise QueueValidationError(f"user_prompt missing {sorted(missing_prompt)}")

        answer_spec_raw = user_prompt_raw["answer_spec"]
        if not isinstance(answer_spec_raw, dict):
            raise QueueValidationError("answer_spec must be an object")
        answer_spec_required = {"kind"}
        _ensure_no_extra_keys(
            answer_spec_raw,
            answer_spec_required | {"choices", "value_type", "units_hint", "text_bounds"},
            "answer_spec",
        )
        if "kind" not in answer_spec_raw:
            raise QueueValidationError("answer_spec missing required field kind")
        if answer_spec_raw.get("kind") not in _VALID_ANSWER_KINDS:
            raise QueueValidationError(f"answer_spec.kind {answer_spec_raw.get('kind')!r} invalid")
        validated_text_bounds: dict[str, int] = {}
        if "text_bounds" in answer_spec_raw:
            tb = answer_spec_raw["text_bounds"]
            if not isinstance(tb, dict):
                raise QueueValidationError("answer_spec.text_bounds must be an object")
            _ensure_no_extra_keys(
                tb,
                {"max_items", "max_chars"},
                "answer_spec.text_bounds",
            )
            for key in tb:
                if key not in {"max_items", "max_chars"}:
                    raise QueueValidationError(
                        f"answer_spec.text_bounds has disallowed key {key!r}"
                    )
                _ensure_int(tb[key], f"answer_spec.text_bounds[{key}]")
                if tb[key] < 1:
                    raise QueueValidationError(
                        f"answer_spec.text_bounds[{key}] must be >= 1",
                    )
            validated_text_bounds.update(
                {key: _ensure_int(tb[key], f"answer_spec.text_bounds[{key}]") for key in tb}
            )

        answer_spec_choices = answer_spec_raw.get("choices", [])
        if not isinstance(answer_spec_choices, list):
            raise QueueValidationError("answer_spec.choices must be a list")
        validated_choices = _ensure_choice_specs(
            answer_spec_choices,
            "answer_spec.choices",
        )

        answer_spec_value_type = answer_spec_raw.get("value_type", "")
        if "value_type" in answer_spec_raw:
            if not isinstance(answer_spec_value_type, str):
                raise QueueValidationError("answer_spec.value_type must be a string")
            if answer_spec_value_type not in _VALID_ANSWER_VALUE_TYPES:
                raise QueueValidationError(
                    f"answer_spec.value_type {answer_spec_value_type!r} is not valid",
                )

        answer_spec = AnswerSpec(
            kind=answer_spec_raw.get("kind", "choice"),
            choices=validated_choices,
            value_type=answer_spec_value_type,
            units_hint=answer_spec_raw.get("units_hint", ""),
            text_bounds=validated_text_bounds,
        )
        if not isinstance(answer_spec.units_hint, str):
            raise QueueValidationError("answer_spec.units_hint must be a string")

        user_prompt = UserPrompt(
            text=user_prompt_raw.get("text", ""),
            scenario=user_prompt_raw.get("scenario", ""),
            why_it_matters=user_prompt_raw.get("why_it_matters", ""),
            answer_spec=answer_spec,
        )

        blockers_raw = d["blockers"]
        if not isinstance(blockers_raw, dict):
            raise QueueValidationError("blockers must be an object")
        _ensure_no_extra_keys(
            blockers_raw,
            {"severity", "blocked_slices", "blocked_layers", "blocked_steps"},
            "blockers",
        )
        required_blockers = {"severity", "blocked_slices"}
        missing_blockers = required_blockers - set(blockers_raw)
        if missing_blockers:
            raise QueueValidationError(
                f"blockers missing required fields: {sorted(missing_blockers)}"
            )
        blockers = QuestionBlockers(
            severity=blockers_raw.get("severity", "INFO"),
            blocked_slices=blockers_raw.get("blocked_slices", []),
            blocked_layers=blockers_raw.get("blocked_layers", []),
            blocked_steps=blockers_raw.get("blocked_steps", []),
        )

        qg_raw = d["quality_gate"]
        if not isinstance(qg_raw, dict):
            raise QueueValidationError("quality_gate must be an object")
        _ensure_no_extra_keys(
            qg_raw,
            {"status", "attempts", "last_quality_record_id", "last_checked_at"},
            "quality_gate",
        )
        required_qg = {"status", "attempts", "last_quality_record_id", "last_checked_at"}
        missing_qg = required_qg - set(qg_raw)
        if missing_qg:
            raise QueueValidationError(
                f"quality_gate missing required fields: {sorted(missing_qg)}"
            )
        quality_gate = QualityGateStatus(
            status=qg_raw.get("status", "PENDING"),
            attempts=qg_raw.get("attempts", 0),
            last_quality_record_id=qg_raw.get("last_quality_record_id", ""),
            last_checked_at=qg_raw.get("last_checked_at", ""),
        )

        origins_raw = d["origins"]
        if not isinstance(origins_raw, list) or not origins_raw:
            raise QueueValidationError("origins must be a non-empty list")
        origins: list[QuestionOrigin] = []
        for origin_raw in origins_raw:
            if not isinstance(origin_raw, dict):
                raise QueueValidationError("each origin must be an object")
            _ensure_no_extra_keys(
                origin_raw,
                {
                    "source_kind",
                    "trace_id",
                    "signal_id",
                    "slice_id",
                    "layer",
                    "created_at",
                    "spec_refs",
                    "code_refs",
                },
                "origin",
            )
            for required_origin in ("source_kind", "created_at"):
                if required_origin not in origin_raw:
                    raise QueueValidationError(f"origin missing required field {required_origin!r}")
            source_kind = _canonical_source_kind(origin_raw["source_kind"], "origin.source_kind")
            _ensure_iso_datetime(origin_raw.get("created_at", ""), "origin.created_at")

            spec_refs = origin_raw.get("spec_refs", [])
            if not isinstance(spec_refs, list):
                raise QueueValidationError("origin.spec_refs must be a list")

            code_refs = origin_raw.get("code_refs", [])
            if not isinstance(code_refs, list):
                raise QueueValidationError("origin.code_refs must be a list")

            validated_spec_refs: list[dict[str, Any]] = []
            for idx, ref_raw in enumerate(spec_refs):
                if not isinstance(ref_raw, dict):
                    raise QueueValidationError(f"origin.spec_refs[{idx}] must be an object")
                _ensure_no_extra_keys(
                    ref_raw,
                    {"spec_text", "source_file", "source_line_hint"},
                    "origin.spec_refs",
                )
                validated_spec_refs.append(
                    {
                        "spec_text": _ensure_str(
                            ref_raw.get("spec_text", ""), f"origin.spec_refs[{idx}].spec_text"
                        ),
                        "source_file": _ensure_str(
                            ref_raw.get("source_file", ""), f"origin.spec_refs[{idx}].source_file"
                        ),
                        "source_line_hint": _ensure_int(
                            ref_raw.get("source_line_hint", 0),
                            f"origin.spec_refs[{idx}].source_line_hint",
                        ),
                    }
                )

            validated_code_refs: list[dict[str, Any]] = []
            for idx, ref_raw in enumerate(code_refs):
                if not isinstance(ref_raw, dict):
                    raise QueueValidationError(f"origin.code_refs[{idx}] must be an object")
                _ensure_no_extra_keys(
                    ref_raw,
                    {"file", "symbol", "line"},
                    "origin.code_refs",
                )
                validated_code_refs.append(
                    {
                        "file": _ensure_str(
                            ref_raw.get("file", ""), f"origin.code_refs[{idx}].file"
                        ),
                        "symbol": _ensure_str(
                            ref_raw.get("symbol", ""), f"origin.code_refs[{idx}].symbol"
                        ),
                        "line": _ensure_int(
                            ref_raw.get("line", 0), f"origin.code_refs[{idx}].line"
                        ),
                    }
                )

            origins.append(
                QuestionOrigin(
                    source_kind=source_kind,
                    trace_id=origin_raw.get("trace_id", ""),
                    signal_id=origin_raw.get("signal_id", ""),
                    slice_id=origin_raw.get("slice_id", ""),
                    layer=origin_raw.get("layer", ""),
                    created_at=origin_raw.get("created_at", ""),
                    spec_refs=validated_spec_refs,
                    code_refs=validated_code_refs,
                ),
            )

        timestamps = d["timestamps"]
        if not isinstance(timestamps, dict):
            raise QueueValidationError("timestamps must be an object")
        _ensure_no_extra_keys(
            timestamps,
            {"created_at", "updated_at"},
            "timestamps",
        )
        required_timestamps = {"created_at", "updated_at"}
        missing_timestamps = required_timestamps - set(timestamps)
        if missing_timestamps:
            raise QueueValidationError(
                f"timestamps missing required fields: {sorted(missing_timestamps)}"
            )

        raw_system_binding = d.get("system_binding", {})
        if raw_system_binding is None:
            raw_system_binding = {}
        if not isinstance(raw_system_binding, dict):
            raise QueueValidationError("system_binding must be an object")
        normalized_system_binding = _coerce_system_binding(raw_system_binding)

        item = cls(
            question_id=d.get("question_id", ""),
            status=d.get("status", "OPEN"),
            taxonomy_type=d.get("taxonomy_type", "CONSTRAINT"),
            scope_kind=d.get("scope_kind", "FEATURE_SPECIFIC"),
            canonical_key=d.get("canonical_key", ""),
            user_prompt=user_prompt,
            system_binding=normalized_system_binding,
            origins=origins,
            blockers=blockers,
            priority=dict(d.get("priority", {"score": 0.0, "explanation": ""})),
            quality_gate=quality_gate,
            last_transition_reason=d.get("last_transition_reason", ""),
            timestamps=dict(timestamps),
        )
        item.validate()
        return item


# ---------------------------------------------------------------------------
# Reassessment projections
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReassessQuestionKeySignal:
    """Projection of canonical-key linkage state consumed by queue reassessment."""

    canonical_key: str
    resolved_constraint_ids: tuple[str, ...] = ()
    related_decision_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReassessPlannerSignal:
    """Projection of planner events consumed by queue reassessment."""

    event_kind: str = ""
    event_ref: str = ""
    affected_canonical_keys: tuple[str, ...] = ()
    affected_constraint_ids: tuple[str, ...] = ()
    affected_decision_ids: tuple[str, ...] = ()
    affected_question_ids: tuple[str, ...] = ()
    superseded_question_ids: tuple[str, ...] = ()
    superseded_canonical_keys: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# QuestionQueue
# ---------------------------------------------------------------------------


class QuestionQueue:
    """Manages the lifecycle of QuestionItems.

    Per response2.md Section 2: priority ordering, dedup, reassessment,
    batching, staleness tracking.
    """

    _severity_weight: ClassVar[dict[str, float]] = {
        "BLOCKING": 0.45,
        "HIGH_RISK": 0.3,
        "MEDIUM_RISK": 0.2,
        "INFO": 0.05,
    }
    _scope_weight: ClassVar[dict[str, float]] = {
        "SYSTEM_WIDE": 0.18,
        "FEATURE_SPECIFIC": 0.08,
    }
    _severity_tiebreak: ClassVar[dict[str, int]] = {
        "BLOCKING": 4,
        "HIGH_RISK": 3,
        "MEDIUM_RISK": 2,
        "INFO": 1,
    }
    _canonical_key_batch_delimiter: ClassVar[str] = "."

    def __init__(self) -> None:
        self._items: dict[str, QuestionItem] = {}
        self._reassess_drop_actions: list[dict[str, Any]] = []

    def _touch(self, item: QuestionItem, reason: str = "") -> None:
        if reason:
            item.last_transition_reason = reason
        item.timestamps["updated_at"] = datetime.now(UTC).isoformat()

    @staticmethod
    def _blocked_layer_criticality(blocked_layers: list[str]) -> float:
        if not blocked_layers:
            return 0.0
        planning_like = {"PLANNING", "PLAN", "DECISION", "SCOPE", "ARCHITECTURE", "CONSTRAINT"}
        score = 0.0
        for layer in blocked_layers:
            normalized = (layer or "").upper()
            if any(token in normalized for token in planning_like):
                score += 0.02
            else:
                score += 0.005
        return min(score, 0.1)

    def _compute_priority(self, item: QuestionItem) -> tuple[float, str]:
        blocker_count = len(item.blockers.blocked_slices)
        blocker_term = min(blocker_count / 5.0, 1.0)
        severity_term = self._severity_weight.get(item.blockers.severity, 0.0)
        scope_term = self._scope_weight.get(item.scope_kind, 0.0)
        layer_term = self._blocked_layer_criticality(item.blockers.blocked_layers)
        stale_penalty = 0.0
        stale_reason = ""
        if not blocker_count:
            stale_penalty = 0.22
            stale_reason = "no remaining blocked_slices"

        score = (
            0.40 * blocker_term
            + 0.30 * severity_term
            + 0.20 * scope_term
            + layer_term
            - stale_penalty
        )
        score = max(0.0, min(1.0, round(score, 12)))
        explanation = (
            f"blocked_slices={blocker_count} severity={item.blockers.severity} "
            f"scope={item.scope_kind} planning_layer_penalty={layer_term:.2f} "
            f"stale_penalty={stale_reason}"
        )
        item.priority = {"score": score, "explanation": explanation}
        return score, explanation

    def _sort_key(self, item: QuestionItem) -> tuple[Any, ...]:
        created_at = item.timestamps.get("created_at", "")
        return (
            -item.priority.get("score", 0.0),
            -len(item.blockers.blocked_slices),
            -self._severity_tiebreak.get(item.blockers.severity, 0),
            -self._scope_weight.get(item.scope_kind, 0.0),
            -self._blocked_layer_criticality(item.blockers.blocked_layers),
            -len(item.blockers.blocked_layers),
            -len(item.blockers.blocked_steps),
            item.canonical_key,
            created_at,
            item.question_id,
        )

    def _rank_open_items(self, run_agent: Any = None) -> tuple[list[QuestionItem], dict[str, Any]]:
        open_items = [it for it in self._items.values() if it.status == "OPEN"]
        for item in open_items:
            self._compute_priority(item)

        ordered = sorted(open_items, key=self._sort_key)
        tie_break_status: dict[str, Any] = {"mode": "deterministic", "reason": "not_attempted"}

        # Optional deterministic-safe LLM tie-break for top-5 only.
        if not run_agent or len(ordered) <= 1:
            return ordered, tie_break_status

        top_candidates = ordered[:5]
        if len(top_candidates) < 2:
            tie_break_status = {"mode": "deterministic", "reason": "insufficient_candidates"}
            return ordered, tie_break_status

        prompt_payload = {
            "items": [
                {
                    "question_id": item.question_id,
                    "canonical_key": item.canonical_key,
                    "scope_kind": item.scope_kind,
                    "taxonomy_type": item.taxonomy_type,
                    "score": item.priority.get("score", 0.0),
                    "severity": item.blockers.severity,
                    "blocked_slices": len(item.blockers.blocked_slices),
                }
                for item in top_candidates
            ],
        }
        prompt = (
            "Which question unlocks the most progress with the least user burden?\n"
            "Return JSON object with keys: ordered_question_ids (array of question_id in "
            "priority order) and justification (short reason for the ordering).\n"
            f"{json.dumps(prompt_payload)}"
        )

        try:
            raw = run_agent(prompt)
            text = raw.strip()
            tie_break_response = json.loads(text)
            if isinstance(tie_break_response, dict):
                ordered_ids = tie_break_response.get("ordered_question_ids")
                justification = str(tie_break_response.get("justification", "")).strip()
                if not isinstance(ordered_ids, list):
                    tie_break_status = {
                        "mode": "deterministic",
                        "reason": "llm_missing_ordered_question_ids",
                    }
                    return ordered, tie_break_status
                if not justification:
                    tie_break_status = {
                        "mode": "deterministic",
                        "reason": "llm_missing_justification",
                    }
                    return ordered, tie_break_status

                id_to_item = {it.question_id: it for it in top_candidates}
                ordered_top: list[QuestionItem] = []
                used: set[str] = set()
                for candidate_id in ordered_ids:
                    candidate_key = str(candidate_id)
                    item = id_to_item.get(candidate_key)
                    if item is None or candidate_key in used:
                        continue
                    ordered_top.append(item)
                    used.add(candidate_key)
                if used:
                    for item in top_candidates:
                        if item.question_id not in used:
                            ordered_top.append(item)
                    tie_break_status = {
                        "mode": "llm",
                        "reason": "applied",
                        "ordered_question_ids": [item.question_id for item in ordered_top],
                        "justification": justification,
                    }
                    logger.info(
                        "Applied LLM tie-break ordering for top-priority questions",
                        extra={"tie_break_status": tie_break_status},
                    )
                    return ordered_top + ordered[5:], tie_break_status
            tie_break_status = {"mode": "deterministic", "reason": "llm_no_usable_ids"}
        except Exception as exc:
            tie_break_status = {
                "mode": "deterministic",
                "reason": "llm_error_fallback",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
            logger.warning(
                "LLM tie-break failed for next_question ordering; using deterministic fallback",
                extra={"tie_break_status": tie_break_status},
                exc_info=True,
            )

        return ordered, tie_break_status

    @classmethod
    def _batch_prefix_from_canonical(cls, canonical_key: str) -> str:
        if not canonical_key:
            return ""
        delimiter = cls._canonical_key_batch_delimiter
        if delimiter not in canonical_key:
            return ""
        return canonical_key.split(delimiter, 1)[0]

    def _project_question_key_map(
        self,
        question_key_map: dict[str, ReassessQuestionKeySignal],
    ) -> dict[str, ReassessQuestionKeySignal]:
        projected: dict[str, ReassessQuestionKeySignal] = {}
        for raw_canonical_key, signal in question_key_map.items():
            canonical_key = _coerce_id(raw_canonical_key, "question_key_map.canonical_key")
            if not isinstance(signal, ReassessQuestionKeySignal):
                raise QueueValidationError(
                    "question_key_map values must be ReassessQuestionKeySignal instances"
                )

            signal_key = _coerce_id(signal.canonical_key, "question_key_map.signal.canonical_key")
            if signal_key != canonical_key:
                raise QueueValidationError(
                    "question_key_map key must match ReassessQuestionKeySignal.canonical_key"
                )

            projected[canonical_key] = ReassessQuestionKeySignal(
                canonical_key=canonical_key,
                resolved_constraint_ids=tuple(
                    _coerce_id_list(
                        signal.resolved_constraint_ids,
                        "question_key_map.signal.resolved_constraint_ids",
                    )
                ),
                related_decision_ids=tuple(
                    _coerce_id_list(
                        signal.related_decision_ids,
                        "question_key_map.signal.related_decision_ids",
                    )
                ),
            )

        return projected

    def _project_planner_updates(
        self,
        planner_updates: list[ReassessPlannerSignal],
    ) -> list[ReassessPlannerSignal]:
        projected: list[ReassessPlannerSignal] = []
        for idx, update in enumerate(planner_updates):
            if not isinstance(update, ReassessPlannerSignal):
                raise QueueValidationError(
                    "planner_updates entries must be ReassessPlannerSignal instances"
                )

            event_kind_raw = _ensure_str(update.event_kind, f"planner_updates[{idx}].event_kind")
            event_kind = event_kind_raw.strip().lower()
            event_ref = ""
            if update.event_ref:
                event_ref = _coerce_id(update.event_ref, f"planner_updates[{idx}].event_ref")

            projected.append(
                ReassessPlannerSignal(
                    event_kind=event_kind,
                    event_ref=event_ref,
                    affected_canonical_keys=tuple(
                        _coerce_id_list(
                            update.affected_canonical_keys,
                            f"planner_updates[{idx}].affected_canonical_keys",
                        )
                    ),
                    affected_constraint_ids=tuple(
                        _coerce_id_list(
                            update.affected_constraint_ids,
                            f"planner_updates[{idx}].affected_constraint_ids",
                        )
                    ),
                    affected_decision_ids=tuple(
                        _coerce_id_list(
                            update.affected_decision_ids,
                            f"planner_updates[{idx}].affected_decision_ids",
                        )
                    ),
                    affected_question_ids=tuple(
                        _coerce_id_list(
                            update.affected_question_ids,
                            f"planner_updates[{idx}].affected_question_ids",
                        )
                    ),
                    superseded_question_ids=tuple(
                        _coerce_id_list(
                            update.superseded_question_ids,
                            f"planner_updates[{idx}].superseded_question_ids",
                        )
                    ),
                    superseded_canonical_keys=tuple(
                        _coerce_id_list(
                            update.superseded_canonical_keys,
                            f"planner_updates[{idx}].superseded_canonical_keys",
                        )
                    ),
                )
            )

        return projected

    def _build_trigger(self, planner_updates: list[ReassessPlannerSignal]) -> dict[str, str]:
        if not planner_updates:
            return {"kind": "USER_ANSWER_INGESTED", "ref": ""}
        for update in planner_updates:
            trigger_kind = _TRIGGER_BY_EVENT.get(update.event_kind)
            if trigger_kind:
                return {"kind": trigger_kind, "ref": update.event_ref}
        ref = ""
        for update in planner_updates:
            ref = update.event_ref
            if ref:
                break
        return {"kind": "PLANNER_EVENT_UNRECOGNIZED", "ref": ref}

    def _collect_redundant_keys(
        self,
        planner_updates: list[ReassessPlannerSignal],
        question_key_map: dict[str, ReassessQuestionKeySignal],
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        canonical_reasons: dict[str, set[str]] = {}
        question_reasons: dict[str, set[str]] = {}

        def _record_reason(bucket: dict[str, set[str]], key: str, reason: str) -> None:
            if not key:
                return
            bucket.setdefault(key, set()).add(reason)

        planner_id_to_canonical: dict[str, set[str]] = {}

        def _record_unmapped_planner_id(
            update_index: int,
            update: ReassessPlannerSignal,
            field_name: str,
            raw_id: str,
        ) -> None:
            self._record_reassess_drop_action(
                source="planner_updates",
                identifier=f"entry[{update_index}].{field_name}",
                reason=(
                    f"planner id {raw_id!r} from {field_name} does not map to any canonical_key"
                ),
                metadata={
                    "value": raw_id,
                    "event_kind": update.event_kind,
                    "event_ref": update.event_ref,
                },
            )

        for canonical_key, ref in question_key_map.items():
            raw_ids = [canonical_key, *ref.resolved_constraint_ids, *ref.related_decision_ids]
            _record_reason(canonical_reasons, canonical_key, "canonical_key")
            for rid in raw_ids:
                planner_id_to_canonical.setdefault(rid, set()).add(canonical_key)

        for update_index, update in enumerate(planner_updates):
            canonical_keys = set(update.affected_canonical_keys)
            for canonical_key in canonical_keys:
                _record_reason(canonical_reasons, canonical_key, "canonical_key")

            for raw_id in update.affected_constraint_ids:
                mapped_keys = planner_id_to_canonical.get(raw_id, set())
                if not mapped_keys:
                    _record_unmapped_planner_id(
                        update_index,
                        update,
                        "affected_constraint_ids",
                        raw_id,
                    )
                    continue
                for canonical_key in mapped_keys:
                    _record_reason(canonical_reasons, canonical_key, "constraint_map")

            for raw_id in update.affected_decision_ids:
                mapped_keys = planner_id_to_canonical.get(raw_id, set())
                if not mapped_keys:
                    _record_unmapped_planner_id(
                        update_index,
                        update,
                        "affected_decision_ids",
                        raw_id,
                    )
                    continue
                for canonical_key in mapped_keys:
                    _record_reason(canonical_reasons, canonical_key, "decision_map")

            for question_id in update.affected_question_ids:
                _record_reason(question_reasons, question_id, "question_id")
                mapped_keys = planner_id_to_canonical.get(question_id, set())
                if not mapped_keys and question_id not in self._items:
                    _record_unmapped_planner_id(
                        update_index,
                        update,
                        "affected_question_ids",
                        question_id,
                    )
                for canonical_key in mapped_keys:
                    _record_reason(canonical_reasons, canonical_key, "question_map")

            for raw_id in update.superseded_question_ids:
                _record_reason(question_reasons, raw_id, "superseded_question_ids")
                mapped_keys = planner_id_to_canonical.get(raw_id, set())
                if not mapped_keys and raw_id not in self._items:
                    _record_unmapped_planner_id(
                        update_index,
                        update,
                        "superseded_question_ids",
                        raw_id,
                    )
                for canonical_key in mapped_keys:
                    _record_reason(canonical_reasons, canonical_key, "question_map")

            for related_key in update.superseded_canonical_keys:
                _record_reason(canonical_reasons, related_key, "superseded_canonical_keys")

        canonical_reasons = {key: set(values) for key, values in canonical_reasons.items() if key}
        question_reasons = {
            question_id: set(values)
            for question_id, values in question_reasons.items()
            if question_id
        }
        return canonical_reasons, question_reasons

    def _record_reassess_drop_action(
        self,
        *,
        source: str,
        identifier: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        action: dict[str, Any] = {
            "question_id": "",
            "action": "INVALID_INPUT",
            "source": source,
            "identifier": identifier,
            "reason": reason,
        }
        if metadata:
            action["metadata"] = metadata
        self._reassess_drop_actions.append(action)

    def _drain_reassess_drop_actions(self) -> list[dict[str, Any]]:
        actions = list(self._reassess_drop_actions)
        self._reassess_drop_actions.clear()
        return actions

    # TODO [R2-2.1]: Implement enqueue(item) — add item after quality gate pass
    def enqueue(self, item: QuestionItem) -> None:
        """Add a quality-gate-passed item to the queue."""
        item.validate()
        if item.quality_gate.status != "PASS":
            logger.warning(
                "Skipping enqueue for %s: quality_gate status is %s (need PASS)",
                item.question_id,
                item.quality_gate.status,
            )
            return
        now = datetime.now(UTC).isoformat()
        item.timestamps["updated_at"] = now
        if not item.timestamps.get("created_at"):
            item.timestamps["created_at"] = now
        self._items[item.question_id] = item

    # TODO [R2-2.2]: Implement next_question() → QuestionItem | None
    #   - Returns the highest-priority OPEN item
    #   - Priority: deterministic base score from blockers/severity/scope/layer
    #   - scoring formula (Section 2.2):
    #     blocked_slices count, severity weight, scope_kind weight,
    #     layer criticality, staleness penalty
    def next_question(self, run_agent: Any = None) -> QuestionItem | None:
        """Return the highest-priority OPEN question."""
        open_items, _ = self._rank_open_items(run_agent=run_agent)
        return open_items[0] if open_items else None

    # TODO [R2-2.5]: Implement next_batch() → list[QuestionItem]
    #   - Returns batch of 1-3 questions sharing same domain concern
    #   - Default: single question. Batch only if same canonical_key prefix
    #     + answering together reduces ambiguity + all pass quality gate
    def next_batch(self, run_agent: Any = None) -> list[QuestionItem]:
        """Return the next batch of questions to present together."""
        top = self.next_question(run_agent=run_agent)
        if top is None:
            return []

        prefix = self._batch_prefix_from_canonical(top.canonical_key)
        if not prefix:
            return [top]

        compatible_types = {
            "CONSTRAINT": {"CONSTRAINT", "SCOPE"},
            "SCOPE": {"SCOPE", "CONSTRAINT"},
            "TRADEOFF": {"TRADEOFF"},
            "INTENT": {"INTENT"},
            "VALIDATION": {"VALIDATION"},
        }.get(top.taxonomy_type, {top.taxonomy_type})

        ranked_items, _ = self._rank_open_items(run_agent=run_agent)
        peers = [
            item
            for item in ranked_items
            if item.question_id != top.question_id
            and item.scope_kind == top.scope_kind
            and self._batch_prefix_from_canonical(item.canonical_key) == prefix
            and item.taxonomy_type in compatible_types
            and item.quality_gate.status == "PASS"
        ]

        peers = peers[:2]
        batch = [top, *peers]
        if len(batch) < 2:
            return [top]

        return batch

    def reassess(
        self,
        planner_updates: list[ReassessPlannerSignal],
        question_key_map: dict[str, ReassessQuestionKeySignal],
        *,
        run_id: str = "",
        session_id: str = "",
        run_agent: Any = None,
    ) -> dict[str, Any]:
        """Reassess all OPEN questions using explicit planner/key projection contracts."""
        created_at = datetime.now(UTC).isoformat()
        self._reassess_drop_actions.clear()
        projected_updates = self._project_planner_updates(planner_updates)
        projected_question_key_map = self._project_question_key_map(question_key_map)
        stale_canonical_keys, stale_question_reasons = self._collect_redundant_keys(
            projected_updates,
            projected_question_key_map,
        )
        stale_question_ids: set[str] = set()

        def _format_reassess_reason(
            base_reason: str,
            canonical_key: str = "",
            reasons: set[str] | None = None,
        ) -> str:
            ordered_reasons = [reason for reason in sorted(reasons) if reason] if reasons else []
            if not ordered_reasons and not canonical_key:
                return base_reason
            parts = [base_reason]
            if canonical_key:
                parts.append(f"canonical_key={canonical_key}")
            if ordered_reasons:
                parts.append("reasons=" + ",".join(ordered_reasons))
            return " | ".join(parts)

        for update in projected_updates:
            stale_question_ids.update(update.affected_question_ids)
            stale_question_ids.update(update.superseded_question_ids)
        trigger = self._build_trigger(projected_updates)
        actions: list[dict[str, Any]] = self._drain_reassess_drop_actions()

        for item in sorted(self._items.values(), key=lambda item: item.question_id):
            if item.status != "OPEN":
                continue

            key_entry = projected_question_key_map.get(item.canonical_key)
            resolved_constraint_ids = list(key_entry.resolved_constraint_ids) if key_entry else []
            related_decision_ids = list(key_entry.related_decision_ids) if key_entry else []
            canonical_reasons = stale_canonical_keys.get(item.canonical_key, set())
            direct_reasons = stale_question_reasons.get(item.question_id, set())

            if resolved_constraint_ids:
                reason = (
                    f"canonical_key {item.canonical_key!r} resolved by planner constraints "
                    f"{resolved_constraint_ids}"
                )
                if self.mark_answered(item.question_id, reason):
                    actions.append(
                        {
                            "question_id": item.question_id,
                            "action": "ANSWERED",
                            "reason": _format_reassess_reason(
                                reason,
                                item.canonical_key,
                                canonical_reasons,
                            ),
                        }
                    )
                continue

            if item.blockers.severity != "HIGH_RISK" and not item.blockers.blocked_slices:
                reason = "all blockers cleared and severity is not HIGH_RISK"
                if self.set_status(item.question_id, "STALE", reason):
                    actions.append(
                        {
                            "question_id": item.question_id,
                            "action": "STALE",
                            "reason": _format_reassess_reason(
                                reason,
                                item.canonical_key,
                            ),
                        }
                    )
                continue

            if item.canonical_key in stale_canonical_keys:
                reason = "canonical_key marked obsolete/relevant-change by planner update"
                if self.set_status(item.question_id, "SUPERSEDED", reason):
                    actions.append(
                        {
                            "question_id": item.question_id,
                            "action": "SUPERSEDED",
                            "reason": _format_reassess_reason(
                                reason,
                                item.canonical_key,
                                canonical_reasons,
                            ),
                        }
                    )
                continue

            if item.question_id in stale_question_reasons or item.question_id in stale_question_ids:
                reason = "question marked obsolete/replacement-needed by planner update"
                if self.set_status(item.question_id, "SUPERSEDED", reason):
                    actions.append(
                        {
                            "question_id": item.question_id,
                            "action": "SUPERSEDED",
                            "reason": _format_reassess_reason(
                                reason,
                                item.canonical_key,
                                direct_reasons,
                            ),
                        }
                    )
                continue

            if related_decision_ids:
                reason = (
                    f"question {item.question_id} stale after planner decision(s): "
                    f"{related_decision_ids}"
                )
                if self.set_status(item.question_id, "STALE", reason):
                    actions.append(
                        {
                            "question_id": item.question_id,
                            "action": "STALE",
                            "reason": _format_reassess_reason(reason, item.canonical_key),
                        }
                    )
                continue

            actions.append(
                {
                    "question_id": item.question_id,
                    "action": "KEEP",
                    "reason": "no mechanical match",
                }
            )

        return {
            "version": 1,
            "run_id": run_id,
            "session_id": session_id,
            "trigger": trigger,
            "created_at": created_at,
            "actions": actions,
        }

    def _set_status(self, item: QuestionItem, new_status: str, reason: str = "") -> bool:
        if new_status not in _VALID_STATUSES:
            raise QueueValidationError(f"Invalid status transition target {new_status!r}")
        if item.status == new_status:
            return False
        if item.status != "OPEN":
            logger.debug(
                "Ignoring status transition for %s: %s -> %s",
                item.question_id,
                item.status,
                new_status,
            )
            return False
        item.status = new_status
        self._touch(item, reason)
        return True

    def set_status(self, question_id: str, new_status: str, reason: str = "") -> bool:
        item = self._items.get(question_id)
        if item is None:
            logger.warning("set_status: question_id %s not found", question_id)
            return False
        return self._set_status(item, new_status, reason)

    # TODO [R2-2.4]: Implement dedup(new_item) → QuestionItem | None
    #   - Tier 1: same canonical_key → merge origins/blockers, keep best prompt
    #   - Tier 2: same decision_requirement_id → merge
    #   - Tier 3: semantic LLM match among same taxonomy_type + scope_kind
    #   - Returns existing item if duplicate, None if unique
    def dedup(self, new_item: QuestionItem) -> QuestionItem | None:
        """Check if new_item duplicates an existing question."""
        if new_item.canonical_key:
            for existing in self._items.values():
                if existing.canonical_key == new_item.canonical_key:
                    self._merge_into(existing, new_item)
                    return existing

        new_dr_ids = set(
            _coerce_id_list(
                new_item.system_binding.get("decision_requirement_ids", []),
                "system_binding.decision_requirement_ids",
                allow_scalar=True,
            )
        )
        if new_dr_ids:
            for existing in self._items.values():
                existing_dr_ids = set(
                    _coerce_id_list(
                        existing.system_binding.get("decision_requirement_ids", []),
                        "system_binding.decision_requirement_ids",
                        allow_scalar=True,
                    )
                )
                if existing_dr_ids and new_dr_ids & existing_dr_ids:
                    self._merge_into(existing, new_item)
                    return existing

        return None

    @staticmethod
    def _merge_into(existing: QuestionItem, new_item: QuestionItem) -> None:
        """Merge origins and blockers from new_item into existing."""
        existing_trace_ids = {o.trace_id for o in existing.origins if o.trace_id}
        for origin in new_item.origins:
            if origin.trace_id and origin.trace_id in existing_trace_ids:
                continue
            existing.origins.append(origin)
        for attr in ("blocked_slices", "blocked_layers", "blocked_steps"):
            existing_set = set(getattr(existing.blockers, attr))
            new_set = set(getattr(new_item.blockers, attr))
            setattr(existing.blockers, attr, sorted(existing_set | new_set))
        existing.timestamps["updated_at"] = datetime.now(UTC).isoformat()

    # TODO [R2-2.6]: Implement mark_stale() — staleness sweep
    #   - STALE if no blocked slices + not HIGH_RISK
    #   - STALE if superseded by problem redefinition
    #   - STALE if Planner recorded constraint/decision making it irrelevant
    def mark_stale(
        self,
        question_ids: set[str] | None = None,
        canonical_keys: set[str] | None = None,
    ) -> list[str]:
        """Mark stale questions and return their IDs."""
        stale_ids: list[str] = []
        ids: set[str] = set()
        for raw_id in question_ids or set():
            for item_id in _coerce_id_list(raw_id, "question_ids", allow_scalar=True):
                ids.add(item_id)

        keys: set[str] = set()
        for raw_key in canonical_keys or set():
            for key in _coerce_id_list(raw_key, "canonical_keys", allow_scalar=True):
                keys.add(key)

        for item in sorted(self._items.values(), key=lambda item: item.question_id):
            if item.status != "OPEN":
                continue
            if (
                item.question_id in ids
                or item.canonical_key in keys
                or (not item.blockers.blocked_slices and item.blockers.severity != "HIGH_RISK")
            ):
                if item.question_id in ids:
                    reason = "question marked stale by explicit reassess input"
                elif item.canonical_key in keys:
                    reason = "canonical key marked stale by planner update"
                else:
                    reason = "all blockers cleared and severity is not HIGH_RISK"
                if self._set_status(item, "STALE", reason):
                    stale_ids.append(item.question_id)
        return stale_ids

    # TODO [R2-2.1]: Implement mark_answered(question_id, planner_constraint_ids)
    def mark_answered(self, question_id: str, reason: str = "") -> bool:
        """Mark a question as ANSWERED."""
        item = self._items.get(question_id)
        if item is None:
            logger.warning("mark_answered: question_id %s not found", question_id)
            return False
        return self._set_status(item, "ANSWERED", reason)

    def state_ids(self) -> dict[str, list[str]]:
        open_ids = [it.question_id for it in self._items.values() if it.status == "OPEN"]
        closed_ids = [
            it.question_id
            for it in self._items.values()
            if it.status in {"ANSWERED", "SUPERSEDED", "DISMISSED", "UNASKABLE"}
        ]
        stale_ids = [it.question_id for it in self._items.values() if it.status == "STALE"]
        return {
            "open_ids": sorted(open_ids),
            "closed_ids": sorted(closed_ids),
            "stale_ids": sorted(stale_ids),
        }

    def get_open_items(self) -> list[QuestionItem]:
        """Return all OPEN items sorted by deterministic priority."""
        open_items, _ = self._rank_open_items()
        return open_items

    def get_item(self, question_id: str) -> QuestionItem | None:
        """Get a question by ID."""
        return self._items.get(question_id)

    # TODO [R2-2.1]: Implement save(run_dir) → writes question_queue.json
    def save(self, run_dir: Path) -> Path:
        """Persist queue snapshot."""
        out_dir = _question_queue_snapshot_dir(run_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "question_queue.json"
        data = [
            item.to_dict()
            for item in sorted(self._items.values(), key=lambda item: item.question_id)
        ]
        payload = json.dumps(data, indent=2, sort_keys=True, separators=(",", ": "))
        out_path.write_text(payload, encoding="utf-8")

        history_dir = _question_queue_history_dir(run_dir)
        history_dir.mkdir(parents=True, exist_ok=True)
        snapshot_suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_path = (
            history_dir / f"question_queue.{snapshot_suffix}.{uuid.uuid4().hex[:8]}.json"
        )
        snapshot_path.write_text(payload, encoding="utf-8")

        history_snapshots = sorted(history_dir.glob(_QUEUE_HISTORY_SNAPSHOT_GLOB))
        overflow_count = len(history_snapshots) - _QUEUE_HISTORY_RETENTION_LIMIT
        if overflow_count > 0:
            pruned = history_snapshots[:overflow_count]
            prune_record = {
                "pruned_at": datetime.now(UTC).isoformat(),
                "retention_limit": _QUEUE_HISTORY_RETENTION_LIMIT,
                "deleted_snapshots": [path.name for path in pruned],
            }
            prune_log_path = history_dir / _QUEUE_HISTORY_PRUNE_LOG
            with prune_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(prune_record, sort_keys=True))
                handle.write("\n")
            for stale_path in pruned:
                stale_path.unlink(missing_ok=True)

        return out_path

    # TODO [R2-2.1]: Implement load(run_dir) classmethod
    @classmethod
    def load(cls, run_dir: Path) -> QuestionQueue:
        """Load queue from snapshot."""
        queue = cls()
        path = _question_queue_snapshot_dir(run_dir) / "question_queue.json"
        if not path.exists():
            return queue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise QueueValidationError("question_queue.json must be a list")
        ordered = sorted(
            raw,
            key=lambda item: item.get("question_id", "") if isinstance(item, dict) else "",
        )
        for item_payload in ordered:
            item = QuestionItem.from_dict(item_payload)
            item.validate()
            if item.quality_gate.status != "PASS":
                raise QueueValidationError(
                    f"question_queue.json contains non-PASS item {item.question_id!r}; "
                    "only PASS quality gate items may enter the active queue"
                )
            if item.question_id in queue._items:
                raise QueueValidationError(
                    f"question_queue.json contains duplicate question_id {item.question_id!r}"
                )
            queue._items[item.question_id] = item
        return queue
