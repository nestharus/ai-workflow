"""UserQuestionSignal — file-backed signal store for user-facing questions.

Per response2.md Section 3: Internal agents never talk to the user directly.
They emit UserQuestionSignal events that request user input. The final
user prompt is produced by the Intent Agent and must pass the quality gate.

Storage: .pdd_runs/<run_id>/coordination/user_questions.jsonl (append-only)

Emitters:
    - Planner (AuthorityDecider marks human_required)
    - UnderSpecManager (ambiguity not auto-resolvable)
    - PromotionLoop / PddLifecycle (checkpoint signals)
    - Slice agents (rare, user-domain ambiguity only)
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Authoritative enum per response2.md Section 3.1
VALID_SOURCE_KINDS = frozenset(
    {
        "PLANNER",
        "UNDER_SPEC",
        "PROMOTION_LOOP",
        "PDD_LIFECYCLE",
        "INTENT_AGENT",
        "SLICE_AGENT",
    }
)


def _validate_source_kind(
    source_kind: str,
    *,
    uq_id: str,
    source_payload: dict[str, Any],
) -> None:
    """Enforce authoritative source-kind values with traceable error context."""
    if source_kind and source_kind not in VALID_SOURCE_KINDS:
        raise ValueError(
            "Signal has invalid source.kind: "
            f"{source_kind!r}; uq_id={uq_id!r}; source={source_payload!r}; "
            f"expected one of {sorted(VALID_SOURCE_KINDS)}"
        )


@dataclass
class SignalSource:
    """Source of a UserQuestionSignal."""

    kind: str = ""  # PLANNER | UNDER_SPEC | PROMOTION_LOOP | PDD_LIFECYCLE | SLICE_AGENT
    trace_id: str = ""
    slice_id: str = ""
    layer: str = ""
    signal_id: str = ""


@dataclass
class SignalBlocking:
    """Blocking context for the signal."""

    severity: str = "INFO"  # BLOCKING | HIGH_RISK | MEDIUM_RISK | INFO
    blocked_slices: list[str] = field(default_factory=list)


@dataclass
class SpecRefItem:
    """Reference to a spec text location."""

    spec_text: str = ""
    source_file: str = ""
    source_line_hint: int = 0


@dataclass
class CodeRefItem:
    """Reference to a code location."""

    file: str = ""
    symbol: str = ""
    line: int = 0


@dataclass
class SignalQuestion:
    """Internal draft question (may be technical — Intent Agent rewrites)."""

    text: str = ""
    taxonomy_hint: str = "UNKNOWN"  # May include internal-only types
    canonical_key_hint: str = ""
    answer_spec_hint: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalContext:
    """Context for a UserQuestionSignal."""

    blocking: SignalBlocking = field(default_factory=SignalBlocking)
    spec_refs: list[SpecRefItem] = field(default_factory=list)
    code_refs: list[CodeRefItem] = field(default_factory=list)


@dataclass
class UserQuestionSignal:
    """Signal requesting user input via the Intent Agent queue.

    Per response2.md Section 3.1 JSON schema. Internal agents emit these;
    the Intent Agent ingests, rewrites into user-facing language, and
    enforces the quality gate before presenting to the user.
    """

    uq_version: int = 1
    uq_id: str = ""
    run_id: str = ""
    created_at: str = ""
    source: SignalSource = field(default_factory=SignalSource)
    question: SignalQuestion = field(default_factory=SignalQuestion)
    context: SignalContext = field(default_factory=SignalContext)
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.uq_id:
            self.uq_id = f"uq_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        _validate_source_kind(
            self.source.kind,
            uq_id=self.uq_id,
            source_payload={
                "kind": self.source.kind,
                "trace_id": self.source.trace_id,
                "slice_id": self.source.slice_id,
                "layer": self.source.layer,
                "signal_id": self.source.signal_id,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uq_version": self.uq_version,
            "uq_id": self.uq_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "source": {
                "kind": self.source.kind,
                "trace_id": self.source.trace_id,
                "slice_id": self.source.slice_id,
                "layer": self.source.layer,
                "signal_id": self.source.signal_id,
            },
            "question": {
                "text": self.question.text,
                "taxonomy_hint": self.question.taxonomy_hint,
                "canonical_key_hint": self.question.canonical_key_hint,
                "answer_spec_hint": self.question.answer_spec_hint,
            },
            "context": {
                "blocking": {
                    "severity": self.context.blocking.severity,
                    "blocked_slices": self.context.blocking.blocked_slices,
                },
                "spec_refs": [
                    {
                        "spec_text": r.spec_text,
                        "source_file": r.source_file,
                        "source_line_hint": r.source_line_hint,
                    }
                    for r in self.context.spec_refs
                ],
                "code_refs": [
                    {
                        "file": r.file,
                        "symbol": r.symbol,
                        "line": r.line,
                    }
                    for r in self.context.code_refs
                ],
            },
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UserQuestionSignal:
        if not isinstance(d, dict):
            raise TypeError("Signal record must be a JSON object")

        uq_id = d.get("uq_id")
        if not isinstance(uq_id, str) or not uq_id.strip():
            raise TypeError("Signal record missing required field: uq_id")

        src = d.get("source")
        if not isinstance(src, dict):
            raise TypeError("Signal record missing required object: source")
        source_kind = src.get("kind")
        if not isinstance(source_kind, str) or not source_kind.strip():
            raise TypeError("Signal record missing required field: source.kind")
        _validate_source_kind(
            source_kind,
            uq_id=uq_id,
            source_payload=src,
        )
        if "trace_id" not in src:
            raise TypeError("Signal record missing required field: source.trace_id")
        if not isinstance(src["trace_id"], str):
            raise TypeError("Signal record has invalid source.trace_id")
        if "slice_id" not in src:
            raise TypeError("Signal record missing required field: source.slice_id")
        if not isinstance(src["slice_id"], str):
            raise TypeError("Signal record has invalid source.slice_id")
        if "layer" not in src:
            raise TypeError("Signal record missing required field: source.layer")
        if not isinstance(src["layer"], str):
            raise TypeError("Signal record has invalid source.layer")
        if "signal_id" not in src:
            raise TypeError("Signal record missing required field: source.signal_id")
        if not isinstance(src["signal_id"], str):
            raise TypeError("Signal record has invalid source.signal_id")
        source = SignalSource(
            kind=source_kind,
            trace_id=src["trace_id"],
            slice_id=src["slice_id"],
            layer=src["layer"],
            signal_id=src["signal_id"],
        )

        q = d.get("question")
        if not isinstance(q, dict):
            raise TypeError("Signal record missing required object: question")
        question_text = q.get("text")
        if not isinstance(question_text, str) or not question_text.strip():
            raise TypeError("Signal record missing required field: question.text")
        if "taxonomy_hint" not in q:
            raise TypeError("Signal record missing required field: question.taxonomy_hint")
        if not isinstance(q["taxonomy_hint"], str):
            raise TypeError("Signal record has invalid question.taxonomy_hint")
        if "canonical_key_hint" not in q:
            raise TypeError("Signal record missing required field: question.canonical_key_hint")
        if not isinstance(q["canonical_key_hint"], str):
            raise TypeError("Signal record has invalid question.canonical_key_hint")
        if "answer_spec_hint" not in q:
            raise TypeError("Signal record missing required field: question.answer_spec_hint")
        answer_spec_hint = q["answer_spec_hint"]
        if not isinstance(answer_spec_hint, dict):
            raise TypeError("Signal record has invalid question.answer_spec_hint")
        question = SignalQuestion(
            text=question_text,
            taxonomy_hint=q["taxonomy_hint"],
            canonical_key_hint=q["canonical_key_hint"],
            answer_spec_hint=answer_spec_hint,
        )

        if "context" not in d:
            raise TypeError("Signal record missing required object: context")
        ctx = d["context"]
        if not isinstance(ctx, dict):
            raise TypeError("Signal record has invalid context")
        if "blocking" not in ctx:
            raise TypeError("Signal record missing required object: context.blocking")
        blk = ctx["blocking"]
        if not isinstance(blk, dict):
            raise TypeError("Signal record has invalid context.blocking")
        if "blocked_slices" not in blk:
            raise TypeError("Signal record missing required field: context.blocking.blocked_slices")
        blocked_slices = blk["blocked_slices"]
        if not isinstance(blocked_slices, list) or any(
            not isinstance(item, str) for item in blocked_slices
        ):
            raise TypeError("Signal record has invalid context.blocking.blocked_slices")
        if "severity" not in blk:
            raise TypeError("Signal record missing required field: context.blocking.severity")
        if not isinstance(blk["severity"], str):
            raise TypeError("Signal record has invalid context.blocking.severity")
        blocking = SignalBlocking(
            severity=blk["severity"],
            blocked_slices=blocked_slices,
        )

        if "spec_refs" not in ctx:
            raise TypeError("Signal record missing required field: context.spec_refs")
        raw_spec_refs = ctx["spec_refs"]
        if not isinstance(raw_spec_refs, list):
            raise TypeError("Signal record has invalid context.spec_refs")
        spec_refs: list[SpecRefItem] = []
        for r in raw_spec_refs:
            if not isinstance(r, dict):
                raise TypeError("Signal record has invalid spec_refs entry")
            if "source_line_hint" not in r:
                raise TypeError("Signal record missing required field: spec_refs.source_line_hint")
            source_line_hint = r["source_line_hint"]
            if not isinstance(source_line_hint, int):
                raise TypeError("Signal record has invalid spec_refs.source_line_hint")
            if "spec_text" not in r:
                raise TypeError("Signal record missing required field: spec_refs.spec_text")
            if not isinstance(r["spec_text"], str):
                raise TypeError("Signal record has invalid spec_refs.spec_text")
            if "source_file" not in r:
                raise TypeError("Signal record missing required field: spec_refs.source_file")
            if not isinstance(r["source_file"], str):
                raise TypeError("Signal record has invalid spec_refs.source_file")
            spec_refs.append(
                SpecRefItem(
                    spec_text=r["spec_text"],
                    source_file=r["source_file"],
                    source_line_hint=source_line_hint,
                )
            )

        if "code_refs" not in ctx:
            raise TypeError("Signal record missing required field: context.code_refs")
        raw_code_refs = ctx["code_refs"]
        if not isinstance(raw_code_refs, list):
            raise TypeError("Signal record has invalid context.code_refs")
        code_refs: list[CodeRefItem] = []
        for r in raw_code_refs:
            if not isinstance(r, dict):
                raise TypeError("Signal record has invalid code_refs entry")
            if "line" not in r:
                raise TypeError("Signal record missing required field: code_refs.line")
            line = r["line"]
            if not isinstance(line, int):
                raise TypeError("Signal record has invalid code_refs.line")
            if "file" not in r:
                raise TypeError("Signal record missing required field: code_refs.file")
            if not isinstance(r["file"], str):
                raise TypeError("Signal record has invalid code_refs.file")
            if "symbol" not in r:
                raise TypeError("Signal record missing required field: code_refs.symbol")
            if not isinstance(r["symbol"], str):
                raise TypeError("Signal record has invalid code_refs.symbol")
            code_refs.append(
                CodeRefItem(
                    file=r["file"],
                    symbol=r["symbol"],
                    line=line,
                )
            )

        context = SignalContext(
            blocking=blocking,
            spec_refs=spec_refs,
            code_refs=code_refs,
        )
        uq_version = d.get("uq_version", 1)
        if not isinstance(uq_version, int):
            raise TypeError("Signal record has invalid uq_version")
        run_id = d.get("run_id", "")
        if not isinstance(run_id, str):
            raise TypeError("Signal record has invalid run_id")
        created_at = d.get("created_at", "")
        if not isinstance(created_at, str):
            raise TypeError("Signal record has invalid created_at")
        payload = d.get("payload", {})
        if not isinstance(payload, dict):
            raise TypeError("Signal record has invalid payload")

        sig = cls.__new__(cls)
        sig.uq_version = uq_version
        sig.uq_id = uq_id
        sig.run_id = run_id
        sig.created_at = created_at
        sig.source = source
        sig.question = question
        sig.context = context
        sig.payload = payload
        return sig


@dataclass
class RejectedSignalLine:
    """Explicit accounting for an unparseable signal store line."""

    line_number: int
    raw_line: str
    line_sha256: str
    reason: str
    recorded_at: str


@dataclass
class UserQuestionSignalReadResult:
    """Derived view of the signal store with full input accounting."""

    signals: list[UserQuestionSignal] = field(default_factory=list)
    rejections: list[RejectedSignalLine] = field(default_factory=list)


@dataclass
class PlannerUpdateReadResult:
    """Derived view of planner updates with full input accounting."""

    events: list[dict[str, Any]] = field(default_factory=list)
    rejections: list[RejectedSignalLine] = field(default_factory=list)


class UserQuestionSignalStore:
    """Append-only JSONL store for UserQuestionSignal events."""

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "coordination" / "user_questions.jsonl"
        self._rejections_path = run_dir / "coordination" / "user_questions.rejections.jsonl"

    def write(self, signal: UserQuestionSignal) -> None:
        """Append a signal to the store."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    signal.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

    def read_since(self, watermark: str) -> list[UserQuestionSignal]:
        """Read signals since the given watermark.

        *watermark* is the ``uq_id`` of the last processed signal.
        All signals appearing **after** that line are returned.
        If *watermark* is empty, all signals are returned.
        """
        all_signals = self.read_all().signals
        if not watermark:
            return all_signals
        seen_watermark = False
        past_watermark = False
        result: list[UserQuestionSignal] = []
        for sig in all_signals:
            if past_watermark:
                result.append(sig)
            elif sig.uq_id == watermark:
                seen_watermark = True
                past_watermark = True
        if not seen_watermark:
            logger.warning(
                "UserQuestionSignalStore watermark %s was not found; replaying all signals",
                watermark,
            )
            return all_signals
        return result

    def read_all(self) -> UserQuestionSignalReadResult:
        """Read all signals and malformed-line rejections from the store."""
        if not self._path.exists():
            return UserQuestionSignalReadResult()
        read_result = UserQuestionSignalReadResult()
        for line_number, raw_line in enumerate(
            self._path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            line = raw_line.strip()
            if not line:
                continue
            try:
                read_result.signals.append(UserQuestionSignal.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                rejection_record = RejectedSignalLine(
                    line_number=line_number,
                    raw_line=raw_line,
                    line_sha256=hashlib.sha256(raw_line.encode("utf-8")).hexdigest(),
                    reason=str(exc),
                    recorded_at=datetime.now(UTC).isoformat(),
                )
                read_result.rejections.append(rejection_record)
                self._record_rejected_line(rejection_record)
                logger.warning(
                    "Rejected malformed signal line %s; recorded in %s: %s",
                    line_number,
                    self._rejections_path,
                    exc,
                )
        return read_result

    def _record_rejected_line(self, rejection_record: RejectedSignalLine) -> None:
        self._rejections_path.parent.mkdir(parents=True, exist_ok=True)
        with self._rejections_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "line_number": rejection_record.line_number,
                        "raw_line": rejection_record.raw_line,
                        "line_sha256": rejection_record.line_sha256,
                        "reason": rejection_record.reason,
                        "recorded_at": rejection_record.recorded_at,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


class PlannerUpdateStore:
    """Append-only JSONL store for Planner constraint/decision update signals."""

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "coordination" / "planner_updates.jsonl"
        self._rejections_path = run_dir / "coordination" / "planner_updates.rejections.jsonl"

    def write(self, event: dict[str, Any]) -> None:
        """Append a planner update event."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

    def read_since(self, watermark: str) -> list[dict[str, Any]]:
        """Read events since the given watermark.

        *watermark* is the ``created_at`` timestamp of the last processed
        event.  All events whose ``created_at`` is strictly greater than
        *watermark* are returned.  If *watermark* is empty, all events are
        returned.
        """
        events = self.read_all().events
        if not watermark:
            return events
        return [e for e in events if e.get("created_at", "") > watermark]

    def read_all(self) -> PlannerUpdateReadResult:
        """Read all planner updates and malformed-line rejections from the store."""
        if not self._path.exists():
            return PlannerUpdateReadResult()
        read_result = PlannerUpdateReadResult()
        for line_number, raw_line in enumerate(
            self._path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed_event = json.loads(line)
                if not isinstance(parsed_event, dict):
                    raise TypeError("Planner update record must be a JSON object")
                read_result.events.append(parsed_event)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                rejection_record = RejectedSignalLine(
                    line_number=line_number,
                    raw_line=raw_line,
                    line_sha256=hashlib.sha256(raw_line.encode("utf-8")).hexdigest(),
                    reason=str(exc),
                    recorded_at=datetime.now(UTC).isoformat(),
                )
                read_result.rejections.append(rejection_record)
                self._record_rejected_line(rejection_record)
                logger.warning(
                    "Rejected malformed planner event line %s; recorded in %s: %s",
                    line_number,
                    self._rejections_path,
                    exc,
                )
        return read_result

    def _record_rejected_line(self, rejection_record: RejectedSignalLine) -> None:
        self._rejections_path.parent.mkdir(parents=True, exist_ok=True)
        with self._rejections_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "line_number": rejection_record.line_number,
                        "raw_line": rejection_record.raw_line,
                        "line_sha256": rejection_record.line_sha256,
                        "reason": rejection_record.reason,
                        "recorded_at": rejection_record.recorded_at,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
