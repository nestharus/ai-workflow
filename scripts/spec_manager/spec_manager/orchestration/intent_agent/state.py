"""Intent Agent session state — user-interface state, NOT constraint authority.

Per response2.md Section 1.3: The Intent Agent state model holds user-facing
framing metadata and queue references. It must NOT own constraint objects,
tradeoff positions, or planning decisions.

Persistent artifacts:
    .pdd_runs/<run_id>/intent/session_state.json  (snapshot)
    .pdd_runs/<run_id>/intent/events.jsonl         (append-only log)
    .pdd_runs/<run_id>/intent/question_queue.json  (queue snapshot)
    .pdd_runs/<run_id>/intent/answers.jsonl         (raw answers)
    .pdd_runs/<run_id>/intent/answer_translations/<id>.json
    .pdd_runs/<run_id>/intent/skeleton/...
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OriginalIntent:
    """Captured user statement at session start."""

    user_statement: str = ""
    captured_at: str = ""


@dataclass
class FrameAssumption:
    """Non-authoritative framing assumption (not a constraint)."""

    text: str = ""
    status: str = "HYPOTHESIS"  # HYPOTHESIS | CONFIRMED | REJECTED
    source: str = "intent_agent"  # user | intent_agent
    created_at: str = ""


@dataclass
class ProblemFrame:
    """User-facing problem restatement and scope."""

    current_restatement: str = ""
    goals: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    scope: dict[str, list[str]] = field(default_factory=lambda: {"in": [], "out": []})
    success_metrics: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    frame_assumptions: list[FrameAssumption] = field(default_factory=list)


@dataclass
class ConceptMapEntry:
    """Mapping between a user term and normalized concepts."""

    maps_to: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ConceptMap:
    """Bidirectional mapping between user language and system concepts."""

    user_terms: dict[str, ConceptMapEntry] = field(default_factory=dict)
    normalized_terms: dict[str, list[str]] = field(default_factory=dict)
    user_introduced_terms: list[str] = field(default_factory=list)


@dataclass
class QuestionKeyRef:
    """Reference from question_id to planner constraint/decision IDs."""

    canonical_key: str = ""
    planner_constraint_ids: list[str] = field(default_factory=list)
    planner_decision_ids: list[str] = field(default_factory=list)


@dataclass
class AnswerProvenance:
    """Record of a raw user answer."""

    answer_id: str = ""
    question_id: str = ""
    raw_text: str = ""
    created_at: str = ""
    answer_translation_ref: str = ""
    planner_ingest_trace_id: str = ""
    _passthrough_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkeletonState:
    """Skeleton revision tracking."""

    revision: int = 0
    structure_kind: str = "PRE_DECOMPOSITION"  # PRE_DECOMPOSITION | PHASE0_LIBRARIES
    artifact_paths: list[str] = field(default_factory=list)
    last_generated_at: str = ""


@dataclass
class Watermarks:
    """Watermarks for observing new signals and planner updates."""

    user_question_signal_watermark: str = ""
    planner_update_watermark: str = ""


def _clone_shallow(value: Any) -> Any:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def _normalize_tradeoff_positions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    positions: list[dict[str, Any]] = []
    for raw_position in value:
        if not isinstance(raw_position, dict):
            continue
        normalized_position: dict[str, Any] = {}
        for raw_key, raw_val in raw_position.items():
            key = str(raw_key).strip()
            if not key:
                continue
            normalized_position[key] = _clone_shallow(raw_val)
        if normalized_position:
            positions.append(normalized_position)
    return positions


@dataclass
class ResumeProgressSummaryProjection:
    """Typed projection for queue resume progress at the intent boundary."""

    planner_watermark: str = ""
    planner_updates_seen: int = 0
    planner_update_types: dict[str, Any] = field(default_factory=dict)
    slice_ids: list[str] = field(default_factory=list)
    slice_status_counts: dict[str, Any] = field(default_factory=dict)
    latest_planner_update_at: str = ""
    reassess_action_counts: dict[str, Any] = field(default_factory=dict)
    reassess_resolved_count: int = 0
    _passthrough_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "planner_watermark": self.planner_watermark,
            "planner_updates_seen": self.planner_updates_seen,
            "planner_update_types": _clone_shallow(self.planner_update_types),
            "slice_ids": _clone_shallow(self.slice_ids),
            "slice_status_counts": _clone_shallow(self.slice_status_counts),
            "latest_planner_update_at": self.latest_planner_update_at,
            "reassess_action_counts": _clone_shallow(self.reassess_action_counts),
            "reassess_resolved_count": self.reassess_resolved_count,
        }
        data.update({key: _clone_shallow(value) for key, value in self._passthrough_fields.items()})
        return data

    @classmethod
    def from_dict(cls, raw: Any) -> ResumeProgressSummaryProjection:
        if not isinstance(raw, dict):
            return cls()

        recognized_keys = {
            "planner_watermark",
            "planner_updates_seen",
            "planner_update_types",
            "slice_ids",
            "slice_status_counts",
            "latest_planner_update_at",
            "reassess_action_counts",
            "reassess_resolved_count",
        }
        projection = cls(
            planner_watermark=raw.get("planner_watermark", ""),
            planner_updates_seen=raw.get("planner_updates_seen", 0),
            planner_update_types=_clone_shallow(raw.get("planner_update_types", {})),
            slice_ids=_clone_shallow(raw.get("slice_ids", [])),
            slice_status_counts=_clone_shallow(raw.get("slice_status_counts", {})),
            latest_planner_update_at=raw.get("latest_planner_update_at", ""),
            reassess_action_counts=_clone_shallow(raw.get("reassess_action_counts", {})),
            reassess_resolved_count=raw.get("reassess_resolved_count", 0),
        )
        projection._passthrough_fields = {
            key: _clone_shallow(value) for key, value in raw.items() if key not in recognized_keys
        }
        return projection


@dataclass
class QuestionQueueStateProjection:
    """Typed projection for queue state crossing orchestration boundaries."""

    open_ids: list[str] = field(default_factory=list)
    closed_ids: list[str] = field(default_factory=list)
    stale_ids: list[str] = field(default_factory=list)
    tradeoff_positions: list[dict[str, Any]] = field(default_factory=list)
    last_presented_question_id: str = ""
    active_batch_id: str = ""
    _passthrough_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "open_ids": _clone_shallow(self.open_ids),
            "closed_ids": _clone_shallow(self.closed_ids),
            "stale_ids": _clone_shallow(self.stale_ids),
            "tradeoff_positions": _normalize_tradeoff_positions(self.tradeoff_positions),
            "last_presented_question_id": self.last_presented_question_id,
            "active_batch_id": self.active_batch_id,
        }
        data.update({key: _clone_shallow(value) for key, value in self._passthrough_fields.items()})
        return data

    @classmethod
    def from_dict(cls, raw: Any) -> QuestionQueueStateProjection:
        if not isinstance(raw, dict):
            return cls()

        recognized_keys = {
            "open_ids",
            "closed_ids",
            "stale_ids",
            "tradeoff_positions",
            "last_presented_question_id",
            "active_batch_id",
        }
        projection = cls(
            open_ids=_clone_shallow(raw.get("open_ids", [])),
            closed_ids=_clone_shallow(raw.get("closed_ids", [])),
            stale_ids=_clone_shallow(raw.get("stale_ids", [])),
            tradeoff_positions=_normalize_tradeoff_positions(raw.get("tradeoff_positions", [])),
            last_presented_question_id=raw.get("last_presented_question_id", ""),
            active_batch_id=raw.get("active_batch_id", ""),
        )
        projection._passthrough_fields = {
            key: _clone_shallow(value) for key, value in raw.items() if key not in recognized_keys
        }
        return projection


def _merge_unrecognized_fields(
    sink: dict[str, Any],
    *,
    context: str,
    raw: Any,
    recognized_keys: set[str],
) -> None:
    if not isinstance(raw, dict):
        return
    unknown = {
        key: _clone_shallow(value) for key, value in raw.items() if key not in recognized_keys
    }
    if not unknown:
        return
    existing = sink.get(context)
    if isinstance(existing, dict):
        existing.update(unknown)
    else:
        sink[context] = unknown
    logger.warning(
        "Captured unrecognized IntentSessionState %s field(s) as unvalidated passthrough: %s",
        context,
        sorted(unknown),
    )


@dataclass
class IntentSessionState:
    """Complete Intent Agent session state.

    This is user-interface state, NOT constraint authority.
    No constraint objects, no tradeoff positions, no planning decisions.
    """

    version: int = 1
    run_id: str = ""
    session_id: str = ""
    phase: str = "INTAKE"  # INTAKE | EXECUTION
    original_intent: OriginalIntent = field(default_factory=OriginalIntent)
    problem_frame: ProblemFrame = field(default_factory=ProblemFrame)
    concept_map: ConceptMap = field(default_factory=ConceptMap)
    question_queue_state: QuestionQueueStateProjection = field(
        default_factory=QuestionQueueStateProjection
    )
    question_key_map: dict[str, QuestionKeyRef] = field(default_factory=dict)
    answer_provenance: list[AnswerProvenance] = field(default_factory=list)
    skeleton_state: SkeletonState = field(default_factory=SkeletonState)
    watermarks: Watermarks = field(default_factory=Watermarks)
    # Unvalidated passthrough for unknown fields discovered during from_dict.
    _unrecognized_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        data = {
            "version": self.version,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "phase": self.phase,
            "original_intent": {
                "user_statement": self.original_intent.user_statement,
                "captured_at": self.original_intent.captured_at,
            },
            "problem_frame": {
                "current_restatement": self.problem_frame.current_restatement,
                "goals": list(self.problem_frame.goals),
                "non_goals": list(self.problem_frame.non_goals),
                "scope": {
                    "in": list(self.problem_frame.scope.get("in", [])),
                    "out": list(self.problem_frame.scope.get("out", [])),
                },
                "success_metrics": list(self.problem_frame.success_metrics),
                "risk_flags": list(self.problem_frame.risk_flags),
                "frame_assumptions": [
                    {
                        "text": fa.text,
                        "status": fa.status,
                        "source": fa.source,
                        "created_at": fa.created_at,
                    }
                    for fa in self.problem_frame.frame_assumptions
                ],
            },
            "concept_map": {
                "user_terms": {
                    k: {"maps_to": list(v.maps_to), "confidence": v.confidence}
                    for k, v in self.concept_map.user_terms.items()
                },
                "normalized_terms": {
                    k: list(v) for k, v in self.concept_map.normalized_terms.items()
                },
                "user_introduced_terms": list(self.concept_map.user_introduced_terms),
            },
            "question_queue_state": self.question_queue_state.to_dict(),
            "question_key_map": {
                k: {
                    "canonical_key": v.canonical_key,
                    "planner_constraint_ids": list(v.planner_constraint_ids),
                    "planner_decision_ids": list(v.planner_decision_ids),
                }
                for k, v in self.question_key_map.items()
            },
            "answer_provenance": [
                {
                    "answer_id": answer.answer_id,
                    "question_id": answer.question_id,
                    "raw_text": answer.raw_text,
                    "created_at": answer.created_at,
                    "answer_translation_ref": answer.answer_translation_ref,
                    "planner_ingest_trace_id": answer.planner_ingest_trace_id,
                    **{
                        key: _clone_shallow(value)
                        for key, value in answer._passthrough_fields.items()
                        if key
                        not in {
                            "answer_id",
                            "question_id",
                            "raw_text",
                            "created_at",
                            "answer_translation_ref",
                            "planner_ingest_trace_id",
                        }
                    },
                }
                for answer in self.answer_provenance
            ],
            "skeleton_state": {
                "revision": self.skeleton_state.revision,
                "structure_kind": self.skeleton_state.structure_kind,
                "artifact_paths": list(self.skeleton_state.artifact_paths),
                "last_generated_at": self.skeleton_state.last_generated_at,
            },
            "watermarks": {
                "user_question_signal_watermark": self.watermarks.user_question_signal_watermark,
                "planner_update_watermark": self.watermarks.planner_update_watermark,
            },
        }
        if self._unrecognized_fields:
            data["_unrecognized_fields"] = {
                key: _clone_shallow(value) for key, value in self._unrecognized_fields.items()
            }
        return data

    @classmethod
    def from_dict(
        cls,
        d: dict[str, Any],
        *,
        source: str | None = None,
    ) -> IntentSessionState:
        """Deserialize from a plain dict (e.g. parsed JSON).

        Validates version compatibility, required fields, and phase values.
        Raises ValueError for unsupported versions and unrecognized phases.
        """
        source_suffix = f" from {source}" if source else ""
        version, raw_phase = cls._validate_from_dict_shape(d, source_suffix=source_suffix)
        canonical = cls._canonicalize_deprecated_from_dict_formats(
            d,
            source_suffix=source_suffix,
        )
        return cls._reconstruct_from_canonical_dict(
            canonical,
            version=version,
            raw_phase=raw_phase,
            source_suffix=source_suffix,
        )

    @staticmethod
    def _validate_from_dict_shape(
        d: dict[str, Any],
        *,
        source_suffix: str,
    ) -> tuple[int, str]:
        # Version validation
        version = d.get("version")
        if not isinstance(version, int):
            raise TypeError(
                "IntentSessionState field 'version' must be an integer "
                f"(got {type(version).__name__}){source_suffix}"
            )
        if version < 1:
            raise ValueError(
                f"IntentSessionState field 'version' must be >= 1 (got {version!r}){source_suffix}"
            )

        # Required-shape validation (authoritative fields only).
        # Missing shape indicates a corrupted/incompatible artifact.
        _required = (
            "version",
            "run_id",
            "session_id",
            "phase",
            "original_intent",
            "problem_frame",
            "concept_map",
            "question_queue_state",
            "question_key_map",
            "answer_provenance",
            "skeleton_state",
            "watermarks",
        )
        missing_fields = [field_name for field_name in _required if field_name not in d]
        if missing_fields:
            raise ValueError(
                f"IntentSessionState missing required field(s) {missing_fields!r}{source_suffix}"
            )
        if not isinstance(d["run_id"], str):
            raise TypeError(
                "IntentSessionState field 'run_id' must be a string "
                f"(got {type(d['run_id']).__name__}){source_suffix}"
            )
        if not isinstance(d["session_id"], str):
            raise TypeError(
                "IntentSessionState field 'session_id' must be a string "
                f"(got {type(d['session_id']).__name__}){source_suffix}"
            )
        if not isinstance(d["phase"], str):
            raise TypeError(
                "IntentSessionState field 'phase' must be a string "
                f"(got {type(d['phase']).__name__}){source_suffix}"
            )
        if not isinstance(d["original_intent"], dict):
            raise TypeError(
                "IntentSessionState field 'original_intent' must be an object "
                f"(got {type(d['original_intent']).__name__}){source_suffix}"
            )
        if not isinstance(d["problem_frame"], dict):
            raise TypeError(
                "IntentSessionState field 'problem_frame' must be an object "
                f"(got {type(d['problem_frame']).__name__}){source_suffix}"
            )
        if not isinstance(d["concept_map"], dict):
            raise TypeError(
                "IntentSessionState field 'concept_map' must be an object "
                f"(got {type(d['concept_map']).__name__}){source_suffix}"
            )
        if not isinstance(d["question_queue_state"], dict):
            raise TypeError(
                "IntentSessionState field 'question_queue_state' must be an object "
                f"(got {type(d['question_queue_state']).__name__}){source_suffix}"
            )
        if not isinstance(d["question_key_map"], dict):
            raise TypeError(
                "IntentSessionState field 'question_key_map' must be an object "
                f"(got {type(d['question_key_map']).__name__}){source_suffix}"
            )
        if not isinstance(d["answer_provenance"], list):
            raise TypeError(
                "IntentSessionState field 'answer_provenance' must be an array "
                f"(got {type(d['answer_provenance']).__name__}){source_suffix}"
            )
        if not isinstance(d["skeleton_state"], dict):
            raise TypeError(
                "IntentSessionState field 'skeleton_state' must be an object "
                f"(got {type(d['skeleton_state']).__name__}){source_suffix}"
            )
        if not isinstance(d["watermarks"], dict):
            raise TypeError(
                "IntentSessionState field 'watermarks' must be an object "
                f"(got {type(d['watermarks']).__name__}){source_suffix}"
            )

        scope_raw = d["problem_frame"].get("scope", {})
        if not isinstance(scope_raw, dict):
            raise TypeError(
                "IntentSessionState field 'problem_frame.scope' must be an object "
                f"(got {type(scope_raw).__name__}){source_suffix}"
            )

        # Phase validation
        _valid_phases = ("INTAKE", "EXECUTION")
        raw_phase = d["phase"]
        if raw_phase not in _valid_phases:
            raise ValueError(
                f"Unrecognized IntentSessionState phase {raw_phase!r} "
                f"(expected one of {_valid_phases}){source_suffix}"
            )

        raw_unrecognized_fields = d.get("_unrecognized_fields")
        if raw_unrecognized_fields is not None and not isinstance(raw_unrecognized_fields, dict):
            raise ValueError(
                "IntentSessionState field '_unrecognized_fields' must be an object "
                f"(got {type(raw_unrecognized_fields).__name__}){source_suffix}"
            )
        return version, raw_phase

    @staticmethod
    def _canonicalize_deprecated_from_dict_formats(
        d: dict[str, Any],
        *,
        source_suffix: str,
    ) -> dict[str, Any]:
        canonical = dict(d)
        canonical_problem_frame = dict(d["problem_frame"])
        if "scope_in" in canonical_problem_frame or "scope_out" in canonical_problem_frame:
            raise ValueError(
                "IntentSessionState field 'problem_frame' uses deprecated "
                "'scope_in'/'scope_out' keys; run the scope migration utility "
                f"to write nested 'scope' before loading{source_suffix}"
            )
        canonical["problem_frame"] = canonical_problem_frame
        return canonical

    @classmethod
    def _reconstruct_from_canonical_dict(
        cls,
        d: dict[str, Any],
        *,
        version: int,
        raw_phase: str,
        source_suffix: str,
    ) -> IntentSessionState:
        unrecognized_fields: dict[str, Any] = {}
        raw_unrecognized_fields = d.get("_unrecognized_fields")
        if isinstance(raw_unrecognized_fields, dict):
            unrecognized_fields.update(
                {key: _clone_shallow(value) for key, value in raw_unrecognized_fields.items()}
            )

        _merge_unrecognized_fields(
            unrecognized_fields,
            context="top_level",
            raw=d,
            recognized_keys={
                "version",
                "run_id",
                "session_id",
                "phase",
                "original_intent",
                "problem_frame",
                "concept_map",
                "question_queue_state",
                "question_key_map",
                "answer_provenance",
                "skeleton_state",
                "watermarks",
                "_unrecognized_fields",
            },
        )

        oi_raw = d.get("original_intent", {})
        _merge_unrecognized_fields(
            unrecognized_fields,
            context="original_intent",
            raw=oi_raw,
            recognized_keys={"user_statement", "captured_at"},
        )
        original_intent = OriginalIntent(
            user_statement=oi_raw.get("user_statement", ""),
            captured_at=oi_raw.get("captured_at", ""),
        )

        pf_raw = d["problem_frame"]
        _merge_unrecognized_fields(
            unrecognized_fields,
            context="problem_frame",
            raw=pf_raw,
            recognized_keys={
                "current_restatement",
                "goals",
                "non_goals",
                "scope",
                "scope_in",
                "scope_out",
                "success_metrics",
                "risk_flags",
                "frame_assumptions",
            },
        )
        scope_raw = pf_raw.get("scope", {})
        _merge_unrecognized_fields(
            unrecognized_fields,
            context="problem_frame.scope",
            raw=scope_raw,
            recognized_keys={"in", "out"},
        )
        scope_dict = {
            "in": scope_raw.get("in", []),
            "out": scope_raw.get("out", []),
        }
        valid_frame_assumption_statuses = {"HYPOTHESIS", "CONFIRMED", "REJECTED"}
        valid_frame_assumption_sources = {"user", "intent_agent"}
        frame_assumptions_raw = pf_raw.get("frame_assumptions", [])
        for index, frame_assumption_raw in enumerate(frame_assumptions_raw):
            _merge_unrecognized_fields(
                unrecognized_fields,
                context=f"problem_frame.frame_assumptions[{index}]",
                raw=frame_assumption_raw,
                recognized_keys={"text", "status", "source", "created_at"},
            )
            status = frame_assumption_raw.get("status", "HYPOTHESIS")
            if status not in valid_frame_assumption_statuses:
                raise ValueError(
                    "IntentSessionState field "
                    f"'problem_frame.frame_assumptions[{index}].status' has "
                    f"unrecognized value {status!r} "
                    f"(expected one of {sorted(valid_frame_assumption_statuses)})"
                    f"{source_suffix}"
                )
            source = frame_assumption_raw.get("source", "intent_agent")
            if source not in valid_frame_assumption_sources:
                raise ValueError(
                    "IntentSessionState field "
                    f"'problem_frame.frame_assumptions[{index}].source' has "
                    f"unrecognized value {source!r} "
                    f"(expected one of {sorted(valid_frame_assumption_sources)})"
                    f"{source_suffix}"
                )
        problem_frame = ProblemFrame(
            current_restatement=pf_raw.get("current_restatement", ""),
            goals=pf_raw.get("goals", []),
            non_goals=pf_raw.get("non_goals", []),
            scope=scope_dict,
            success_metrics=pf_raw.get("success_metrics", []),
            risk_flags=pf_raw.get("risk_flags", []),
            frame_assumptions=[
                FrameAssumption(
                    text=fa.get("text", ""),
                    status=fa.get("status", "HYPOTHESIS"),
                    source=fa.get("source", "intent_agent"),
                    created_at=fa.get("created_at", ""),
                )
                for fa in frame_assumptions_raw
            ],
        )

        cm_raw = d.get("concept_map", {})
        _merge_unrecognized_fields(
            unrecognized_fields,
            context="concept_map",
            raw=cm_raw,
            recognized_keys={"user_terms", "normalized_terms", "user_introduced_terms"},
        )
        for term, entry in cm_raw.get("user_terms", {}).items():
            _merge_unrecognized_fields(
                unrecognized_fields,
                context=f"concept_map.user_terms.{term}",
                raw=entry,
                recognized_keys={"maps_to", "confidence"},
            )
        concept_map = ConceptMap(
            user_terms={
                k: ConceptMapEntry(
                    maps_to=v.get("maps_to", []),
                    confidence=v.get("confidence", 0.0),
                )
                for k, v in cm_raw.get("user_terms", {}).items()
            },
            normalized_terms=cm_raw.get("normalized_terms", {}),
            user_introduced_terms=cm_raw.get("user_introduced_terms", []),
        )

        qkm_raw = d.get("question_key_map", {})
        for question_id, question_key_ref in qkm_raw.items():
            _merge_unrecognized_fields(
                unrecognized_fields,
                context=f"question_key_map.{question_id}",
                raw=question_key_ref,
                recognized_keys={
                    "canonical_key",
                    "planner_constraint_ids",
                    "planner_decision_ids",
                },
            )
        question_key_map = {
            k: QuestionKeyRef(
                canonical_key=v.get("canonical_key", ""),
                planner_constraint_ids=v.get("planner_constraint_ids", []),
                planner_decision_ids=v.get("planner_decision_ids", []),
            )
            for k, v in qkm_raw.items()
        }

        answer_provenance_raw = d.get("answer_provenance", [])
        for index, answer in enumerate(answer_provenance_raw):
            _merge_unrecognized_fields(
                unrecognized_fields,
                context=f"answer_provenance[{index}]",
                raw=answer,
                recognized_keys={
                    "answer_id",
                    "question_id",
                    "raw_text",
                    "created_at",
                    "answer_translation_ref",
                    "planner_ingest_trace_id",
                },
            )
        answer_provenance = [
            AnswerProvenance(
                answer_id=answer.get("answer_id", ""),
                question_id=answer.get("question_id", ""),
                raw_text=answer.get("raw_text", ""),
                created_at=answer.get("created_at", ""),
                answer_translation_ref=answer.get("answer_translation_ref", ""),
                planner_ingest_trace_id=answer.get("planner_ingest_trace_id", ""),
                _passthrough_fields={
                    key: _clone_shallow(value)
                    for key, value in answer.items()
                    if key
                    not in {
                        "answer_id",
                        "question_id",
                        "raw_text",
                        "created_at",
                        "answer_translation_ref",
                        "planner_ingest_trace_id",
                    }
                },
            )
            for answer in answer_provenance_raw
        ]

        ss_raw = d.get("skeleton_state", {})
        _merge_unrecognized_fields(
            unrecognized_fields,
            context="skeleton_state",
            raw=ss_raw,
            recognized_keys={"revision", "structure_kind", "artifact_paths", "last_generated_at"},
        )
        valid_structure_kinds = {"PRE_DECOMPOSITION", "PHASE0_LIBRARIES"}
        raw_structure_kind = ss_raw.get("structure_kind", "PRE_DECOMPOSITION")
        if raw_structure_kind not in valid_structure_kinds:
            raise ValueError(
                "IntentSessionState field 'skeleton_state.structure_kind' has "
                f"unrecognized value {raw_structure_kind!r} "
                f"(expected one of {sorted(valid_structure_kinds)}){source_suffix}"
            )
        skeleton_state = SkeletonState(
            revision=ss_raw.get("revision", 0),
            structure_kind=raw_structure_kind,
            artifact_paths=ss_raw.get("artifact_paths", []),
            last_generated_at=ss_raw.get("last_generated_at", ""),
        )

        wm_raw = d["watermarks"]
        _merge_unrecognized_fields(
            unrecognized_fields,
            context="watermarks",
            raw=wm_raw,
            recognized_keys={"user_question_signal_watermark", "planner_update_watermark"},
        )
        watermarks = Watermarks(
            user_question_signal_watermark=wm_raw.get("user_question_signal_watermark", ""),
            planner_update_watermark=wm_raw.get("planner_update_watermark", ""),
        )

        raw_question_queue_state = d.get("question_queue_state")

        return cls(
            version=version,
            run_id=d.get("run_id", ""),
            session_id=d["session_id"],
            phase=raw_phase,
            original_intent=original_intent,
            problem_frame=problem_frame,
            concept_map=concept_map,
            question_queue_state=QuestionQueueStateProjection.from_dict(raw_question_queue_state),
            question_key_map=question_key_map,
            answer_provenance=answer_provenance,
            skeleton_state=skeleton_state,
            watermarks=watermarks,
            _unrecognized_fields=unrecognized_fields,
        )

    def save(self, run_dir: Path) -> Path:
        """Write session state to run_dir/intent/session_state.json."""
        intent_dir = Path(run_dir) / "intent"
        intent_dir.mkdir(parents=True, exist_ok=True)
        path = intent_dir / "session_state.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, separators=(",", ": ")),
            encoding="utf-8",
        )
        logger.debug("Saved IntentSessionState to %s", path)
        return path

    @classmethod
    def load(cls, run_dir: Path) -> IntentSessionState:
        """Read session state from run_dir/intent/session_state.json."""
        path = Path(run_dir) / "intent" / "session_state.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.debug("Loaded IntentSessionState from %s", path)
        return cls.from_dict(data, source=str(path))


# ---------------------------------------------------------------------------
# IntentEventLog — append-only JSONL event logger
# ---------------------------------------------------------------------------

VALID_EVENT_TYPES = frozenset(
    {
        "user_message",
        "signal_received",
        "signal_ingested",
        "user_redefinition_trigger_detected",
        "redefinition_update_blocked",
        "question_enqueued",
        "question_presented",
        "quality_check",
        "question_unaskable",
        "vague_input_fallback",
        "answer_recorded",
        "translation_produced",
        "planner_update_received",
        "queue_reassess",
        "skeleton_updated",
    }
)


class IntentEventLog:
    """Append-only JSONL event log at ``run_dir/intent/events.jsonl``.

    Each event is a single JSON line with:
        event_id   — UUID4 string
        event_type — one of VALID_EVENT_TYPES
        timestamp  — UTC ISO-8601
        payload    — arbitrary dict
    """

    def __init__(self, run_dir: Path) -> None:
        self._dir = Path(run_dir) / "intent"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "events.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an event and return it."""
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type {event_type!r}. Must be one of {sorted(VALID_EVENT_TYPES)}"
            )
        event: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload or {},
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        logger.debug("Appended %s event to %s", event_type, self._path)
        return event

    def read_all(self) -> list[dict[str, Any]]:
        """Read all events from the log file."""
        if not self._path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events


