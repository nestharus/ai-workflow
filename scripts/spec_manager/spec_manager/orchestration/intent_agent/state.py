"""Intent Agent session state — user-interface state, NOT constraint authority.

Per response2.md Section 1.3: The Intent Agent state model holds user-facing
framing metadata and queue references. It must NOT own constraint objects,
tradeoff positions, or planning decisions.

Persistent artifacts:
    .pdd_runs/<run_id>/intent/session_state.json  (snapshot)
    .pdd_runs/<run_id>/intent/events.jsonl         (append-only log)
    .pdd_runs/<run_id>/intent/skeleton/analysis/intent/question_queue.json  (queue snapshot)
    .pdd_runs/<run_id>/intent/answers.jsonl         (raw answers)
    .pdd_runs/<run_id>/intent/answer_translations/<id>.json
    .pdd_runs/<run_id>/intent/skeleton/...
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    scope: dict[str, list[str]] = field(
        default_factory=lambda: {"in": [], "out": []}
    )
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
    question_queue_state: dict[str, Any] = field(default_factory=lambda: {
        "open_ids": [],
        "closed_ids": [],
        "stale_ids": [],
        "open_constraint_question_ids": [],
        "closed_constraint_question_ids": [],
        "open_constraint_dimensions": [],
        "closed_constraint_dimensions": [],
        "unaskable_question_ids": [],
        "skeleton_input_signature": "",
        "last_presented_question_id": "",
        "active_batch_id": "",
    })
    question_key_map: dict[str, QuestionKeyRef] = field(default_factory=dict)
    answer_provenance: list[AnswerProvenance] = field(default_factory=list)
    skeleton_state: SkeletonState = field(default_factory=SkeletonState)
    watermarks: Watermarks = field(default_factory=Watermarks)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
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
                    k: list(v)
                    for k, v in self.concept_map.normalized_terms.items()
                },
                "user_introduced_terms": list(
                    self.concept_map.user_introduced_terms
                ),
            },
        "question_queue_state": dict(self.question_queue_state),
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
                    "answer_id": ap.answer_id,
                    "question_id": ap.question_id,
                    "raw_text": ap.raw_text,
                    "created_at": ap.created_at,
                    "answer_translation_ref": ap.answer_translation_ref,
                    "planner_ingest_trace_id": ap.planner_ingest_trace_id,
                }
                for ap in self.answer_provenance
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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IntentSessionState:
        """Deserialize from a plain dict (e.g. parsed JSON).

        Validates version compatibility, required fields, and phase values.
        Logs warnings for non-conformant artifacts but still deserializes
        to support forward compatibility.
        """
        # Version validation
        version = d.get("version", 1)
        if version != 1:
            logger.warning(
                "IntentSessionState version %d is not supported (expected 1); "
                "deserialization may be incomplete",
                version,
            )

        # Required field validation
        _required = ("session_id", "problem_frame", "watermarks")
        for field_name in _required:
            if field_name not in d:
                logger.warning(
                    "IntentSessionState missing required field %r", field_name,
                )

        # Phase validation
        _valid_phases = ("INTAKE", "EXECUTION")
        raw_phase = d.get("phase", "INTAKE")
        if raw_phase not in _valid_phases:
            logger.warning(
                "IntentSessionState has unrecognized phase %r; defaulting to INTAKE",
                raw_phase,
            )

        oi_raw = d.get("original_intent", {})
        original_intent = OriginalIntent(
            user_statement=oi_raw.get("user_statement", ""),
            captured_at=oi_raw.get("captured_at", ""),
        )

        pf_raw = d.get("problem_frame", {})
        # Support both nested scope: {in, out} and legacy flat scope_in/scope_out
        scope_raw = pf_raw.get("scope", {})
        if isinstance(scope_raw, dict):
            scope_dict = {
                "in": scope_raw.get("in", []),
                "out": scope_raw.get("out", []),
            }
        else:
            # Legacy flat format fallback — emit deprecation warning
            logger.warning(
                "ProblemFrame uses deprecated flat scope_in/scope_out format; "
                "migrate to nested scope: {in: [], out: []}",
            )
            scope_dict = {
                "in": pf_raw.get("scope_in", []),
                "out": pf_raw.get("scope_out", []),
            }
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
                for fa in pf_raw.get("frame_assumptions", [])
            ],
        )

        cm_raw = d.get("concept_map", {})
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
        question_key_map = {
            k: QuestionKeyRef(
                canonical_key=v.get("canonical_key", ""),
                planner_constraint_ids=v.get("planner_constraint_ids", []),
                planner_decision_ids=v.get("planner_decision_ids", []),
            )
            for k, v in qkm_raw.items()
        }

        ap_raw = d.get("answer_provenance", [])
        answer_provenance = [
            AnswerProvenance(
                answer_id=ap.get("answer_id", ""),
                question_id=ap.get("question_id", ""),
                raw_text=ap.get("raw_text", ""),
                created_at=ap.get("created_at", ""),
                answer_translation_ref=ap.get("answer_translation_ref", ""),
                planner_ingest_trace_id=ap.get("planner_ingest_trace_id", ""),
            )
            for ap in ap_raw
        ]

        ss_raw = d.get("skeleton_state", {})
        skeleton_state = SkeletonState(
            revision=ss_raw.get("revision", 0),
            structure_kind=ss_raw.get("structure_kind", "PRE_DECOMPOSITION"),
            artifact_paths=ss_raw.get("artifact_paths", []),
            last_generated_at=ss_raw.get("last_generated_at", ""),
        )

        wm_raw = d.get("watermarks", {})
        watermarks = Watermarks(
            user_question_signal_watermark=wm_raw.get(
                "user_question_signal_watermark", ""
            ),
            planner_update_watermark=wm_raw.get(
                "planner_update_watermark", ""
            ),
        )

        validated_phase = raw_phase if raw_phase in _valid_phases else "INTAKE"

        return cls(
            version=d.get("version", 1),
            run_id=d.get("run_id", ""),
            session_id=d.get("session_id", ""),
            phase=validated_phase,
            original_intent=original_intent,
            problem_frame=problem_frame,
            concept_map=concept_map,
            question_queue_state=d.get("question_queue_state", {
                "open_ids": [],
                "closed_ids": [],
                "stale_ids": [],
                "open_constraint_question_ids": [],
                "closed_constraint_question_ids": [],
                "open_constraint_dimensions": [],
                "closed_constraint_dimensions": [],
                "unaskable_question_ids": [],
                "skeleton_input_signature": "",
                "last_presented_question_id": "",
                "active_batch_id": "",
            }),
            question_key_map=question_key_map,
            answer_provenance=answer_provenance,
            skeleton_state=skeleton_state,
            watermarks=watermarks,
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
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# IntentEventLog — append-only JSONL event logger
# ---------------------------------------------------------------------------

VALID_EVENT_TYPES = frozenset({
    "user_message",
    "signal_received",
    "signal_ingested",
    "question_enqueued",
    "question_presented",
    "quality_check",
    "question_unaskable",
    "answer_recorded",
    "translation_produced",
    "planner_update_received",
    "queue_reassess",
    "skeleton_updated",
})


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
                f"Invalid event_type {event_type!r}. "
                f"Must be one of {sorted(VALID_EVENT_TYPES)}"
            )
        event: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    logger.debug("Saved answer %s to %s", answer.answer_id, path)
    return path


def load_answers(run_dir: Path) -> list[AnswerProvenance]:
    """Load all AnswerProvenance records from ``answers.jsonl``."""
    path = Path(run_dir) / "intent" / "answers.jsonl"
    if not path.exists():
        return []
    answers: list[AnswerProvenance] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        answers.append(
            AnswerProvenance(
                answer_id=d.get("answer_id", ""),
                question_id=d.get("question_id", ""),
                raw_text=d.get("raw_text", ""),
                created_at=d.get("created_at", ""),
                answer_translation_ref=d.get("answer_translation_ref", ""),
                planner_ingest_trace_id=d.get("planner_ingest_trace_id", ""),
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