# ---------------------------------------------------------------------------
# Session persistence helpers
# ---------------------------------------------------------------------------


def _intent_dir(run_dir: Path) -> Path:
    """Return (and ensure) the intent directory under *run_dir*."""
    d = Path(run_dir) / "intent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_answer(run_dir: Path, answer: AnswerProvenance) -> Path:
    """Append a single AnswerProvenance record to ``answers.jsonl``."""
    intent = _intent_dir(run_dir)
    path = intent / "answers.jsonl"
    record = {
        "answer_id": answer.answer_id,
        "question_id": answer.question_id,
        "raw_text": answer.raw_text,
        "created_at": answer.created_at,
        "answer_translation_ref": answer.answer_translation_ref,
        "planner_ingest_trace_id": answer.planner_ingest_trace_id,
    }
    record.update(
        {
            key: _clone_shallow(value)
            for key, value in answer._passthrough_fields.items()
            if key
            not in {
                "answer_id",
                "question_id",
                "raw_text",
                "created_at",
                "answer_translation_ref",
                "planner_ingest_trace_id",
            }
        }
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    logger.debug("Saved answer %s to %s", answer.answer_id, path)
    return path


def load_answers(run_dir: Path) -> list[AnswerProvenance]:
    """Load all AnswerProvenance records from ``answers.jsonl``."""
    path = Path(run_dir) / "intent" / "answers.jsonl"
    if not path.exists():
        return []
    required_keys = {
        "answer_id",
        "question_id",
        "raw_text",
        "created_at",
    }
    optional_keys = {
        "answer_translation_ref",
        "planner_ingest_trace_id",
    }
    recognized_keys = required_keys | optional_keys
    answers: list[AnswerProvenance] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if not isinstance(d, dict):
            raise TypeError(
                f"Invalid answer record at {path}:{line_number}; "
                f"expected object, got {type(d).__name__}"
            )
        passthrough_fields = {
            key: _clone_shallow(value) for key, value in d.items() if key not in recognized_keys
        }
        if passthrough_fields:
            logger.warning(
                "Preserving unmodeled answer record field(s) at %s:%s: %s",
                path,
                line_number,
                sorted(passthrough_fields),
            )
        missing_fields = sorted(key for key in required_keys if key not in d)
        if missing_fields:
            raise ValueError(
                f"Answer record at {path}:{line_number} missing required field(s): {missing_fields}"
            )
        answers.append(
            AnswerProvenance(
                answer_id=d["answer_id"],
                question_id=d["question_id"],
                raw_text=d["raw_text"],
                created_at=d["created_at"],
                answer_translation_ref=d.get("answer_translation_ref", ""),
                planner_ingest_trace_id=d.get("planner_ingest_trace_id", ""),
                _passthrough_fields=passthrough_fields,
            )
        )
    return sorted(
        answers,
        key=lambda item: (item.created_at, item.answer_id, item.question_id),
    )


def save_translation(
    run_dir: Path,
    translation: dict[str, Any],
) -> Path:
    """Write a translation dict to ``answer_translations/<id>.json``.

    The translation dict must contain an ``"id"`` key used as the filename.
    """
    intent = _intent_dir(run_dir)
    trans_dir = intent / "answer_translations"
    trans_dir.mkdir(parents=True, exist_ok=True)
    tid = translation.get("id", str(uuid.uuid4()))
    path = trans_dir / f"{tid}.json"
    path.write_text(
        json.dumps(translation, indent=2, sort_keys=True, separators=(",", ": ")),
        encoding="utf-8",
    )
    logger.debug("Saved translation %s to %s", tid, path)
    return path
